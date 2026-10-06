"""
Health-Check Endpoint
======================
A minimal endpoint used to confirm that:
    1. The Flask server is running.
    2. The PostgreSQL database is reachable (optional detail).

This is typically the very first endpoint tested with Postman when
setting up a new environment, and it's useful later for uptime
monitoring.
"""

from flask import Blueprint

from app.utils.db import db_is_available
from app.utils.responses import success_response

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health_check():
    """
    GET /api/health

    Response:
        {
            "success": true,
            "message": "SafeRoute API is running",
            "data": {
                "database": "connected" | "unavailable"
            }
        }
    """
    database_status = "connected" if db_is_available() else "unavailable"

    return success_response(
        message="SafeRoute API is running",
        data={"database": database_status},
    )
