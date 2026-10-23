"""Minimum-time intercept pinned to physics the old routine could not obey.

The analytic routine clamped its transfer orbit so that delta-V never depended
on the time of flight, and returned 1 per cent of the Hohmann time at less than
Hohmann cost: LEO to GEO in 190 s (audit F-004). The replacement solves
Lambert's problem against the target's real position at each arrival time.

Checks used here, each independent of the code under test:
● a two-impulse transfer between circular coplanar orbits with r2/r1 < 11.94
  cannot cost less than Hohmann (Vallado section 6.3);
● the departure state plus the first burn, propagated two-body for the time of
  flight, must reach the target;
● more budget can never make the earliest reachable arrival later.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import StateVector
from spectre.astro.transfers import hohmann

_EPOCH = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


class _Circular:
    """A TLEOrbit stand-in on an exact equatorial circular orbit."""

    def __init__(self, radius_km: float, phase_deg: float) -> None:
        self._r = radius_km
        self._v = math.sqrt(MU_EARTH / radius_km)
        self._n = self._v / radius_km
        self._u0 = math.radians(phase_deg)

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._u0 + self._n * (epoch - _EPOCH).total_seconds()
        r = self._r * np.array([math.cos(u), math.sin(u), 0.0])
        v = self._v * np.array([-math.sin(u), math.cos(u), 0.0])
        return StateVector(epoch=epoch, r=r, v=v)


@pytest.fixture
def leo_pair(monkeypatch: pytest.MonkeyPatch) -> tuple[_Circular, _Circular]:
    red, blue = _Circular(7000.0, 0.0), _Circular(8000.0, 40.0)
    by_tle = {"RED": red, "BLUE": blue}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
    return red, blue


def _two_body(r0: np.ndarray, v0: np.ndarray, seconds: float) -> np.ndarray:
    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        a = -MU_EARTH * r / np.linalg.norm(r) ** 3
        return [*s[3:], *a]
    out = solve_ivp(f, (0.0, seconds), np.concatenate([r0, v0]), rtol=1e-11, atol=1e-9)
    return out.y[:3, -1]


def test_the_intercept_is_never_cheaper_than_hohmann(leo_pair: object) -> None:
    solution = maneuvers.min_time_intercept_wrapper("RED", "BLUE", _EPOCH, max_delta_v=3.0)
    assert solution.total_delta_v >= hohmann(7000.0, 8000.0).total_delta_v * (1.0 - 1e-6)
    assert solution.total_delta_v <= 3.0


def test_the_transfer_actually_reaches_the_target(leo_pair: tuple[_Circular, _Circular]) -> None:
    red, blue = leo_pair
    solution = maneuvers.min_time_intercept_wrapper("RED", "BLUE", _EPOCH, max_delta_v=3.0)
    tof = (solution.arrival_epoch - solution.departure_epoch).total_seconds()
    start = red.propagate(solution.departure_epoch)
    reached = _two_body(start.r, start.v + solution.burns[0].delta_v, tof)
    target = blue.propagate(solution.arrival_epoch).r
    assert float(np.linalg.norm(reached - target)) < 1.0


def test_more_budget_never_arrives_later(leo_pair: object) -> None:
    # With the target 40 deg ahead, 1.5 km/s first reaches it after about 52 min
    # and 3 km/s after about 37 min; immediate departure within one revolution.
    lean = maneuvers.min_time_intercept_wrapper("RED", "BLUE", _EPOCH, max_delta_v=1.5)
    rich = maneuvers.min_time_intercept_wrapper("RED", "BLUE", _EPOCH, max_delta_v=3.0)
    assert rich.arrival_epoch < lean.arrival_epoch - timedelta(minutes=5)


def test_a_budget_below_hohmann_is_refused_not_answered(leo_pair: object) -> None:
    with pytest.raises(ValueError, match="no single-revolution intercept"):
        maneuvers.min_time_intercept_wrapper("RED", "BLUE", _EPOCH, max_delta_v=0.2)
