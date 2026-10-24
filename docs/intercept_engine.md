# Intercept Engine

The SPECTRE intercept engine is implemented entirely in pure Python across `spectre/astro/` and dispatched by `spectre/web/routes/maneuver.py`. It provides 23 solvers in five categories, and two declared aliases.

> **Historical note:** An earlier version of SPECTRE used STK Astrogator COM integration for intercept planning (`spectre/intercept_engine/`, `spectre/stk_adapter/`). That architecture was removed when the codebase migrated to pure-Python astrodynamics. This document describes the current implementation.

---

## Method Categories

The batch runs each of the 23 solvers once and ranks the results.

### Classical Transfers

| Method | Key input | Output |
|--------|-----------|--------|
| **Lambert** | coast_h, tof_h | Δv₁ (VNB), Δv₂ (VNB), miss distance |
| **Hohmann** | — | Δv₁, Δv₂, transfer time, propagated miss |
| **Bi-elliptic** | intermediate SMA | Δv₁, Δv₂, Δv₃, transfer time |
| **Min-Time** | ΔV budget | fastest feasible transfer within the budget |

### Proximity Operations

| Method | Description |
|--------|-------------|
| **Phasing** | Phasing orbit to advance or retard along-track position; Revolutions field |
| **R-bar hop** | Clohessy-Wiltshire radial separation to a prescribed radial offset |
| **V-bar hop** | Hops along the velocity vector; Hops field |
| **H-bar hop** | Hops across track; Hops field |
| **CW Drift** | Clohessy-Wiltshire along-track drift, controlled in the Hill frame |
| **NMC** | Natural Motion Circumnavigation — passive safety ellipse sizing and phasing |

### Orbital Manoeuvres

| Method | Description |
|--------|-------------|
| **Plane Change** | Combined or pure plane change; node-crossing timing |
| **J2 Drift** | Exploit J2 RAAN precession to align RAAN with a target |
| **GEO Drift** | Longitude relocation via drift orbit; Drift (days) field |

### Defensive

| Method | Description |
|--------|-------------|
| **COLA** | Collision avoidance — minimum ΔV to achieve a target miss distance |
| **Evasion** | Defensive evasion against the threat's predicted position, within the ΔV budget |
| **Formation Defence** | Formation-aware defensive burn |

### Assessment

These return a 0-100 score, not a miss distance.

| Method | Description |
|--------|-------------|
| **Detectability** | Observability of an intercept given ground-based sensor geometry |
| **Intent Predict** | Adversary intent prediction from approach geometry, ΔV budget, and NOTSO history |
| **Stability** | Relative motion stability classification (bounded, drifting, diverging) |
| **Fingerprint** | Behavioural classification of a manoeuvre sequence against known archetypes |
| **Terrain** | Orbital regime risk mapping — crowded altitude and inclination bands |
| **Manoeuvre Detect** | Classify a TLE-pair delta as a manoeuvre type |
| **Intercept Envelope** | Reachability — ΔV-feasible intercepts over the planning horizon |

### Aliases

**Rendezvous** and **Proximity** are not separate solvers. Rendezvous runs the
Hohmann solver and Proximity the Lambert transfer; the batch leaves them out,
and a result requested under either name says which solver it ran
(`_METHOD_ALIASES` in `spectre/web/routes/maneuver.py`).

---

## Module Map

| Module | Responsibility |
|--------|---------------|
| `spectre/astro/maneuvers.py` | the intercept solvers: Hohmann, bi-elliptic, phasing, hops, plane change, drift, COLA, evasion and the rest |
| `spectre/astro/transfers.py` | Hohmann and bi-elliptic transfer costs (vis-viva closed forms) |
| `spectre/astro/lambert.py` | Lambert solver: universal variables, single and multiple revolutions |
| `spectre/astro/tactical.py` | All 17 tactical and decision-support categories |
| `spectre/astro/cw_geometry.py` | Hill-frame / Clohessy-Wiltshire equations |
| `spectre/astro/propagator.py` | SGP4 propagation; `TLEOrbit.propagate()` |
| `spectre/astro/events.py` | Orbital event detection (apogee, perigee, nodes) |
| `spectre/web/routes/maneuver.py` | Route dispatcher — maps HTTP form fields → solver calls → HTML partial |

---

## Result Format

Every method returns an `InterceptResult` dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `method` | `InterceptMethod` | Enum value identifying the solver |
| `total_delta_v_km_s` | `float` | Total ΔV magnitude (km/s) |
| `burns` | `list[BurnResult]` | Per-burn breakdown (see below) |
| `intercept_range_km` | `float` | Miss distance at arrival epoch (km) |
| `transfer_time_h` | `float` | Coast time from burn to intercept (hours) |
| `notes` | `str` | Human-readable summary |

Each `BurnResult`:

| Field | Type | Description |
|-------|------|-------------|
| `burn_epoch` | `datetime` | UTC time of burn |
| `delta_v_km_s` | `float` | Burn magnitude (km/s) |
| `dv_radial` | `float` | Radial (R) component in VNB frame |
| `dv_along_track` | `float` | Along-track (T) / in-track component |
| `dv_cross_track` | `float` | Cross-track (N) component |
| `location_label` | `str` | Human label (e.g. "Apogee", "Ascending Node") |

---

## Route Dispatch (`maneuver.py`)

`POST /plan/maneuver/calculate` — main intercept solver route:

1. Parse form fields: `red_satno`, `blue_satno`, `method`, `coast_h`, `tof_h`, plus method-specific params
2. Fetch TLEs from `SessionState` (assets must already be loaded)
3. Resolve `InterceptMethod` enum → dispatch to the appropriate `spectre.astro` function
4. Wrap result in `InterceptResult`; append to `state.intercept_history`
5. Return `partials/intercept_result.html` fragment via HTMX swap

`GET /plan/maneuver/tradespace` — trade-space scatter data:

- Returns all `InterceptResult` objects from `state.intercept_history` as a Chart.js dataset
- Called automatically after the second intercept result is added (HTMX trigger)

---

## Trade-Space Plot

After two or more intercept results are computed, a scatter plot appears automatically showing all results in ΔV vs transfer-time space, colour-coded by method. Zoom/pan is enabled via `hammer.min.js` + `chartjs-plugin-zoom.min.js`.

Use this to identify the optimal trade-off between fuel cost and time of arrival. Methods that appear in the lower-left quadrant (low ΔV, short time) are the most efficient under the current orbital geometry.

---

## Solver Implementation Notes

### Lambert (universal variable method)

The Lambert solver is in `spectre/astro/lambert.py`. It is Curtis, *Orbital
Mechanics for Engineering Students*, Algorithm 5.2: universal variables with
Stumpff functions, solved for z by bracketed bisection on the time-of-flight
residual. The transfer direction follows the departure velocity, so a
retrograde orbit gets a retrograde arc. `solve_lambert` returns the
zero-revolution arc; `solve_lambert_all` also returns the multi-revolution
solutions (each band (2πN)² < z < (2π(N+1))², both branches), and
`cheapest_lambert` the one costing least, which the intercept engine and the
envelope sweep use. Branches are bracketed on a fixed grid of z, so a pair
whose minimum time of flight only just reaches the request can be missed.
Validated against Curtis Example 5.2 and by propagating each solution
(tests/unit/test_lambert_validation.py, test_lambert_multi_revolution.py).

### J2 RAAN drift

The J2 RAAN precession rate is:

```
dΩ/dt = −(3/2) n J2 (Rₑ/p)² cos(i)
```

where `n` is the mean motion, `J2 = 1.08263×10⁻³`, `Rₑ = 6378.137 km`, `p = a(1−e²)` is the semi-latus rectum, and `i` is inclination. SPECTRE uses this to compute how many days of natural RAAN drift are needed before a plane-change manoeuvre can be reduced to a specified ΔV.

### SGP4 propagation

All propagation uses the `sgp4` Python library (Vallado algorithm, `WGS72` constants by default, `WGS84` available). Epoch handling uses the SGP4 built-in `jday()` conversion to avoid timezone ambiguity.
