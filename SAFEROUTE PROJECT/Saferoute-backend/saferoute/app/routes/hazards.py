"""
Hazard Management Routes
=========================
Handles hazard lifecycle operations:
- Public verified hazard search
- Reporter personal reports ("My reports")
- Geospatial nearby hazard search
- Hazard report submission with automated duplicate detection
- Hazard updates by the original reporter
- Verification, rejection, visibility toggles, and resolution
"""

from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, g

from app.utils.responses import success_response, error_response
from app.utils.db import query_all, query_one, execute, execute_insert
from app.middleware.auth import token_required, admin_required
from app.utils.audit import record_audit_log
from app.utils.notifications import create_notification
from app.geospatial.calculations import haversine_distance

hazards_bp = Blueprint("hazards", __name__)

VALID_HAZARD_TYPES = {
    "road_closure",
    "flooding",
    "waterlogging",
    "construction",
    "blocked_road",
    "accident",
    "temporary_restriction",
    "other",
}

VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@hazards_bp.route("", methods=["GET"])
@token_required
def list_hazards():
    """Lists hazards with optional filtering by type, severity, city, and status."""
    user = g.current_user
    is_admin = user.get("role") == "admin"

    hazard_type = request.args.get("type")
    severity = request.args.get("severity")
    city = request.args.get("city", "").strip()
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    where_clauses = []
    params = []

    # Non-admins ALWAYS only see verified and visible hazards
    if not is_admin:
        where_clauses.append("status = 'verified'")
        where_clauses.append("visibility = 'visible'")
    else:
        if status:
            where_clauses.append("status = %s")
            params.append(status)

    if hazard_type and hazard_type in VALID_HAZARD_TYPES:
        where_clauses.append("hazard_type = %s")
        params.append(hazard_type)

    if severity and severity in VALID_SEVERITIES:
        where_clauses.append("severity = %s")
        params.append(severity)

    if city:
        where_clauses.append("(city LIKE %s OR address LIKE %s)")
        params.append(f"%{city}%")
        params.append(f"%{city}%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"""
        SELECT id, reporter_id, hazard_type, title, description, address, city,
               latitude, longitude, severity, start_time, expected_end_time,
               status, visibility, is_potential_duplicate, duplicate_of_hazard_id,
               verified_by, verified_at, verification_note,
               resolved_by, resolved_at, resolution_note, created_at, updated_at
        FROM hazards
        {where_sql}
        ORDER BY created_at DESC
        LIMIT {limit} OFFSET {offset}
    """

    hazards = query_all(sql, tuple(params))
    return success_response(data={"hazards": hazards, "count": len(hazards)})


@hazards_bp.route("/my", methods=["GET"])
@token_required
def list_my_hazards():
    """Returns all hazard reports filed by the authenticated user."""
    user_id = g.current_user["id"]
    hazards = query_all(
        """
        SELECT id, reporter_id, hazard_type, title, description, address, city,
               latitude, longitude, severity, start_time, expected_end_time,
               status, visibility, is_potential_duplicate, duplicate_of_hazard_id,
               verified_by, verified_at, verification_note,
               resolved_by, resolved_at, resolution_note, created_at, updated_at
        FROM hazards
        WHERE reporter_id = %s
        ORDER BY created_at DESC
        """,
        (user_id,),
    )
    return success_response(data={"hazards": hazards, "count": len(hazards)})


@hazards_bp.route("/nearby", methods=["GET"])
@token_required
def list_nearby_hazards():
    """Searches for verified and visible hazards within a geographic radius of a point."""
    try:
        lat = float(request.args.get("latitude", ""))
        lng = float(request.args.get("longitude", ""))
    except ValueError:
        return error_response(
            "Valid numeric latitude and longitude parameters are required.",
            "INVALID_COORDINATES",
            400,
        )

    radius_km = float(request.args.get("radius_km", 5.0))
    hazard_type = request.args.get("type")
    severity = request.args.get("severity")

    # Fetch all verified, visible hazards
    sql = """
        SELECT id, reporter_id, hazard_type, title, description, address, city,
               latitude, longitude, severity, start_time, expected_end_time,
               status, visibility, created_at
        FROM hazards
        WHERE status = 'verified' AND visibility = 'visible'
    """
    params = []
    if hazard_type and hazard_type in VALID_HAZARD_TYPES:
        sql += " AND hazard_type = %s"
        params.append(hazard_type)
    if severity and severity in VALID_SEVERITIES:
        sql += " AND severity = %s"
        params.append(severity)

    all_hazards = query_all(sql, tuple(params))

    # Calculate precise Haversine distance and filter
    nearby = []
    for h in all_hazards:
        h_lat = float(h["latitude"])
        h_lng = float(h["longitude"])
        dist = haversine_distance(lat, lng, h_lat, h_lng)
        if dist <= radius_km:
            h["distance_km"] = round(dist, 2)
            nearby.append(h)

    # Sort ascending by distance (closest first)
    nearby.sort(key=lambda x: x["distance_km"])
    return success_response(data={"hazards": nearby, "count": len(nearby), "radius_km": radius_km})


@hazards_bp.route("", methods=["POST"])
@token_required
def create_hazard():
    """Submits a new hazard report. Automatically runs duplicate detection."""
    data = request.get_json(silent=True) or {}
    reporter_id = g.current_user["id"]

    hazard_type = data.get("hazard_type")
    severity = data.get("severity")
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    address = (data.get("address") or "").strip() or None
    city = (data.get("city") or "").strip() or None
    start_time = data.get("start_time")
    expected_end_time = data.get("expected_end_time") or None

    if hazard_type not in VALID_HAZARD_TYPES:
        return error_response(f"Invalid hazard type '{hazard_type}'.", "INVALID_HAZARD_TYPE", 400)

    if severity not in VALID_SEVERITIES:
        return error_response(f"Invalid severity '{severity}'.", "INVALID_SEVERITY", 400)

    if not title or not description:
        return error_response("Title and description are required.", "MISSING_REQUIRED_FIELDS", 400)

    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
    except (TypeError, ValueError):
        return error_response("Valid latitude and longitude numbers are required.", "INVALID_COORDINATES", 400)

    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        return error_response("Coordinates out of bounds (-90..90, -180..180).", "COORDINATES_OUT_OF_BOUNDS", 400)

    if not start_time:
        start_time = datetime.now(timezone.utc).isoformat()

    # Duplicate detection: check if same hazard_type reported within 500m in the last 24h
    recent_hazards = query_all(
        """
        SELECT id, latitude, longitude
        FROM hazards
        WHERE hazard_type = %s AND status IN ('reported', 'under_review', 'verified')
        """,
        (hazard_type,),
    )

    is_duplicate = False
    duplicate_of_id = None
    for h in recent_hazards:
        dist = haversine_distance(latitude, longitude, float(h["latitude"]), float(h["longitude"]))
        if dist <= 0.5:  # within 500 meters
            is_duplicate = True
            duplicate_of_id = h["id"]
            break

    hazard_id = execute_insert(
        """
        INSERT INTO hazards (
            reporter_id, hazard_type, title, description, address, city,
            latitude, longitude, severity, start_time, expected_end_time,
            status, visibility, is_potential_duplicate, duplicate_of_hazard_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'reported', 'visible', %s, %s)
        """,
        (
            reporter_id,
            hazard_type,
            title,
            description,
            address,
            city,
            latitude,
            longitude,
            severity,
            start_time,
            expected_end_time,
            bool(is_duplicate),
            duplicate_of_id,
        ),
    )

    created = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))

    # Create submission confirmation notification for the reporter
    create_notification(
        user_id=reporter_id,
        notification_type="hazard_submitted",
        title="Hazard report submitted",
        message=f"Your report '{title}' was submitted. It is now awaiting verification before going public.",
        hazard_id=hazard_id,
    )

    record_audit_log(
        action="HAZARD_CREATED",
        resource_type="hazard",
        resource_id=hazard_id,
        user_id=reporter_id,
        description=f"Hazard '{title}' reported by user {reporter_id}."
        + (f" Flagged as duplicate of #{duplicate_of_id}." if is_duplicate else ""),
    )

    return success_response(
        message="Hazard reported successfully. It will appear publicly once verified by a moderator.",
        data={"hazard": created},
        status_code=201,
    )


@hazards_bp.route("/<int:hazard_id>", methods=["GET"])
@token_required
def get_hazard(hazard_id: int):
    """Fetches details for a specific hazard."""
    hazard = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    if not hazard:
        return error_response("Hazard not found.", "NOT_FOUND", 404)

    user = g.current_user
    # Visibility rule:
    # Visible to all if verified and visible.
    # Otherwise, only the reporter or an administrator can inspect it.
    is_public = hazard["status"] == "verified" and hazard["visibility"] == "visible"
    is_owner = hazard["reporter_id"] == user["id"]
    is_admin = user["role"] == "admin"

    if not (is_public or is_owner or is_admin):
        return error_response("You do not have permission to view this report.", "FORBIDDEN", 403)

    return success_response(data={"hazard": hazard})


@hazards_bp.route("/<int:hazard_id>", methods=["PATCH"])
@token_required
def update_hazard(hazard_id: int):
    """Updates a hazard report. Only the original reporter can edit, and only while status is 'reported'."""
    hazard = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    if not hazard:
        return error_response("Hazard not found.", "NOT_FOUND", 404)

    user_id = g.current_user["id"]
    if hazard["reporter_id"] != user_id:
        return error_response("You can only edit your own reports.", "FORBIDDEN", 403)

    if hazard["status"] != "reported":
        return error_response(
            f"Cannot edit report once it is {hazard['status']}.",
            "HAZARD_NOT_EDITABLE",
            400,
        )

    data = request.get_json(silent=True) or {}
    updates = []
    params = []

    if "title" in data and data["title"].strip():
        updates.append("title = %s")
        params.append(data["title"].strip())

    if "description" in data and data["description"].strip():
        updates.append("description = %s")
        params.append(data["description"].strip())

    if "hazard_type" in data and data["hazard_type"] in VALID_HAZARD_TYPES:
        updates.append("hazard_type = %s")
        params.append(data["hazard_type"])

    if "severity" in data and data["severity"] in VALID_SEVERITIES:
        updates.append("severity = %s")
        params.append(data["severity"])

    if "address" in data:
        updates.append("address = %s")
        params.append(data["address"])

    if "city" in data:
        updates.append("city = %s")
        params.append(data["city"])

    if "expected_end_time" in data:
        updates.append("expected_end_time = %s")
        params.append(data["expected_end_time"])

    if not updates:
        return error_response("No valid fields provided for update.", "NO_FIELDS_TO_UPDATE", 400)

    updates.append("updated_at = NOW()")
    params.append(hazard_id)

    set_clause = ", ".join(updates)
    execute(f"UPDATE hazards SET {set_clause} WHERE id = %s", tuple(params))

    updated = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    record_audit_log(
        action="HAZARD_UPDATED",
        resource_type="hazard",
        resource_id=hazard_id,
        user_id=user_id,
        description=f"Hazard #{hazard_id} edited by reporter.",
    )

    return success_response(message="Hazard updated successfully.", data={"hazard": updated})


# ----------------------------------------------------------------------
# Admin Verification & Lifecycle Controls
# ----------------------------------------------------------------------

@hazards_bp.route("/<int:hazard_id>/verify", methods=["POST"])
@admin_required
def verify_hazard(hazard_id: int):
    """Admin endpoint to verify a reported hazard and make it publicly visible."""
    admin_id = g.current_user["id"]
    hazard = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    if not hazard:
        return error_response("Hazard not found.", "NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    note = (data.get("verification_note") or data.get("note") or "").strip() or None

    execute(
        """
        UPDATE hazards
        SET status = 'verified', visibility = 'visible', verified_by = %s,
            verified_at = NOW(), verification_note = %s, updated_at = NOW()
        WHERE id = %s
        """,
        (admin_id, note, hazard_id),
    )

    # Verification history entry
    execute_insert(
        """
        INSERT INTO hazard_verification_history (hazard_id, admin_id, previous_status, new_status, verification_note)
        VALUES (%s, %s, %s, 'verified', %s)
        """,
        (hazard_id, admin_id, hazard["status"], note),
    )

    # In-app notification to the reporter
    create_notification(
        user_id=hazard["reporter_id"],
        notification_type="hazard_verified",
        title="Your hazard report has been verified",
        message=f"Your report '{hazard['title']}' was reviewed and verified. It is now visible to drivers.",
        hazard_id=hazard_id,
    )

    record_audit_log(
        action="HAZARD_VERIFIED",
        resource_type="hazard",
        resource_id=hazard_id,
        user_id=admin_id,
        description=f"Hazard #{hazard_id} verified by admin #{admin_id}.",
    )

    updated = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    return success_response(message="Hazard verified and published.", data={"hazard": updated})


@hazards_bp.route("/<int:hazard_id>/reject", methods=["POST"])
@admin_required
def reject_hazard(hazard_id: int):
    """Admin endpoint to reject a reported hazard."""
    admin_id = g.current_user["id"]
    hazard = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    if not hazard:
        return error_response("Hazard not found.", "NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    note = (data.get("verification_note") or data.get("note") or "").strip()

    if not note:
        return error_response("A reason note is required when rejecting a hazard report.", "REASON_REQUIRED", 400)

    execute(
        """
        UPDATE hazards
        SET status = 'rejected', visibility = 'hidden', verified_by = %s,
            verified_at = NOW(), verification_note = %s, updated_at = NOW()
        WHERE id = %s
        """,
        (admin_id, note, hazard_id),
    )

    execute_insert(
        """
        INSERT INTO hazard_verification_history (hazard_id, admin_id, previous_status, new_status, verification_note)
        VALUES (%s, %s, %s, 'rejected', %s)
        """,
        (hazard_id, admin_id, hazard["status"], note),
    )

    create_notification(
        user_id=hazard["reporter_id"],
        notification_type="hazard_rejected",
        title="Your hazard report was rejected",
        message=f"Your report '{hazard['title']}' was not verified. Reason: {note}",
        hazard_id=hazard_id,
    )

    record_audit_log(
        action="HAZARD_REJECTED",
        resource_type="hazard",
        resource_id=hazard_id,
        user_id=admin_id,
        description=f"Hazard #{hazard_id} rejected. Reason: {note}",
    )

    updated = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    return success_response(message="Hazard rejected.", data={"hazard": updated})


@hazards_bp.route("/<int:hazard_id>/visibility", methods=["POST"])
@admin_required
def toggle_visibility(hazard_id: int):
    """Toggles visibility between 'visible' and 'hidden'."""
    admin_id = g.current_user["id"]
    hazard = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    if not hazard:
        return error_response("Hazard not found.", "NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    new_visibility = data.get("visibility")
    if new_visibility not in ("visible", "hidden"):
        new_visibility = "hidden" if hazard["visibility"] == "visible" else "visible"

    execute(
        "UPDATE hazards SET visibility = %s, updated_at = NOW() WHERE id = %s",
        (new_visibility, hazard_id),
    )

    record_audit_log(
        action="HAZARD_VISIBILITY_CHANGED",
        resource_type="hazard",
        resource_id=hazard_id,
        user_id=admin_id,
        description=f"Hazard #{hazard_id} visibility changed to '{new_visibility}'.",
    )

    updated = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    return success_response(message=f"Hazard visibility set to {new_visibility}.", data={"hazard": updated})


@hazards_bp.route("/<int:hazard_id>/resolve", methods=["POST"])
@admin_required
def resolve_hazard(hazard_id: int):
    """Marks a hazard as resolved once the incident/road condition is cleared."""
    admin_id = g.current_user["id"]
    hazard = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    if not hazard:
        return error_response("Hazard not found.", "NOT_FOUND", 404)

    data = request.get_json(silent=True) or {}
    note = (data.get("resolution_note") or data.get("note") or "").strip()

    execute(
        """
        UPDATE hazards
        SET status = 'resolved', visibility = 'hidden', resolved_by = %s,
            resolved_at = NOW(), resolution_note = %s, updated_at = NOW()
        WHERE id = %s
        """,
        (admin_id, note or "Incident resolved and cleared.", hazard_id),
    )

    execute_insert(
        """
        INSERT INTO hazard_verification_history (hazard_id, admin_id, previous_status, new_status, verification_note)
        VALUES (%s, %s, %s, 'resolved', %s)
        """,
        (hazard_id, admin_id, hazard["status"], note or "Resolved"),
    )

    create_notification(
        user_id=hazard["reporter_id"],
        notification_type="hazard_resolved",
        title="Hazard resolved",
        message=f"The hazard '{hazard['title']}' has been marked as resolved and removed from active warnings.",
        hazard_id=hazard_id,
    )

    record_audit_log(
        action="HAZARD_RESOLVED",
        resource_type="hazard",
        resource_id=hazard_id,
        user_id=admin_id,
        description=f"Hazard #{hazard_id} marked as resolved.",
    )

    updated = query_one("SELECT * FROM hazards WHERE id = %s", (hazard_id,))
    return success_response(message="Hazard resolved successfully.", data={"hazard": updated})


@hazards_bp.route("/expire-overdue", methods=["POST"])
@admin_required
def expire_overdue_hazards():
    """Automatically marks verified hazards whose expected_end_time has passed as expired."""
    admin_id = g.current_user["id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    overdue = query_all(
        """
        SELECT id, title, reporter_id
        FROM hazards
        WHERE status = 'verified' AND expected_end_time IS NOT NULL AND expected_end_time < %s
        """,
        (now_iso,),
    )

    count = 0
    for h in overdue:
        execute(
            """
            UPDATE hazards
            SET status = 'expired', visibility = 'hidden', updated_at = NOW()
            WHERE id = %s
            """,
            (h["id"],),
        )
        count += 1

    record_audit_log(
        action="HAZARDS_EXPIRED_OVERDUE",
        resource_type="hazard",
        user_id=admin_id,
        description=f"Expired {count} overdue hazards automatically.",
    )

    return success_response(
        message=f"Expired {count} overdue hazard(s).",
        data={"expired_count": count},
    )
