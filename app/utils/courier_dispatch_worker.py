import logging
from sqlmodel import select
from app.db.session import async_session_factory
from app.models.trip import Trip, TripStatus
from app.services.dispatch import find_nearby_courier_drivers
from app.utils.driver_notification import push_trip_to_driver
from app.models.courier import CourierDriverHistory, CourierLedgerEntryType, get_utc_now_naive
# from app.models.trip import CompanyLedger, LedgerEntryType
# from app.models.user import PaymentMethod, PaymentStatus
# from datetime import datetime, timezone

import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models.user import User
# Add these imports at the top if they aren't there
from app.models.courier import CourierTrip, CourierStatus
from app.services.dispatch import find_nearby_courier_drivers

logger = logging.getLogger(__name__)

# search ring and time 
SEARCH_RINGS = [5.0, 10.0, 15.0] 
WAIT_TIME_SECONDS = 60


async def broadcast_courier_trip_to_drivers(trip_id: str):
    """
    The main matchmaking loop for the Courier app. 
    Expands the search radius if no van accepts.
    """
    async with async_session_factory() as session:
        trip = await session.get(CourierTrip, trip_id)
        
        # Only broadcast if the trip is actively looking for vans (PENDING)
        if not trip or trip.status != CourierStatus.PENDING:
            return

        for radius in SEARCH_RINGS:
            logger.info(f"Searching for {trip.requested_vehicle_type} within {radius}km for Courier Trip {trip_id}")
            
            # 1. Find drivers with the correct vehicle in this ring
            nearby_drivers = await find_nearby_courier_drivers(
                session=session,
                pickup_lat=trip.pickup_lat,
                pickup_lng=trip.pickup_lng,
                radius_km=radius,
                vehicle_type=trip.requested_vehicle_type
            )

            # 2. Ping their mobile apps via FCM
            if nearby_drivers:
                for driver in nearby_drivers:
                    if getattr(driver, "fcm_token", None):
                        logger.info(f"Pinging Courier {driver.id} - Distance: {driver.distance:.2f}km")
                        await push_trip_to_driver(
                            fcm_token=driver.fcm_token,
                            trip_id=str(trip.id),
                            pickup_address=trip.pickup_address,
                            amount=str(trip.total_cost) # Total they will collect
                        )

            # 3. Wait 60 seconds to give them a chance to tap "Accept"
            await asyncio.sleep(WAIT_TIME_SECONDS)

            # 4. Refresh trip from database to see if a driver accepted it
            await session.refresh(trip)
            
            # In courier flow, accepted trips flip to ACCEPTED (towing uses EN_ROUTE)
            if trip.status == CourierStatus.ACCEPTED:
                logger.info(f"Courier Trip {trip_id} was accepted! Stopping the search.")
                return 

        # 5. If we get through all rings and no one accepted...
        if trip.status == CourierStatus.PENDING:
            logger.warning(f"No vans accepted Courier Trip {trip_id}. Auto-cancelling.")
            
            trip.status = CourierStatus.CANCELLED
            # If they paid by card, you would trigger a refund/void here
            session.add(trip)
            await session.commit()
            
            # TODO: Send FCM Push Notification to the User: "Sorry, all our vans are currently busy."

# 
# async def wait_and_auto_complete_courier_trip(trip_id: str, session_factory):
#     """
#     Background Task: Waits 2 minutes after driver arrives at the drop-off.
#     If they forget to hit 'Complete', it forces completion and logs the debt.
#     """
#     logger.info(f"Starting 2-minute auto-completion timer for Courier Trip {trip_id}")
#     await asyncio.sleep(120)

#     async with session_factory() as session:
#         trip = await session.get(CourierTrip, trip_id)
        
#         # If it hasn't been completed manually yet...
#         if trip and trip.status == CourierStatus.ARRIVED:
#             logger.info(f"Timer expired for Courier Trip {trip_id}. Auto-completing.")
            
#             # If they didn't successfully pay by card, we assume the driver took CASH
#             if trip.payment_method != "CARD" or trip.payment_status != "PAID":
#                 trip.payment_method = "CASH"
#                 trip.payment_status = "DEBT_LOGGED"
                
#                 # Log the platform fee as debt against the courier driver
#                 debt_entry = CourierDriverHistory(
#                     driver_id=trip.driver_id,
#                     trip_id=trip.id,
#                     entry_type=CourierLedgerEntryType.COMMISSION_DEBT,
#                     amount=-float(trip.platform_fee),
#                     description=f"Auto-completed Commission debt for Cash Trip #{str(trip.id)[:8]}"
#                 )
#                 session.add(debt_entry)
            
#             trip.status = CourierStatus.COMPLETED
#             trip.completed_at = get_utc_now_naive() # Naive UTC to prevent DB crashes
            
#             session.add(trip)
#             await session.commit()
            
#             logger.info(f"Courier Trip {trip.id} auto-completed. Debt logged if cash.")



async def wait_and_auto_complete_courier_trip(
    trip_id: str,
    session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """
    Background worker that waits 2 minutes after a driver arrives at drop-off.
    If the trip is still uncompleted, it forces completion, reconciles user debt,
    and logs driver commission debt for cash trips.
    """
    # 1. Wait for the 2-minute safety window (120 seconds)
    await asyncio.sleep(120)

    # 2. Open an independent database session for the background worker
    async with session_factory() as session:
        try:
            trip = await session.get(CourierTrip, trip_id)
            if not trip:
                return

            # Race condition check: If driver already completed or cancelled manually, abort
            if trip.status != CourierStatus.ARRIVED:
                return

            # Fetch the associated user
            user = await session.get(User, trip.user_id)
            if not user:
                return

            # 3. Process Cash Trip Ledger Entry
            if trip.payment_method == "CASH":
                trip.payment_status = "DEBT_LOGGED"
                total_owed_to_platform = float(trip.platform_fee) + float(trip.applied_debt)
                
                ledger_entry = CourierDriverHistory(
                    driver_id=trip.driver_id,
                    trip_id=trip.id,
                    entry_type=CourierLedgerEntryType.COMMISSION_DEBT,
                    amount=-total_owed_to_platform,
                    description=f"Auto-completed cash trip #{str(trip.id)[:8]} ledger sync"
                )
                session.add(ledger_entry)

            # 4. Clear the User's Chalkboard Debt
            if trip.applied_debt > 0:
                user.pending_cancellation_fee = max(
                    0.0, 
                    float(user.pending_cancellation_fee) - float(trip.applied_debt)
                )
                session.add(user)

            # 5. Force Completion State
            trip.status = CourierStatus.COMPLETED
            trip.completed_at = get_utc_now_naive()

            session.add(trip)
            await session.commit()

        except Exception as e:
            await session.rollback()
            # Log the exception via your monitoring tool (e.g., Sentry / Loguru)
            print(f"Background task error auto-completing trip {trip_id}: {str(e)}")