"""The photometry baseline is fitted before the window it is tested against (audit F-100).

The phase-function baseline was fitted to every usable observation, the
recent window included, so a real brightness change was partly absorbed
into the fit, wholly so when phase angle trends with time, as it does
across a season. The recent residuals were then compared against a model
that had already learned them.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from spectre.astro.photometry import PhotometryObservation, assess_photometry

_START = datetime(2026, 1, 1, tzinfo=UTC)
_STEP_MAG = 0.3


def _observations(step_from_day: int) -> list[PhotometryObservation]:
    """120 nightly observations, phase angle drifting 20 to 80 degrees.

    The object follows a linear phase law, plus a small deterministic
    scatter, and fades by 0.3 mag from *step_from_day* on.
    """
    out = []
    for day in range(120):
        phase = 20.0 + 0.5 * day
        mag = 8.0 + 0.02 * phase + 0.02 * math.sin(day * 1.7)
        if day >= step_from_day:
            mag += _STEP_MAG
        out.append(PhotometryObservation(
            epoch_utc=_START + timedelta(days=day), apparent_magnitude=mag, uncertainty=0.02,
            filter_band="V", observer_lat_deg=51.0, observer_lon_deg=0.0, observer_alt_m=50.0,
            range_km=1000.0, solar_phase_angle_deg=phase, elevation_deg=90.0,
            lunar_phase_fraction=0.1, lunar_separation_deg=90.0,
        ))
    return out


def test_a_step_in_the_recent_window_is_recovered_in_full() -> None:
    # The recent window is the last 30 days: day 89 to day 119.
    result = assess_photometry(_observations(step_from_day=89), recent_window_days=30.0, baseline_window_days=90.0)
    assert abs(result.magnitude_change - _STEP_MAG) < 0.05
    assert result.change_direction == "fading"
    assert result.significant_at_99


def test_no_step_reads_as_no_change() -> None:
    result = assess_photometry(_observations(step_from_day=10_000), recent_window_days=30.0, baseline_window_days=90.0)
    assert abs(result.magnitude_change) < 0.02
    assert not result.significant_at_95


def test_extrapolating_past_the_baseline_phases_is_linear_and_says_so() -> None:
    # Recent phases run to 79.5 degrees against a baseline that ends at 64.
    result = assess_photometry(_observations(step_from_day=10_000), recent_window_days=30.0, baseline_window_days=90.0)
    notes = [c for c in result.confounding_factors if "extrapolated" in c]
    assert notes == ["Recent phase angles run 15.5° beyond the baseline's 20.0–64.0°; "
                     "the baseline is extrapolated with a linear phase law"]


def test_the_fit_holds_its_precision_at_large_phase_angles() -> None:
    """Audit F-107: normal equations on raw powers lost precision; x^4 is of order 1e8."""
    import numpy as np

    from spectre.astro.photometry import _fit_least_squares_quadratic

    phases = np.linspace(150.0, 170.0, 50)
    mags = 3.0 + 0.04 * phases - 1e-4 * phases**2 + 0.01 * np.sin(phases)
    a0, a1, a2, _ = _fit_least_squares_quadratic(list(phases), list(mags))
    expected = np.polynomial.polynomial.polyfit(phases, mags, 2)
    assert np.allclose([a0, a1, a2], expected, rtol=1e-9, atol=1e-12)
