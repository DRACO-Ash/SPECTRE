"""Fly a plan's burns and measure how close the red satellite really comes (charming-dirac d3447e2, SPC-234).

Several solvers report the miss they were asked for rather than the one their burns achieve: Lambert its aim, CW
drift and COLA the standoff requested, minimum-time 0.0. On the GEO test pair, 736 km apart, CW drift read 10 km.
A plan that never reaches its target read as an approach.

This flies the plan instead. The red satellite is propagated by SGP4 to its first burn, and from there
spectre.astro.maneuvers.flown_approach applies each burn in turn and searches the separation from the target to
arrival: the same function plane change, phasing and the R-bar hop fly their own burn with (0.33.0), so there is
one flown-miss path. Every solver builds its burns in the inertial frame, through ``maneuvers._make_burn``. A plan
that arrives the moment it fires, such as a plane change, is flown for one revolution of the orbit it leaves on.

Basis, for the analyst: two-body for red between burns, as every solver here assumes; SGP4 for the target. This
differs from the Decision Engine's RK45 with J2, which flies a row only once it is opened there.
"""

from __future__ import annotations

from datetime import timedelta

from spectre.astro.constants import MU_EARTH
from spectre.astro.maneuvers import FlownApproach, InterceptSolution, flown_approach, orbit_period_s
from spectre.astro.propagator import StateVector, TLEOrbit

#: A plan whose arrival is within this of its first burn has no time of flight worth searching, so it is flown for
#: one revolution instead.
_INSTANT = timedelta(minutes=1)

#: What every flown closest approach is computed with, stated beside it.
FLIGHT_BASIS = "flown from the plan's burns: two-body for red between burns, SGP4 for the target"


def _window(sol: InterceptSolution, red_tle: str, mu: float) -> tuple[StateVector, float]:
    """Red's state at *sol*'s first burn and the span its flight is searched over, s."""
    burns = sorted(sol.burns, key=lambda b: b.epoch)
    start = burns[0].epoch if burns else sol.departure_epoch
    sv = TLEOrbit(red_tle).propagate(start)
    span = sol.arrival_epoch - start
    span_s = span.total_seconds()
    if span < _INSTANT:
        # Every burn lands within the minute, so the orbit it leaves on is red's velocity plus all of them.
        after = StateVector(epoch=start, r=sv.r, v=sv.v + sum((b.delta_v for b in burns), start=0.0 * sv.v))
        span_s = orbit_period_s(after, mu) or 0.0
    return sv, span_s


def fly(sol: InterceptSolution, red_tle: str, blue_tle: str, mu: float = MU_EARTH) -> FlownApproach:
    """The closest the red satellite comes to the target flying *sol*'s burns, from its first burn to arrival."""
    sv, span_s = _window(sol, red_tle, mu)
    plan = [(b.epoch, b.delta_v) for b in sorted(sol.burns, key=lambda b: b.epoch)]
    return flown_approach(sv, plan, TLEOrbit(blue_tle), span_s, mu)


def baseline(sol: InterceptSolution, red_tle: str, blue_tle: str, mu: float = MU_EARTH) -> FlownApproach:
    """The closest the red satellite comes to the target over *sol*'s window with no burn at all.

    When this is already inside the approach radius, burning reaches nothing the satellite was not already at: on a
    LEO pair 18 km apart a 0 m/s Hohmann "arrived" and became the most likely course of action (review of SPC-234).
    """
    sv, span_s = _window(sol, red_tle, mu)
    return flown_approach(sv, [], TLEOrbit(blue_tle), span_s, mu)
