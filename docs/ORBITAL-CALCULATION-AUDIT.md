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
| remaining eight modules | **not audited** | see the honest limits below |

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

Eight modules were not audited: `tactical.py` (2,129 lines, the largest in the
package), `photometry.py`, `notso.py`, `events.py`, `tle_filter.py`,
`tle_preprocessing.py`, the collision-probability paths of `monte_carlo.py`,
and the bulk of `pattern_of_life.py` beyond its J2 rates. Given that the three
modules examined most closely each contained a defect that produced confidently
wrong numbers, the prior for the remainder should not be optimistic.

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
