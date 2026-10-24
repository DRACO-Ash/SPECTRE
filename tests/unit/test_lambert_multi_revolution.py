"""Lambert transfers longer than one revolution.

Audit F-010. The module docstring said multi-revolution transfers were
"rejected explicitly". They were not: the time of flight diverges as z
approaches 4 pi^2, so the guard never fired, and a 30 deg hop along GEO in
24 h came back as a single-revolution arc costing 7,820 m/s over its two
burns, where flying once round costs about 214 m/s. intercept_envelope_intercept
sweeps to 48 h by default, so most of its sweep was priced this way.

Each solution is checked by propagating the departure state for the time of
flight with numerical integration, independent of the solver.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro.constants import MU_EARTH
from spectre.astro.lambert import cheapest_lambert, solve_lambert, solve_lambert_all

_R = 42_164.0
_V = math.sqrt(MU_EARTH / _R)


def _geo(deg: float) -> tuple[np.ndarray, np.ndarray]:
    t = math.radians(deg)
    return _R * np.array([math.cos(t), math.sin(t), 0.0]), _V * np.array([-math.sin(t), math.cos(t), 0.0])


def _reach(r0: np.ndarray, v0: np.ndarray, seconds: float) -> np.ndarray:
    def f(_t: float, s: np.ndarray) -> list[float]:
        r = s[:3]
        return [*s[3:], *(-MU_EARTH * r / np.linalg.norm(r) ** 3)]
    return solve_ivp(f, (0.0, seconds), np.concatenate([r0, v0]), rtol=1e-11, atol=1e-9).y[:3, -1]


@pytest.mark.parametrize(("deg", "hours"), [(30.0, 24.0), (30.0, 48.0), (200.0, 36.0), (100.0, 60.0)])
def test_every_solution_reaches_the_target(deg: float, hours: float) -> None:
    r1, v1 = _geo(0.0)
    r2, v2 = _geo(deg)
    tof = hours * 3600.0
    solutions = solve_lambert_all(r1, r2, tof, v1_initial=v1, v2_target=v2)
    assert any(s.revolutions > 0 for s in solutions)
    for s in solutions:
        assert float(np.linalg.norm(_reach(r1, s.v1, tof) - r2)) < 0.01, f"N={s.revolutions}"


def test_a_long_geo_hop_is_priced_on_the_cheap_revolution() -> None:
    r1, v1 = _geo(0.0)
    r2, v2 = _geo(30.0)
    best = cheapest_lambert(r1, r2, 86_400.0, v1_initial=v1, v2_target=v2)
    single = solve_lambert(r1, r2, 86_400.0, v1_initial=v1, v2_target=v2)
    assert best.revolutions == 1
    assert best.total_delta_v < 0.25
    assert single.total_delta_v > 7.0, "the single-revolution arc is still available, and still dear"


def test_a_short_flight_has_only_the_single_revolution_answer() -> None:
    r1, v1 = _geo(0.0)
    r2, v2 = _geo(30.0)
    solutions = solve_lambert_all(r1, r2, 4 * 3600.0, v1_initial=v1, v2_target=v2)
    assert [s.revolutions for s in solutions] == [0]


def test_the_module_no_longer_claims_to_reject_multiple_revolutions() -> None:
    from spectre.astro import lambert

    assert "rejected explicitly" not in (lambert.__doc__ or "")


def test_a_root_beside_the_band_edge_is_found() -> None:
    """A near-circular drift once round with a small transfer angle.

    Two degrees along GEO in 24 h, flown once round, has z just above
    (2 pi)^2, nearer the band edge than the first point of the bracketing
    grid. The first version of the search stepped over it and priced the hop
    at 2.2 km/s on two revolutions; once round costs 5.8 m/s.
    """
    r1, v1 = _geo(0.0)
    r2, v2 = _geo(2.0)
    best = cheapest_lambert(r1, r2, 86_400.0, v1_initial=v1, v2_target=v2)
    assert best.revolutions == 1
    assert best.total_delta_v < 0.010
    assert float(np.linalg.norm(_reach(r1, best.v1, 86_400.0) - r2)) < 0.01
