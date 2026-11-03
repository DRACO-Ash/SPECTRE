"""The closest approach of two element sets, both on SGP4, with no burn (SPC-120).

The Decision Engine's computed closest approach. Both orbits are propagated
by SGP4 from their element sets, and their separation is searched by the
shared helper (closest_approach), every 60 s from the window start with each
local minimum refined to 0.01 s, as the access search does (audit F-115). It
lives here, pure apart from SGP4, so the Decision Engine never names the
propagator.

One propagator for both objects: SGP4 against RK45 missed the GEO reference
TCA by 1,951 s (0.13.0). A failed SGP4 instant refuses the whole call, naming
its side, rather than reading as infinite, because an infinity could hide the
minimum it stands in for.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, NamedTuple

import numpy as np

from spectre.astro.closest_approach import ClosestApproach, closest_approach
from spectre.astro.monte_carlo import SeparationWindow
from spectre.astro.propagator import TLE_ERRORS, StateVector, TLEOrbit

#: What every computed closest approach propagates with, stated on it.
ELSET_PROPAGATOR = "SGP4 for both orbits, from their element sets, with no burn"

Side = Literal["red", "blue"]


class ElsetApproach(NamedTuple):
    """The closest approach in *window*, unrounded with its edge flag, and the relative speed at it, km/s."""

    approach: ClosestApproach
    closing_speed_km_s: float
    window: SeparationWindow
    propagator: str = ELSET_PROPAGATOR


class ElsetFailure(NamedTuple):
    """Why there is no closest approach: which side's element set did not parse or did not propagate."""

    side: Side
    reason: Literal["unparsable", "propagation"]


class _SideFailedError(Exception):
    """One side's SGP4 failed at an instant of the search."""

    def __init__(self, side: Side) -> None:
        super().__init__(side)
        self.side = side


class _Pair:
    """Both orbits, propagated together; any SGP4 failure raises _SideFailedError naming its side."""

    def __init__(self, red: TLEOrbit, blue: TLEOrbit, start: datetime) -> None:
        self.orbits: tuple[tuple[Side, TLEOrbit], ...] = (("red", red), ("blue", blue))
        self.start = start

    def states(self, t: float) -> tuple[StateVector, StateVector]:
        when = self.start + timedelta(seconds=t)
        out: list[StateVector] = []
        for side, orbit in self.orbits:
            try:
                out.append(orbit.propagate(when))
            except TLE_ERRORS as exc:
                raise _SideFailedError(side) from exc
        return out[0], out[1]

    def separation_km(self, t: float) -> float:
        red, blue = self.states(t)
        return float(np.linalg.norm(red.r - blue.r))

    def speed_km_s(self, t: float) -> float:
        red, blue = self.states(t)
        return float(np.linalg.norm(red.v - blue.v))


def _orbit(side: Side, tle: str) -> TLEOrbit | ElsetFailure:
    try:
        return TLEOrbit(tle)
    except TLE_ERRORS:
        return ElsetFailure(side, "unparsable")


def elset_closest_approach(red_tle: str, blue_tle: str, window: SeparationWindow) -> ElsetApproach | ElsetFailure:
    """The closest approach of *red_tle* to *blue_tle* over *window*, both on SGP4 with no burn.

    The search samples every ``window.step_s`` (60 s by default) and refines each local minimum to 0.01 s
    through closest_approach. Refused, naming the side, when an element set does not parse or SGP4 fails at
    any instant searched, the closest approach's own included.
    """
    red = _orbit("red", red_tle)
    if isinstance(red, ElsetFailure):
        return red
    blue = _orbit("blue", blue_tle)
    if isinstance(blue, ElsetFailure):
        return blue
    pair = _Pair(red, blue, window.start_utc)
    try:
        approach = closest_approach(pair.separation_km, window.span_s, step_s=window.step_s)
        speed = pair.speed_km_s(approach.tca_s)
    except _SideFailedError as failed:
        return ElsetFailure(failed.side, "propagation")
    return ElsetApproach(approach=approach, closing_speed_km_s=speed, window=window)
