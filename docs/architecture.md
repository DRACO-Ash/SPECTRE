# SIPC Architecture

## Overview

SIPC is a **pure-Python** orbital analysis console. All astrodynamics computations
are performed by the `sipc.astro` package — no external tools, COM interfaces, or
licensed astrodynamics software are required.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Web Layer                                  │
│   FastAPI + Jinja2 + HTMX (routes, templates, HTMX partials)        │
│   Session auth (signed cookies)  ·  SQLite / PostgreSQL DB          │
│   Routes: operator · login · udl · maneuver · threat · pol · gcat   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ calls
┌──────────────────────────▼──────────────────────────────────────────┐
│                        Domain Layer                                 │
│   ScenarioPlanner · BlueAsset · RedTrack · InterceptResult          │
│   RunConfig · BurnResult · ManeuverOption · ManeuverSearchConfig    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ calls
┌──────────────────────────▼──────────────────────────────────────────┐
│                      sipc.astro Layer                               │
│   Pure-Python orbital mechanics — no external dependencies          │
│   constants · maneuvers · tactical · pattern_of_life                │
│   SGP4 propagation (sgp4 library)                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Packages

### `sipc/astro/`

Pure-Python orbital mechanics. No GUI, no COM, no licensed software.

| Module | Contents |
|--------|----------|
| `constants.py` | Earth gravitational parameter (μ), radius, J2 coefficient, sidereal rate, unit conversions |
| `maneuvers.py` | `lambert_transfer()`, `hohmann_transfer()`, `bielliptic_transfer()`, `rendezvous()`, `proximity_rendezvous()` — all return ΔV vectors in VNB frame |
| `tactical.py` | 17 solver categories: phasing orbit, CW radial separation, CW along-track drift, plane change, J2 RAAN drift, COLA avoidance, optimal evasion, GEO drift (longitude relocation), NMC safety ellipse, manoeuvre classification, intercept detectability, adversary intent prediction, intercept envelope, relative motion stability, manoeuvre fingerprinting, formation defence, minimum-time intercept |
| `pattern_of_life.py` | Historical TLE sequence analysis: period tracking, manoeuvre detection, activity classification, behavioural baseline |

SGP4 propagation uses the [`sgp4`](https://pypi.org/project/sgp4/) library (Vallado algorithm). Orbital events (apogee, perigee, ascending/descending node crossings) are detected by propagating over the scenario window and finding sign changes.

### `sipc/domain/`

Pure Python. No I/O. Contains:

- **models.py** — dataclasses/enums: `BlueAsset`, `RedTrack`, `InterceptWindow`,
  `RunConfig`, `AccessInterval`, `BurnType`, `BurnLocation`, `ManeuverOption`,
  `ManeuverSearchConfig`, `InterceptMethod`, `InterceptConfig`, `InterceptResult`, `BurnResult`
- **scenario.py** — `ScenarioPlanner`: orchestrates planning runs, manages asset state,
  dispatches to `sipc.astro` solvers
- **geometry.py** — stateless helpers (AER, closure rate, orbital elements from TLE)

### `sipc/web/`

FastAPI application. All operator access via browser — no desktop install required.

- **app.py** — application factory + lifespan startup (DB init, admin bootstrap, Jinja2
  custom filters including `urlquote`)
- **auth.py** — session cookies (`itsdangerous`), `require_login` dependency, 8 hr expiry
- **database.py** — async SQLAlchemy engine + admin account bootstrap from env vars
- **models.py** — `User` ORM model
- **planning_state.py** — per-session in-memory state (`SessionState`): blue/red asset
  lists, UDL credentials, intercept history, `deque`-backed run log (O(1) eviction at 500 entries)
- **routes/**
  - `login.py` — `GET/POST /login`, `POST /logout`
  - `operator.py` — dashboard, asset CRUD, log, orbital events
  - `udl.py` — UDL login/logout, TLE fetch (latest + epoch modes), HRR watchlist,
    orbit catalogue search
  - `maneuver.py` — full intercept engine: 23 methods across Classical, Tactical,
    Advanced Analysis, and Decision Support categories; trade-space data endpoint
  - `threat.py` — Threat Sweep: batch Hohmann evaluation + Lambert refinement across
    HRR target groups; sentinel pattern; per-epoch sweep (now/apogee/perigee/nodes)
  - `pol.py` — Pattern of Life panel: historical TLE analysis, manoeuvre detection,
    activity baseline, behavioural classification
  - `gcat.py` — GCAT panel: 28 TSV datasets from planet4589.org, in-memory cache,
    on-demand per-dataset download, search/sort/paginate
- **templates/** — Jinja2 HTML: `base.html`, `login.html`, `operator.html`, and
  HTMX partials for every panel and result type
- **static/** — `style.css` (Bluestaq dark ops theme), `Chart.js`, `hammer.min.js`,
  `chartjs-plugin-zoom.min.js`, `SIPC_logo.svg`

### `sipc/app_logging/`

Configures `structlog` with:
- Console renderer (human-readable) for terminal output
- JSON-lines file renderer for post-run analysis
- `run_id` UUID bound to all log records via `structlog.contextvars`

### `sipc/config/`

- **constants.py** — naming prefixes (`B_SAT_`, `R_SAT_`), units, step sizes
- **settings.py** — `Settings` dataclass populated from environment variables

---

## GCAT Module

The `/gcat` route set implements a fully interactive browser for the
**General Catalog of Artificial Space Objects** (J. McDowell, planet4589.org).

| Route | Behaviour |
|-------|-----------|
| `GET /gcat/panel` | Returns the panel skeleton instantly (< 50 ms, no network I/O) |
| `GET /gcat/table` | Downloads the requested dataset on first access (~2–5 s), served from in-memory cache thereafter |
| `POST /gcat/refresh` | Concurrently re-downloads all 28 datasets via `asyncio.gather` + `ThreadPoolExecutor` |

28 datasets across 4 categories (Derived, Objects, Payloads, Supporting) are registered.
Each dataset is a TSV fetched from `https://planet4589.org/space/gcat/tsv/`.
`pandas` is used for parsing, column-level search, sorting, and pagination.
HTMX out-of-band swaps (`hx-swap-oob="outerHTML"`) update nav button row counts after
each table load without re-rendering the full panel.

---

## Key Design Decisions

### Pure-Python astrodynamics

All orbital mechanics — Lambert solver, Hohmann/bi-elliptic transfers, CW equations,
J2 secular drift, SGP4 propagation — are implemented in `sipc/astro/`. No licensed
tools, no COM objects, no platform-native dependencies. The application runs identically
on Windows, Linux, and in Docker.

### HTMX partial swap pattern

All operator actions return HTML fragments that HTMX swaps into targeted DOM elements —
no full page reloads. The panel skeleton is always rendered instantly; heavyweight
operations (TLE downloads, intercept solves, GCAT fetches) are handled via async routes
with loading indicators (`htmx-indicator`).

### Off-thread blocking calls

Downloads and compute-intensive solvers that would block FastAPI's async event loop are
dispatched via `asyncio.get_running_loop().run_in_executor(_EXECUTOR, ...)` using a
shared `ThreadPoolExecutor`.

### In-memory session state

`SessionState` is a single in-memory object per server process. Asset lists, intercept
history, and the run log are held in memory. GCAT datasets are cached in a module-level
`_CACHE` dict keyed by dataset name. State is not persisted across restarts.

### In-memory GCAT cache

Downloaded GCAT DataFrames are stored in a module-level `_CACHE: dict[str, pd.DataFrame]`
for the lifetime of the server process. The panel loads instantly even on cold start;
users see row counts populate as they click datasets. **Refresh All** forces a full
concurrent re-download.

### Database

SQLite by default (`sipc.db`). Switch to PostgreSQL by setting:
```
DATABASE_URL=postgresql+asyncpg://user:pass@host/sipc_db
```
No code changes required — the async SQLAlchemy adapter handles the swap.

### Provenance tagging

Every planning run is assigned a `run_id` (UUID) bound to `structlog` context at run
start, appearing in all log records for that run.

---

## Testing Strategy

| Layer | Test type | Notes |
|-------|-----------|-------|
| `sipc/astro/` | unit | No external deps; fast |
| `domain/` | unit | Pure-Python models |
| `web/routes/` | integration (TestClient) | In-memory SQLite |
| Tactical solvers | unit | 74 parametrised test cases |

Integration tests that require a live network (UDL, GCAT) are guarded by
`@pytest.mark.integration` and skipped unless `SIPC_INTEGRATION_TESTS=1` is set.
