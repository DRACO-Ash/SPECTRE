"""Unit tests for sipc.domain.geometry — pure math helpers."""

from __future__ import annotations

import math

from sipc.domain.geometry import (
    azimuth_elevation_range,
    closure_rate_ms,
    degrees_to_radians,
    radians_to_degrees,
)


class TestDegreesRadiansConversion:
    """Tests for degree/radian conversion helpers."""

    def test_degrees_to_radians_zero(self) -> None:
        assert degrees_to_radians(0.0) == 0.0

    def test_degrees_to_radians_90(self) -> None:
        assert math.isclose(degrees_to_radians(90.0), math.pi / 2)

    def test_degrees_to_radians_180(self) -> None:
        assert math.isclose(degrees_to_radians(180.0), math.pi)

    def test_radians_to_degrees_zero(self) -> None:
        assert radians_to_degrees(0.0) == 0.0

    def test_radians_to_degrees_pi(self) -> None:
        assert math.isclose(radians_to_degrees(math.pi), 180.0)

    def test_round_trip(self) -> None:
        """Converting to radians and back should recover the original value."""
        original = 45.0
        assert math.isclose(radians_to_degrees(degrees_to_radians(original)), original)


class TestAzimuthElevationRange:
    """Tests for azimuth_elevation_range."""

    def test_same_position_returns_zero_range(self) -> None:
        """Identical positions should give zero range."""
        _, _, rng = azimuth_elevation_range((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        assert rng == 0.0

    def test_range_along_x_axis(self) -> None:
        """Target 100 km along +X from observer at origin."""
        _, _, rng = azimuth_elevation_range((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
        assert math.isclose(rng, 100.0)

    def test_azimuth_east(self) -> None:
        """Target due east (+Y in ECEF approximation) should give ~90° azimuth."""
        az, _, _ = azimuth_elevation_range((0.0, 0.0, 0.0), (0.0, 100.0, 0.0))
        assert math.isclose(az, 90.0, abs_tol=0.1)

    def test_elevation_above(self) -> None:
        """Target directly above (+Z) should give positive elevation."""
        _, el, _ = azimuth_elevation_range((0.0, 0.0, 0.0), (0.0, 0.0, 100.0))
        assert el > 0.0

    def test_returns_three_values(self) -> None:
        """Should always return a 3-tuple."""
        result = azimuth_elevation_range((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
        assert len(result) == 3


class TestClosureRate:
    """Tests for closure_rate_ms."""

    def test_zero_range_returns_zero(self) -> None:
        """Zero relative position should return 0 to avoid division by zero."""
        rate = closure_rate_ms((0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
        assert rate == 0.0

    def test_approaching_positive_rate(self) -> None:
        """Objects moving toward each other should have a positive closure rate."""
        # Target is at +X, moving in -X direction (toward observer)
        rate = closure_rate_ms((100.0, 0.0, 0.0), (-500.0, 0.0, 0.0))
        assert rate > 0.0

    def test_receding_negative_rate(self) -> None:
        """Objects moving away from each other should have a negative closure rate."""
        # Target is at +X, moving in +X direction (away from observer)
        rate = closure_rate_ms((100.0, 0.0, 0.0), (500.0, 0.0, 0.0))
        assert rate < 0.0

    def test_perpendicular_velocity_zero_closure(self) -> None:
        """Perpendicular relative velocity should give zero closure rate."""
        # Target at +X, moving in +Y — no range-rate component
        rate = closure_rate_ms((100.0, 0.0, 0.0), (0.0, 500.0, 0.0))
        assert math.isclose(rate, 0.0, abs_tol=1e-9)
