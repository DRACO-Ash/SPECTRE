"""Phase angle between an interceptor and its target (SPC-004, red team finding 3).

Hand cases: circular orbits with the angle placed by construction, so the
expected value comes from the set-up, not from the code under test.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spectre.astro.phase_angle import phase_angle_deg

_R_GEO = 42_164.0
_V_GEO = 3.0747


def _on_circle(angle_deg: float, radius: float = _R_GEO, z: float = 0.0) -> np.ndarray:
    a = math.radians(angle_deg)
    return np.array([radius * math.cos(a), radius * math.sin(a), z])


_CHASER_R = _on_circle(0.0)
# Moving anticlockwise seen from +z: the direction of increasing angle.
_CHASER_V = np.array([0.0, _V_GEO, 0.0])


@pytest.mark.parametrize("placed", [30.0, -30.0, 90.0, -135.0, 1.0, 179.0])
def test_the_angle_placed_is_the_angle_measured(placed: float) -> None:
    assert phase_angle_deg(_CHASER_R, _CHASER_V, _on_circle(placed)) == pytest.approx(placed, abs=1e-9)


def test_ahead_is_positive_in_the_direction_of_motion() -> None:
    retrograde = -_CHASER_V
    assert phase_angle_deg(_CHASER_R, retrograde, _on_circle(30.0)) == pytest.approx(-30.0, abs=1e-9)


def test_directly_opposite_reads_half_a_turn() -> None:
    # Ahead or behind by half a turn is the same place; only the size is pinned.
    assert abs(phase_angle_deg(_CHASER_R, _CHASER_V, _on_circle(180.0))) == pytest.approx(180.0, abs=1e-9)


def test_an_out_of_plane_offset_does_not_change_the_phase() -> None:
    # A target 500 km above the chaser's plane at the same in-plane position.
    assert phase_angle_deg(_CHASER_R, _CHASER_V, _on_circle(45.0, z=500.0)) == pytest.approx(45.0, abs=1e-9)


def test_a_different_radius_does_not_change_the_phase() -> None:
    assert phase_angle_deg(_CHASER_R, _CHASER_V, _on_circle(-20.0, radius=7_000.0)) == pytest.approx(-20.0, abs=1e-9)


def test_an_undefined_plane_is_refused() -> None:
    with pytest.raises(ValueError, match="plane is undefined"):
        phase_angle_deg(_CHASER_R, np.zeros(3), _on_circle(10.0))


def test_a_target_on_the_normal_is_refused() -> None:
    with pytest.raises(ValueError, match="orbit normal"):
        phase_angle_deg(_CHASER_R, _CHASER_V, np.array([0.0, 0.0, _R_GEO]))
