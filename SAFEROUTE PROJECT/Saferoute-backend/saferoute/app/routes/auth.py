"""
Authentication Routes
======================
Implements user registration, login, logout, and session profile inspection.
"""

import re
from flask import Blueprint, request, g
from werkzeug.security import generate_password_hash, check_password_hash

from app.utils.responses import success_response, error_response
from app.utils.db import query_one, execute_insert, execute
from app.middleware.auth import token_required, generate_jwt_token
from app.utils.audit import record_audit_log

auth_bp = Blueprint("auth", __name__)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_bp.route("/register", methods=["POST"])
def register():
    """Registers a new user account."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name:
        return error_response("Full name is required.", "MISSING_NAME", 400)

    if not email or not EMAIL_REGEX.match(email):
        return error_response("A valid email address is required.", "INVALID_EMAIL", 400)

    if len(password) < 8:
        return error_response("Password must be at least 8 characters long.", "PASSWORD_TOO_SHORT", 400)

    # Check for existing email
    existing = query_one("SELECT id FROM users WHERE LOWER(email) = %s", (email,))
    if existing:
        return error_response(
            "An account with this email already exists.",
            "EMAIL_ALREADY_EXISTS",
            409,
        )

    # Default role is 'user'; if this is the first user ever registered, grant admin
    user_count = query_one("SELECT COUNT(*) as cnt FROM users")
    role = "admin" if (user_count and user_count["cnt"] == 0) else "user"

    password_hash = generate_password_hash(password)
    user_id = execute_insert(
        """
        INSERT INTO users (name, email, password_hash, role, account_status)
        VALUES (%s, %s, %s, %s, 'active')
        """,
        (name, email, password_hash, role),
    )

    created_user = query_one(
        "SELECT id, name, email, role, account_status, created_at FROM users WHERE id = %s",
        (user_id,),
    )

    record_audit_log(
        action="USER_REGISTERED",
        resource_type="user",
        resource_id=user_id,
        user_id=user_id,
        description=f"User {name} ({email}) registered with role {role}.",
    )

    user_data = {
        "id": created_user["id"],
        "name": created_user["name"],
        "email": created_user["email"],
        "role": created_user["role"],
        "account_status": created_user["account_status"],
        "created_at": created_user.get("created_at"),
    }
    token = generate_jwt_token(user_data)

    return success_response(
        message="Account created successfully.",
        data={
            "user": user_data,
            "token": token,
        },
        status_code=201,
    )


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticates a user and returns a signed JWT token."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return error_response("Email and password are required.", "INVALID_CREDENTIALS", 400)

    user = query_one(
        "SELECT id, name, email, password_hash, role, account_status, created_at FROM users WHERE LOWER(email) = %s",
        (email,),
    )

    if not user or not check_password_hash(user["password_hash"], password):
        return error_response("Invalid email or password.", "INVALID_CREDENTIALS", 401)

    if user.get("account_status") != "active":
        return error_response(
            f"Account is {user.get('account_status')}. Please contact support.",
            "ACCOUNT_INACTIVE",
            403,
        )

    # Strip sensitive fields
    user_data = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "account_status": user["account_status"],
        "created_at": user.get("created_at"),
    }

    token = generate_jwt_token(user_data)

    record_audit_log(
        action="USER_LOGIN",
        resource_type="user",
        resource_id=user["id"],
        user_id=user["id"],
        description=f"User {user['email']} logged in successfully.",
    )

    return success_response(
        message="Login successful.",
        data={
            "token": token,
            "user": user_data,
        },
    )


@auth_bp.route("/logout", methods=["POST"])
@token_required
def logout():
    """Logs out the active session."""
    record_audit_log(
        action="USER_LOGOUT",
        resource_type="user",
        resource_id=g.current_user["id"],
        user_id=g.current_user["id"],
        description=f"User {g.current_user['email']} logged out.",
    )
    return success_response(message="Logged out successfully.")


@auth_bp.route("/profile", methods=["GET"])
@token_required
def get_profile():
    """Returns the authenticated user's profile."""
    return success_response(data={"user": g.current_user})


@auth_bp.route("/profile", methods=["PATCH"])
@token_required
def update_profile():
    """Updates the authenticated user's profile information (name, email, password)."""
    user_id = g.current_user["id"]
    data = request.get_json(silent=True) or {}

    current_db_user = query_one(
        "SELECT id, name, email, password_hash, role, account_status, created_at FROM users WHERE id = %s",
        (user_id,),
    )
    if not current_db_user:
        return error_response("User not found.", "NOT_FOUND", 404)

    updates = []
    params = []

    # 1. Update Name
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return error_response("Name cannot be empty.", "MISSING_NAME", 400)
        updates.append("name = %s")
        params.append(name)

    # 2. Update Email
    if "email" in data:
        email = (data["email"] or "").strip().lower()
        if not email or not EMAIL_REGEX.match(email):
            return error_response("A valid email address is required.", "INVALID_EMAIL", 400)
        if email != current_db_user["email"].lower():
            existing = query_one(
                "SELECT id FROM users WHERE LOWER(email) = %s AND id != %s",
                (email, user_id),
            )
            if existing:
                return error_response("An account with this email already exists.", "EMAIL_ALREADY_EXISTS", 409)
            updates.append("email = %s")
            params.append(email)

    # 3. Update Password
    new_password = data.get("password") or data.get("new_password")
    if new_password:
        if len(new_password) < 8:
            return error_response("Password must be at least 8 characters long.", "PASSWORD_TOO_SHORT", 400)

        # If current_password is provided in request, verify it matches
        current_password = data.get("current_password")
        if current_password:
            if not check_password_hash(current_db_user["password_hash"], current_password):
                return error_response("Current password does not match.", "INVALID_CREDENTIALS", 400)

        updates.append("password_hash = %s")
        params.append(generate_password_hash(new_password))

    if not updates:
        return error_response("No valid fields provided for update.", "NO_FIELDS_TO_UPDATE", 400)

    updates.append("updated_at = NOW()")
    params.append(user_id)

    set_sql = ", ".join(updates)
    execute(f"UPDATE users SET {set_sql} WHERE id = %s", tuple(params))

    updated_user = query_one(
        "SELECT id, name, email, role, account_status, created_at, updated_at FROM users WHERE id = %s",
        (user_id,),
    )

    record_audit_log(
        action="USER_PROFILE_UPDATED",
        resource_type="user",
        resource_id=user_id,
        user_id=user_id,
        description=f"User {updated_user['email']} updated profile details.",
    )

    return success_response(
        message="Profile updated successfully.",
        data={"user": updated_user},
    )

