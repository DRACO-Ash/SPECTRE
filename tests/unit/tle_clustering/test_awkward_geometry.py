"""Clustering on the inputs that broke it (audits F-162, F-163, F-171).

Every clustering test used one epoch, nodes away from 0/360 degrees and no
near-equatorial orbit, so none could see that:

● RAAN was linear: 359.99 and 0.01 degrees were 7,199.6 tolerances apart,
  and a group straddling the seam had a centroid near 180 (F-162);
● DBSCAN chains: five sets each 0.9 tolerance from the next form one
  cluster whose ends are 3.6 tolerances apart (F-163);
● a near-equatorial GEO orbit has no meaningful node, so fits of one
  object scatter in RAAN and never clustered (F-171).
"""

from __future__ import annotations

import math

import pytest
from sgp4.api import Satrec

from tests.unit.tle_clustering.conftest import make_tle_pair, make_tle_strings
from tle_clustering.clustering import cluster_records
from tle_clustering.config import ClusteringConfig
from tle_clustering.parser import parse_tle_strings
from tle_clustering.selection import _chebyshev_distance_normalised

_CFG = ClusteringConfig()


def _cluster(variations: list[tuple[float, float, float]]):  # type: ignore[no-untyped-def]
    return cluster_records(25544, parse_tle_strings(make_tle_strings(25544, variations)), _CFG)


def _arc(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


class TestTheRaanSeam:
    def test_nodes_either_side_of_zero_form_one_cluster_centred_on_the_seam(self) -> None:
        result = _cluster([(51.6, 359.98, 1e-4), (51.6, 359.99, 1e-4), (51.6, 0.01, 1e-4)])
        assert result.cluster_count == 1
        assert result.noise_count == 0
        assert _arc(result.clusters[0].centroid_raan_deg, 359.99) < 0.01

    def test_selection_measures_raan_the_short_way_round(self) -> None:
        (record,) = parse_tle_strings(list(make_tle_pair(25544, 51.6, 0.01, 1e-4)))
        distance = _chebyshev_distance_normalised(record, 51.6, 359.99, 1e-4, _CFG)
        assert distance == pytest.approx(0.02 / _CFG.raan_tolerance_deg)


class TestChains:
    def test_a_chain_is_one_cluster_and_says_how_wide_it_is(self) -> None:
        step = 0.9 * _CFG.inclination_tolerance_deg
        result = _cluster([(51.6 + k * step, 200.0, 1e-4) for k in range(5)])
        assert result.cluster_count == 1, "neighbours within tolerance chain into one cluster"
        cluster = result.clusters[0]
        assert cluster.span_tolerances == pytest.approx(3.6, abs=1e-6)
        assert cluster.exceeds_tolerance

    def test_a_tight_cluster_is_within_tolerance(self) -> None:
        result = _cluster([(51.6, 200.0, 1e-4), (51.605, 200.02, 1.2e-4)])
        assert result.clusters[0].span_tolerances <= 1.0
        assert not result.clusters[0].exceeds_tolerance


class TestNearEquatorialGeo:
    def test_fits_of_one_equatorial_orbit_cluster_whatever_their_node(self) -> None:
        # Inclination 0.02 degrees: the node direction is noise.
        result = _cluster([(0.02, 85.0, 2e-4), (0.03, 270.0, 2e-4), (0.02, 140.0, 2.5e-4)])
        assert result.cluster_count == 1
        assert result.noise_count == 0

    def test_an_inclined_geo_orbit_still_compares_its_node(self) -> None:
        result = _cluster([(5.0, 85.0, 2e-4), (5.0, 270.0, 2e-4)])
        assert result.cluster_count == 0
        assert result.noise_count == 2


class TestMultiEpochLeo:
    def test_fits_hours_apart_cluster_once_the_node_is_carried_by_sgp4s_rate(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.6, 200.0, 1e-4, epoch="26091.50000000")
        rate_deg_per_day = math.degrees(Satrec.twoline2rv(l1, l2).nodedot) * 1440.0
        lines: list[str] = []
        for hours in (0, 3, 6, 9):
            raan = (200.0 + rate_deg_per_day * hours / 24.0) % 360.0
            lines += make_tle_pair(25544, 51.6, raan, 1e-4, epoch=f"{26091.5 + hours / 24.0:014.8f}")
        result = cluster_records(25544, parse_tle_strings(lines), _CFG)
        assert result.cluster_count == 1
        assert result.noise_count == 0


def test_a_chained_cluster_is_reported_to_the_operator(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from spectre.astro.tle_preprocessing import cluster_and_reduce_tle_cache

    step = 0.9 * _CFG.inclination_tolerance_deg
    lines = make_tle_strings(25544, [(51.6 + k * step, 200.0, 1e-4) for k in range(5)])
    tles = [f"{lines[i]}\n{lines[i + 1]}" for i in range(0, len(lines), 2)]
    with caplog.at_level(logging.WARNING):
        cluster_and_reduce_tle_cache({"25544": tles}, {}, {})
    assert "spans 3.6 tolerances end to end" in caplog.text
