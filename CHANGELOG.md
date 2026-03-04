# Changelog

All notable changes to SIPC will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
