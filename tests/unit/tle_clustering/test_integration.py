"""Integration tests: raw TLE strings in → representative TLEs out.

Tests the full pipeline via the public ``cluster_tle_strings`` entry point,
covering multi-object batches, the noise-only case, and the single-TLE
passthrough.
"""

from __future__ import annotations

import pytest

from tests.unit.tle_clustering.conftest import make_tle_strings
from tle_clustering import ClusteringConfig, cluster_tle_strings


class TestClusterTleStrings:
    def test_single_object_single_cluster(self, default_norad: int) -> None:
        lines = make_tle_strings(
            default_norad,
            [
                (51.6400, 247.1200, 0.000123),
                (51.6405, 247.1210, 0.000124),
                (51.6395, 247.1195, 0.000122),
            ],
        )
        results = cluster_tle_strings(lines)
        assert default_norad in results
        r = results[default_norad]
        assert r.cluster_count == 1
        assert r.clusters[0].size == 3
        assert r.noise_count == 0

    def test_representative_tle_is_valid_string(self, default_norad: int) -> None:
        lines = make_tle_strings(
            default_norad,
            [(51.64, 247.12, 0.000123), (51.641, 247.12, 0.000124)],
        )
        results = cluster_tle_strings(lines)
        rep = results[default_norad].clusters[0].representative
        assert "\n" in rep.tle
        l1, l2 = rep.tle.split("\n")
        assert l1.startswith("1 ")
        assert l2.startswith("2 ")

    def test_multi_object_batch(self) -> None:
        lines_a = make_tle_strings(
            10001,
            [(51.64, 247.12, 0.000123), (51.641, 247.12, 0.000123)],
        )
        lines_b = make_tle_strings(
            20002,
            [(28.50, 180.00, 0.000001), (28.501, 180.00, 0.000001)],
        )
        results = cluster_tle_strings(lines_a + lines_b)
        assert set(results.keys()) == {10001, 20002}
        assert results[10001].cluster_count == 1
        assert results[20002].cluster_count == 1

    def test_all_noise_returns_no_clusters(
        self,
        default_norad: int,
        spread_variations: list[tuple[float, float, float]],
    ) -> None:
        lines = make_tle_strings(default_norad, spread_variations)
        results = cluster_tle_strings(lines)
        r = results[default_norad]
        assert r.cluster_count == 0
        assert r.noise_count == len(spread_variations)

    def test_single_tle_is_noise(self, default_norad: int) -> None:
        lines = make_tle_strings(default_norad, [(51.64, 247.12, 0.000123)])
        results = cluster_tle_strings(lines)
        r = results[default_norad]
        assert r.cluster_count == 0
        assert r.noise_count == 1

    def test_empty_lines_returns_empty(self) -> None:
        results = cluster_tle_strings([])
        assert results == {}

    def test_custom_config_applied(self, default_norad: int) -> None:
        """With very tight tolerances, two close TLEs become noise."""
        lines = make_tle_strings(
            default_norad,
            [(51.6400, 247.12, 0.000123), (51.6409, 247.12, 0.000123)],
        )
        # 0.0009 deg gap — within default 0.01 tol, but outside 0.0005 tol
        cfg_tight = ClusteringConfig(inclination_tolerance_deg=0.0005)
        cfg_default = ClusteringConfig()

        r_tight = cluster_tle_strings(lines, config=cfg_tight)[default_norad]
        r_default = cluster_tle_strings(lines, config=cfg_default)[default_norad]

        assert r_default.cluster_count == 1
        assert r_tight.cluster_count == 0

    def test_summary_dict_consistent(self, default_norad: int) -> None:
        lines = make_tle_strings(
            default_norad,
            [(51.64, 247.12, 0.000123), (51.641, 247.12, 0.000123)],
        )
        result = cluster_tle_strings(lines)[default_norad]
        s = result.summary()
        assert s["total_in"] == result.total_tles_in
        assert s["clusters"] == result.cluster_count
        assert s["representatives_out"] == result.representative_count
        assert s["noise"] == result.noise_count

    def test_name_lines_skipped_gracefully(self, default_norad: int) -> None:
        from tests.unit.tle_clustering.conftest import make_tle_pair
        l1, l2 = make_tle_pair(default_norad, 51.64, 247.12, 0.000123)
        l3, l4 = make_tle_pair(default_norad, 51.641, 247.12, 0.000123)
        lines = [f"SATNAME {default_norad}", l1, l2, "ANOTHER SAT", l3, l4]
        results = cluster_tle_strings(lines)
        assert results[default_norad].total_tles_in == 2
