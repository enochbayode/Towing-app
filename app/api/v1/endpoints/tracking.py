# app/api/v1/endpoints/tracking.py
from uuid import UUID
from fastapi import BackgroundTasks
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_session
from app.models.trip import Trip, TripStatus
import logging
from datetime import datetime, timezone
from app.models.driver import Driver

from app.utils.dispatch_worker import wait_and_auto_complete_trip
from app.api.deps import get_current_driver

# Reuse the Haversine function we wrote earlier
from app.services.pricing_engine import calculate_distance_km

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/{trip_id}/location")
async def update_driver_location(
    trip_id: UUID,
    lat: float,
    lng: float,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_driver: Driver = Depends(get_current_driver)
):
    """
    Called by the driver's phone every ~10 seconds.
    Updates their location and checks if they have arrived.
    """
    trip = await session.get(Trip, trip_id)
    
    if trip.status == TripStatus.TOWING:
        # Check distance to drop-off
        distance_to_dropoff = calculate_distance_km(
            lat, lng, trip.dropoff_lat, trip.dropoff_lng
        )
        
        # 0.1 km = 100 meters (Standard GPS geofence radius)
        if distance_to_dropoff <= 0.1:
            logger.info(f"Geofence breached! Auto-arriving Trip {trip.id}")
            
            trip.status = TripStatus.ARRIVED
            trip.arrived_at = datetime.now(timezone.utc)
            session.add(trip)
            await session.commit()
            
            # Start the 2-minute failsafe timer!
            from app.db.session import async_session_factory
            background_tasks.add_task(wait_and_auto_complete_trip, trip.id, async_session_factory)
            
            return {"status": "arrived"}

    # Just a normal location update
    # TODO: Broadcast new lat/lng to the User via WebSocket here
    return {"status": "tracking_updated"}