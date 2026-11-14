"""Search a method's free choices for the cheapest plan that reaches the target (charming-dirac d3447e2, SPC-234).

The Intercept Engine solved each method once with the coast, time of flight, revolutions and hops the operator
typed. The cost depends heavily on them: on the GEO test pair a Lambert transfer costs several times more with a
6 hour time of flight than with a longer one, and the panel showed whichever was typed.

This tries the choices instead and keeps the cheapest plan that brings the red satellite within the approach
radius; failing that, the one that comes closest, which the row then labels as not an approach. Nothing is
dropped for not arriving (owner ruling, 2026-11-12). The choices are:

● burn point: now, and the red satellite's next apogee, perigee, ascending node and descending node within one
  revolution;
● time of flight: fractions and multiples of the red revolution;
● revolutions, for phasing, and hops, for the V-bar and H-bar hops.

Every combination is solved first, which costs little; the plans are then measured cheapest first, and once one
arrives nothing dearer can beat it, so the flying stops there. A plan whose closest approach could not be computed
(NaN, SPC-238) is kept only when nothing else was measured, and never reads as arriving.

The grids are tuned, not sourced: Claude's choice in d3447e2, kept by this port.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

from spectre.astro.events import find_orbital_events
from spectre.astro.maneuvers import InterceptSolution, orbit_period_s
from spectre.astro.propagator import TLEOrbit

#: Times of flight tried, as fractions of the red satellite's revolution.
TOF_FRACTIONS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
#: Phasing orbit revolutions tried.
REVOLUTIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
#: V-bar and H-bar hop counts tried.
HOPS: tuple[int, ...] = (1, 2, 3, 4, 5)

BURN = "burn point"
TOF = "time of flight"
REVS = "revolutions"
HOP = "hops"

NOW = "Now"

#: Arrival is judged with this tolerance, km: the larger of 1 m and a millionth of the radius. A flown Lambert miss
#: lands micrometres either side of its aim point, so a plain comparison rejected half of the plans that reach it
#: (review of SPC-234: 14 of 28 at a 100 m standoff on the GEO test pair).
_ARRIVAL_FLOOR_KM = 1e-3
_ARRIVAL_FRACTION = 1e-6

#: Event search resolution. One minute places a GEO apogee within about 3 km of arc, finer than any solver here
#: resolves.
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
    """The plan the search kept, how close it came, and what it compared."""

    solution: InterceptSolution
    choice: Choice
    closest_km: float              # NaN when it could not be computed
    closest_at: datetime | None    # None when it could not be computed
    approach: bool
    tried: int
    refused: int
    #: The target was already within the radius with no burn over the same window, so burning reached nothing.
    already_within: bool = False


class Measured(NamedTuple):
    """What a measure reports of one plan: its closest approach, when, and the closest with no burn at all over the
    same window (NaN when not flown), km."""

    closest_km: float
    closest_at: datetime | None
    baseline_km: float = math.nan


#: Solves one choice; the caller binds the method and both satellites.
Solve = Callable[[Choice], InterceptSolution]
#: Measures a solution: (closest approach km, when[, no-burn baseline km]), (NaN, None) when not computed.
Measure = Callable[[InterceptSolution], tuple[float, datetime | None] | Measured]


def arrives(closest_km: float, approach_km: float) -> bool:
    """Whether a closest approach of *closest_km* is within *approach_km*, with the tolerance above.

    The one place arrival is judged. NaN or infinity never arrives (SPC-238).
    """
    tolerance = max(_ARRIVAL_FLOOR_KM, _ARRIVAL_FRACTION * approach_km)
    return math.isfinite(closest_km) and closest_km <= approach_km + tolerance


def revolution_s(red_tle: str, at: datetime) -> float:
    """The red satellite's revolution at *at*, in seconds."""
    period = orbit_period_s(TLEOrbit(red_tle).propagate(at))
    if period is None:
        raise ValueError("the red satellite is not on a closed orbit")
    return period


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


def _cost(sol: InterceptSolution) -> float:
    return abs(sol.total_delta_v)


def _rank(t: Targeted) -> int:
    """0 an approach, 1 a computed miss beyond the radius, 2 a miss not computed."""
    if t.approach:
        return 0
    return 1 if math.isfinite(t.closest_km) else 2


def _same_cost(a: InterceptSolution, b: InterceptSolution) -> bool:
    return math.isclose(_cost(a), _cost(b), rel_tol=1e-6)


def _better(a: Targeted, b: Targeted) -> bool:
    """True when *a* should be kept over *b*: an approach, cheaper then sooner; else the closer; else the cheaper."""
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return ra < rb
    if ra == 1:
        return a.closest_km < b.closest_km
    if ra == 0 and _same_cost(a.solution, b.solution):
        return a.closest_at is not None and b.closest_at is not None and a.closest_at < b.closest_at
    return _cost(a.solution) < _cost(b.solution)


def _solve_all(solve: Solve, candidates: list[Choice]) -> tuple[list[tuple[Choice, InterceptSolution]], Exception]:
    """Every candidate the solver accepts, cheapest first, and the last refusal."""
    solved: list[tuple[Choice, InterceptSolution]] = []
    last: Exception = ValueError("no combination to try")
    for choice in candidates:
        try:
            solved.append((choice, solve(choice)))
        # BLE001: a refused combination is counted and the search goes on.
        except Exception as exc:  # noqa: BLE001
            last = exc
    solved.sort(key=lambda pair: _cost(pair[1]))
    return solved, last


def search(solve: Solve, measure: Measure, candidates: list[Choice], approach_km: float) -> Targeted:
    """The best plan among *candidates*.

    Raises:
        Exception: the last refusal, when every candidate was refused, so the row says why in the solver's own
            words.
    """
    solved, last = _solve_all(solve, candidates)
    refused = len(candidates) - len(solved)
    best: Targeted | None = None
    for choice, sol in solved:
        if best is not None and best.approach and not _same_cost(sol, best.solution):
            break  # cheapest first: nothing dearer beats an approach already found
        try:
            closest_km, closest_at, baseline_km = Measured(*measure(sol))
        # BLE001: a plan that cannot be flown is counted as refused, as a solver refusal is.
        except Exception as exc:  # noqa: BLE001
            refused, last = refused + 1, exc
            continue
        already = arrives(baseline_km, approach_km)
        found = Targeted(sol, choice, closest_km, closest_at, arrives(closest_km, approach_km) and not already, 0, 0,
                         already_within=already)
        if best is None or _better(found, best):
            best = found
    if best is None:
        raise last
    return dataclasses.replace(best, tried=len(candidates), refused=refused)
