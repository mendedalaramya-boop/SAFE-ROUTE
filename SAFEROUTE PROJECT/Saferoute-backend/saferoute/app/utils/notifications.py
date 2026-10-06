"""
Notification Creation Utility
==============================
Generates in-app notifications for users regarding hazard reports and route alerts.
"""

import logging
from typing import Optional
from app.utils.db import execute_insert

logger = logging.getLogger(__name__)


def create_notification(
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    hazard_id: Optional[int] = None,
) -> Optional[int]:
    """Creates an in-app notification row."""
    try:
        nid = execute_insert(
            """
            INSERT INTO notifications (user_id, hazard_id, notification_type, title, message, is_read)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            """,
            (user_id, hazard_id, notification_type, title, message),
        )
        return nid
    except Exception as exc:
        logger.error("Failed to create notification for user %s: %s", user_id, exc)
        return None
