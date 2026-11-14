"""The production RK45 integration against a tighter reference (SPC-197, evaluation finding F-06, gate G7).

The engine integrates with RK45 at RK45_RTOL 1e-8 and RK45_ATOL 1e-10 over
_j2_drag_ode, two-body, J2 and exponential drag, on two paths: each Monte Carlo
sample through monte_carlo._integrate, and each separation series, burn arc
and closest approach through the dense path, monte_carlo.rk45_arc and
_dense_arc. Both are measured here. The same equations, with the same
ballistic coefficient, are integrated by DOP853 at rtol 1e-12 and atol 1e-14 as
the reference, and each production state is compared with it at 48 h and 72 h
for two orbits, each the blue starting state of a hand-checked reference case
(tests/unit/_decision_reference.py), taken through SPECTRE's SGP4 at the cases'
epoch as the engine takes it:

● LEO: COPLANAR_LEO's blue, circular at 500 km and 51.6 degrees, with B* 1e-4
  (784.8 kg/m^2 by the production conversion) so drag is on;
● GEO: GEO_DRIFT_IN's blue, circular at geostationary radius and 0.05 degrees.

Measured at this commit (scipy 1.17.1), the position error is 0.285 km at 48 h
and 0.652 km at 72 h in LEO, and 0.0042 km and 0.0148 km at GEO, the figures
the evaluation's probe P-13 reports, on both paths. Each bound sits just above
its measured figure, so a looser tolerance, another method or a broken
integrator on either path fails here. Both sides share _j2_drag_ode, so an
error in the equations themselves is not this test's to find: the physics
tests pin those. Tightening the tolerances is finding F-27, not this test:
these bounds record today's error, they do not accept it.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from spectre.astro import monte_carlo
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN

_HOUR_S = 3600.0
#: B* for both orbits: the reference cases' element sets carry none, so drag is set on here.
_BSTAR = 1e-4
#: Each case's measured error at this commit, km, and the bound just above it.
_BOUNDS_KM = {
    ("LEO", 48): (0.285, 0.30),
    ("LEO", 72): (0.652, 0.70),
    ("GEO", 48): (0.0042, 0.005),
    ("GEO", 72): (0.0148, 0.017),
}


def _start(tle: str) -> np.ndarray:
    track = monte_carlo.elset_state(tle, EPOCH)
    assert track is not None
    return track.state_eci_km


_ORBITS = {"LEO": _start(COPLANAR_LEO.blue_tle), "GEO": _start(GEO_DRIFT_IN.blue_tle)}


def _sampled(state: np.ndarray, span_s: float, bstar: float) -> np.ndarray | None:
    """The Monte Carlo sample path."""
    return monte_carlo._integrate(state, span_s, bstar)


def _dense(state: np.ndarray, span_s: float, bstar: float) -> np.ndarray | None:
    """The separation series, burn arc and closest approach path."""
    arc = monte_carlo.rk45_arc(state, span_s, bstar)
    return None if arc is None else np.asarray(arc(span_s))


_PATHS: dict[str, Callable[[np.ndarray, float, float], np.ndarray | None]] = {"sampled": _sampled, "dense": _dense}


def _reference(state: np.ndarray, span_s: float, bstar: float) -> np.ndarray:
    """The same equations and ballistic coefficient, by DOP853 at rtol 1e-12 and atol 1e-14."""
    sol = solve_ivp(monte_carlo._j2_drag_ode, (0.0, span_s), state, method="DOP853", rtol=1e-12, atol=1e-14,
                    args=(monte_carlo._ballistic_coefficient_kg_m2(bstar),))
    assert sol.success
    return np.array(sol.y[:, -1])


def test_the_production_settings_are_the_ones_measured() -> None:
    """The figures in the bounds were measured at these tolerances; F-27 changes them, with new figures."""
    assert (monte_carlo.RK45_RTOL, monte_carlo.RK45_ATOL) == (1e-8, 1e-10)


@pytest.mark.parametrize("path", list(_PATHS))
@pytest.mark.parametrize(("orbit", "hours"), list(_BOUNDS_KM), ids=[f"{o} {h} h" for o, h in _BOUNDS_KM])
def test_the_production_rk45_stays_within_its_bound_of_the_reference(orbit: str, hours: int, path: str) -> None:
    state, span = _ORBITS[orbit], hours * _HOUR_S
    production = _PATHS[path](state, span, _BSTAR)
    assert production is not None
    error_km = float(np.linalg.norm(production[:3] - _reference(state, span, _BSTAR)[:3]))
    measured, bound = _BOUNDS_KM[orbit, hours]
    assert error_km < bound, f"{orbit} at {hours} h, {path}: {error_km:.4f} km from the reference, measured {measured}"
    # A bound far above the error would let a looser setting through: each sits under 1.2 times today's error.
    assert bound < measured * 1.2


def test_the_leo_case_has_drag_on() -> None:
    """Drag moves the LEO reference by more than the production error bound, so the case exercises it."""
    state, span = _ORBITS["LEO"], 72 * _HOUR_S
    without = solve_ivp(monte_carlo._j2_drag_ode, (0.0, span), state, method="DOP853", rtol=1e-12, atol=1e-14,
                        args=(0.0,))
    assert float(np.linalg.norm(_reference(state, span, _BSTAR)[:3] - without.y[:3, -1])) > _BOUNDS_KM["LEO", 72][1]
