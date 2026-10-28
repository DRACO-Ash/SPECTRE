"""Zero guards hold for values that are zero in all but floating-point noise.

SonarQube python:S1244 (0.6.0 submission) flagged five exact ``== 0.0``
checks. Each guards a special case that a value a rounding step away from
zero should also take: a circular orbit, a closed RAAN gap, a zero-length
integration, an empty ΔV breakdown and a zero burn.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from spectre.astro.monte_carlo import _integrate, _ric_split
from spectre.astro.tactical import _j2_acceleration, plane_change

_NOISE = 1e-15


class TestNearCircularOrbit:
    def test_an_eccentricity_of_rounding_noise_is_circular(self) -> None:
        result = plane_change(7000.0, 5.0, ecc=_NOISE, argp_deg=30.0)
        assert result.optimal_location == "node"


class TestClosedRaanGap:
    def test_a_gap_of_rounding_noise_needs_no_altitude_change(self) -> None:
        chaser = (7000.0, 0.001, 51.6)
        assert _j2_acceleration(chaser, 1e-7, _NOISE, 12.0, 398600.4418) == (0.0, 12.0)


class TestZeroSpanIntegration:
    def test_a_span_of_rounding_noise_returns_the_state_unchanged(self) -> None:
        state = np.array([7000.0, 0.0, 0.0, 0.0, 7.5, 0.0])
        result = _integrate(state, _NOISE, 1e-4)
        assert result is not None
        assert result is not state
        np.testing.assert_array_equal(result, state)


class TestEmptyBreakdown:
    def test_a_breakdown_of_rounding_noise_is_assumed_in_track(self) -> None:
        radial = SimpleNamespace(channel="radial", dv_km_s=1e-20, inputs={})
        direction, basis = _ric_split(SimpleNamespace(components=(radial,)))
        np.testing.assert_array_equal(direction, [0.0, 1.0, 0.0])
        assert basis.startswith("assumed in-track")

    def test_a_real_breakdown_is_still_split(self) -> None:
        radial = SimpleNamespace(channel="radial", dv_km_s=0.001, inputs={})
        direction, basis = _ric_split(SimpleNamespace(components=(radial,)))
        np.testing.assert_allclose(direction, [1.0, 0.0, 0.0])
        assert basis.startswith("split from")


class TestZeroBurn:
    def test_a_zero_burn_reports_no_split_and_no_error(self) -> None:
        from spectre.web.routes.maneuver import _burn_breakdown

        burn = SimpleNamespace(
            burn_number=1, burn_epoch=datetime(2026, 10, 28, tzinfo=UTC),
            delta_v_m_s=0.0, dv_prograde=0.0, dv_normal=0.0, dv_radial=0.0,
        )
        row = _burn_breakdown(SimpleNamespace(burns=[burn]))[0]  # type: ignore[arg-type]
        assert (row["pro_pct"], row["nor_pct"], row["rad_pct"]) == pytest.approx((0.0, 0.0, 0.0))

    def test_a_real_burn_still_splits_by_component(self) -> None:
        from spectre.web.routes.maneuver import _burn_breakdown

        burn = SimpleNamespace(
            burn_number=1, burn_epoch=datetime(2026, 10, 28, tzinfo=UTC),
            delta_v_m_s=5.0, dv_prograde=3.0, dv_normal=0.0, dv_radial=4.0,
        )
        row = _burn_breakdown(SimpleNamespace(burns=[burn]))[0]  # type: ignore[arg-type]
        assert (row["pro_pct"], row["rad_pct"]) == pytest.approx((60.0, 80.0))


class TestMigrationIdentifiersStayAscii:
    """python:S6353 asked for ``\\w``; in Python 3 that matches any Unicode
    letter unless the pattern is ASCII-only, which would widen the allow-list
    that guards interpolated DDL."""

    def test_an_ascii_identifier_is_accepted(self) -> None:
        from spectre.web.database import _assert_safe_ddl

        _assert_safe_ddl("training_progress", "user_id", "INTEGER")

    def test_a_non_ascii_identifier_is_refused(self) -> None:
        from spectre.web.database import _assert_safe_ddl

        with pytest.raises(ValueError, match="unsafe migration column"):
            _assert_safe_ddl("training_progress", "usér_id", "INTEGER")
