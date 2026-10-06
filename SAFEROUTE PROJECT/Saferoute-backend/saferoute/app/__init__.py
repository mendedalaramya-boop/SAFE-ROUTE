"""
SafeRoute Backend - Application Factory
=========================================
Configures and initializes the Flask application using the factory pattern:
- Environment configuration
- Resilient database engine (PostgreSQL connection pool with automatic SQLite fallback)
- Cross-Origin Resource Sharing (CORS) with preflight handling
- Modular Blueprint registration (Health, Auth, Hazards, Routes, Notifications, Admin)
- Standardized JSON error response envelope
- Automatic unified frontend serving (when opened in browser)
"""

import os
import logging
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from app.config import get_config
from app.utils.db import init_db_pool, close_db_pool


def create_app(config_name: str = None) -> Flask:
    """Creates and configures a Flask application instance."""
    app = Flask(__name__)

    # 1. Load configuration
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    if config_class.REQUIRE_SECRET_KEY and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured when running in production.")

    # 2. Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 3. Setup Cross-Origin Resource Sharing (CORS)
    CORS(
        app,
        resources={r"/api/*": {"origins": "*"}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    )

    # 4. Initialize Database
    init_db_pool(app)

    # 5. Register Blueprints
    from app.routes.health import health_bp
    from app.routes.auth import auth_bp, get_profile, update_profile
    from app.routes.hazards import hazards_bp
    from app.routes.routes import routes_bp
    from app.routes.notifications import notifications_bp
    from app.routes.admin import admin_bp, get_platform_reports, get_reports_dashboard, get_audit_logs

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(hazards_bp, url_prefix="/api/hazards")
    app.register_blueprint(routes_bp, url_prefix="/api/routes")
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    # Frontend convenience aliases:
    app.add_url_rule("/api/profile", endpoint="api_profile_get", view_func=get_profile, methods=["GET"])
    app.add_url_rule("/api/profile", endpoint="api_profile_patch", view_func=update_profile, methods=["PATCH"])
    app.add_url_rule("/api/reports", endpoint="api_reports", view_func=get_platform_reports, methods=["GET"])
    app.add_url_rule("/api/reports/dashboard", endpoint="api_reports_dashboard", view_func=get_reports_dashboard, methods=["GET"])
    app.add_url_rule("/api/audit-logs", endpoint="api_audit_logs", view_func=get_audit_logs, methods=["GET"])

    # 6. Global error handlers for consistent JSON API envelope
    register_error_handlers(app)

    # 7. Unified Frontend Serving
    frontend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
    )
    if os.path.exists(frontend_dir):
        @app.route("/", methods=["GET"])
        def serve_index():
            return send_from_directory(frontend_dir, "index.html")

        @app.route("/<path:path>", methods=["GET"])
        def serve_static_frontend(path):
            if path.startswith("api/"):
                return jsonify({
                    "success": False,
                    "message": "The requested API endpoint was not found.",
                    "error": "NOT_FOUND",
                }), 404
            full_path = os.path.join(frontend_dir, path)
            if os.path.isfile(full_path):
                return send_from_directory(frontend_dir, path)
            return jsonify({
                "success": False,
                "message": "The requested resource was not found.",
                "error": "NOT_FOUND",
            }), 404

    # 8. Teardown hook
    @app.teardown_appcontext
    def _shutdown_db(exception=None):
        pass

    return app


def register_error_handlers(app: Flask) -> None:
    """Registers standard JSON response format for HTTP errors."""

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({
            "success": False,
            "message": getattr(e, "description", "The request could not be understood."),
            "error": "BAD_REQUEST",
        }), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({
            "success": False,
            "message": "Authentication is required to access this resource.",
            "error": "UNAUTHORIZED",
        }), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({
            "success": False,
            "message": "You do not have permission to perform this action.",
            "error": "FORBIDDEN",
        }), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            "success": False,
            "message": "The requested resource was not found.",
            "error": "NOT_FOUND",
        }), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({
            "success": False,
            "message": "This HTTP method is not allowed for this endpoint.",
            "error": "METHOD_NOT_ALLOWED",
        }), 405

    @app.errorhandler(409)
    def conflict(e):
        return jsonify({
            "success": False,
            "message": "The request could not be completed due to a conflict.",
            "error": "CONFLICT",
        }), 409

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify({
            "success": False,
            "message": "Validation failed for the submitted data.",
            "error": "VALIDATION_ERROR",
        }), 422

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.exception("Unhandled server error: %s", e)
        return jsonify({
            "success": False,
            "message": "An unexpected error occurred. Please try again later.",
            "error": "INTERNAL_SERVER_ERROR",
        }), 500
