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

The RK45 path's altitude floor, REENTRY_FLOOR_KM, holds here too (SPC-200,
evaluation F-30): an object below it at any instant searched has decayed or is
decaying, and the call is refused naming its side. SGP4 raises its own decay
error only while the radius is under one Earth radius, so between perigee
passes it returns states again, and a decayed object gave a computed miss. That
error, code SGP4_DECAYED, is read as the same re-entry, so whether a search
meets the error or the floor first, the refusal says the object has decayed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, NamedTuple

import numpy as np

from spectre.astro.along_track import position_error_km
from spectre.astro.closest_approach import ClosestApproach, closest_approach
from spectre.astro.monte_carlo import REENTRY_FLOOR_KM, SeparationWindow
from spectre.astro.propagator import SGP4_DECAYED, TLE_ERRORS, SGP4Error, StateVector, TLEOrbit, regime_from_tle

#: What every computed closest approach propagates with, stated on it.
ELSET_PROPAGATOR = "SGP4 for both orbits, from their element sets, with no burn"

Side = Literal["red", "blue"]


class ElsetApproach(NamedTuple):
    """The closest approach in *window*, unrounded with its edge flag, and the relative speed at it, km/s."""

    approach: ClosestApproach
    closing_speed_km_s: float
    window: SeparationWindow
    propagator: str = ELSET_PROPAGATOR


_SECONDS_PER_DAY = 86_400.0


def elset_position_error_km(tle: str, epoch: datetime, at: datetime) -> float:
    """The position error the sweep assumes for *tle*, whose epoch is *epoch*, aged to *at* (SPC-118).

    The model is spectre/astro/along_track.py's, tuned rather than sourced: 1 km at epoch plus 2 km a day by the LEO
    figure, 2 km plus 1 km a day by the GEO figure, chosen by the regime family read from the element set's own
    elements; along_track.error_rate_words says whose figure a set takes (SPC-215).
    """
    return position_error_km((at - epoch).total_seconds() / _SECONDS_PER_DAY, regime_from_tle(tle))


Reason = Literal["unparsable", "propagation", "reentered"]


class ElsetFailure(NamedTuple):
    """Why there is no closest approach: which side's element set did not parse, did not propagate, or put its
    object below REENTRY_FLOOR_KM at an instant searched."""

    side: Side
    reason: Reason


class _SideFailedError(Exception):
    """One side's SGP4 failed, or its object was below the re-entry floor, at an instant of the search."""

    def __init__(self, side: Side, reason: Reason = "propagation") -> None:
        super().__init__(side)
        self.side = side
        self.reason: Reason = reason


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
                state = orbit.propagate(when)
            except TLE_ERRORS as exc:
                decayed = isinstance(exc, SGP4Error) and exc.code == SGP4_DECAYED
                raise _SideFailedError(side, "reentered" if decayed else "propagation") from exc
            if state.altitude_km < REENTRY_FLOOR_KM:
                raise _SideFailedError(side, "reentered")
            out.append(state)
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
    through closest_approach. Refused, naming the side, when an element set does not parse, or SGP4 fails or
    puts its object below REENTRY_FLOOR_KM at any instant searched, the closest approach's own included.
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
        return ElsetFailure(failed.side, failed.reason)
    return ElsetApproach(approach=approach, closing_speed_km_s=speed, window=window)


class BurnApproach(NamedTuple):
    """The red object's closest approach to one blue set from before a burn and from after it (SPC-173).

    *margin_km* is the position error the two misses carry between them: for each, the sweep's assumed error of
    the red set and of the blue set aged to that TCA (SPC-118), added as the worst case. A miss that shrank by
    no more than this is not shown to be closer.
    """

    before: ElsetApproach
    after: ElsetApproach
    margin_km: float

    @property
    def after_tca(self) -> datetime:
        """When the approach after the burn happens."""
        return _tca(self.after)


def _tca(found: ElsetApproach) -> datetime:
    return found.window.start_utc + timedelta(seconds=found.approach.tca_s)


def _separation_error_km(red: tuple[str, datetime], blue: tuple[str, datetime], at: datetime) -> float:
    return elset_position_error_km(red[0], red[1], at) + elset_position_error_km(blue[0], blue[1], at)


def burn_approach(red_before: tuple[str, datetime], red_after: tuple[str, datetime], blue: tuple[str, datetime],
                  window: SeparationWindow) -> BurnApproach | ElsetFailure:
    """The closest approach of the red set from before a burn, and of the one from after it, to *blue* over *window*.

    Each argument is an element set and its epoch. Before is flown across the window as if the burn had not
    happened. Refused, naming the side, as elset_closest_approach refuses either search.
    """
    before = elset_closest_approach(red_before[0], blue[0], window)
    if isinstance(before, ElsetFailure):
        return before
    after = elset_closest_approach(red_after[0], blue[0], window)
    if isinstance(after, ElsetFailure):
        return after
    margin = _separation_error_km(red_before, blue, _tca(before)) + _separation_error_km(red_after, blue, _tca(after))
    return BurnApproach(before=before, after=after, margin_km=margin)
