"""The NMC burn shown is the burn that flies the safety ellipse.

Audit F-017. nmc_safety_ellipse was corrected to price an along-track burn
of 2nA from a radial offset of A, because a radial burn from a co-located
state passes through the target once per orbit. nmc_intercept still built
that radial burn, from wherever red happened to be, and labelled it with the
corrected cost and a positive safety margin.

Checks used here are independent of the wrapper: its burn is applied to red's
relative state and flown through the closed-form Clohessy-Wiltshire solution,
and the closest approach over the orbit is compared with the margin reported.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from spectre.astro import cw_geometry, maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate, _eci_to_hill_matrix
from spectre.astro.propagator import StateVector

_EPOCH = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
_R = 7000.0
_N = math.sqrt(MU_EARTH / _R**3)


class _Circular:
    """A TLEOrbit stand-in on an equatorial circular orbit."""

    def __init__(self, radius_km: float, phase_rad: float) -> None:
        self._r = radius_km
        self._v = math.sqrt(MU_EARTH / radius_km)
        self._n = self._v / radius_km
        self._u0 = phase_rad

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._u0 + self._n * (epoch - _EPOCH).total_seconds()
        r = self._r * np.array([math.cos(u), math.sin(u), 0.0])
        v = self._v * np.array([-math.sin(u), math.cos(u), 0.0])
        return StateVector(epoch=epoch, r=r, v=v)


def _with(monkeypatch: pytest.MonkeyPatch, red: _Circular) -> tuple[_Circular, _Circular]:
    blue = _Circular(_R, 0.0)
    by_tle = {"RED": red, "BLUE": blue}
    for module in (maneuvers, cw_geometry):
        monkeypatch.setattr(module, "TLEOrbit", lambda tle: by_tle[tle])
    return red, blue


def _flown_min_range(sol: maneuvers.InterceptSolution) -> tuple[float, float]:
    """Closest approach over one orbit, and the drift after it, from the wrapper's burn."""
    state, n, _, _ = cw_geometry._initial_hill_state("RED", "BLUE", sol.departure_epoch)
    blue = cw_geometry.TLEOrbit("BLUE").propagate(sol.departure_epoch)
    dv_hill = _eci_to_hill_matrix(blue.r, blue.v) @ sol.burns[0].delta_v
    after = CWState(state.x, state.y, state.z, state.xd + dv_hill[0], state.yd + dv_hill[1], state.zd + dv_hill[2])
    period = 2.0 * math.pi / n
    ranges = [
        math.sqrt(p.x**2 + p.y**2 + p.z**2)
        for p in (_cw_propagate(after, n, period * k / 2000) for k in range(2000))
    ]
    end = _cw_propagate(after, n, period)
    return min(ranges), math.hypot(end.x - after.x, end.y - after.y)


def test_from_a_radial_offset_the_burn_is_along_track_and_the_margin_is_flown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red 1 km above blue: the 2 km along-track ellipse centred on blue
    # passes through it, so this is the insertion point the method assumes.
    _with(monkeypatch, _Circular(_R + 1.0, 0.0))
    sol = maneuvers.nmc_intercept("RED", "BLUE", _EPOCH, along_track_km=2.0)
    burn = sol.burns[0]
    assert abs(burn.dv_radial) < 1e-9
    assert abs(burn.dv_prograde) > 0.0
    closest, drift = _flown_min_range(sol)
    assert drift < 1e-6, "the relative orbit must be bounded"
    assert sol.miss_distance_km == pytest.approx(closest, rel=1e-3)
    assert closest == pytest.approx(1.0, rel=1e-2)


def test_a_co_located_interceptor_is_refused_not_certified(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _Circular(_R, 0.0))
    with pytest.raises(ValueError, match="ellipse"):
        maneuvers.nmc_intercept("RED", "BLUE", _EPOCH, along_track_km=2.0)


def test_an_interceptor_far_from_the_requested_ellipse_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _Circular(_R, 50.0 / _R))  # 50 km along track
    with pytest.raises(ValueError, match="50"):
        maneuvers.nmc_intercept("RED", "BLUE", _EPOCH, along_track_km=2.0)


def test_cross_track_amplitude_is_flown(monkeypatch: pytest.MonkeyPatch) -> None:
    _with(monkeypatch, _Circular(_R + 1.0, 0.0))
    sol = maneuvers.nmc_intercept("RED", "BLUE", _EPOCH, along_track_km=2.0, cross_track_km=0.5)
    closest, _ = _flown_min_range(sol)
    assert sol.miss_distance_km == pytest.approx(closest, rel=1e-3)
    assert sol.total_delta_v == pytest.approx(float(np.linalg.norm(sol.burns[0].delta_v)), rel=1e-12)
