"""Burn-timing dispersion moves the burn, not the moment the cloud is read.

Audit F-029. Every sample burned at t = 0 from the same state, and the
timing perturbation lengthened or shortened the propagation instead, so the
cloud mixed states read at different times. In LEO the along-track spread
from that alone is about v x sigma_t, 7.6 km/s x 30 s = 228 km per sigma,
and it was shown to the operator as physical uncertainty.

With no delta-V or pointing dispersion, moving a 1 m/s burn by tens of
seconds changes the orbit by metres, so the cloud must be far smaller than
v x sigma_t.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np

from spectre.astro.constants import MU_EARTH, R_EARTH
from spectre.astro.monte_carlo import ManoeuvreHypothesis, run_monte_carlo

_A = R_EARTH + 500.0
_V = math.sqrt(MU_EARTH / _A)


def _hypothesis(timing_sigma_s: float) -> ManoeuvreHypothesis:
    return ManoeuvreHypothesis(
        epoch_utc=datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
        delta_v_magnitude_km_s=0.001,
        delta_v_radial=0.0, delta_v_in_track=0.001, delta_v_cross_track=0.0,
        pre_manoeuvre_state_eci_km=np.array([_A, 0.0, 0.0, 0.0, _V, 0.0]),
        delta_v_magnitude_1sigma_km_s=0.0,
        delta_v_pointing_1sigma_deg=0.0,
        epoch_1sigma_seconds=timing_sigma_s,
        bstar_post=1e-5,
        bstar_1sigma=0.0,
        n_samples=40,
    )


def test_timing_dispersion_does_not_smear_the_cloud_along_track() -> None:
    sigma = 30.0
    result = run_monte_carlo(_hypothesis(sigma), prediction_horizon_hours=2.0, max_workers=1)
    assert result.n_samples_converged == 40
    assert result.position_3sigma_km < 0.05 * _V * sigma, (
        f"3-sigma cloud {result.position_3sigma_km:.1f} km against v x sigma = {_V * sigma:.0f} km"
    )


def test_every_sample_is_read_at_the_same_horizon() -> None:
    # No dispersion of any kind except timing, and no timing: one point.
    result = run_monte_carlo(_hypothesis(0.0), prediction_horizon_hours=2.0, max_workers=1)
    assert result.position_3sigma_km < 1e-6
