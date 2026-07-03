# app/workers/dispatch_worker.py
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import async_session_factory
from app.models.trip import Trip, TripStatus
from app.services.dispatch import find_nearby_drivers
import logging

logger = logging.getLogger(__name__)

# The Bolt-style expanding rings (in kilometers)
SEARCH_RINGS = [5.0, 10.0, 15.0] 
WAIT_TIME_SECONDS = 60

async def broadcast_trip_to_drivers(trip_id: str):
    """
    The main matchmaking loop. Expands the search radius if no one accepts.
    """
    async with async_session_factory() as session:
        # Fetch the trip coordinates
        trip = await session.get(Trip, trip_id)
        if not trip or trip.status != TripStatus.FUNDS_ESCROWED:
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

            # 2. Ping their mobile apps
            if nearby_drivers:
                for driver in nearby_drivers:
                    logger.info(f"Pinging Driver {driver.id} - Distance: {radius}km ring")
                    # TODO: Trigger Firebase Push Notification or WebSocket event to the driver's phone here
                    # e.g., send_push_notification(driver.device_token, "New Tow Request Nearby!", trip_data)

            # 3. Wait 60 seconds to give them a chance to tap "Accept"
            await asyncio.sleep(WAIT_TIME_SECONDS)

            # 4. Check the database again. Did someone accept it while we were sleeping?
            # We must refresh the trip from the database to get the latest status
            await session.refresh(trip)
            
            if trip.status == TripStatus.EN_ROUTE:
                logger.info(f"Trip {trip_id} was accepted! Stopping the search broadcast.")
                return # Exit the loop, our job is done!

        # 5. If we get through all rings (e.g., 15km) and no one accepted...
        if trip.status == TripStatus.FUNDS_ESCROWED:
            logger.warning(f"No drivers accepted Trip {trip_id} after maximum radius.")
            # TODO: Auto-cancel the trip, trigger the Paystack Refund API, and notify the user.