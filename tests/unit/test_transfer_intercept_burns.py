"""Hohmann and bi-elliptic intercepts: burn signs and the reported miss.

Audit F-011, F-012 and F-013. hohmann_intercept reported a miss of 0 km
whatever the phasing, and emitted both burns prograde for a lowering transfer.
bielliptic_intercept pointed burn 2 along the departure velocity, which half
an ellipse later is antiparallel to the actual velocity, and burn 3 prograde
where circularising at the perigee of the second ellipse needs a retrograde
burn.

Checks used here, each independent of the code under test:
● a numerical two-body integration (scipy) of the departure state plus each
  burn gives the arrival state;
● the Hohmann lead angle, 180 deg minus the target's motion over the transfer
  time, phases the target so that the miss is zero;
● raising needs prograde burns and lowering retrograde ones.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.kepler import propagate_two_body
from spectre.astro.propagator import StateVector

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


def _pair(monkeypatch: pytest.MonkeyPatch, red: _Circular, blue: _Circular) -> tuple[_Circular, _Circular]:
    by_tle = {"RED": red, "BLUE": blue}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
    return red, blue


def _integrate(r0: np.ndarray, v0: np.ndarray, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        return [*s[3:], *(-MU_EARTH * r / np.linalg.norm(r) ** 3)]
    out = solve_ivp(f, (0.0, seconds), np.concatenate([r0, v0]), rtol=1e-11, atol=1e-9)
    return out.y[:3, -1], out.y[3:, -1]


def _hohmann_half_period(r1: float, r2: float) -> float:
    return math.pi * math.sqrt(((r1 + r2) / 2.0) ** 3 / MU_EARTH)


class TestTwoBodyPropagator:
    @pytest.mark.parametrize("dt", [600.0, 5000.0, 86_400.0])
    def test_it_matches_numerical_integration(self, dt: float) -> None:
        r0 = np.array([7000.0, 500.0, 1200.0])
        v0 = np.array([-0.8, 7.3, 1.1])
        r, v = propagate_two_body(r0, v0, dt)
        r_ref, v_ref = _integrate(r0, v0, dt)
        assert float(np.linalg.norm(r - r_ref)) < 1e-3
        assert float(np.linalg.norm(v - v_ref)) < 1e-6

    def test_a_hyperbolic_arc_matches_too(self) -> None:
        r0 = np.array([7000.0, 0.0, 0.0])
        v0 = np.array([0.0, 12.0, 0.0])
        r, _ = propagate_two_body(r0, v0, 3600.0)
        r_ref, _ = _integrate(r0, v0, 3600.0)
        assert float(np.linalg.norm(r - r_ref)) < 1e-3


class TestHohmannIntercept:
    def test_the_miss_is_the_propagated_separation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        red, blue = _pair(monkeypatch, _Circular(7000.0, 0.0), _Circular(8000.0, 40.0))
        sol = maneuvers.hohmann_intercept("RED", "BLUE", _EPOCH)
        start = red.propagate(sol.departure_epoch)
        tof = (sol.arrival_epoch - sol.departure_epoch).total_seconds()
        reached, _ = _integrate(start.r, start.v + sol.burns[0].delta_v, tof)
        expected = float(np.linalg.norm(reached - blue.propagate(sol.arrival_epoch).r))
        assert expected > 1000.0, "the test pair must be mis-phased"
        assert sol.miss_distance_km == pytest.approx(expected, abs=1.0)

    def test_a_target_at_the_lead_angle_is_met(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r1, r2 = 7000.0, 8000.0
        n2 = math.sqrt(MU_EARTH / r2 ** 3)
        lead_deg = 180.0 - math.degrees(n2 * _hohmann_half_period(r1, r2))
        _pair(monkeypatch, _Circular(r1, 0.0), _Circular(r2, lead_deg))
        sol = maneuvers.hohmann_intercept("RED", "BLUE", _EPOCH)
        assert sol.miss_distance_km < 1.0

    def test_raising_burns_are_prograde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _pair(monkeypatch, _Circular(7000.0, 0.0), _Circular(8000.0, 40.0))
        sol = maneuvers.hohmann_intercept("RED", "BLUE", _EPOCH)
        assert sol.burns[0].dv_prograde > 0.0
        assert sol.burns[1].dv_prograde > 0.0

    def test_lowering_burns_are_retrograde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _pair(monkeypatch, _Circular(8000.0, 0.0), _Circular(7000.0, 40.0))
        sol = maneuvers.hohmann_intercept("RED", "BLUE", _EPOCH)
        assert sol.burns[0].dv_prograde < 0.0
        assert sol.burns[1].dv_prograde < 0.0

    def test_the_second_burn_circularises_at_the_target_radius(self, monkeypatch: pytest.MonkeyPatch) -> None:
        red, _ = _pair(monkeypatch, _Circular(8000.0, 0.0), _Circular(7000.0, 40.0))
        sol = maneuvers.hohmann_intercept("RED", "BLUE", _EPOCH)
        start = red.propagate(sol.departure_epoch)
        tof = (sol.arrival_epoch - sol.departure_epoch).total_seconds()
        r, v = _integrate(start.r, start.v + sol.burns[0].delta_v, tof)
        v_after = v + sol.burns[1].delta_v
        assert float(np.linalg.norm(v_after)) == pytest.approx(math.sqrt(MU_EARTH / 7000.0), abs=1e-5)
        assert abs(float(np.dot(r, v_after))) < 1e-3 * float(np.linalg.norm(r))


class TestBiellipticIntercept:
    def _run(self, monkeypatch: pytest.MonkeyPatch, r1: float, r2: float) -> tuple[_Circular, maneuvers.InterceptSolution]:
        red, _ = _pair(monkeypatch, _Circular(r1, 0.0), _Circular(r2, 40.0))
        return red, maneuvers.bielliptic_intercept("RED", "BLUE", _EPOCH, rb_km=3.0 * max(r1, r2))

    def test_raising_signs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, sol = self._run(monkeypatch, 7000.0, 9000.0)
        assert sol.burns[0].dv_prograde > 0.0
        assert sol.burns[1].dv_prograde > 0.0
        assert sol.burns[2].dv_prograde < 0.0

    def test_lowering_signs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, sol = self._run(monkeypatch, 9000.0, 7000.0)
        assert sol.burns[0].dv_prograde > 0.0
        assert sol.burns[1].dv_prograde < 0.0
        assert sol.burns[2].dv_prograde < 0.0

    def test_the_three_burns_end_on_the_target_circle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        red, sol = self._run(monkeypatch, 7000.0, 9000.0)
        b1, b2, b3 = sol.burns
        start = red.propagate(sol.departure_epoch)
        r, v = _integrate(start.r, start.v + b1.delta_v, (b2.epoch - b1.epoch).total_seconds())
        r, v = _integrate(r, v + b2.delta_v, (b3.epoch - b2.epoch).total_seconds())
        v_after = v + b3.delta_v
        assert float(np.linalg.norm(r)) == pytest.approx(9000.0, abs=1.0)
        assert float(np.linalg.norm(v_after)) == pytest.approx(math.sqrt(MU_EARTH / 9000.0), abs=1e-5)

    def test_the_miss_is_the_propagated_separation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        red, sol = self._run(monkeypatch, 7000.0, 9000.0)
        b1, b2, b3 = sol.burns
        start = red.propagate(sol.departure_epoch)
        r, v = _integrate(start.r, start.v + b1.delta_v, (b2.epoch - b1.epoch).total_seconds())
        r, _ = _integrate(r, v + b2.delta_v, (b3.epoch - b2.epoch).total_seconds())
        blue = _Circular(9000.0, 40.0).propagate(sol.arrival_epoch)
        assert sol.miss_distance_km == pytest.approx(float(np.linalg.norm(r - blue.r)), abs=1.0)
        assert sol.arrival_epoch - sol.departure_epoch > timedelta(hours=1)
