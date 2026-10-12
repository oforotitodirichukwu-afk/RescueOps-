from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def rank_by_distance(ambulances: list[dict], lat: float, lon: float) -> list[tuple[float, dict]]:
    scored = [(haversine_km(lat, lon, float(a["latitude"]), float(a["longitude"])), a) for a in ambulances]
    return sorted(scored, key=lambda pair: pair[0])


def eta_minutes(distance_km: float, speed_kmh: float) -> float:
    return round(distance_km / speed_kmh * 60, 1)
