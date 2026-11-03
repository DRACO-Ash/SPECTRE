"""Our burn on the blue asset, sized to a target separation by propagation (SPC-121).

SGP4 cannot take an impulsive burn, and SPECTRE fits no element set to a burnt orbit, so a figure that includes our
burn propagates both objects by the Monte Carlo engine's RK45 with J2 and exponential drag, from their SGP4 states
at the scenario epoch, and blue burns from its own RK45 arc at the burn time. What the burn buys is then the RK45
closest approach after it minus the RK45 closest approach before it, from the same arcs: one model on both sides
of the subtraction.

The size is a search, not an optimiser. The manoeuvre library's Clohessy-Wiltshire answer
(tactical.collision_avoidance) gives the axis, when the operator names none, and a first size; both senses are
flown at that size; the size doubles until the target is reached or the budget is spent, then halves back to
within 1 %. The library's size assumes the time of closest approach stays fixed, and a burn moves it: in the
coplanar_leo reference case it guesses about 0.23 m/s, and 3.085 m/s retrograde in-track is what reaches 20 km,
while 1 m/s prograde closes the miss from 10.006 km to 9.705 km. The minimum miss is continuous in delta-V but not
monotone, so a smaller burn on the same axis may also reach the target.

Imports the Monte Carlo engine, never the reverse.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Literal, NamedTuple

import numpy as np

from spectre.astro.elset_approach import ElsetApproach, ElsetFailure, Side
from spectre.astro.monte_carlo import (
    BlueBurn,
    BlueTrack,
    ManoeuvreHypothesis,
    ReenteredError,
    SeparationWindow,
    burnt_arc,
    elset_state,
    nominal_red_arc,
    rk45_arc,
    searched_approach,
)
from spectre.astro.tactical import collision_avoidance

#: What every figure that may include our burn propagates with, stated on it.
RESPONSE_PROPAGATOR = (
    "RK45 with J2 and exponential drag for both orbits, from their SGP4 states at the scenario epoch, our burn "
    "applied to the blue asset"
)
#: The most burns one sizing flies: 2 senses, at most 6 doublings from the larger of the library's size and the
#: budget over 64, and 7 halvings to within 1 %.
MAX_SIZING_TRIALS = 16
#: The first size is at least the budget over this, so 6 doublings reach the whole budget.
_FIRST_SIZE_DIVISOR = 64.0
#: The search stops once the size is known to within this fraction of itself.
_SIZE_TOLERANCE = 0.01

#: A trajectory: the state [x, y, z, vx, vy, vz] at t seconds after the window start.
Trajectory = Callable[[float], np.ndarray]
#: Called after every trial with (the request's key, trials flown, MAX_SIZING_TRIALS); it may raise to stop.
SizingTick = Callable[[str, int, int], None]


class BurnAxis(StrEnum):
    """The axis our burn is sized on: the library's cheapest, or one the operator names."""

    CHEAPEST = "cheapest"
    RADIAL = "radial"
    IN_TRACK = "in-track"
    CROSS_TRACK = "cross-track"


_AXIS_INDEX: dict[BurnAxis, int] = {BurnAxis.RADIAL: 0, BurnAxis.IN_TRACK: 1, BurnAxis.CROSS_TRACK: 2}
_LIBRARY_AXES: dict[str, BurnAxis] = {
    "radial": BurnAxis.RADIAL, "along_track": BurnAxis.IN_TRACK, "out_of_plane": BurnAxis.CROSS_TRACK,
}
_LIBRARY_FIELDS: dict[BurnAxis, str] = {
    BurnAxis.RADIAL: "radial", BurnAxis.IN_TRACK: "along_track", BurnAxis.CROSS_TRACK: "out_of_plane",
}


class BurnRequest(NamedTuple):
    """One response's burn to size: at *at_s* after the window start, to *target_km*, within *budget_km_s*."""

    key: str
    at_s: float
    target_km: float
    budget_km_s: float
    axis: BurnAxis


class SizedBurn(NamedTuple):
    """The burn found for a request, with the closest approach before and after it, both RK45 for both orbits.

    *burn* is None when the target is met without one, and *after* is then *before*. *sense* is +1 or -1 along
    *axis*, 0 with no burn; *reached* is False when the whole budget falls short of the target.
    """

    key: str
    burn: BlueBurn | None
    before: ElsetApproach
    after: ElsetApproach
    axis: BurnAxis
    from_library: bool
    lead_s: float
    sense: int
    reached: bool
    trials: int


class BurnRefusal(NamedTuple):
    """Why a request was not sized: the burn is after the window or the closest approach, or its arc failed.

    *tca_s* is the no-burn closest approach's time, after the window start, that an "after_tca" refusal was decided
    on, so the sentence names the same figure; None for the other reasons.
    """

    key: str
    reason: Literal["after_window", "after_tca", "propagation", "reentered"]
    trials: int
    tca_s: float | None = None


class Rk45Plan(NamedTuple):
    """A bound pair on RK45 for both orbits: the closest approach with no burn, and each request's burn."""

    before: ElsetApproach
    responses: tuple[SizedBurn | BurnRefusal, ...]


class Rk45Pair(NamedTuple):
    """Both orbits' RK45 arcs over a window from their SGP4 states at its start, and blue's B*."""

    red: Trajectory
    blue: Trajectory
    blue_bstar: float


class _ArcFailedError(Exception):
    """A burnt arc's solve failed."""


def rk45_approach(red: Trajectory, blue: Trajectory, window: SeparationWindow) -> ElsetApproach:
    """The closest approach of *red* to *blue* over *window*, both RK45, with their relative speed at it."""
    found = searched_approach(red, blue, window)
    return ElsetApproach(found.approach, found.closing_speed_km_s, window, RESPONSE_PROPAGATOR)


def burnt_approach(pair: Rk45Pair, window: SeparationWindow, burn: BlueBurn) -> ElsetApproach:
    """The closest approach once *burn* is applied to blue's RK45 arc. Raises ReenteredError or _ArcFailedError."""
    burnt = burnt_arc(pair.blue, burn, window.span_s, pair.blue_bstar)
    if burnt is None:
        raise _ArcFailedError
    return rk45_approach(pair.red, burnt, window)


def rk45_pair(red_tle: str, blue_tle: str, window: SeparationWindow) -> Rk45Pair | ElsetFailure:
    """Both element sets' RK45 arcs over *window* from their SGP4 states at its start; a failure names its side."""
    arcs: list[Trajectory] = []
    bstar = 0.0
    sides: tuple[tuple[Side, str], ...] = (("red", red_tle), ("blue", blue_tle))
    for side, tle in sides:
        start = elset_state(tle, window.start_utc)
        arc = None if start is None else _arc_or_none(start, window)
        if start is None or arc is None:
            return ElsetFailure(side, "propagation")
        arcs.append(arc)
        bstar = start.bstar
    return Rk45Pair(arcs[0], arcs[1], bstar)


def _arc_or_none(start: BlueTrack, window: SeparationWindow) -> Trajectory | None:
    try:
        return rk45_arc(start.state_eci_km, window.span_s, start.bstar)
    except (ReenteredError, ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return None


def elset_response_plan(
    red_tle: str, blue_tle: str, window: SeparationWindow, requests: Sequence[BurnRequest], *,
    tick: SizingTick | None = None,
) -> Rk45Plan | ElsetFailure:
    """The bound pair on RK45 for both orbits with no burn, and each request sized against it (a computed row)."""
    pair = rk45_pair(red_tle, blue_tle, window)
    if isinstance(pair, ElsetFailure):
        return pair
    before = rk45_approach(pair.red, pair.blue, window)
    return Rk45Plan(before, tuple(_size(pair, window, request, before, tick) for request in requests))


def hypothesis_response_plan(
    hypothesis: ManoeuvreHypothesis, blue: BlueTrack, window: SeparationWindow, requests: Sequence[BurnRequest], *,
    tick: SizingTick | None = None,
) -> tuple[SizedBurn | BurnRefusal, ...] | None:
    """Each request sized against red with the hypothesis's nominal burn (a sampled row); None when an arc fails."""
    red = nominal_red_arc(hypothesis, window)
    blue_arc = _arc_or_none(blue, window)
    if red is None or blue_arc is None:
        return None
    pair = Rk45Pair(red, blue_arc, blue.bstar)
    before = rk45_approach(red, blue_arc, window)
    return tuple(_size(pair, window, request, before, tick) for request in requests)


def size_against(
    pair: Rk45Pair, window: SeparationWindow, request: BurnRequest, *, tick: SizingTick | None = None,
) -> SizedBurn | BurnRefusal:
    """*request* sized against the pair's red: the smallest burn found on its axis that puts the closest approach
    at its target or more within its budget, or the whole budget when none does; refused when it cannot open it."""
    return _size(pair, window, request, rk45_approach(pair.red, pair.blue, window), tick)


class _Trials:
    """Flies burns on one axis and sense, counting them and ticking after each."""

    def __init__(self, pair: Rk45Pair, window: SeparationWindow, request: BurnRequest, tick: SizingTick | None) -> None:
        self.pair, self.window, self.request, self.tick = pair, window, request, tick
        self.count = 0

    def burn(self, axis: BurnAxis, signed_km_s: float) -> BlueBurn:
        parts = [0.0, 0.0, 0.0]
        parts[_AXIS_INDEX[axis]] = signed_km_s
        return BlueBurn(self.request.at_s, (parts[0], parts[1], parts[2]))

    def fly(self, burn: BlueBurn) -> ElsetApproach:
        self.count += 1
        try:
            return burnt_approach(self.pair, self.window, burn)
        finally:
            if self.tick is not None:
                self.tick(self.request.key, self.count, MAX_SIZING_TRIALS)

    @property
    def spent(self) -> bool:
        return self.count >= MAX_SIZING_TRIALS


def _size(
    pair: Rk45Pair, window: SeparationWindow, request: BurnRequest, before: ElsetApproach, tick: SizingTick | None,
) -> SizedBurn | BurnRefusal:
    """Size *request* against the no-burn *before*, or refuse it naming why."""
    lead = before.approach.tca_s - request.at_s
    if before.approach.miss_km >= request.target_km:
        return SizedBurn(request.key, None, before, before, request.axis, False, lead, 0, reached=True, trials=0)
    if request.at_s >= window.span_s:
        return BurnRefusal(request.key, "after_window", 0)
    if lead <= 0.0:
        return BurnRefusal(request.key, "after_tca", 0, before.approach.tca_s)
    trials = _Trials(pair, window, request, tick)
    try:
        return _search(trials, before, lead)
    except ReenteredError:
        return BurnRefusal(request.key, "reentered", trials.count)
    except (_ArcFailedError, ArithmeticError, ValueError):   # numpy's LinAlgError is a ValueError
        return BurnRefusal(request.key, "propagation", trials.count)


def _first_guess(trials: _Trials, lead: float) -> tuple[BurnAxis, float]:
    """The axis, the library's cheapest unless the operator named one, and the first size, km/s."""
    request = trials.request
    r_blue = float(np.linalg.norm(trials.pair.blue(request.at_s)[:3]))
    plan = collision_avoidance(r_blue, request.target_km, lead)
    if request.axis is BurnAxis.CHEAPEST:
        choice = plan.best
        axis = _LIBRARY_AXES[choice.strategy]
    else:
        choice, axis = getattr(plan, _LIBRARY_FIELDS[request.axis]), request.axis
    size = float(choice.delta_v)
    floor = request.budget_km_s / _FIRST_SIZE_DIVISOR
    return axis, min(max(size, floor), request.budget_km_s) if math.isfinite(size) else request.budget_km_s


def _search(trials: _Trials, before: ElsetApproach, lead: float) -> SizedBurn:
    """Fly both senses at the first size, double to the target or the budget, then halve back to within 1 %."""
    request = trials.request
    axis, size = _first_guess(trials, lead)
    plus, minus = trials.fly(trials.burn(axis, size)), trials.fly(trials.burn(axis, -size))
    sense, found = (1, plus) if plus.approach.miss_km >= minus.approach.miss_km else (-1, minus)
    low, high = 0.0, size
    while found.approach.miss_km < request.target_km and high < request.budget_km_s and not trials.spent:
        low, high = high, min(2.0 * high, request.budget_km_s)
        found = trials.fly(trials.burn(axis, sense * high))
    reached = found.approach.miss_km >= request.target_km
    while reached and high - low > _SIZE_TOLERANCE * high and not trials.spent:
        middle = 0.5 * (low + high)
        tried = trials.fly(trials.burn(axis, sense * middle))
        if tried.approach.miss_km >= request.target_km:
            high, found = middle, tried
        else:
            low = middle
    return SizedBurn(
        request.key, trials.burn(axis, sense * high), before, found, axis,
        request.axis is BurnAxis.CHEAPEST, lead, sense, reached, trials.count,
    )
