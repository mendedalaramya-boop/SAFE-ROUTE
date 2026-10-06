"""
Geospatial Calculations
========================
Provides high-performance mathematical functions for:
- Haversine distance between coordinates (km)
- Minimum distance from a point to a line segment and polyline corridor
- Polyline waypoint interpolation for offline routing estimation
"""

import math
from typing import List, Tuple, Dict, Any

EARTH_RADIUS_KM = 6371.0088


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the great-circle distance between two points in kilometers."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(EARTH_RADIUS_KM * c, 4)


def distance_point_to_segment(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float
) -> float:
    """Calculates the minimum distance from point P to line segment AB in kilometers."""
    # Convert lat/lon degrees to approximate local planar coordinates in km
    # around point A for fast and accurate segment projection
    mean_lat_rad = math.radians((a_lat + b_lat + p_lat) / 3.0)
    kx = EARTH_RADIUS_KM * math.cos(mean_lat_rad) * (math.pi / 180.0)
    ky = EARTH_RADIUS_KM * (math.pi / 180.0)

    # Local coordinates in km relative to point A (0,0)
    ax, ay = 0.0, 0.0
    bx = (b_lon - a_lon) * kx
    by = (b_lat - a_lat) * ky
    px = (p_lon - a_lon) * kx
    py = (p_lat - a_lat) * ky

    seg_len_sq = bx * bx + by * by
    if seg_len_sq == 0.0:
        return math.sqrt(px * px + py * py)

    # Project point P onto vector AB: t in [0, 1]
    t = max(0.0, min(1.0, (px * bx + py * by) / seg_len_sq))

    proj_x = ax + t * bx
    proj_y = ay + t * by

    dx = px - proj_x
    dy = py - proj_y
    return math.sqrt(dx * dx + dy * dy)


def distance_point_to_polyline(p_lat: float, p_lon: float, polyline: List[List[float]]) -> float:
    """Calculates the minimum distance from point P to any segment in a polyline."""
    if not polyline:
        return float("inf")
    if len(polyline) == 1:
        return haversine_distance(p_lat, p_lon, polyline[0][0], polyline[0][1])

    min_dist = float("inf")
    for i in range(len(polyline) - 1):
        a_lat, a_lon = polyline[i][0], polyline[i][1]
        b_lat, b_lon = polyline[i + 1][0], polyline[i + 1][1]
        dist = distance_point_to_segment(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon)
        if dist < min_dist:
            min_dist = dist

    return min_dist


def interpolate_route_points(
    lat1: float, lon1: float, lat2: float, lon2: float, num_points: int = 15
) -> List[List[float]]:
    """Interpolates waypoints between origin and destination to produce a smooth route geometry."""
    points = []
    for i in range(num_points):
        fraction = i / float(num_points - 1)
        # Add slight natural road curvature variations for realistic visualization
        curve = math.sin(fraction * math.pi) * 0.003
        lat = lat1 + fraction * (lat2 - lat1) + curve
        lon = lon1 + fraction * (lon2 - lon1) - curve * 0.5
        points.append([round(lat, 6), round(lon, 6)])
    return points
