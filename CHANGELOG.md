# Changelog

All notable changes to SIPC will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **GCAT Browser** (`sipc/web/routes/gcat.py`)
  - Fully interactive browser for the General Catalog of Artificial Space Objects
    (J. McDowell, planet4589.org/space/gcat; CC-BY)
  - 28 TSV datasets registered across four categories: Derived, Objects, Payloads,
    Supporting
  - `GET /gcat/panel` returns the panel skeleton instantly (< 50 ms, no network I/O);
    skeleton includes header chips (datasets loaded / total records / last refreshed),
    4-tab category navigator, and per-dataset nav buttons
  - `GET /gcat/table` fetches the requested dataset on first access (~2–5 s via
    `ThreadPoolExecutor`) then serves from in-memory `_CACHE` thereafter; supports
    column search (all columns, case-insensitive), single-column sort (ascending /
    descending), and windowed pagination (configurable page size, ±3 page window)
  - `POST /gcat/refresh` concurrently re-downloads all 28 datasets using
    `asyncio.gather` + `ThreadPoolExecutor` and replaces the full panel via
    HTMX `hx-swap="outerHTML"`
  - HTMX out-of-band swaps (`hx-swap-oob`) update nav button row counts after each
    table load without re-rendering the panel
  - Debounced search input (350 ms); `urlquote` Jinja2 filter registered in `app.py`
    for safe URL construction in sort/pagination links
  - CSS `position: absolute; inset: 0` layout for the GCAT hero panel (avoids
    `height: 100%` chain failures); `position: relative` added to `.hero-panels`
  - Fixed loading overlay always-visible bug: `.gcat-load-overlay` defaulted to
    `display: flex` (overriding `.htmx-indicator { display: none }`) — corrected to
    `display: none` with `.gcat-load-overlay.htmx-request { display: flex }`
  - Added `pandas>=2.0` dependency (pandas 3.x installed)

- **Pattern of Life panel** (`sipc/astro/pattern_of_life.py`, `sipc/web/routes/pol.py`)
  - Historical TLE sequence analysis: period tracking, manoeuvre detection, activity
    classification, and behavioural baseline from NORAD catalogue number input
  - Hero tab lazy-loaded via HTMX; Chart.js zoom/pan via `hammer.min.js` +
    `chartjs-plugin-zoom.min.js`

- **Threat Sweep redesign** (`sipc/web/routes/threat.py`)
  - HRR group dropdown (Blue/Red HRR by rank 0–5) with TLE pre-fetch on selection
  - Batch Hohmann evaluation across 5 orbital epochs (now, apogee, perigee, ascending
    node, descending node); top 5 auto-refined with Lambert for VNB components
  - Sentinel pattern: background sweep re-run when asset set changes
  - One-click asset ingestion into Blue/Red lists directly from sweep results

- **HRR Watchlist sub-tab** in the Assets panel
  - Blue HRR and Red HRR tables with one-click **→ Blue** / **→ Red** buttons
  - Button replaced by OOB confirmation badge on success

- **Intercept engine expansion** (`sipc/web/routes/maneuver.py`, `sipc/astro/tactical.py`)
  - 23 total methods: Classical (Lambert, Hohmann, Bi-elliptic, Rendezvous, Proximity),
    Tactical (Phasing, CW Radial, CW Along-Track, Plane Change, J2 Drift, COLA, Evasion),
    Advanced Analysis (GEO Drift, NMC, Manoeuvre Detect, Detectability),
    Decision Support (Intent Predict, Intercept Envelope, Stability, Fingerprint,
    Formation Defence, Terrain, Min-Time)
  - All-intercepts comparison result partial
  - Trade-space ΔV vs transfer-time scatter plot with zoom/pan

### Changed
- Architecture completely migrated from STK-dependent hexagonal adapter pattern to
  pure-Python astrodynamics; `sipc/stk_adapter/` and `sipc/intercept_engine/` packages
  removed; `sipc/astro/` package now provides all orbital mechanics
- `docs/architecture.md` rewritten to reflect current pure-Python stack
- `sipc/astro/constants.py` extended with J2 coefficient, sidereal rate, additional
  unit conversions
- `sipc/domain/models.py` extended with `InterceptResult`, `BurnResult`, updated enums

---

### Added (prior — Phase 6 — Intercept Engine Integration)
- **Phase 6 — Intercept Engine Integration**
  - `sipc/intercept_engine/` package: `LambertPlanner`, `RendezvousPlanner`, `ProximityInterceptPlanner`, `OptimalInterceptPlanner` moved from disconnected `intercept engine/` folder into proper Python package
  - `InterceptMethod` enum (`lambert`, `rendezvous`, `proximity`, `optimal`) in `domain/models.py`
  - `InterceptConfig` dataclass for direct calculate-and-apply operations
  - `MCSBuilder` (`stk_adapter/mcs_builder.py`): translates intercept engine dict plans into STK Astrogator COM segment calls (Target Sequence with DC/Optimizer profile, Cartesian VNC controls)
  - `IStkSession.apply_intercept_plan(config: InterceptConfig) -> ManeuverOption` protocol method + `FakeStkSession` stub
  - `StkComSession.apply_intercept_plan`: three-phase implementation — (1) targeting MCS with DC, (2) extract solved ΔV, (3) apply as fixed MCS so satellite permanently moves in STK
  - `ManeuverSearchConfig` extended with optional intercept engine fields (`intercept_methods`, `manoeuvre_start`, `coast_hours`, `intercept_hours`, `number_of_burns`, `target_distance_m`, `minimize_delta_v`) — all backward-compatible with defaults
  - `POST /plan/maneuver/apply-intercept` endpoint for direct intercept calculation and application
  - `/plan/maneuver/search` extended to accept and forward intercept engine parameters alongside existing burn-location search
  - Dedicated "Intercept Engine" operator panel: algorithm selection, timing inputs, Calculate & Apply button
  - `_set_initial_state_epoch()` helper: robust STK 13 epoch assignment via `init_seg.Epoch.Value` (direct `.Epoch =` assignment raises COM exception in STK 13)
  - `_EngineLogger` adapter bridging Python `logging.Logger` to intercept engine `.log(msg, tag)` API

### Fixed
- `init_seg.Epoch = "..."` raises `"Property 'Insert.Epoch' can not be set."` in STK 13 — `Epoch` is an `IAgDate` sub-object; fixed via `init_seg.Epoch.Value = "..."` at all four call sites in `com_session.py`

- **Phase 5 — Astrogator Intercept Maneuver Planning**
  - `BurnType`, `BurnLocation`, `ManeuverOption`, `ManeuverSearchConfig` domain models
  - `ManeuverPlanner` service with full input validation (window, ΔV budget, non-empty burn sets)
  - `IStkSession.compute_maneuver_options()` / `apply_maneuver()` protocol methods + `FakeStkSession` stubs
  - `StkComSession` Astrogator MCS implementation: per-location × per-type differential corrector search; red satellite SGP4 propagator always restored in `finally` block
  - `/plan/maneuver/search`, `/plan/maneuver/refresh`, `/plan/maneuver/select` HTMX API routes
  - Intel/Mission panel: Maneuver Options section with burn-type / burn-location checkboxes, window pickers, max ΔV input, sortable results table, and Select action
  - 17 unit tests covering all `ManeuverPlanner` validation paths and sort order
- `IStkSession.list_scenario_satellites()` — enumerate Satellite children from the active STK scenario
- `POST /stk/import-satellites` — maps `B_SAT_*` / `R_SAT_*` objects from an existing STK scenario into SIPC session state; responds with `HX-Refresh` so dropdowns re-populate without re-adding or re-propagating satellites
- "Import from Scenario" button in the connected STK panel (recovers session state after app restart)
- UDL HRR watchlist: incremental 1→2→3 day lookback (stops when results found); correct extraction from `msgBody`; sortable table with column headers; name pre-filled from `commonName`
- Orbit Catalog search panel with live UDL lookup (name or SATNO, 50-result cap)
- TLE age badge: days from scenario start, "STALE" warning when > 7 days
- Tooltips (`title` attributes) on all interactive UI elements across the operator console, login page, and all HTMX partials

### Fixed
- `ePropagatorAstrogator` corrected to `12` (was `8`) — confirmed from STK 13 gen_py stubs (`AgEVePropagatorType` enum)
- `AddSegsFromFile` "Failed to add the TLE": name line now uses `satno` (not STK object name); platform-native `\r\n` line endings on Windows
- TLE line 1 `+` sign normalisation at five sign positions (cols 33, 44, 50, 53, 59) before `AddSegsFromFile`
- Non-standard TLE line length (≠ 69 chars) now logged as `WARNING` with exact content to aid diagnosis
- `CoInitialize` called in `_require_connection` to handle FastAPI thread-pool dispatch
- `Annotated[str, Query(...)] = ""` pattern for `name_override` fixes `AttributeError` when route is called directly in tests
- `gencache.EnsureModule` used for stub generation instead of `EnsureDispatch`
- `ExecuteCommand` / Connect command layer blocked by ODTK: all TLE and satellite operations now use Object Model exclusively

### Changed
- "Refresh from Live Orbit" button renamed to "Re-run Last Search" (clarifies actual behaviour)
- `ePropagatorAstrogator` fallback changed from `WARNING` log to `DEBUG` (confirmed value; fallback is expected path, not degraded)
- `planning_state.py`: `log_entries` changed from `list[str]` to `deque[str](maxlen=500)` — O(1) eviction, no manual `pop(0)`
- `planning_state.py`: `stk_session` typed as `IStkSession | None` (under `TYPE_CHECKING`) instead of bare `Any`
- All route modules: removed per-module `_templates()` closures; centralised in `sipc/web/deps.py`
- `operator.py`: `asyncio.get_event_loop()` → `asyncio.get_running_loop()` (correct API inside async functions; `get_event_loop()` deprecated in Python 3.10+)
- `maneuver_refresh`: now re-uses `state.last_maneuver_config` stored after a successful search instead of reconstructing config with hardcoded defaults

### Added (refactor)
- `sipc/web/deps.py` — centralised `get_templates()` / `get_com_session()` shared by all route modules; eliminates circular-import `_templates()` pattern
- `SessionState.last_maneuver_config: ManeuverSearchConfig | None` — stores the operator's last search parameters so **Re-run Last Search** reproduces them exactly
- `IStkSession.get_satellite_tle(sat_name) -> str | None` — read back TLE from an existing STK satellite (used when importing scenario satellites so imported assets carry real TLEs)
- `IStkSession.get_scenario_time() -> tuple[datetime, datetime]` — read scenario start/stop from STK after Attach/Load; auto-populates `state.scenario_start` / `state.scenario_stop` on connect
- TLE auto-pad to exactly 69 chars (`ljust(69)[:69]`) in `_set_propagator_via_om` before writing to temp file
- Duplicate-name guard in `add_blue_asset` / `add_red_track`: returns an `stk_error` banner instead of silently adding a second copy
- `stk_error` context key in `blue_list.html` / `red_list.html` partials — surfaces STK push failures to the operator inline without a page reload

## [0.1.0] — 2026-03-04

### Added
- Initial project scaffold with hexagonal architecture
- `IStkSession` Protocol (stk_adapter/interface.py)
- `FakeStkSession` unit-test double (stk_adapter/fake.py)
- `StkComSession` COM stub (stk_adapter/com_session.py)
- Domain models: `BlueAsset`, `RedTrack`, `InterceptWindow`, `RunConfig`, `AccessInterval`
- `ScenarioPlanner` stub (domain/scenario.py)
- Geometry helpers stub (domain/geometry.py)
- PySide6 QMainWindow shell (ui/main_window.py)
- QApplication entry point with `main()` (ui/app.py)
- QThread worker base for off-thread STK calls (ui/workers.py)
- Panel stubs: AssetPanel, InterceptPanel, RunLogPanel
- ScenarioViewModel stub
- structlog configuration with run_id correlation (app_logging/setup.py)
- Constants and runtime settings (config/)
- pytest unit test stubs with FakeStkSession fixture
- Integration test stub with `@pytest.mark.integration` opt-in guard
- GitHub Actions CI (lint + unit tests on ubuntu-latest)
- PyInstaller build helper script (scripts/build_exe.py)
- Architecture, operator guide, and STK object model notes (docs/)
