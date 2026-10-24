"""Combined altitude and plane change: burn vectors match the ΔV priced.

Audit F-015. combined_altitude_plane_change prices a raising transfer with
the whole plane change on burn 2 (at the slower, higher point) and burn 1
prograde only, and the reverse for lowering. The intercept then gave burn 1 a
fixed 36.9 deg out-of-plane tilt (0.8 and 0.6) and burn 2 none, departing at
an arbitrary point that need not lie on either plane's line of nodes.

Checks used here, each independent of the code under test: the departure
state plus each burn is integrated numerically, and must end circular, at the
target radius, in the target plane; and the burn magnitudes must equal the
cosine-rule ΔV for the angle between the planes.
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
from spectre.astro.tactical import combined_altitude_plane_change

_EPOCH = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


class _Circular:
    """A TLEOrbit stand-in on an exact circular orbit."""

    def __init__(self, radius_km: float, inc_deg: float, raan_deg: float, phase_deg: float) -> None:
        i, o = math.radians(inc_deg), math.radians(raan_deg)
        self._r = radius_km
        self._v = math.sqrt(MU_EARTH / radius_km)
        self._n = self._v / radius_km
        self._node = np.array([math.cos(o), math.sin(o), 0.0])
        self.h_hat = np.array([math.sin(o) * math.sin(i), -math.cos(o) * math.sin(i), math.cos(i)])
        self._in_plane = np.cross(self.h_hat, self._node)
        self._u0 = math.radians(phase_deg)

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._u0 + self._n * (epoch - _EPOCH).total_seconds()
        r = self._r * (math.cos(u) * self._node + math.sin(u) * self._in_plane)
        v = self._v * (-math.sin(u) * self._node + math.cos(u) * self._in_plane)
        return StateVector(epoch=epoch, r=r, v=v)


def _integrate(r0: np.ndarray, v0: np.ndarray, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        return [*s[3:], *(-MU_EARTH * r / np.linalg.norm(r) ** 3)]
    out = solve_ivp(f, (0.0, seconds), np.concatenate([r0, v0]), rtol=1e-11, atol=1e-9)
    return out.y[:3, -1], out.y[3:, -1]


def _plan(monkeypatch: pytest.MonkeyPatch, r1: float, r2: float) -> tuple[_Circular, _Circular, maneuvers.InterceptSolution]:
    red, blue = _Circular(r1, 53.0, 0.0, 30.0), _Circular(r2, 53.0, 10.0, 75.0)
    by_tle = {"RED": red, "BLUE": blue}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
    return red, blue, maneuvers.plane_change_intercept("RED", "BLUE", _EPOCH)


@pytest.mark.parametrize(("r1", "r2"), [(7000.0, 8000.0), (8000.0, 7000.0)], ids=["raising", "lowering"])
def test_the_burns_end_circular_in_the_target_plane(monkeypatch: pytest.MonkeyPatch, r1: float, r2: float) -> None:
    red, blue, sol = _plan(monkeypatch, r1, r2)
    b1, b2 = sol.burns
    start = red.propagate(b1.epoch)
    r, v = _integrate(start.r, start.v + b1.delta_v, (b2.epoch - b1.epoch).total_seconds())
    v = v + b2.delta_v
    h_hat = np.cross(r, v) / np.linalg.norm(np.cross(r, v))
    assert float(np.linalg.norm(r)) == pytest.approx(r2, abs=1.0)
    assert float(np.linalg.norm(v)) == pytest.approx(math.sqrt(MU_EARTH / r2), abs=1e-4)
    assert math.degrees(math.acos(min(1.0, float(np.dot(h_hat, blue.h_hat))))) < 0.01


@pytest.mark.parametrize(("r1", "r2"), [(7000.0, 8000.0), (8000.0, 7000.0)], ids=["raising", "lowering"])
def test_the_burn_magnitudes_are_the_priced_ones(monkeypatch: pytest.MonkeyPatch, r1: float, r2: float) -> None:
    red, blue, sol = _plan(monkeypatch, r1, r2)
    angle = math.degrees(math.acos(float(np.dot(red.h_hat, blue.h_hat))))
    priced = combined_altitude_plane_change(r1, r2, angle)
    assert sol.burns[0].delta_v_mag == pytest.approx(priced.delta_v_1, abs=1e-6)
    assert sol.burns[1].delta_v_mag == pytest.approx(priced.delta_v_2, abs=1e-6)
    assert sol.total_delta_v == pytest.approx(priced.total_delta_v, abs=1e-6)


def test_a_raising_first_burn_stays_in_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, sol = _plan(monkeypatch, 7000.0, 8000.0)
    assert sol.burns[0].dv_normal == pytest.approx(0.0, abs=1e-9)
    assert sol.burns[0].dv_prograde > 0.0


def test_a_lowering_second_burn_stays_in_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, sol = _plan(monkeypatch, 8000.0, 7000.0)
    assert sol.burns[1].dv_normal == pytest.approx(0.0, abs=1e-9)
    assert sol.burns[1].dv_prograde < 0.0
