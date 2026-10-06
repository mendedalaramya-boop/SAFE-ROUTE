"""
Administrator Management & Analytics Routes
============================================
Provides admin-only endpoints for:
- Reviewing pending hazard reports
- Viewing and moderating verified hazards
- Platform-wide analytical reporting (hazard stats, severity, geographical distribution)
- Audit log inspection and filtering
"""

from flask import Blueprint, request
from app.utils.responses import success_response
from app.utils.db import query_all, query_one
from app.middleware.auth import admin_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/hazards/pending", methods=["GET"])
@admin_required
def get_pending_hazards():
    """Returns hazards waiting for moderator review, oldest first."""
    hazards = query_all(
        """
        SELECT h.id, h.reporter_id, u.name as reporter_name, u.email as reporter_email,
               h.hazard_type, h.title, h.description, h.address, h.city,
               h.latitude, h.longitude, h.severity, h.start_time, h.expected_end_time,
               h.status, h.visibility, h.is_potential_duplicate, h.duplicate_of_hazard_id,
               h.created_at
        FROM hazards h
        LEFT JOIN users u ON h.reporter_id = u.id
        WHERE h.status IN ('reported', 'under_review')
        ORDER BY h.created_at ASC
        """
    )
    return success_response(data={"hazards": hazards, "count": len(hazards)})


@admin_bp.route("/hazards/verified", methods=["GET"])
@admin_required
def get_verified_hazards():
    """Returns all verified hazards (both visible and hidden) for admin moderation."""
    hazards = query_all(
        """
        SELECT h.id, h.reporter_id, u.name as reporter_name,
               h.hazard_type, h.title, h.description, h.address, h.city,
               h.latitude, h.longitude, h.severity, h.start_time, h.expected_end_time,
               h.status, h.visibility, h.verified_by, h.verified_at, h.verification_note,
               h.created_at
        FROM hazards h
        LEFT JOIN users u ON h.reporter_id = u.id
        WHERE h.status = 'verified'
        ORDER BY h.created_at DESC
        """
    )
    return success_response(data={"hazards": hazards, "count": len(hazards)})


@admin_bp.route("/reports", methods=["GET"])
@admin_bp.route("/reports/dashboard", methods=["GET"])
@admin_required
def get_platform_reports():
    """Generates comprehensive aggregated metrics for platform monitoring."""
    # Status metrics
    status_counts = query_all(
        "SELECT status, COUNT(*) as cnt FROM hazards GROUP BY status"
    )
    status_map = {row["status"]: row["cnt"] for row in status_counts}

    total_hazards = sum(status_map.values())
    pending_count = status_map.get("reported", 0) + status_map.get("under_review", 0)
    verified_count = status_map.get("verified", 0)
    rejected_count = status_map.get("rejected", 0)
    resolved_count = status_map.get("resolved", 0)
    expired_count = status_map.get("expired", 0)

    # By Type
    type_counts = query_all(
        "SELECT hazard_type, COUNT(*) as cnt FROM hazards GROUP BY hazard_type ORDER BY cnt DESC"
    )

    # By Severity
    severity_counts = query_all(
        "SELECT severity, COUNT(*) as cnt FROM hazards GROUP BY severity ORDER BY cnt DESC"
    )

    # By City (top 10)
    city_counts = query_all(
        """
        SELECT COALESCE(NULLIF(city, ''), 'Unknown') as city_name, COUNT(*) as cnt
        FROM hazards
        GROUP BY city_name
        ORDER BY cnt DESC
        LIMIT 10
        """
    )

    # User and Route search metrics
    user_cnt_row = query_one("SELECT COUNT(*) as cnt FROM users")
    total_users = user_cnt_row["cnt"] if user_cnt_row else 0

    route_cnt_row = query_one(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(hazards_found_count), 0) as hazards_sum FROM route_searches"
    )
    total_searches = route_cnt_row["cnt"] if route_cnt_row else 0
    total_hazards_intercepted = route_cnt_row["hazards_sum"] if route_cnt_row else 0

    # Top Reporters
    top_reporters = query_all(
        """
        SELECT u.id, u.name, u.email,
               COUNT(h.id) as report_count,
               SUM(CASE WHEN h.status = 'verified' THEN 1 ELSE 0 END) as verified_count
        FROM users u
        JOIN hazards h ON u.id = h.reporter_id
        GROUP BY u.id, u.name, u.email
        ORDER BY report_count DESC
        LIMIT 10
        """
    )

    # Top Searchers
    top_searchers = query_all(
        """
        SELECT u.id, u.name, u.email,
               COUNT(rs.id) as search_count,
               ROUND(COALESCE(SUM(rs.distance_km), 0), 1) as total_distance_km,
               COALESCE(SUM(rs.hazards_found_count), 0) as total_hazards_intercepted
        FROM users u
        JOIN route_searches rs ON u.id = rs.user_id
        GROUP BY u.id, u.name, u.email
        ORDER BY search_count DESC
        LIMIT 10
        """
    )

    return success_response(
        data={
            "summary": {
                "total_hazards": total_hazards,
                "pending_review": pending_count,
                "verified": verified_count,
                "rejected": rejected_count,
                "resolved": resolved_count,
                "expired": expired_count,
                "total_users": total_users,
                "total_searches": total_searches,
                "total_hazards_intercepted": total_hazards_intercepted,
            },
            "by_type": type_counts,
            "by_severity": severity_counts,
            "by_city": city_counts,
            "top_reporters": top_reporters,
            "top_searchers": top_searchers,
        }
    )


def get_reports_dashboard():
    """Convenience alias for get_platform_reports."""
    return get_platform_reports()


@admin_bp.route("/audit-logs", methods=["GET"])
@admin_required
def get_audit_logs():
    """Returns paginated platform audit logs with user details."""
    action = request.args.get("action", "").strip()
    user_id = request.args.get("user_id")
    limit = min(int(request.args.get("limit", 25)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    where_clauses = []
    params = []

    if action:
        where_clauses.append("a.action LIKE %s")
        params.append(f"%{action}%")

    if user_id:
        try:
            where_clauses.append("a.user_id = %s")
            params.append(int(user_id))
        except ValueError:
            pass

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    logs = query_all(
        f"""
        SELECT a.id, a.user_id, u.name as user_name, u.email as user_email,
               a.action, a.resource_type, a.resource_id, a.description, a.created_at
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        {where_sql}
        ORDER BY a.created_at DESC
        LIMIT {limit} OFFSET {offset}
        """,
        tuple(params),
    )

    total_row = query_one(
        f"SELECT COUNT(*) as count FROM audit_logs a {where_sql}",
        tuple(params),
    )
    total = total_row["count"] if total_row else len(logs)

    return success_response(
        data={
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )
