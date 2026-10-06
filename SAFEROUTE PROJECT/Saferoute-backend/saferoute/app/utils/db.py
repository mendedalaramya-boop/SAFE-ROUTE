"""
Database Connection and Query Utility
=======================================
Dual-engine database manager for SafeRoute:
- Connects to PostgreSQL via psycopg2 pool when DATABASE_URL points to PostgreSQL
  and the server is reachable.
- Gracefully falls back to SQLite when PostgreSQL is not configured or unavailable,
  enabling immediate zero-configuration local runs and testing.
- Normalizes query execution, placeholder syntax (%s vs ?), and dictionary row mapping.
- Auto-seeds initial admin and demo hazard data on first run so the platform is
  fully interactive out-of-the-box.
"""

import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

# Engine type: 'postgres' or 'sqlite'
_db_engine = "sqlite"
_pg_pool = None
_sqlite_path = None


def init_db_pool(app):
    """Initializes the database connection pool or SQLite engine."""
    global _db_engine, _pg_pool, _sqlite_path

    database_url = app.config.get("DATABASE_URL")
    sqlite_path = app.config.get("SQLITE_DB_PATH")
    _sqlite_path = sqlite_path

    # Attempt PostgreSQL if DATABASE_URL starts with postgresql:// or postgres://
    if database_url and (
        database_url.startswith("postgresql://") or database_url.startswith("postgres://")
    ):
        try:
            import psycopg2
            from psycopg2 import pool

            _pg_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=database_url,
            )
            # Test connectivity
            conn = _pg_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            _pg_pool.putconn(conn)
            _db_engine = "postgres"
            logger.info("Connected to PostgreSQL successfully via connection pool.")
            _ensure_postgres_schema()
            _seed_initial_data()
            return
        except Exception as exc:
            logger.warning(
                "PostgreSQL connection to '%s' failed: %s. Falling back to local SQLite engine (%s).",
                database_url,
                exc,
                sqlite_path,
            )
            _pg_pool = None

    # Fallback / default to SQLite
    _db_engine = "sqlite"
    logger.info("SafeRoute database initialized in SQLite mode: %s", _sqlite_path)
    _ensure_sqlite_schema()
    _seed_initial_data()


def get_db_engine() -> str:
    return _db_engine


def close_db_pool():
    """Closes all connections in the pool."""
    global _pg_pool
    if _pg_pool is not None:
        try:
            _pg_pool.closeall()
        except Exception:
            pass
        _pg_pool = None
        logger.info("Database connection pool closed.")


@contextmanager
def get_db_connection():
    """Yields a database connection."""
    if _db_engine == "postgres" and _pg_pool is not None:
        conn = _pg_pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pg_pool.putconn(conn)
    else:
        conn = sqlite3.connect(_sqlite_path or "saferoute.db")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def db_is_available() -> bool:
    """Verifies database connectivity."""
    try:
        with get_db_connection() as conn:
            if _db_engine == "postgres":
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
            else:
                cur = conn.cursor()
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False


def _normalize_sql(sql: str) -> str:
    """Adapts PostgreSQL SQL statements for SQLite if needed."""
    if _db_engine == "postgres":
        return sql

    # Translate %s placeholder to ? for SQLite
    # Careful: avoid replacing formatting inside string literals
    adapted = re.sub(r"%s", "?", sql)

    # SQLite adaptations:
    # Remove PostgreSQL 'RETURNING id' or 'RETURNING *' if present in INSERT/UPDATE
    adapted = re.sub(r"\s+RETURNING\s+[\w\s\*,\.]+", "", adapted, flags=re.IGNORECASE)

    # Replace NOW() with CURRENT_TIMESTAMP
    adapted = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", adapted, flags=re.IGNORECASE)

    # Replace ILIKE with LIKE (SQLite LIKE is case-insensitive for ASCII)
    adapted = re.sub(r"\bILIKE\b", "LIKE", adapted, flags=re.IGNORECASE)

    return adapted


def query_all(sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
    """Executes a SELECT query and returns all matching rows as a list of dicts."""
    norm_sql = _normalize_sql(sql)
    params = params or ()

    with get_db_connection() as conn:
        if _db_engine == "postgres":
            from psycopg2.extras import RealDictCursor

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                # Convert RealDictRow to standard python dict with ISO date strings
                return [_serialize_row(dict(r)) for r in rows]
        else:
            cur = conn.cursor()
            cur.execute(norm_sql, params)
            rows = cur.fetchall()
            return [_serialize_row(dict(r)) for r in rows]


def query_one(sql: str, params: Optional[Tuple[Any, ...]] = None) -> Optional[Dict[str, Any]]:
    """Executes a SELECT query and returns a single matching row as a dict, or None."""
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
    """Executes an INSERT, UPDATE, or DELETE query and returns the affected rowcount."""
    norm_sql = _normalize_sql(sql)
    params = params or ()

    with get_db_connection() as conn:
        if _db_engine == "postgres":
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount
        else:
            cur = conn.cursor()
            cur.execute(norm_sql, params)
            return cur.rowcount


def execute_insert(sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
    """Executes an INSERT query and returns the generated primary key ID."""
    params = params or ()

    with get_db_connection() as conn:
        if _db_engine == "postgres":
            # If query doesn't have RETURNING id, append it
            has_returning = bool(re.search(r"RETURNING\s+id", sql, re.IGNORECASE))
            run_sql = sql if has_returning else f"{sql.rstrip(';')} RETURNING id;"
            with conn.cursor() as cur:
                cur.execute(run_sql, params)
                row = cur.fetchone()
                return row[0] if row else 0
        else:
            norm_sql = _normalize_sql(sql)
            cur = conn.cursor()
            cur.execute(norm_sql, params)
            return cur.lastrowid


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serializes datetime, boolean, and numeric objects for JSON compatibility."""
    res = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            res[k] = v.isoformat()
        elif isinstance(v, int) and (k.startswith("is_") or k.endswith("_read") or k.startswith("has_")):
            res[k] = bool(v)
        else:
            res[k] = v
    return res


# ----------------------------------------------------------------------
# SQLite Schema Initialization & Data Seeding
# ----------------------------------------------------------------------

def _ensure_sqlite_schema():
    """Ensures all necessary tables exist in SQLite with appropriate constraints."""
    with sqlite3.connect(_sqlite_path or "saferoute.db") as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash   TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'user',
                account_status  TEXT NOT NULL DEFAULT 'active',
                created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS hazards (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id             INTEGER NOT NULL REFERENCES users(id),
                hazard_type             TEXT NOT NULL,
                title                   TEXT NOT NULL,
                description             TEXT NOT NULL,
                address                 TEXT,
                city                    TEXT,
                latitude                REAL NOT NULL,
                longitude               REAL NOT NULL,
                severity                TEXT NOT NULL,
                start_time              TEXT NOT NULL,
                expected_end_time       TEXT,
                status                  TEXT NOT NULL DEFAULT 'reported',
                visibility              TEXT NOT NULL DEFAULT 'hidden',
                is_potential_duplicate  INTEGER NOT NULL DEFAULT 0,
                duplicate_of_hazard_id  INTEGER REFERENCES hazards(id),
                verified_by             INTEGER REFERENCES users(id),
                verified_at             TEXT,
                verification_note       TEXT,
                resolved_by             INTEGER REFERENCES users(id),
                resolved_at             TEXT,
                resolution_note         TEXT,
                created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS hazard_verification_history (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                hazard_id           INTEGER NOT NULL REFERENCES hazards(id) ON DELETE CASCADE,
                admin_id            INTEGER NOT NULL REFERENCES users(id),
                previous_status     TEXT NOT NULL,
                new_status          TEXT NOT NULL,
                verification_note   TEXT,
                created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                hazard_id           INTEGER REFERENCES hazards(id) ON DELETE SET NULL,
                notification_type   TEXT NOT NULL,
                title               TEXT NOT NULL,
                message             TEXT NOT NULL,
                is_read             INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER REFERENCES users(id),
                action          TEXT NOT NULL,
                resource_type   TEXT NOT NULL,
                resource_id     INTEGER,
                description     TEXT,
                created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS route_searches (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER REFERENCES users(id),
                origin_latitude     REAL NOT NULL,
                origin_longitude    REAL NOT NULL,
                destination_latitude  REAL NOT NULL,
                destination_longitude REAL NOT NULL,
                distance_km         REAL,
                duration_minutes    REAL,
                hazards_found_count INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()


def _ensure_postgres_schema():
    """Ensures all necessary tables exist in PostgreSQL."""
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id              SERIAL PRIMARY KEY,
        name            VARCHAR(255) NOT NULL,
        email           VARCHAR(255) NOT NULL UNIQUE,
        password_hash   VARCHAR(255) NOT NULL,
        role            VARCHAR(50) NOT NULL DEFAULT 'user',
        account_status  VARCHAR(50) NOT NULL DEFAULT 'active',
        created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS hazards (
        id                      SERIAL PRIMARY KEY,
        reporter_id             INTEGER NOT NULL REFERENCES users(id),
        hazard_type             VARCHAR(50) NOT NULL,
        title                   VARCHAR(255) NOT NULL,
        description             TEXT NOT NULL,
        address                 VARCHAR(255),
        city                    VARCHAR(100),
        latitude                DOUBLE PRECISION NOT NULL,
        longitude               DOUBLE PRECISION NOT NULL,
        severity                VARCHAR(50) NOT NULL,
        start_time              TIMESTAMP WITH TIME ZONE NOT NULL,
        expected_end_time       TIMESTAMP WITH TIME ZONE,
        status                  VARCHAR(50) NOT NULL DEFAULT 'reported',
        visibility              VARCHAR(50) NOT NULL DEFAULT 'hidden',
        is_potential_duplicate  BOOLEAN NOT NULL DEFAULT FALSE,
        duplicate_of_hazard_id  INTEGER REFERENCES hazards(id),
        verified_by             INTEGER REFERENCES users(id),
        verified_at             TIMESTAMP WITH TIME ZONE,
        verification_note       TEXT,
        resolved_by             INTEGER REFERENCES users(id),
        resolved_at             TIMESTAMP WITH TIME ZONE,
        resolution_note         TEXT,
        created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS hazard_verification_history (
        id                  SERIAL PRIMARY KEY,
        hazard_id           INTEGER NOT NULL REFERENCES hazards(id) ON DELETE CASCADE,
        admin_id            INTEGER NOT NULL REFERENCES users(id),
        previous_status     VARCHAR(50) NOT NULL,
        new_status          VARCHAR(50) NOT NULL,
        verification_note   TEXT,
        created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id                  SERIAL PRIMARY KEY,
        user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        hazard_id           INTEGER REFERENCES hazards(id) ON DELETE SET NULL,
        notification_type   VARCHAR(50) NOT NULL,
        title               VARCHAR(255) NOT NULL,
        message             TEXT NOT NULL,
        is_read             BOOLEAN NOT NULL DEFAULT FALSE,
        created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id              SERIAL PRIMARY KEY,
        user_id         INTEGER REFERENCES users(id),
        action          VARCHAR(50) NOT NULL,
        resource_type   VARCHAR(50) NOT NULL,
        resource_id     INTEGER,
        description     TEXT,
        created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS route_searches (
        id                  SERIAL PRIMARY KEY,
        user_id             INTEGER REFERENCES users(id),
        origin_latitude     DOUBLE PRECISION NOT NULL,
        origin_longitude    DOUBLE PRECISION NOT NULL,
        destination_latitude  DOUBLE PRECISION NOT NULL,
        destination_longitude DOUBLE PRECISION NOT NULL,
        distance_km         DOUBLE PRECISION,
        duration_minutes    DOUBLE PRECISION,
        hazards_found_count INTEGER NOT NULL DEFAULT 0,
        created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    except Exception as exc:
        logger.warning("PostgreSQL schema initialization skipped or failed: %s", exc)



def _seed_initial_data():
    """Seeds baseline admin and user accounts along with sample hazards if empty."""
    user_count = query_one("SELECT COUNT(*) as count FROM users")
    if user_count and user_count["count"] > 0:
        return

    admin_password = os.environ.get("DEMO_ADMIN_PASSWORD") or "admin123"
    user_password = os.environ.get("DEMO_USER_PASSWORD") or "user123"
    logger.info("Seeding initial administrator and demo records...")

    admin_hash = generate_password_hash(admin_password)
    admin_id = execute_insert(
        """
        INSERT INTO users (name, email, password_hash, role, account_status)
        VALUES (%s, %s, %s, %s, %s)
        """,
        ("SafeRoute Administrator", "admin@saferoute.com", admin_hash, "admin", "active"),
    )

    user_hash = generate_password_hash(user_password)
    user_id = execute_insert(
        """
        INSERT INTO users (name, email, password_hash, role, account_status)
        VALUES (%s, %s, %s, %s, %s)
        """,
        ("Asha Rao", "user@saferoute.com", user_hash, "user", "active"),
    )

    now_iso = datetime.now(timezone.utc).isoformat()

    # 3. Seed Verified Hazards across typical routes
    demo_hazards = [
        (
            admin_id,
            "flooding",
            "Waterlogged Underpass on NH16",
            "Severe waterlogging under the railway bridge on NH16. Water depth around 2.5 feet, impassable for two-wheelers and compact cars.",
            "Benz Circle Underpass, NH16",
            "Vijayawada",
            16.5062,
            80.6480,
            "high",
            now_iso,
            None,
            "verified",
            "visible",
            admin_id,
            now_iso,
            "Verified by Vijayawada Municipal traffic control room.",
        ),
        (
            user_id,
            "road_closure",
            "Flyover Maintenance & Lane Closure",
            "Kanakadurga Varadhi flyover ongoing surface resurfacing. Outbound lanes towards Guntur restricted to single lane.",
            "Kanakadurga Varadhi, Krishna River Crossing",
            "Vijayawada",
            16.5140,
            80.6120,
            "medium",
            now_iso,
            None,
            "verified",
            "visible",
            admin_id,
            now_iso,
            "Confirmed by AP Highway Authority bulletin.",
        ),
        (
            user_id,
            "accident",
            "Multi-Vehicle Collision near Auto Nagar",
            "Heavy truck and bus collision causing significant blockage on the bypass road. Tow trucks on scene.",
            "Auto Nagar Gate No. 3, Inner Ring Road",
            "Vijayawada",
            16.4950,
            80.6720,
            "critical",
            now_iso,
            None,
            "verified",
            "visible",
            admin_id,
            now_iso,
            "Emergency services responding.",
        ),
        (
            user_id,
            "construction",
            "Metro Pipeline Excavation",
            "Trench dug along the service road for municipal water pipe replacement. Loose gravel on tarmac.",
            "BRTS Road, near Machavaram Down",
            "Vijayawada",
            16.5200,
            80.6350,
            "low",
            now_iso,
            None,
            "verified",
            "visible",
            admin_id,
            now_iso,
            "Inspected and flagged with barricades.",
        ),
        (
            user_id,
            "blocked_road",
            "Fallen Tree Blocking Roadway",
            "Large banyan tree branch fell across the lane following strong winds near Guntur Bus Stand.",
            "Old Club Road, Near RTC Complex",
            "Guntur",
            16.3067,
            80.4365,
            "medium",
            now_iso,
            None,
            "reported",
            "hidden",
            None,
            None,
            None,
        ),
    ]

    for h in demo_hazards:
        hid = execute_insert(
            """
            INSERT INTO hazards (
                reporter_id, hazard_type, title, description, address, city,
                latitude, longitude, severity, start_time, expected_end_time,
                status, visibility, verified_by, verified_at, verification_note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            h,
        )

        # Add verification history for verified ones
        if h[11] == "verified":
            execute_insert(
                """
                INSERT INTO hazard_verification_history (
                    hazard_id, admin_id, previous_status, new_status, verification_note, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (hid, admin_id, "reported", "verified", h[15], now_iso),
            )

    # 4. Seed notifications
    execute_insert(
        """
        INSERT INTO notifications (user_id, notification_type, title, message, is_read, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            user_id,
            "hazard_verified",
            "Your report was verified",
            "Your report 'Flyover Maintenance & Lane Closure' has been reviewed and verified by an administrator. It is now visible to drivers on that route.",
            False,
            now_iso,
        ),
    )
    execute_insert(
        """
        INSERT INTO notifications (user_id, notification_type, title, message, is_read, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            user_id,
            "route_hazard_alert",
            "Route alert near NH16",
            "A high-severity flooding hazard was reported along your frequently searched corridor near Benz Circle.",
            True,
            now_iso,
        ),
    )

    # 5. Seed initial audit log
    execute_insert(
        """
        INSERT INTO audit_logs (user_id, action, resource_type, resource_id, description, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (admin_id, "SYSTEM_INIT", "platform", 1, "Platform initial setup and seeding completed successfully.", now_iso),
    )

    logger.info("Database seeding completed successfully.")
