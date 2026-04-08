"""Unit tests for spectre.astro.monte_carlo — Monte Carlo manoeuvre simulation."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from spectre.astro.monte_carlo import (
    MANOEUVRE_ARCHETYPES,
    ManoeuvreHypothesis,
    MonteCarloResult,
    _ric_to_eci_rotation,
    _state_to_keplerian,
    check_convergence,
    generate_samples,
    run_monte_carlo,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _leo_state() -> np.ndarray:
    """ISS-like circular LEO state in ECI (km, km/s)."""
    r = np.array([6778.0, 0.0, 0.0])
    v_mag = np.sqrt(398600.4418 / 6778.0)
    v = np.array([0.0, v_mag * np.cos(np.radians(51.6)), v_mag * np.sin(np.radians(51.6))])
    return np.concatenate([r, v])


def _basic_hypothesis(n_samples: int = 50) -> ManoeuvreHypothesis:
    return ManoeuvreHypothesis(
        epoch_utc=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        delta_v_magnitude_km_s=0.010,
        delta_v_radial=0.0,
        delta_v_in_track=0.010,
        delta_v_cross_track=0.0,
        pre_manoeuvre_state_eci_km=_leo_state(),
        delta_v_magnitude_1sigma_km_s=0.001,
        delta_v_pointing_1sigma_deg=2.0,
        epoch_1sigma_seconds=30.0,
        bstar_post=1e-4,
        n_samples=n_samples,
        random_seed=42,
    )


# ── RIC → ECI rotation ───────────────────────────────────────────────────────

class TestRicToEci:
    def test_rotation_matrix_is_orthogonal(self):
        state = _leo_state()
        R = _ric_to_eci_rotation(state[:3], state[3:])
        identity = R @ R.T
        np.testing.assert_allclose(identity, np.eye(3), atol=1e-12)

    def test_rotation_matrix_is_proper(self):
        """Determinant of a proper rotation matrix is +1."""
        state = _leo_state()
        R = _ric_to_eci_rotation(state[:3], state[3:])
        assert abs(np.linalg.det(R) - 1.0) < 1e-12

    def test_radial_column_is_r_hat(self):
        state = _leo_state()
        R = _ric_to_eci_rotation(state[:3], state[3:])
        r_hat = state[:3] / np.linalg.norm(state[:3])
        np.testing.assert_allclose(R[:, 0], r_hat, atol=1e-12)


# ── State → Keplerian ─────────────────────────────────────────────────────────

class TestStateToKeplerian:
    def test_circular_orbit_eccentricity_near_zero(self):
        state = _leo_state()
        sma, ecc, inc = _state_to_keplerian(state[:3], state[3:])
        assert ecc < 0.01

    def test_sma_matches_radius_for_circular(self):
        state = _leo_state()
        sma, ecc, inc = _state_to_keplerian(state[:3], state[3:])
        assert abs(sma - 6778.0) < 5.0   # within 5 km for near-circular

    def test_inclination_reasonable(self):
        state = _leo_state()
        _, _, inc = _state_to_keplerian(state[:3], state[3:])
        assert 0.0 <= inc <= 180.0


# ── Sample generation ─────────────────────────────────────────────────────────

class TestGenerateSamples:
    def test_output_shape(self):
        h = _basic_hypothesis(n_samples=100)
        s = generate_samples(h)
        assert s.shape == (100, 5)

    def test_epoch_offsets_mean_near_zero(self):
        """Gaussian epoch offsets should have mean ≈ 0 for large N."""
        h = _basic_hypothesis(n_samples=2000)
        s = generate_samples(h)
        assert abs(np.mean(s[:, 3])) < 5.0   # within 5 seconds

    def test_dv_magnitude_nonnegative(self):
        h = _basic_hypothesis(n_samples=200)
        s = generate_samples(h)
        dv_mags = np.linalg.norm(s[:, :3], axis=1)
        assert np.all(dv_mags >= 0)

    def test_reproducibility_with_same_seed(self):
        h1 = _basic_hypothesis(n_samples=50)
        h2 = _basic_hypothesis(n_samples=50)
        s1 = generate_samples(h1)
        s2 = generate_samples(h2)
        np.testing.assert_array_equal(s1, s2)

    def test_different_seeds_give_different_samples(self):
        h1 = _basic_hypothesis(n_samples=50)
        h2 = _basic_hypothesis(n_samples=50)
        h2.random_seed = 99
        s1 = generate_samples(h1)
        s2 = generate_samples(h2)
        assert not np.allclose(s1, s2)

    def test_uniform_distribution_option(self):
        h = _basic_hypothesis(n_samples=200)
        h.distribution_type = "uniform"
        s = generate_samples(h)
        assert s.shape[0] == 200


# ── Convergence check ─────────────────────────────────────────────────────────

class TestCheckConvergence:
    def test_too_few_samples_returns_false(self):
        assert not check_convergence([1.0] * 100)

    def test_constant_sequence_converges(self):
        # A constant sequence has zero std — should converge
        vals = [6778.0] * 1000
        assert check_convergence(vals, window_size=200)

    def test_random_unconverged_sequence(self):
        rng = np.random.default_rng(0)
        # Small window relative to high-variance data → unlikely to converge
        vals = rng.normal(6778.0, 50.0, 400).tolist()
        # With only 400 samples and window=200, result may vary — just test no crash
        result = check_convergence(vals, window_size=200)
        assert isinstance(result, bool)


# ── Full MC run (small N for speed) ──────────────────────────────────────────

class TestRunMonteCarlo:
    def test_smoke_test_leo(self):
        """Smoke test: 50 samples, 6h horizon, LEO state."""
        h = _basic_hypothesis(n_samples=50)
        result = run_monte_carlo(h, satno=99999, prediction_horizon_hours=6.0, max_workers=2)
        assert isinstance(result, MonteCarloResult)
        assert result.n_samples_converged > 0

    def test_regime_probabilities_sum_to_one(self):
        h = _basic_hypothesis(n_samples=50)
        result = run_monte_carlo(h, satno=99999, prediction_horizon_hours=6.0, max_workers=2)
        total_prob = sum(result.regime_probabilities.values())
        assert abs(total_prob - 1.0) < 1e-9

    def test_sma_percentiles_ordered(self):
        h = _basic_hypothesis(n_samples=50)
        result = run_monte_carlo(h, satno=99999, prediction_horizon_hours=6.0, max_workers=2)
        assert result.sma_km_p5 <= result.sma_km_p50 <= result.sma_km_p95

    def test_leo_stays_in_leo(self):
        """Small ΔV on LEO object should stay in LEO."""
        h = _basic_hypothesis(n_samples=50)
        result = run_monte_carlo(h, satno=99999, prediction_horizon_hours=6.0, max_workers=2)
        leo_prob = result.regime_probabilities.get("LEO", 0.0)
        assert leo_prob > 0.8   # > 80% should remain in LEO

    def test_archetypes_all_defined(self):
        expected = {
            "station_keeping", "orbit_raise", "plane_change",
            "phasing", "intercept_approach", "evasive", "repositioning",
        }
        assert expected.issubset(MANOEUVRE_ARCHETYPES.keys())

    def test_result_has_wall_time(self):
        h = _basic_hypothesis(n_samples=20)
        result = run_monte_carlo(h, satno=0, prediction_horizon_hours=1.0, max_workers=1)
        assert result.wall_time_seconds > 0.0
