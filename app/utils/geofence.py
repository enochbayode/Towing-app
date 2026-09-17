from math import radians, sin, cos, sqrt, atan2

def calculate_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the great-circle distance between two points 
    on the Earth (specified in decimal degrees) in meters.
    """
    R = 6371000  # Radius of Earth in meters
    
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    
    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    return R * c