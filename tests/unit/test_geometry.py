"""Unit tests for spectre.domain.geometry — pure math helpers."""

from __future__ import annotations

import math

from spectre.domain.geometry import (
    azimuth_elevation_range,
    closure_rate_ms,
    degrees_to_radians,
    ecef_to_sez,
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


class TestEcefToSez:
    """Tests for ecef_to_sez — ECEF to local South-East-Zenith rotation."""

    _R: float = 6371.0

    def test_equator_prime_meridian_zenith(self) -> None:
        """At lat=0 lon=0, a radial-outward delta should map entirely to Z."""
        s, e, z = ecef_to_sez((self._R, 0.0, 0.0), (self._R + 100.0, 0.0, 0.0))
        assert math.isclose(s, 0.0, abs_tol=1e-9)
        assert math.isclose(e, 0.0, abs_tol=1e-9)
        assert math.isclose(z, 100.0, rel_tol=1e-9)

    def test_equator_prime_meridian_east(self) -> None:
        """At lat=0 lon=0, +Y ECEF delta should map to East."""
        s, e, z = ecef_to_sez((self._R, 0.0, 0.0), (self._R, 100.0, 0.0))
        assert math.isclose(s, 0.0, abs_tol=1e-9)
        assert math.isclose(e, 100.0, rel_tol=1e-9)
        assert math.isclose(z, 0.0, abs_tol=1e-9)

    def test_equator_prime_meridian_south(self) -> None:
        """At lat=0 lon=0, -Z ECEF delta should map to South."""
        s, e, z = ecef_to_sez((self._R, 0.0, 0.0), (self._R, 0.0, -100.0))
        assert math.isclose(s, 100.0, rel_tol=1e-9)
        assert math.isclose(e, 0.0, abs_tol=1e-9)
        assert math.isclose(z, 0.0, abs_tol=1e-9)

    def test_north_pole_zenith(self) -> None:
        """At the North Pole, +Z ECEF delta should map to Zenith."""
        s, e, z = ecef_to_sez((0.0, 0.0, self._R), (0.0, 0.0, self._R + 100.0))
        assert math.isclose(s, 0.0, abs_tol=1e-9)
        assert math.isclose(e, 0.0, abs_tol=1e-9)
        assert math.isclose(z, 100.0, rel_tol=1e-9)


class TestAzimuthElevationRange:
    """Tests for azimuth_elevation_range using a proper ECEF → SEZ transform.

    Reference observer: lat=0°, lon=0° → ECEF (6371, 0, 0) km.
    At this point the local frame is:
        Zenith (Z) = (1, 0, 0)
        East   (E) = (0, 1, 0)
        North  (N) = (0, 0, 1)  →  South (S) = (0, 0, -1)

    All azimuth values are measured clockwise from North (0–360°).
    Elevation is measured from the local horizontal plane (−90° to +90°).

    These tests define the behaviour of the *correct* SEZ implementation
    (Phase 2.2). They are expected to fail on the current placeholder stub.
    """

    _R: float = 6371.0  # nominal Earth radius (km)

    def test_same_position_returns_zero_range(self) -> None:
        """Identical positions should give zero range regardless of location."""
        _, _, rng = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R, 0.0, 0.0)
        )
        assert rng == 0.0

    def test_range_is_euclidean_distance(self) -> None:
        """Range should equal the straight-line distance between the two points."""
        _, _, rng = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R + 100.0, 0.0, 0.0)
        )
        assert math.isclose(rng, 100.0, rel_tol=1e-9)

    def test_elevation_90_target_directly_overhead(self) -> None:
        """Target in the observer's zenith direction should give elevation = 90°."""
        # Δr = (100, 0, 0) → purely in Zenith direction
        _, el, _ = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R + 100.0, 0.0, 0.0)
        )
        assert math.isclose(el, 90.0, abs_tol=1e-6)

    def test_elevation_0_target_on_horizon(self) -> None:
        """Target perpendicular to zenith (due East) should give elevation = 0°."""
        # Δr = (0, 100, 0) → purely in East direction, no Z component
        _, el, _ = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R, 100.0, 0.0)
        )
        assert math.isclose(el, 0.0, abs_tol=1e-6)

    def test_azimuth_90_due_east(self) -> None:
        """Target due East should give azimuth = 90°."""
        # Δr = (0, 100, 0) → SEZ: S=0, E=100, Z=0 → Az = atan2(100, 0) = 90°
        az, _, _ = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R, 100.0, 0.0)
        )
        assert math.isclose(az, 90.0, abs_tol=1e-6)

    def test_azimuth_0_due_north(self) -> None:
        """Target due North should give azimuth = 0°."""
        # Δr = (0, 0, 100) → SEZ: S=-100, E=0, Z=0 → Az = atan2(0, 100) = 0°
        az, _, _ = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R, 0.0, 100.0)
        )
        assert math.isclose(az, 0.0, abs_tol=1e-6)

    def test_azimuth_180_due_south(self) -> None:
        """Target due South should give azimuth = 180°."""
        # Δr = (0, 0, -100) → SEZ: S=100, E=0, Z=0 → Az = atan2(0, -100) = 180°
        az, _, _ = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R, 0.0, -100.0)
        )
        assert math.isclose(az, 180.0, abs_tol=1e-6)

    def test_azimuth_270_due_west(self) -> None:
        """Target due West should give azimuth = 270°."""
        # Δr = (0, -100, 0) → SEZ: S=0, E=-100, Z=0 → Az = atan2(-100, 0) → 270°
        az, _, _ = azimuth_elevation_range(
            (self._R, 0.0, 0.0), (self._R, -100.0, 0.0)
        )
        assert math.isclose(az, 270.0, abs_tol=1e-6)

    def test_elevation_45_degrees(self) -> None:
        """Target at 45° elevation due North should give az=0°, el=45°, range=100 km."""
        # In SEZ: S = -100*cos(45°), E = 0, Z = 100*sin(45°)
        # In ECEF: Δr = Z_hat * 70.711 + N_hat * 70.711 = (70.711, 0, 70.711)
        d = 100.0
        delta = d / math.sqrt(2)
        observer = (self._R, 0.0, 0.0)
        target = (self._R + delta, 0.0, delta)
        az, el, rng = azimuth_elevation_range(observer, target)
        assert math.isclose(el, 45.0, abs_tol=1e-4)
        assert math.isclose(az, 0.0, abs_tol=1e-4)
        assert math.isclose(rng, d, rel_tol=1e-6)

    def test_north_pole_observer_overhead_target(self) -> None:
        """At the North Pole, zenith is +Z; target directly above should give El=90°."""
        # For lat=90°: Zenith=(0,0,1), so Δr purely in +Z → El=90°
        observer = (0.0, 0.0, self._R)
        target = (0.0, 0.0, self._R + 100.0)
        _, el, _ = azimuth_elevation_range(observer, target)
        assert math.isclose(el, 90.0, abs_tol=1e-6)


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
