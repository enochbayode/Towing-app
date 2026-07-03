import math
import pytz
from decimal import Decimal
from datetime import datetime, time
from app.schemas.trip import VehicleType, TowTruckType

# --- PRICING MATRIX (Can be moved to DB or config later) ---
BASE_DISPATCH_FEE = 10000.0  # NGN: Minimum cost just to send a truck
COST_PER_KM = 800.0          # NGN: Rate per kilometer towed
NIGHT_SURGE_MULTIPLIER = 1.5 # 1.5x surge for late-night tows (10 PM - 5 AM)

VEHICLE_MULTIPLIERS = {
    VehicleType.MOTORCYCLE: 0.8, # Cheaper
    VehicleType.SEDAN: 1.0,      # Standard
    VehicleType.SUV: 1.3,        # Heavier
    VehicleType.TRUCK: 1.8       # Heaviest
}

TRUCK_TYPE_MULTIPLIERS = {
    TowTruckType.WHEEL_LIFT: 1.0, # Standard chained
    TowTruckType.FLATBED: 1.5,     # Premium/Safer platform
    TowTruckType.HEAVY_DUTY: 2.0  # For large vehicles like buses or trucks
}

def get_time_of_day_multiplier() -> float:
    """
    Applies a surge multiplier for tows requested between 10:00 PM and 5:00 AM WAT.
    """
    # Force the timezone to West Africa Time to avoid server-time mismatches
    wat_tz = pytz.timezone('Africa/Lagos')
    current_time = datetime.now(wat_tz).time()
    
    night_start = time(22, 0)
    night_end = time(5, 0)
    
    # Apply surge if time is 10:00 PM or later, OR before 5:00 AM
    if current_time >= night_start or current_time < night_end:
        return NIGHT_SURGE_MULTIPLIER
        
    return 1.0

def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the straight-line distance between two GPS coordinates using the Haversine formula.
    """
    R = 6371.0 # Radius of Earth in kilometers

    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance

def calculate_tow_cost(
    pickup_lat: float, 
    pickup_lng: float, 
    dropoff_lat: float, 
    dropoff_lng: float, 
    vehicle_type: VehicleType, 
    truck_type: TowTruckType
) -> Decimal:
    """
    Calculates the raw base_cost based on distance, vehicle weight, tow truck type, and time of day.
    """
    # 1. Get the distance
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
    
    # Return as a clean Decimal rounded to 2 decimal places
    return Decimal(str(round(final_cost, 2)))