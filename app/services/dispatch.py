# app/services/dispatch.py
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import logging

# Adjust import based on your models
from app.models.driver import Driver 

logger = logging.getLogger(__name__)

async def find_nearby_drivers(
    session: AsyncSession, 
    pickup_lat: float, 
    pickup_lng: float, 
    radius_km: float,
    limit: int = 10
) -> List[Driver]:
    """
    Finds available drivers within a specific radius (in kilometers),
    ordered by who is physically closest to the pickup location.
    """
    # PostgreSQL Math for Haversine Formula (6371 is the Earth's radius in km)
    distance_expr = (
        6371.0 * func.acos(
            func.cos(func.radians(pickup_lat)) 
            * func.cos(func.radians(Driver.current_lat)) 
            * func.cos(func.radians(Driver.current_lng) - func.radians(pickup_lng)) 
            + func.sin(func.radians(pickup_lat)) 
            * func.sin(func.radians(Driver.current_lat))
        )
    )

    # We only want drivers who are online, not currently on a trip, and within the ring
    statement = (
        select(Driver)
        .where(Driver.is_online == True)
        .where(Driver.is_available == True)
        .where(Driver.current_lat != None)
        .where(distance_expr <= radius_km)
        .order_by(distance_expr) # Closest drivers first
        .limit(limit)
    )

    result = await session.execute(statement)
    drivers = result.scalars().all()
    
    return drivers



from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

async def find_nearby_courier_drivers(
    session: AsyncSession, 
    pickup_lat: float, 
    pickup_lng: float, 
    radius_km: float,
    vehicle_type: str
):
    """
    Finds available courier drivers within a specific radius driving the correct vehicle.
    """
    query = text("""
        WITH driver_distances AS (
            SELECT cd.id, cd.fcm_token,
                   (6371 * acos(
                        least(1.0, 
                            cos(radians(:lat)) * cos(radians(cd.current_lat)) *
                            cos(radians(cd.current_lng) - radians(:lng)) +
                            sin(radians(:lat)) * sin(radians(cd.current_lat))
                        )
                   )) AS distance
            FROM courier_drivers cd
            JOIN courier_vehicles cv ON cd.current_vehicle_id = cv.id
            WHERE cd.is_online = True
              AND cd.is_available = True
              AND cd.is_verified = True
              AND cd.current_lat IS NOT NULL
              AND cd.current_lng IS NOT NULL
              AND LOWER(cv.vehicle_type) = LOWER(:vehicle_type)
        )
        SELECT id, fcm_token, distance
        FROM driver_distances
        WHERE distance <= :radius
        ORDER BY distance ASC
        LIMIT 10;
    """)

    result = await session.execute(
        query,
        {
            "lat": pickup_lat,
            "lng": pickup_lng,
            "vehicle_type": vehicle_type,
            "radius": radius_km
        }
    )
    return result.mappings().all()