from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import settings
from app.schemas.courier import CourierTripCreate 

def is_night_time(scheduled_time: datetime = None) -> bool:
    tz = ZoneInfo("Africa/Lagos")
    check_time = scheduled_time.astimezone(tz) if scheduled_time else datetime.now(tz)
    return check_time.hour >= 20 or check_time.hour < 6

def calculate_courier_price(trip_data: CourierTripCreate) -> dict:
    """
    Calculates the dynamic pricing breakdown for a courier job,
    now heavily factoring in the requested vehicle size.
    """
    # 1. Load base config values
    BASE_FARE = Decimal(str(settings.COURIER_BASE_FARE))
    PER_KM_RATE = Decimal(str(settings.COURIER_PER_KM_RATE))
    LABOR_SURCHARGE = Decimal(str(settings.COURIER_LABOR_SURCHARGE))
    PASSENGER_SURCHARGE = Decimal(str(settings.COURIER_PASSENGER_SURCHARGE))
    INTERSTATE_SURCHARGE = Decimal(str(settings.COURIER_INTERSTATE_SURCHARGE))
    NIGHT_MULTIPLIER = Decimal(str(settings.COURIER_NIGHT_MULTIPLIER))
    COMMISSION = Decimal(str(settings.COURIER_PLATFORM_COMMISSION))
    
    # 2. Determine Vehicle Multiplier
    # (Assumes your schema has a `requested_vehicle_type` field)
    vehicle_type = (getattr(trip_data, 'requested_vehicle_type', 'sprinter')).lower()
    
    if vehicle_type == "motorcycle":
        v_mult = Decimal(str(settings.COURIER_MULT_MOTORCYCLE))
    elif vehicle_type == "box_truck":
        v_mult = Decimal(str(settings.COURIER_MULT_BOX_TRUCK))
    else:
        v_mult = Decimal(str(settings.COURIER_MULT_SPRINTER))

    # 3. Scale base fare and distance cost by vehicle size
    scaled_base_fare = BASE_FARE * v_mult
    scaled_distance_cost = (Decimal(str(trip_data.estimated_distance_km)) * PER_KM_RATE) * v_mult
    
    # Flat fees usually don't scale with vehicle size
    labor_cost = LABOR_SURCHARGE if trip_data.requires_labor else Decimal("0.00")
    passenger_cost = PASSENGER_SURCHARGE * Decimal(str(trip_data.passenger_count))
    interstate_cost = INTERSTATE_SURCHARGE if trip_data.is_interstate else Decimal("0.00")
    
    # 4. Base Subtotal
    subtotal = scaled_base_fare + scaled_distance_cost + labor_cost + passenger_cost + interstate_cost
    
    # 5. Apply Night Surcharge
    scheduled_time = getattr(trip_data, 'scheduled_time', None)
    is_night = is_night_time(scheduled_time)
    
    if is_night:
        total_cost = subtotal * NIGHT_MULTIPLIER
    else:
        total_cost = subtotal
        
    # 6. Calculate Platform Split
    platform_fee = total_cost * COMMISSION
    driver_payout = total_cost - platform_fee
    
    return {
        "total_cost": total_cost.quantize(Decimal("0.01")),
        "platform_fee": platform_fee.quantize(Decimal("0.01")),
        "driver_payout": driver_payout.quantize(Decimal("0.01")),
        "is_night_rate_applied": is_night,
        "vehicle_multiplier_applied": v_mult
    }