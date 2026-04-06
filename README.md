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

- Browsing the **GCAT** (General Catalog of Artificial Space Objects — J. McDowell, planet4589.org): 28 datasets across Derived, Objects, Payloads, and Supporting categories; searchable, sortable, and paginated, with on-demand download and in-session caching
- Analysing **Pattern of Life** from historical TLE sequences: manoeuvre detection, activity classification, and behavioural baseline
- **TLE Clustering & De-duplication**: DBSCAN-based multi-provider TLE reduction, automatically run before each Threat Sweep to select the best representative TLE per satellite and flag objects with divergent orbit solutions (elevated uncertainty indicator)

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
┌──────────────────────────────────────────────────────────────────┐
│  [≡] SIPC    [UDL ●]                         [operator] [Logout] │
├────────────────────────┬─────────────────────────────────────────┤
│  SIDEBAR (500px)       │  HERO TABS                              │
│  ┌ Assets ───────────┐ │  [Engine] [Sweep] [PoL] [GCAT]         │
│  │ [Red][Blue][HRR]  │ ├─────────────────────────────────────────┤
│  │  sub-tabs          │ │  Intercept Engine  (23 methods)        │
│  └───────────────────┘ │  Threat Sweep      (batch HRR eval)    │
│  Scenario Time          │  Pattern of Life   (TLE history)       │
│  UDL Catalogue Search   │  GCAT Browser      (28 datasets)       │
│                         │  Trade-Space Plot  (ΔV vs time)        │
│                         │  Session Log                           │
└────────────────────────┴─────────────────────────────────────────┘
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
   - The dropdown automatically pre-fetches TLEs for the selected group; multi-provider TLE history is fetched concurrently and clustered via DBSCAN to select the best representative per satellite before the sweep runs
   - Click **Sweep Targets** to batch-evaluate all objects at 5 orbital epochs (now, apogee, perigee, ascending node, descending node) using Hohmann transfers, then auto-refine the top 5 with Lambert for VNB components
   - Results are ranked by ΔV with one-click refinement per entry
   - A **TLE Clustering** accordion in the results shows per-object reduction statistics; objects with multiple divergent clusters (possible recent manoeuvre) are flagged with an elevated-uncertainty warning

9. **Compare solutions** — run multiple intercept calculations with different methods or parameters. After the second solution, a trade-space scatter plot (ΔV vs transfer time) appears automatically, colour-coded by method. Use this to identify the optimal trade-off.

10. **Pattern of Life** — open the **PoL** hero tab, enter a NORAD catalogue number, and fetch a historical TLE sequence. SIPC analyses the sequence for period anomalies, manoeuvre detections, and activity classification, displaying a timeline of inferred events.

11. **GCAT** — open the **GCAT** hero tab for instant access to the General Catalog of Artificial Space Objects. The panel skeleton loads immediately; click any dataset in the left-hand navigator to fetch and display it (first access ~2–5 s, cached for the session thereafter):
    - **Derived**: Current Satellite Catalog, Launch Log, Active Satellites, Geosync Catalog, Full Launch Log
    - **Objects**: SatCat, AuxCat, EventCat, DeepCat, and more
    - **Payloads**: Mission metadata, classification, end-of-life data
    - **Supporting**: Organisations, Sites, Launch Vehicles, Engines

    Use the search box to filter all columns, click any column header to sort, and navigate pages with the pagination bar. Use **↻ Refresh All** to force a fresh download of all 28 datasets from planet4589.org.

12. **Review and repeat** — use **Clear History** to reset the trade-space plot. Click × on any asset to remove it. All panel updates are HTMX partial swaps — the page never fully reloads.

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
│   ├── astro/              ← pure-Python orbital mechanics
│   │   ├── tle_preprocessing.py  ← TLE clustering integration bridge;
│   │   │                            cluster_and_reduce_tle_cache() + ClusteringSummary
│   │   └── ...             ← transfers, tactical manoeuvres, advanced analysis, SGP4, events
│   ├── domain/             ← intercept planning logic
│   │   ├── models.py       ← BlueAsset, RedTrack, RunConfig, InterceptResult,
│   │   │                      BurnResult, ManeuverOption, ManeuverSearchConfig
│   │   ├── scenario.py     ← ScenarioPlanner orchestrator
│   │   └── geometry.py     ← geometry helpers
│   ├── web/                ← FastAPI web console
│   │   ├── app.py          ← application factory + startup, Jinja2 filters
│   │   ├── auth.py         ← session cookies + require_login dependency
│   │   ├── database.py     ← async SQLAlchemy engine + admin bootstrap
│   │   ├── models.py       ← User ORM model
│   │   ├── planning_state.py ← per-session in-memory state (assets, TLE caches, intercept history)
│   │   ├── routes/
│   │   │   ├── login.py    ← GET/POST /login, POST /logout
│   │   │   ├── operator.py ← dashboard, asset CRUD, log, orbital events
│   │   │   ├── udl.py      ← UDL login/logout, TLE fetch, multi-provider history fetch,
│   │   │   │                  catalogue search, HRR watchlist, NOTSO cache sync
│   │   │   ├── maneuver.py ← 23-method intercept engine, trade-space data
│   │   │   ├── threat.py   ← Threat Sweep (batch Hohmann + Lambert refinement, TLE clustering)
│   │   │   ├── pol.py      ← Pattern of Life (historical TLE analysis, NOTSO correlation)
│   │   │   └── gcat.py     ← GCAT browser (28 datasets, on-demand fetch, in-memory cache)
│   │   ├── templates/      ← Jinja2 HTML (base, login, operator, partials)
│   │   └── static/         ← style.css (Bluestaq dark ops theme), Chart.js, hammer.min.js,
│   │                          chartjs-plugin-zoom.min.js, SIPC_logo.svg
│   ├── app_logging/        ← structlog setup + run_id correlation
│   └── config/             ← constants and runtime settings (TLE_CLUSTERING, TLE_FILTER)
├── tle_clustering/         ← standalone TLE de-duplication package (scikit-learn DBSCAN)
│   ├── __init__.py         ← cluster_tle_strings() — primary entry point
│   ├── config.py           ← ClusteringConfig (tolerances, DBSCAN hyper-parameters)
│   ├── models.py           ← TLERecord, Cluster, NoiseTLE, ClusteringResult
│   ├── parser.py           ← TLE string parser → TLERecord list (sgp4 backed)
│   ├── clustering.py       ← DBSCAN clustering (Chebyshev / L-∞ metric, normalised space)
│   └── selection.py        ← representative selection (min Chebyshev distance, recency tie-break)
├── tests/
│   ├── unit/               ← fast tests (auth helpers, state, domain models, tle_clustering/)
│   └── integration/        ← FastAPI TestClient routes + TLE clustering pipeline tests
├── docs/                   ← operator guide generator, architecture notes, reference PDFs
├── Dockerfile              ← production container (uvicorn, Python slim)
└── pyproject.toml
```

### TLE Clustering

The `tle_clustering/` package is a standalone, dependency-free (except `sgp4` + `scikit-learn`) module that clusters near-duplicate TLEs from multiple tracking providers into a single best representative per satellite.

**Why this matters:** Satellites on the HRR watchlist can attract dozens of TLEs per day from different providers (18 SDS, SpaceTrack, commercial SSA networks). Each provider fits from different observation sets, producing slightly different orbital elements. Feeding all of them into the threat sweep is redundant and misleads the solver — the same orbit re-appears under different labels.

**How it works:**

```
raw TLE history (N TLEs per sat)
         │
         ▼
  parse_tle_strings()       ← extract inc, RAAN, ecc via sgp4
         │
         ▼
  normalise per tolerance   ← divide by [inc_tol, raan_tol, ecc_tol]
         │
         ▼
  DBSCAN (Chebyshev / L-∞)  ← eps=1.0 → all three elements within tolerance
         │
         ├─ cluster members ─▶ select_representative()
         │                        (min Chebyshev dist to centroid, recency tie-break)
         └─ noise TLEs ──────▶ flagged in ClusteringSummary
```

**Tolerances** (configurable in `sipc/config/constants.py → TLE_CLUSTERING`):

| Element | Default | Rationale |
|---------|---------|-----------|
| Inclination | 0.01° | J2 + fitting noise < 0.01° |
| RAAN | 0.05° | Provider epoch offsets of minutes → ~0.05° J2 drift |
| Eccentricity | 1×10⁻⁴ | Typical inter-provider LEO variation |

**Elevated uncertainty flag:** When DBSCAN finds >1 cluster for a satellite (e.g. after an unannounced manoeuvre, or during poor tracking coverage), the first cluster representative is used and the sweep results show a red ▲ warning. This is the system's automatic indicator that the orbit is not well-determined.

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

All times are UTC. Distances in km, speeds in km/s, angles in degrees.
Coordinate frame: ICRF/J2000.

---

## Architecture

See `docs/architecture.md` for architecture design decisions and adapter pattern details.
