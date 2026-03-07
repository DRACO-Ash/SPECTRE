# SIPC — STK Intercept Planning Console

Rapid intercept replanning console interfacing with AGI Systems Tool Kit (STK) via COM automation.
Accessed through a browser-based operator interface built on FastAPI + HTMX.

## Overview

SIPC provides analysts with a web console for:

- Defining blue/red asset sets (satellites) with TLE propagators
- Configuring intercept planning runs with full provenance tracking (operator, source, run ID)
- Executing STK scenario updates on-the-fly via the STK Object Model
- Reviewing intercept windows, geometry data, and scrolling run logs — all without page reloads

The application runs as a local or cloud-hosted web server. Operators access it from any browser; no desktop install required.

---

## Requirements

| Component | Minimum version | Notes |
|-----------|-----------------|-------|
| Python | 3.14 | |
| AGI STK | 13.0 | Object Model licence required for live STK |
| pywin32 | 311 | Windows only; skipped automatically without STK |
| uvicorn | 0.29 | Bundled via `pip install` |

> **STK COM is Windows-only.** On Linux / macOS (or in Docker), SIPC falls back to `FakeStkSession`, which returns empty access intervals. All domain and web logic is fully functional without STK.

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
| `SIPC_SCENARIO_PATH` | No | — | Path to `.sc` scenario file passed to STK on connect. |
| `STK_INTEGRATION_TESTS` | No | `0` | Set to `1` to enable live-STK integration tests. |

---

## Operator Walkthrough

Once logged in, the operator console is divided into several panels. The nav bar exposes two connection chips:

```
┌──────────────────────────────────────────────────────────────┐
│  [≡] SIPC    [STK ●] [UDL ●]              [operator] [Logout]│
├───────────────────────────┬──────────────────────────────────┤
│  BLUE ASSETS              │  RED TRACKS                      │
│  (asset list with TLE age)│  (track list with TLE age)       │
│  SATNO [______] [Fetch]   │  SATNO [______] [Fetch]          │
│  [+ Add Blue Asset]       │  [+ Add Red Track]               │
│                           │                                  │
│  HRR WATCHLIST            │  HRR WATCHLIST                   │
│  (sortable UDL HRR table) │  (sortable UDL HRR table)        │
│                           │                                  │
│  ORBIT CATALOG SEARCH     │                                  │
│  [name/SATNO ___] [Search]│                                  │
├───────────────────────────┴──────────────────────────────────┤
│  MANEUVER OPTIONS (Intel/Mission panel)                      │
│  Red [dropdown] vs Blue [dropdown]                           │
│  Window start [__] stop [__]  Max ΔV [__] km/s              │
│  Burns: [x] Impulsive [ ] Finite                             │
│  Locs:  [x] Apogee [x] Perigee [x] AN [x] DN [x] Poles     │
│  [Generate Options]   [Re-run Last Search]                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Loc | Type | Burn Epoch | ΔV km/s | Transfer | Range | │ │
│  └─────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  RUN CONFIGURATION                                           │
│  Operator [____] | Source [____]          [Run Plan]         │
├──────────────────────────────────────────────────────────────┤
│  INTERCEPT WINDOWS                                           │
│  Blue | Red | Start UTC | End UTC | Duration (s)             │
├──────────────────────────────────────────────────────────────┤
│  RUN LOG                           [Refresh] [Clear]         │
│  (scrolling structured log, auto-polled every 5 s)           │
└──────────────────────────────────────────────────────────────┘
```

### Step-by-step

1. **Connect STK** — click the **STK** chip in the nav bar and choose:
   - *Attach* — connect to a running STK instance with a scenario already loaded
   - *Load* — provide a path to a `.sc` file to open it in STK
   - *Create* — enter a name and UTC start/stop times to create a new scenario
   - After restart: use **Import from Scenario** to re-populate session state from existing `B_SAT_*`/`R_SAT_*` objects in STK without re-adding or re-propagating them.

2. **Connect UDL** — click the **UDL** chip and enter credentials. Once connected, TLE fetch and HRR watchlist are enabled.

3. **Add blue assets** — enter a SATNO and click **Fetch TLE** (UDL), or click **+ Add Blue Asset** and paste a TLE manually. Use the HRR watchlist or Orbit Catalog to discover candidates. Repeat for all friendly assets.

4. **Add red tracks** — same workflow using the Red column. Repeat for all threat tracks.

5. **Generate maneuver options** — in the **Maneuver Options** panel, select a Red satellite, a Blue target, a search window, max ΔV, burn types, and burn locations. Click **Generate Options**. STK Astrogator runs a differential corrector for each location × burn type combination; solved options appear in the sortable table. Click **Select** on any row to store that maneuver.

6. **Run intercept plan** — confirm the Operator callsign and Source tag, then click **Run Plan**. STK computes access windows for all blue/red pairs; results appear in the **Intercept Windows** table.

7. **Review and repeat** — use **Re-run Last Search** to re-run the Astrogator search with updated satellite state. Use **Clear** to reset the run log between runs. Click × on any asset to remove it before the next run.

All panel updates are HTMX partial swaps — the page never fully reloads.

---

## Running Tests

```powershell
# Unit tests only (no STK, no web server required)
pytest tests/unit/

# Unit tests with coverage report
pytest tests/unit/ --cov=sipc --cov-report=term-missing

# Web integration tests (FastAPI TestClient, in-memory DB)
pytest tests/integration/test_web_routes.py

# Full suite
pytest
```

### Live STK integration tests

```powershell
$env:STK_INTEGRATION_TESTS = "1"
pytest tests/integration/ -m integration
```

---

## Project Structure

```
sipc/                       ← repo root
├── sipc/                   ← importable package
│   ├── stk_adapter/        ← IStkSession interface, FakeStkSession, StkComSession
│   ├── domain/             ← intercept planning logic (decoupled from STK)
│   │   ├── models.py       ← BlueAsset, RedTrack, RunConfig, InterceptWindow,
│   │   │                      BurnType, BurnLocation, ManeuverOption, ManeuverSearchConfig
│   │   ├── scenario.py     ← ScenarioPlanner orchestrator
│   │   ├── maneuver_planner.py ← ManeuverPlanner (Astrogator option search)
│   │   └── geometry.py     ← geometry helpers
│   ├── web/                ← FastAPI web console
│   │   ├── app.py          ← application factory + startup
│   │   ├── auth.py         ← session cookies + require_login dependency
│   │   ├── database.py     ← async SQLAlchemy engine + admin bootstrap
│   │   ├── models.py       ← User ORM model
│   │   ├── planning_state.py ← per-session in-memory state (assets, maneuver options)
│   │   ├── routes/
│   │   │   ├── login.py    ← GET/POST /login, POST /logout
│   │   │   ├── operator.py ← dashboard, asset CRUD, /plan, STK connect/import, log
│   │   │   ├── udl.py      ← UDL login/logout, TLE fetch, HRR watchlist, orbit catalog
│   │   │   └── maneuver.py ← /plan/maneuver/search, /refresh, /select
│   │   ├── templates/      ← Jinja2 HTML (base, login, operator, partials)
│   │   └── static/         ← style.css (dark-mode military theme), SIPC_logo.svg
│   ├── app_logging/        ← structlog setup + run_id correlation
│   └── config/             ← constants and runtime settings
├── tests/
│   ├── unit/               ← fast tests (FakeStkSession, auth helpers, state, ManeuverPlanner)
│   └── integration/        ← FastAPI TestClient + live STK (opt-in)
├── Dockerfile              ← production container (uvicorn, Python slim)
└── docs/                   ← architecture notes, operator guide, astrogator notes
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
| `CALC_` | Computed / derived STK objects |
| `OUT_` | Run output folders |

All times are UTC. Distances in km, speeds in m/s, angles in degrees.
Coordinate frame: ICRF/J2000.

---

## Architecture

See `docs/architecture.md` for hexagonal architecture design decisions and adapter pattern details.
