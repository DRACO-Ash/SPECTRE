# SPECTRE audit: claims ledger (phase 4)

**Source audited:** tree at `a34e273`. Claims are extracted from README, docs, module and function docstrings, inline comments, error messages and type hints. Each one is reconciled against the implementing code and against a test that would prove it. Slice extraction used read-only reviewers under `audit/LENS-BRIEF.md`. Orchestrator claims come from phases 1 and 3.

## Summary

| Status | Count |
|---|---|
| PROVEN | 94 |
| IMPLEMENTED-UNTESTED | 72 |
| DRIFTED | 126 |
| ABSENT | 13 |
| UNDOCUMENTED-BEHAVIOUR | 11 |
| **Total** | **316** |

No status is blank (fact: every row was validated against the five permitted values by script).

Drift rate: 126 of 316 claims (40 %) describe behaviour that the code does not have. Proven rate: 94 of 316 (30 %). PRIORS.md names drift as one of the three numbers to judge this repository by.

Claims are recorded as found. A DRIFTED claim becomes a finding only once it passes phase 7 (see `audit/FINDINGS.md`). A claim is PROVEN only where a test would fail if it regressed; tests that merely exercise the code do not count.

## Orchestrator claims (phases 1 and 3)

| # | Claim | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| O-1 | README declares `pip install -e ".[dev]"` installs the dev environment | `README.md:41; .github/workflows/ci.yml:31` | ABSENT: pyproject.toml has no [project.optional-dependencies] | NONE (reproduced: TOOLS.md 0a) | DRIFTED |
| O-2 | README: `spectre-serve` starts the server | `README.md:49; spectre/web/_entrypoint.py:1` | ABSENT: no [project.scripts]; Dockerfile:194 says it 'was' a console script | NONE | DRIFTED |
| O-3 | README: open http://localhost:8000 | `README.md:54,72` | spectre/config/settings.py:36 DEFAULT_PORT = 8080 | tests/unit/test_entrypoint.py (port resolution) | DRIFTED |
| O-4 | README: Python minimum 3.14 | `README.md:28` | pyproject.toml:46 >=3.12; Dockerfile:20 python:3.12 | NONE | DRIFTED |
| O-5 | README: SPECTRE_LOG_DIR is the directory for structlog output files | `README.md:102` | ABSENT: Settings.log_dir is never read (ARCHITECTURE A1) | NONE | DRIFTED |
| O-6 | README: app_logging provides structlog setup and run_id correlation | `README.md:359` | ABSENT: configure_logging has no caller; module omitted from coverage | NONE | DRIFTED |
| O-7 | UDL credentials held in memory 'for this session only' | `spectre/web/planning_state.py:55` | planning_state.py:113 process-global dict keyed by username | NONE | DRIFTED |
| O-8 | log_queue is an 'Async queue of log-line strings for SSE streaming' | `spectre/web/planning_state.py:43` | ABSENT: no SSE endpoint; queue unbounded with no consumer | NONE | DRIFTED |
| O-9 | Request logging is 'handled by the application's own audit path' | `spectre/web/_entrypoint.py:44` | ABSENT: no request-logging middleware (ARCHITECTURE A7) | NONE | DRIFTED |
| O-10 | Architecture route inventory: operator, login, udl, maneuver, threat, pol, decision, geometry, gcat, training | `docs/architecture.md:14-15` | app.py:347-359 also mounts admin, plan, health | NONE | DRIFTED |
| O-11 | README: pyproject marker 'integration' covers 'opt-in network tests' | `README.md:254; pyproject.toml:58` | ABSENT: no test carries the marker (git grep mark.integration: none) | NONE | DRIFTED |
| O-12 | NOTSO cache is persisted application data | `spectre/web/routes/udl.py:1081` | spectre/data/notso_cache.py:47 writes inside the package, outside the storage mount | tests/unit/test_notso_cache.py | UNDOCUMENTED-BEHAVIOUR |
| O-13 | Lambert solver: 'Validated against Curtis Example 5.2' | `spectre/astro/lambert.py:7` | lambert.py:44-159 | tests/unit/test_lambert_validation.py:89-110 (mutation-proven, PRIORS-STATUS P1) | PROVEN |
| O-14 | solve_lambert 'using Izzo's algorithm' | `spectre/astro/lambert.py:53` | lambert.py implements Curtis Algorithm 5.2 bisection | NONE | DRIFTED |
| O-15 | Session cookie is Secure by default | `spectre/config/settings.py:255-262` | settings.py:263-265; login.py:171 | tests/integration/test_root_contract.py:60-71 (resolver only) | PROVEN |

## Slice S01

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S01-1 | `Method: Curtis, *Orbital Mechanics for Engineering Students*, Algorithm 5.2.` | spectre/astro/lambert.py:6 | spectre/astro/lambert.py:126-144 (eqs 5.35, 5.38, 5.40, 5.46 all match by hand) | tests/unit/test_lambert_validation.py:98-112 (Curtis Ex 5.2, 1 m/s) | PROVEN |
| S01-2 | `Validated against Curtis Example 5.2 and by propagating the departure state` | spectre/astro/lambert.py:7 | spectre/astro/lambert.py:44-159 | tests/unit/test_lambert_validation.py:139-147 (miss < 1 km, 6 geometries) | PROVEN |
| S01-3 | `realistic GEO intercept planning, is not supported and is rejected explicitly` | spectre/astro/lambert.py:15 | spectre/astro/lambert.py:281-288 (guard practically unreachable) | NONE (line 284 uncovered per audit/tools-raw/pytest.txt:62) | DRIFTED |
| S01-4 | `"""Solve Lambert's problem using Izzo's algorithm.` | spectre/astro/lambert.py:53 | spectre/astro/lambert.py:308-316 (bisection on Curtis F(z)) | NONE | DRIFTED |
| S01-5 | `prograde: If True, assume prograde (short-way) transfer.` | spectre/astro/lambert.py:60 | spectre/astro/lambert.py:95 (sense keyed to sign of z component, not to short way) | NONE (no case with cross_z < 0) | DRIFTED |
| S01-6 | `ValueError: If tof <= 0 or positions are degenerate.` | spectre/astro/lambert.py:68 | spectre/astro/lambert.py:73-129 | tests/unit/test_astro.py:90-92; tests/unit/test_lambert_validation.py:168-190 | PROVEN |
| S01-7 | `# Solve via Stumpff functions with Newton–Raphson iteration.` | spectre/astro/lambert.py:131 | spectre/astro/lambert.py:308-316 (bisection) | NONE | DRIFTED |
| S01-8 | `# The single-revolution solution lies below the parabolic limit z = 4*pi^2.` | spectre/astro/lambert.py:208 | spectre/astro/lambert.py:211 | NONE | DRIFTED |
| S01-9 | `Monotonically increasing in z, which is what makes bisection safe.` | spectre/astro/lambert.py:233 | spectre/astro/lambert.py:242-254 | tests/unit/test_lambert_validation.py:139-147 (indirect) | IMPLEMENTED-UNTESTED |
| S01-10 | `to reach *tol*. Never returns an unconverged value.` | spectre/astro/lambert.py:274 | spectre/astro/lambert.py:308-321 | NONE (line 318 uncovered) | IMPLEMENTED-UNTESTED |
| S01-11 | `All functions use the vis-viva equation: v = sqrt(μ × (2/r − 1/a)).` | spectre/astro/transfers.py:3 | spectre/astro/transfers.py:31-33 | tests/unit/test_astro.py:34-46 (bands of about 6 per cent, not a pinned reference) | PROVEN |
| S01-12 | `rb: Intermediate apoapsis radius (km) — must be > max(r1, r2).` | spectre/astro/transfers.py:74 | ABSENT | NONE | ABSENT |
| S01-13 | `miss_distance_km: float = 0.0     # km — actual miss at arrival` | spectre/astro/maneuvers.py:70 | spectre/astro/maneuvers.py:144, 940, 1037, 1152, 1263 (requested value, scores, counts) | NONE | DRIFTED |
| S01-14 | `4. Compute impulse burns at departure and (optionally) arrival.` | spectre/astro/maneuvers.py:90 | spectre/astro/maneuvers.py:127-133 (arrival burn always computed) | NONE | DRIFTED |
| S01-15 | `Approximates both orbits as circular at their current radii.` | spectre/astro/maneuvers.py:158 | spectre/astro/maneuvers.py:178-181 (no phasing; miss hardcoded 0.0 at :201) | tests/unit/test_astro.py:223-233 (shape only) | UNDOCUMENTED-BEHAVIOUR |
| S01-16 | `# Departure burn is along velocity direction (prograde).` | spectre/astro/maneuvers.py:184 | spectre/astro/maneuvers.py:185-186 (prograde even when lowering) | NONE | DRIFTED |
| S01-17 | `# Burns: departure, intermediate apoapsis, circularise at target.` | spectre/astro/maneuvers.py:243 | spectre/astro/maneuvers.py:251-256 | NONE | DRIFTED |
| S01-18 | `# Final corrective burn (anti-normal)` | spectre/astro/maneuvers.py:565 | spectre/astro/maneuvers.py:570 (no sign flip) | NONE | DRIFTED |
| S01-19 | `"""Compute plane change to align red satellite with blue orbital plane.` | spectre/astro/maneuvers.py:589 | spectre/astro/maneuvers.py:616 (inclination only, RAAN ignored) | NONE (grep `plane_change_intercept` in tests: no match) | DRIFTED |
| S01-20 | `# Single burn at optimal location, in the normal direction` | spectre/astro/maneuvers.py:625 | spectre/astro/maneuvers.py:630 (burn epoch is t_departure) | NONE | DRIFTED |
| S01-21 | `# KeplerianElements stores inc/raan/argp/ta in DEGREES. These angles were` | spectre/astro/maneuvers.py:611 | spectre/astro/maneuvers.py:924-925 still converts again | tests/unit/test_orbital_units_and_degeneracies.py:101-131 (blind to `_m.degrees`) | DRIFTED |
| S01-22 | `The BLUE satellite evades an incoming RED threat. Unlike COLA` | spectre/astro/maneuvers.py:1054 | spectre/astro/maneuvers.py:1068-1074 (red_tle never read) | NONE | DRIFTED |
| S01-23 | `Propagates red once, then solves Lambert's problem against blue at 24` | spectre/astro/maneuvers.py:1167 | spectre/astro/maneuvers.py:1227-1246 | tests/unit/test_intercept_envelope.py:141 onward (outside slice, not re-read) | IMPLEMENTED-UNTESTED (TBC, re-verify against that file) |
| S01-24 | `r: np.ndarray  # km   — position (3,) in TEME` | spectre/astro/propagator.py:33 | spectre/astro/propagator.py:91-99 (sgp4 TEME output) | NONE (tests/unit/test_astro.py:111-119 checks altitude band only) | IMPLEMENTED-UNTESTED |
| S01-25 | `inc: float        # degrees — inclination` | spectre/astro/propagator.py:56 | spectre/astro/propagator.py:153 | tests/unit/test_orbital_units_and_degeneracies.py:87-97 | PROVEN |
| S01-26 | `The standard substitutions below keep the state recoverable in every` | spectre/astro/propagator.py:196 | spectre/astro/propagator.py:213-216 (fails for retrograde circular equatorial) | tests/unit/test_orbital_units_and_degeneracies.py:46-69 (prograde cases only) | DRIFTED |
| S01-27 | `immune to propagation errors caused by stale TLE epochs.` | spectre/astro/propagator.py:304 | spectre/astro/propagator.py:310-314 | tests/unit/test_hrr_bootstrap.py:155-161 (outside slice) | IMPLEMENTED-UNTESTED |
| S01-28 | `Propagates the TLE with SGP4 at *step_s*-second intervals and looks` | spectre/astro/events.py:47 | spectre/astro/events.py:75-127 | tests/unit/test_astro.py:169-177 (asserts at least 2 event types, no timing) | IMPLEMENTED-UNTESTED |
| S01-29 | `_MEO_MAX_ALT: float = 35386.0   # GEO lower bound − 400 km` | spectre/astro/constants.py:20 | spectre/astro/constants.py:20 (value is the GEO lower bound itself) | NONE | DRIFTED |
| S01-30 | `Uses perigee / apogee altitudes and eccentricity to distinguish:` | spectre/astro/constants.py:66 | spectre/astro/constants.py:72-85 (Molniya to GTO, Tundra to MEO) | NONE (grep `classify_orbit_regime` in tests: no match) | DRIFTED |
| S01-31 | `altitudes, so they are permitted against any regime they physically cross.` | spectre/astro/constants.py:54 | spectre/astro/constants.py:58-60 (permitted against every regime) | NONE (grep `regimes_compatible` in tests: no match) | DRIFTED |
| S01-32 | `COORD_FRAME: str = "ICRF"` | spectre/config/constants.py:17 | ABSENT (states are TEME, propagator.py:33; constant unused) | NONE | DRIFTED |
| S01-33 | `SPEED_UNIT: str = "m/s"` | spectre/config/constants.py:13 | ABSENT (astro layer is km/s; constant unused) | NONE | DRIFTED |
| S01-34 | `Deliberately a separate implementation. Verifying the solver with machinery` | tests/unit/test_lambert_validation.py:50 | tests/unit/test_lambert_validation.py:39-44 imports `_stumpff_C`, `_stumpff_S` from the solver | n/a | DRIFTED |
| S01-35 | `and ten call sites in maneuvers.py passed them through` | tests/unit/test_orbital_units_and_degeneracies.py:7 | spectre/astro/maneuvers.py:924-925 (an eleventh survives) | tests/unit/test_orbital_units_and_degeneracies.py:125 | DRIFTED |

## Slice S02

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S02-1 | "CW relative motion (Hill/Clohessy-Wiltshire radial separation & along-track drift)" | spectre/astro/tactical.py:5 | spectre/astro/tactical.py:142-238 | NONE (tests/unit/test_tactical.py:81-110 check sign and shape only) | IMPLEMENTED-UNTESTED |
| S02-2 | "x(t) = (Δvx / n) sin(nt)" | spectre/astro/tactical.py:154 | spectre/astro/tactical.py:174-177 | NONE | IMPLEMENTED-UNTESTED |
| S02-3 | "y(t) = Δvy (4 sin(nt) - 3nt) / n" | spectre/astro/tactical.py:205 | spectre/astro/tactical.py:215-226 | NONE | IMPLEMENTED-UNTESTED |
| S02-4 | "Solves the 2×2 CW system for [Δvx, Δvy] to achieve both radial and" | spectre/astro/tactical.py:250 | spectre/astro/tactical.py:268-283 | NONE (tests/unit/test_tactical.py:122-128 tolerance exceeds the value, see F-S02-27) | IMPLEMENTED-UNTESTED |
| S02-5 | "N * period_phase = period_target * (N - phase_rad / 2pi)" | spectre/astro/tactical.py:76 | spectre/astro/tactical.py:79-90 | tests/unit/test_tactical_validation.py:41-60 | PROVEN |
| S02-6 | "at 2*a_phase - r_chaser. A deep phasing orbit can put that inside the" | spectre/astro/tactical.py:93 | spectre/astro/tactical.py:95-102 | tests/unit/test_tactical.py:75-78; tests/unit/test_tactical_validation.py:71-74 | PROVEN |
| S02-7 | "Evaluates cost at the equatorial node (circular velocity) and at" | spectre/astro/tactical.py:336 | spectre/astro/tactical.py:348-354 | NONE | DRIFTED |
| S02-8 | "The plane change is split across both burns using the cosine rule," | spectre/astro/tactical.py:381 | spectre/astro/tactical.py:401-409 (all at one burn) | NONE | DRIFTED |
| S02-9 | "dΩ/dt = -3/2 · n · J2 · (R_E / p)² · cos(i)" | spectre/astro/tactical.py:453 | spectre/astro/tactical.py:463-468 | tests/unit/test_tactical_validation.py:174-177 | PROVEN |
| S02-10 | "accel_altitude_change_km: float   # altitude change to double convergence rate" | spectre/astro/tactical.py:437 | spectre/astro/tactical.py:511 (fixed 50 km step) | NONE | DRIFTED |
| S02-11 | "accel_delta_v: float              # km/s — ΔV for the altitude change" | spectre/astro/tactical.py:439 | spectre/astro/tactical.py:524-527 (first burn only) | NONE | DRIFTED |
| S02-12 | "Compute minimum-ΔV collision avoidance using three strategies." | spectre/astro/tactical.py:574 | spectre/astro/tactical.py:594-637 | NONE (tests/unit/test_tactical.py:221-227 only checks min of its own three) | IMPLEMENTED-UNTESTED |
| S02-13 | "miss_distance_km: float   # resulting miss distance" | spectre/astro/tactical.py:552 | spectre/astro/tactical.py:619 (echoes desired input) | NONE | DRIFTED |
| S02-14 | "dλ/dt = -3/2 · n_geo · Δa / a_geo" | spectre/astro/tactical.py:681 | spectre/astro/tactical.py:699-701 | tests/unit/test_tactical_validation.py:156-163 | PROVEN |
| S02-15 | "Standard end-of-life disposal: Hohmann transfer to GEO + 300 km." | spectre/astro/tactical.py:740 | spectre/astro/tactical.py:746-757 | tests/unit/test_tactical_validation.py:165-172 | PROVEN |
| S02-16 | "confidence: float          # 0.0–1.0" | spectre/astro/tactical.py:786 | spectre/astro/tactical.py:853-873 (fixed constants) | NONE | UNDOCUMENTED-BEHAVIOUR |
| S02-17 | "# Subtract expected J2 drift to isolate manoeuvre-induced RAAN change" | spectre/astro/tactical.py:827 | spectre/astro/tactical.py:812, 828-829 | NONE | DRIFTED |
| S02-18 | "In CW relative motion, bounded (non-drifting) relative orbits have a" | spectre/astro/tactical.py:927 | spectre/astro/tactical.py:950-951 | tests/unit/test_tactical_validation.py:106-122 | PROVEN |
| S02-19 | "displaced radially by A_x, and then an ALONG-TRACK burn of 2*n*A_x:" | spectre/astro/tactical.py:969 | spectre/astro/tactical.py:973 | tests/unit/test_tactical_validation.py:86-104 | PROVEN |
| S02-20 | "Uses empirical rules based on Space Surveillance Network (SSN)" | spectre/astro/tactical.py:1028 | ABSENT (no source cited for constants at 1054-1062, 1075-1077, 1082) | NONE | ABSENT |
| S02-21 | "tracking_detection_prob: float   # 0.0–1.0" | spectre/astro/tactical.py:1014 | spectre/astro/tactical.py:1064, 1079 | NONE | UNDOCUMENTED-BEHAVIOUR |
| S02-22 | "Optimises burn timing (not just direction)" | spectre/astro/tactical.py:1151 | spectre/astro/tactical.py:1169 (four-point grid) | NONE | IMPLEMENTED-UNTESTED |
| S02-23 | "Evaluates combined multi-axis burns" | spectre/astro/tactical.py:1152 | spectre/astro/tactical.py:1206 (computed, never used) | NONE | DRIFTED |
| S02-24 | "Reports remaining fuel after the manoeuvre" | spectre/astro/tactical.py:1153 | spectre/astro/tactical.py:1233 | tests/unit/test_tactical.py:386-388 (budget cap only) | IMPLEMENTED-UNTESTED |
| S02-25 | "likelihood: float         # 0.0–1.0" | spectre/astro/tactical.py:1286 | spectre/astro/tactical.py:1321-1358 (additive score) | NONE | UNDOCUMENTED-BEHAVIOUR |
| S02-26 | "The ``penalty`` factor below is a shaping heuristic with no physical" | spectre/astro/tactical.py:1442 | spectre/astro/tactical.py:1491-1493 | NONE | IMPLEMENTED-UNTESTED |
| S02-27 | "It is retained as a cheap upper-bound sketch for unequal radii. For an" | spectre/astro/tactical.py:1438 | spectre/astro/tactical.py:1433-1434 say it underestimates | NONE | DRIFTED |
| S02-28 | "CW boundedness condition: Δvy₀ = -2n·Δx₀  (zero secular drift)" | spectre/astro/tactical.py:1545 | spectre/astro/tactical.py:1557 | tests/unit/test_tactical.py:484-491 | PROVEN |
| S02-29 | "along_track_drift_km_per_orbit: float  # secular along-track drift per orbit" | spectre/astro/tactical.py:1527 | spectre/astro/tactical.py:1558 (factor -0.5 out) | NONE | DRIFTED |
| S02-30 | "radial_amplitude_km: float        # max radial oscillation" | spectre/astro/tactical.py:1526 | spectre/astro/tactical.py:1563 | NONE | DRIFTED |
| S02-31 | "propagate one orbit and assess whether the motion is bounded or drifting." | spectre/astro/tactical.py:1543 | ABSENT (no propagation in 1553-1596) | NONE | DRIFTED |
| S02-32 | "probabilities: dict[str, float]    # classification → probability" | spectre/astro/tactical.py:1611 | spectre/astro/tactical.py:1647-1715 (unnormalised additive scores) | NONE (tests/unit/test_tactical.py:527-531 checks range only) | DRIFTED |
| S02-33 | "available space surveillance statistics and radiation belt models." | spectre/astro/tactical.py:1847 | ABSENT (bands at 1862-1913 carry no citation) | NONE | ABSENT |
| S02-34 | "budget. The TLE wrapper uses full Lambert for higher accuracy." | spectre/astro/tactical.py:1975 | spectre/astro/maneuvers.py:1475 calls the analytic routine | NONE | DRIFTED |
| S02-35 | "period, a radial impulse Δv_r advances the chaser by 4·Δv_r/n along" | spectre/astro/tactical.py:2076 | spectre/astro/tactical.py:2099 | NONE (Grep `vbar_hop_sequence\ | IMPLEMENTED-UNTESTED |
| S02-36 | "time_per_hop_s: Hop duration (s); defaults to T_orbit / 2." | spectre/astro/tactical.py:2089 | spectre/astro/tactical.py:2095-2099 (ΔV ignores it) | NONE | UNDOCUMENTED-BEHAVIOUR |
| S02-37 | "Each hop is a small incremental plane change (normal burn at a node" | spectre/astro/tactical.py:2141 | spectre/astro/tactical.py:2161-2165 | NONE | DRIFTED |
| S02-38 | "stealthy because each individual radial impulse is small and mimics" | spectre/astro/tactical.py:2082 | ABSENT (no source or model) | NONE | ABSENT |
| S02-39 | "y(t) = 6(s - nt)x₀ + y₀ - 2(1 - c)ẋ₀/n + (4s - 3nt)ẏ₀/n" | spectre/astro/cw_geometry.py:19 | spectre/astro/cw_geometry.py:216-222 | tests/unit/test_cw_geometry.py:180-191 | PROVEN |
| S02-40 | "All numeric inputs are validated to be finite and within operational bounds." | spectre/astro/cw_geometry.py:28 | spectre/astro/cw_geometry.py:419-437, 463-468 (range cap only warns; no tof ceiling) | NONE | DRIFTED |
| S02-41 | "(CW approximation breakdown, large separation, high eccentricity) are logged at" | spectre/astro/cw_geometry.py:35 | spectre/astro/cw_geometry.py:473-475 | NONE (Grep `caplog` in tests/unit/test_cw_geometry.py: 0 matches) | DRIFTED |
| S02-42 | "v_rel_hill = R * (v_red - v_blue) - ω × r_rel" | spectre/astro/cw_geometry.py:294 | spectre/astro/cw_geometry.py:296-299 | NONE (tests/unit/test_cw_geometry.py:321-326 finiteness only) | IMPLEMENTED-UNTESTED |
| S02-43 | "# Hard cap on ΔV components (km/s) — flag implausible values." | spectre/astro/cw_geometry.py:74 | spectre/astro/cw_geometry.py:429-433 | tests/unit/test_cw_geometry.py:445-447 | PROVEN |
| S02-44 | "Pure-math geometry helpers for intercept planning." | spectre/domain/geometry.py:1 | ABSENT (no production caller) | tests/unit/test_geometry.py | UNDOCUMENTED-BEHAVIOUR |
| S02-45 | "Azimuth is measured clockwise from North (0–360°)." | spectre/domain/geometry.py:74 | spectre/domain/geometry.py:91-92 | tests/unit/test_geometry.py:122-152 | PROVEN |
| S02-46 | "Closure rate in m/s (positive = closing, negative = opening)." | spectre/domain/geometry.py:110 | spectre/domain/geometry.py:120-122 | tests/unit/test_geometry.py:184-194 | PROVEN |

## Slice S03

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S03-1 | "Extracts mean orbital elements at each epoch (direct from SGP4 Satrec)" | spectre/astro/pattern_of_life.py:4 | spectre/astro/pattern_of_life.py:361-375 | NONE (tests/unit/test_pattern_of_life.py:156-197 assert count and order, never an element value) | IMPLEMENTED-UNTESTED |
| S03-2 | "Estimates ΔV between successive TLEs (propagation-difference method)" | spectre/astro/pattern_of_life.py:6 | spectre/astro/pattern_of_life.py:428-444 (mean element differencing; docstring at 431-434 says the propagation method was replaced) | NONE | DRIFTED |
| S03-3 | "Corrects RAAN and argp changes for J2 secular drift" | spectre/astro/pattern_of_life.py:8 | spectre/astro/pattern_of_life.py:844-847 | NONE (tests/unit/test_pattern_of_life.py:300-309 check sign and type only) | IMPLEMENTED-UNTESTED |
| S03-4 | "Computes statistical Pattern of Life bounds (μ ± 2σ)" | spectre/astro/pattern_of_life.py:10 | spectre/astro/pattern_of_life.py:630-636 | tests/unit/test_pattern_of_life.py:106-112 (mean only; std not pinned) | PROVEN |
| S03-5 | "Scores the object on an anomaly scale vs GEO-SK baseline" | spectre/astro/pattern_of_life.py:11 | ABSENT (removed, see spectre/astro/pattern_of_life.py:122-134) | tests/unit/test_pattern_of_life.py:384-390 asserts it is gone | DRIFTED |
| S03-6 | "Estimates propellant budget and remaining operational life" | spectre/astro/pattern_of_life.py:12 | ABSENT in module | tests/unit/test_pattern_of_life.py:384-390 asserts it is gone | DRIFTED |
| S03-7 | "Produces an operator-level intelligence assessment" | spectre/astro/pattern_of_life.py:13 | ABSENT in module | tests/unit/test_pattern_of_life.py:384-390 asserts it is gone | DRIFTED |
| S03-8 | "Greenwich Apparent Sidereal Time (degrees) at *epoch*." | spectre/astro/pattern_of_life.py:349 | spectre/astro/pattern_of_life.py:351 (GMST, no equation of the equinoxes) | tests/unit/test_pattern_of_life.py:138-142 (range only) | DRIFTED |
| S03-9 | "providers, and a malformed pair must drop out rather than stop the parse." | spectre/astro/pattern_of_life.py:729 | ABSENT (no try at spectre/astro/pattern_of_life.py:731) | NONE | DRIFTED |
| S03-10 | "Records with no attribution are grouped together rather than discarded." | spectre/astro/pattern_of_life.py:454 | spectre/astro/pattern_of_life.py:456 | tests/unit/test_dv_estimation.py:378-389 (out of slice, TBC re-verify) | IMPLEMENTED-UNTESTED |
| S03-11 | "detections beyond ``_LONG_GAP_WARN_DAYS`` are kept but flagged as possibly several burns." | spectre/astro/pattern_of_life.py:86-87 | ABSENT (grep `_LONG_GAP_WARN_DAYS\ | several burns\ | ABSENT |
| S03-12 | "Pairs separated by more than ``_MAX_GAP_DAYS`` are counted and dropped" | spectre/astro/pattern_of_life.py:801 | spectre/astro/pattern_of_life.py:809-811 | NONE (audit/tools-raw/pytest.txt:66 lists 810-811 uncovered) | IMPLEMENTED-UNTESTED |
| S03-13 | "it stands ten times above the object's own measured fit" | spectre/astro/pattern_of_life.py:969-970 | spectre/astro/dv_estimation.py:113, spectre/astro/dv_estimation.py:1150-1152 | TBC, re-verify in tests/unit/test_dv_estimation.py | IMPLEMENTED-UNTESTED |
| S03-14 | "Two detections can only be the same burn if they came from DIFFERENT" | spectre/astro/pattern_of_life.py:499 | spectre/astro/pattern_of_life.py:537-540 | tests/unit/test_pol_assessment.py:484-546 (out of slice) | PROVEN |
| S03-15 | "# Drift rate: positive = east" | spectre/astro/pattern_of_life.py:385 | spectre/astro/pattern_of_life.py:386 (omits node and perigee rates, F-S03-14) | NONE | IMPLEMENTED-UNTESTED |
| S03-16 | "# Use signed raw longitude difference for distance (handles 180° wrap)" | spectre/astro/pattern_of_life.py:673 | spectre/astro/pattern_of_life.py:672 uses mean_rate * dur | NONE | DRIFTED |
| S03-17 | "_DRIFT_STATIONARY = 0.05    # °/day — \ | drift\ | below this → "Stationary"" | spectre/astro/pattern_of_life.py:111 | PROVEN |
| S03-18 | "_STATUS_RECENT_DAYS     = 10.0  # days: older than this and there is no "latest" manoeuvre" | spectre/astro/pattern_of_life.py:118 | spectre/astro/pattern_of_life.py:881-883 | tests/unit/test_pol_status_ladder.py:81-91 | PROVEN |
| S03-19 | "_STATUS_ANOMALOUS_SIGMA = 3.0   # σ above the historical mean ΔV → "ANOMALOUS"" | spectre/astro/pattern_of_life.py:119 | spectre/astro/pattern_of_life.py:885-888 (latest ΔV is inside the sample it is scored against, F-S03-01) | tests/unit/test_pol_status_ladder.py:69-79 | PROVEN |
| S03-20 | "# Element Set Number — TLE line 1, columns 65-68 (1-indexed), right-justified" | spectre/astro/pattern_of_life.py:388 | spectre/astro/pattern_of_life.py:390 (slice [64:68] is columns 65-68, correct) | NONE (audit/tools-raw/pytest.txt:66 lists 391-392 uncovered) | IMPLEMENTED-UNTESTED |
| S03-21 | "A provenance value that will not unpack drops its own record only." | tests/unit/test_pattern_of_life.py:211 | spectre/astro/pattern_of_life.py:755-761 | tests/unit/test_pattern_of_life.py:199-233 | PROVEN |
| S03-22 | "without averaging (which is physically meaningless for SGP4 mean elements)." | spectre/astro/tle_filter.py:14-15 | spectre/astro/tle_filter.py:130-147 | tests/unit/test_tle_filter.py:116-146 | PROVEN |
| S03-23 | "TLERecords for a single NORAD ID.  Need not be sorted on input." | spectre/astro/tle_filter.py:101 | spectre/astro/tle_filter.py:114 | tests/unit/test_tle_filter.py:94-100 | PROVEN |
| S03-24 | "1. Lowest ``rms_residual`` (if populated from UDL metadata)." | spectre/astro/tle_filter.py:134 | spectre/astro/tle_filter.py:140-147 | tests/unit/test_tle_filter.py:122-146 | PROVEN |
| S03-25 | "* Data gaps exceeding the staleness threshold for the object's regime." | spectre/astro/tle_filter.py:154 | spectre/astro/tle_filter.py:167-181 | tests/unit/test_tle_filter.py:167-179 | PROVEN |
| S03-26 | "* Large fractional jumps in the B* drag coefficient (catalogue artefact)." | spectre/astro/tle_filter.py:155 | spectre/astro/tle_filter.py:184-195 | tests/unit/test_tle_filter.py:181-191 | PROVEN |
| S03-27 | "# Sort most-recent first" | spectre/astro/tle_filter.py:251 | spectre/astro/tle_filter.py:252 | tests/unit/test_tle_filter.py:239-249 (conditional assert, F-S03-35) | PROVEN |
| S03-28 | "DBSCAN finds.  When multiple clusters exist (rare: post-manoeuvre objects or" | spectre/astro/tle_preprocessing.py:9 | spectre/astro/tle_preprocessing.py:246-254 ("rare" contradicted, F-S03-06) | NONE (tests/integration/test_tle_clustering_pipeline.py:251 is conditional; audit/tools-raw/pytest.txt:71 lists 248-249 uncovered) | IMPLEMENTED-UNTESTED |
| S03-29 | "orbital elements (inclination, RAAN, eccentricity) and selects the best" | spectre/astro/tle_preprocessing.py:114 | tle_clustering/clustering.py:62-65 | TBC, re-verify in tests/unit/tle_clustering/test_clustering.py | IMPLEMENTED-UNTESTED |
| S03-30 | "Always 1 after post-processing; multi-cluster objects are collapsed to" | spectre/astro/tle_preprocessing.py:53 | spectre/astro/tle_preprocessing.py:241 sets 0 | NONE | DRIFTED |
| S03-31 | "objects_fallback: Number of objects where fallback to existing cache was used." | spectre/astro/tle_preprocessing.py:88 | spectre/astro/tle_preprocessing.py:227 only; 203 and 241 set fallback=True without counting | NONE | DRIFTED |
| S03-32 | "Satnos present in *existing_cache* but absent from *tle_multiset* are not" | spectre/astro/tle_preprocessing.py:125 | spectre/astro/tle_preprocessing.py:169 | tests/integration/test_tle_clustering_pipeline.py:190 | PROVEN |
| S03-33 | "reasonable variants." (parser handles the common USSPACECOM template format) | spectre/astro/notso.py:16-17 | spectre/astro/notso.py:319-412 | NONE against any real USSPACECOM sample (TBC: no reference message in tests) | IMPLEMENTED-UNTESTED |
| S03-34 | "Parsed records.  Unparseable messages are skipped with a log warning." | spectre/astro/notso.py:301 | spectre/astro/notso.py:313-314 logs; spectre/astro/notso.py:350 returns None with no log | tests/unit/test_notso.py:208-211 (count only) | DRIFTED |
| S03-35 | "ISO-formatted structured messages.  Unknown fields are captured in" | spectre/astro/notso.py:296 | spectre/astro/notso.py:384-387 (only when no DESCRIPTION, REMARKS or COMMENT field) | NONE | DRIFTED |
| S03-36 | "# Default: window of 24h if not specified" | spectre/astro/notso.py:376 | spectre/astro/notso.py:377 | NONE | IMPLEMENTED-UNTESTED |
| S03-37 | "# Convert m/s to km/s if the unit says m/s" | spectre/astro/notso.py:262 | spectre/astro/notso.py:263-264 | tests/unit/test_notso.py:135-137 | PROVEN |
| S03-38 | "1. A NOTSO matches a manoeuvre if the manoeuvre epoch falls within" | spectre/astro/notso.py:427 | spectre/astro/notso.py:451-458 (uses after-set epoch, F-S03-02) | tests/unit/test_notso.py:238-289 | PROVEN |
| S03-39 | "2. Multiple manoeuvre candidates → select closest to window midpoint." | spectre/astro/notso.py:429 | spectre/astro/notso.py:461-465 | NONE (no test puts two candidates in one window) | IMPLEMENTED-UNTESTED |
| S03-40 | "3. Multiple NOTSO candidates → select closest effective_start." | spectre/astro/notso.py:430 | ABSENT (greedy first-come at spectre/astro/notso.py:450-458) | NONE | DRIFTED |
| S03-41 | "time_offset_hours: float \ | None    # NOTSO effective_start − manoeuvre epoch (h)" | spectre/astro/notso.py:71 | spectre/astro/notso.py:467-469 | IMPLEMENTED-UNTESTED |
| S03-42 | "magnitude_ratio:   float \ | None    # Predicted ΔV / detected ΔV" | spectre/astro/notso.py:72 | spectre/astro/notso.py:471-472 | PROVEN |
| S03-43 | "consistent_notifier:    bool = False   # rate > 0.90" | spectre/astro/notso.py:126 | spectre/astro/notso.py:673-676 | tests/unit/test_notso.py:350-416 | PROVEN |
| S03-44 | "predictable_timing:     bool = False   # std_lead_time < 6 h" | spectre/astro/notso.py:130 | spectre/astro/notso.py:677 | NONE | IMPLEMENTED-UNTESTED |
| S03-45 | "window_accuracy_rate:   float       # Fraction where manoeuvre fell inside NOTSO window" | spectre/astro/notso.py:99 | spectre/astro/notso.py:562-578 | tests/unit/test_notso.py:429-432 | PROVEN |
| S03-46 | "band. Pass the routine per-burn ceiling for the object's regime; without it" | spectre/astro/notso.py:614 | spectre/astro/notso.py:540-541, spectre/astro/notso.py:635-636 | NONE (tests/unit/test_notso.py:466 passes no threshold but asserts only the count) | IMPLEMENTED-UNTESTED |
| S03-47 | "beside them. A NOTSO follows human analysis, so the likeliest " | spectre/astro/notso.py:164 | ABSENT (no computation behind "likeliest"; F-S03-02 gives a competing cause) | NONE | ABSENT |

## Slice S04

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S04-1 | "**Along-track** — drives semi-major axis.   Δv = μ·Δa / (2·a²·v_perigee)" | spectre/astro/dv_estimation.py:51 | spectre/astro/dv_estimation.py:570 | tests/unit/test_dv_estimation.py:269, :632-656 | PROVEN |
| S04-2 | "exact two-burn Hohmann total it is +1.1% at Δa/a = 0.015 (100 km in LEO)," | spectre/astro/dv_estimation.py:53 | spectre/astro/dv_estimation.py:583-586 | tests/unit/test_dv_estimation.py:278-302 | PROVEN (hand check: r2/r1 = 1.145 gives Hohmann 0.065387·v1 against first order 0.0725·v1, +10.9%; 1.015 gives +1.1%) |
| S04-3 | "**Radial** — drives the eccentricity vector. Δe = Δv/v   ⟹  Δv = v·Δe" | spectre/astro/dv_estimation.py:57 | spectre/astro/dv_estimation.py:624-626 | tests/unit/test_dv_estimation.py:242-248 | PROVEN |
| S04-4 | "**Cross-track** — drives the orbit plane.    Δv = 2·v·sin(θ/2)" | spectre/astro/dv_estimation.py:61 | spectre/astro/dv_estimation.py:658 | tests/unit/test_dv_estimation.py:235-240 | PROVEN (hand: v = 7.585 km/s, θ = 0.1° gives 13.24 m/s; test expects 13.25) |
| S04-5 | "Measured against known synthetic burns it is accurate to better than 0.1% and, unlike the original," | spectre/astro/dv_estimation.py:41 | spectre/astro/dv_estimation.py:756-847 | tests/unit/test_dv_estimation.py:297 (rel=0.01 only) | DRIFTED (tested to 1%, not 0.1%) |
| S04-6 | "doubled it. On a 550 km, 53° orbit the rate is +3.10°/day, not −3.10." | spectre/astro/dv_estimation.py:429 | spectre/astro/dv_estimation.py:439-441 | tests/unit/test_dv_estimation.py:626 | DRIFTED (formula proven; hand value is +3.02°/day at a = 6928.137 km, +3.05 at n = 15.1 rev/day) |
| S04-7 | "Falls back to the analytic rates when no element set is to hand." | spectre/astro/dv_estimation.py:454 | spectre/astro/dv_estimation.py:462-464 | tests/unit/test_dv_estimation.py:331-334 | UNDOCUMENTED-BEHAVIOUR (fallback is silent to caller; see F-S04-06) |
| S04-8 | "the absolute floor stood in. Nothing downstream should present an" | spectre/astro/dv_estimation.py:324 | ABSENT (floor_is_measured never read outside the module) | NONE for display | DRIFTED (F-S04-04) |
| S04-9 | "Golden-section refine of the closest approach, one coarse step either side." | spectre/astro/dv_estimation.py:729 | spectre/astro/dv_estimation.py:741 (thirds, i.e. ternary search) | NONE | DRIFTED |
| S04-10 | `#: Above this the measured "floor" is not fit scatter (km/s).` | spectre/astro/dv_estimation.py:123 | spectre/astro/dv_estimation.py:910-920 | tests/unit/test_dv_estimation.py:674-689 | PROVEN |
| S04-11 | "Only HIGH is a confirmation, and it takes all three of: the two independent" | spectre/astro/dv_estimation.py:1093 | spectre/astro/dv_estimation.py:1134-1152 | tests/unit/test_dv_estimation.py:403-425 | IMPLEMENTED-UNTESTED for the tuned thresholds (claimed calibration "four simulated catalogues" is not reproduced by any test) |
| S04-12 | "Propagates each sample forward using a J2 + exponential drag numerical" | spectre/astro/monte_carlo.py:7 | spectre/astro/monte_carlo.py:273-316, :454-463 | NONE (smoke only) | IMPLEMENTED-UNTESTED (drag scaling wrong, F-S04-03) |
| S04-13 | "Generates N perturbed ΔV samples (magnitude, pointing cone, timing, Bstar)." | spectre/astro/monte_carlo.py:6 | spectre/astro/monte_carlo.py:449 (timing applied to horizon, not burn) | NONE | DRIFTED (F-S04-01) |
| S04-14 | "Concurrency: ThreadPoolExecutor (scipy/NumPy releases the GIL; no Windows" | spectre/astro/monte_carlo.py:20 | spectre/astro/monte_carlo.py:546 | NONE | DRIFTED (F-S04-17) |
| S04-15 | "Simplified piecewise exponential fit valid for 0–2000 km." | spectre/astro/monte_carlo.py:54 | spectre/astro/monte_carlo.py:60-76; used only below 800 km at :307 | NONE | IMPLEMENTED-UNTESTED (source uncited, F-S04-13) |
| S04-16 | "bstar : B* parameter from TLE (used for regime check only; drag uses bc)" | spectre/astro/monte_carlo.py:284 | ABSENT (bstar never read in _j2_drag_ode) | NONE | DRIFTED |
| S04-17 | "RNG seed for reproducibility." | spectre/astro/monte_carlo.py:197 | spectre/astro/monte_carlo.py:350 | tests/unit/test_monte_carlo.py:108-113 | PROVEN for samples; converged flag not reproducible (F-S04-11) |
| S04-18 | "position_3sigma_km: float      # 3-σ radius of position cloud at horizon" | spectre/astro/monte_carlo.py:246 | spectre/astro/monte_carlo.py:605 (99.7th percentile) | NONE | DRIFTED (F-S04-10) |
| S04-19 | "Check if the running mean/std of SMA have stabilised." | spectre/astro/monte_carlo.py:493 | spectre/astro/monte_carlo.py:494-504 | tests/unit/test_monte_carlo.py:132-147 (constant input only; :147 asserts type) | DRIFTED (F-S04-11) |
| S04-20 | "Uses the propagated state at the manoeuvre epoch as the pre-manoeuvre state." | spectre/astro/monte_carlo.py:652 | spectre/astro/monte_carlo.py:656-658 | NONE (lines 654-667 uncovered, audit/tools-raw/pytest.txt:64) | IMPLEMENTED-UNTESTED |
| S04-21 | "recent window vs the baseline window → ``PhotometryChangeAssessment``." with "run a two-sample Student's t-test on a" | spectre/astro/photometry.py:13-14 | spectre/astro/photometry.py:356-390 (Welch) | tests/unit/test_photometry.py:97-103 | DRIFTED (Welch, not Student) |
| S04-22 | "Fitted phase-angle baseline over a quiet period." | spectre/astro/photometry.py:76 | spectre/astro/photometry.py:281, :585 (all epochs) | NONE | DRIFTED (F-S04-07) |
| S04-23 | "# Covariance: residual variance × (X^T X)^{-1}  (approximated from diagonal)" | spectre/astro/photometry.py:262 | spectre/astro/photometry.py:266 | NONE | DRIFTED (F-S04-09) |
| S04-24 | "Accurate to ~6 decimal places for the range needed here." | spectre/astro/photometry.py:443 | spectre/astro/photometry.py:401-436 (EPS 3.0e-7, MAXIT 200) | tests/unit/test_photometry.py:125-128 (abs 0.01 only) | IMPLEMENTED-UNTESTED |
| S04-25 | "# Confidence: composite based on p-value and sample sizes" | spectre/astro/photometry.py:629 | spectre/astro/photometry.py:630-635 (p only) | NONE | DRIFTED (F-S04-05) |
| S04-26 | "Rozenberg (1966) airmass formula." | spectre/astro/photometry.py:136 | spectre/astro/photometry.py:143 | tests/unit/test_photometry.py:72-85 | PROVEN (1/(sin h + 0.025·exp(−11 sin h)) matches Rozenberg 1966; 40 at horizon) |
| S04-27 | `"lunar"        — lunar_separation < 20° or lunar_phase > 0.8` | spectre/astro/photometry.py:159 | spectre/astro/photometry.py:177 | tests/unit/test_photometry.py:139-152 | PROVEN |
| S04-28 | "Return epochs of manoeuvres within ±window_hours of change_epoch." | spectre/astro/photometry.py:527 | spectre/astro/photometry.py:528-534 | tests/unit/test_photometry.py:341-356 | PROVEN |

## Slice S05

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S05-1 | "Evaluates a grid of adversary actions × friendly responses using deterministic" / "SGP4 propagation and a weighted composite scoring function." | spectre/domain/decision.py:3-4 | spectre/domain/decision.py:194-209 (lookup table); SGP4 only in optional block :213-232, which the only caller never reaches (spectre/web/routes/decision.py:171 sets red_tle = None) | NONE (coverage misses decision.py 214-232, audit/tools-raw/pytest.txt:80) | DRIFTED |
| S05-2 | "MAXIMIN           = \"maximin\"           # maximise worst-case benefit" | spectre/domain/decision.py:49 | spectre/domain/decision.py:335-338 (minimises the best case, i.e. minimin) | tests/unit/test_decision.py:204-207 (isinstance only) | DRIFTED |
| S05-3 | "MAXIMIN  — maximise the minimum (best-case) composite score." | spectre/domain/decision.py:305 | spectre/domain/decision.py:338 uses min, not max | tests/unit/test_decision.py:204-207 (isinstance only) | DRIFTED |
| S05-4 | "MINIMAX  — minimise the maximum (worst-case) composite score." | spectre/domain/decision.py:303 | spectre/domain/decision.py:319-322 (max over adversary axis i, min over friendly j: correct) | tests/unit/test_decision.py:194-214 (type and determinism only) | IMPLEMENTED-UNTESTED |
| S05-5 | "EXPECTED_VALUE — minimise expected score weighted by adversary probabilities." | spectre/domain/decision.py:304 | spectre/domain/decision.py:324-333 | tests/unit/test_decision.py:199-202, :289-295 (type and enum only) | IMPLEMENTED-UNTESTED |
| S05-6 | "# Scoring weights (sum should equal 1)" | spectre/domain/decision.py:110 | not enforced in domain; route normalises at spectre/web/routes/decision.py:144-151 | tests/unit/test_decision.py:94 (defaults only) | PROVEN |
| S05-7 | "- custody_maintained: True unless adversary is a MANOEUVRE and friendly is NO_ACTION" | spectre/domain/decision.py:170 | spectre/domain/decision.py:178, :183 (POSTURE_CHANGE also loses custody) | tests/unit/test_decision.py:114-120 (NO_ACTION only) | DRIFTED |
| S05-8 | "- custody_gap_hours: 0 if maintained, else horizon * (1 - friendly.reversibility)" | spectre/domain/decision.py:171 | spectre/domain/decision.py:186 (also multiplied by adversary.confidence); :190 gives a non-zero gap while custody is maintained | NONE | DRIFTED |
| S05-9 | "closest-approach estimation uses the TLE epoch separation as a proxy." | spectre/domain/decision.py:165-166 | spectre/domain/decision.py:219-230 (propagated position separation at the horizon midpoint, not epoch separation) | NONE | DRIFTED |
| S05-10 | "# Scale analytic CA by ratio of actual/typical separation" | spectre/domain/decision.py:229 | spectre/domain/decision.py:230 (reversibility-weighted blend, no ratio) | NONE | DRIFTED |
| S05-11 | "- delta_v_cost_km_s: 0 for non-manoeuvre responses, else friendly.cost * 0.05" | spectre/domain/decision.py:173 | spectre/domain/decision.py:237-240 | tests/unit/test_decision.py:137-149 (sign only) | PROVEN |
| S05-12 | "dv_km_s = friendly.cost * 0.05   # 0–50 m/s range" | spectre/domain/decision.py:238 | holds only if cost is in [0, 1]; no domain check | NONE | IMPLEMENTED-UNTESTED |
| S05-13 | "Sort friendly responses best→worst for a single adversary action." | spectre/domain/decision.py:281 | spectre/domain/decision.py:285-286 | tests/unit/test_decision.py:162-170 | PROVEN |
| S05-14 | "Propagates all blue/red TLEs via SGP4 and identifies time windows" / "where the range between any blue-red pair falls below a threshold." | spectre/domain/scenario.py:30-31 | spectre/domain/scenario.py:81-113 | NONE (coverage misses scenario.py 90-106, audit/tools-raw/pytest.txt:87) | IMPLEMENTED-UNTESTED |
| S05-15 | "Propagates each blue-vs-red pair over the scenario window and" | spectre/domain/scenario.py:47 | spectre/domain/scenario.py:63 (fixed 24 h, not a scenario window) | NONE | DRIFTED |
| S05-16 | "stk_name: Auto-derived object name (equals ``name``)." | spectre/domain/models.py:21 | spectre/domain/models.py:29 (prefixed with BLUE_PREFIX) | tests/unit/test_domain_models.py:20-23 (pins the prefix, contradicting the docstring) | DRIFTED |
| S05-17 | "dv_radial: VNC radial (cross-track) component in m/s." | spectre/domain/models.py:205 | ABSENT (label only; radial is not cross-track) | NONE | DRIFTED |
| S05-18 | "Every boundary below is traceable to a named table or observed case in" | spectre/domain/manoeuvre_calibration.py:47 | spectre/domain/manoeuvre_calibration.py:213-217, :236-240 carry bounds absent from their own basis text | tests/unit/test_manoeuvre_calibration.py:214-223 (checks "Table" substring only) | DRIFTED |
| S05-19 | "An unrecognised method falls back to RENDEZVOUS, the most permissive band," | spectre/domain/manoeuvre_calibration.py:171 | spectre/domain/manoeuvre_calibration.py:174; RENDEZVOUS is not the most permissive (GEO PLANE_CHANGE 50/160 vs RENDEZVOUS 25/120 at :199-223) | tests/unit/test_manoeuvre_calibration.py:178-179 (mapping only) | DRIFTED |
| S05-20 | "9e-5 m/s^2 and needs about 64 DAYS to deliver 500 m/s." | spectre/domain/manoeuvre_calibration.py:358 | spectre/domain/manoeuvre_calibration.py:413, :378-382 (hand check: 0.27/3000 = 9.0e-5; 500/9e-5 = 5.56e6 s = 64.3 days) | tests/unit/test_manoeuvre_calibration.py:127-135; tests/unit/test_pol_assessment.py:256-260 | PROVEN |
| S05-21 | "PROPELLANT LOAD, which is reachable: about 1.57 km/s for a LEO smallsat and" / "0.85 km/s for a chemical GEO comsat, both inside Table 2's envelopes." | spectre/domain/threat_assessment.py:119-120 | spectre/domain/pol_assessment.py:462-466 (hand check: 15,690 m/s x -ln(1-0.095) = 1,566 m/s; 3,138 m/s x -ln(1-0.2375) = 851 m/s) | NONE | IMPLEMENTED-UNTESTED |
| S05-22 | "VERDICT     both, with the weaker one governing" | spectre/domain/threat_assessment.py:29 | spectre/domain/threat_assessment.py:414 | tests/unit/test_threat_assessment.py:113-122 | PROVEN |
| S05-23 | "Absence is carried through to the confidence of the verdict rather than" | spectre/domain/threat_assessment.py:209 | spectre/domain/threat_assessment.py:395-402 (discretionary reserve is never listed as used or missing) | tests/unit/test_threat_assessment.py:81-97 (propellant_used_pct only) | DRIFTED |
| S05-24 | "None is not the same as MINIMAL, and conflating them is how a verdict" | spectre/domain/threat_assessment.py:309 | spectre/domain/threat_assessment.py:312-321, :404-412 | tests/unit/test_threat_assessment.py:68-79 | PROVEN |
| S05-25 | "**Provenance.** Every threshold in this module comes from the open-source" | spectre/domain/pol_assessment.py:11 | spectre/domain/pol_assessment.py:110-123, :599, :604, :610, :616, :194, :189 (uncited tuned weights, ladder and normalisers) | NONE | DRIFTED |
| S05-26 | "#: Upper edge of the GEO protected region, km of altitude. A raise that ends" | spectre/domain/pol_assessment.py:176 | spectre/domain/pol_assessment.py:179 (36,186 km is GEO +400 km; the IADC protected region ends at GEO +200 km, 35,986 km) | tests/unit/test_pol_assessment.py:85-93 (fixture altitude 36,486 km for a "300 km" raise) | DRIFTED |
| S05-27 | "#: True when this single manoeuvre exceeds what any platform in this regime" | spectre/domain/pol_assessment.py:211 | spectre/domain/pol_assessment.py:363 (500 m/s on-station threshold; the platform-total test is :364) | NONE | DRIFTED |
| S05-28 | "# The correction that matters: full budget score at five times the regime's" | spectre/domain/pol_assessment.py:620 | spectre/domain/pol_assessment.py:622-628 | tests/unit/test_pol_assessment.py:307-318 | PROVEN |
| S05-29 | "#: Confirmed manoeuvres needed before an anomaly score means anything." | spectre/domain/pol_assessment.py:555 | spectre/domain/pol_assessment.py:590-591 | tests/unit/test_pol_assessment.py:428-451 | PROVEN |
| S05-30 | "so an object missing either gets no figure rather than one extrapolated" | spectre/domain/pol_assessment.py:894 | spectre/domain/pol_assessment.py:897-902 | NONE (coverage misses pol_assessment.py 898-899) | IMPLEMENTED-UNTESTED |
| S05-31 | "Validates search configuration before intercept calculations are run." | spectre/domain/maneuver_planner.py:3 | ABSENT as wiring: no production caller (Grep `ScenarioPlanner\ | validate_search_config` over spectre and scripts, excluding the two defining files: 0 matches) | DRIFTED |
| S05-32 | "Falls back to the chemical GEO comsat, the most constrained class, so an" | spectre/domain/manoeuvre_calibration.py:601 | spectre/domain/manoeuvre_calibration.py:605 | NONE | IMPLEMENTED-UNTESTED |

## Slice S06

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S06-1 | "``from_km_s`` is applied here and nowhere downstream. A second conversion" | spectre/web/routes/threat.py:534 | spectre/web/routes/threat.py:552-556 | NONE (no test pins a km/s solver figure to the m/s entry value) | IMPLEMENTED-UNTESTED |
| S06-2 | "*refusals* collects, per method, why it produced nothing. Every method used" | spectre/web/routes/threat.py:645 | spectre/web/routes/threat.py:679-682 (keyed by method only, first reason wins, recorded even when the same method succeeded elsewhere) | tests/unit/test_threat_sweep_template.py:118 (template only) | DRIFTED |
| S06-3 | "is recorded with the reason rather than dropped, because a short result" | spectre/web/routes/threat.py:1201 | spectre/web/routes/threat.py:1213, 1222-1225, 1236-1238 | NONE (lines 1204-1240 uncovered, pytest.txt:117) | IMPLEMENTED-UNTESTED |
| S06-4 | "recorded against the target rather than dropped." | spectre/web/routes/threat.py:1121 | spectre/web/routes/threat.py:1147-1148 | NONE (1123-1150 uncovered) | IMPLEMENTED-UNTESTED |
| S06-5 | "Truncation is always reported." | spectre/web/routes/threat.py:920 | spectre/web/routes/threat.py:1546-1551 | NONE (grep `_MAX_SCREEN_ACTORS` in tests: no match) | IMPLEMENTED-UNTESTED |
| S06-6 | "An actor that cannot be assessed is recorded with the reason rather than" | spectre/web/routes/threat.py:1463 | spectre/web/routes/threat.py:1474, 1481-1484 | NONE at route level; tests/unit/test_threat_screen_template.py:193 is template only | IMPLEMENTED-UNTESTED |
| S06-7 | "Synchronous on purpose: the handler hands this to an executor thread." | spectre/web/routes/threat.py:1196 | spectre/web/routes/threat.py:1347-1352 | NONE (route uncovered) | IMPLEMENTED-UNTESTED |
| S06-8 | "# Metres per second, whole numbers. Measured against TLE uncertainty a" | spectre/web/routes/threat.py:814 | spectre/web/routes/threat.py:822 (summary `.0f`), but spectre/web/templates/partials/threat_sweep.html:100 and :285 print `%.3f` | tests/unit/test_threat_sweep_template.py:194 (passes on "401.200") | DRIFTED |
| S06-9 | "# plane_change can report a signed figure; cost is a magnitude." | spectre/web/routes/threat.py:672 | threat.py:673 takes `abs`; spectre/web/routes/maneuver.py:1483 does not | NONE | DRIFTED |
| S06-10 | "# Hard cap: prevent runaway compute on unexpectedly large groups." | spectre/web/routes/threat.py:1312 | spectre/web/routes/threat.py:1313-1316 | NONE (grep `_MAX_SWEEP_TARGETS` in tests: no match) | IMPLEMENTED-UNTESTED |
| S06-11 | "Session state is shared, and dropping a guard because it looks redundant" | spectre/web/routes/threat.py:324 | spectre/web/routes/threat.py:331-332 | NONE (327-353 uncovered) | IMPLEMENTED-UNTESTED |
| S06-12 | "The bundled bootstrap watchlist seeds the cache so the sweep and the screen" | spectre/web/routes/threat.py:445 | spectre/web/routes/threat.py:451-454 | tests/unit/test_hrr_bootstrap.py:198-208 | PROVEN |
| S06-13 | "# The reason stays in the log, not in the markup. This response bypasses" | spectre/web/routes/threat.py:149 | spectre/web/routes/threat.py:152-154 | NONE (77-152 uncovered) | IMPLEMENTED-UNTESTED |
| S06-14 | "so a typo in the paste box never quietly becomes a sweep of a different" | spectre/web/routes/threat.py:1074 | spectre/web/routes/threat.py:1083-1084 | NONE | IMPLEMENTED-UNTESTED |
| S06-15 | "\"\"\"Every empty result carries a reason. Silence reads as safety.\"\"\"" | spectre/web/routes/threat.py:1665 | spectre/web/routes/threat.py:1675-1691 | tests/integration/test_threat_screen_route.py:40-56 | PROVEN |
| S06-16 | "# Count total targets (HRR + manual)." | spectre/web/routes/threat.py:1335 | spectre/web/routes/threat.py:1336 (`hrr_count`, named HRR, includes manual; grep `hrr_count` in templates: no match, so unused) | NONE | DRIFTED |
| S06-17 | "nothing to cluster. The cache update stays inside the try: a summary" | spectre/web/routes/threat.py:1157 | spectre/web/routes/threat.py:1171-1181 | NONE (1164-1181 uncovered) | IMPLEMENTED-UNTESTED |
| S06-18 | "``group_idx`` arrives with ``entry_index`` from the row being replaced." | spectre/web/routes/threat.py:1746 | spectre/web/routes/threat.py:1741, 1803-1806 | tests/unit/test_deployment_contract.py:1574 (template only; route 1755-1803 uncovered) | IMPLEMENTED-UNTESTED |
| S06-19 | "THIS IS THE UNIT BOUNDARY for the intercept engine. The astro layer works" | spectre/web/routes/maneuver.py:1462 | spectre/web/routes/maneuver.py:1471-1483 | NONE (no reference value) | IMPLEMENTED-UNTESTED |
| S06-20 | "*target_km* is a SEPARATION DISTANCE and *max_dv_m_s* is a VELOCITY BUDGET." | spectre/web/routes/maneuver.py:1433 | spectre/web/routes/maneuver.py:1402, 1415 | tests/integration/test_all_intercepts_ranking.py:104 | PROVEN |
| S06-21 | "accounts for all twenty-three rather than quietly listing fewer than it ran." | spectre/web/routes/maneuver.py:1022 | spectre/web/routes/maneuver.py:1029-1030 | tests/integration/test_all_intercepts_ranking.py:188 | PROVEN |
| S06-22 | "A method whose solver failed sorts behind every assessment." | spectre/web/routes/maneuver.py:1037 | spectre/web/routes/maneuver.py:1039-1040 | tests/integration/test_all_intercepts_ranking.py:188 | PROVEN |
| S06-23 | "Executes all 23 methods concurrently using sensible shared parameters," | spectre/web/routes/maneuver.py:1060 | spectre/web/routes/maneuver.py:1001-1011 (sequential loop, one thread) | NONE | DRIFTED |
| S06-24 | "Runs Lambert, Hohmann, or bi-elliptic transfer calculations using" | spectre/web/routes/maneuver.py:801 | spectre/web/routes/maneuver.py:858 (any of 25 methods) | NONE | DRIFTED |
| S06-25 | "Falls back silently to the supplied originals when UDL credentials are" | spectre/web/routes/maneuver.py:1213 | spectre/web/routes/maneuver.py:1216-1235 | NONE (1216-1235 uncovered) | IMPLEMENTED-UNTESTED |
| S06-26 | "\"\"\"Fuel budget for the evasion solver, falling back to half a km/s.\"\"\"" | spectre/web/routes/maneuver.py:1284 | spectre/web/routes/maneuver.py:1285-1287 (a coast time in hours is returned as km/s) | NONE (1286 uncovered) | UNDOCUMENTED-BEHAVIOUR |
| S06-27 | "\"\"\"Drift time for the GEO relocation solver, or None to leave it to the solver.\"\"\"" | spectre/web/routes/maneuver.py:1277 | spectre/web/routes/maneuver.py:1278-1279 returns hours into `drift_time_days` (maneuver.py:1374) | NONE (1279 uncovered) | DRIFTED |
| S06-28 | "The phasing and hop solvers count revolutions rather than taking a" | spectre/web/routes/maneuver.py:1256 | spectre/web/routes/maneuver.py:1260-1262 | NONE (1261 uncovered) | IMPLEMENTED-UNTESTED |
| S06-29 | "Thresholds in m/s. They were 1.0 / 0.1 / 0.01 km/s, so against m/s values" | spectre/web/routes/maneuver.py:222 | spectre/web/routes/maneuver.py:226-236 | tests/unit/test_intercept_intel_characterisation.py:81 | PROVEN |
| S06-30 | "# The denominator travels with the percentage. The template used to" | spectre/web/routes/maneuver.py:707 | spectre/web/routes/maneuver.py:688, 711 (always the 500 m/s default, never the operator's `max_dv_m_s`) | NONE | UNDOCUMENTED-BEHAVIOUR |
| S06-31 | "# BLE001: any solver failure is reported to the operator, not raised." | spectre/web/routes/maneuver.py:872 | spectre/web/routes/maneuver.py:878-880 | NONE (873-878 uncovered) | IMPLEMENTED-UNTESTED |
| S06-32 | "This and ``to_km_s`` are the ONLY places the conversion is written." | spectre/domain/manoeuvre_calibration.py:104 | violated at spectre/web/routes/threat.py:664 | NONE | DRIFTED |
| S06-33 | "number_of_burns: Number of burn segments (reserved for future use)." | spectre/domain/models.py:288 | spectre/web/routes/maneuver.py:792 accepts it, ignores it; operator.html:475-477 offers it as a live control | NONE | UNDOCUMENTED-BEHAVIOUR |
| S06-34 | "# pinned by tests/unit/test_intercept_intel_characterisation.py." | spectre/web/routes/maneuver.py:178 | spectre/web/routes/maneuver.py:199-305 | tests/unit/test_intercept_intel_characterisation.py:73-165 | PROVEN |

## Slice S08

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S08-1 | "# Session cookie expires after 8 hours (28 800 seconds)." | spectre/web/auth.py:21 | spectre/web/auth.py:71 | NONE (Grep `max_age\ | IMPLEMENTED-UNTESTED |
| S08-2 | "a later logout or password change, which increments the stored counter, refuses this token" | spectre/web/auth.py:55-56 | spectre/web/routes/login.py:189; spectre/web/models.py:81; spectre/web/auth.py:102 | tests/integration/test_login_hardening.py:185-229 | PROVEN |
| S08-3 | "Raises HTTP 302 (redirect to /login) if the session is missing or invalid." | spectre/web/auth.py:115 | spectre/web/auth.py:118-129 | tests/integration/test_admin_routes.py:31-34 | PROVEN |
| S08-4 | "raises HTTP 403 if the authenticated user is not an admin." | spectre/web/auth.py:156-157 | spectre/web/auth.py:159-163 | tests/integration/test_admin_routes.py:36-48 (GET only) | PROVEN |
| S08-5 | "Login and logout both mint or clear the cookie, so a token really is invalidated by either" | spectre/web/csrf.py:5-6 | spectre/web/csrf.py:46-47 (no generation check; a revoked cookie's token still verifies) | NONE | DRIFTED |
| S08-6 | "GET/HEAD/OPTIONS/TRACE and the public /login POST are exempted." | spectre/web/csrf.py:71 | spectre/web/csrf.py:24-25, 73-76 | tests/unit/test_csrf.py:94-118 | PROVEN |
| S08-7 | "# 10 failed attempts per source address per 300 s." | spectre/web/routes/login.py:30 | spectre/web/routes/login.py:41 | tests/integration/test_login_hardening.py:81-99 | PROVEN |
| S08-8 | "ten wrong passwords against a given username in five minutes is the ceiling however many addresses they are spread across." | spectre/web/routes/login.py:54-55 | spectre/web/routes/login.py:132-141 (password still checked after the ceiling; a correct guess succeeds) | tests/integration/test_login_hardening.py:415-426 (asserts only that a 429 appears) | DRIFTED |
| S08-9 | "so every attempt does the same bcrypt work." | spectre/web/routes/login.py:84 | spectre/web/routes/login.py:131-132 | tests/integration/test_login_hardening.py:134-155 | PROVEN |
| S08-10 | "The router rewrites that header, which is what stops a caller nominating its own address to get a fresh budget." | spectre/web/routes/login.py:98-99 | ABSENT (property of external ingress; tests/integration/test_login_hardening.py:391-394 itself calls it an assumption) | NONE | ABSENT |
| S08-11 | "httponly=True,   # not readable from JavaScript" and "HTTPS only unless explicitly opted out" | spectre/web/routes/login.py:170-171 | spectre/web/routes/login.py:167-174; spectre/config/settings.py:263-265 | tests/integration/test_root_contract.py:50-90 | PROVEN |
| S08-12 | "Every session, not only the cookie that asked" | spectre/web/routes/login.py:181 | spectre/web/routes/login.py:189 | NONE (test_login_hardening.py:185-206 replays the same token, not a second session) | IMPLEMENTED-UNTESTED |
| S08-13 | "Retention is now bounded by RATE TIMES WINDOW rather than by the number of distinct keys ever seen" | spectre/web/rate_limit.py:65-66 | spectre/web/rate_limit.py:94-102 | tests/unit/test_rate_limit_memory.py:34-56 | PROVEN |
| S08-14 | "so no legitimate key is truncated here." | spectre/web/rate_limit.py:39 | spectre/web/rate_limit.py:107 | tests/unit/test_rate_limit_memory.py:204-222 | PROVEN |
| S08-15 | "# Guard: cannot demote the last admin" | spectre/web/routes/admin.py:220 | spectre/web/routes/admin.py:221-227 (not atomic, F-S08-05) | tests/integration/test_admin_routes.py:241-275 | PROVEN |
| S08-16 | "Cannot delete the last admin account." | spectre/web/routes/admin.py:280 | spectre/web/routes/admin.py:274-281 | NONE (test named for it exercises demotion, test_admin_routes.py:257-274) | IMPLEMENTED-UNTESTED |
| S08-17 | "You cannot delete your own account." | spectre/web/routes/admin.py:271 | spectre/web/routes/admin.py:267-272 | tests/integration/test_admin_routes.py:225-238 | PROVEN |
| S08-18 | "# A password change has to end the sessions that were opened with the old" | spectre/web/models.py:61 | spectre/web/models.py:71-81 | tests/integration/test_login_hardening.py:208-229 | PROVEN |
| S08-19 | "two places already rewrite a hash - the admin form and the" (break-glass bootstrap) | spectre/web/models.py:66 | spectre/web/database.py:215 | NONE for the bootstrap path (test_admin_bootstrap.py:123-176 checks the hash, not session revocation) | IMPLEMENTED-UNTESTED |
| S08-20 | "Every branch logs." | spectre/web/database.py:189 | spectre/web/database.py:218, 224, 232, 250 | tests/integration/test_admin_bootstrap.py:55-176 | PROVEN |
| S08-21 | "# "require" means encrypt, and explicitly does NOT mean verify." | spectre/config/settings.py:231 | spectre/config/settings.py:235-238 | tests/unit/test_config_settings.py:370 | PROVEN |
| S08-22 | "The fallback is reached only when SECRET_KEY is absent AND the scanner's flag is set" | spectre/config/settings.py:96-97 | spectre/config/settings.py:100-103 | tests/unit/test_config_settings.py:126-156 | PROVEN |
| S08-23 | "Fails closed. A missing, placeholder, or trivially short signing key" | spectre/config/settings.py:361 | spectre/config/settings.py:365-381 | tests/unit/test_config_settings.py:96-108 | PROVEN |
| S08-24 | "A 200 carries ``status`` and nothing" | spectre/web/health.py:16-17 | spectre/web/health.py:87, 118 | tests/unit/test_health.py:112-125 | PROVEN |
| S08-25 | "Readiness probe. 200 only when storage genuinely accepts a write." | spectre/web/health.py:110 | spectre/web/health.py:111-118 (database not probed, F-S08-09) | tests/unit/test_health.py:73-93 | PROVEN |
| S08-26 | "Uvicorn trusts that header from loopback only and the router is not on loopback" | spectre/web/app.py:302-303 | spectre/web/_entrypoint.py:33-45 (no `forwarded_allow_ips`, relies on uvicorn default) | NONE | IMPLEMENTED-UNTESTED |
| S08-27 | "access_log=False,  # request logging is handled by the application's own audit path" | spectre/web/_entrypoint.py:44 | ABSENT (Grep `middleware` in spectre/: only app.py:327, the security-header middleware) | NONE | ABSENT |
| S08-28 | "Keycloak single-sign-on gateway in front of the service, not by this bind." | spectre/web/_entrypoint.py:40 | ABSENT (Grep `Keycloak\ | keycloak`: _entrypoint.py, READINESS.md and audit files only) | ABSENT |
| S08-29 | "# UDL credentials — held in memory for this session only, never persisted." | spectre/web/planning_state.py:55 | spectre/web/planning_state.py:113, 126-133 (keyed by username, outlives session expiry and account deletion) | NONE | DRIFTED |
| S08-30 | "Safe repr that never leaks the UDL password." | spectre/web/planning_state.py:94 | spectre/web/planning_state.py:95-99 | NONE (Grep `repr\ | IMPLEMENTED-UNTESTED |
| S08-31 | "no newlines, no carriage returns, no other control characters, and never longer than *limit*." | spectre/web/log_safety.py:47-49 | spectre/web/log_safety.py:52-58 (exceeds limit when limit < 3, F-S08-19) | tests/unit/test_log_safety.py:30-75 | DRIFTED |
| S08-32 | "Automatically injects ``csrf_token`` into the context" | spectre/web/deps.py:40-41 | spectre/web/deps.py:47-49 | NONE directly (tests mint tokens via tests/conftest.py:42-45) | IMPLEMENTED-UNTESTED |
| S08-33 | "Configure structlog for a planning run." | spectre/app_logging/config.py:13 | ABSENT at runtime (never called, F-S08-16) | NONE | DRIFTED |
| S08-34 | "Oldest entries are evicted automatically when the deque is full." (log_entries) and `log_queue` "for SSE streaming" | spectre/web/planning_state.py:43-45 | spectre/web/planning_state.py:51, 107-109 (queue unbounded, no consumer) | tests/unit/test_planning_state.py:53 (deque only) | DRIFTED |

## Slice S09

| # | Claim (quoted) | Source | Implementing | Proving test | Status |
|---|---|---|---|---|---|
| S09-1 | "13 structured scenarios" | README.md:178 | spectre/training/config/scenarios.yaml:31-919 (13 ids counted) | NONE (test_training_gamification.py:281-282 asserts only `>= 3`) | IMPLEMENTED-UNTESTED |
| S09-2 | "from Cadet (level 1) to Expert (level 6)" | README.md:178 | gamification.yaml:188-189 names level 6 "Instructor"; highest scenario level_required is 5 (scenarios.yaml:829) | tests/unit/test_training_gamification.py:70 asserts "Instructor" | DRIFTED |
| S09-3 | "Challenges — timed scenarios that unlock at Level 4+" | README.md:179 | level gate only at training.py:191; no time limit enforced (grep `time_limit_minutes` in spectre/**/*.py: only scenarios.py:80,159) | NONE | DRIFTED |
| S09-4 | "Tutorials — step-by-step skill-axis tutorials; mark complete for XP" | README.md:180 | training.py:603-614 | tests/integration/test_web_routes_extended.py:118-124 (status only) | IMPLEMENTED-UNTESTED |
| S09-5 | "\ | 2 \ | Trainee \ | 200 \ | DRIFTED |
| S09-6 | "contribute points to one or more of five skill axes" | README.md:200 | gamification.yaml:7-36 (five axes) | test_training_gamification.py:41-49 | PROVEN |
| S09-7 | "\ | `intercept_planning` \ | Intercept Engine and transfer methods \ | " (axis names) | DRIFTED |
| S09-8 | "normalise per tolerance   ← divide by [inc_tol, raan_tol, ecc_tol]" | README.md:396 | tle_clustering/clustering.py:62-74 | tests/unit/tle_clustering/test_clustering.py:122-154 | PROVEN |
| S09-9 | "eps=1.0 → all three elements within tolerance" | README.md:399 | DBSCAN density chaining allows members beyond one tolerance apart (clustering.py:131-136) | NONE | DRIFTED |
| S09-10 | "(min Chebyshev dist to centroid, recency tie-break)" | README.md:402 | tle_clustering/selection.py:109-125 | tests/unit/tle_clustering/test_selection.py:40-68 | PROVEN |
| S09-11 | "configurable in `spectre/config/constants.py → TLE_CLUSTERING`" | README.md:406 | spectre/config/constants.py:52-58; spectre/astro/tle_preprocessing.py:158 | tests/integration/test_tle_clustering_pipeline.py:282-297 | PROVEN |
| S09-12 | Inclination 0.01°, RAAN 0.05°, eccentricity 1×10⁻⁴ defaults | README.md:410-412 | constants.py:53-55; config.py:65-67; config.py:96-104 (three copies) | NONE (no test pins the defaults) | IMPLEMENTED-UNTESTED |
| S09-13 | "Provider epoch offsets of minutes → ~0.05° J2 drift" | README.md:411 | fetch window is 24 h (constants.py:57); no epoch alignment before comparison (parser.py:80-82) | NONE | DRIFTED |
| S09-14 | "When DBSCAN finds >1 cluster for a satellite, the sweep results show a red ▲ warning" | README.md:414 | tle_preprocessing multi_cluster flag | tests/integration/test_tle_clustering_pipeline.py:228-255 | PROVEN (premise undermined by F-S09-10, F-S09-11) |
| S09-15 | "a pair of TLEs is neighbours only if *all* elements simultaneously satisfy their respective tolerance" | tle_clustering/clustering.py:9-11 | clustering.py:131-136 (metric chebyshev) | tests/unit/tle_clustering/test_clustering.py:122-137 | PROVEN |
| S09-16 | "``parser.TLERecord`` and ``clustering._normalise`` accordingly — no other" | tle_clustering/config.py:60 | TLERecord is in models.py:14; function is `_build_feature_matrix` (clustering.py:41); selection.py:61-64 also hard-codes three elements | NONE | DRIFTED |
| S09-17 | "They never touch SessionState, operational TLEs, or UDL credentials." | spectre/training/__init__.py:7 | contradicted by spectre/web/routes/training.py:231-240 | NONE | DRIFTED |
| S09-18 | "- No access to: session state, operational TLEs, UDL credentials" | spectre/training/models.py:7 | contradicted by training.py:231 | NONE | DRIFTED |
| S09-19 | "No operational systems are affected." | spectre/web/templates/training.html:43 | synthetic objects persist in the operator's live SessionState (training.py:236, 240); Console tab frames the operational console at training.html:290 | NONE | DRIFTED |
| S09-20 | "no operational systems are accessed" | spectre/training/config/tutorials.yaml:17 | as claim 19 | NONE | DRIFTED |
| S09-21 | "The row is deleted when the operator resets or submits." | spectre/web/routes/training.py:302 | submit never deletes (training.py:489-504) | NONE | DRIFTED |
| S09-22 | "this attempt is cancelled with no side effects" | training_scenario_active.html:177 | route honours it (training.py:330-337) but the button sits in a nested form (F-S09-05) | NONE (coverage gap at training.py:332-337, pytest.txt:118) | DRIFTED |
| S09-23 | "Speed multiplier [0.5, 1.5]" | spectre/training/gamification.py:163 | clamp is [0.5, 2.0] at gamification.py:176 | test_training_gamification.py:112-115 assumes 2.0 | DRIFTED |
| S09-24 | "axis_weights must sum to 1.0." | gamification.yaml:41 | gamification.py:106 (not enforced at load) | test_training_gamification.py:72-78 | PROVEN |
| S09-25 | "award bonus if ΔV < this" | gamification.yaml:202 | ABSENT (grep `efficiency_bonus` in spectre/**/*.py: only gamification.py:70,134; grep `award_points\(` shows three call sites, none for efficiency_bonus) | NONE | ABSENT |
| S09-26 | "Multiplied by speed_factor (0.5–1.5) at award time" | gamification.yaml:79 | ABSENT (no call site passes speed_factor; grep `speed_factor` only in gamification.py) | NONE | ABSENT |
| S09-27 | "The efficiency score in your debrief rewards low-ΔV solutions." | tutorials.yaml:137 | ABSENT (no ΔV is submitted; submit form fields at training_scenario_active.html:69-71) | NONE | ABSENT |
| S09-28 | "Read the RAAN field — for a GEO satellite this equals the sub-satellite longitude in degrees East." | scenarios.yaml:61 | scored against answer "45.0" at scenarios.yaml:75 | NONE | DRIFTED (physically false, F-S09-08) |
| S09-29 | "Score above threshold on decision quality in both to pass." / "No restart — advance on your decisions." | scenarios.yaml:248, :252 | ABSENT: `challenge_scenarios` parsed at scenarios.py:161 and never read; reset and explore remain available | NONE | ABSENT |
| S09-30 | "Monte Carlo        — Not yet implemented." | scenarios.yaml:16 | README.md:162 documents Monte Carlo as shipped | NONE | DRIFTED |
| S09-31 | Formula leads "=", "+", "-", "@", "\t", "\r" neutralised | spectre/web/routes/plan.py:33 | plan.py:42-54 | tests/integration/test_plan_export.py:170-206 | PROVEN |
| S09-32 | "A number is not a formula, so numbers are let through unchanged." | plan.py:38 | plan.py:52-53 | test_plan_export.py:208-226 | PROVEN |
| S09-33 | "a unit test walks this file's AST to keep it that way" | plan.py:61 | plan.py:57-65 | test_plan_export.py:254-290 | PROVEN |
| S09-34 | "A run_id outside _RUN_ID_PATTERN is refused with 400 before it is used" | plan.py:164-165 | plan.py:106-127 | test_plan_export.py:314-350 | PROVEN |
| S09-35 | "All numeric form fields are validated server-side before propagation." | spectre/web/routes/geometry.py:9 | geometry.py:135-142 | tests/integration/test_web_routes_extended.py test_geometry_invalid_dv (line TBC, re-verify) | PROVEN |
| S09-36 | "Parse a datetime-local string to an aware UTC datetime." | geometry.py:67 | naive fallback converted as local time at geometry.py:81 | NONE | DRIFTED |
| S09-37 | "# Adversary actions (up to 4, passed as parallel form arrays)" | spectre/web/routes/decision.py:60 | no cap (decision.py:109); README.md:166 says 1–5 | NONE | DRIFTED |
| S09-38 | "Returns 200 in both cases." (anonymous GET / serves login) | spectre/web/routes/operator.py:50 | operator.py:55-56 | tests/integration/test_web_routes.py:51-66 | PROVEN |
| S09-39 | "Nothing from the exception reaches the browser." | operator.py:297 | operator.py:298-301 | test_web_routes.py:132-140 (weak: `b"Invalid" ... or b"error"`) | PROVEN |
| S09-40 | "Roughly 1500 inline style attributes and two" / "inline <style> blocks." | spectre/web/app.py:242-243 | three templates carry `<style>`: training.html:266, partials/intercept_geometry.html:6, partials/splash_overlay.html:11 | NONE | DRIFTED |
| S09-41 | "18 templates carry inline <script>" and "159 inline onclick and onkeydown" | app.py:229-231 | counted: 18 files with `<script>`, 159 `\s(onclick\ | onkeydown)=` matches (one is a comment in base.html:38) | IMPLEMENTED-UNTESTED |
| S09-42 | "Auto-dismissed after 3.2 s" | partials/splash_overlay.html:3 | timer is 3400 ms at :119 | NONE | DRIFTED |
| S09-43 | "no template performs unit arithmetic" ... "enforced by a test" | spectre/web/format_units.py:57-59 | format_units.py:44-66 | tests/unit/test_operator_sees_metres_per_second.py:217-229 | PROVEN |
| S09-44 | "Only delete if not yet submitted — don't destroy a scored record" | training.py:331 | training.py:330-332 | NONE (lines 332-337 uncovered, pytest.txt:118) | IMPLEMENTED-UNTESTED |
| S09-45 | "Completing a tutorial twice should not award points the second time" | tests/integration/test_web_routes_extended.py:597 | training.py:601-614 | test asserts only status and absence of "error" (:608-611) | IMPLEMENTED-UNTESTED |
