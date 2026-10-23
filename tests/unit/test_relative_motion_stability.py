"""Relative-motion stability pinned to the Clohessy-Wiltshire solution.

Reference: Curtis, Orbital Mechanics for Engineering Students, eq. 7.53, which
``spectre.astro.cw_geometry._cw_propagate`` implements in closed form. Over one
orbit the along-track position of a drifting state moves by -6*pi*(ydot0 +
2*n*x0)/n; a state with ydot0 = -2*n*x0 is bounded and does not drift.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from spectre.astro import cw_geometry, maneuvers
from spectre.astro.constants import MU_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate
from spectre.astro.propagator import StateVector
from spectre.astro.tactical import relative_motion_stability

_R_REF = 7000.0
_N = math.sqrt(MU_EARTH / _R_REF**3)
_PERIOD = 2.0 * math.pi / _N


class TestSecularDrift:
    """Audit F-005: the drift came out at -0.5 times its true value."""

    @pytest.mark.parametrize(
        ("x0", "yd0"),
        [(1.0, 0.0), (0.0, 0.001), (-0.5, 0.0003)],
    )
    def test_the_drift_per_orbit_matches_the_cw_solution(self, x0: float, yd0: float) -> None:
        start = CWState(x=x0, y=0.0, z=0.0, xd=0.0, yd=yd0, zd=0.0)
        truth = _cw_propagate(start, _N, _PERIOD).y - start.y
        result = relative_motion_stability(_R_REF, x0, 0.0, 0.0, 0.0, yd0, 0.0)
        assert result.along_track_drift_km_per_orbit == pytest.approx(truth, rel=1e-9)

    def test_one_kilometre_radial_offset_drifts_backwards_by_twelve_pi(self) -> None:
        """The hand case the audit worked: x0 = 1 km, ydot0 = 0."""
        result = relative_motion_stability(_R_REF, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert result.along_track_drift_km_per_orbit == pytest.approx(-12.0 * math.pi, rel=1e-12)


class _StandIn:
    """A TLEOrbit stand-in that returns one fixed state vector."""

    def __init__(self, sv: StateVector) -> None:
        self._sv = sv

    def propagate(self, epoch: datetime) -> StateVector:
        return StateVector(epoch=epoch, r=self._sv.r, v=self._sv.v)


class TestStabilityInterceptFrame:
    """Audit F-006: the wrapper fed inertial, not rotating-frame, velocity."""

    def test_a_bounded_relative_orbit_scores_as_fully_stable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        epoch = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        r_blue = np.array([_R_REF, 0.0, 0.0])
        v_blue = np.array([0.0, math.sqrt(MU_EARTH / _R_REF), 0.0])
        # A bounded 2:1 ellipse in the rotating frame: ydot0 = -2 n x0.
        x0 = 1.0
        r_rel = np.array([x0, 0.0, 0.0])
        v_rel_rotating = np.array([0.0, -2.0 * _N * x0, 0.0])
        omega_cross_r = np.array([-_N * r_rel[1], _N * r_rel[0], 0.0])
        # Hill axes coincide with ECI here (radial = x, in-track = y, normal = z).
        sv_red = StateVector(epoch=epoch, r=r_blue + r_rel, v=v_blue + v_rel_rotating + omega_cross_r)
        sv_blue = StateVector(epoch=epoch, r=r_blue, v=v_blue)
        by_tle = {"RED": _StandIn(sv_red), "BLUE": _StandIn(sv_blue)}
        monkeypatch.setattr(cw_geometry, "TLEOrbit", lambda tle: by_tle[tle])
        monkeypatch.setattr(maneuvers, "TLEOrbit", lambda tle: by_tle[tle])

        solution = maneuvers.stability_intercept("RED", "BLUE", epoch)

        assert solution.miss_distance_km == pytest.approx(100.0), (
            "a truly bounded relative orbit must score 100; a lower score means the "
            "inertial velocity reached the CW boundedness test without the omega x r term"
        )
