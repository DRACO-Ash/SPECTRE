"""Search a method's free choices for the cheapest plan that reaches the target.

The intercept engine solved each method once with the coast, time of flight,
revolutions and hops the operator typed. The cost depends heavily on them:
on the GEO test pair a Lambert transfer costs 59 m/s with a 6 hour time of
flight and 9 m/s with 18 hours, and the panel showed whichever was typed.

This tries the choices instead and keeps the cheapest plan that brings the
red satellite within the approach radius; failing that, the one that comes
closest. The choices are:

● burn point: now, and the red satellite's next apogee, perigee, ascending
  node and descending node within one revolution;
● time of flight: fractions and multiples of the red revolution;
● revolutions, for phasing, and hops, for the V-bar and H-bar hops.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from spectre.astro.constants import MU_EARTH
from spectre.astro.events import find_orbital_events
from spectre.astro.maneuvers import InterceptSolution
from spectre.astro.propagator import TLEOrbit

#: Times of flight tried, as fractions of the red satellite's revolution.
TOF_FRACTIONS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
REVOLUTIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
HOPS: tuple[int, ...] = (1, 2, 3, 4, 5)

BURN = "burn point"
TOF = "time of flight"
REVS = "revolutions"
HOP = "hops"

NOW = "Now"

#: Event search resolution. One minute places a GEO apogee within about
#: 3 km of arc, finer than any solver here resolves.
_EVENT_STEP_S = 60.0


@dataclass(frozen=True)
class Choice:
    """One combination of a method's free choices."""

    burn_point: str
    burn_at: datetime
    coast_s: float
    tof_s: float | None = None
    revolutions: int | None = None
    hops: int | None = None


@dataclass(frozen=True)
class Targeted:
    """The plan the search kept, how it was measured, and what it compared."""

    solution: InterceptSolution
    choice: Choice
    closest_km: float
    closest_at: datetime
    approach: bool
    tried: int
    refused: int


#: Solves one choice; the caller binds the method and both satellites.
Solve = Callable[[Choice], InterceptSolution]
#: Measures a solution: (closest approach km, when).
Measure = Callable[[InterceptSolution], tuple[float, datetime]]


def revolution_s(red_tle: str, at: datetime) -> float:
    """The red satellite's revolution at *at*, in seconds."""
    sv = TLEOrbit(red_tle).propagate(at)
    a = 1.0 / (2.0 / sv.r_mag - sv.v_mag ** 2 / MU_EARTH)
    return 2.0 * math.pi * math.sqrt(a ** 3 / MU_EARTH)


def burn_points(red_tle: str, start: datetime, period_s: float) -> list[tuple[str, datetime]]:
    """Now, then the next of each orbital event within one revolution, in time order."""
    events = find_orbital_events(
        red_tle, start, start + timedelta(seconds=period_s), max_per_type=1, step_s=_EVENT_STEP_S,
    )
    named = [(e.event_type.value.replace("_", " ").capitalize(), e.epoch) for e in events]
    return [(NOW, start), *sorted(named, key=lambda p: p[1])]


def choices(
    axes: Iterable[str], points: list[tuple[str, datetime]], start: datetime, period_s: float,
) -> list[Choice]:
    """Every combination of the choices on *axes*, from each burn point."""
    wanted = set(axes)
    tofs: tuple[float | None, ...] = tuple(f * period_s for f in TOF_FRACTIONS) if TOF in wanted else (None,)
    revs: tuple[int | None, ...] = REVOLUTIONS if REVS in wanted else (None,)
    hops: tuple[int | None, ...] = HOPS if HOP in wanted else (None,)
    burns = points if BURN in wanted else points[:1]
    return [
        Choice(name, at, (at - start).total_seconds(), tof, rev, hop)
        for (name, at), tof, rev, hop in itertools.product(burns, tofs, revs, hops)
    ]


def _better(a: Targeted, b: Targeted) -> bool:
    """True when *a* should be kept over *b*: an approach first, then cheaper, then sooner."""
    if a.approach != b.approach:
        return a.approach
    if not a.approach:
        return a.closest_km < b.closest_km
    if not math.isclose(a.solution.total_delta_v, b.solution.total_delta_v, rel_tol=1e-6):
        return abs(a.solution.total_delta_v) < abs(b.solution.total_delta_v)
    return a.closest_at < b.closest_at


def search(
    solve: Solve, measure: Measure, candidates: list[Choice], approach_km: float,
) -> Targeted:
    """The best plan among *candidates*.

    Raises:
        Exception: the last refusal, when every candidate was refused, so the
            row says why in the solver's own words.
    """
    best: Targeted | None = None
    refused = 0
    last: Exception = ValueError("no combination to try")
    for choice in candidates:
        try:
            sol = solve(choice)
            closest_km, closest_at = measure(sol)
        # BLE001: a refused combination is counted and the search goes on.
        except Exception as exc:  # noqa: BLE001
            refused += 1
            last = exc
            continue
        if math.isnan(closest_km):
            refused += 1
            last = ValueError("the plan's closest approach could not be computed")
            continue
        found = Targeted(sol, choice, closest_km, closest_at, closest_km <= approach_km, 0, 0)
        if best is None or _better(found, best):
            best = found
    if best is None:
        raise last
    return Targeted(
        best.solution, best.choice, best.closest_km, best.closest_at, best.approach,
        tried=len(candidates), refused=refused,
    )
