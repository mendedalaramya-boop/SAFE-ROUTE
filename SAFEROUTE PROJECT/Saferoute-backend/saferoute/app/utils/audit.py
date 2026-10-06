"""
Audit Logging Utility
======================
Provides a helper to record security, administrative, and lifecycle actions
into the audit_logs table.
"""

import logging
from typing import Optional
from app.utils.db import execute_insert

logger = logging.getLogger(__name__)


def record_audit_log(
    action: str,
    resource_type: str,
    resource_id: Optional[int] = None,
    user_id: Optional[int] = None,
    description: Optional[str] = None,
) -> None:
    """Inserts a structured audit log entry."""
    try:
        execute_insert(
            """
            INSERT INTO audit_logs (user_id, action, resource_type, resource_id, description)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, action, resource_type, resource_id, description),
        )
    except Exception as exc:
        logger.error("Failed to write audit log entry (%s): %s", action, exc)
