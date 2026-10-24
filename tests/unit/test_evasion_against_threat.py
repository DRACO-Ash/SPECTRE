"""Evasion is planned against the threat, not against a generic orbit.

Audit F-014: evasion_intercept never read red_tle, so the "optimal" burn and
its resulting miss came from the defended satellite's radius alone. Two
different threats produced the same answer.

The check here is independent of the code under test: the defended satellite
is moved by the burn under numerically integrated two-body motion, and the
miss is its distance from the threat at the time of closest approach (TCA).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import StateVector

_TCA = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


class _Circular:
    """A TLEOrbit stand-in on a circular orbit with its node on the x axis."""

    def __init__(self, radius_km: float, inc_deg: float, phase_deg: float) -> None:
        self._r = radius_km
        self._v = math.sqrt(MU_EARTH / radius_km)
        self._n = self._v / radius_km
        self._u0 = math.radians(phase_deg)
        i = math.radians(inc_deg)
        self._p = np.array([1.0, 0.0, 0.0])
        self._q = np.array([0.0, math.cos(i), math.sin(i)])

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._u0 + self._n * (epoch - _TCA).total_seconds()
        r = self._r * (math.cos(u) * self._p + math.sin(u) * self._q)
        v = self._v * (-math.sin(u) * self._p + math.cos(u) * self._q)
        return StateVector(epoch=epoch, r=r, v=v)


_BLUE = _Circular(7000.0, 0.0, 0.0)


def _with(monkeypatch: pytest.MonkeyPatch, red: _Circular) -> None:
    by_tle = {"RED": red, "BLUE": _BLUE}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])


def _integrate(r0: np.ndarray, v0: np.ndarray, seconds: float) -> np.ndarray:
    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        return [*s[3:], *(-MU_EARTH * r / np.linalg.norm(r) ** 3)]
    return solve_ivp(f, (0.0, seconds), np.concatenate([r0, v0]), rtol=1e-11, atol=1e-9).y[:3, -1]


def _achieved_miss(sol: maneuvers.InterceptSolution, red: _Circular) -> float:
    burn = sol.burns[0]
    start = _BLUE.propagate(burn.epoch)
    coast = (sol.arrival_epoch - burn.epoch).total_seconds()
    moved = _integrate(start.r, start.v + burn.delta_v, coast)
    return float(np.linalg.norm(moved - red.propagate(sol.arrival_epoch).r))


# An inclined threat that meets the defended satellite at the node at TCA,
# and the same threat arriving 6 km further along its track.
_HEAD_ON = _Circular(7000.0, 60.0, 0.0)
_OFFSET = _Circular(7000.0, 60.0, math.degrees(6.0 / 7000.0))


@pytest.mark.parametrize("red", [_HEAD_ON, _OFFSET], ids=["head-on", "offset"])
def test_the_reported_miss_is_the_achieved_separation_from_the_threat(
    monkeypatch: pytest.MonkeyPatch, red: _Circular,
) -> None:
    _with(monkeypatch, red)
    sol = maneuvers.evasion_intercept("RED", "BLUE", _TCA, desired_miss_km=10.0, fuel_budget_km_s=0.5)
    assert sol.miss_distance_km == pytest.approx(_achieved_miss(sol, red), abs=0.05)


def test_the_desired_miss_is_met_when_the_budget_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _OFFSET)
    sol = maneuvers.evasion_intercept("RED", "BLUE", _TCA, desired_miss_km=10.0, fuel_budget_km_s=0.5)
    assert _achieved_miss(sol, _OFFSET) >= 10.0 - 0.05


def test_two_threats_give_two_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _HEAD_ON)
    a = maneuvers.evasion_intercept("RED", "BLUE", _TCA, desired_miss_km=10.0, fuel_budget_km_s=0.5)
    _with(monkeypatch, _OFFSET)
    b = maneuvers.evasion_intercept("RED", "BLUE", _TCA, desired_miss_km=10.0, fuel_budget_km_s=0.5)
    assert (a.miss_distance_km, a.total_delta_v) != pytest.approx((b.miss_distance_km, b.total_delta_v), abs=1e-3)


def test_no_warning_time_reports_the_unmanoeuvred_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _OFFSET)
    sol = maneuvers.evasion_intercept("RED", "BLUE", _TCA, time_before_tca_s=0.0)
    assert sol.total_delta_v == 0.0
    assert sol.miss_distance_km == pytest.approx(6.0, abs=0.01)
