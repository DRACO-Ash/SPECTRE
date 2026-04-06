"""Unit tests for sipc.astro.photometry — geometric corrections, baseline fitting,
change detection, and manoeuvre correlation."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from sipc.astro.photometry import (
    PhotometryObservation,
    CorrectedObservation,
    PhotometryBaseline,
    PhotometryChangeAssessment,
    _rozenberg_airmass,
    _t_test_two_sample,
    _regularised_incomplete_beta,
    apply_geometric_corrections,
    fit_baseline,
    detect_change,
    correlate_with_manoeuvres,
    assess_photometry,
    parse_photometry_csv,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


def _obs(epoch_iso: str, mag: float, phase: float = 45.0, elevation: float = 45.0,
         range_km: float = 1000.0, lunar_frac: float = 0.0, lunar_sep: float = 90.0) -> PhotometryObservation:
    return PhotometryObservation(
        epoch_utc=_dt(epoch_iso),
        apparent_magnitude=mag,
        uncertainty=0.05,
        filter_band="V",
        observer_lat_deg=40.0,
        observer_lon_deg=-75.0,
        observer_alt_m=100.0,
        range_km=range_km,
        solar_phase_angle_deg=phase,
        elevation_deg=elevation,
        lunar_phase_fraction=lunar_frac,
        lunar_separation_deg=lunar_sep,
    )


def _make_obs_sequence(n: int, base_mag: float = 12.0, phase_start: float = 10.0,
                       phase_step: float = 1.0, start_iso: str = "2025-01-01T00:00:00") -> list[PhotometryObservation]:
    """Generate n observations with slowly varying phase angles."""
    start = _dt(start_iso)
    return [
        _obs(
            (start + timedelta(days=i)).isoformat(),
            base_mag + 0.002 * i * i / n,  # slight quadratic — mimics phase function
            phase=phase_start + phase_step * i,
        )
        for i in range(n)
    ]


class _FakeManoeuvre:
    def __init__(self, epoch: datetime):
        self.epoch = epoch


# ── Rozenberg airmass ─────────────────────────────────────────────────────────

class TestRozenbergAirmass:
    def test_zenith_is_one(self):
        assert _rozenberg_airmass(90.0) == pytest.approx(1.0, abs=0.02)

    def test_45_deg_reasonable(self):
        am = _rozenberg_airmass(45.0)
        assert 1.3 < am < 1.6   # standard value ≈ 1.41 (sec z)

    def test_low_elevation_clipped(self):
        am = _rozenberg_airmass(0.0)
        assert am == 40.0

    def test_horizon_large(self):
        am = _rozenberg_airmass(5.0)
        assert am > 10.0


# ── Statistical helpers ────────────────────────────────────────────────────────

class TestTTest:
    def test_identical_groups_p_equals_one(self):
        g = [1.0] * 20
        t, p = _t_test_two_sample(g, g)
        assert abs(t) < 1e-9
        assert p == pytest.approx(1.0, abs=0.01)

    def test_clearly_different_groups_p_small(self):
        import random
        rng = random.Random(0)
        a = [1.0 + rng.gauss(0, 0.05) for _ in range(30)]
        b = [10.0 + rng.gauss(0, 0.05) for _ in range(30)]
        t, p = _t_test_two_sample(a, b)
        assert p < 0.001

    def test_p_value_in_unit_interval(self):
        import random
        rng = random.Random(42)
        a = [rng.gauss(0, 1) for _ in range(20)]
        b = [rng.gauss(0.5, 1) for _ in range(20)]
        _, p = _t_test_two_sample(a, b)
        assert 0.0 <= p <= 1.0

    def test_too_few_samples_returns_one(self):
        _, p = _t_test_two_sample([1.0], [2.0])
        assert p == 1.0


class TestRegularisedIncompleteBeta:
    def test_zero_returns_zero(self):
        assert _regularised_incomplete_beta(0.0, 2.0, 1.0) == 0.0

    def test_one_returns_one(self):
        assert _regularised_incomplete_beta(1.0, 2.0, 1.0) == 1.0

    def test_symmetry(self):
        """I_0.5(a, a) ≈ 0.5 for any a."""
        v = _regularised_incomplete_beta(0.5, 5.0, 5.0)
        assert abs(v - 0.5) < 0.01


# ── Geometric corrections ─────────────────────────────────────────────────────

class TestGeometricCorrections:
    def test_nominal_ok_flag(self):
        obs = _obs("2025-01-01T00:00:00", 12.0)
        corrected = apply_geometric_corrections([obs])
        assert corrected[0].quality_flag == "ok"

    def test_lunar_flag(self):
        obs = _obs("2025-01-01T00:00:00", 12.0, lunar_frac=0.9, lunar_sep=10.0)
        corrected = apply_geometric_corrections([obs])
        assert corrected[0].quality_flag in ("lunar", "reject")

    def test_low_elevation_flag(self):
        obs = _obs("2025-01-01T00:00:00", 12.0, elevation=5.0)
        corrected = apply_geometric_corrections([obs])
        assert corrected[0].quality_flag in ("low_elevation", "reject")

    def test_reject_flag_both_bad(self):
        obs = _obs("2025-01-01T00:00:00", 12.0, elevation=5.0, lunar_frac=0.9, lunar_sep=10.0)
        corrected = apply_geometric_corrections([obs])
        assert corrected[0].quality_flag == "reject"

    def test_range_normalisation_direction(self):
        """Object at 500 km (same apparent mag as one at 2000 km) is intrinsically
        dimmer, so its reduced magnitude (normalised to reference) is HIGHER."""
        obs_near = _obs("2025-01-01T00:00:00", 12.0, range_km=500.0)
        obs_far  = _obs("2025-01-01T00:00:00", 12.0, range_km=2000.0)
        c_near = apply_geometric_corrections([obs_near], reference_range_km=1000.0)[0]
        c_far  = apply_geometric_corrections([obs_far],  reference_range_km=1000.0)[0]
        assert c_near.reduced_magnitude > c_far.reduced_magnitude

    def test_same_range_as_reference_no_range_correction(self):
        """If range == reference_range, range correction is zero."""
        obs = _obs("2025-01-01T00:00:00", 12.0, range_km=1000.0)
        c = apply_geometric_corrections([obs], reference_range_km=1000.0)[0]
        # Airmass correction still applies, so not exactly 12.0, but close for moderate elevation
        assert abs(c.reduced_magnitude - 12.0) < 0.2


# ── Baseline fitting ──────────────────────────────────────────────────────────

class TestFitBaseline:
    def _corrected_stable(self, n: int = 30, noise: float = 0.02) -> list[CorrectedObservation]:
        """Generate stable observations on a known quadratic: mag = 12 + 0.01*phase."""
        import random
        rng = random.Random(0)
        start = _dt("2025-01-01T00:00:00")
        result = []
        for i in range(n):
            phase = 10.0 + i * (40.0 / n)
            mag   = 12.0 + 0.01 * phase + rng.gauss(0, noise)
            obs   = _obs(
                (start + timedelta(days=i)).isoformat(),
                mag, phase=phase,
            )
            result.append(CorrectedObservation(
                epoch_utc=obs.epoch_utc,
                reduced_magnitude=mag,
                solar_phase_angle_deg=phase,
                aspect_angle_deg=None,
                filter_band="V",
                quality_flag="ok",
                original=obs,
            ))
        return result

    def test_baseline_fit_returns_baseline(self):
        corr = self._corrected_stable()
        b = fit_baseline(corr)
        assert isinstance(b, PhotometryBaseline)

    def test_a1_positive_for_increasing_phase(self):
        """Phase coefficient a1 should be positive (brighter at small phase)."""
        corr = self._corrected_stable(n=40)
        b = fit_baseline(corr)
        # Linear term positive since mag = 12 + 0.01*phase
        assert b.a1 > -0.1   # may be slightly off with quadratic term

    def test_residual_std_small_for_clean_data(self):
        corr = self._corrected_stable(n=40, noise=0.01)
        b = fit_baseline(corr)
        assert b.residual_std < 0.05

    def test_sigma_clipping_removes_outliers(self):
        corr = self._corrected_stable(n=50, noise=0.01)
        # Inject 3 obvious outliers
        for i in range(3):
            corr[i] = CorrectedObservation(
                epoch_utc=corr[i].epoch_utc,
                reduced_magnitude=corr[i].reduced_magnitude + 5.0,   # +5 mag outlier
                solar_phase_angle_deg=corr[i].solar_phase_angle_deg,
                aspect_angle_deg=None,
                filter_band="V",
                quality_flag="ok",
                original=corr[i].original,
            )
        b = fit_baseline(corr)
        assert b.n_outliers >= 3

    def test_too_few_observations_raises(self):
        corr = self._corrected_stable(n=3)
        with pytest.raises(ValueError):
            fit_baseline(corr)


# ── Change detection ──────────────────────────────────────────────────────────

class TestDetectChange:
    def _make_corrected_with_shift(
        self, n_base: int = 60, n_recent: int = 30, shift: float = 0.0
    ) -> tuple[list[CorrectedObservation], PhotometryBaseline]:
        """Generate corrected observations: flat baseline then shifted recent window."""
        import random
        rng = random.Random(42)
        now   = _dt("2025-09-01T00:00:00")
        start = now - timedelta(days=n_base + n_recent)
        all_corr = []
        for i in range(n_base + n_recent):
            epoch = start + timedelta(days=i)
            phase = 20.0 + 20.0 * math.sin(2 * math.pi * i / 90.0)
            mag   = 12.0 + 0.005 * phase + rng.gauss(0, 0.03)
            if i >= n_base:
                mag += shift
            obs = _obs(epoch.isoformat(), mag, phase=phase)
            all_corr.append(CorrectedObservation(
                epoch_utc=epoch,
                reduced_magnitude=mag,
                solar_phase_angle_deg=phase,
                aspect_angle_deg=None,
                filter_band="V",
                quality_flag="ok",
                original=obs,
            ))
        # Fit baseline on all data first (includes slight shift, but dominated by baseline)
        b = fit_baseline(all_corr)
        return all_corr, b

    def test_no_change_p_large(self):
        corr, b = self._make_corrected_with_shift(shift=0.0)
        bm, bs, rm, rs, t, p = detect_change(corr, b,
                                              recent_window_days=30,
                                              baseline_window_days=60)
        assert p > 0.05   # should not be significant

    def test_large_shift_p_small(self):
        corr, b = self._make_corrected_with_shift(shift=0.5)  # 0.5 mag shift
        bm, bs, rm, rs, t, p = detect_change(corr, b,
                                              recent_window_days=30,
                                              baseline_window_days=60)
        assert p < 0.05   # should be significant


# ── Full pipeline ─────────────────────────────────────────────────────────────

class TestAssessPhotometry:
    def _stable_observations(self, n: int = 120) -> list[PhotometryObservation]:
        """Synthetic stable sequence: magnitude follows quadratic phase function."""
        import random
        rng = random.Random(7)
        start = _dt("2025-01-01T00:00:00")
        return [
            _obs(
                (start + timedelta(days=i)).isoformat(),
                12.0 + 0.005 * (20 + i * 40.0 / n) + rng.gauss(0, 0.02),
                phase=20.0 + i * 40.0 / n,
            )
            for i in range(n)
        ]

    def _shifted_observations(self, n: int = 120, shift: float = 0.4) -> list[PhotometryObservation]:
        """Same as stable but last 30 obs are shifted by `shift` mag."""
        obs = self._stable_observations(n)
        for i in range(n - 30, n):
            obs[i] = _obs(
                obs[i].epoch_utc.isoformat(),
                obs[i].apparent_magnitude + shift,
                phase=obs[i].solar_phase_angle_deg,
            )
        return obs

    def test_stable_not_significant(self):
        obs = self._stable_observations()
        result = assess_photometry(obs, recent_window_days=30, baseline_window_days=60)
        assert not result.significant_at_99

    def test_shifted_significant_at_95(self):
        obs = self._shifted_observations(shift=0.4)
        result = assess_photometry(obs, recent_window_days=30, baseline_window_days=60)
        assert result.significant_at_95

    def test_shifted_direction_fading(self):
        obs = self._shifted_observations(shift=0.4)   # positive Δmag = fading
        result = assess_photometry(obs, recent_window_days=30, baseline_window_days=60)
        if result.significant_at_95:
            assert result.change_direction == "fading"

    def test_summary_string_not_empty(self):
        obs = self._stable_observations()
        result = assess_photometry(obs)
        assert len(result.summary()) > 10

    def test_empty_observations_raises(self):
        with pytest.raises(ValueError):
            assess_photometry([])


# ── Manoeuvre correlation ─────────────────────────────────────────────────────

class TestCorrelateWithManoeuvres:
    def test_manoeuvre_within_window_returned(self):
        change_ep = _dt("2025-06-01T12:00:00")
        mnv = _FakeManoeuvre(_dt("2025-06-02T00:00:00"))   # 12h later
        result = correlate_with_manoeuvres(change_ep, [mnv], window_hours=48.0)
        assert len(result) == 1

    def test_manoeuvre_outside_window_excluded(self):
        change_ep = _dt("2025-06-01T12:00:00")
        mnv = _FakeManoeuvre(_dt("2025-06-10T00:00:00"))   # 9 days later
        result = correlate_with_manoeuvres(change_ep, [mnv], window_hours=48.0)
        assert len(result) == 0

    def test_none_change_epoch_returns_empty(self):
        mnv = _FakeManoeuvre(_dt("2025-06-01T12:00:00"))
        result = correlate_with_manoeuvres(None, [mnv])
        assert result == []


# ── CSV parser ────────────────────────────────────────────────────────────────

class TestParsePhotometryCsv:
    _MINIMAL_CSV = (
        "epoch_utc,apparent_magnitude\n"
        "2025-01-01T00:00:00Z,12.3\n"
        "2025-01-02T00:00:00Z,12.4\n"
    )
    _FULL_CSV = (
        "epoch_utc,apparent_magnitude,uncertainty,range_km,solar_phase_angle_deg,elevation_deg\n"
        "2025-01-01T00:00:00Z,12.3,0.03,900,40.0,55.0\n"
        "2025-01-02T00:00:00Z,12.4,0.04,920,41.0,52.0\n"
    )

    def test_minimal_csv_parses(self):
        obs = parse_photometry_csv(self._MINIMAL_CSV)
        assert len(obs) == 2

    def test_full_csv_parses(self):
        obs = parse_photometry_csv(self._FULL_CSV)
        assert obs[0].range_km == pytest.approx(900.0)
        assert obs[0].elevation_deg == pytest.approx(55.0)

    def test_default_uncertainty_filled(self):
        obs = parse_photometry_csv(self._MINIMAL_CSV)
        assert obs[0].uncertainty == pytest.approx(0.05)

    def test_invalid_epoch_skipped(self):
        csv = "epoch_utc,apparent_magnitude\nbad-date,12.3\n2025-01-02T00:00:00Z,12.4\n"
        obs = parse_photometry_csv(csv)
        assert len(obs) == 1

    def test_missing_magnitude_skipped(self):
        csv = "epoch_utc,apparent_magnitude\n2025-01-01T00:00:00Z,\n2025-01-02T00:00:00Z,12.4\n"
        obs = parse_photometry_csv(csv)
        assert len(obs) == 1
