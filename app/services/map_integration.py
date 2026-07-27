# app/services/map_integration.py
import httpx
import logging
from typing import Optional, Dict
from app.core.config import settings

logger = logging.getLogger(__name__)

async def get_route_details(
    pickup_lat: float, 
    pickup_lng: float, 
    dropoff_lat: float, 
    dropoff_lng: float
) -> Optional[Dict[str, float]]:
    """
    Calls the Google Maps Routes API to calculate exact driving distance and time.
    Returns a dictionary with distance (in kilometers) and duration (in minutes).
    """
    # Using the newer Routes API (preferred over the legacy Directions API)
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        # FieldMask tells Google to ONLY return distance and duration to save bandwidth/money
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration"
    }
    
    payload = {
        "origin": {
            "location": {
                "latLng": {"latitude": pickup_lat, "longitude": pickup_lng}
            }
        },
        "destination": {
            "location": {
                "latLng": {"latitude": dropoff_lat, "longitude": dropoff_lng}
            }
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE" # Crucial for accurate ETAs
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                
                if not data.get("routes"):
                    logger.warning("Google Maps found no valid driving route.")
                    return None
                    
                route = data["routes"][0]
                
                # Convert meters to kilometers
                distance_km = route.get("distanceMeters", 0) / 1000.0
                
                # Duration comes back as a string like "1500s", we strip the 's' and convert to minutes
                duration_str = route.get("duration", "0s")
                duration_mins = float(duration_str.replace("s", "")) / 60.0
                
                return {
                    "distance_km": round(distance_km, 2),
                    "duration_mins": round(duration_mins, 2)
                }
            else:
                logger.error(f"Google Maps API Error {response.status_code}: {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to connect to Google Maps: {str(e)}")
        return None


async def geocode_coordinates(lat: float, lng: float) -> Optional[str]:
    """
    (Optional but recommended) Reverse Geocoding.
    Translates raw GPS coordinates back into a human-readable street address.
    """
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "latlng": f"{lat},{lng}",
        "key": settings.GOOGLE_MAPS_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK" and data.get("results"):
                    # Return the most accurate formatted address
                    return data["results"][0]["formatted_address"]
    except Exception as e:
        logger.error(f"Geocoding failed: {str(e)}")
        
    return None