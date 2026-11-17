"""Evasion is planned against the threat, not against a generic orbit.

Audit F-014: evasion_intercept never read red_tle, so the "optimal" burn and
its resulting miss came from the defended satellite's radius alone. Two
different threats produced the same answer.

The check here is independent of the code under test: the defended satellite
is moved by the burn under numerically integrated two-body motion, and the
miss is its closest approach to the threat within ten minutes of the assumed
time of closest approach (TCA), found by scipy's bounded minimiser. It was the
separation at the assumed TCA instant, which the burn moves, so in crossing
geometry it overstated the miss (0.47.0 review, B2).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar

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


def _closest(separation: object, centre_s: float) -> float:
    """The smallest of *separation* within 600 s of *centre_s*: a 1 s grid, then the bounded minimiser."""
    grid = np.arange(centre_s - 600.0, centre_s + 600.5, 1.0)
    k = int(np.argmin([separation(t) for t in grid]))  # type: ignore[operator]
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    return float(minimize_scalar(separation, bounds=(lo, hi), method="bounded", options={"xatol": 1e-7}).fun)


def _achieved_miss(sol: maneuvers.InterceptSolution, red: _Circular) -> float:
    burn = sol.burns[0]
    start = _BLUE.propagate(burn.epoch)
    to_tca = (sol.arrival_epoch - burn.epoch).total_seconds()

    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        return [*s[3:], *(-MU_EARTH * r / np.linalg.norm(r) ** 3)]

    flown = solve_ivp(f, (0.0, to_tca + 600.0), np.concatenate([start.r, start.v + burn.delta_v]),
                      dense_output=True, rtol=1e-12, atol=1e-10).sol

    def separation(t: float) -> float:
        return float(np.linalg.norm(flown(t)[:3] - red.propagate(burn.epoch + timedelta(seconds=t)).r))

    return _closest(separation, to_tca)


def _unmanoeuvred_miss(red: _Circular) -> float:
    def separation(t: float) -> float:
        when = _TCA + timedelta(seconds=t)
        return float(np.linalg.norm(_BLUE.propagate(when).r - red.propagate(when).r))

    return _closest(separation, 0.0)


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
    # The threat crosses 6 km along its own track from the node, so the closest approach is under the 6 km
    # separation at the TCA instant, which is what was reported.
    assert sol.miss_distance_km == pytest.approx(_unmanoeuvred_miss(_OFFSET), abs=0.01)
    assert sol.miss_distance_km < 6.0 - 0.1
