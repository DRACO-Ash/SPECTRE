# SIPC — Satellite Intercept Planning Console

Real-time orbital manoeuvre planning console for space defence operators.
Accessed through a browser-based operator interface built on FastAPI + HTMX.

## Overview

SIPC provides analysts with a web console for:

- Defining blue/red asset sets (satellites) with TLE propagators
- Computing intercept trajectories using Lambert, Hohmann, and bi-elliptic transfer solvers
- Executing tactical manoeuvres: phasing orbits, CW relative motion (radial separation / along-track drift), plane changes, J2 RAAN drift planning, collision avoidance, and optimal defensive evasion
- Advanced analysis: GEO drift orbit (longitude relocation), NMC passive safety ellipse (proximity ops), manoeuvre classification (space intelligence), and intercept detectability metrics
- Decision support tools: adversary intent prediction, intercept envelope analysis, relative motion stability, manoeuvre fingerprinting, formation defence, orbital terrain mapping, and minimum-time intercept optimisation
- Comparing solutions via a ΔV vs transfer-time trade-space scatter plot
- Detecting orbital events (apogee, perigee, node crossings) via SGP4 propagation
- Reviewing per-burn ΔV breakdowns (VNB frame), miss distances, and scrolling run logs — all without page reloads

All orbital mechanics computations use the pure-Python `sipc.astro` package — no external astrodynamics software required.

---

## Requirements

| Component | Minimum version | Notes |
|-----------|-----------------|-------|
| Python | 3.14 | |
| uvicorn | 0.29 | Bundled via `pip install` |

---

## Quick Start — Local (Windows)

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install in editable mode with dev extras
pip install -e ".[dev]"

# 3. Set required environment variables
$env:SECRET_KEY      = "change-me-to-a-long-random-string"
$env:SIPC_ADMIN_USER = "admin"
$env:SIPC_ADMIN_PASS = "change-me"

# 4. Start the server
sipc-serve
# or equivalently:
uvicorn sipc.web.app:app --reload
```

Then open **http://localhost:8000** in your browser.

### First Login

On first run, SIPC creates the database and inserts a single admin account using the values from `SIPC_ADMIN_USER` / `SIPC_ADMIN_PASS`. Sign in with those credentials.

> If neither env var is set, no bootstrap account is created. You must insert a user manually (see [User Management](#user-management)).

---

## Quick Start — Docker

```bash
# Build the image
docker build -t sipc:latest .

# Run with a named volume for the database
docker run -d \
  -p 8000:8000 \
  -v sipc_data:/app/data \
  -e SECRET_KEY="change-me-to-a-long-random-string" \
  -e SIPC_ADMIN_USER="admin" \
  -e SIPC_ADMIN_PASS="change-me" \
  --name sipc \
  sipc:latest
```

Then open **http://localhost:8000** in your browser.

To use PostgreSQL instead of SQLite, add:

```bash
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host/sipc_db"
```

No code changes are required — the adapter swap is entirely via `DATABASE_URL`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **Yes** | — | Signs session cookies. Use a long random string in production. |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./sipc.db` | SQLAlchemy async connection string. |
| `SIPC_ADMIN_USER` | No | `admin` | Bootstrap admin username (first run only). |
| `SIPC_ADMIN_PASS` | No | — | Bootstrap admin password (first run only). Omit to skip bootstrap. |
| `SIPC_LOG_LEVEL` | No | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `SIPC_LOG_DIR` | No | `logs` | Directory for structlog output files. |

---

## Operator Walkthrough

Once logged in, the operator console has a collapsible sidebar (default 500 px) on the left and an intelligence panel on the right. The nav bar exposes a UDL connection chip:

```
┌──────────────────────────────────────────────────────────────┐
│  [≡] SIPC    [UDL ●]                       [operator] [Logout]│
├──────────────────────┬─────────────────────────────────────────┤
│  SIDEBAR (500px)     │  INTELLIGENCE PANEL                    │
│  ┌ Assets ─────────┐ │  Intercept Engine                      │
│  │ [Red][Blue][HRR]│ │  Threat Sweep                          │
│  │  sub-tabs        │ │  Orbital Events                        │
│  └─────────────────┘ │  Trade-Space Plot                      │
│  Scenario Time        │  Session Log                           │
│  UDL Catalogue Search │                                        │
└──────────────────────┴─────────────────────────────────────────┘
```

### Step-by-step

1. **Connect UDL** — click the **UDL** chip in the nav bar and enter credentials. Once connected, TLE fetch, catalogue search, and HRR watchlist are enabled.

2. **Load the HRR watchlist** — in the UDL panel, click **Fetch HRR Watchlist**. Objects are classified as Blue (friendly nations) or Red (adversary nations) and ranked 0–5 by activity level.

3. **Add assets from the HRR watchlist** — switch to the **HRR** sub-tab inside the Assets panel. Each row in the Blue HRR and Red HRR tables has one-click buttons:
   - **→ Blue** — fetches the TLE from UDL and immediately adds the satellite as a Blue Asset
   - **→ Red** — fetches the TLE from UDL and immediately adds the satellite as a Red Track

   The button is replaced by a confirmation badge on success.

4. **Add assets manually** — use the **Blue** and **Red** sub-tabs in the Assets panel to enter a NORAD catalogue number (Fetch TLE) or paste a TLE directly.

5. **Set scenario time** — define the analysis window (start/stop times) in the Scenario Time panel. Defaults to current UTC + 24 hours.

6. **Compute orbital events** — select a red and/or blue satellite, click **Compute Events**. Apogee, perigee, and node crossings are detected via SGP4 propagation and displayed as clickable badges that auto-populate the manoeuvre start time.

7. **Run intercept calculations** — in the **Intercept Engine** panel, select a red target, a blue asset, and choose a method. Methods are grouped into:
   - **Classical Transfers**: Lambert, Hohmann, Bi-elliptic, Rendezvous, Proximity
   - **Tactical Manoeuvres**: Phasing, CW Radial Separation, CW Along-Track Drift, Plane Change, J2 Drift, COLA, Evasion
   - **Advanced Analysis**: GEO Drift (longitude relocation), NMC (safety ellipse), Manoeuvre Detect (classify TLE changes), Detectability (intercept observability)
   - **Decision Support**: Intent Predict (adversary assessment), Intercept Envelope (reachability analysis), Stability (relative motion), Fingerprint (behavioural classification), Formation Defence (formation-aware COLA), Terrain (orbital regime risk), Min-Time (fastest transfer)

   Set coast and time-of-flight parameters, then click **Calculate Intercept**. The per-burn ΔV breakdown appears with VNB components, arrival epoch, and miss distance.

8. **Run a Threat Sweep** — in the **Threat Sweep** panel:
   - Select a **Target Group** from the dropdown (Blue HRR or Red HRR, by rank 0–5)
   - The dropdown automatically pre-fetches TLEs for the selected group
   - Click **Sweep Targets** to batch-evaluate all objects at 5 orbital epochs (now, apogee, perigee, ascending node, descending node) using Hohmann transfers, then auto-refine the top 5 with Lambert for VNB components
   - Results are ranked by ΔV with one-click refinement per entry

9. **Compare solutions** — run multiple intercept calculations with different methods or parameters. After the second solution, a trade-space scatter plot (ΔV vs transfer time) appears automatically, colour-coded by method. Use this to identify the optimal trade-off.

10. **Review and repeat** — use **Clear History** to reset the trade-space plot. Click × on any asset to remove it. All panel updates are HTMX partial swaps — the page never fully reloads.

---

## Running Tests

```powershell
# Unit tests only (no web server required)
pytest tests/unit/

# Unit tests with coverage report
pytest tests/unit/ --cov=sipc --cov-report=term-missing

# Web integration tests (FastAPI TestClient, in-memory DB)
pytest tests/integration/test_web_routes.py

# Full suite
pytest
```

---

## Generating the Operator Guide

```powershell
python docs/generate_guide.py
```

Outputs `docs/SIPC_Operator_Guide.docx` — a comprehensive 15-section guide formatted per the Bluestaq document style guide (Segoe UI, navy/gold headings, data tables, callout boxes). Covers classical transfers, tactical manoeuvres, advanced analysis (GEO drift, NMC, manoeuvre classification, detectability, evasion), trade-space analysis, and 9 operator scenarios.

---

## Project Structure

```
sipc/                       ← repo root
├── sipc/                   ← importable package
│   ├── astro/              ← pure-Python orbital mechanics (classical transfers, tactical manoeuvres, advanced analysis, decision support, SGP4, events)
│   ├── domain/             ← intercept planning logic
│   │   ├── models.py       ← BlueAsset, RedTrack, RunConfig, InterceptResult,
│   │   │                      BurnResult, ManeuverOption, ManeuverSearchConfig
│   │   ├── scenario.py     ← ScenarioPlanner orchestrator
│   │   └── geometry.py     ← geometry helpers
│   ├── web/                ← FastAPI web console
│   │   ├── app.py          ← application factory + startup
│   │   ├── auth.py         ← session cookies + require_login dependency
│   │   ├── database.py     ← async SQLAlchemy engine + admin bootstrap
│   │   ├── models.py       ← User ORM model
│   │   ├── planning_state.py ← per-session in-memory state (assets, intercept history)
│   │   ├── routes/
│   │   │   ├── login.py    ← GET/POST /login, POST /logout
│   │   │   ├── operator.py ← dashboard, asset CRUD, log
│   │   │   ├── udl.py      ← UDL login/logout, TLE fetch, catalogue search
│   │   │   └── maneuver.py ← intercept engine, orbital events, trade-space data
│   │   ├── templates/      ← Jinja2 HTML (base, login, operator, partials)
│   │   └── static/         ← style.css (Bluestaq dark ops theme), Chart.js, SIPC_logo.svg
│   ├── app_logging/        ← structlog setup + run_id correlation
│   └── config/             ← constants and runtime settings
├── tests/
│   ├── unit/               ← fast tests (auth helpers, state, domain models)
│   └── integration/        ← FastAPI TestClient web route tests
├── docs/                   ← operator guide generator, architecture notes, reference PDFs
├── Dockerfile              ← production container (uvicorn, Python slim)
└── pyproject.toml
```

---

## User Management

SIPC does not currently expose a web UI for user management. To add or modify users, connect to the SQLite database directly:

```powershell
# Open the database (install sqlite3 CLI if needed)
sqlite3 sipc.db

-- List users
SELECT id, username, role, created_at FROM users;

-- Add a new operator (hash must be a bcrypt hash — use a Python snippet below)
```

```python
import bcrypt
print(bcrypt.hashpw(b"operator-password-here", bcrypt.gensalt()).decode())
```

Then insert the hash:

```sql
INSERT INTO users (username, hashed_password, role) VALUES ('newuser', '<hash>', 'operator');
```

---

## Naming Conventions

| Prefix | Meaning |
|--------|---------|
| `B_SAT_` | Blue satellite asset |
| `R_SAT_` | Red track satellite |
| `OUT_` | Run output folders |

All times are UTC. Distances in km, speeds in km/s, angles in degrees.
Coordinate frame: ICRF/J2000.

---

## Architecture

See `docs/architecture.md` for architecture design decisions and adapter pattern details.
