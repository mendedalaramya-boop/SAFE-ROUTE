"""
Authentication & Authorization Middleware
============================================
Handles JWT token generation, verification, and route protection decorators.
Ensures stateless, secure API access with role-based authorization.
"""

from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import request, current_app, g
import jwt

from app.utils.responses import error_response
from app.utils.db import query_one


def generate_jwt_token(user: dict) -> str:
    """Generates a signed JWT access token containing essential user claims."""
    secret = current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("SECRET_KEY")
    exp_hours = current_app.config.get("JWT_EXPIRATION_HOURS", 168)
    exp = datetime.now(timezone.utc) + timedelta(hours=exp_hours)

    payload = {
        "sub": str(user["id"]),
        "user_id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "user"),
        "exp": exp,
        "iat": datetime.now(timezone.utc),
    }

    token = jwt.encode(payload, secret, algorithm="HS256")
    return token if isinstance(token, str) else token.decode("utf-8")


def decode_jwt_token(token: str) -> dict:
    """Decodes and validates a JWT access token."""
    secret = current_app.config.get("JWT_SECRET_KEY") or current_app.config.get("SECRET_KEY")
    return jwt.decode(token, secret, algorithms=["HS256"])


def token_required(f):
    """Decorator protecting routes requiring an authenticated session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return error_response(
                "Authentication is required to access this resource.",
                "UNAUTHORIZED",
                401,
            )

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return error_response(
                "Invalid Authorization header format. Expected 'Bearer <token>'.",
                "INVALID_TOKEN_FORMAT",
                401,
            )

        token = parts[1]
        try:
            payload = decode_jwt_token(token)
        except jwt.ExpiredSignatureError:
            return error_response(
                "Your session has expired. Please log in again.",
                "TOKEN_EXPIRED",
                401,
            )
        except jwt.InvalidTokenError:
            return error_response(
                "Invalid authentication token.",
                "INVALID_TOKEN",
                401,
            )

        user_id = payload.get("user_id")
        user = query_one(
            "SELECT id, name, email, role, account_status FROM users WHERE id = %s",
            (user_id,),
        )

        if not user:
            return error_response(
                "The account associated with this session no longer exists.",
                "USER_NOT_FOUND",
                401,
            )

        if user.get("account_status") != "active":
            return error_response(
                f"Your account is {user.get('account_status')}. Please contact support.",
                "ACCOUNT_NOT_ACTIVE",
                403,
            )

        # Attach authenticated user to Flask's request context global `g`
        g.current_user = user
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    """Decorator protecting routes requiring an administrator role."""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if g.current_user.get("role") != "admin":
            return error_response(
                "Administrator privileges are required to perform this action.",
                "FORBIDDEN",
                403,
            )
        return f(*args, **kwargs)

    return decorated


def reporter_required(f):
    """Decorator allowing verified reporters or administrators."""
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if g.current_user.get("role") not in ("reporter", "admin"):
            return error_response(
                "Reporter or administrator privileges are required.",
                "FORBIDDEN",
                403,
            )
        return f(*args, **kwargs)

    return decorated
