# SPECTRE — Phased Development Plan

Last updated: 2026-04-08

---

> **Architecture note:** Phases 1–6 below describe the original STK COM-based architecture, retained here for historical context. That architecture was fully replaced with a pure-Python implementation. The **Current State** section at the top reflects what is built and deployed today.

---

## Current State — 2026-04-08

### Implemented and in production

| Capability | Modules | Notes |
|-----------|---------|-------|
| Pure-Python intercept engine (23 methods) | `spectre/astro/maneuvers.py`, `transfers.py`, `lambert.py`, `tactical.py`, `cw_geometry.py` | Replaces all STK solver paths |
| SGP4 propagation + orbital events | `spectre/astro/propagator.py`, `events.py` | sgp4 library (Vallado) |
| Threat Sweep + TLE clustering | `spectre/web/routes/threat.py`, `spectre/astro/tle_preprocessing.py`, `tle_clustering/` | DBSCAN per-satellite de-duplication |
| Pattern of Life — base analysis | `spectre/astro/pattern_of_life.py`, `spectre/web/routes/pol.py` | Manoeuvre detection, activity baseline |
| Pattern of Life — TLE cadence filter | `spectre/astro/tle_filter.py` | Cluster/select/flag pipeline |
| Pattern of Life — NOTSO correlation | `spectre/astro/notso.py` | Parser, correlation, behaviour profile |
| Pattern of Life — Monte Carlo | `spectre/astro/monte_carlo.py` | RK45 + J2 + drag, P5/P50/P95, regime probs |
| Pattern of Life — Photometry | `spectre/astro/photometry.py` | Phase function baseline, t-test change detection |
| Decision Engine (Phase 1) | `spectre/domain/decision.py`, `spectre/web/routes/decision.py` | Deterministic analytic scoring |
| GCAT Browser | `spectre/web/routes/gcat.py` | 28 datasets, DBSCAN search/sort/paginate |
| HRR Watchlist | `spectre/web/routes/udl.py` | One-click → Blue/Red asset import |
| Training Mode | `spectre/training/`, `spectre/web/routes/training.py` | 6 levels, 13 scenarios, tutorials, challenges |
| Session auth + DB bootstrap | `spectre/web/auth.py`, `spectre/web/database.py` | bcrypt, itsdangerous, 8 hr expiry |
| CI pipeline | `.github/workflows/ci.yml` | lint, test, sast, sca, secrets jobs |
| Pre-commit security hooks | `.pre-commit-config.yaml` | gitleaks, ruff, bandit, mypy |
| CODEOWNERS | `CODEOWNERS` | Security-path review gates |
| Dependabot | `.github/dependabot.yml` | Weekly pip + Actions updates |

### Open backlog (prioritised)

| ID | Description | Priority |
|----|-------------|---------|
| P1-A | CSRF middleware + `/udl/*` rate limiting | P1 |
| P1-B | UDL `datatype` filter (REAL/SIMULATED/EXERCISE/TEST) per panel | P1 |
| P1-C | User management web UI (`/admin/users`) | P1 |
| P2-A | Decision Engine Phase 2 — Monte Carlo integration | P2 |
| P2-B | UDL conjunction + observation endpoints | P2 |
| P2-C | Intercept results export (CSV) | P2 |
| P2-D | UDL route integration tests | P2 |
| P3-A | Decision Engine Phase 3 — SGP4-propagated outcomes | P3 |
| P3-B | Roll-up reporting dashboard | P3 |
| P3-C | Decision Engine Phase 5 — NOTSO-informed priors | P3 |
| P4-A | Decision Engine Phase 4 — multi-turn game tree | P4 |
| P4-B | Orekit migration evaluation | P4 |

See `memory/project_todo_backlog.md` for full detail and dependencies.

---

## Historical — STK-Era Phases (v0.1.0)

The sections below describe the original development plan when SPECTRE used STK COM integration. They are retained for historical context only. All STK-specific items are obsolete.

---

### Phase 1 — Foundation ✅ COMPLETE (STK era)

Core scaffold, architecture, and live STK wiring.

| Item | Status |
|------|--------|
| Hexagonal architecture (stk_adapter / domain / web) | Done |
| `IStkSession` Protocol + `FakeStkSession` test double | Done |
| `StkComSession` — connect, new_scenario, folder setup | Done |
| Domain models (BlueAsset, RedTrack, RunConfig, InterceptWindow, AccessInterval) | Done |
| `ScenarioPlanner` — provision assets + compute access windows | Done |
| FastAPI + HTMX web console (dark-mode military theme) | Done |
| Session auth (signed cookies, admin bootstrap, 8hr expiry) | Done |
| UDL — login/logout, TLE fetch, state vector fetch | Done |
| structlog with run_id correlation | Done |
| Unit + integration tests | Done |
| Docker + uvicorn deployment | Done |

---

### Phase 2 — Core Intercept Geometry (STK era)

Min-range query, SEZ geometry, asset pair labels in results.

**Status:** Superseded — replaced by pure-Python propagation and geometry in `spectre/astro/`.

---

### Phase 3 — Enhanced Data & UI (STK era)

Scenario time controls, UDL conjunction/observation endpoints, results export, user management UI.

**Status:** Partially superseded. UDL conjunction (P2-B) and user management UI (P1-C) remain as open backlog items above.

---

### Phase 4 — Production Hardening (STK era)

UDL route tests, CSRF/rate limiting, structured logging review, CI pipeline.

**Status:** Partially done. CI pipeline ✅. CSRF + rate limiting (P1-A) remain open. UDL route tests (P2-D) remain open. Structured logging in place.

---

### Phase 5 — Astrogator Intercept Option Generation ✅ COMPLETE (STK era)

STK Astrogator MCS-based manoeuvre search with differential corrector.

**Status:** Superseded and removed. All manoeuvre planning is now pure-Python via `spectre/astro/tactical.py` and `spectre/web/routes/maneuver.py` (23 methods). The `spectre/stk_adapter/` and `spectre/intercept_engine/` packages have been deleted.

---

### Phase 6 — Intercept Engine Integration ✅ COMPLETE (STK era)

Integration of `LambertPlanner`, `RendezvousPlanner`, `ProximityInterceptPlanner`, `OptimalInterceptPlanner` as STK Astrogator plan generators.

**Status:** Superseded. See `docs/intercept_engine.md` for the current pure-Python implementation.

---

## Future Roadmap

See `docs/decision_engine_phases.md` for the Decision Engine phase roadmap (Phases 2–5).

### Aspirational items (no design doc yet)

- **AI pattern learning** — feed historical SPECTRE data into a model to learn operator patterns and anomalous RSO behaviour
- **Cohort comparison in training dashboard** — anonymised team/quartile comparison (requires multi-user tracking design and privacy review)
- **Daily/weekly challenge mechanics** — rotating challenge scenarios on a schedule
- **Orekit migration** — replace `spectre/astro/` with Orekit Python bindings for higher-fidelity force models (see P4-B above)
