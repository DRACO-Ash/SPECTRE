"""The stability analyser's radial amplitude is the largest radial distance flown.

Audit F-071. The code took sqrt(x0^2 + (xdot0/n)^2), ignoring the along-track
velocity and the factor 3 in the Clohessy-Wiltshire solution
x(t) = (4 - 3 cos nt) x0 + (sin nt) xdot0 / n + 2 (1 - cos nt) ydot0 / n.
From x0 = 0 with an along-track velocity v the radial distance reaches 4v/n;
the code reported 0. Checked here against that solution sampled densely.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate
from spectre.astro.tactical import relative_motion_stability

_R = 7000.0
_N = math.sqrt(MU_EARTH / _R**3)


def _max_abs_x(x0: float, xd0: float, yd0: float) -> float:
    state = CWState(x0, 0.0, 0.0, xd0, yd0, 0.0)
    period = 2.0 * math.pi / _N
    return max(abs(_cw_propagate(state, _N, period * k / 20_000).x) for k in range(20_001))


@pytest.mark.parametrize(
    ("x0", "xd0", "yd0"),
    [(0.0, 0.0, 0.001), (1.0, 0.0, -2.0 * _N * 1.0), (1.0, 0.0005, 0.0), (-2.0, 0.001, 0.0004)],
    ids=["along-track-only", "bounded", "radial-velocity", "mixed"],
)
def test_the_radial_amplitude_is_the_largest_radial_distance(x0: float, xd0: float, yd0: float) -> None:
    result = relative_motion_stability(_R, x0, 0.0, 0.0, xd0, yd0, 0.0)
    assert result.radial_amplitude_km == pytest.approx(_max_abs_x(x0, xd0, yd0), rel=1e-6)


def test_an_along_track_kick_from_the_origin_reaches_four_v_over_n() -> None:
    v = 0.001
    assert relative_motion_stability(_R, 0.0, 0.0, 0.0, 0.0, v, 0.0).radial_amplitude_km == pytest.approx(4 * v / _N)
