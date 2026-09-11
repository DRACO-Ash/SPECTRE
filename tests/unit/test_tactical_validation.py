"""Numerical validation of the tactical manoeuvre library.

Every check here either compares against a closed form or flies the answer and
measures what actually happens. Three defects were found this way, all of them
returning confident numbers that no existing test disputed:

* ``phasing_orbit`` solved for a non-integer number of revolutions, so the
  chaser reached the target's angle at the wrong altitude. No rendezvous.
* ``nmc_safety_ellipse`` reported a passive-safety margin for a trajectory
  that passes through the target once per orbit. Closest approach was zero.
* ``intercept_envelope_analytical`` cannot see the angular separation at all,
  and underestimated true intercept cost by between 1.3x and 121x.

The functions that were checked and found correct are asserted here too, so
that remains true.
"""

from __future__ import annotations

import math

import pytest

from spectre.astro.constants import GEO_RADIUS, MU_EARTH
from spectre.astro.cw_geometry import CWState, _cw_propagate
from spectre.astro.tactical import (
    geo_drift,
    graveyard_transfer,
    j2_raan_rate,
    nmc_safety_ellipse,
    phasing_orbit,
)

_GEO_PERIOD_S = 2.0 * math.pi * math.sqrt(GEO_RADIUS**3 / MU_EARTH)
_GEO_MEAN_MOTION = math.sqrt(MU_EARTH / GEO_RADIUS**3)


class TestPhasingClosesTheLoop:
    """A phasing orbit must return the chaser to the point it burned at."""

    @pytest.mark.parametrize("phase_deg", [5.0, 30.0, 90.0, 180.0])
    def test_the_chaser_flies_a_whole_number_of_revolutions(self, phase_deg: float) -> None:
        result = phasing_orbit(GEO_RADIUS, GEO_RADIUS, phase_deg, 1)
        revolutions = result.time_to_intercept_s / result.phasing_period_s
        assert revolutions == pytest.approx(1.0, abs=1e-9), (
            f"{revolutions:.4f} revolutions. A fractional count puts the chaser at "
            "the target's angle but the wrong radius, so the second burn happens "
            "somewhere the two are not co-located."
        )

    @pytest.mark.parametrize(
        ("phase_deg", "expected_sma_km"),
        [(5.0, 41772.7), (30.0, 39787.8), (90.0, 34805.6), (180.0, 26561.7)],
    )
    def test_the_phasing_orbit_matches_the_closed_form(
        self, phase_deg: float, expected_sma_km: float
    ) -> None:
        """Target must cover 2*pi - phase to reach the chaser's burn point."""
        result = phasing_orbit(GEO_RADIUS, GEO_RADIUS, phase_deg, 1)
        assert result.phasing_sma_km == pytest.approx(expected_sma_km, abs=1.0)

    def test_a_gap_too_large_for_the_revolutions_allowed_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be closed"):
            phasing_orbit(GEO_RADIUS, GEO_RADIUS, 400.0, 1)

    def test_more_revolutions_make_a_large_gap_workable(self) -> None:
        """The refusal must be about the request, not a blanket rejection."""
        result = phasing_orbit(GEO_RADIUS, GEO_RADIUS, 400.0, 3)
        assert result.phasing_sma_km > 0.0

    def test_a_phasing_orbit_inside_the_atmosphere_is_refused(self) -> None:
        """A plan that cannot be flown is not a plan."""
        with pytest.raises(ValueError, match="atmosphere|cannot be closed"):
            phasing_orbit(7000.0, 7000.0, 359.0, 1)


class TestNmcIsActuallySafe:
    """Fly the prescribed trajectory and measure the closest approach.

    The previous implementation reported a 5 km margin for a trajectory whose
    closest approach was zero: a pure radial burn from a co-located state gives
    x(t) = (v/n) sin(nt) and y(t) = -(2v/n)(1 - cos(nt)), which returns to the
    origin every orbit. It certified a collision trajectory as passively safe.
    """

    def test_the_reported_margin_is_the_real_closest_approach(self) -> None:
        result = nmc_safety_ellipse(GEO_RADIUS, along_track_km=10.0)
        amplitude = result.radial_amplitude_km

        # The documented establishing condition: displaced radially, then an
        # along-track burn.
        state = CWState(x=amplitude, y=0.0, z=0.0,
                        xd=0.0, yd=-result.delta_v_establish, zd=0.0)
        ranges = [
            math.sqrt(s.x**2 + s.y**2 + s.z**2)
            for s in (
                _cw_propagate(state, _GEO_MEAN_MOTION, 2.0 * _GEO_PERIOD_S * i / 720.0)
                for i in range(721)
            )
        ]
        assert min(ranges) == pytest.approx(result.safety_margin_km, rel=0.02), (
            f"reported margin {result.safety_margin_km:.3f} km, actual closest "
            f"approach {min(ranges):.3f} km"
        )

    def test_the_relative_orbit_is_bounded_two_to_one(self) -> None:
        result = nmc_safety_ellipse(GEO_RADIUS, along_track_km=10.0)
        amplitude = result.radial_amplitude_km
        state = CWState(x=amplitude, y=0.0, z=0.0,
                        xd=0.0, yd=-result.delta_v_establish, zd=0.0)
        samples = [
            _cw_propagate(state, _GEO_MEAN_MOTION, _GEO_PERIOD_S * i / 360.0)
            for i in range(361)
        ]
        radial = max(abs(s.x) for s in samples)
        along = max(abs(s.y) for s in samples)
        assert along / radial == pytest.approx(2.0, rel=0.02), (
            "a bounded CW relative orbit has a 2:1 along-track to radial ratio"
        )
        # Bounded means it comes back, not drifts away.
        closed = _cw_propagate(state, _GEO_MEAN_MOTION, _GEO_PERIOD_S)
        assert abs(closed.y) < 1e-6, "the relative orbit must close, not drift"

    def test_a_radial_burn_from_co_location_is_not_a_safety_ellipse(self) -> None:
        """Pin the actual defect: that trajectory hits the target.

        If anyone reinstates the old establishing condition, this says why it
        is wrong rather than leaving the next reader to rediscover it.
        """
        result = nmc_safety_ellipse(GEO_RADIUS, along_track_km=10.0)
        wrong = CWState(x=0.0, y=0.0, z=0.0,
                        xd=result.radial_amplitude_km * _GEO_MEAN_MOTION,
                        yd=0.0, zd=0.0)
        ranges = [
            math.sqrt(s.x**2 + s.y**2 + s.z**2)
            for s in (
                _cw_propagate(wrong, _GEO_MEAN_MOTION, _GEO_PERIOD_S * i / 360.0)
                for i in range(361)
            )
        ]
        assert min(ranges) < 0.01, (
            "a radial burn from a co-located state returns to the target every "
            "orbit; this test exists to record that it is not a safety ellipse"
        )


class TestTheCorrectOnesStayCorrect:
    """Validated against independent relations. Keep them that way."""

    def test_geo_drift_moves_east_for_a_lower_orbit(self) -> None:
        east = geo_drift(10.0, 10.0)
        west = geo_drift(-10.0, 10.0)
        assert east.drift_sma_km < GEO_RADIUS, "an eastward drift needs a lower, faster orbit"
        assert west.drift_sma_km > GEO_RADIUS

    def test_geo_drift_magnitude_matches_the_standard_relation(self) -> None:
        """delta_a = -2/3 * (dlambda/dt) * a / n."""
        result = geo_drift(10.0, 10.0)
        mean_motion = 2.0 * math.pi / 86164.1
        expected_delta_a = (
            -2.0 / 3.0 * (math.radians(1.0) / 86400.0) * GEO_RADIUS / mean_motion
        )
        assert result.drift_sma_km - GEO_RADIUS == pytest.approx(expected_delta_a, rel=0.01)

    def test_graveyard_transfer_matches_the_closed_form(self) -> None:
        result = graveyard_transfer(300.0)
        r1, r2 = GEO_RADIUS, GEO_RADIUS + 300.0
        dv1 = math.sqrt(MU_EARTH / r1) * (math.sqrt(2.0 * r2 / (r1 + r2)) - 1.0)
        dv2 = math.sqrt(MU_EARTH / r2) * (1.0 - math.sqrt(2.0 * r1 / (r1 + r2)))
        assert result.total_delta_v == pytest.approx(dv1 + dv2, rel=1e-9)
        # IADC disposal guidance puts a 300 km raise at roughly 11 m/s.
        assert 10.0 < result.total_delta_v * 1000.0 < 12.0

    def test_j2_raan_rate_reproduces_the_sun_synchronous_condition(self) -> None:
        """Sun-synchronous orbits are DEFINED by +0.9856 deg/day."""
        rate = j2_raan_rate(7078.0, 0.0012, 98.19)
        assert rate == pytest.approx(0.9856, abs=0.01)

    def test_j2_raan_rate_is_westward_for_a_prograde_orbit(self) -> None:
        assert j2_raan_rate(6796.0, 0.0003, 51.64) < 0.0
