# Intercept Engine

The SPECTRE intercept engine is implemented entirely in pure Python across `spectre/astro/` and dispatched by `spectre/web/routes/maneuver.py`. It provides 23 solver methods grouped into four categories.

> **Historical note:** An earlier version of SPECTRE used STK Astrogator COM integration for intercept planning (`spectre/intercept_engine/`, `spectre/stk_adapter/`). That architecture was removed when the codebase migrated to pure-Python astrodynamics. This document describes the current implementation.

---

## Method Categories

### Classical Transfers

| Method | Key input | Output |
|--------|-----------|--------|
| **Lambert** | coast_h, tof_h | Δv₁ (VNB), Δv₂ (VNB), miss distance |
| **Hohmann** | — | Δv₁, Δv₂, transfer time |
| **Bi-elliptic** | intermediate SMA | Δv₁, Δv₂, Δv₃, transfer time |
| **Rendezvous** | coast_h | Δv (VNB), relative velocity at arrival |
| **Proximity** | coast_h, stand-off km | Δv (VNB), range at arrival |

### Tactical Manoeuvres

| Method | Description |
|--------|-------------|
| **Phasing** | Phasing orbit to advance/retard along-track position by a target angle |
| **CW Radial** | Clohessy-Wiltshire radial separation — set a prescribed radial offset |
| **CW Along-Track** | Clohessy-Wiltshire along-track drift — controlled drift in the Hill frame |
| **Plane Change** | Combined or pure plane change; node-crossing timing |
| **J2 Drift** | Exploit J2 RAAN precession to align RAAN with a target; coast or active |
| **COLA** | Collision avoidance manoeuvre — minimum ΔV to achieve a target miss distance |
| **Evasion** | Optimal defensive evasion — maximise miss distance per ΔV unit |

### Advanced Analysis

| Method | Description |
|--------|-------------|
| **GEO Drift** | Longitude relocation via drift orbit; east/west drift rate; station acquisition epoch |
| **NMC** | Natural Motion Circumnavigation — passive safety ellipse sizing and phasing |
| **Manoeuvre Detect** | Classify a TLE-pair delta as manoeuvre type (Hohmann, plane change, combined, drag) |
| **Detectability** | Assess observability of an intercept given ground-based sensor geometry |

### Decision Support

| Method | Description |
|--------|-------------|
| **Intent Predict** | Adversary intent prediction from approach geometry, ΔV budget, and NOTSO history |
| **Intercept Envelope** | Reachability analysis — ΔV-feasible intercept positions over the planning horizon |
| **Stability** | Relative motion stability classification (bounded, drifting, diverging) |
| **Fingerprint** | Behavioural classification of a manoeuvre sequence against known archetypes |
| **Formation Defence** | Formation-aware COLA — simultaneous protection of multiple Blue assets |
| **Terrain** | Orbital regime risk mapping — identify crowded altitude/inclination bands |
| **Min-Time** | Minimum-time intercept — fastest feasible transfer given a ΔV budget |

---

## Module Map

| Module | Responsibility |
|--------|---------------|
| `spectre/astro/maneuvers.py` | Hohmann, bi-elliptic, rendezvous, proximity |
| `spectre/astro/transfers.py` | Lambert solver (universal variable method) |
| `spectre/astro/lambert.py` | Lambert targeting: multi-revolution, batched evaluation |
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

The Lambert solver in `transfers.py` uses the universal variable (Battin) formulation. It iterates on the universal variable `x` using Halley's method until the desired time of flight is matched. The solution is always computed for the prograde direction; retrograde and multi-revolution solutions are available via `lambert.py`.

### J2 RAAN drift

The J2 RAAN precession rate is:

```
dΩ/dt = −(3/2) n J2 (Rₑ/p)² cos(i)
```

where `n` is the mean motion, `J2 = 1.08263×10⁻³`, `Rₑ = 6378.137 km`, `p = a(1−e²)` is the semi-latus rectum, and `i` is inclination. SPECTRE uses this to compute how many days of natural RAAN drift are needed before a plane-change manoeuvre can be reduced to a specified ΔV.

### SGP4 propagation

All propagation uses the `sgp4` Python library (Vallado algorithm, `WGS72` constants by default, `WGS84` available). Epoch handling uses the SGP4 built-in `jday()` conversion to avoid timezone ambiguity.
