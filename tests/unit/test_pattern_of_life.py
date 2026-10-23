"""Unit tests for spectre.astro.pattern_of_life — the PoL MEASUREMENT engine.

Interpretation moved to :mod:`spectre.domain.pol_assessment` and is covered by
``tests/unit/test_pol_assessment.py``. What is left here is what astro still
does: parse element sets, difference them, measure drift, and keep statistics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.astro.pattern_of_life import (
    TLERecord,
    _angle_diff,
    _compute_drift_phases,
    _dominant_element,
    _downsample,
    _epoch_to_jd,
    _gst_deg,
    _j2_argp_rate,
    _j2_raan_rate,
    _parse_tle_epoch,
    _percentile,
    _pol_stats,
    analyse_pattern_of_life,
    parse_tle_history,
)

# ── Sample TLE strings (all lines exactly 69 chars) ──────────────────────────

# ISS-like LEO TLE (epoch 2024-001.0)
_LEO_TLE_A = (
    "1 25544U 98067A   24001.00000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 25544  51.6400 100.0000 0001000  90.0000 270.0000 15.49000000 00001"
)

# Slight variation (epoch 2024-011.0)
_LEO_TLE_B = (
    "1 25544U 98067A   24011.00000000  .00001100  00000-0  10500-3 0  9991\n"
    "2 25544  51.6420 105.0000 0001200  91.0000 271.0000 15.49100000 00002"
)

_LEO_TLE_C = (
    "1 25544U 98067A   24021.00000000  .00001200  00000-0  11000-3 0  9992\n"
    "2 25544  51.6440 110.0000 0001400  92.0000 272.0000 15.49200000 00003"
)

# GEO-like TLE (mean motion ~1.0027 rev/day)
_GEO_TLE_A = (
    "1 43689U 18066A   24001.00000000  .00000000  00000-0  00000+0 0  9991\n"
    "2 43689   0.0500  95.0000 0002800 180.0000 180.0000  1.00272100 12345"
)

_GEO_TLE_B = (
    "1 43689U 18066A   24015.00000000  .00000000  00000-0  00000+0 0  9992\n"
    "2 43689   0.0520  96.0000 0002800 181.0000 181.0000  1.00273000 12350"
)

_GEO_TLE_C = (
    "1 43689U 18066A   24029.00000000  .00000000  00000-0  00000+0 0  9993\n"
    "2 43689   0.0540  97.0000 0002800 182.0000 182.0000  1.00274000 12355"
)


# ── Helper functions ──────────────────────────────────────────────────────────

class TestAngleDiff:
    def test_small_positive(self) -> None:
        assert abs(_angle_diff(0.0, 10.0) - 10.0) < 1e-9

    def test_wraps_negative(self) -> None:
        diff = _angle_diff(350.0, 10.0)
        assert abs(diff - 20.0) < 1e-9

    def test_wraps_positive(self) -> None:
        diff = _angle_diff(10.0, 350.0)
        assert abs(diff - (-20.0)) < 1e-9

    def test_zero(self) -> None:
        assert _angle_diff(90.0, 90.0) == 0.0


class TestPercentile:
    def test_empty_returns_zero(self) -> None:
        assert _percentile([], 50) == 0.0

    def test_single_element(self) -> None:
        assert _percentile([3.0], 50) == 3.0

    def test_median(self) -> None:
        val = _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50)
        assert abs(val - 3.0) < 0.01

    def test_p100(self) -> None:
        data = [1.0, 2.0, 3.0]
        assert _percentile(data, 100) == 3.0


class TestPolStats:
    def test_returns_none_for_single_value(self) -> None:
        assert _pol_stats([5.0]) is None

    def test_basic_stats(self) -> None:
        stats = _pol_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats is not None
        assert abs(stats.mean - 3.0) < 0.01
        assert stats.n == 5
        assert stats.low_2sigma < stats.mean
        assert stats.high_2sigma > stats.mean


class TestDownsample:
    def test_no_downsample_if_under_max(self) -> None:
        data = list(range(10))
        assert _downsample(data, max_pts=100) == data

    def test_downsample_reduces_length(self) -> None:
        data = list(range(1000))
        result = _downsample(data, max_pts=50)
        assert len(result) == 50

    def test_first_element_preserved(self) -> None:
        data = list(range(200))
        result = _downsample(data, max_pts=10)
        assert result[0] == 0


class TestEpochToJd:
    def test_j2000_epoch(self) -> None:
        j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
        jd = _epoch_to_jd(j2000)
        assert abs(jd - 2451545.0) < 1e-6


class TestGstDeg:
    def test_returns_float_in_0_360(self) -> None:
        epoch = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        gst = _gst_deg(epoch)
        assert 0.0 <= gst < 360.0


class TestParseTleEpoch:
    def test_parses_known_epoch(self) -> None:
        # line1 with epoch 26060.5 => 2026, day 60.5 (= March 1, 12:00 approx)
        line1 = "1 25544U 98067A   26060.50000000  .00016717  00000-0  10270-3 0  9993"
        epoch = _parse_tle_epoch(line1)
        assert epoch.year == 2026
        assert epoch.tzinfo is UTC


# ── parse_tle_history ─────────────────────────────────────────────────────────

class TestParseTleHistory:
    def test_parses_two_tles(self) -> None:
        tle_text = f"{_LEO_TLE_A}\n{_LEO_TLE_B}"
        records = parse_tle_history(tle_text)
        assert len(records) == 2

    def test_records_sorted_by_epoch(self) -> None:
        # Put newer TLE first in text
        tle_text = f"{_LEO_TLE_B}\n{_LEO_TLE_A}"
        records = parse_tle_history(tle_text)
        assert records[0].epoch < records[1].epoch

    def test_deduplication_by_epoch(self) -> None:
        # Same TLE twice — should deduplicate
        tle_text = f"{_LEO_TLE_A}\n{_LEO_TLE_A}"
        records = parse_tle_history(tle_text)
        assert len(records) == 1

    def test_empty_text_returns_empty(self) -> None:
        records = parse_tle_history("")
        assert records == []

    def test_with_metadata(self) -> None:
        tle_text = _LEO_TLE_A
        l1 = _LEO_TLE_A.strip().split("\n")[0]
        metadata = {l1: ("REAL", "18SCS")}
        records = parse_tle_history(tle_text, metadata=metadata)
        assert len(records) == 1
        assert records[0].data_mode == "REAL"
        assert records[0].source == "18SCS"

    def test_with_rms_metadata(self) -> None:
        tle_text = _LEO_TLE_A
        l1 = _LEO_TLE_A.strip().split("\n")[0]
        rms = {l1: 0.123}
        records = parse_tle_history(tle_text, rms_metadata=rms)
        assert records[0].rms_residual == pytest.approx(0.123)

    def test_invalid_lines_skipped(self) -> None:
        tle_text = "garbage line\n" + _LEO_TLE_A + "\nmore garbage"
        records = parse_tle_history(tle_text)
        assert len(records) == 1

    @pytest.mark.parametrize(
        "bad_value",
        [
            ("REAL", "18SCS", "SPARE"),   # one name too many to unpack
            ("REAL",),                    # one too few
            None,                         # not iterable at all
            7,                            # nor is this
        ],
    )
    def test_a_malformed_provenance_value_costs_one_element_set(
        self, bad_value: Any,
    ) -> None:
        """A provenance value that will not unpack drops its own record only.

        Splitting this function into _tle_line_pairs and _record_from_pair
        moved the metadata assignment out of the try that used to wrap the
        whole record. One unusable value then ended the entire parse and the
        operator got an empty history instead of a history short one element
        set. Breaking _apply_metadata's catch turns this red.
        """
        l1_a = _LEO_TLE_A.split("\n")[0]
        l1_b = _LEO_TLE_B.split("\n")[0]
        records = parse_tle_history(
            f"{_LEO_TLE_A}\n{_LEO_TLE_B}\n{_LEO_TLE_C}",
            metadata={l1_a: ("REAL", "18SCS"), l1_b: bad_value},
        )

        epochs = [r.epoch for r in records]
        assert len(records) == 2, "the two sound element sets must survive"
        assert epochs == sorted(epochs), "the surviving records stay in epoch order"
        # The sound value beside the bad one must still land: the catch covers
        # one record, not the whole metadata pass.
        assert (records[0].data_mode, records[0].source) == ("REAL", "18SCS")

    def test_a_record_dropped_on_provenance_still_spends_its_epoch(self) -> None:
        """The dropped record keeps its epoch out of the de-duplication set.

        This is the half of the restored behaviour that is easy to lose. The
        original added the epoch to ``seen`` BEFORE it touched the metadata, so
        a second element set at the same epoch was a duplicate however the
        first one ended. Re-admitting it would be a different parse from the
        one this release was meant to preserve.
        """
        l1, l2 = _LEO_TLE_A.split("\n")
        # Same epoch columns, different element set number, so the two line-1
        # strings differ while the de-duplication key does not.
        twin = l1[:64] + "9999" + l1[68]
        assert twin != l1 and len(twin) == len(l1)

        sound = parse_tle_history(f"{l1}\n{l2}\n{twin}\n{l2}")
        assert len(sound) == 1, "the twin is a duplicate epoch either way"

        dropped = parse_tle_history(
            f"{l1}\n{l2}\n{twin}\n{l2}", metadata={l1: ("REAL", "18SCS", "SPARE")},
        )
        assert dropped == [], "the spent epoch must not let the twin back in"


# ── _dominant_element ─────────────────────────────────────────────────────────

class TestDominantElement:
    """Which element moved is a measurement. Whether that is station-keeping is
    a judgement against cited budgets, and lives in the domain layer now."""

    def test_altitude_dominant(self) -> None:
        assert _dominant_element(d_alt=200.0, d_inc=0.01, d_ecc=0.0001) == "altitude"

    def test_inclination_dominant(self) -> None:
        assert _dominant_element(d_alt=5.0, d_inc=2.0, d_ecc=0.0001) == "inclination"

    def test_nothing_moved_is_mixed(self) -> None:
        assert _dominant_element(d_alt=0.01, d_inc=0.0001, d_ecc=1e-9) == "mixed"

    def test_a_breakdown_decides_it_directly(self) -> None:
        """With a measured decomposition there is nothing to infer."""
        from spectre.astro.dv_estimation import build_breakdown
        from tests.unit.test_dv_estimation import _pair

        before, after, _ = _pair(1.0, 0.5, d_inc=1.0)
        bd = build_breakdown(before, after, 1.0)
        assert _dominant_element(0.0, 0.0, 0.0, bd) == "inclination"


# ── _j2_raan_rate and _j2_argp_rate ──────────────────────────────────────────

def _make_record(sma: float = 6778.0, ecc: float = 0.001, inc: float = 51.6) -> TLERecord:
    from spectre.astro.pattern_of_life import _parse_tle_epoch
    lines = _LEO_TLE_A.strip().split("\n")
    epoch = _parse_tle_epoch(lines[0])
    return TLERecord(
        epoch=epoch, tle=_LEO_TLE_A,
        sma_km=sma, ecc=ecc, inc_deg=inc,
        raan_deg=0.0, argp_deg=0.0, mean_anomaly_deg=0.0,
        mean_motion_revday=15.54, bstar=1.0e-4,
        alt_km=sma - 6371.0, period_min=92.0, regime="LEO",
    )


class TestJ2Rates:
    def test_raan_rate_negative_for_prograde(self) -> None:
        rec = _make_record(sma=6778.0, ecc=0.001, inc=51.6)
        rate = _j2_raan_rate(rec)
        # RAAN regresses for prograde orbits (inc < 90°)
        assert rate < 0.0

    def test_argp_rate_returns_float(self) -> None:
        rec = _make_record()
        rate = _j2_argp_rate(rec)
        assert isinstance(rate, float)


# ── _compute_drift_phases ─────────────────────────────────────────────────────

class TestComputeDriftPhases:
    def test_empty_records_returns_empty(self) -> None:
        assert _compute_drift_phases([]) == []

    def test_no_geo_records_returns_empty(self) -> None:
        rec = _make_record()
        assert _compute_drift_phases([rec]) == []

    def test_detects_east_drift(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=UTC)
        recs = []
        for i in range(10):
            r = _make_record(sma=42164.0, ecc=0.0001, inc=0.05)
            r.epoch = base + timedelta(days=i)
            r.geo_longitude_deg = 100.0 + i * 0.3
            r.geo_drift_rate_deg_day = 0.3  # East drift
            r.regime = "GEO"
            recs.append(r)
        phases = _compute_drift_phases(recs)
        assert len(phases) >= 1
        assert any(p.direction == "EAST" for p in phases)


# ── analyse_pattern_of_life ───────────────────────────────────────────────────

class TestAnalysePatternOfLife:
    def test_raises_on_empty_records(self) -> None:
        with pytest.raises(ValueError, match="No TLE records"):
            analyse_pattern_of_life([])

    def test_single_record_no_manoeuvres(self) -> None:
        records = parse_tle_history(_LEO_TLE_A)
        assert len(records) == 1
        result = analyse_pattern_of_life(records, satno=25544, name="ISS")
        assert result.tle_count == 1
        assert len(result.manoeuvres) == 0
        assert result.candidate_manoeuvres == []

    def test_multiple_leo_records(self) -> None:
        tle_text = f"{_LEO_TLE_A}\n{_LEO_TLE_B}\n{_LEO_TLE_C}"
        records = parse_tle_history(tle_text)
        result = analyse_pattern_of_life(records, satno=25544, name="ISS")
        assert result.tle_count == 3
        assert isinstance(result.total_dv_km_s, float)
        assert result.regime in ("LEO", "MEO", "GEO", "HEO", "GTO", "DEEP")

    def test_result_has_chart_data(self) -> None:
        tle_text = f"{_LEO_TLE_A}\n{_LEO_TLE_B}"
        records = parse_tle_history(tle_text)
        result = analyse_pattern_of_life(records)
        assert len(result.chart_epochs) == 2
        assert len(result.chart_alts) == 2
        assert len(result.chart_incs) == 2

    def test_result_carries_the_detection_audit(self) -> None:
        """Measurement, not interpretation: what was examined and discarded."""
        tle_text = f"{_LEO_TLE_A}\n{_LEO_TLE_B}"
        records = parse_tle_history(tle_text)
        result = analyse_pattern_of_life(records)
        assert result.noise_model is not None
        assert result.pairs_examined >= 0

    def test_the_astro_layer_no_longer_interprets(self) -> None:
        """Every calibrated judgement now has exactly one home.

        Two sets of numbers for the same physics is worse than one set that is
        wrong, because only one of them ever gets updated.
        """
        tle_text = f"{_LEO_TLE_A}\n{_LEO_TLE_B}"
        result = analyse_pattern_of_life(parse_tle_history(tle_text))
        for gone in ("propellant_budget", "anomaly_score", "intel_assessment",
                     "dominant_activity", "is_station_keeping", "sk_type"):
            assert not hasattr(result, gone), (
                f"{gone} is back on the astro result. It is a judgement against "
                "cited per-regime budgets and belongs in "
                "spectre.domain.pol_assessment."
            )

    def test_geo_records(self) -> None:
        tle_text = f"{_GEO_TLE_A}\n{_GEO_TLE_B}\n{_GEO_TLE_C}"
        records = parse_tle_history(tle_text)
        result = analyse_pattern_of_life(records, satno=43689, name="GEO-SAT")
        assert result.regime in ("GEO", "MEO", "LEO", "DEEP")

    def test_quality_flags_stored(self) -> None:
        records = parse_tle_history(_LEO_TLE_A)
        flags = ["warning: sparse data"]
        result = analyse_pattern_of_life(records, quality_flags=flags)
        assert result.quality_flags == flags
