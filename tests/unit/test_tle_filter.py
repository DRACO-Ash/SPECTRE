"""Unit tests for sipc.astro.tle_filter — TLE cadence filtering & deduplication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sipc.astro.tle_filter import (
    QualityFlag,
    TLECluster,
    cluster_tles,
    filter_tle_history,
    quality_flag_sequence,
    select_representative,
)
from sipc.astro.pattern_of_life import TLERecord


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    epoch: datetime,
    bstar: float = 1e-4,
    rms_residual: float | None = None,
    element_set_no: int = 0,
    regime: str = "LEO",
    sma_km: float = 6778.0,
) -> TLERecord:
    """Create a minimal TLERecord for testing (no real TLE text needed)."""
    return TLERecord(
        epoch=epoch,
        tle="1 99999U 00000A   00001.00000000  .00000000  00000-0  00000-0 0  9999\n"
            "2 99999  51.6000   0.0000 0000001   0.0000   0.0000 15.50000000    00",
        sma_km=sma_km,
        ecc=0.001,
        inc_deg=51.6,
        raan_deg=0.0,
        argp_deg=0.0,
        mean_anomaly_deg=0.0,
        mean_motion_revday=15.5,
        bstar=bstar,
        alt_km=sma_km - 6378.137,
        period_min=93.0,
        regime=regime,
        rms_residual=rms_residual,
        element_set_no=element_set_no,
    )


_T0 = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


# ── cluster_tles ─────────────────────────────────────────────────────────────

class TestClusterTles:
    def test_empty_input(self):
        assert cluster_tles([]) == []

    def test_single_tle_gives_one_cluster(self):
        rec = _make_record(_T0)
        clusters = cluster_tles([rec])
        assert len(clusters) == 1
        assert len(clusters[0].tles) == 1

    def test_two_tles_5s_apart_give_one_cluster_leo(self):
        """5 seconds < 15-minute LEO threshold → single cluster."""
        r1 = _make_record(_T0)
        r2 = _make_record(_T0 + timedelta(seconds=5))
        clusters = cluster_tles([r1, r2])
        assert len(clusters) == 1
        assert len(clusters[0].tles) == 2

    def test_two_tles_20min_apart_give_two_clusters_leo(self):
        """20 minutes > 15-minute LEO threshold → two clusters."""
        r1 = _make_record(_T0)
        r2 = _make_record(_T0 + timedelta(minutes=20))
        clusters = cluster_tles([r1, r2])
        assert len(clusters) == 2

    def test_geo_threshold_is_60min(self):
        """50 minutes < 60-minute GEO threshold → single cluster."""
        r1 = _make_record(_T0, regime="GEO", sma_km=42164.0)
        r2 = _make_record(_T0 + timedelta(minutes=50), regime="GEO", sma_km=42164.0)
        clusters = cluster_tles([r1, r2])
        assert len(clusters) == 1

    def test_meo_threshold_is_30min(self):
        """35 minutes > 30-minute MEO threshold → two clusters."""
        r1 = _make_record(_T0, regime="MEO", sma_km=20200.0)
        r2 = _make_record(_T0 + timedelta(minutes=35), regime="MEO", sma_km=20200.0)
        clusters = cluster_tles([r1, r2])
        assert len(clusters) == 2

    def test_unsorted_input_sorted_correctly(self):
        r1 = _make_record(_T0)
        r2 = _make_record(_T0 + timedelta(hours=2))
        r3 = _make_record(_T0 + timedelta(hours=1))
        clusters = cluster_tles([r2, r1, r3])
        # Should all end up in 3 separate clusters (1h gaps > 15 min)
        assert len(clusters) == 3

    def test_span_seconds_property(self):
        r1 = _make_record(_T0)
        r2 = _make_record(_T0 + timedelta(minutes=5))
        cluster = TLECluster(tles=[r1, r2])
        assert cluster.span_seconds == pytest.approx(300.0)

    def test_span_seconds_single(self):
        r1 = _make_record(_T0)
        cluster = TLECluster(tles=[r1])
        assert cluster.span_seconds == 0.0


# ── select_representative ─────────────────────────────────────────────────────

class TestSelectRepresentative:
    def test_single_tle_returns_it(self):
        r = _make_record(_T0)
        cluster = TLECluster(tles=[r])
        assert select_representative(cluster) is r

    def test_lowest_rms_wins(self):
        r_good = _make_record(_T0,                  rms_residual=0.002)
        r_bad  = _make_record(_T0 + timedelta(seconds=30), rms_residual=0.010)
        cluster = TLECluster(tles=[r_bad, r_good])
        assert select_representative(cluster) is r_good

    def test_latest_epoch_wins_when_no_rms(self):
        r_old = _make_record(_T0)
        r_new = _make_record(_T0 + timedelta(seconds=30))
        cluster = TLECluster(tles=[r_old, r_new])
        assert select_representative(cluster) is r_new

    def test_highest_esn_is_tiebreaker(self):
        r_low  = _make_record(_T0, element_set_no=100)
        r_high = _make_record(_T0, element_set_no=200)
        cluster = TLECluster(tles=[r_low, r_high])
        assert select_representative(cluster) is r_high

    def test_rms_only_for_records_that_have_it(self):
        """If only some records have RMS, prefer the lowest-RMS among those."""
        r_no_rms  = _make_record(_T0 + timedelta(seconds=60), rms_residual=None)
        r_good_rms = _make_record(_T0,                       rms_residual=0.001)
        r_bad_rms  = _make_record(_T0 + timedelta(seconds=30), rms_residual=0.005)
        cluster = TLECluster(tles=[r_no_rms, r_bad_rms, r_good_rms])
        assert select_representative(cluster) is r_good_rms


# ── quality_flag_sequence ─────────────────────────────────────────────────────

class TestQualityFlagSequence:
    def test_empty_and_single_return_no_flags(self):
        assert quality_flag_sequence([]) == []
        assert quality_flag_sequence([_make_record(_T0)]) == []

    def test_no_flags_for_well_cadenced_sequence(self):
        reps = [_make_record(_T0 + timedelta(hours=i * 6)) for i in range(5)]
        flags = quality_flag_sequence(reps)
        assert flags == []

    def test_returns_quality_flag_objects(self):
        r1 = _make_record(_T0)
        r2 = _make_record(_T0 + timedelta(hours=30))
        flags = quality_flag_sequence([r1, r2])
        assert all(isinstance(f, QualityFlag) for f in flags)

    def test_staleness_flag_raised_for_leo(self):
        """Gap > 24h for LEO should raise a staleness gap flag."""
        r1 = _make_record(_T0)
        r2 = _make_record(_T0 + timedelta(hours=30))
        flags = quality_flag_sequence([r1, r2])
        assert any(f.flag_type == "gap" and ("staleness" in f.message.lower() or "30h" in f.message) for f in flags)

    def test_staleness_flag_raised_for_geo(self):
        """Gap > 72h for GEO should raise a staleness gap flag."""
        r1 = _make_record(_T0,                       regime="GEO", sma_km=42164.0)
        r2 = _make_record(_T0 + timedelta(hours=80), regime="GEO", sma_km=42164.0)
        flags = quality_flag_sequence([r1, r2])
        assert any(f.flag_type == "gap" and ("staleness" in f.message.lower() or "80h" in f.message) for f in flags)

    def test_bstar_discontinuity_flagged(self):
        r1 = _make_record(_T0, bstar=1.0e-4)
        r2 = _make_record(_T0 + timedelta(hours=12), bstar=9.0e-4)  # 800% change
        flags = quality_flag_sequence([r1, r2])
        assert any(f.flag_type == "bstar" and "discontinuity" in f.message.lower() for f in flags)

    def test_small_bstar_change_not_flagged(self):
        r1 = _make_record(_T0, bstar=1.0e-4)
        r2 = _make_record(_T0 + timedelta(hours=12), bstar=1.1e-4)  # 10% change
        flags = quality_flag_sequence([r1, r2])
        assert not any(f.flag_type == "bstar" for f in flags)

    def test_str_repr_returns_message(self):
        r1 = _make_record(_T0, bstar=1.0e-4)
        r2 = _make_record(_T0 + timedelta(hours=12), bstar=9.0e-4)
        flags = quality_flag_sequence([r1, r2])
        assert all(str(f) == f.message for f in flags)


# ── filter_tle_history ────────────────────────────────────────────────────────

class TestFilterTleHistory:
    def test_empty_returns_empty(self):
        reps, flags = filter_tle_history([])
        assert reps == []
        assert flags == []

    def test_single_record_passes_through(self):
        r = _make_record(_T0)
        reps, flags = filter_tle_history([r])
        assert len(reps) == 1
        assert reps[0] is r

    def test_dense_cluster_reduces_to_one(self):
        """Three TLEs within 5 minutes should reduce to one representative."""
        recs = [_make_record(_T0 + timedelta(seconds=i * 100)) for i in range(3)]
        reps, _ = filter_tle_history(recs)
        assert len(reps) == 1

    def test_well_spaced_tles_all_kept(self):
        """TLEs spaced 2h apart (> 15-min LEO threshold) should all be kept."""
        recs = [_make_record(_T0 + timedelta(hours=i * 2)) for i in range(5)]
        reps, _ = filter_tle_history(recs)
        assert len(reps) == 5

    def test_representatives_are_sorted(self):
        """Output should always be in chronological order."""
        recs = [_make_record(_T0 + timedelta(hours=i)) for i in range(10)]
        reps, _ = filter_tle_history(recs)
        epochs = [r.epoch for r in reps]
        assert epochs == sorted(epochs)

    def test_large_cluster_flag_emitted(self):
        """A cluster of 10+ TLEs should generate a cluster flag."""
        recs = [_make_record(_T0 + timedelta(seconds=i * 30)) for i in range(12)]
        _, flags = filter_tle_history(recs)
        assert any(f.flag_type == "cluster" and "12" in f.message for f in flags)

    def test_flags_sorted_newest_first(self):
        """Quality flags must be in descending epoch order."""
        recs = (
            [_make_record(_T0 + timedelta(seconds=i * 30)) for i in range(12)]   # large cluster (early)
            + [_make_record(_T0 + timedelta(hours=h * 2)) for h in range(1, 6)]  # spaced TLEs
            + [_make_record(_T0 + timedelta(hours=60))]                           # staleness gap
        )
        _, flags = filter_tle_history(recs)
        if len(flags) >= 2:
            epochs = [f.epoch for f in flags]
            assert epochs == sorted(epochs, reverse=True)

    def test_known_manoeuvre_not_hidden(self):
        """Manoeuvre epoch gap (> spacing threshold) creates two clusters, both kept."""
        # Before-manoeuvre TLEs: dense cluster
        before = [_make_record(_T0 + timedelta(seconds=i * 60)) for i in range(3)]
        # After-manoeuvre TLEs: separate cluster (2h later)
        after = [_make_record(_T0 + timedelta(hours=2, seconds=i * 60)) for i in range(3)]
        reps, _ = filter_tle_history(before + after)
        assert len(reps) == 2  # One before, one after — manoeuvre window preserved
