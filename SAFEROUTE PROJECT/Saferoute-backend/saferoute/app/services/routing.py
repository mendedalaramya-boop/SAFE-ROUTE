"""
Routing Service
================
Provides high-accuracy route calculations and hazard-corridor collision analysis.
Integrates with OpenStreetMap's OSRM routing engine to retrieve actual road network
geometry, real highway driving distances, and turn-by-turn navigation paths.
Includes an intelligent mathematical fallback if offline or unreachable.
"""

import logging
import requests
from typing import Dict, Any, List, Optional
from flask import current_app

from app.geospatial.calculations import (
    haversine_distance,
    distance_point_to_polyline,
    interpolate_route_points,
)

logger = logging.getLogger(__name__)


def calculate_route(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> Dict[str, Any]:
    """Computes real road network geometry, driving distance, and estimated duration.
    
    Tries:
    1. OSRM (Open Source Routing Machine) public driving routing API for actual road paths.
    2. OpenRouteService if API key is provided.
    3. Intelligent geometric Great-Circle corridor estimation as an offline fallback.
    """
    api_url = current_app.config.get("ROUTING_API_URL")
    api_key = current_app.config.get("ROUTING_API_KEY")

    # 1. Primary: Query OpenStreetMap OSRM routing engine for real road network polyline
    osrm_url = f"https://router.project-osrm.org/route/v1/driving/{origin_lng},{origin_lat};{dest_lng},{dest_lat}?overview=full&geometries=geojson"
    try:
        resp = requests.get(
            osrm_url,
            headers={"User-Agent": "SafeRouteNavigation/2.0"},
            timeout=6,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == "Ok" and data.get("routes"):
                best_route = data["routes"][0]
                dist_km = round(best_route["distance"] / 1000.0, 2)
                dur_min = round(best_route["duration"] / 60.0, 1)
                raw_coords = best_route["geometry"]["coordinates"]
                # Convert GeoJSON [longitude, latitude] to Leaflet [latitude, longitude]
                geometry = [[round(pt[1], 6), round(pt[0], 6)] for pt in raw_coords]

                return {
                    "distance_km": dist_km,
                    "duration_minutes": dur_min,
                    "geometry": geometry,
                    "provider": "OSRM (OpenStreetMap Road Network)",
                    "note": None,
                }
    except Exception as exc:
        logger.warning("OSRM public road routing request failed: %s. Trying secondary routing.", exc)

    # 2. Secondary: OpenRouteService if configured
    if api_url and api_key and not api_url.startswith("https://api.example"):
        try:
            headers = {"Authorization": api_key, "Content-Type": "application/json"}
            payload = {
                "coordinates": [[origin_lng, origin_lat], [dest_lng, dest_lat]],
            }
            resp = requests.post(
                f"{api_url.rstrip('/')}/v2/directions/driving-car",
                json=payload,
                headers=headers,
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                route_meta = data["routes"][0]["summary"]
                distance_km = round(route_meta["distance"] / 1000.0, 2)
                duration_min = round(route_meta["duration"] / 60.0, 1)
                coords = data["routes"][0]["geometry"]["coordinates"]
                geometry = [[round(pt[1], 6), round(pt[0], 6)] for pt in coords]
                return {
                    "distance_km": distance_km,
                    "duration_minutes": duration_min,
                    "geometry": geometry,
                    "provider": "OpenRouteService",
                    "note": None,
                }
        except Exception as exc:
            logger.warning("OpenRouteService API request failed: %s.", exc)

    # 3. Resilient Offline Fallback:
    # High-fidelity corridor interpolation with urban circuity factor
    crow_dist = haversine_distance(origin_lat, origin_lng, dest_lat, dest_lng)
    road_dist = round(max(0.1, crow_dist * 1.32), 2)
    est_duration = round(max(1.0, (road_dist / 42.0) * 60.0), 1)
    geometry = interpolate_route_points(origin_lat, origin_lng, dest_lat, dest_lng, num_points=35)

    return {
        "distance_km": road_dist,
        "duration_minutes": est_duration,
        "geometry": geometry,
        "provider": "offline_estimate",
        "note": "Calculated via geometric corridor estimation. SafeRoute does not guarantee the route is safe.",
    }


def find_hazards_along_route(
    route_geometry: List[List[float]],
    verified_hazards: List[Dict[str, Any]],
    search_radius_km: float = 1.0,
) -> List[Dict[str, Any]]:
    """Identifies hazards whose physical location falls within search_radius_km of the route polyline."""
    matched = []
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    for h in verified_hazards:
        h_lat = float(h["latitude"])
        h_lng = float(h["longitude"])
        dist_from_route = distance_point_to_polyline(h_lat, h_lng, route_geometry)

        if dist_from_route <= search_radius_km:
            h_copy = dict(h)
            h_copy["distance_from_route"] = round(dist_from_route, 2)
            h_copy["distance_km"] = round(dist_from_route, 2)
            matched.append(h_copy)

    # Sort primarily by severity (critical first) then by proximity to route
    matched.sort(
        key=lambda item: (
            -severity_rank.get(item.get("severity", "low"), 0),
            item["distance_from_route"],
        )
    )

    return matched
