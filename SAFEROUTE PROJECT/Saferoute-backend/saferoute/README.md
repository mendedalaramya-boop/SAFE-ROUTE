# SafeRoute Backend

**Emergency Route and Hazard Information Platform — Backend API**
_Final-year degree project. Backend-only. Python + Flask + PostgreSQL._

> ⚠️ SafeRoute reports hazards near a route. It never claims a route is
> guaranteed safe.

---

## Project Status: Phase 1 — Flask Foundation

This phase sets up the skeleton of the application:

- Modular Flask project structure (application factory pattern)
- Environment-based configuration (no hardcoded secrets)
- PostgreSQL connection pool
- A `/api/health` endpoint to confirm everything is wired correctly
- Consistent JSON success/error response format
- Global error handlers (no raw stack traces ever reach the client)

Later phases (see project brief) will add authentication, hazard
reporting, verification, geospatial search, route integration,
notifications, reports, and audit logging.

---

## 1. Folder Structure (Phase 1)

```
saferoute/
├── app/
│   ├── __init__.py        # Application factory: create_app()
│   ├── config.py          # Environment-based configuration
│   ├── routes/
│   │   ├── __init__.py
│   │   └── health.py      # GET /api/health
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── db.py          # PostgreSQL connection pool
│   │   └── responses.py   # success_response() / error_response()
│   ├── models/            # (empty for now — Phase 2)
│   ├── services/          # (empty for now — Phase 7)
│   ├── schemas/           # (empty for now — Phase 3/4)
│   ├── auth/              # (empty for now — Phase 3)
│   ├── notifications/     # (empty for now — Phase 9)
│   ├── reports/           # (empty for now — Phase 10)
│   ├── geospatial/        # (empty for now — Phase 6)
│   └── middleware/        # (empty for now — Phase 11)
├── tests/
│   └── __init__.py
├── .env.example
├── .gitignore
├── requirements.txt
├── run.py
└── README.md
```

**Why this structure?**
Each concern (routes, business logic/services, database access,
validation, auth) lives in its own package. This means:
- A student can explain each folder's single responsibility in a viva.
- Adding Phase 2+ features means *adding* files, not rewriting Phase 1.
- Flask "blueprints" (see `health.py`) let each feature register its
  own routes without one giant `app.py`.

---

## 2. Prerequisites

- Python 3.10+
- PostgreSQL 13+ installed and running
- `pip` and (recommended) a virtual environment
- Postman (for API testing)

---

## 3. PostgreSQL Setup

Create a database and a dedicated user (don't use the `postgres`
superuser for the app):

```sql
CREATE DATABASE saferoute;
CREATE USER saferoute_user WITH PASSWORD 'REPLACE_WITH_A_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE saferoute TO saferoute_user;
```

(Optional, for testing) create a second database:

```sql
CREATE DATABASE saferoute_test;
GRANT ALL PRIVILEGES ON DATABASE saferoute_test TO saferoute_user;
```

We are **not** creating any tables yet — that's Phase 2. Phase 1 only
needs the database to *exist* so the connection pool and health-check
can verify connectivity.

---

## 4. Project Setup

```bash
# 1. Move into the project folder
cd saferoute

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your local .env file from the example
cp .env.example .env

# 5. Edit .env and set real values, especially:
#    - SECRET_KEY (generate with the command shown inside .env.example)
#    - DATABASE_URL (matching the PostgreSQL user/db you created above)
```

---

## 5. Running the Server

```bash
python run.py
```

You should see Flask start on `http://localhost:5001`.

If `DATABASE_URL` is missing or wrong, the app will still **start**
(so you can see clear errors), but `/api/health` will report the
database as `unavailable` instead of `connected`.

---

## 6. Testing with Postman

### Request

```
GET http://localhost:5001/api/health
```

No authentication or body required.

### Expected Response (database connected)

```json
{
    "success": true,
    "message": "SafeRoute API is running",
    "data": {
        "database": "connected"
    }
}
```
Status: `200 OK`

### Expected Response (database NOT connected)

```json
{
    "success": true,
    "message": "SafeRoute API is running",
    "data": {
        "database": "unavailable"
    }
}
```
Status: `200 OK` — the API itself is up even if the DB isn't, which is
useful for distinguishing "Flask is down" from "Flask is up, DB is
down" while debugging.

### Testing error handling

Try a route that doesn't exist:

```
GET http://localhost:5000/api/does-not-exist
```

Expected:
```json
{
    "success": false,
    "message": "The requested resource was not found.",
    "error": "NOT_FOUND"
}
```
Status: `404`

---

## 7. Common Errors and Solutions

| Symptom | Likely Cause | Fix |
|---|---|---|
| `RuntimeError: Database pool is not initialized` when hitting an endpoint that needs the DB | `DATABASE_URL` missing/invalid in `.env` | Double-check `.env`, confirm PostgreSQL is running, confirm the DB/user exist |
| `psycopg2.OperationalError: could not connect to server` | PostgreSQL not running, or wrong host/port | Start PostgreSQL; verify `DATABASE_URL` host/port |
| `ModuleNotFoundError: No module named 'app'` | Running `run.py` from the wrong directory | Run commands from inside the `saferoute/` folder |
| `/api/health` returns `database: unavailable` even though PostgreSQL is running | Wrong username/password/db name in `DATABASE_URL`, or user lacks privileges | Recheck the `CREATE USER` / `GRANT` statements above |
| Flask says the port is already in use | Another process is using port 5000 | Run `PORT=5001 python run.py` or stop the other process |

---

## 8. Phase 2 — Database Design

Phase 2 adds the full PostgreSQL schema via a small, transparent
migration runner (no ORM — see `app/utils/db.py` for why).

### Tables created

| Table | Purpose |
|---|---|
| `users` | Accounts, roles (`user`/`reporter`/`admin`), account status |
| `hazards` | Hazard reports: type, severity, location, status, visibility, duplicate flags, verification/resolution info |
| `hazard_verification_history` | Append-only log of every admin verification decision |
| `notifications` | In-app notifications per user |
| `audit_logs` | Platform-wide audit trail of important actions |
| `route_searches` | Optional history of route searches (for reporting/debugging) |
| `schema_migrations` | Internal bookkeeping — tracks which migration files have run |

`hazards.location_point` (a PostGIS `geography` column) is added
**optionally** by migration 008 if the PostGIS extension is available
on your PostgreSQL server. If it isn't, that migration safely skips
itself and logs a notice — nothing else breaks, and later phases fall
back to Haversine-formula distance math on `latitude`/`longitude`.

### Running the migrations

With your virtual environment active and `.env` configured (from
Phase 1):

```bash
python scripts/migrate.py
```

Expected output ends with:
```
INFO: All migrations applied successfully.
```

Running it again is always safe — already-applied migrations are
skipped automatically (tracked in the `schema_migrations` table).

### Verifying in psql

```bash
psql -U saferoute_user -d saferoute -h localhost
```
```sql
\dt
```
You should see all 7 tables listed (plus `schema_migrations`).

### Common Phase 2 errors

| Symptom | Cause | Fix |
|---|---|---|
| `DATABASE_URL is not set` | `.env` missing/not loaded | Confirm `.env` exists and `DATABASE_URL` is filled in |
| `permission denied for schema public` | `saferoute_user` lacks privileges | Re-run the `GRANT ALL PRIVILEGES` statement from Phase 1, or additionally run `GRANT ALL ON SCHEMA public TO saferoute_user;` as the `postgres` superuser |
| `type "user_role" already exists` mid-run | A previous partial run created some objects | Drop the database and recreate it (`DROP DATABASE saferoute;` then redo Phase 1 step 5), then re-run migrations from scratch |
| PostGIS notice: "extension is not available" | PostGIS isn't installed on your PostgreSQL server | This is fine — it's optional. Skip it, or install the `postgresql-<version>-postgis-3` package if you want it |

---

## Roadmap

- [x] Phase 1 — Flask Foundation
- [x] Phase 2 — Database Design
- [ ] Phase 3 — Authentication
- [ ] Phase 4 — Hazard Reporting
- [ ] Phase 5 — Hazard Verification
- [ ] Phase 6 — Hazard Search
- [ ] Phase 7 — Route Integration
- [ ] Phase 8 — Route + Hazard Matching
- [ ] Phase 9 — Notifications
- [ ] Phase 10 — Reports
- [ ] Phase 11 — Security and Audit
- [ ] Phase 12 — Testing
- [ ] Phase 13 — Postman and Documentation
