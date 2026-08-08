from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000

# Straight-line distance under-reports real road distance. 1.4 is a placeholder
# until Google Distance Matrix arrives in phase 3.
ROAD_FACTOR = 1.4

AVG_SPEED_KMH = 20.0


def road_distance_m(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> int:
    """Great-circle distance times a road-winding factor, in metres."""
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    )
    straight_m = EARTH_RADIUS_M * 2 * atan2(sqrt(a), sqrt(1 - a))
    return round(straight_m * ROAD_FACTOR)


def eta_minutes(distance_m: int) -> int:
    """Rough ETA from average city speed. Replaced by Maps in phase 3."""
    hours = (distance_m / 1000) / AVG_SPEED_KMH
    return max(1, round(hours * 60))
