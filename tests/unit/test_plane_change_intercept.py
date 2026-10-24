"""Plane-change intercept pinned to the angle between the two orbit planes.

The angle between two planes is acos(h1 . h2), which for equal inclinations i
and a node offset dO is acos(cos^2 i + sin^2 i cos dO) (Vallado, Fundamentals of
Astrodynamics and Applications, section 6.4; Curtis section 6.10). The routine
used the inclination difference alone, so two 53 degree planes 10 degrees apart
in RAAN cost nothing (audit F-002). A pure plane change at the line of nodes
costs 2 v sin(theta / 2) on a circular orbit.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from spectre.astro import maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.propagator import StateVector

_R = 7000.0
_V = math.sqrt(MU_EARTH / _R)
_N = _V / _R
_EPOCH = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)


class _CircularOrbit:
    """A TLEOrbit stand-in flying an exact circular two-body orbit."""

    def __init__(self, inc_deg: float, raan_deg: float, phase_deg: float) -> None:
        i, o = math.radians(inc_deg), math.radians(raan_deg)
        self._node = np.array([math.cos(o), math.sin(o), 0.0])
        self._h_hat = np.array([math.sin(o) * math.sin(i), -math.cos(o) * math.sin(i), math.cos(i)])
        self._in_plane = np.cross(self._h_hat, self._node)
        self._phase = math.radians(phase_deg)

    def propagate(self, epoch: datetime) -> StateVector:
        u = self._phase + _N * (epoch - _EPOCH).total_seconds()
        r = _R * (math.cos(u) * self._node + math.sin(u) * self._in_plane)
        v = _V * (-math.sin(u) * self._node + math.cos(u) * self._in_plane)
        return StateVector(epoch=epoch, r=r, v=v)

    @property
    def h_hat(self) -> np.ndarray:
        return self._h_hat


@pytest.fixture
def walker_pair(monkeypatch: pytest.MonkeyPatch) -> tuple[_CircularOrbit, _CircularOrbit]:
    red = _CircularOrbit(53.0, 0.0, 30.0)
    blue = _CircularOrbit(53.0, 10.0, 75.0)
    by_tle = {"RED": red, "BLUE": blue}
    monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])
    return red, blue


def _plane_angle_rad(i_deg: float, d_raan_deg: float) -> float:
    i, d = math.radians(i_deg), math.radians(d_raan_deg)
    return math.acos(math.cos(i) ** 2 + math.sin(i) ** 2 * math.cos(d))


def test_planes_apart_in_raan_are_not_free_to_align(walker_pair: object) -> None:
    solution = maneuvers.plane_change_intercept("RED", "BLUE", _EPOCH)
    expected = 2.0 * _V * math.sin(_plane_angle_rad(53.0, 10.0) / 2.0)
    assert solution.total_delta_v == pytest.approx(expected, rel=0.01), (
        f"{solution.total_delta_v:.4f} km/s for planes 8 deg apart; {expected:.4f} km/s expected"
    )


def test_the_burn_is_at_the_line_of_nodes_and_lands_in_the_blue_plane(
    walker_pair: tuple[_CircularOrbit, _CircularOrbit],
) -> None:
    red, blue = walker_pair
    solution = maneuvers.plane_change_intercept("RED", "BLUE", _EPOCH)
    burn = solution.burns[0]
    assert burn.epoch >= _EPOCH
    assert burn.epoch - _EPOCH <= timedelta(seconds=2.0 * math.pi / _N)

    at_burn = red.propagate(burn.epoch)
    assert abs(float(np.dot(at_burn.r, blue.h_hat))) < 1.0, "the burn is not on the blue plane"

    h_after = np.cross(at_burn.r, at_burn.v + burn.delta_v)
    misalignment = math.degrees(math.acos(min(1.0, float(np.dot(h_after / np.linalg.norm(h_after), blue.h_hat)))))
    assert misalignment < 0.01, f"after the burn the orbit is still {misalignment:.3f} deg out of the blue plane"
