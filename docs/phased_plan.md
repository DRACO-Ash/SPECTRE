# SIPC — Phased Development Plan

Last updated: 2026-03-07

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

## Phase 2 — Core Intercept Geometry

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

### 3.5 Fix README passlib reference ✅ Done
The user management section of `README.md` now uses `bcrypt` directly
(`bcrypt.hashpw` / `bcrypt.gensalt`). `passlib` is no longer a dependency.

---

## Phase 4 — Production Hardening

Quality, observability, and operational robustness.

### 4.1 UDL route tests
`tests/integration/` has no coverage for `web/routes/udl.py`.
Add TestClient tests for:
- `POST /udl/login` — 200 (mock httpx), 401, timeout, unreachable
- `GET /udl/tle` — happy path, no session, no results
- `GET /udl/statevector` — happy path, no session, no results

### 4.2 STK error surfacing in UI *(partially done)*
`StkCommandError` and `StkConnectionError` are caught by the operator route and
surfaced via an `stk_error` context key rendered as an inline banner in
`blue_list.html` and `red_list.html` — the operator sees the actual error message
without a page reload.  Remaining: propagate the same pattern to other failure
paths (scenario create/load, run-plan failures).

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

---

## Phase 5 — Astrogator Intercept Option Generation ✅ COMPLETE

Enumerate viable intercept maneuver options for a Red satellite against a Blue target
using STK Astrogator MCS.  Sits **alongside** `compute_access` — not a replacement.
See `docs/astrogator_notes.md` for STK COM reference.

### 5.1 — Domain models  `[x]`

New types in `sipc/domain/models.py`:

- **`BurnType`** enum — `IMPULSIVE | FINITE`
- **`BurnLocation`** enum — `APOGEE | PERIGEE | ASCENDING_NODE | DESCENDING_NODE | NORTH_POLE | SOUTH_POLE | CUSTOM`
- **`ManeuverOption`** dataclass:

  | Field | Type | Description |
  |-------|------|-------------|
  | `option_id` | `str` | Auto UUID |
  | `red_name` | `str` | Red STK object name |
  | `blue_name` | `str` | Blue STK object name |
  | `burn_type` | `BurnType` | Impulsive / Finite |
  | `burn_location` | `BurnLocation` | Orbital geometry tag |
  | `burn_epoch` | `datetime` | UTC time to execute burn |
  | `delta_v_km_s` | `float` | Total ΔV magnitude (km/s) |
  | `dv_prograde` | `float` | VNC prograde component (km/s) |
  | `dv_normal` | `float` | VNC normal component (km/s) |
  | `dv_radial` | `float` | VNC radial component (km/s) |
  | `intercept_epoch` | `datetime` | When intercept occurs |
  | `transfer_duration_s` | `float` | Coast time burn → intercept (s) |
  | `intercept_range_km` | `float` | Miss distance at intercept (km) |
  | `notes` | `str` | Human label e.g. "Hohmann via apogee" |

- **`ManeuverSearchConfig`** dataclass:
  - `red_sat`, `blue_sat` — STK object names
  - `search_window_start`, `search_window_stop` — `datetime`
  - `max_delta_v_km_s` — `float` (discard solutions above this)
  - `burn_types` — `list[BurnType]`
  - `burn_locations` — `list[BurnLocation]`

### 5.2 — IStkSession + FakeStkSession + ManeuverPlanner  `[x]`

- Add `compute_maneuver_options(config) -> list[ManeuverOption]` to `IStkSession` Protocol
- Add `apply_maneuver(red_sat, option) -> None` to `IStkSession` Protocol
- `FakeStkSession` returns deterministic stub `ManeuverOption` list for unit tests
- New `sipc/domain/maneuver_planner.py` — `ManeuverPlanner.compute_options(config, session)`
  validates inputs, delegates, sorts by `delta_v_km_s` ascending, logs provenance
- Unit tests: validation errors, sort order, FakeStkSession round-trip

### 5.3 — Web routes `/plan/maneuver/`  `[x]`

| Route | Method | Action |
|-------|--------|--------|
| `/plan/maneuver/search` | `POST` | Run search; return `maneuver_options_table.html` partial |
| `/plan/maneuver/refresh` | `POST` | Re-run with same config from live STK state |
| `/plan/maneuver/select` | `POST` | Store selected option in session; return status partial |

`SessionState` gains `maneuver_options: list[ManeuverOption]` and
`selected_maneuver: ManeuverOption | None`.

### 5.4 — Intel / Mission UI panel  `[x]`

New section below the force columns in `operator.html` — `panel-intel` accent colour.

Controls:
- Red asset dropdown (populated from `state.red_tracks`) vs Blue asset dropdown
- Search window start / stop datetime inputs
- Max ΔV (km/s) numeric input
- Burn type checkboxes: Impulsive / Finite
- Burn location checkboxes: Apogee / Perigee / AN / DN / Poles
- **[Generate Options]** — HTMX POST to `/plan/maneuver/search`
- **[Refresh from Live Orbit]** — HTMX POST to `/plan/maneuver/refresh`

Maneuver options table (sortable, same JS pattern as HRR):

| Location | Type | Burn Epoch (UTC) | ΔV km/s | Transfer | Intercept Range | Notes | |
|----------|------|-----------------|---------|----------|-----------------|-------|--|
| Apogee | Impulsive | 2026-03-06 … | 0.312 | 47 min | 0.8 km | … | [Select] |

Sorted by ΔV ascending on load.  [Select] fires POST to `/plan/maneuver/select`.

### 5.5 — StkComSession — Astrogator COM  `[x]`

`compute_maneuver_options` core loop:

1. Get red satellite object; snapshot its current SGP4 propagator state
2. For each enabled `BurnLocation` × candidate burn epochs (stepped through window):
   - `SetPropagatorType(ePropagatorAstrogator)`
   - Build MCS: `InitialState → Propagate (coast) → Maneuver → Propagate → TargetSequence`
   - Set target constraint: range to blue satellite < threshold at intercept epoch
   - Run differential corrector; if converged → extract ΔV, epochs, miss distance → `ManeuverOption`
   - Non-convergence: DEBUG-log and skip
3. Restore red satellite to SGP4 + original TLE (in `finally` block)
4. Return all solved options

`apply_maneuver`: write selected `ManeuverOption` into the red satellite's Astrogator MCS
as a fixed (non-targeting) sequence ready for propagation.

See `docs/astrogator_notes.md` for Astrogator enum values and MCS COM patterns.

### 5.6 — Integration tests  `[ ]` ⬅ CURRENT

- Unit test: `ManeuverPlanner` validation (bad window, no burn types, dv ≤ 0)
- Unit test: `FakeStkSession` returns options sorted by ΔV
- Integration test (opt-in, requires STK + Astrogator licence): one impulsive apogee burn
  solves and returns a `ManeuverOption` with `intercept_range_km < 1.0`
- 17 `ManeuverPlanner` unit tests implemented (validation paths + sort order)

### Technical risks

| Risk | Mitigation |
|------|-----------|
| Astrogator licence absent | Check at connect time; surface clear error in panel; disable controls |
| ODTK blocks MCS construction | MCS is pure OM — should be unaffected; verify with first live test |
| Differential corrector non-convergence | Drop silently; DEBUG-log; operator sees only solved options |
| Computation time | Run in executor thread (existing pattern); consider SSE progress streaming |
| Propagator state corruption | Restore SGP4 + TLE in `finally`; never leave satellite in Astrogator state after search |
| Astrogator enum values unknown | Discover from gen_py stubs at runtime; document in `astrogator_notes.md` |

### Implementation order

1. 5.1 domain models (no STK dependency)
2. 5.2 FakeStkSession + ManeuverPlanner + unit tests
3. 5.3 web routes + 5.4 UI panel (end-to-end with fake session)
4. 5.5 StkComSession Astrogator COM (requires live STK + licence)
5. 5.6 integration tests

---

## Backlog / Future Consideration

These are not scheduled but recorded for later discussion:

- **Multi-scenario support** — run multiple named scenarios concurrently per operator session
- **Intercept scoring / figure of merit** — rank windows by geometry quality (closure rate, elevation angle, range rate)
- **PostgreSQL** — already switchable via `DATABASE_URL`; no code change needed, but needs ops runbook
- **Role-based access** — currently single `admin`/`operator` roles; may need finer-grained permissions
- **Real-time SSE updates** — push access computation progress to the run log as it computes (currently polling)
