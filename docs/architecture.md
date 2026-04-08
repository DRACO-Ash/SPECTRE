# SPECTRE Architecture

## Overview

SPECTRE is a **pure-Python** orbital analysis console. All astrodynamics computations
are performed by the `spectre.astro` package — no external tools, COM interfaces, or
licensed astrodynamics software are required.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Web Layer                                  │
│   FastAPI + Jinja2 + HTMX (routes, templates, HTMX partials)        │
│   Session auth (signed cookies)  ·  SQLite / PostgreSQL DB          │
│   Routes: operator · login · udl · maneuver · threat · pol ·        │
│           decision · geometry · gcat · training                     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ calls
┌──────────────────────────▼──────────────────────────────────────────┐
│                        Domain Layer                                 │
│   ScenarioPlanner · BlueAsset · RedTrack · InterceptResult          │
│   RunConfig · BurnResult · ManeuverOption · ManeuverSearchConfig    │
│   Decision Engine: AdversaryAction · FriendlyResponse ·             │
│                    OutcomeMetrics · evaluate_scenario()              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ calls
┌──────────────────────────▼──────────────────────────────────────────┐
│                      spectre.astro Layer                               │
│   Pure-Python orbital mechanics — no external dependencies          │
│   constants · maneuvers · transfers · lambert · tactical            │
│   cw_geometry · propagator · events                                 │
│   pattern_of_life · tle_filter · monte_carlo · notso · photometry   │
│   SGP4 propagation (sgp4 library)                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Packages

### `spectre/astro/`

Pure-Python orbital mechanics. No GUI, no COM, no licensed software.

| Module | Contents |
|--------|----------|
| `constants.py` | Earth gravitational parameter (μ), radius, J2 coefficient, sidereal rate, unit conversions |
| `maneuvers.py` | `hohmann_transfer()`, `bielliptic_transfer()`, `rendezvous()`, `proximity_rendezvous()` — all return ΔV vectors in VNB frame |
| `transfers.py` | Lambert solver (universal variable method); two-impulse intercept ΔV |
| `lambert.py` | Lambert targeting: multi-revolution solutions, batched evaluation |
| `tactical.py` | 17 solver categories: phasing orbit, CW radial separation, CW along-track drift, plane change, J2 RAAN drift, COLA avoidance, optimal evasion, GEO drift (longitude relocation), NMC safety ellipse, manoeuvre classification, intercept detectability, adversary intent prediction, intercept envelope, relative motion stability, manoeuvre fingerprinting, formation defence, minimum-time intercept |
| `cw_geometry.py` | Clohessy-Wiltshire equations, Hill-frame relative motion, relative state vectors |
| `propagator.py` | `TLEOrbit`: SGP4 propagation via `sgp4` library; `state_to_keplerian()`, `keplerian_to_state()` |
| `events.py` | Orbital event detection: apogee, perigee, ascending/descending node crossings (sign-change scan over SGP4 trajectory) |
| `pattern_of_life.py` | Historical TLE sequence analysis: period tracking, manoeuvre detection, activity classification, behavioural baseline; `PolAnalysis` result dataclass |
| `tle_filter.py` | Cadence-based TLE clustering: `cluster_tles()`, `select_representative()`, `quality_flag_sequence()`, `filter_tle_history()` |
| `tle_preprocessing.py` | Bridge between `tle_clustering/` (DBSCAN) and `spectre.astro`; `cluster_and_reduce_tle_cache()` used by Threat Sweep |
| `monte_carlo.py` | `ManoeuvreHypothesis`, `ManoeuvreType`, `MANOEUVRE_ARCHETYPES`; `run_monte_carlo()` (ProcessPoolExecutor, RK45 + J2 + drag); `MonteCarloResult` with P5/P50/P95 and regime probabilities |
| `notso.py` | `NOTSORecord` parser (USSPACECOM format), `correlate_notsos_with_manoeuvres()`, `OperatorBehaviourProfile` |
| `photometry.py` | `PhotometryObservation`, geometric corrections (range normalisation, Rozenberg airmass), `fit_baseline()` (quadratic phase function, sigma-clipping), `detect_change()` (Student's t-test), `PhotometryChangeAssessment` |

SGP4 propagation uses the [`sgp4`](https://pypi.org/project/sgp4/) library (Vallado algorithm).

### `spectre/domain/`

Pure Python. No I/O. Contains:

- **models.py** — dataclasses/enums: `BlueAsset`, `RedTrack`, `InterceptWindow`,
  `RunConfig`, `AccessInterval`, `BurnType`, `BurnLocation`, `ManeuverOption`,
  `ManeuverSearchConfig`, `InterceptMethod`, `InterceptConfig`, `InterceptResult`, `BurnResult`
- **scenario.py** — `ScenarioPlanner`: orchestrates planning runs, manages asset state,
  dispatches to `spectre.astro` solvers
- **decision.py** — Decision Engine Phase 1: `ActionType`, `AdversaryAction`, `FriendlyResponse`,
  `OutcomeMetrics`, `Scenario`, `ScenarioResult`, `compute_outcome_metrics()`,
  `rank_responses()`, `find_robust_response()`, `evaluate_scenario()`
- **geometry.py** — stateless helpers (AER, closure rate, orbital elements from TLE)
- **maneuver_planner.py** — `ManeuverPlanner`: validates search config, sorts options by ΔV
- **exceptions.py** — domain exception types

### `spectre/training/`

Gamification and training mode. YAML-driven configuration with a DB-backed progress model.

| Module | Contents |
|--------|----------|
| `gamification.py` | XP engine, level unlock rules, progress tracking, `TrainingProgressService` |
| `scenarios.py` | Scenario loader, unlock logic (level gate), `ScenarioService` |
| `tutorials.py` | Tutorial loader, completion tracking, `TutorialService` |
| `models.py` | `TrainingSession`, `TrainingProgress`, `TrainingChallengeResult` ORM models |
| `config/scenarios.yaml` | 13 scenarios: Cadet (L1) → Expert (L6); each has Blue+Red assets, objectives, tool_workflow, and answer spec |
| `config/gamification.yaml` | 6 levels with XP thresholds, skill axes, point values per action |
| `config/tutorials.yaml` | Tutorial definitions per skill axis, with point awards and unlock rules |

### `spectre/web/`

FastAPI application. All operator access via browser — no desktop install required.

- **app.py** — application factory + lifespan startup (DB init, admin bootstrap, Jinja2 custom filters including `urlquote`)
- **auth.py** — session cookies (`itsdangerous`), `require_login` dependency, 8 hr expiry
- **database.py** — async SQLAlchemy engine + admin account bootstrap from env vars
- **models.py** — `User` ORM model
- **deps.py** — centralised `get_templates()` shared by all route modules
- **planning_state.py** — per-session in-memory state (`SessionState`): blue/red asset lists, UDL credentials, intercept history, `deque`-backed run log (O(1) eviction at 500 entries)
- **routes/**
  - `login.py` — `GET/POST /login`, `POST /logout`
  - `operator.py` — dashboard, asset CRUD, log, orbital events
  - `udl.py` — UDL login/logout, TLE fetch (latest + epoch modes), HRR watchlist, orbit catalogue search, NOTSO cache sync
  - `maneuver.py` — full intercept engine: 23 methods across Classical, Tactical, Advanced Analysis, and Decision Support categories; trade-space data endpoint
  - `threat.py` — Threat Sweep: batch Hohmann evaluation + Lambert refinement across HRR target groups; sentinel pattern; per-epoch sweep (now/apogee/perigee/nodes); TLE clustering
  - `pol.py` — Pattern of Life: historical TLE analysis, manoeuvre detection, cadence filtering, NOTSO correlation, Monte Carlo simulation, photometry assessment
  - `decision.py` — `GET /plan/decision/panel` (scenario builder form), `POST /plan/decision/evaluate` (runs `evaluate_scenario()`)
  - `geometry.py` — CW geometry visualiser; Hill-frame relative motion plots
  - `gcat.py` — GCAT panel: 28 TSV datasets from planet4589.org, in-memory cache, on-demand per-dataset download, search/sort/paginate
  - `training.py` — Training mode: session management, scenario dispatch, tutorial progress, gamification XP awards
- **templates/** — Jinja2 HTML: `base.html`, `login.html`, `operator.html`, `training.html`, and HTMX partials for every panel and result type
- **static/** — `style.css` (Bluestaq dark ops theme), `Chart.js`, `hammer.min.js`, `chartjs-plugin-zoom.min.js`, `SPECTRE_logo.svg`

### `spectre/data/`

- **notso_cache.py** — `NOTSOCache`: persistent NOTSO record storage keyed by NORAD ID; retrieval for Decision Engine Phase 5 priors
- **intel.py** — Intelligence data helpers (OOB lookup, nation classification)

### `spectre/app_logging/`

Configures `structlog` with:
- Console renderer (human-readable) for terminal output
- JSON-lines file renderer for post-run analysis
- `run_id` UUID bound to all log records via `structlog.contextvars`

### `spectre/config/`

- **constants.py** — naming prefixes (`B_SAT_`, `R_SAT_`), units, step sizes; `TLE_CLUSTERING` and `TLE_FILTER` threshold dicts
- **settings.py** — `Settings` dataclass populated from environment variables

---

## `tle_clustering/` Package

Standalone, dependency-free (except `sgp4` + `scikit-learn`) module that clusters near-duplicate TLEs from multiple tracking providers.

| Route | Behaviour |
|-------|-----------|
| `cluster_tle_strings(tles)` | Primary entry point: parse → normalise → DBSCAN → select |
| `ClusteringConfig` | Configurable tolerances and DBSCAN hyper-parameters |
| `ClusteringResult` | Representatives list + noise list + `ClusteringSummary` |

---

## GCAT Module

| Route | Behaviour |
|-------|-----------|
| `GET /gcat/panel` | Returns the panel skeleton instantly (< 50 ms, no network I/O) |
| `GET /gcat/table` | Downloads the requested dataset on first access (~2–5 s), served from in-memory cache thereafter |
| `POST /gcat/refresh` | Concurrently re-downloads all 28 datasets via `asyncio.gather` + `ThreadPoolExecutor` |

28 datasets across 4 categories (Derived, Objects, Payloads, Supporting) are registered.
Each dataset is a TSV fetched from `https://planet4589.org/space/gcat/tsv/`.
`pandas` is used for parsing, column-level search, sorting, and pagination.

---

## Key Design Decisions

### Pure-Python astrodynamics

All orbital mechanics — Lambert solver, Hohmann/bi-elliptic transfers, CW equations, J2 secular drift, SGP4 propagation — are implemented in `spectre/astro/`. No licensed tools, no COM objects, no platform-native dependencies. The application runs identically on Windows, Linux, and in Docker.

### HTMX partial swap pattern

All operator actions return HTML fragments that HTMX swaps into targeted DOM elements — no full page reloads. The panel skeleton is always rendered instantly; heavyweight operations (TLE downloads, intercept solves, Monte Carlo runs, GCAT fetches) are handled via async routes with loading indicators (`htmx-indicator`).

### Off-thread blocking calls

Downloads and compute-intensive solvers that would block FastAPI's async event loop are dispatched via `asyncio.get_running_loop().run_in_executor(_EXECUTOR, ...)` using a shared `ThreadPoolExecutor`. The Monte Carlo engine additionally uses `ProcessPoolExecutor` for CPU-bound sample propagation.

### In-memory session state

`SessionState` is a single in-memory object per server process. Asset lists, intercept history, and the run log are held in memory. GCAT datasets are cached in a module-level `_CACHE` dict keyed by dataset name. State is not persisted across restarts.

### Database

SQLite by default (`spectre.db`). Switch to PostgreSQL by setting:
```
DATABASE_URL=postgresql+asyncpg://user:pass@host/spectre_db
```
No code changes required — the async SQLAlchemy adapter handles the swap.

### Provenance tagging

Every planning run is assigned a `run_id` (UUID) bound to `structlog` context at run start, appearing in all log records for that run.

### Training session isolation

Training sessions are DB-persisted (`TrainingSession` ORM model). XP awards and scenario completions survive server restarts. The training console embeds the live SPECTRE operator interface in an iframe; the training session record is passed as a session variable so the operator tools behave normally.

---

## Testing Strategy

| Layer | Test type | Notes |
|-------|-----------|-------|
| `spectre/astro/` | unit | No external deps; fast; 74+ parametrised tactical cases |
| `spectre/astro/monte_carlo.py` | unit | Smoke (100 samples), convergence, regime classification, RIC→ECI |
| `spectre/astro/notso.py` | unit | Parser, all four correlation match cases, behaviour profile |
| `spectre/astro/photometry.py` | unit | Geometric corrections, sigma-clipping, t-test significance |
| `spectre/astro/tle_filter.py` | unit | Cadence clustering, representative selection, quality flags |
| `domain/` | unit | Pure-Python models; decision engine minimax/EV/maximin selectors |
| `training/` | unit | XP progression, level unlock gates, scenario unlock logic |
| `web/routes/` | integration (TestClient) | In-memory SQLite; covers login, operator, UDL, maneuver, training |
| `tle_clustering/` | unit + integration | DBSCAN pipeline: parser → clustering → selection; full pipeline |

Integration tests that require a live network (UDL, GCAT) are guarded by
`@pytest.mark.integration` and skipped unless `SPECTRE_INTEGRATION_TESTS=1` is set.

---

## Security Architecture

| Layer | Control |
|-------|---------|
| Session cookies | `httponly=True`, `samesite="lax"`, `secure=True` in non-debug environments |
| Authentication | bcrypt password hashing; 8-hour signed session token via `itsdangerous` |
| SAST | `bandit` in CI on every push; `gitleaks` secret scan in CI and pre-commit |
| SCA | `pip-audit` in CI on every push |
| Code review gates | `CODEOWNERS` routes security-sensitive paths to `@Higgy-843` |
| Dependency updates | Dependabot weekly (pip + GitHub Actions) |
| Pre-commit | `gitleaks`, `ruff`, `bandit`, `mypy` enforced locally before commit |

Full security policy: `docs/SECURITY.md` (UK NCSC / SSCoP aligned).
