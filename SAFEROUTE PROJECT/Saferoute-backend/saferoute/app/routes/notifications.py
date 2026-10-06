"""
Notification Routes
====================
Provides user notification retrieval, unread tracking, and mark-as-read actions.
"""

from flask import Blueprint, request, g

from app.utils.responses import success_response, error_response
from app.utils.db import query_all, query_one, execute
from app.middleware.auth import token_required

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("", methods=["GET"])
@token_required
def list_notifications():
    """Lists notifications for the current user, optionally filtered to unread only."""
    user_id = g.current_user["id"]
    unread_only = request.args.get("unread_only", "").lower() in ("true", "1", "yes")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    where_clauses = ["user_id = %s"]
    params = [user_id]

    if unread_only:
        where_clauses.append("is_read = FALSE")

    where_sql = "WHERE " + " AND ".join(where_clauses)
    sql = f"""
        SELECT id, user_id, hazard_id, notification_type, title, message, is_read, created_at
        FROM notifications
        {where_sql}
        ORDER BY created_at DESC
        LIMIT {limit} OFFSET {offset}
    """
    notifications = query_all(sql, tuple(params))

    unread_row = query_one(
        "SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = FALSE",
        (user_id,),
    )
    unread_count = unread_row["count"] if unread_row else 0

    return success_response(
        data={
            "notifications": notifications,
            "count": len(notifications),
            "unread_count": unread_count,
        }
    )


@notifications_bp.route("/<int:notification_id>/read", methods=["PATCH"])
@token_required
def mark_read(notification_id: int):
    """Marks a single notification as read."""
    user_id = g.current_user["id"]
    notification = query_one(
        "SELECT * FROM notifications WHERE id = %s AND user_id = %s",
        (notification_id, user_id),
    )
    if not notification:
        return error_response("Notification not found.", "NOT_FOUND", 404)

    execute(
        "UPDATE notifications SET is_read = TRUE WHERE id = %s",
        (notification_id,),
    )

    updated = query_one("SELECT * FROM notifications WHERE id = %s", (notification_id,))
    return success_response(message="Notification marked as read.", data={"notification": updated})


@notifications_bp.route("/mark-all-read", methods=["POST"])
@token_required
def mark_all_read():
    """Marks all unread notifications for the user as read."""
    user_id = g.current_user["id"]
    count = execute(
        "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
        (user_id,),
    )
    return success_response(message=f"Marked {count} notification(s) as read.")
