"""
SafeRoute Migration Runner
============================
This project does not use an ORM (see app/utils/db.py for why), so we
also don't use an ORM's migration tool (like Alembic). Instead, this
is a small, transparent script that:

    1. Ensures a `schema_migrations` table exists (tracks which
       migration files have already been applied).
    2. Reads every *.sql file from the migrations/ folder, sorted by
       filename (hence the 001_, 002_, 003_... prefixes).
    3. Applies any file not yet recorded in `schema_migrations`, in
       order, each inside its own transaction.
    4. Records successfully applied files so re-running this script
       is always safe (it will skip anything already applied).

This is intentionally simple so a student can read this entire file
during a viva and explain exactly how the schema gets created.

Usage:
    python scripts/migrate.py
"""

import os
import sys
import glob
import logging

import psycopg2
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")

load_dotenv()

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations"
)


def get_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error(
            "DATABASE_URL is not set. Check your .env file (copy it from "
            ".env.example if you haven't already)."
        )
        sys.exit(1)
    return database_url


def ensure_migrations_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename    VARCHAR(255) PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def get_applied_migrations(cur) -> set:
    cur.execute("SELECT filename FROM schema_migrations;")
    return {row[0] for row in cur.fetchall()}


def get_migration_files() -> list:
    pattern = os.path.join(MIGRATIONS_DIR, "*.sql")
    return sorted(glob.glob(pattern))


def run_migrations() -> None:
    database_url = get_database_url()
    conn = psycopg2.connect(database_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            ensure_migrations_table(cur)
            conn.commit()
            already_applied = get_applied_migrations(cur)

        migration_files = get_migration_files()
        if not migration_files:
            logger.warning("No migration files found in %s", MIGRATIONS_DIR)
            return

        pending = [
            path for path in migration_files
            if os.path.basename(path) not in already_applied
        ]

        if not pending:
            logger.info("Database is already up to date. Nothing to apply.")
            return

        for path in pending:
            filename = os.path.basename(path)
            logger.info("Applying migration: %s", filename)

            with open(path, "r", encoding="utf-8") as f:
                sql = f.read()

            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s);",
                        (filename,),
                    )
                conn.commit()
                logger.info("  -> Success.")
            except Exception as exc:
                conn.rollback()
                logger.error("  -> FAILED: %s", exc)
                logger.error(
                    "Migration stopped. Fix the error above and re-run "
                    "this script — already-applied migrations will be "
                    "skipped automatically."
                )
                sys.exit(1)

        logger.info("All migrations applied successfully.")

    finally:
        conn.close()


if __name__ == "__main__":
    run_migrations()
