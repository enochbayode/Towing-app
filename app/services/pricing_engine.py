import math
import pytz
from decimal import Decimal
from datetime import datetime, time
from app.schemas.trip import CustomerVehicleType, TowTruckType
from app.services.map_integration import get_route_details # NEW IMPORT

# --- PRICING MATRIX ---
BASE_DISPATCH_FEE = 10000.0   # Base fee for dispatching a tow truck (in NGN)
COST_PER_KM = 800.0           # Cost per kilometer of towing (in NGN)
NIGHT_SURGE_MULTIPLIER = 1.5  # Nighttime surcharge (10 PM to 5 AM)

VEHICLE_MULTIPLIERS = {
    CustomerVehicleType.MOTORCYCLE: 0.8, 
    CustomerVehicleType.SEDAN: 1.0,      
    CustomerVehicleType.SUV: 1.3,        
    CustomerVehicleType.TRUCK: 1.8,
    CustomerVehicleType.BUS: 2.5,
    CustomerVehicleType.MINIVAN: 1.5     
}

TRUCK_TYPE_MULTIPLIERS = {
    TowTruckType.WHEEL_LIFT: 1.0, 
    TowTruckType.FLATBED: 1.5,     
    TowTruckType.HEAVY_DUTY: 2.0  
}

def get_time_of_day_multiplier() -> float:
    # ... (Your existing timezone logic remains unchanged) ...
    wat_tz = pytz.timezone('Africa/Lagos')
    current_time = datetime.now(wat_tz).time()
    night_start, night_end = time(22, 0), time(5, 0)
    
    if current_time >= night_start or current_time < night_end:
        return NIGHT_SURGE_MULTIPLIER
    return 1.0

def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # ... (Your existing Haversine logic remains unchanged as the fallback) ...
    R = 6371.0 
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat, dlon = lat2_rad - lat1_rad, lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# NOW CONVERTED TO ASYNC
async def calculate_tow_cost(
    pickup_lat: float, 
    pickup_lng: float, 
    dropoff_lat: float, 
    dropoff_lng: float, 
    vehicle_type: CustomerVehicleType, 
    truck_type: TowTruckType
) -> Decimal:
    """
    Calculates cost using Google Maps actual driving distance, with a Haversine fallback.
    """
    # 1. Attempt to get actual driving distance from Google Maps
    route_data = await get_route_details(
        pickup_lat=pickup_lat, 
        pickup_lng=pickup_lng, 
        dropoff_lat=dropoff_lat, 
        dropoff_lng=dropoff_lng
    )
    
    if route_data:
        distance_km = route_data["distance_km"]
    else:
        # Fallback to straight-line distance if Google API fails or times out
        distance_km = calculate_distance_km(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    
    # 2. Minimum 1km charge to prevent 0 NGN distance fees
    if distance_km < 1.0:
        distance_km = 1.0
        
    # 3. Calculate raw distance cost
    distance_cost = distance_km * COST_PER_KM
    
    # 4. Apply multipliers
    v_mult = VEHICLE_MULTIPLIERS[vehicle_type]
    t_mult = TRUCK_TYPE_MULTIPLIERS[truck_type]
    time_mult = get_time_of_day_multiplier()
    
    # Formula: (Base + Distance) * Vehicle Penalty * Truck Premium * Time Surge
    final_cost = (BASE_DISPATCH_FEE + distance_cost) * v_mult * t_mult * time_mult
    
    return Decimal(str(round(final_cost, 2)))