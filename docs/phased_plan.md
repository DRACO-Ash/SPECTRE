# SIPC — Phased Development Plan

Last updated: 2026-03-05

---

## Phase 1 — Foundation ✅ COMPLETE

Core scaffold, architecture, and live STK wiring.

| Item | Status |
|------|--------|
| Hexagonal architecture (stk_adapter / domain / web) | Done |
| `IStkSession` Protocol + `FakeStkSession` test double | Done |
| `StkComSession` — connect, new_scenario, folder setup | Done |
| `StkComSession` — create_satellite, set_propagator, compute_access | Done |
| Domain models (BlueAsset, RedTrack, RunConfig, InterceptWindow, AccessInterval) | Done |
| `ScenarioPlanner` — provision assets + compute access windows | Done |
| FastAPI + HTMX web console (dark-mode military theme) | Done |
| Session auth (signed cookies, admin bootstrap, 8hr expiry) | Done |
| Operator dashboard — asset CRUD, run plan, run log | Done |
| STK connection panel — connect to existing / create new scenario | Done |
| UDL — login/logout with credential probe | Done |
| UDL — TLE fetch → pre-fill asset form | Done |
| UDL — state vector fetch | Done |
| structlog with run_id correlation | Done |
| Unit tests (FakeStkSession, auth, planning_state) | Done |
| FastAPI TestClient integration tests | Done |
| Docker + uvicorn deployment | Done |

---

## Phase 2 — Core Intercept Geometry ⬅ CURRENT

Fill the remaining stub/hardcoded gaps to produce real intercept data.

### 2.1 Min-range query (highest priority)
`ScenarioPlanner._compute_windows` hardcodes `min_range_km=0.0`.
Resolve via STK data provider:

- Add `get_range_at_time(obj_a, obj_b, epoch) -> float` to `IStkSession` + `FakeStkSession` + `StkComSession`
- In `StkComSession`, use `IAgDataPrvInterval` or a `Range` figure-of-merit on the access object to retrieve the minimum range over each access interval
- Wire into `ScenarioPlanner._compute_windows` to replace the hardcoded `0.0`
- Update `FakeStkSession` to return a deterministic non-zero value for tests

### 2.2 Geometry helpers — proper SEZ transform
`geometry.azimuth_elevation_range` uses a placeholder angle calculation.
Replace with a correct ECEF → local SEZ (South-East-Zenith) transform:

- Compute geodetic lat/lon of observer from ECEF
- Build rotation matrix: ECEF → SEZ
- Derive true azimuth and elevation from the SEZ components

### 2.3 Intercept window — add asset pair labels
`InterceptWindow` does not record which blue/red pair produced it.
The results table cannot show "Alpha vs Track01" without this.

- Add `blue_name: str` and `red_name: str` fields to `InterceptWindow`
- Update `ScenarioPlanner._compute_windows` to populate them
- Update `partials/results_table.html` to display the pair

### 2.4 Tests for Phase 2 additions
- Unit test: `get_range_at_time` via FakeStkSession
- Unit test: SEZ geometry against known reference values
- Unit test: `InterceptWindow` pair labels round-trip through ScenarioPlanner

---

## Phase 3 — Enhanced Data & UI

Richer data sources and improved operator experience.

### 3.1 Scenario time window controls
- Expose scenario start/stop epoch and step size in the operator UI
- Route: `POST /stk/scenario-time` → calls `StkComSession.set_scenario_time(start, stop, step)`
- Add `set_scenario_time` to `IStkSession` + adapters

### 3.2 UDL — additional data types
Beyond TLEs and state vectors, add routes for:
- `GET /udl/conjunction?satno=<N>` — CDM/conjunction data (close approach warnings)
- `GET /udl/observation?satno=<N>` — sensor observation history

### 3.3 Results export
- Add `GET /plan/export?run_id=<id>` returning a CSV of intercept windows
- Or: copy-to-clipboard button on the results table via HTMX + JS

### 3.4 User management UI
Currently DB-only (documented workaround in README).
Add a minimal admin-only panel:
- `GET /admin/users` — list users
- `POST /admin/users` — add user
- `POST /admin/users/{id}/delete` — remove user

### 3.5 Fix README passlib reference
The user management section of `README.md` references `passlib` which is
no longer a dependency. Update to use `bcrypt` directly:
```python
import bcrypt
hash = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
```

---

## Phase 4 — Production Hardening

Quality, observability, and operational robustness.

### 4.1 UDL route tests
`tests/integration/` has no coverage for `web/routes/udl.py`.
Add TestClient tests for:
- `POST /udl/login` — 200 (mock httpx), 401, timeout, unreachable
- `GET /udl/tle` — happy path, no session, no results
- `GET /udl/statevector` — happy path, no session, no results

### 4.2 STK error surfacing in UI
`StkCommandError` and `StkConnectionError` are currently caught by the
operator route and logged, but the operator sees a generic failure.
Return structured HTMX error partials with the actual STK error message.

### 4.3 Rate limiting & session hardening
- Add per-user rate limit on `/udl/*` proxy routes (prevent credential hammering)
- Add CSRF protection (FastAPI middleware or double-submit cookie)

### 4.4 Structured logging review
- Confirm all routes emit `run_id` in log context where applicable
- Add request/response timing middleware for slow-query detection

### 4.5 CI pipeline
- Add GitHub Actions workflow: lint (ruff) + unit tests on push
- Add Docker build check to CI

---

## Backlog / Future Consideration

These are not scheduled but recorded for later discussion:

- **Multi-scenario support** — run multiple named scenarios concurrently per operator session
- **Intercept scoring / figure of merit** — rank windows by geometry quality (closure rate, elevation angle, range rate)
- **Maneuver planning** — integrate STK Astrogator for delta-V calculation
- **PostgreSQL** — already switchable via `DATABASE_URL`; no code change needed, but needs ops runbook
- **Role-based access** — currently single `admin`/`operator` roles; may need finer-grained permissions
- **Real-time SSE updates** — push access computation progress to the run log as it computes (currently polling)
