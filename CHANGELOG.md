# Changelog

All notable changes to SIPC will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
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
