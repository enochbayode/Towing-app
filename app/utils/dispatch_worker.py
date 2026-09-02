# app/utils/dispatch_worker.py
import asyncio
import logging
from uuid import UUID
from sqlmodel import select
from app.db.session import async_session_factory
from app.models.trip import Trip, TripStatus
from app.services.dispatch import find_nearby_drivers
from app.utils.driver_notification import push_trip_to_driver
from app.models.trip import CompanyLedger, LedgerEntryType, PaymentStatus, PaymentMethod
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SEARCH_RINGS = [5.0, 10.0, 15.0] 
WAIT_TIME_SECONDS = 60

async def broadcast_trip_to_drivers(trip_id: str):
    """
    The main matchmaking loop for the Towing app. 
    Expands the search radius if no one accepts.
    """
    async with async_session_factory() as session:
        trip = await session.get(Trip, trip_id)
        
        # Only broadcast if the trip is actively looking for drivers
        if not trip or trip.status != TripStatus.SEARCHING:
            return

        for radius in SEARCH_RINGS:
            logger.info(f"Searching for drivers within {radius}km for Trip {trip_id}")
            
            # 1. Find drivers in this ring
            nearby_drivers = await find_nearby_drivers(
                session=session,
                pickup_lat=trip.pickup_lat,
                pickup_lng=trip.pickup_lng,
                radius_km=radius
            )

            # 2. Ping their mobile apps via FCM
            if nearby_drivers:
                for driver in nearby_drivers:
                    if getattr(driver, "fcm_token", None):
                        logger.info(f"Pinging Driver {driver.id} - Distance: {radius}km")
                        await push_trip_to_driver(
                            fcm_token=driver.fcm_token,
                            trip_id=str(trip.id),
                            pickup_address=trip.pickup_address,
                            amount=str(trip.total_cost) # Show the total cost they will collect at the location
                        )

            # 3. Wait 60 seconds to give them a chance to tap "Accept"
            await asyncio.sleep(WAIT_TIME_SECONDS)

            # 4. Refresh trip from database to see if a driver accepted it
            await session.refresh(trip)
            
            if trip.status == TripStatus.EN_ROUTE:
                logger.info(f"Trip {trip_id} was accepted! Stopping the search broadcast.")
                return 

        # 5. If we get through all rings and no one accepted...
        if trip.status == TripStatus.SEARCHING:
            logger.warning(f"No drivers accepted Trip {trip_id}. Auto-cancelling.")
            
            # Since no payment was taken upfront, we simply cancel the trip.
            trip.status = TripStatus.CANCELLED
            session.add(trip)
            await session.commit()
            
            # TODO: Send FCM Push Notification to the User: "Sorry, all our tow trucks are currently busy. Please try requesting again."


# wait
async def wait_and_auto_complete_trip(trip_id: UUID, session_factory):
    """
    Background Task: Waits 2 minutes post-arrival.
    If the trip is still 'ARRIVED', it forces a CASH completion.
    """
    logger.info(f"Starting 2-minute auto-completion timer for Trip {trip_id}")
    await asyncio.sleep(120)

    async with session_factory() as session:
        trip = await session.get(Trip, trip_id)
        
        # If the webhook or manual click already completed it, this safely does nothing.
        if trip and trip.status == TripStatus.ARRIVED:
            logger.info(f"Timer expired for Trip {trip_id}. Driver forgot to click. Auto-completing as CASH.")
            
            # Force the payment method to CASH
            trip.payment_method = PaymentMethod.CASH
            trip.payment_status = PaymentStatus.DEBT_LOGGED
            trip.status = TripStatus.COMPLETED
            trip.completed_at = datetime.now(timezone.utc)
            
            # Log the debt against the driver/company
            debt_entry = CompanyLedger(
                company_id=trip.company_id,
                driver_id=trip.driver_id,
                trip_id=trip.id,
                entry_type=LedgerEntryType.COMMISSION_DEBT,
                amount=-trip.platform_fee,
                description=f"Auto-completed Commission debt for Cash Trip #{str(trip.id)[:8]}"
            )
            session.add(debt_entry)
            session.add(trip)
            await session.commit()
            
            logger.info(f"Trip {trip.id} auto-completed. Debt logged.")