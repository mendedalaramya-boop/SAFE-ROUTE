# SafeRoute — Intelligent Emergency Route & Hazard Information Platform

SafeRoute is a full-stack emergency routing and crowd-sourced hazard management platform designed to help commuters and emergency responders navigate around road hazards (such as potholes, waterlogging, accidents, road closures, and construction).

---

## 🚀 Quick Start (Zero-Config)

### Option 1: One-Click Launch (Recommended)
- **Windows:** Double-click [`RUN_SAFEROUTE.bat`](RUN_SAFEROUTE.bat)
- **Mac / Linux:** Run `bash run_saferoute.sh` in your terminal.

The script automatically sets up the local Python environment, installs dependencies, launches the server, and opens your browser at **`http://127.0.0.1:5001`**.

---

### Option 2: Manual Terminal Launch
```bash
# 1. Navigate to the backend directory
cd "Saferoute-backend/saferoute"

# 2. Create and activate a virtual environment
python -m venv ../venv
# Windows:
..\venv\Scripts\activate
# Mac/Linux:
source ../venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application
python run.py
```
Open **`http://127.0.0.1:5001`** in any web browser.

---

## Local Demo Data

On a fresh local SQLite database, demo accounts and sample hazards are seeded only when `DEMO_ADMIN_PASSWORD` and `DEMO_USER_PASSWORD` are configured in `Saferoute-backend/saferoute/.env`. Choose local-only passwords; no demo passwords are published. Without these values, create an account through the registration page.

---

## 🛠️ System Architecture

- **Frontend:** Responsive vanilla HTML5, modern CSS3 (glassmorphic dark/light design system), Leaflet.js interactive maps, OpenStreetMap tiles.
- **Backend:** Python 3.10+ / Flask application factory architecture with modular blueprints (`/api/auth`, `/api/hazards`, `/api/routes`, `/api/admin`, `/api/notifications`).
- **Database:** Dual-engine architecture with automatic SQLite fallback for local development and full PostgreSQL compatibility via `DATABASE_URL`. Local database files are excluded from uploads.
- **Geospatial & Routing:** High-accuracy real road network routing powered by OSRM (OpenStreetMap Routing Machine) with 750+ waypoints, Haversine point-to-polyline hazard corridor collision detection, and automated 500m duplicate hazard detection.
- **Security:** JWT authentication, bcrypt password hashing, input sanitization, and Role-Based Access Control (RBAC) protecting all administrative actions.

---

## 📦 Project Structure

```
SAFEROUTE PROJECT/
├── RUN_SAFEROUTE.bat         # 1-click Windows launcher
├── run_saferoute.sh          # 1-click Mac/Linux launcher
├── README.md                 # Project guide & instructions
├── frontend/                 # Client UI (served directly by Flask)
│   ├── index.html            # Hazard dashboard & modal report submission
│   ├── route.html            # Route search with interactive map & corridor alerts
│   ├── profile.html          # User profile view, details update & password change
│   ├── notifications.html    # In-app alert inbox & notification management
│   ├── admin.html            # Admin verification, analytics dashboard & audit logs
│   ├── login.html            # User & administrator sign-in
│   ├── register.html         # Commuter registration
│   ├── css/styles.css        # Unified responsive styling & design system
│   └── js/                   # Modular client scripts (api, auth, hazards, route, profile, admin)
└── Saferoute-backend/
    └── saferoute/
        ├── run.py            # Server entrypoint
        ├── requirements.txt  # Python package dependencies
        ├── saferoute.db      # Local-only database; excluded from uploads
        ├── app/              # Application factory & modules
        │   ├── routes/       # Auth, Hazards, Routes, Admin, Notifications
        │   ├── services/     # OSRM road routing engine
        │   ├── geospatial/   # Haversine & corridor collision logic
        │   ├── middleware/   # JWT & RBAC authorization guards
        │   └── utils/        # Dual-engine DB layer & notifications
        └── tests/            # Automated end-to-end test suite
```
