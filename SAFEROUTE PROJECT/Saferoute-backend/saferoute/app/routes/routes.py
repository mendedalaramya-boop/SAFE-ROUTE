"""
Route Search & Hazard Intersection Routes
==========================================
Enables users to search a navigation route between origin and destination coordinates,
computing driving distance, estimated duration, polyline corridor geometry, and
intersecting verified hazards within the corridor radius.
"""

import requests
from flask import Blueprint, request, g, current_app

from app.utils.responses import success_response, error_response
from app.utils.db import query_all, execute_insert
from app.middleware.auth import token_required
from app.utils.audit import record_audit_log
from app.utils.notifications import create_notification
from app.services.routing import calculate_route, find_hazards_along_route

routes_bp = Blueprint("routes", __name__)

# Fallback geocoding dictionary for key regional hubs & transit points
PRESET_COORDINATES = {
    "vijayawada": (16.5062, 80.6480, "Vijayawada, Andhra Pradesh, India"),
    "vijayawada railway station": (16.5186, 80.6198, "Vijayawada Junction Railway Station, AP"),
    "guntur": (16.3067, 80.4365, "Guntur, Andhra Pradesh, India"),
    "guntur bus stand": (16.3015, 80.4430, "NTR Bus Station, Guntur, AP"),
    "benz circle": (16.5020, 80.6510, "Benz Circle, Vijayawada, AP"),
    "auto nagar": (16.4950, 80.6720, "Auto Nagar Industrial Area, Vijayawada"),
    "hyderabad": (17.3850, 78.4867, "Hyderabad, Telangana, India"),
    "visakhapatnam": (17.6868, 83.2185, "Visakhapatnam, Andhra Pradesh, India"),
    "amaravati": (16.5730, 80.3575, "Amaravati Capital City, AP"),
    "mangalagiri": (16.4300, 80.5700, "Mangalagiri, Guntur District, AP"),
    "tadepalli": (16.4800, 80.6000, "Tadepalli, Guntur District, AP"),
    "gannavaram": (16.5390, 80.8030, "Gannavaram Airport Road, AP"),
    "kanaka durga temple": (16.5152, 80.6050, "Sri Durga Malleswara Swamy Temple, Indrakeeladri, Vijayawada"),
    "tenali": (16.2430, 80.6400, "Tenali, Guntur District, AP"),
    "eluru": (16.7107, 81.0952, "Eluru, Andhra Pradesh, India"),
    "chennai": (13.0827, 80.2707, "Chennai, Tamil Nadu, India"),
    "bengaluru": (12.9716, 77.5946, "Bengaluru, Karnataka, India"),
    "delhi": (28.6139, 77.2090, "New Delhi, Delhi, India"),
    "mumbai": (19.0760, 72.8777, "Mumbai, Maharashtra, India"),
    "kolkata": (22.5726, 88.3639, "Kolkata, West Bengal, India"),
}


@routes_bp.route("/geocode", methods=["GET"])
@token_required
def geocode():
    """Geocodes a human-readable address query into geographic coordinates."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return error_response("Search query 'q' parameter is required.", "MISSING_QUERY", 400)

    # 1. Check quick preset dictionary
    norm_q = q.lower().replace(",", " ").replace(".", " ").strip()
    norm_q = " ".join(norm_q.split())

    for key, (lat, lng, name) in PRESET_COORDINATES.items():
        if key in norm_q or norm_q in key:
            return success_response(data={"latitude": lat, "longitude": lng, "displayName": name})

    # 2. Query OpenStreetMap Nominatim with proper User-Agent
    try:
        url = "https://nominatim.openstreetmap.org/search"
        resp = requests.get(
            url,
            params={"q": q, "format": "json", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": "SafeRouteNavigation/2.0"},
            timeout=5,
        )
        if resp.status_code == 200:
            results = resp.json()
            if results:
                top = results[0]
                return success_response(
                    data={
                        "latitude": float(top["lat"]),
                        "longitude": float(top["lon"]),
                        "displayName": top.get("display_name", q),
                    }
                )
    except Exception as exc:
        current_app.logger.warning("Backend geocoding failed for query '%s': %s", q, exc)

    return error_response(
        f"Could not locate '{q}'. Please check the address or try adding city name.",
        "LOCATION_NOT_FOUND",
        404,
    )


@routes_bp.route("/reverse-geocode", methods=["GET"])
@token_required
def reverse_geocode():
    """Reverse geocodes latitude and longitude into street, village, district, city, state."""
    try:
        lat = float(request.args.get("latitude") or request.args.get("lat"))
        lng = float(request.args.get("longitude") or request.args.get("lng") or request.args.get("lon"))
    except (TypeError, ValueError):
        return error_response("Valid latitude and longitude parameters are required.", "INVALID_COORDINATES", 400)

    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        resp = requests.get(
            url,
            params={
                "lat": lat,
                "lon": lng,
                "format": "json",
                "addressdetails": 1,
                "zoom": 18,
            },
            headers={"User-Agent": "SafeRouteNavigation/2.0"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            address = data.get("address", {})
            road = (
                address.get("road")
                or address.get("pedestrian")
                or address.get("suburb")
                or address.get("neighbourhood")
                or address.get("highway")
                or ""
            )
            village = (
                address.get("village")
                or address.get("suburb")
                or address.get("neighbourhood")
                or address.get("town")
                or address.get("city_district")
                or ""
            )
            district = (
                address.get("state_district")
                or address.get("county")
                or address.get("district")
                or ""
            )
            city = address.get("city") or address.get("town") or address.get("municipality") or ""
            state = address.get("state") or ""

            # Build full formatted string preserving locality order
            parts = []
            for item in [road, village, city, district, state]:
                if item and item not in parts:
                    parts.append(item)

            formatted = ", ".join(parts) if parts else data.get("display_name", f"{lat:.4f}, {lng:.4f}")

            return success_response(
                data={
                    "displayName": formatted,
                    "road": road,
                    "village": village,
                    "district": district,
                    "city": city,
                    "state": state,
                    "raw_address": address,
                    "latitude": lat,
                    "longitude": lng,
                }
            )
    except Exception as exc:
        current_app.logger.warning("Backend reverse geocoding failed for (%s, %s): %s", lat, lng, exc)

    return success_response(
        data={
            "displayName": f"Location ({lat:.4f}, {lng:.4f})",
            "latitude": lat,
            "longitude": lng,
        }
    )



@routes_bp.route("/search", methods=["POST"])
@token_required
def search_route():
    """Searches a route between two geographic coordinates and detects nearby hazards."""
    data = request.get_json(silent=True) or {}
    origin = data.get("origin") or {}
    dest = data.get("destination") or {}

    try:
        origin_lat = float(origin.get("latitude"))
        origin_lng = float(origin.get("longitude"))
        dest_lat = float(dest.get("latitude"))
        dest_lng = float(dest.get("longitude"))
    except (TypeError, ValueError):
        return error_response(
            "Valid coordinates are required for both origin and destination.",
            "INVALID_COORDINATES",
            400,
        )

    if not (-90 <= origin_lat <= 90 and -180 <= origin_lng <= 180):
        return error_response("Origin coordinates out of valid geographic range.", "COORDINATES_OUT_OF_BOUNDS", 400)

    if not (-90 <= dest_lat <= 90 and -180 <= dest_lng <= 180):
        return error_response("Destination coordinates out of valid geographic range.", "COORDINATES_OUT_OF_BOUNDS", 400)

    # Calculate route geometry, distance, and duration
    route_calc = calculate_route(origin_lat, origin_lng, dest_lat, dest_lng)

    # Fetch active verified and visible hazards to check against the corridor
    verified_hazards = query_all(
        """
        SELECT id, hazard_type, title, description, address, city,
               latitude, longitude, severity, status, visibility, start_time
        FROM hazards
        WHERE status = 'verified' AND visibility = 'visible'
        """
    )

    match_radius_km = float(
        data.get("radius_km")
        or data.get("search_radius_km")
        or current_app.config.get("ROUTE_HAZARD_MATCH_RADIUS_KM", 1.5)
    )
    matched_hazards = find_hazards_along_route(
        route_geometry=route_calc["geometry"],
        verified_hazards=verified_hazards,
        search_radius_km=match_radius_km,
    )

    # Record search history in route_searches table
    user_id = g.current_user["id"]
    try:
        execute_insert(
            """
            INSERT INTO route_searches (
                user_id, origin_latitude, origin_longitude, destination_latitude,
                destination_longitude, distance_km, duration_minutes, hazards_found_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                origin_lat,
                origin_lng,
                dest_lat,
                dest_lng,
                route_calc["distance_km"],
                route_calc["duration_minutes"],
                len(matched_hazards),
            ),
        )
    except Exception:
        pass

    # If critical or high hazards are along the route, issue an in-app alert notification
    if matched_hazards:
        high_severity_hazards = [h for h in matched_hazards if h["severity"] in ("critical", "high")]
        if high_severity_hazards:
            create_notification(
                user_id=user_id,
                notification_type="route_hazard_alert",
                title="Hazard warning along your route",
                message=f"Found {len(matched_hazards)} hazard(s) near your route, including {high_severity_hazards[0]['title']}.",
                hazard_id=high_severity_hazards[0]["id"],
            )

    record_audit_log(
        action="ROUTE_SEARCH",
        resource_type="route",
        user_id=user_id,
        description=f"Route search ({origin_lat:.3f},{origin_lng:.3f} -> {dest_lat:.3f},{dest_lng:.3f}). {len(matched_hazards)} hazards identified.",
    )

    response_payload = {
        "origin": {"latitude": origin_lat, "longitude": origin_lng},
        "destination": {"latitude": dest_lat, "longitude": dest_lng},
        "distance_km": route_calc["distance_km"],
        "duration_minutes": route_calc["duration_minutes"],
        "geometry": route_calc["geometry"],
        "provider": route_calc["provider"],
        "note": route_calc.get("note"),
        "hazards": matched_hazards,
        "hazard_count": len(matched_hazards),
        "hazard_matching": {
            "hazards": matched_hazards,
            "count": len(matched_hazards),
            "search_radius_km": match_radius_km,
        },
    }

    return success_response(
        message=f"Route computed. {len(matched_hazards)} verified hazard(s) located near this route.",
        data=response_payload,
    )
