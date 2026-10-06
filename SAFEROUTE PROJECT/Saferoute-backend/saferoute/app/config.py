"""
SafeRoute Configuration
========================
All secrets and environment-specific values (database URL, secret
key, external API keys) are loaded from environment variables.
Provides graceful local defaults for seamless evaluation and testing.
"""

import os
import secrets
from dotenv import load_dotenv

# Load variables from a .env file if present
load_dotenv()


class BaseConfig:
    """Common configuration shared by all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    REQUIRE_SECRET_KEY = False
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", 168))  # 7 days

    # Database URL: PostgreSQL if configured, or SQLite fallback
    DATABASE_URL = os.environ.get("DATABASE_URL")
    SQLITE_DB_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saferoute.db"
    )

    # External routing API configuration
    ROUTING_API_KEY = os.environ.get("ROUTING_API_KEY")
    ROUTING_API_URL = os.environ.get("ROUTING_API_URL")

    # Default radius (in kilometers) used for route-hazard matching
    ROUTE_HAZARD_MATCH_RADIUS_KM = float(
        os.environ.get("ROUTE_HAZARD_MATCH_RADIUS_KM", 1.0)
    )

    # Duplicate hazard distance threshold (km) and time window (hours)
    DUPLICATE_DISTANCE_KM = float(os.environ.get("DUPLICATE_DISTANCE_KM", 0.5))
    DUPLICATE_WINDOW_HOURS = int(os.environ.get("DUPLICATE_WINDOW_HOURS", 24))

    # JSON responses should preserve key order
    JSON_SORT_KEYS = False

    DEBUG = False
    TESTING = False


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    DATABASE_URL = None



class ProductionConfig(BaseConfig):
    SECRET_KEY = os.environ.get("SECRET_KEY")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    REQUIRE_SECRET_KEY = True
    DEBUG = False


_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(config_name: str = None):
    """Resolves which configuration class to use."""
    name = config_name or os.environ.get("FLASK_ENV", "development")
    return _CONFIG_MAP.get(name, DevelopmentConfig)
