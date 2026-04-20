# SPECTRE — Space Planning, Evaluation & Counter-Threat Response Engine

Real-time orbital manoeuvre planning console for space defence operators.
Accessed through a browser-based operator interface built on FastAPI + HTMX.

---

## Overview

SPECTRE provides analysts with a web console for:

- **Asset Management** — define Blue (friendly) and Red (adversary) satellite sets with TLE propagators; fetch live TLEs from UDL; one-click import from the HRR watchlist
- **Intercept Engine** (23 methods) — Lambert, Hohmann, bi-elliptic, rendezvous, proximity; tactical manoeuvres (phasing, CW relative motion, plane change, J2 RAAN drift, COLA, evasion); advanced analysis (GEO drift, NMC, manoeuvre classification, detectability); decision support (intent prediction, intercept envelope, stability, fingerprinting, formation defence, orbital terrain, minimum-time intercept)
- **Threat Sweep** — batch Hohmann evaluation across HRR target groups at 5 orbital epochs; Lambert refinement of top results; TLE clustering and de-duplication via DBSCAN; per-object uncertainty flagging
- **Pattern of Life (PoL)** — historical TLE sequence analysis: manoeuvre detection, activity classification, behavioural baseline; TLE cadence filtering and de-duplication; NOTSO message correlation with detected manoeuvres; Monte Carlo simulation of adversary manoeuvre hypotheses; historical photometry change assessment
- **Decision Engine (Phase 1)** — deterministic what-if analysis: build a grid of adversary actions × friendly responses; compute an outcome matrix (composite score, custody gap, closest approach); three selector strategies (Minimax, Expected Value, Maximin); robust recommendation banner
- **GCAT Browser** — interactive browser for the General Catalog of Artificial Space Objects (J. McDowell, planet4589.org): 28 datasets across Derived, Objects, Payloads, and Supporting categories; searchable, sortable, paginated; on-demand download with in-session caching
- **Training Mode** — full gamification system for operator skill development: six proficiency levels, 13 structured scenarios (Cadet through Expert), timed challenges, step-by-step tutorials, live SPECTRE console embed, XP/points progression, session tracking

All orbital mechanics computations use the pure-Python `spectre.astro` package — no external astrodynamics software required.

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
$env:SPECTRE_ADMIN_USER = "admin"
$env:SPECTRE_ADMIN_PASS = "change-me"

# 4. Start the server
spectre-serve
# or equivalently:
uvicorn spectre.web.app:app --reload
```

Then open **http://localhost:8000** in your browser.

### First Login

On first run, SPECTRE creates the database and inserts a single admin account using the values from `SPECTRE_ADMIN_USER` / `SPECTRE_ADMIN_PASS`. Sign in with those credentials.

> If neither env var is set, no bootstrap account is created. You must insert a user manually (see [User Management](#user-management)).

---

## Quick Start — Docker

```bash
# Build the image
docker build -t spectre:latest .

# Run with a named volume for the database
docker run -d \
  -p 8000:8000 \
  -v spectre_data:/app/data \
  -e SECRET_KEY="change-me-to-a-long-random-string" \
  -e SPECTRE_ADMIN_USER="admin" \
  -e SPECTRE_ADMIN_PASS="change-me" \
  --name spectre \
  spectre:latest
```

Then open **http://localhost:8000** in your browser.

To use PostgreSQL instead of SQLite, add:

```bash
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host/spectre_db"
```

No code changes are required — the adapter swap is entirely via `DATABASE_URL`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **Yes** | — | Signs session cookies. Use a long random string in production. |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./spectre.db` | SQLAlchemy async connection string. |
| `SPECTRE_ADMIN_USER` | No | `admin` | Bootstrap admin username (first run only). |
| `SPECTRE_ADMIN_PASS` | No | — | Bootstrap admin password (first run only). Omit to skip bootstrap. |
| `SPECTRE_LOG_LEVEL` | No | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `SPECTRE_LOG_DIR` | No | `logs` | Directory for structlog output files. |

---

## Operator Walkthrough

Once logged in, the operator console has a collapsible sidebar on the left and an intelligence panel on the right. The nav bar exposes a UDL connection chip and a Training Mode button:

```
┌──────────────────────────────────────────────────────────────────┐
│  [≡] SPECTRE    [UDL ●]   [Training]           [operator] [Logout]  │
├────────────────────────┬─────────────────────────────────────────┤
│  SIDEBAR               │  HERO TABS                              │
│  ┌ Assets ───────────┐ │  [Engine] [Sweep] [PoL] [Decision]      │
│  │ [Red][Blue][HRR]  │ │  [GCAT]                                 │
│  │  sub-tabs          │ ├─────────────────────────────────────────┤
│  └───────────────────┘ │  Intercept Engine  (23 methods)         │
│  Scenario Time          │  Threat Sweep      (batch HRR eval)    │
│  UDL Catalogue Search   │  Pattern of Life   (TLE history + MC)  │
│                         │  Decision Engine   (what-if analysis)  │
│                         │  GCAT Browser      (28 datasets)       │
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

4. **Add assets manually** — use the **Blue** and **Red** sub-tabs in the Assets panel to enter a NORAD catalogue number (Fetch TLE) or paste a TLE directly.

5. **Set scenario time** — define the analysis window (start/stop times) in the Scenario Time panel. Defaults to current UTC + 24 hours.

6. **Compute orbital events** — select a red and/or blue satellite, click **Compute Events**. Apogee, perigee, and node crossings are detected via SGP4 propagation and displayed as clickable badges that auto-populate the manoeuvre start time.

7. **Run intercept calculations** — in the **Intercept Engine** panel, select a red target, a blue asset, and choose a method. Methods are grouped into:
   - **Classical Transfers**: Lambert, Hohmann, Bi-elliptic, Rendezvous, Proximity
   - **Tactical Manoeuvres**: Phasing, CW Radial Separation, CW Along-Track Drift, Plane Change, J2 Drift, COLA, Evasion
   - **Advanced Analysis**: GEO Drift, NMC (safety ellipse), Manoeuvre Detect, Detectability
   - **Decision Support**: Intent Predict, Intercept Envelope, Stability, Fingerprint, Formation Defence, Terrain, Min-Time

   Set coast and time-of-flight parameters, then click **Calculate Intercept**. The per-burn ΔV breakdown appears with VNB components, arrival epoch, and miss distance.

8. **Run a Threat Sweep** — in the **Threat Sweep** panel:
   - Select a **Target Group** from the dropdown (Blue HRR or Red HRR, by rank 0–5)
   - TLEs are pre-fetched and clustered via DBSCAN; multi-provider duplicates are reduced to one representative per satellite
   - Click **Sweep Targets** to batch-evaluate all objects at 5 orbital epochs (now, apogee, perigee, ascending node, descending node) using Hohmann transfers, then auto-refine the top 5 with Lambert for VNB components
   - Objects with multiple DBSCAN clusters (possible recent manoeuvre or poor tracking) are flagged with a red ▲ elevated-uncertainty warning

9. **Pattern of Life** — open the **PoL** hero tab, enter a NORAD catalogue number, and fetch a historical TLE sequence. SPECTRE analyses the sequence for:
   - Manoeuvre detections and activity classification
   - Cadence filtering (remove temporally clumped duplicate TLEs)
   - NOTSO message correlation (paste NOTSO text or fetch from UDL) — matches notifications against detected manoeuvres and derives operator behaviour profile
   - Monte Carlo simulation — select any detected manoeuvre, define a `ManoeuvreHypothesis` (ΔV, pointing uncertainty, archetype), and run N samples to get P5/P50/P95 closest-approach bands and regime probability distribution
   - Photometry assessment — paste or upload historical magnitude observations; SPECTRE fits a phase-function baseline and runs a Student's t-test to detect statistically significant brightness changes, correlated with manoeuvre epochs

10. **Decision Engine** — open the **Decision** hero tab:
    - Define 1–5 adversary action rows (type, probability, confidence)
    - Define 1–5 friendly response rows (type, cost, reversibility, time-to-execute)
    - Click **Evaluate** — the engine computes an N × M outcome matrix with composite scores, custody indicators, and closest-approach estimates
    - Choose selector strategy: **Minimax** (minimise worst-case), **Expected Value** (probability-weighted), or **Maximin** (maximise best-case)
    - The robust recommendation banner shows the best response across all adversary action probabilities

11. **Compare solutions** — run multiple intercept calculations with different methods or parameters. After the second solution, a trade-space scatter plot (ΔV vs transfer time) appears automatically, colour-coded by method.

12. **GCAT** — open the **GCAT** hero tab. Click any dataset in the left-hand navigator to fetch and display it (~2–5 s on first access, cached thereafter). Use the search box, column sort, and pagination bar to explore the 28 datasets.

13. **Training Mode** — click the **Training** button in the nav bar. A dedicated training console opens with:
    - **Dashboard** — XP progress, level badge, recommended next step
    - **Free-Play** — 13 structured scenarios from Cadet (level 1) to Expert (level 6); each includes a briefing, objectives, and tool workflow guidance
    - **Challenges** — timed scenarios that unlock at Level 4+
    - **Tutorials** — step-by-step skill-axis tutorials; mark complete for XP
    - **SPECTRE Console** — live SPECTRE operator console embedded in the training session; use real tools against scenario data

---

## Training System

### Levels and progression

| Level | Title | Min Points |
|-------|-------|-----------|
| 1 | Cadet | 0 |
| 2 | Trainee | 200 |
| 3 | Operator | 500 |
| 4 | Senior Operator | 1 000 |
| 5 | Analyst | 2 000 |
| 6 | Expert | 4 000 |

### Skill axes

Scenarios and tutorials each contribute points to one or more of five skill axes:

| Axis | Description |
|------|-------------|
| `intercept_planning` | Intercept Engine and transfer methods |
| `threat_assessment` | Threat Sweep, HRR, detectability |
| `pattern_analysis` | Pattern of Life, NOTSO, photometry |
| `decision_making` | Decision Engine, what-if analysis |
| `situational_awareness` | GCAT, regime identification, data literacy |

### Scenario design rules

All 13 training scenarios require only tools available in SPECTRE without a live UDL connection:
- Assets panel (manual TLE entry or paste)
- Intercept Engine (requires both Blue and Red assets)
- Decision Engine (fully manual entry, no UDL dependency)

Pattern of Life, NOTSO, Monte Carlo, and HRR-auto-fetch are not used in scenarios because they require live UDL data for real SATNOs; training uses synthetic TLEs.

---

## Running Tests

```powershell
# Unit tests only (no web server required)
pytest tests/unit/

# Unit tests with coverage report
pytest tests/unit/ --cov=spectre --cov-report=term-missing

# Web integration tests (FastAPI TestClient, in-memory DB)
pytest tests/integration/test_web_routes.py

# Full suite
pytest
```

### Test modules

| Module | Contents |
|--------|---------|
| `test_astro.py` | Hohmann, Lambert, bi-elliptic, SGP4 propagation |
| `test_tactical.py` | 74 parametrised tactical solver cases |
| `test_cw_geometry.py` | Clohessy-Wiltshire relative motion |
| `test_monte_carlo.py` | MC sampling, convergence, regime classification |
| `test_notso.py` | NOTSO parser, correlation algorithm, behaviour profile |
| `test_photometry.py` | Geometric corrections, baseline fitting, change detection |
| `test_tle_filter.py` | TLE cadence clustering and quality flags |
| `test_decision.py` | Decision Engine models, minimax/EV/maximin selectors |
| `test_training_gamification.py` | XP/level progression, scenario unlocks |
| `test_threat_sweep.py` | Threat Sweep solver dispatch |
| `test_domain_models.py` | Data model validation |
| `test_planning_state.py` | Session state management |
| `tests/unit/tle_clustering/` | TLE DBSCAN clustering pipeline |
| `tests/integration/` | FastAPI TestClient routes; opt-in network tests |

---

## Security Tooling

The following tools are configured and run in CI:

| Tool | Purpose | Config |
|------|---------|--------|
| `ruff` | Linting + import sorting | `pyproject.toml [tool.ruff]` |
| `mypy` | Static type checking | `pyproject.toml [tool.mypy]` |
| `bandit` | SAST — Python AST security scan | `pyproject.toml [tool.bandit]` |
| `pip-audit` | SCA — CVE scan of dependencies | CI `sca` job |
| `gitleaks` | Secret scanning — prevent credential leakage | `.pre-commit-config.yaml` + CI `secrets` job |

Pre-commit hooks (`.pre-commit-config.yaml`) run `gitleaks`, `ruff`, `bandit`, and `mypy` on every commit.

`CODEOWNERS` gates security-sensitive paths (`spectre/web/auth.py`, `spectre/web/database.py`, `spectre/config/`, `docs/SECURITY.md`) to `@Higgy-843`.

`.github/dependabot.yml` schedules weekly pip and GitHub Actions dependency updates.

To run security checks locally:

```powershell
# SAST
bandit -c pyproject.toml -r spectre

# SCA
pip-audit

# Secret scan
gitleaks detect --source=. --no-git
```

---

## Generating the Operator Guide

```powershell
python docs/generate_guide.py
```

Outputs `docs/SPECTRE_Operator_Guide.docx` — a comprehensive guide formatted per the Bluestaq document style guide (Segoe UI, navy/gold headings, data tables, callout boxes). Covers classical transfers, tactical manoeuvres, advanced analysis, decision engine, trade-space analysis, and operator scenarios.

---

## Project Structure

```
spectre/                           ← repo root
├── spectre/                       ← importable package
│   ├── astro/                  ← pure-Python orbital mechanics
│   │   ├── constants.py        ← μ, R_Earth, J2, sidereal rate, unit conversions
│   │   ├── maneuvers.py        ← Hohmann, bi-elliptic, rendezvous, proximity
│   │   ├── transfers.py        ← Lambert solver (universal variable method)
│   │   ├── lambert.py          ← Lambert targeting (multi-rev, batched)
│   │   ├── tactical.py         ← 17 solver categories (phasing, CW, J2, COLA, evasion…)
│   │   ├── cw_geometry.py      ← Clohessy-Wiltshire relative motion geometry
│   │   ├── propagator.py       ← TLEOrbit: SGP4 propagation, state-to-Keplerian
│   │   ├── events.py           ← Orbital event detection (apogee, perigee, nodes)
│   │   ├── pattern_of_life.py  ← Historical TLE analysis, manoeuvre detection
│   │   ├── tle_filter.py       ← Cadence clustering, representative selection, quality flags
│   │   ├── tle_preprocessing.py← TLE DBSCAN clustering bridge (Threat Sweep integration)
│   │   ├── monte_carlo.py      ← ManoeuvreHypothesis MC sampling, RK45 propagation, results
│   │   ├── notso.py            ← NOTSO parser, manoeuvre correlation, behaviour profile
│   │   └── photometry.py       ← Photometry baseline fitting, change detection, correlation
│   ├── domain/                 ← intercept planning logic
│   │   ├── models.py           ← BlueAsset, RedTrack, RunConfig, InterceptResult, BurnResult…
│   │   ├── scenario.py         ← ScenarioPlanner orchestrator
│   │   ├── decision.py         ← Decision Engine: ActionType, AdversaryAction,
│   │   │                          FriendlyResponse, OutcomeMetrics, evaluate_scenario()
│   │   ├── geometry.py         ← AER, closure rate, orbital elements from TLE
│   │   ├── maneuver_planner.py ← ManeuverPlanner: validates config, sorts options
│   │   └── exceptions.py       ← Domain exception types
│   ├── training/               ← Gamification and training mode
│   │   ├── gamification.py     ← XP engine, level unlock rules, progress tracking
│   │   ├── scenarios.py        ← Scenario loader and unlock logic
│   │   ├── tutorials.py        ← Tutorial loader and completion tracking
│   │   ├── models.py           ← TrainingSession, TrainingProgress ORM models
│   │   └── config/
│   │       ├── scenarios.yaml  ← 13 scenarios (Cadet → Expert)
│   │       ├── gamification.yaml ← 6 levels, point thresholds, skill axes
│   │       └── tutorials.yaml  ← Tutorial definitions per skill axis
│   ├── web/                    ← FastAPI web console
│   │   ├── app.py              ← Application factory, lifespan startup, Jinja2 filters
│   │   ├── auth.py             ← Session cookies, require_login dependency, 8 hr expiry
│   │   ├── database.py         ← Async SQLAlchemy engine, admin bootstrap
│   │   ├── models.py           ← User ORM model
│   │   ├── deps.py             ← Shared FastAPI dependencies (templates, state)
│   │   ├── planning_state.py   ← Per-session in-memory state (assets, history, log)
│   │   └── routes/
│   │       ├── login.py        ← GET/POST /login, POST /logout
│   │       ├── operator.py     ← Dashboard, asset CRUD, log, orbital events
│   │       ├── udl.py          ← UDL login/TLE fetch/HRR watchlist/NOTSO cache sync
│   │       ├── maneuver.py     ← 23-method intercept engine, trade-space data
│   │       ├── threat.py       ← Threat Sweep (batch Hohmann + Lambert, TLE clustering)
│   │       ├── pol.py          ← PoL, TLE filter, NOTSO correlation, MC, photometry
│   │       ├── decision.py     ← GET /plan/decision/panel, POST /plan/decision/evaluate
│   │       ├── geometry.py     ← CW geometry visualiser, Hill-frame plots
│   │       ├── gcat.py         ← GCAT browser (28 datasets, cache, search/sort/paginate)
│   │       └── training.py     ← Training mode: session, scenarios, tutorials, progress
│   ├── data/
│   │   ├── intel.py            ← Intelligence data helpers
│   │   └── notso_cache.py      ← NOTSO record persistence and retrieval
│   ├── app_logging/            ← structlog setup, run_id correlation
│   └── config/                 ← Constants and runtime settings
├── tle_clustering/             ← Standalone TLE de-duplication package (DBSCAN)
│   ├── __init__.py             ← cluster_tle_strings() — primary entry point
│   ├── config.py               ← ClusteringConfig (tolerances, DBSCAN hyper-parameters)
│   ├── models.py               ← TLERecord, Cluster, NoiseTLE, ClusteringResult
│   ├── parser.py               ← TLE string parser → TLERecord list (sgp4 backed)
│   ├── clustering.py           ← DBSCAN clustering (Chebyshev / L-∞ metric)
│   └── selection.py            ← Representative selection (min Chebyshev, recency tie-break)
├── tests/
│   ├── unit/                   ← Fast tests (astro, domain, training, tle_clustering)
│   └── integration/            ← FastAPI TestClient + TLE clustering pipeline tests
├── docs/                       ← Architecture notes, planning docs, reference PDFs
├── .github/
│   ├── workflows/ci.yml        ← lint / test / sast / sca / secrets jobs
│   └── dependabot.yml          ← Weekly pip + Actions dependency updates
├── .pre-commit-config.yaml     ← gitleaks, ruff, bandit, mypy on every commit
├── CODEOWNERS                  ← Security-path review gates
├── Dockerfile                  ← Production container (uvicorn, Python slim)
└── pyproject.toml
```

### TLE Clustering

The `tle_clustering/` package clusters near-duplicate TLEs from multiple tracking providers into a single best representative per satellite.

**Why this matters:** Satellites on the HRR watchlist can attract dozens of TLEs per day from different providers (18 SDS, SpaceTrack, commercial SSA networks). Each provider fits from different observation sets, producing slightly different orbital elements. Feeding all of them into the threat sweep is redundant and misleads the solver.

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

**Tolerances** (configurable in `spectre/config/constants.py → TLE_CLUSTERING`):

| Element | Default | Rationale |
|---------|---------|-----------|
| Inclination | 0.01° | J2 + fitting noise < 0.01° |
| RAAN | 0.05° | Provider epoch offsets of minutes → ~0.05° J2 drift |
| Eccentricity | 1×10⁻⁴ | Typical inter-provider LEO variation |

**Elevated uncertainty flag:** When DBSCAN finds >1 cluster for a satellite, the sweep results show a red ▲ warning — the orbit is not well-determined (possible recent unannounced manoeuvre or poor tracking coverage).

---

## User Management

Admins can manage user accounts at **`/admin/users`** — no direct database access required.

### Accessing the admin console

Navigate to `http://<host>/admin/users` while logged in as an admin. Non-admin accounts receive HTTP 403. Unauthenticated requests are redirected to `/login`.

### Operations

| Operation | How |
|-----------|-----|
| **Create user** | Fill in Username, Password, and Role in the form at the top; click **Create User** |
| **Change role** | Click **Edit** on any row, select the new role, click **Save** |
| **Reset password** | Click **Edit** on any row, enter a new password, click **Save** (leave blank to keep current password) |
| **Delete user** | Click **Delete** on any row; confirm the prompt |

### Roles

| Role | Permissions |
|------|-------------|
| `operator` | Full access to all operator console features; cannot access `/admin/*` |
| `admin` | All operator permissions plus `/admin/users` management |

### Safety constraints

- An admin cannot delete their own account.
- An admin cannot delete or demote the last remaining admin account.

### Bootstrap admin (first run)

On first start, SPECTRE creates a single admin account from:

```powershell
$env:SPECTRE_ADMIN_USER = "admin"      # default: "admin"
$env:SPECTRE_ADMIN_PASS = "change-me"  # required; bootstrap is skipped if blank
```

This runs only once — if the `users` table is empty at startup. Use the web UI or change the env vars before first run to set the initial credentials.

### Fallback: direct database access

If the admin account is lost (e.g. all admins deleted via direct SQL), restore access by stopping the server, deleting `spectre.db`, and restarting with `SPECTRE_ADMIN_PASS` set — this re-runs the bootstrap. For PostgreSQL, truncate the `users` table and restart instead.

---

## Naming Conventions

All times are UTC. Distances in km, speeds in km/s, angles in degrees.
Coordinate frame: ICRF/J2000.

---

## Architecture

See `docs/architecture.md` for architecture design decisions and module details.

## Security Policy

See `docs/SECURITY.md` for the full security policy (UK NCSC / SSCoP aligned).
