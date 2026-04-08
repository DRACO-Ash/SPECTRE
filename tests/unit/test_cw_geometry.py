"""Unit tests for spectre.astro.cw_geometry — CW relative motion geometry.

Coverage
--------
- CWState creation and field access
- _eci_to_hill_matrix orthogonality and right-handedness
- _cw_propagate: identity (dt=0), round-trip, drift-only orbit, CW invariants
- _apply_dv: additive, zero-delta, sign conventions
- _build_trajectory: length, monotonically increasing time, range formula
- _initial_hill_state: synthetic TLEs, returns finite values
- _check_validity: all warning thresholds
- compute_relative_geometry: full pipeline, input validation, error paths
- Security: name sanitisation, non-finite inputs, missing TLEs
- Audit: that RelativeGeometry fields are populated correctly
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timezone

import numpy as np
import pytest

from spectre.astro.cw_geometry import (
    CWState,
    RelativeGeometryError,
    TrajectoryPoint,
    _apply_dv,
    _build_trajectory,
    _check_validity,
    _cw_propagate,
    _eci_to_hill_matrix,
    _initial_hill_state,
    _sanitise_name,
    compute_relative_geometry,
)


# ── Shared test fixtures ───────────────────────────────────────────────────────

# A pair of close LEO TLEs (ISS-like, slightly offset semi-major axis).
_TLE_BLUE = (
    "1 25544U 98067A   24001.00000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 25544  51.6400 100.0000 0001000  90.0000 270.0000 15.49000000 00001"
)
_TLE_RED = (
    "1 25545U 98067B   24001.00000000  .00001000  00000-0  10000-3 0  9991\n"
    "2 25545  51.6400 100.0000 0001200  90.0000 270.0000 15.49500000 00001"
)

_EPOCH = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)


# ── _sanitise_name ─────────────────────────────────────────────────────────────

class TestSanitiseName:
    def test_printable_passthrough(self):
        assert _sanitise_name("Alpha") == "Alpha"

    def test_strips_non_printable(self):
        assert "\x00" not in _sanitise_name("Alpha\x00Beta")
        assert _sanitise_name("Alpha\x00Beta") == "AlphaBeta"

    def test_truncates_to_64(self):
        long_name = "A" * 100
        result = _sanitise_name(long_name)
        assert len(result) == 64

    def test_empty_string(self):
        assert _sanitise_name("") == ""

    def test_unicode_printable(self):
        assert _sanitise_name("Sat-α-01") == "Sat-α-01"

    def test_control_chars_stripped(self):
        assert "\n" not in _sanitise_name("line1\nline2")
        assert "\t" not in _sanitise_name("col1\tcol2")


# ── _eci_to_hill_matrix ────────────────────────────────────────────────────────

class TestEciToHillMatrix:
    def _circular_leo_state(self):
        """Return a circular LEO position and velocity."""
        r = np.array([6778.0, 0.0, 0.0])
        v_mag = math.sqrt(398600.4418 / 6778.0)
        v = np.array([0.0, v_mag, 0.0])
        return r, v

    def test_shape(self):
        r, v = self._circular_leo_state()
        R = _eci_to_hill_matrix(r, v)
        assert R.shape == (3, 3)

    def test_orthogonal(self):
        r, v = self._circular_leo_state()
        R = _eci_to_hill_matrix(r, v)
        err = np.linalg.norm(R @ R.T - np.eye(3))
        assert err < 1e-10, f"Matrix not orthogonal: max err = {err}"

    def test_determinant_plus_one(self):
        """Proper rotation — det = +1."""
        r, v = self._circular_leo_state()
        R = _eci_to_hill_matrix(r, v)
        assert abs(np.linalg.det(R) - 1.0) < 1e-10

    def test_radial_row_aligned_with_r(self):
        r, v = self._circular_leo_state()
        R = _eci_to_hill_matrix(r, v)
        r_hat = r / np.linalg.norm(r)
        assert np.allclose(R[0], r_hat, atol=1e-12)

    def test_cross_track_perpendicular_to_orbital_plane(self):
        r = np.array([6778.0, 0.0, 0.0])
        v_mag = math.sqrt(398600.4418 / 6778.0)
        v = np.array([0.0, v_mag, 0.0])
        R = _eci_to_hill_matrix(r, v)
        # Cross-track (row 2) should be along z for equatorial circular orbit
        assert abs(R[2, 2]) > 0.99

    def test_inclined_orbit(self):
        """Non-equatorial orbit — matrix should still be orthogonal."""
        angle = math.radians(51.6)
        r = np.array([6778.0, 0.0, 0.0])
        v_mag = math.sqrt(398600.4418 / 6778.0)
        v = np.array([0.0, v_mag * math.cos(angle), v_mag * math.sin(angle)])
        R = _eci_to_hill_matrix(r, v)
        err = np.linalg.norm(R @ R.T - np.eye(3))
        assert err < 1e-10


# ── _cw_propagate ──────────────────────────────────────────────────────────────

class TestCWPropagate:
    def _state(self, x=1.0, y=0.0, z=0.0, xd=0.0, yd=0.0, zd=0.0):
        return CWState(x=x, y=y, z=z, xd=xd, yd=yd, zd=zd)

    def test_zero_dt_is_identity(self):
        s = self._state(x=1.0, y=2.0, z=3.0, xd=0.01, yd=0.02, zd=0.003)
        n = 0.0011  # ~LEO mean motion rad/s
        out = _cw_propagate(s, n, 0.0)
        assert math.isclose(out.x, s.x, abs_tol=1e-12)
        assert math.isclose(out.y, s.y, abs_tol=1e-12)
        assert math.isclose(out.z, s.z, abs_tol=1e-12)

    def test_out_of_plane_decoupled(self):
        """z / ż evolve independently of x, y."""
        n = 0.0011
        s = self._state(x=0.0, y=0.0, z=1.0, xd=0.0, yd=0.0, zd=0.0)
        one_period = 2 * math.pi / n
        out = _cw_propagate(s, n, one_period)
        # After one full period, z should return to z0
        assert math.isclose(out.z, 1.0, abs_tol=1e-6)
        assert math.isclose(out.x, 0.0, abs_tol=1e-6)

    def test_pure_vbar_initial_vel_no_radial_drift(self):
        """Pure ẏ₀ with x₀=0 produces the CW drift pattern, not pure Keplerian."""
        n = 0.0011
        s = self._state(x=0.0, y=0.0, z=0.0, xd=0.0, yd=0.001, zd=0.0)
        # At t=π/(2n) (quarter period):
        dt = math.pi / (2 * n)
        out = _cw_propagate(s, n, dt)
        # x should be 2*(1-cos(nt))*yd0/n; at nt=π/2 → 2*(1-0)/n * yd0 = 2*yd0/n
        expected_x = 2.0 * (1.0 - math.cos(math.pi / 2)) * 0.001 / n
        assert math.isclose(out.x, expected_x, rel_tol=1e-6)

    def test_returns_cwstate(self):
        n = 0.0011
        s = self._state(x=1.0)
        out = _cw_propagate(s, n, 100.0)
        assert isinstance(out, CWState)

    def test_all_fields_finite(self):
        n = 0.0011
        s = self._state(x=2.0, y=-1.0, z=0.5, xd=0.001, yd=0.002, zd=-0.0005)
        out = _cw_propagate(s, n, 3600.0)
        for field_val in out:
            assert math.isfinite(field_val)

    def test_one_full_period_drift(self):
        """CW drift: pure x₀ offset — after one period, y shifts by -6π·x₀."""
        n = 0.0011
        x0 = 1.0
        s = self._state(x=x0, y=0.0, z=0.0, xd=0.0, yd=0.0, zd=0.0)
        T = 2 * math.pi / n
        out = _cw_propagate(s, n, T)
        # x returns to x0 (cos(2π)=1 → (4-3)*x0 = x0)
        assert math.isclose(out.x, x0, abs_tol=1e-8)
        # y has secular drift: 6*(sin(2π)-2π)*x0 = -12π*x0
        expected_y = 6.0 * (math.sin(2 * math.pi) - 2 * math.pi) * x0
        assert math.isclose(out.y, expected_y, rel_tol=1e-6)

    def test_z_simple_harmonic(self):
        """z oscillates at mean motion frequency."""
        n = 0.0011
        z0, zd0 = 0.5, 0.0
        s = self._state(z=z0, zd=zd0)
        dt = math.pi / n  # half period
        out = _cw_propagate(s, n, dt)
        # z(π/n) = z0*cos(π) + zd0*sin(π)/n = -z0
        assert math.isclose(out.z, -z0, abs_tol=1e-8)


# ── _apply_dv ──────────────────────────────────────────────────────────────────

class TestApplyDv:
    def test_adds_to_velocity_components(self):
        s = CWState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        out = _apply_dv(s, 0.1, 0.2, 0.3)
        assert math.isclose(out.xd, 0.1)
        assert math.isclose(out.yd, 0.2)
        assert math.isclose(out.zd, 0.3)

    def test_position_unchanged(self):
        s = CWState(1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
        out = _apply_dv(s, 0.5, -0.5, 1.0)
        assert out.x == 1.0
        assert out.y == 2.0
        assert out.z == 3.0

    def test_zero_dv_no_change(self):
        s = CWState(1.0, 2.0, 3.0, 0.1, 0.2, 0.3)
        out = _apply_dv(s, 0.0, 0.0, 0.0)
        assert out == s

    def test_negative_dv(self):
        s = CWState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        out = _apply_dv(s, -0.1, -0.2, -0.3)
        assert math.isclose(out.xd, -0.1)


# ── _build_trajectory ──────────────────────────────────────────────────────────

class TestBuildTrajectory:
    def _state(self):
        return CWState(10.0, 0.0, 0.0, 0.0, 0.01, 0.0)

    def test_returns_n_plus_1_points(self):
        n = 0.0011
        pts = _build_trajectory(self._state(), n, 3600.0, n_points=60)
        assert len(pts) == 61

    def test_time_monotonically_increasing(self):
        n = 0.0011
        pts = _build_trajectory(self._state(), n, 7200.0, n_points=30)
        times = [p.t_s for p in pts]
        assert times == sorted(times)

    def test_first_point_at_t_zero(self):
        n = 0.0011
        pts = _build_trajectory(self._state(), n, 3600.0)
        assert pts[0].t_s == 0.0

    def test_range_formula(self):
        n = 0.0011
        state = CWState(3.0, 4.0, 0.0, 0.0, 0.0, 0.0)
        pts = _build_trajectory(state, n, 1.0, n_points=1)
        expected_range = math.sqrt(3**2 + 4**2)  # 5 km
        assert math.isclose(pts[0].range_km, expected_range, rel_tol=1e-9)

    def test_zero_tof_returns_single_point(self):
        n = 0.0011
        pts = _build_trajectory(self._state(), n, 0.0)
        assert len(pts) == 1
        assert pts[0].t_s == 0.0

    def test_all_ranges_finite(self):
        n = 0.0011
        pts = _build_trajectory(self._state(), n, 7200.0)
        for p in pts:
            assert math.isfinite(p.range_km)

    def test_returns_trajectory_points(self):
        n = 0.0011
        pts = _build_trajectory(self._state(), n, 100.0, n_points=5)
        assert all(isinstance(p, TrajectoryPoint) for p in pts)


# ── _check_validity ────────────────────────────────────────────────────────────

class TestCheckValidity:
    def test_valid_close_circular_short_tof(self):
        ok, notes = _check_validity(50.0, 0.001, 2.0)
        assert ok
        assert any("valid" in n.lower() for n in notes)

    def test_large_range_invalid(self):
        ok, notes = _check_validity(600.0, 0.001, 2.0)
        assert not ok
        assert any("500" in n or "separation" in n.lower() for n in notes)

    def test_high_eccentricity_invalid(self):
        ok, notes = _check_validity(50.0, 0.1, 2.0)
        assert not ok
        assert any("eccentricity" in n.lower() for n in notes)

    def test_long_tof_warning(self):
        ok, notes = _check_validity(50.0, 0.001, 10.0)
        # tof > 6h triggers warning but may still be "valid" range/ecc wise
        assert any("time of flight" in n.lower() or "hours" in n.lower() or "tof" in n.lower()
                   or "secular" in n.lower() for n in notes)

    def test_all_bad_still_has_notes(self):
        ok, notes = _check_validity(1000.0, 0.3, 20.0)
        assert not ok
        assert len(notes) >= 2

    def test_exact_boundary_range(self):
        """At exactly the warning threshold — should not warn."""
        ok, notes = _check_validity(500.0, 0.001, 2.0)
        assert ok

    def test_just_over_threshold(self):
        ok, notes = _check_validity(500.1, 0.001, 2.0)
        assert not ok


# ── _initial_hill_state ────────────────────────────────────────────────────────

class TestInitialHillState:
    def test_returns_finite_state(self):
        state, n, rng, ecc = _initial_hill_state(_TLE_RED, _TLE_BLUE, _EPOCH)
        for val in state:
            assert math.isfinite(val), f"Non-finite state field: {val}"
        assert math.isfinite(n)
        assert math.isfinite(rng)

    def test_n_positive(self):
        _, n, _, _ = _initial_hill_state(_TLE_RED, _TLE_BLUE, _EPOCH)
        assert n > 0.0

    def test_range_positive(self):
        _, _, rng, _ = _initial_hill_state(_TLE_RED, _TLE_BLUE, _EPOCH)
        assert rng >= 0.0

    def test_ecc_bounded(self):
        _, _, _, ecc = _initial_hill_state(_TLE_RED, _TLE_BLUE, _EPOCH)
        assert 0.0 <= ecc < 1.0

    def test_same_tle_near_zero_range(self):
        """Same TLE for both satellites → near-zero initial separation."""
        state, n, rng, _ = _initial_hill_state(_TLE_BLUE, _TLE_BLUE, _EPOCH)
        assert rng < 1e-3  # essentially zero

    def test_invalid_tle_raises(self):
        with pytest.raises(RelativeGeometryError):
            _initial_hill_state("not a valid tle", _TLE_BLUE, _EPOCH)


# ── compute_relative_geometry ──────────────────────────────────────────────────

class TestComputeRelativeGeometry:
    def _call(self, **kw):
        defaults = dict(
            red_tle=_TLE_RED,
            blue_tle=_TLE_BLUE,
            burn_epoch=_EPOCH,
            dv_radial_km_s=0.0,
            dv_prograde_km_s=0.1,
            dv_normal_km_s=0.0,
            tof_s=3600.0,
            method="hohmann",
            red_name="RedSat",
            blue_name="BlueSat",
            coast_s=0.0,
            caller="test",
        )
        defaults.update(kw)
        return compute_relative_geometry(**defaults)

    def test_returns_relative_geometry(self):
        from spectre.astro.cw_geometry import RelativeGeometry
        result = self._call()
        assert isinstance(result, RelativeGeometry)

    def test_method_preserved(self):
        result = self._call(method="lambert")
        assert result.method == "lambert"

    def test_transfer_points_populated(self):
        result = self._call()
        assert len(result.transfer_points) > 10

    def test_coast_points_empty_when_coast_zero(self):
        result = self._call(coast_s=0.0)
        assert result.coast_points == []

    def test_coast_points_populated_when_coast_nonzero(self):
        result = self._call(coast_s=1800.0)
        assert len(result.coast_points) > 10

    def test_vr_transfer_series_length_matches_points(self):
        result = self._call()
        assert len(result.vr_transfer) == len(result.transfer_points)

    def test_hr_transfer_series_length_matches_points(self):
        result = self._call()
        assert len(result.hr_transfer) == len(result.transfer_points)

    def test_range_series_populated(self):
        result = self._call()
        assert len(result.range_series) > 0

    def test_arrival_range_finite(self):
        result = self._call()
        assert math.isfinite(result.arrival_range_km)

    def test_dv_total_ms_correct(self):
        result = self._call(dv_prograde_km_s=0.1, dv_radial_km_s=0.0, dv_normal_km_s=0.0)
        assert math.isclose(result.dv_total_ms, 100.0, rel_tol=1e-9)

    def test_dv_total_ms_vector_magnitude(self):
        result = self._call(dv_prograde_km_s=0.3, dv_radial_km_s=0.4, dv_normal_km_s=0.0)
        expected = math.sqrt(0.3**2 + 0.4**2) * 1000.0  # 500 m/s
        assert math.isclose(result.dv_total_ms, expected, rel_tol=1e-9)

    def test_n_rad_s_reasonable_for_leo(self):
        result = self._call()
        # LEO mean motion: ~0.001 rad/s
        assert 0.0008 < result.n_rad_s < 0.0014

    def test_tof_hours_preserved(self):
        result = self._call(tof_s=7200.0)
        assert math.isclose(result.tof_hours, 2.0, rel_tol=1e-9)

    def test_burn_epoch_preserved(self):
        result = self._call()
        assert result.burn_epoch == _EPOCH

    def test_name_sanitisation(self):
        result = self._call(red_name="Red\x00Sat", blue_name="Blue\nSat")
        assert "\x00" not in result.red_name
        assert "\n" not in result.blue_name

    # ── Security / validation tests ───────────────────────────────────────────

    def test_non_finite_dv_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(dv_prograde_km_s=float("inf"))

    def test_nan_dv_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(dv_radial_km_s=float("nan"))

    def test_dv_exceeds_hard_cap_raises(self):
        with pytest.raises(RelativeGeometryError, match="hard cap"):
            self._call(dv_prograde_km_s=25.0)  # > 20 km/s cap

    def test_negative_tof_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(tof_s=-1.0)

    def test_negative_coast_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(coast_s=-10.0)

    def test_empty_red_tle_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(red_tle="")

    def test_empty_blue_tle_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(blue_tle="  ")

    def test_invalid_tle_raises(self):
        with pytest.raises(RelativeGeometryError):
            self._call(red_tle="THIS IS NOT A TLE")

    def test_naive_epoch_raises(self):
        naive = datetime(2024, 1, 1, 0, 0, 0)  # no tzinfo
        with pytest.raises(RelativeGeometryError, match="timezone-aware"):
            self._call(burn_epoch=naive)

    def test_zero_dv_produces_trajectory(self):
        """Zero ΔV still produces a valid trajectory (just CW drift)."""
        result = self._call(dv_prograde_km_s=0.0)
        assert len(result.transfer_points) > 0

    def test_cw_valid_flag_close_circular(self):
        result = self._call(tof_s=1800.0)
        # Both TLEs are near-circular LEO — should be valid
        assert result.cw_valid

    def test_validity_notes_non_empty(self):
        result = self._call()
        assert len(result.validity_notes) > 0

    # ── Chart data format ─────────────────────────────────────────────────────

    def test_vr_coast_is_list_of_tuples(self):
        result = self._call(coast_s=600.0)
        for item in result.vr_coast:
            assert len(item) == 2

    def test_vr_transfer_tuples_are_floats(self):
        result = self._call()
        for y, x in result.vr_transfer:
            assert isinstance(y, float)
            assert isinstance(x, float)

    def test_range_series_time_ascending(self):
        result = self._call()
        times = [t for t, _ in result.range_series]
        assert times == sorted(times)

    def test_range_series_all_positive(self):
        result = self._call()
        for _, rng in result.range_series:
            assert rng >= 0.0

    def test_burn_state_is_cw_state(self):
        result = self._call()
        assert isinstance(result.burn_state, CWState)


# ── Data isolation ─────────────────────────────────────────────────────────────

class TestDataIsolation:
    def test_no_session_state_import(self):
        import spectre.astro.cw_geometry as m
        assert not hasattr(m, "SessionState")
        assert not hasattr(m, "get_session_state")

    def test_no_web_imports(self):
        import spectre.astro.cw_geometry as m
        # Should not import FastAPI or any web layer
        assert not hasattr(m, "APIRouter")
        assert not hasattr(m, "HTMLResponse")
