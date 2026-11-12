# Intercept Engine

The SPECTRE intercept engine is implemented entirely in pure Python across `spectre/astro/` and dispatched by `spectre/web/routes/maneuver.py`. It provides 23 solvers in five categories, and two declared aliases.

> **Historical note:** An earlier version of SPECTRE used STK Astrogator COM integration for intercept planning (`spectre/intercept_engine/`, `spectre/stk_adapter/`). That architecture was removed when the codebase migrated to pure-Python astrodynamics. This document describes the current implementation.

---

## Method Categories

The batch runs all 23 methods and ranks the results in three groups: red approaches, avoidance and defence, and
assessments. Each red approach is searched for its cheapest plan that reaches the target, flown to measure its
closest approach and banded for realism against the NOTSO record (see "Targeting, flight and realism" below); the
other methods are solved once with the panel's values.

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

Shown as "Avoidance and defence" in the batch: blue's options and burns that move away, never ranked as red threats
(SPC-234).

| Method | Description |
|--------|-------------|
| **COLA** | Collision avoidance — minimum ΔV to achieve a target miss distance |
| **Evasion** | Defensive evasion against the threat's predicted position, within the ΔV budget |
| **Formation Defence** | Formation-aware defensive burn |

### Assessment

These return a 0-100 score, not a miss distance. In the batch, J2 drift joins them: it reports the RAAN gap natural
precession closes, in degrees, often over years, and is not a red approach (SPC-234).

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
| `spectre/astro/flight.py` | Flies a plan's burns and measures its closest approach, through `maneuvers.flown_approach` (SPC-234) |
| `spectre/astro/targeting.py` | Searches burn point, time of flight, revolutions and hops for the cheapest plan that arrives (SPC-234) |
| `spectre/domain/manoeuvre_evidence.py` | The on-station delta-V record from NOTSOs, shipped and merged with the NOTSO cache (SPC-234) |
| `spectre/domain/realism.py` | Realism bands: Seen before, Possible, Unrealistic, each with its reason (SPC-234) |
| `spectre/data/manoeuvre_evidence.json` | The shipped record: catalogue numbers, satellite names, dates and delta-V figures only |
| `spectre/web/routes/maneuver.py` | Route dispatcher — maps HTTP form fields → solver calls → HTML partial |

---

## Result Format

Every method returns an `InterceptResult` dataclass (`spectre/domain/models.py`).
Delta-V is in m/s throughout.

| Field | Type | Description |
|-------|------|-------------|
| `red_name` | `str` | The interceptor |
| `blue_name` | `str` | The target |
| `method` | `InterceptMethod` | Enum value identifying the solver (an alias names the solver it ran in `notes`) |
| `burns` | `list[BurnResult]` | Per-burn breakdown (see below) |
| `total_delta_v_m_s` | `float` | Sum of the burn magnitudes (m/s) |
| `arrival_epoch` | `datetime` | UTC time the interceptor reaches its final position |
| `intercept_range_km` | `float` | Miss distance (km). In the batch, a red approach's flown closest approach; NaN when the flown search could not run, shown as "not computed" and never read as arriving (SPC-238) |
| `notes` | `str` | Provenance line: the solver, or for a heuristic assessment that it is an uncalibrated score |
| `option_id` | `str` | Unique result identifier (`INT_…`) |
| `score` | `float \| None` | An assessment's 0 to 100 score, the envelope's feasible count, or a drift method's angular gap; `None` for a trajectory |
| `score_kind` | `str` | What `score` measures, with its unit where it has one |
| `provenance` | `str` | `physics` for a solved quantity, `heuristic` for a score of uncalibrated weights, shown with a "modelled estimate" badge |

Each `BurnResult`:

| Field | Type | Description |
|-------|------|-------------|
| `burn_number` | `int` | Position in the sequence, from 1 |
| `segment_name` | `str` | Display label, "Burn 1", "Burn 2" and so on |
| `burn_epoch` | `datetime` | UTC time of the burn |
| `delta_v_m_s` | `float` | Burn magnitude (m/s) |
| `dv_prograde` | `float` | Along the velocity vector (m/s) |
| `dv_normal` | `float` | Along the orbit normal (m/s) |
| `dv_radial` | `float` | Along the radius vector (m/s) |

---

## Route Dispatch (`maneuver.py`)

All under `/plan/maneuver`, behind login.

`POST /plan/maneuver/apply-all-intercepts`: what the Intercept Engine form posts.
Runs all 23 methods on the same inputs (red and blue satellite, manoeuvre start,
coast, time of flight, approach distance, ΔV budget, revolutions, hops, drift
days, data mode and targeting mode), ranks the results, replaces the trade-space
history with them and returns `partials/all_intercepts_result.html`. The counts
and the targeting mode are read through the `_shaping_form` dependency, because
the route is at the Code Quality gate's 13-parameter limit. A form that sends no
targeting mode searches; `targeting_mode=typed` solves each method once with the
typed values, as before. The ΔV budget defaults to 171.8 m/s.

`POST /plan/maneuver/apply-intercept`: one method by name, for scripted use. It
appends its result to the history (the latest 200 are kept) and returns
`partials/intercept_result.html`.

`GET /plan/maneuver/trade-space-data`: the history as JSON points (ΔV in m/s,
transfer time in minutes, `miss_km` or, for an assessment method, `score`),
fetched when the operator renders the trade-space chart. A miss that was not
computed is `null`, never NaN, which no JSON parser reads (SPC-238).

`POST /plan/maneuver/clear-history`: empties the history.

`GET /plan/maneuver/orbital-events`: apogee, perigee and node times for the
selected satellites.

---

## Targeting, flight and realism (SPC-234)

Ported from the charming-dirac branch (d3447e2, "realistic intercepts from the NOTSO record") by the owner's ruling
of 2026-11-12. The batch used to solve each method once with the typed coast, time of flight, revolutions and hops,
report several solvers' requested standoff as their miss, rank blue's defensive burns as red threats and let
minimum-time spend the whole budget.

**Flight.** Every red approach but the V-bar and H-bar hops is flown: red is propagated by SGP4 to its first burn,
each burn is applied in turn, two-body between burns, and the separation from the target (SGP4) is searched to
arrival by `spectre.astro.closest_approach`, 96 samples a revolution, each minimum refined to a second. A plan that
arrives the moment it fires, such as a plane change, is flown for one revolution. This is one path with 0.33.0's:
plane change, phasing and the R-bar hop fly their own burn through the same `maneuvers.flown_approach`, and inside
the batch each solver runs under `miss_not_read`, so a kept plan is flown once. The hops keep 0.33.0's figure in the
sequence's own linear model, because their solvers list only the first and last burn, and the row says so. Each
flown miss is shown with SPC-202's 1-sigma element-set error band beside it: both sets' along-track error at the
closest approach, by `spectre/astro/along_track.py`'s model, in quadrature. When the search cannot run (no finite
separation, or past `closest_approach`'s 100,000 samples, as an R-bar time of about 70 days in LEO needs), the miss
is NaN: the method still solves, the page says "not computed", and the row is never read as arriving (SPC-238).

**Search.** For each red approach the engine tries, from each burn point (now, and the red satellite's next apogee,
perigee, ascending and descending node within one revolution), the choices below, solves them all, then flies them
cheapest first and keeps the cheapest that comes within the approach distance; once one arrives nothing dearer is
flown. When none arrives, the one that comes closest is kept and labelled "No approach". Nothing is dropped for not
arriving (owner ruling, 2026-11-12).

| Method | Burn point | Time of flight | Revolutions | Hops |
|--------|-----------|----------------|-------------|------|
| Lambert, R-bar hop, CW drift | ● | ● | | |
| Phasing | ● | | ● | |
| V-bar hop, H-bar hop | ● | | | ● |
| Hohmann, bi-elliptic, plane change, NMC, GEO drift, minimum-time | ● | | | |

When searching, minimum-time is given a realistic budget instead of the panel's maximum: 36.8 m/s, or the red
satellite's own busiest 14 days on station when that is more. A minimum-time plan always spends its whole budget, so
at the panel's maximum its ΔV measured the panel, not the satellite.

**Realism.** Each red approach is banded against what satellites have spent on station in 14 days, as JCO NOTSOs
state it (959 on-station burns by 129 satellites, 28 April 2022 to 27 March 2026, merged at run time with the NOTSO
cache): Seen before (within this satellite's own busiest 14 days), Possible (within 171.8 m/s, the most any
satellite spent) or Unrealistic. The NOTSO cache can raise a satellite's own figures, but never the 171.8 m/s
ceiling, which sets Possible against Unrealistic for every satellite: that comes from the shipped, reviewed record only
(lead's ruling in review of SPC-234, confirmed by the owner on 2026-11-12). The panel's sentence about the record describes the shipped record. A malformed
cache record is skipped on its own; catalogue numbers are compared without leading zeros ("05678" is 5678); the
merge is recomputed only when the cache has changed. A plan is not an arrival when the target is already within the
radius with no burn over the same window (flown as a baseline): such rows read "Already within" and never count.
Arrival allows the larger of 1 m and a millionth of the radius, as a flown miss lands micrometres either side of an
aim point. A red approach counts towards the worst case and the "Most likely course of action"
headline only if it arrives and is not Unrealistic. The record is a floor on what satellites have done, not a ceiling
on what they could do: an Unrealistic row stays listed, dimmed, with its reason.

**Constants.** None reaches the Decision Engine, so none is in `docs/lookup-register.md`, whose test covers the
Decision Engine's own modules only.

| Figure | Value | Where | Source | Owner | Set |
|--------|-------|-------|--------|-------|-----|
| Fleet maximum, busiest 14 days on station | 171.8 m/s (COSMOS 2589) | `manoeuvre_evidence.json` `fleet.largest_window_m_s`; `maneuver.ENGINE_DEFAULT_BUDGET_M_S` | JCO TACREP_NOTSO export, 3,124 messages, built by `scripts/build-manoeuvre-evidence.py` in d3447e2 | Owner ruling 2026-11-12: the engine's Max ΔV default | 2026-10-31 (d3447e2); default 2026-11-12 (SPC-234) |
| Nine in ten satellites stay within | 36.8 m/s (36.77) | `fleet.typical_window_m_s` | as above, 0.9 quantile | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |
| Window | 14 days | `manoeuvre_evidence.WINDOW_DAYS` | none: tuned, not sourced | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |
| Approach radius | 50 km, or the panel's "Approach within" | `realism.CLOSE_APPROACH_KM` | none: an assumption for the analyst to confirm | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |
| Time-of-flight grid | 0.25, 0.5, 0.75, 1, 1.5, 2, 3 red revolutions | `targeting.TOF_FRACTIONS` | none: tuned, not sourced | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |
| Revolutions grid | 1 to 6 | `targeting.REVOLUTIONS` | none: tuned, not sourced | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |
| Hops grid | 1 to 5 | `targeting.HOPS` | none: tuned, not sourced | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |
| Launch-phase floor | 20 m/s | `manoeuvre_evidence._LAUNCH_PHASE_FLOOR_M_S` | none: tuned, not sourced | Claude's choice (d3447e2), unassigned | 2026-10-31 (d3447e2) |

Measured on the GEO test pair 1 degree apart and a LEO pair 2 degrees apart, from 1 March 2026: the batch took
0.030 s (GEO) and 0.056 s (LEO) before; typed, 0.047 s and 0.179 s; searched, 0.484 s and 0.951 s, with the no-burn
baseline flown only for a plan that arrives. It runs off the
web server's main thread, as before. On the GEO pair the searched Lambert costs 10.8 m/s against 72.6 m/s typed.

---

## Trade-Space Plot

Once results exist, the operator renders a scatter plot of the history in ΔV against transfer-time space, colour-coded by method, from the trade-space bar. Assessment methods carry a score, not a miss, and their points say so. Zoom/pan is enabled via `hammer.min.js` + `chartjs-plugin-zoom.min.js`.

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
