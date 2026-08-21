# Changelog

All notable changes to SPECTRE will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] - 2026-08-21

Bluestaq App Store readiness. SPECTRE is packaged for the docker-only template
and meets the platform runtime contract. See `READINESS.md` for the scored
report and the remaining gaps.

### Fixed

- **37 failing integration tests.** Commit `d88cb69` added a global CSRF
  dependency without updating the suite, so every authenticated POST returned
  403 and `master` CI had been red since 5 May 2026. Tests now mint a real
  token via `csrf_headers()`, exercising the control rather than disabling it.
- **`GET /` returned 302 to anonymous callers.** The App Store router probes the
  root and treats a redirect as a failed deploy. It now serves the login page at
  200 via the new `optional_login` dependency; console state still never renders
  without a valid session.
- **Lint job disagreed with the local loop.** It installed a partial dependency
  set, so mypy failed in CI while passing locally. It now installs `.[dev]`.
- **`HRR_List.json` resolved to a path that cannot exist in a container.** It is
  now read from the data volume first, so a deployed instance can be given fresh
  data without a rebuild.

### Added

- **Health and readiness endpoints** (`spectre/web/health.py`). `/healthz` is
  liveness only. `/readyz` proves storage with a real write, races a hard 2 s
  timeout so a stalled mount cannot become a silent liveness kill, and returns
  the resolved data directory and the exact errno in its 503 body.
- **Fail-closed startup validation.** A missing, placeholder or short
  `SECRET_KEY` stops the boot. So does a data directory that will not accept a
  write, with the `securityContext.fsGroup` remedy named in the message.
- **`requirements.lock`**, 43 dependencies pinned with SHA-256 hashes,
  installed with `--require-hashes --only-binary=:all:`.
- **`scripts/verify-container.sh`**, builds the image and asserts every
  contract property against it. POSIX `sh`, no bashisms. Run before every upload.
- **`tests/unit/test_deployment_contract.py`**, pins the deployment contract as
  tests so it cannot silently regress.
- Test suites for configuration resolution, the health endpoints, the CSRF and
  session controls, the logout flow and the intercept CSV export.
- **Container contract job in CI**, builds the image and verifies non-root, no
  setuid paths, no package manager, 200 at `/` and the health paths, and
  fail-closed boot.

### Changed

- **Dockerfile rewritten** as a three-stage hardened build: no compiler (every
  dependency ships a manylinux wheel), base pinned by digest, package managers
  and toolchain stripped, the setuid/setgid sweep as the last mutation failing
  the build closed, and the runtime flattened to `FROM scratch` with a single
  `COPY --from=prep / /` so the policy scan finds no layer history.
- **Port 8080.** Resolved from `PORT` in code, never baked with `ENV`.
- **`DATABASE_URL` and the data directory resolve at runtime**, explicit
  variable, then the platform-injected value, then a local default. The baked
  `ENV DATABASE_URL` that would have sent writes to the ephemeral layer is gone.
- Container runs as `USER 10001:0`.
- Version single-sourced from `spectre/__init__.py`; `pyproject.toml` reads it
  dynamically and the FastAPI app stamps it. Previously 0.1.0 and 0.4.0 disagreed.
- `pip-audit` in CI now scans `requirements.lock` rather than a hand-maintained
  duplicate list, so CI and the image can never disagree about what was scanned.

### Removed

- `bluestaq-foundations-server-python-tailored.zip` (456 KB), committed in error.

---

## [Unreleased]

### Added

- **Training Mode** (`spectre/training/`, `spectre/web/routes/training.py`, `spectre/web/templates/training.html`)
  - Full gamification system: 6 proficiency levels (Cadet → Expert), XP/points engine, five skill axes
  - 13 structured training scenarios covering all 6 levels; each defines Blue+Red assets (synthetic TLEs), objectives, tool workflow, and answer specification
  - Timed challenge scenarios that unlock at Level 4+
  - Step-by-step tutorials per skill axis with XP awards on completion
  - Live SPECTRE console embed via iframe (lazy-loaded) — operators use real tools against scenario data inside the training session
  - DB-persisted training sessions and progress (`TrainingSession`, `TrainingProgress`, `TrainingChallengeResult` ORM models)
  - Training mode banner with sticky amber warning strip; persistent "Return to Operations" control
  - Training session metrics: scenarios passed, tutorials completed, challenges passed, time in training, total points
  - Recommended next step widget based on current level and skill-axis gaps
  - All 13 scenarios designed for tool-only use (Assets panel + Intercept Engine + Decision Engine); no UDL dependency in training

- **Decision Engine Phase 1** (`spectre/domain/decision.py`, `spectre/web/routes/decision.py`)
  - Deterministic what-if analysis: define a grid of N adversary actions × M friendly responses
  - Outcome matrix: each cell computes `composite_score`, `custody_maintained`, `custody_gap_h`, `closest_approach_km`, `time_to_intercept_h`, `delta_v_cost_km_s`
  - Three selector strategies: Minimax (minimise worst-case), Expected Value (probability-weighted), Maximin (maximise best-case)
  - Robust recommendation banner + per-adversary ranked response cards
  - `GET /plan/decision/panel` scenario builder; `POST /plan/decision/evaluate` evaluator

- **Pattern of Life — NOTSO Correlation** (`spectre/astro/notso.py`, `spectre/web/routes/pol.py`)
  - `NOTSORecord` parser for USSPACECOM free-text and structured message formats
  - `correlate_notsos_with_manoeuvres()`: temporal matching of NOTSO windows against detected manoeuvre epochs
  - `OperatorBehaviourProfile`: aggregated statistics on notification lead time, ΔV magnitude accuracy, phantom NOTSO rate
  - `/pol/notso-panel` and `/pol/notso-correlate` routes; graceful fallback when UDL has no NOTSO endpoint
  - Results partial: three-column matched/notso-only/manoeuvre-only table + behaviour profile card

- **Pattern of Life — Monte Carlo Simulation** (`spectre/astro/monte_carlo.py`, `spectre/web/routes/pol.py`)
  - `ManoeuvreHypothesis` and `ManoeuvreType` dataclasses; `MANOEUVRE_ARCHETYPES` dict (park, shadow, inspection, rendezvous, evasion)
  - Vectorised NumPy sample generation: Gaussian/uniform ΔV magnitude, Rayleigh pointing cone, Gaussian timing, Gaussian B*
  - RIC→ECI rotation via pre-manoeuvre state unit vectors
  - RK45 integrator (scipy) with J2 + exponential atmosphere drag; `ProcessPoolExecutor` for parallel sample propagation
  - `MonteCarloResult`: P5/P50/P95 SMA/ecc/inc/RAAN distributions, position cloud 3σ radius, regime probability breakdown, convergence diagnostics
  - `/pol/monte-carlo` route; per-manoeuvre `[Monte Carlo ▶]` button in PoL results; regime probability bar chart and percentile table
  - Added `scipy>=1.11` dependency

- **Pattern of Life — Photometry Analysis** (`spectre/astro/photometry.py`, `spectre/web/routes/pol.py`)
  - `PhotometryObservation` dataclass with observer geometry fields (airmass, elevation, range, solar phase, lunar phase)
  - Geometric corrections: range normalisation (reduced magnitude), Rozenberg airmass, lunar quality flagging
  - `fit_baseline()`: quadratic phase function via `scipy.optimize.curve_fit` + iterative sigma-clipping
  - `detect_change()`: Student's t-test on recent residuals vs baseline window; `PhotometryChangeAssessment`
  - Manoeuvre correlation: for each detected brightness change, search for manoeuvres within ±48 h
  - `/pol/photometry-panel` and `/pol/photometry-analyse` routes; "Photometry" tab in PoL results

- **Pattern of Life — TLE Cadence Filtering** (`spectre/astro/tle_filter.py`)
  - `TLECluster` dataclass with `span_seconds` property
  - `cluster_tles()`: groups sorted `TLERecord` list by regime-aware minimum spacing threshold
  - `select_representative()`: best TLE per cluster — lowest RMS residual → latest epoch → highest element set number
  - `quality_flag_sequence()`: staleness, B* discontinuity, and element-jump flags across the representative sequence
  - `filter_tle_history()`: top-level pipeline returning `(representatives, flags)` tuple
  - Cadence-filter checkbox in PoL panel; quality flags summary in PoL results
  - `TLE_FILTER` thresholds added to `spectre/config/constants.py`

- **CW Geometry Module** (`spectre/astro/cw_geometry.py`)
  - Clohessy-Wiltshire equations for Hill-frame relative motion
  - Relative state vector computation; NMC (natural motion circumnavigation) safety ellipse parameters

- **CW Geometry Route** (`spectre/web/routes/geometry.py`)
  - `GET /plan/geometry/panel` — Hill-frame visualiser
  - `POST /plan/geometry/intercept` — compute Hill-frame trajectory for given (blue, red, response) parameters

- **NOTSO Cache** (`spectre/data/notso_cache.py`)
  - Persistent NOTSO record storage keyed by NORAD ID; retrieval interface for Decision Engine Phase 5 priors (planned)

- **Security hardening**
  - `.pre-commit-config.yaml`: `gitleaks` v8.18.4, `ruff`, `bandit[toml]`, `mypy`, standard hooks (large files, YAML/TOML validation, no-commit-to-branch master)
  - `CODEOWNERS`: `@Higgy-843` owns `.github/`, `spectre/web/auth.py`, `spectre/web/routes/login.py`, `spectre/web/database.py`, `spectre/config/`, `docs/SECURITY.md`
  - `.github/dependabot.yml`: weekly pip + GitHub Actions dependency updates; Europe/London schedule; labels: `dependencies`, `security`, `ci`
  - `pyproject.toml`: `[tool.bandit]` configuration section added; `hypothesis>=6.0`, `bandit[toml]>=1.7`, `pip-audit>=2.7` added to dev extras
  - `docs/SECURITY.md`: full UK NCSC / SSCoP aligned security policy (classification, incident response, secure development, supply chain)

- **CI pipeline rewrite** (`.github/workflows/ci.yml`)
  - `permissions: contents: read` at top level (principle of least privilege)
  - `lint` job: ruff + mypy
  - `test` job: full pytest suite with coverage
  - `sast` job: bandit with `pyproject.toml` config
  - `sca` job: pip-audit for CVE scanning of dependencies
  - `secrets` job: gitleaks v8.18.4 secret scan

- **New test modules**
  - `tests/unit/test_monte_carlo.py`
  - `tests/unit/test_notso.py`
  - `tests/unit/test_photometry.py`
  - `tests/unit/test_tle_filter.py`
  - `tests/unit/test_decision.py`
  - `tests/unit/test_training_gamification.py`
  - `tests/unit/test_cw_geometry.py`
  - `tests/unit/test_threat_sweep.py`
  - `tests/unit/test_udl_tle_fetch.py`
  - `tests/unit/test_exceptions.py`

### Changed

- `pyproject.toml`: added `numpy>=2.0`, `python-dotenv>=1.0`, `scipy>=1.11`, `scikit-learn>=1.4` to runtime dependencies (previously undeclared but used); removed `pywin32` (no imports in codebase)
- All 13 training scenarios rebuilt — removed all PoL/NOTSO/Monte Carlo/HRR auto-fetch references; scenarios now require only Assets panel, Intercept Engine, and Decision Engine so they are usable without a live UDL connection
- `spectre/training/config/scenarios.yaml`: added comment block documenting tool capabilities and design rules for future scenario authors
- Training mode `tpanel-console` iframe: lazy-loaded on first tab activation; `training-main` switches to `position:relative` / `overflow:hidden` when console tab is active so the iframe fills the panel correctly

### Fixed

- Training mode leave redirect: `POST /training/leave` now redirects to `/` (operator console), not `/operator`
- Training session `datetime` subtraction: naive/aware mismatch when computing `time_in_training_minutes`; both datetimes now forced to UTC-aware before subtraction
- Training active scenario layout: objectives, descriptions, and answer inputs now render correctly in scenario detail partial

---

## [Unreleased — prior sprint]

### Added

- **GCAT Browser** (`spectre/web/routes/gcat.py`)
  - Fully interactive browser for the General Catalog of Artificial Space Objects (J. McDowell, planet4589.org/space/gcat; CC-BY)
  - 28 TSV datasets across four categories: Derived, Objects, Payloads, Supporting
  - `GET /gcat/panel` returns the panel skeleton instantly (< 50 ms, no network I/O)
  - `GET /gcat/table` fetches the requested dataset on first access then serves from in-memory `_CACHE`; supports column search, single-column sort, and windowed pagination
  - `POST /gcat/refresh` concurrently re-downloads all 28 datasets using `asyncio.gather` + `ThreadPoolExecutor`
  - HTMX out-of-band swaps (`hx-swap-oob`) update nav button row counts after each table load
  - Debounced search input (350 ms); `urlquote` Jinja2 filter registered in `app.py`
  - CSS `position: absolute; inset: 0` layout for the GCAT hero panel
  - Fixed loading overlay always-visible bug: `.gcat-load-overlay` defaulted to `display: flex` — corrected to `display: none` with `.gcat-load-overlay.htmx-request { display: flex }`
  - Added `pandas>=2.0` dependency

- **Pattern of Life panel** (`spectre/astro/pattern_of_life.py`, `spectre/web/routes/pol.py`)
  - Historical TLE sequence analysis: period tracking, manoeuvre detection, activity classification, and behavioural baseline
  - Hero tab lazy-loaded via HTMX; Chart.js zoom/pan via `hammer.min.js` + `chartjs-plugin-zoom.min.js`
  - Dual-fetch strategy: `/elset/current` for latest TLE + `/elset` with epoch for history

- **Threat Sweep redesign** (`spectre/web/routes/threat.py`)
  - HRR group dropdown (Blue/Red HRR by rank 0–5) with TLE pre-fetch on selection
  - Batch Hohmann evaluation across 5 orbital epochs; top 5 auto-refined with Lambert for VNB components
  - TLE clustering via DBSCAN before sweep run; elevated-uncertainty flag (▲) for multi-cluster objects
  - Sentinel pattern: background sweep re-run when asset set changes
  - Collapsible TLE Cadence Filter Flags section in results (collapsed by default)

- **HRR Watchlist sub-tab** in the Assets panel
  - Blue HRR and Red HRR tables with one-click **→ Blue** / **→ Red** buttons
  - Button replaced by OOB confirmation badge on success

- **Intercept engine expansion** (`spectre/web/routes/maneuver.py`, `spectre/astro/tactical.py`)
  - 23 total methods across Classical, Tactical, Advanced Analysis, and Decision Support categories
  - All-intercepts comparison result partial
  - Trade-space ΔV vs transfer-time scatter plot with zoom/pan

### Changed

- Architecture completely migrated from STK-dependent hexagonal adapter pattern to pure-Python astrodynamics; `spectre/stk_adapter/` and `spectre/intercept_engine/` packages removed; `spectre/astro/` package now provides all orbital mechanics
- `docs/architecture.md` rewritten to reflect current pure-Python stack

---

## [0.1.0] — 2026-03-04

### Added

- Initial project scaffold with hexagonal architecture
- `IStkSession` Protocol (stk_adapter/interface.py)
- `FakeStkSession` unit-test double (stk_adapter/fake.py)
- `StkComSession` COM stub (stk_adapter/com_session.py)
- Domain models: `BlueAsset`, `RedTrack`, `InterceptWindow`, `RunConfig`, `AccessInterval`
- `ScenarioPlanner` stub (domain/scenario.py)
- Geometry helpers stub (domain/geometry.py)
- structlog configuration with run_id correlation (app_logging/setup.py)
- Constants and runtime settings (config/)
- pytest unit test stubs
- GitHub Actions CI (lint + unit tests on ubuntu-latest)
- Docker + uvicorn deployment
- Architecture, operator guide, and STK object model notes (docs/)

> **Note:** v0.1.0 used STK COM integration for all orbital mechanics. This was completely replaced in favour of pure-Python astrodynamics in the subsequent sprint. The STK adapter, PySide6 UI, and `intercept_engine/` package have all been removed. No upgrade path from v0.1.0 is provided — start fresh.
