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

Once logged in, the operator console is divided into five sections:

```
┌──────────────────────────────────────────────────────────┐
│  SIPC — STK Intercept Planning Console     [Logout][user]│
├─────────────────────┬────────────────────────────────────┤
│  BLUE ASSETS        │  RED TRACKS                        │
│  (asset list)       │  (track list)                      │
│  [+ Add Blue Asset] │  [+ Add Red Track]                 │
├─────────────────────┴────────────────────────────────────┤
│  RUN CONFIGURATION                                       │
│  Operator | Source | Scenario      [Run Plan]            │
├──────────────────────────────────────────────────────────┤
│  INTERCEPT WINDOWS                                       │
│  Start UTC | End UTC | Duration (s) | Min Range (km)     │
├──────────────────────────────────────────────────────────┤
│  RUN LOG               [Refresh] [Clear]                 │
│  (scrolling log, auto-polled every 5 s)                  │
└──────────────────────────────────────────────────────────┘
```

### Step-by-step

1. **Add blue assets** — click **+ Add Blue Asset**, enter a name (e.g. `Alpha`) and a two-line TLE. Repeat for all friendly assets.
2. **Add red tracks** — click **+ Add Red Track**, enter a name (e.g. `Track01`) and a TLE. Repeat for all threat tracks.
3. **Fill run configuration** — confirm your operator callsign, enter a source tag (e.g. `SPADOC`, `MANUAL`), and optionally a scenario path.
4. **Click Run Plan** — results appear in the **Intercept Windows** table. The **Run Log** updates automatically.
5. **Export / review** — copy results from the table; use **Clear** to reset the log between runs.
6. **Remove assets** — click the × next to any asset to remove it before the next run.

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
│   │   ├── models.py       ← BlueAsset, RedTrack, RunConfig, InterceptWindow
│   │   ├── scenario.py     ← ScenarioPlanner orchestrator
│   │   └── geometry.py     ← geometry helpers
│   ├── web/                ← FastAPI web console
│   │   ├── app.py          ← application factory + startup
│   │   ├── auth.py         ← session cookies + require_login dependency
│   │   ├── database.py     ← async SQLAlchemy engine + admin bootstrap
│   │   ├── models.py       ← User ORM model
│   │   ├── planning_state.py ← per-session in-memory state
│   │   ├── routes/
│   │   │   ├── login.py    ← GET/POST /login, POST /logout
│   │   │   └── operator.py ← dashboard, asset CRUD, /plan, log SSE
│   │   ├── templates/      ← Jinja2 HTML (base, login, operator, partials)
│   │   └── static/         ← style.css (dark-mode military theme)
│   ├── app_logging/        ← structlog setup + run_id correlation
│   └── config/             ← constants and runtime settings
├── tests/
│   ├── unit/               ← fast tests (FakeStkSession, auth helpers, state)
│   └── integration/        ← FastAPI TestClient + live STK (opt-in)
├── Dockerfile              ← production container (uvicorn, Python slim)
└── docs/                   ← architecture notes + operator guide
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
from passlib.context import CryptContext
ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
print(ctx.hash("operator-password-here"))
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
