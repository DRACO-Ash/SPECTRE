"""Formation slot displacement is the furthest the burn carries the asset.

Audit F-078. A radial impulse dv drives a radial swing of dv/n and an
along-track excursion of up to 4 dv/n half an orbit later, so reporting
dv/n understated the slot displacement up to four times. Checked against
the Clohessy-Wiltshire solution flown over one orbit.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate
from spectre.astro.tactical import _slot_displacement_km, formation_defence_burn

_R = 7000.0
_N = math.sqrt(MU_EARTH / _R**3)


def _flown(strategy: str, dv: float) -> float:
    xd, yd, zd = {"radial": (dv, 0, 0), "along_track": (0, dv, 0), "out_of_plane": (0, 0, dv)}[strategy]
    state = CWState(0.0, 0.0, 0.0, xd, yd, zd)
    period = 2.0 * math.pi / _N
    return max(
        math.sqrt(p.x**2 + p.y**2 + p.z**2)
        for p in (_cw_propagate(state, _N, period * k / 20_000) for k in range(20_001))
    )


@pytest.mark.parametrize("strategy", ["radial", "along_track", "out_of_plane"])
def test_the_displacement_is_the_largest_distance_flown(strategy: str) -> None:
    assert _slot_displacement_km(strategy, 0.001, _N) == pytest.approx(_flown(strategy, 0.001), rel=1e-6)


def test_a_radial_burn_reaches_four_times_dv_over_n() -> None:
    # Along-track excursion 4 dv / n at the half orbit, against the dv / n reported.
    assert _slot_displacement_km("radial", 0.001, _N) == pytest.approx(4 * 0.001 / _N, rel=1e-6)


def test_the_result_reports_that_displacement() -> None:
    result = formation_defence_burn(_R, 3600.0, 5.0)
    assert result.formation_impact_km == pytest.approx(
        _slot_displacement_km(result.burn_direction, result.delta_v, _N), rel=1e-12,
    )
