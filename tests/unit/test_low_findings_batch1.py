"""Low findings, audit batch 1 (F-213 to F-240). Each test names its finding."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


class TestF215ClusteringFallbacksAreCounted:
    """A clustering failure and an all-noise object without a cache were not counted as fallbacks."""

    _A = ("1 25544U 98067A   26091.50000000  .00000000  00000-0  00000-0 0  9990\n"
          "2 25544  51.6400 200.0000 0001000 100.0000 200.0000 15.54321098000010")

    def test_a_failed_clustering_is_a_fallback_and_keeps_only_a_cached_tle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tle_clustering
        from spectre.astro import tle_preprocessing

        def boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("clustering failed")

        monkeypatch.setattr(tle_clustering, "cluster_tle_strings", boom)
        _, with_cache = tle_preprocessing.cluster_and_reduce_tle_cache({"1": [self._A, self._A]}, {"1": self._A}, {})
        _, without = tle_preprocessing.cluster_and_reduce_tle_cache({"1": [self._A, self._A]}, {}, {})
        assert (with_cache.objects_fallback, with_cache.objects[0].representatives_out) == (1, 1)
        assert (without.objects_fallback, without.objects[0].representatives_out) == (1, 0)


class TestF214F216NotsoParsing:
    def test_an_ambiguous_slash_date_is_refused(self) -> None:
        from spectre.astro.notso import _parse_dt

        assert _parse_dt("03/04/2026 12:00") is None

    def test_an_unambiguous_slash_date_still_reads(self) -> None:
        from datetime import UTC, datetime

        from spectre.astro.notso import _parse_dt

        assert _parse_dt("03/14/2026 12:00") == datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

    def test_a_date_time_group_reads(self) -> None:
        from datetime import UTC, datetime

        from spectre.astro.notso import _extract_datetime

        assert _extract_datetime("EFFECTIVE 141230Z MAR 26 FOR 48HRS") == datetime(2026, 3, 14, 12, 30, tzinfo=UTC)

    @pytest.mark.parametrize(("text", "kind"), [
        ("latest manoeuvre plan", "MANOEUVRE"),
        ("follower satellite keeps formation", "OTHER"),
        ("thruster test campaign", "TEST"),
        ("planned orbit raise", "MANOEUVRE"),
    ])
    def test_types_match_whole_words(self, text: str, kind: str) -> None:
        from spectre.astro.notso import NOTSOType, _infer_notso_type

        assert _infer_notso_type(text) == NOTSOType[kind]


def test_f220_a_uniform_magnitude_spread_has_the_stated_sigma() -> None:
    import numpy as np

    from spectre.astro.monte_carlo import generate_samples
    from tests.unit.test_monte_carlo import _basic_hypothesis

    hypothesis = _basic_hypothesis(n_samples=20_000)
    hypothesis.distribution_type = "uniform"
    magnitudes = np.linalg.norm(generate_samples(hypothesis)[:, :3], axis=1)
    assert float(np.std(magnitudes)) == pytest.approx(hypothesis.delta_v_magnitude_1sigma_km_s, rel=0.05)


def test_f224_a_photometry_epoch_with_an_offset_is_converted() -> None:
    from datetime import UTC, datetime

    from spectre.astro.photometry import parse_photometry_csv

    obs = parse_photometry_csv("epoch_utc,apparent_magnitude\n2026-03-14T14:00:00+02:00,8.1\n")
    assert obs[0].epoch_utc == datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def test_f225_the_swept_estimate_says_how_many_samples_propagated() -> None:
    from spectre.astro.dv_estimation import estimate_dv_epoch_swept
    from tests.unit.test_dv_estimation import TestTwoTierReporting

    records = TestTwoTierReporting._catalogue(n=4, burn_at=2)
    a, b = records[1], records[2]
    estimate = estimate_dv_epoch_swept(a.tle, b.tle, a.epoch, b.epoch)
    assert any("coarse samples across the gap propagated" in n for n in estimate.notes)


class TestCalibrationBands:
    def test_f227_an_interpolated_band_says_it_is_a_judgement(self) -> None:
        from spectre.domain.manoeuvre_calibration import _BANDS, ManoeuvreKind, classify_posture

        assert _BANDS[("GEO", ManoeuvreKind.ALTITUDE_CHANGE)].judgement
        assert not _BANDS[("GEO", ManoeuvreKind.PLANE_CHANGE)].judgement
        assessed = classify_posture(30.0, "GEO", ManoeuvreKind.ALTITUDE_CHANGE)
        assert "judgement" in assessed.basis

    @pytest.mark.parametrize("dv", [float("nan"), float("inf"), -1.0])
    def test_f233_a_meaningless_delta_v_is_refused(self, dv: float) -> None:
        from spectre.domain.manoeuvre_calibration import ManoeuvreKind, classify_posture

        with pytest.raises(ValueError, match="finite"):
            classify_posture(dv, "GEO", ManoeuvreKind.PHASING)


def test_f228_the_discretionary_reserve_is_listed_as_evidence_used() -> None:
    from spectre.domain.threat_assessment import AccessEvidence, CapabilityEvidence, assess_threat

    access = AccessEvidence(best_delta_v_m_s=12.0, time_to_arrival_hours=6.0, method="hohmann", regime="GEO")
    verdict = assess_threat(access, CapabilityEvidence(discretionary_remaining_m_s=150.0, discretionary_max_m_s=200.0))
    assert "discretionary reserve" in verdict.inputs_used


def test_f230_a_5_m_s_floor_names_the_smallest_event_it_catches() -> None:
    from types import SimpleNamespace

    from spectre.domain.pol_assessment import _assess_detection

    noise = SimpleNamespace(floor_km_s=0.005, median_km_s=0.001, mad_km_s=0.0005, samples=40)
    limits = _assess_detection(noise, "GEO")
    assert limits is not None
    # 0.6.3: a reference event, and Table 3 gives about 11 m/s for a 300 km
    # graveyard raise (10.94 computed), not the 9 m/s the label carried.
    assert "The smallest reference event that this would catch is 11 m/s" in limits.narrative


class TestManoeuvreRouteInputs:
    def test_f236_the_budget_share_is_of_the_operators_budget(self) -> None:
        from datetime import UTC, datetime

        from spectre.domain.models import InterceptMethod, InterceptResult
        from spectre.web.routes.maneuver import _compute_intercept_intel

        result = InterceptResult(red_name="R", blue_name="B", method=InterceptMethod.HOHMANN,
                                 total_delta_v_m_s=50.0, arrival_epoch=datetime(2026, 1, 1, tzinfo=UTC))
        intel = _compute_intercept_intel(result, "GEO", 100.0)
        assert intel["dv_budget_m_s"] == 100.0
        assert intel["dv_budget_pct"] == pytest.approx(50.0)

    @pytest.mark.parametrize(("text", "ok"), [("2026-03-14T12:00:00", True), ("tomorrow", False), ("", True)])
    def test_f237_an_unreadable_start_is_refused_not_replaced(self, text: str, ok: bool) -> None:
        from spectre.web.routes.maneuver import _manoeuvre_start

        assert (_manoeuvre_start(text) is not None) is ok

    def test_f237_an_offset_is_converted(self) -> None:
        from datetime import UTC, datetime

        from spectre.web.routes.maneuver import _manoeuvre_start

        assert _manoeuvre_start("2026-03-14T14:00:00+02:00") == datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

    def test_f234_an_unclassifiable_tle_is_named_not_assumed(self) -> None:
        from spectre.web.routes.maneuver import _pair_regimes

        good = ("1 25544U 98067A   26290.50000000  .00016717  00000-0  10270-3 0  9005\n"
                "2 25544  51.6400 208.9163 0006317  69.9862  25.2906 15.49541392 10001")
        reason = _pair_regimes(good, "1 bad\n2 bad")
        assert isinstance(reason, str)
        assert "blue TLE could not be propagated" in reason
