# Orbital calculation audit

Method: validate against published reference answers and physical invariants,
then propagate the result and measure where it actually arrives. Inspection
alone was not treated as evidence, and three times during this audit the test
harness turned out to be wrong rather than the code. Each of those is recorded
below, because a false finding costs as much as a missed one.

Scope: `spectre/astro/`, 8,338 lines across fifteen modules.

## Verdict

Three defects that produced confidently wrong numbers, one of them in the
solver the whole intercept capability rests on. Two modules were found correct
in ways worth stating, because "we checked and it is right" is useful.

| Module | Status | Basis |
|---|---|---|
| `lambert.py` | **was broken, fixed** | Curtis Example 5.2 and round-trip residual |
| `maneuvers.py` | **was broken, fixed** | closed-form plane-change cost |
| `propagator.py` | **latent defect, fixed** | state to elements and back |
| `transfers.py` | correct maths, no input validation | closed-form Hohmann, bi-elliptic crossover |
| `cw_geometry.py` | correct | numerical integration of the CW equations |
| `pattern_of_life.py` (J2) | correct | sun-synchronous rate, critical inclination |
| `monte_carlo.py` (sampling) | correct | Rayleigh cone statistics |
| `tactical.py` | **three defects, fixed** | closed forms and flown trajectories |
| remaining seven modules | **not audited** | see the honest limits below |

## 1. The Lambert solver returned a confident wrong answer

`solve_lambert` feeds `lambert_intercept`, which the threat sweep calls at two
sites and the manoeuvre planner at one. Every Lambert-derived delta-V the
application ever produced was wrong.

Two independent defects, either sufficient alone.

**The time-of-flight residual used the wrong symbol.** Curtis defines
`chi = sqrt(y/C)` where C is the Stumpff function; the code wrote
`sqrt(y/mu)`, substituting the gravitational parameter. Those differ by six
orders of magnitude, so Newton-Raphson was not solving the time-of-flight
equation. It never converged on any case tried, and the routine returned
whatever value it held after a fixed hundred iterations without checking.

**The degeneracy guard was keyed to the wrong quantity.** At exactly 180
degrees the transfer plane is undefined, but the guard tested the chord term A,
and `sin(pi)` in floating point is 1.2e-16 rather than zero, so A stayed at
3.7e-12 and the guard never fired. A phasing transfer between opposite points
on the GEO belt sits exactly there.

Measured, before and after:

| Check | Before | After |
|---|---|---|
| Curtis 5.2 departure velocity | 1,970 m/s error | 0.05 m/s |
| Curtis 5.2 arrival velocity | 2,077 m/s error | 0.05 m/s |
| Round-trip miss distance | 6,268 km | 0.14 m |
| GEO 180-degree phasing | 74,790 km miss | refused as ill-posed |

Fixed by using the correct residual, replacing divergent Newton with bracketed
bisection (which cannot diverge on a monotone function), raising
`LambertConvergenceError` rather than returning an unconverged value, keying
the degeneracy guard to the transfer angle, and handling Stumpff overflow in
the bracket search. The docstring claimed Izzo (2015); it is Curtis Algorithm
5.2 and always was, so the single-revolution limitation is now stated and
enforced rather than answered wrongly.

## 2. Angles were converted to degrees twice

`KeplerianElements` documents inc, raan, argp and ta as degrees, and
`state_to_keplerian` returns degrees. Twelve call sites in `maneuvers.py`
passed them through `math.degrees()` again, multiplying every angle by 57.3.

Measured effect on plane-change cost at GEO:

| True inclination change | Correct cost | Reported | Overstatement |
|---|---|---|---|
| 0.5 deg | 27 m/s | 1,521 m/s | 57x |
| 2.0 deg | 107 m/s | 5,175 m/s | 48x |
| 5.0 deg | 268 m/s | 3,680 m/s | 14x |

The same corruption reached the J2 drift planner, which received an inclination
of 2,956 degrees for a 51.6-degree orbit, and the manoeuvre-direction
classifier, whose `abs(di) > 0.1` test was satisfied by almost any burn, so
nearly every detected manoeuvre was labelled "normal".

All twelve removed. A regression test scans `spectre/astro/` for the pattern
and carries its own red case, including the three exact lines that shipped and
the neighbouring sgp4 conversions that are correct and must not be flagged.

## 3. Degenerate element sets returned zero instead of the defined element

Three orbits have an undefined classical element. The converter returned zero
rather than substituting the element that is defined, so a state converted to
elements and back moved:

| Orbit | Undefined element | Round-trip error |
|---|---|---|
| Circular inclined | true anomaly | 8,000 km |
| Equatorial elliptical | argument of periapsis | 17,074 km |
| **Circular equatorial (GEO)** | both | **78,460 km** |

The worst case is this application's primary regime. Fixed with the standard
substitutions: argument of latitude, longitude of periapsis, and true
longitude. All six round-trip cases now return the same state.

**Honest scope:** nothing currently reads `.ta` or `.argp` off the result, so
this was a latent defect rather than a live wrong answer. It is still a
landmine, because `keplerian_to_state(state_to_keplerian(sv))` is an obvious
idiom and any future phasing work needs true anomaly.


## 4. tactical.py: a collision trajectory certified as passively safe

`nmc_safety_ellipse` plans a Natural Motion Circumnavigation, the standard
passively-safe inspection trajectory: if propulsion fails, the inspector must
drift clear rather than into the target.

It prescribed a radial burn from a co-located state and then reported the
radial amplitude as the safety margin. Flying that initial condition gives

    x(t) = (v/n) sin(nt),   y(t) = -(2v/n)(1 - cos(nt))

which returns to the origin once per orbit. Measured closest approach for a
reported 5.000 km margin: **zero**. The function certified a collision
trajectory as safe.

A bounded ellipse centred on the target needs the chaser already displaced
radially by A and an along-track burn of 2nA, giving x = A cos(nt),
y = -2A sin(nt), which never comes closer than A. Fixed, and the flown
closest approach is now 5.0000 km against a reported 5.000 km.

## 5. tactical.py: the phasing orbit did not close

`phasing_orbit` solved for `N + phase/2pi` revolutions. A phasing orbit only
returns to its burn point after a whole number of revolutions, so the chaser
arrived at the target's angle at the wrong altitude and the second burn had
nothing to match.

Correct closure: the target starts *phase* ahead of the burn point P, so to be
at P after N chaser revolutions it must travel `2*pi*N - phase`, giving
`T_phase = T_target * (1 - phase / (2*pi*N))`.

| Phase gap | Old semi-major axis | Correct | Error |
|---|---|---|---|
| 5 deg | 41,778.1 km | 41,772.7 km | 5 km |
| 30 deg | 39,973.0 km | 39,787.8 km | 185 km |
| 90 deg | 36,335.8 km | 34,805.6 km | 1,530 km |
| 180 deg | 32,177.2 km | 26,561.7 km | **5,615 km** |

Small at the close-approach gaps the tool is used for most often, which is why
it looked plausible. Now flies exactly 1.000000 revolutions, and refuses a gap
too large for the revolutions allowed or a phasing orbit that would dip into
the atmosphere.

## 6. tactical.py: the intercept envelope could not see the geometry

`intercept_envelope_analytical` takes two radii and no angular separation, so
the term that dominates a co-orbital intercept cannot enter the calculation.
It also multiplies its result by `penalty = (tof_hohmann / tof)**0.5`, a
shaping heuristic with no physical derivation.

Measured against true Lambert solutions, co-orbital GEO, chaser 30 degrees
behind:

| Time of flight | Envelope | True Lambert | Ratio |
|---|---|---|---|
| 2 h | 2,015 m/s | 6,240 m/s | 0.32x |
| 6 h | 1,164 m/s | 1,993 m/s | 0.58x |
| 12 h | 5.6 m/s | 680 m/s | **0.01x** |

Underestimating intercept cost is the dangerous direction: it overstates how
easily a hostile can reach an asset, and it under-budgets our own planning.
For equal radii the Hohmann reference the penalty is anchored to degenerates to
zero delta-V over half a period, which describes no manoeuvre at all.

`intercept_envelope_intercept`, the TLE wrapper, claimed in its description to
run "a full Lambert sweep for higher accuracy" and did not: it discarded the
state vectors it held and passed only the two radii. It also took its delta-V
budget from a parameter named `target_distance_km`, a distance. It now runs a
real Lambert sweep over the requested window using the actual propagated
geometry, and records an unreachable time of flight as infeasible rather than
letting a gap in the sweep read as a cheap option.

The analytic function is retained for unequal radii and its docstring now
states plainly what it cannot represent.

## tactical.py: checked and found correct

`geo_drift` matches `delta_a = -2/3 (dlambda/dt) a / n` exactly, with the
correct sense: a lower orbit drifts east. `graveyard_transfer` matches the
closed form to nine figures and lands at 10.88 m/s against IADC guidance of
about 11 m/s for a 300 km raise. `j2_raan_rate` reproduces the
sun-synchronous condition. `cw_radial_separation` and `cw_along_track_drift`
agree with the validated CW propagator to 1e-6 km, including their reported
side effects, and `cw_along_track_drift` correctly surfaces that a 100 km
along-track move over six hours carries a 277 km radial excursion.

## What was checked and found correct

**Hohmann and bi-elliptic transfers** match the closed form to the last digit
(LEO to GEO, 3.8926 km/s against the published 3.89), are correctly reversible,
and the bi-elliptic crossover behaves properly with finite intermediate
apoapsis.

**Clohessy-Wiltshire** agrees with direct numerical integration of the CW
equations to 1e-12 km across five initial conditions at quarter-orbit and
full-orbit horizons. The 2:1 football closes exactly, an along-track offset is
stationary, cross-track is a clean oscillator, and the Hill frame matrix is
orthonormal and right-handed.

**J2 secular rates** reproduce the sun-synchronous condition at +0.9860 deg/day
against the definitional +0.9856, ISS nodal regression at -4.95 deg/day, and
the argument-of-perigee rate vanishes exactly at the critical inclination of
63.435 degrees.

**Monte Carlo pointing** draws the cone half-angle from a Rayleigh
distribution, which is correct for a two-axis Gaussian pointing error; a
Gaussian cone angle would put mass at negative angles and understate the tail.
Sampled statistics match theory to two decimal places.

## Open findings, not yet fixed

**Transfer functions have no input validation.** `hohmann(7000, 100)` returns
31.8 km/s for a transfer to a radius inside the Earth. `hohmann(7000, 0)`
raises `ZeroDivisionError` at the caller. `bielliptic` documents that the
intermediate apoapsis must exceed both radii and does not enforce it, returning
a number when it does not. Currently reachable only through `maneuvers.py` with
radii derived from real TLEs, so not live, but the preconditions should be
enforced where they are documented.

**The CW validity warning is regime-blind.** It warns above 500 km separation
regardless of orbit. Measured linearisation error after a quarter orbit:

| Separation | GEO | LEO |
|---|---|---|
| 10 km | 0.09% | 0.52% |
| 100 km | 0.86% | 5.1% |
| 500 km | 4.2% | **23.9%** |

The linearisation parameter is separation divided by orbit radius, so one fixed
threshold cannot serve both. Better still would be to report the estimated
error alongside the answer rather than a binary warning.

**The GEO radius constant is inconsistent with the sidereal day.** 42,164.0 km
gives a period of 86,163.57 s against the 86,164.1 s in the same file. Half a
second per day. It matters only at the margins of station-keeping versus drift
classification, but the two constants should agree.

**Frames are conflated.** SGP4 returns TEME. `state_to_keplerian` computes
elements in TEME and `keplerian_to_state` documents its output as ECI. TEME and
ECI differ by precession and nutation, tens of kilometres at GEO. Internally
consistent for relative geometry, wrong for anything compared against an
external ECI ephemeris or published back to a catalogue.

**`propagate_range` swallows propagation failures.** `except RuntimeError:
continue` means a window that fails entirely returns an empty list with no
error, the same silent-degradation pattern as the clustering import.

## Honest limits of this audit

Seven modules remain unaudited: `photometry.py`, `notso.py`, `events.py`,
`tle_filter.py`, `tle_preprocessing.py`, the collision-probability paths of
`monte_carlo.py`, and the bulk of `pattern_of_life.py` beyond its J2 rates.

Within `tactical.py`, the closed-form physics was validated but fourteen
heuristic and classification functions were not: `collision_avoidance`,
`classify_manoeuvre`, `detectability_metric`, `optimal_evasion`,
`assess_intercept_intent`, `relative_motion_stability`,
`fingerprint_manoeuvre`, `formation_defence_burn`, `orbital_terrain`,
`j2_drift_plan`, `combined_altitude_plane_change`, `cw_combined`,
`min_time_intercept_analytical`, and the two hop sequences. These encode
judgement rather than physics, so they need a subject-matter review against
doctrine rather than a numerical one, but note that `fingerprint_manoeuvre` and
`orbital_terrain` were both being fed angles corrupted by the units defect.

Every module examined closely contained at least one defect that produced
confidently wrong numbers. The prior for the remainder should not be
optimistic.

Three times during this audit the harness was wrong rather than the code: a
mis-stated CW drift coefficient, a Hill frame built from a bogus velocity, and
a relative-velocity term that omitted the frame rotation. Each initially looked
like a defect. The lesson is the one the codebase already demonstrates from the
other side: a check you have not verified is not evidence, whichever way it
points.

## What made these findings possible

Every defect here was invisible to the existing tests, which asserted the shape
of an answer rather than its value: a velocity magnitude within 15 per cent of
circular, a delta-V greater than zero, a burn count of two. A transfer that
misses by 6,268 km satisfies all three, and a plane change priced 57 times too
high satisfies the first.

Three checks would have caught all of it, and all three are cheap:

1. Compare against a published answer.
2. Fly the result and measure the miss distance. This needs no reference data
   and applies to any geometry.
3. Assert a physical invariant: energy, angular momentum, a closed relative
   orbit, a known secular rate, a round trip that returns the same state.
