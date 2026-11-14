"""SGP4's WGS-72 states flown by RK45 with WGS-84 constants: the handover measured and stated (SPC-225, F-36).

SGP4 runs on the WGS-72 constants its element sets are fitted with; every RK45 arc the engine integrates starts from
an SGP4 state and flies it with spectre.astro.constants' WGS-84 mu and radius and EGM-96 J2, and nothing said so.
This measures what that handover moves: each object of the three reference pairs INTEGRATOR_ERROR_KM is measured on
(tests/unit/_decision_reference.py, at the cases' epoch, B* 1e-4) is flown by the engine's own RK45 (rk45_arc) from
its SGP4 state twice, with the engine's constants and with SGP4's WGS-72 ones (monte_carlo.SGP4_WGS72, which this
checks against the sgp4 package's own model), and the positions and the pair's separation are compared every 60 s.

Measured at this commit (scipy 1.17.1, sgp4 2.27), the largest up to each horizon:

● position, LEO: 1.167 km by 24 h, 2.336 km by 48 h, 3.516 km by 72 h (the 500 km and the 550 km polar pairs agree
  to 0.02 km): about 1.2 km a day along track;
● position, GEO: 0.476 km by 24 h, 0.952 km by 48 h, 1.428 km by 72 h;
● separation: 0.058 km by 24 h, 0.117 km by 48 h, 0.176 km by 72 h (the 550 km polar pair, whose orbits cross; the
  co-planar 500 km pair 0.006 km and GEO 0.002 km by 72 h).

Both objects drift alike, so the separation a closest approach reads moves at most 0.18 km by 72 h: of the size of
the integrator's own separation error (0.02, 0.11 and 0.38 km by 24, 48 and 72 h, INTEGRATOR_ERROR_KM) and under a
fifth of the smallest element-set error each sample draws (1 km for a LEO set at its epoch, plus 2 km a day). It is
not material, so the constants are not changed; the handover is stated in the sampled basis note and beside RK45
computed cells. WGS_HANDOVER_KM states each figure,
rounded up to 0.01 km; this holds each at or above what is measured and no more than 0.01 km above it.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np
import pytest
from sgp4.earth_gravity import wgs72

from spectre.astro import monte_carlo
from spectre.astro.along_track import position_error_km
from spectre.astro.monte_carlo import SGP4_WGS72, WGS_HANDOVER_KM, handover_words
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE, ReferenceCase

_HOUR_S = 3600.0
_BSTAR = 1e-4
_STEP_S = 60.0
_HORIZONS = (24, 48, 72)
_SLACK_KM = 0.01
_PAIRS: dict[str, tuple[str, ReferenceCase]] = {
    "500 km LEO": ("LEO", COPLANAR_LEO), "550 km polar LEO": ("LEO", PLANE_CHANGE), "GEO": ("GEO", GEO_DRIFT_IN),
}


@contextmanager
def _constants(mu: float, radius: float, j2: float) -> Iterator[None]:
    saved = (monte_carlo._MU, monte_carlo._R_E, monte_carlo._J2)
    monte_carlo._MU, monte_carlo._R_E, monte_carlo._J2 = mu, radius, j2
    try:
        yield
    finally:
        monte_carlo._MU, monte_carlo._R_E, monte_carlo._J2 = saved


def _flown(tle: str, span_s: float) -> np.ndarray:
    track = monte_carlo.elset_state(tle, EPOCH)
    assert track is not None
    arc = monte_carlo.rk45_arc(track.state_eci_km, span_s, _BSTAR)
    assert arc is not None
    return np.array([arc(t)[:3] for t in np.arange(0.0, span_s + 1.0, _STEP_S)])


@functools.cache
def _measured(pair: str) -> dict[int, tuple[float, float]]:
    """By each horizon, the largest position difference of either object and the largest separation difference."""
    _, case = _PAIRS[pair]
    span = max(_HORIZONS) * _HOUR_S
    wgs84 = [_flown(tle, span) for tle in (case.red_tle, case.blue_tle)]
    with _constants(*SGP4_WGS72):
        wgs72_flown = [_flown(tle, span) for tle in (case.red_tle, case.blue_tle)]
    position = np.max([np.linalg.norm(a - b, axis=1) for a, b in zip(wgs84, wgs72_flown, strict=True)], axis=0)
    separation = np.abs(
        np.linalg.norm(wgs84[0] - wgs84[1], axis=1) - np.linalg.norm(wgs72_flown[0] - wgs72_flown[1], axis=1),
    )
    out = {}
    for h in _HORIZONS:
        k = int(h * _HOUR_S / _STEP_S) + 1
        out[h] = (float(position[:k].max()), float(separation[:k].max()))
    return out


def test_the_wgs72_constants_are_sgp4s_own() -> None:
    assert (wgs72.mu, wgs72.radiusearthkm, wgs72.j2) == SGP4_WGS72


def test_the_engine_flies_wgs84() -> None:
    assert (monte_carlo._MU, monte_carlo._R_E, monte_carlo._J2) == (398600.4418, 6378.137, 1.08263e-3)


@pytest.mark.parametrize("h", _HORIZONS)
def test_each_stated_figure_holds_what_is_measured(h: int) -> None:
    leo, geo, sep = WGS_HANDOVER_KM[h]
    measured = {pair: _measured(pair)[h] for pair in _PAIRS}
    leo_found = max(found[0] for pair, found in measured.items() if _PAIRS[pair][0] == "LEO")
    geo_found = measured["GEO"][0]
    sep_found = max(found[1] for found in measured.values())
    for stated, found in ((leo, leo_found), (geo, geo_found), (sep, sep_found)):
        assert found <= stated <= found + _SLACK_KM, (h, stated, found)


def test_the_separation_moves_less_than_the_element_set_error_each_sample_draws() -> None:
    """Why the physics is not changed: at every horizon the handover's separation is under a fifth of the smallest
    element-set error the engine assumes, 1 km for a LEO set at its epoch, and it is of the integrator's own
    separation error's size, 0.06 against 0.02 km by 24 h and 0.18 against 0.38 km by 72 h."""
    floor = position_error_km(0.0, "LEO")
    assert floor == 1.0
    for h in _HORIZONS:
        assert WGS_HANDOVER_KM[h][2] < floor / 5
    assert [WGS_HANDOVER_KM[h][2] for h in _HORIZONS] == [0.06, 0.12, 0.18]
    assert [monte_carlo.INTEGRATOR_ERROR_KM[h][2] for h in _HORIZONS] == [0.02, 0.11, 0.38]


def test_the_words() -> None:
    assert handover_words(72.0) == (
        "constants handover, not in the spread: RK45 starts from SGP4's states, which SGP4 works out with the WGS-72 "
        "constants, and flies them with WGS-84's; flown with WGS-72's instead, each object of three reference pairs "
        "moved up to 3.52 km in LEO and 1.43 km at GEO by 72 h, and the pair's separation up to 0.18 km"
    )
    assert "by 24 h" in handover_words(6.0)
    assert "by 48 h" in handover_words(30.0)
    assert handover_words(100.0).endswith("; it was measured to 72 h only, and grows with time")
