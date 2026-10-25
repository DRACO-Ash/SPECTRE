"""A RAAN change is priced on the angle between the two planes.

Audit F-073. classify_manoeuvre priced a RAAN residual dOmega as if the
planes were dOmega apart. Two planes at inclination i differing only in RAAN
are theta apart with cos theta = cos^2 i + sin^2 i cos dOmega (spherical
trigonometry), about sin i x dOmega, so the cost was overstated by 1/sin i:
1.28 times at 51.6 deg, without bound towards equatorial.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import MU_EARTH
from spectre.astro.tactical import classify_manoeuvre, j2_raan_rate

_A = 7000.0


@pytest.mark.parametrize("inc", [51.6, 10.0])
def test_a_raan_only_change_costs_the_plane_angle(inc: float) -> None:
    dt_s = 1.0  # one second, so the J2 drift removed is negligible but exact
    # Signed: the observed +1 deg less the (negative) J2 drift (audit F-023).
    residual = abs(1.0 - j2_raan_rate(_A, 0.0, inc) * dt_s / 86400.0)
    i, d = math.radians(inc), math.radians(residual)
    theta = math.acos(math.cos(i) ** 2 + math.sin(i) ** 2 * math.cos(d))
    expected = 2.0 * math.sqrt(MU_EARTH / _A) * math.sin(theta / 2.0)

    result = classify_manoeuvre(_A, 0.0, inc, 100.0, _A, 0.0, inc, 101.0, dt_s)
    assert result.estimated_delta_v == pytest.approx(expected, rel=1e-6)
