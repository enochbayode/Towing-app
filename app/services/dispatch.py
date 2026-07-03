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