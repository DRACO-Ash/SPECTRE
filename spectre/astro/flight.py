"""Fly a plan's burns and measure how close the red satellite really comes.

Several solvers reported the miss distance they were asked for rather than
the one their burns achieve: the R-bar hop, CW drift, COLA and Formation
returned the requested standoff, and Lambert and minimum-time returned
their aim, with the target 599 km away on the GEO test pair. A plan that
never reaches its target was ranked as an approach.

This flies the plan instead. The red satellite is propagated to its first
burn, each burn is applied in turn (every solver builds its burns in the
inertial frame, through ``maneuvers._make_burn``), and the separation from
the target is sampled from the first burn to arrival. A single burn with no
time of flight, such as a plane change, is flown for one revolution.

Between burns the motion is two-body, as every solver here assumes; the
target is propagated with SGP4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from spectre.astro.constants import MU_EARTH
from spectre.astro.kepler import propagate_two_body
from spectre.astro.maneuvers import Burn, InterceptSolution
from spectre.astro.propagator import StateVector, TLEOrbit

#: Samples over the flight. At GEO over 24 hours, one every 15 minutes.
FLIGHT_SAMPLES = 96

#: A flight shorter than this has no time of flight worth sampling, so it
#: is flown for a revolution instead.
_INSTANT = timedelta(minutes=1)


@dataclass(frozen=True)
class Flight:
    """Where the flown plan comes closest to the target."""

    closest_km: float
    closest_at: datetime


def _period(sv: StateVector, mu: float) -> timedelta:
    energy = sv.v_mag ** 2 / 2.0 - mu / sv.r_mag
    if energy >= 0:
        raise ValueError("the burn leaves the red satellite on an escape trajectory")
    a = -mu / (2.0 * energy)
    return timedelta(seconds=2.0 * math.pi * math.sqrt(a ** 3 / mu))


def _coast(sv: StateVector, until: datetime, mu: float) -> StateVector:
    r, v = propagate_two_body(sv.r, sv.v, (until - sv.epoch).total_seconds(), mu)
    return StateVector(epoch=until, r=r, v=v)


def _after_burn(sv: StateVector, burn: Burn) -> StateVector:
    return StateVector(epoch=sv.epoch, r=sv.r, v=sv.v + np.asarray(burn.delta_v, dtype=float))


def fly(sol: InterceptSolution, red_tle: str, blue_tle: str, mu: float = MU_EARTH) -> Flight:
    """The closest the red satellite comes to the target flying *sol*'s burns."""
    red = TLEOrbit(red_tle)
    blue = TLEOrbit(blue_tle)
    burns = sorted(sol.burns, key=lambda b: b.epoch)
    start = burns[0].epoch if burns else sol.departure_epoch
    # Each leg is the state just after a burn, flown until the next burn.
    sv = red.propagate(start)
    legs: list[StateVector] = [sv]
    for burn in burns:
        sv = _after_burn(_coast(sv, burn.epoch, mu), burn)
        legs.append(sv)
    end = sol.arrival_epoch
    if end - start < _INSTANT:
        end = start + _period(legs[-1], mu)
    step = (end - start) / FLIGHT_SAMPLES
    best = Flight(math.inf, start)
    for k in range(FLIGHT_SAMPLES + 1):
        when = start + step * k
        leg = next((s for s in reversed(legs) if s.epoch <= when), legs[0])
        here = _coast(leg, when, mu)
        gap = float(np.linalg.norm(here.r - blue.propagate(when).r))
        if gap < best.closest_km:
            best = Flight(gap, when)
    return best
