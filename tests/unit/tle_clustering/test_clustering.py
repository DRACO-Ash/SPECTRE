"""Tests for tle_clustering.clustering."""

from __future__ import annotations

import pytest

from tests.unit.tle_clustering.conftest import make_tle_strings
from tle_clustering.clustering import cluster_records
from tle_clustering.config import ClusteringConfig
from tle_clustering.parser import parse_tle_strings


def _records(norad: int, variations: list[tuple[float, float, float]]):
    return parse_tle_strings(make_tle_strings(norad, variations))


class TestClusterRecords:
    # ── Happy path ────────────────────────────────────────────────────────────

    def test_tight_variations_form_one_cluster(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        """Five near-identical TLEs should collapse into a single cluster."""
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        assert result.cluster_count == 1
        assert result.clusters[0].size == len(tight_cluster_variations)
        assert result.noise_count == 0

    def test_representative_is_a_cluster_member(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        cluster = result.clusters[0]
        assert cluster.representative in cluster.members

    def test_total_tles_in_matches_input(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        assert result.total_tles_in == len(tight_cluster_variations)

    def test_summary_dict_keys(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        s = result.summary()
        assert set(s.keys()) == {
            "norad_id", "total_in", "clusters", "representatives_out", "noise"
        }

    # ── All noise ─────────────────────────────────────────────────────────────

    def test_spread_tles_are_all_noise(
        self,
        default_norad: int,
        spread_variations: list[tuple[float, float, float]],
    ) -> None:
        """TLEs far apart in element space should all be flagged as noise."""
        records = _records(default_norad, spread_variations)
        result = cluster_records(default_norad, records)
        assert result.cluster_count == 0
        assert result.noise_count == len(spread_variations)

    def test_noise_tles_have_reason_string(
        self,
        default_norad: int,
        spread_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, spread_variations)
        result = cluster_records(default_norad, records)
        for n in result.noise:
            assert isinstance(n.reason, str)
            assert len(n.reason) > 0

    # ── Single TLE ────────────────────────────────────────────────────────────

    def test_single_tle_becomes_noise(self, default_norad: int) -> None:
        """One TLE cannot satisfy min_samples=2 and must be labelled noise."""
        records = _records(default_norad, [(51.64, 247.12, 0.000123)])
        result = cluster_records(default_norad, records)
        assert result.cluster_count == 0
        assert result.noise_count == 1
        assert result.total_tles_in == 1

    def test_single_tle_noise_reason_mentions_isolated(self, default_norad: int) -> None:
        records = _records(default_norad, [(51.64, 247.12, 0.000123)])
        result = cluster_records(default_norad, records)
        assert "isolated" in result.noise[0].reason.lower()

    # ── Empty input ───────────────────────────────────────────────────────────

    def test_empty_records_raises(self, default_norad: int) -> None:
        with pytest.raises(ValueError):
            cluster_records(default_norad, [])

    # ── Identical TLEs ────────────────────────────────────────────────────────

    def test_identical_tles_cluster_together(self, default_norad: int) -> None:
        """Multiple identical TLEs must form a single cluster."""
        same = (51.6400, 247.1234, 0.0001234)
        variations = [same, same, same]
        records = _records(default_norad, variations)
        result = cluster_records(default_norad, records)
        assert result.cluster_count == 1
        assert result.clusters[0].size == 3
        assert result.noise_count == 0

    # ── Tolerance sensitivity ─────────────────────────────────────────────────

    def test_tight_tolerance_splits_clusters(self, default_norad: int) -> None:
        """Halving tolerances should split a borderline cluster."""
        # Two TLEs 0.008 deg apart in inclination — within default 0.01 tol
        variations = [
            (51.6400, 247.12, 0.000123),
            (51.6480, 247.12, 0.000123),   # 0.008 deg — within default tolerance
        ]
        cfg_wide = ClusteringConfig(inclination_tolerance_deg=0.01)
        cfg_tight = ClusteringConfig(inclination_tolerance_deg=0.005)

        records = _records(default_norad, variations)
        result_wide = cluster_records(default_norad, records, cfg_wide)
        result_tight = cluster_records(default_norad, records, cfg_tight)

        assert result_wide.cluster_count == 1, "should cluster under wide tolerance"
        assert result_tight.cluster_count == 0, "should not cluster under tight tolerance"

    def test_loose_tolerance_merges_clusters(self, default_norad: int) -> None:
        """TLEs far enough apart to be noise under defaults should cluster when
        tolerance is widened sufficiently."""
        variations = [
            (51.6400, 247.12, 0.000123),
            (51.6600, 247.12, 0.000123),   # 0.02 deg in inc — outside default 0.01
        ]
        cfg_default = ClusteringConfig()
        cfg_wide = ClusteringConfig(inclination_tolerance_deg=0.025)

        records = _records(default_norad, variations)
        result_default = cluster_records(default_norad, records, cfg_default)
        result_wide = cluster_records(default_norad, records, cfg_wide)

        assert result_default.cluster_count == 0, "should be noise under default tolerance"
        assert result_wide.cluster_count == 1, "should merge under wide tolerance"

    # ── Two distinct clusters ─────────────────────────────────────────────────

    def test_two_groups_form_two_clusters(self, default_norad: int) -> None:
        """TLEs from two clearly separated orbit solutions should form 2 clusters."""
        group_a = [
            (51.6400, 247.12, 0.000123),
            (51.6405, 247.12, 0.000123),
            (51.6402, 247.12, 0.000123),
        ]
        group_b = [
            (55.0000, 180.00, 0.000500),
            (55.0005, 180.00, 0.000500),
            (55.0003, 180.00, 0.000500),
        ]
        records = _records(default_norad, group_a + group_b)
        result = cluster_records(default_norad, records)
        assert result.cluster_count == 2
        assert result.noise_count == 0

    # ── norad_id propagated ────────────────────────────────────────────────────

    def test_result_norad_id_matches_input(self, default_norad: int) -> None:
        records = _records(
            default_norad,
            [(51.64, 247.12, 0.000123), (51.641, 247.12, 0.000123)],
        )
        result = cluster_records(default_norad, records)
        assert result.norad_id == default_norad

    # ── Cluster properties ────────────────────────────────────────────────────

    def test_cluster_member_epochs_length(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        cluster = result.clusters[0]
        assert len(cluster.member_epochs) == cluster.size

    def test_cluster_centroid_within_range(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        c = result.clusters[0]
        member_incs = [m.inclination_deg for m in c.members]
        assert min(member_incs) <= c.centroid_inclination_deg <= max(member_incs)

    def test_representatives_tuple(
        self,
        default_norad: int,
        tight_cluster_variations: list[tuple[float, float, float]],
    ) -> None:
        records = _records(default_norad, tight_cluster_variations)
        result = cluster_records(default_norad, records)
        assert len(result.representatives) == 1
