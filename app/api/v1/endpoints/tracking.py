# app/api/v1/endpoints/tracking.py
from uuid import UUID
from fastapi import BackgroundTasks, APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_session
from app.models.trip import Trip, TripStatus
import logging
from datetime import datetime, timezone
from app.models.driver import Driver

from app.utils.dispatch_worker import wait_and_auto_complete_trip
from app.api.deps import get_current_driver
from app.core.config import settings
from app.models.user import User

from app.services.websocket_manager import manager

# Reuse the Haversine function we wrote earlier
from app.services.pricing_engine import calculate_distance_km

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/trip/{trip_id}/track")
async def trip_tracking_ws(
    websocket: WebSocket, 
    trip_id: UUID,
    token: str = Query(...), # Extracts the token from the URL query parameters
    session: AsyncSession = Depends(get_session)
):
    """
    Secured WebSocket endpoint for live GPS tracking.
    Validates the JWT token before accepting the connection.
    """
    # 1. Accept the connection temporarily to send error codes if needed
    await websocket.accept()
    
    # 2. Decode and Validate the JWT
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str = payload.get("sub")
        if not user_id_str:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
            
        # Verify user exists in the database
        user = await session.get(User, UUID(user_id_str))
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
            
    except JWTError:
        # Invalid or expired token
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 3. Verify Trip Ownership (Security Check)
    trip = await session.get(Trip, trip_id)
    if not trip:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    # Ensure the person trying to watch the trip is the one who requested it
    if trip.user_id != user.id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 4. Authentication Passed! Hand over to the Manager
    await manager.connect(websocket, trip_id)
    
    try:
        while True:
            # We are just broadcasting TO the user, but we must keep the loop 
            # running to detect if the user's phone disconnects (e.g., closes the app)
            data_text = await websocket.receive_text()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, trip_id)


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
    Updates location, checks geofence, and broadcasts to the user via WebSocket.
    """
    trip = await session.get(Trip, trip_id)
    
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # 1. Broadcast the new location to the Customer instantly
    await manager.broadcast_location(
        trip_id, 
        {
            "type": "LOCATION_UPDATE",
            "lat": lat, 
            "lng": lng,
            # You can pass heading/rotation here if the mobile app sends it
        }
    )

    # 2. Check the Geofence logic if the trip is currently TOWING
    if trip.status == TripStatus.TOWING:
        distance_to_dropoff = calculate_distance_km(
            lat, lng, trip.dropoff_lat, trip.dropoff_lng
        )
        
        # 0.1 km = 100 meters
        if distance_to_dropoff <= 0.1:
            logger.info(f"Geofence breached! Auto-arriving Trip {trip.id}")
            
            trip.status = TripStatus.ARRIVED
            # Applied the timezone fix here so asyncpg doesn't crash:
            trip.arrived_at = datetime.now(timezone.utc).replace(tzinfo=None)
            
            session.add(trip)
            await session.commit()
            
            # Start the 2-minute failsafe timer
            from app.db.session import async_session_factory
            background_tasks.add_task(wait_and_auto_complete_trip, trip.id, async_session_factory)
            
            return {"status": "arrived"}

    return {"status": "tracking_updated"}