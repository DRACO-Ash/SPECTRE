"""Tests for tle_clustering.parser."""

from __future__ import annotations

import math

import pytest

from tests.unit.tle_clustering.conftest import make_tle_pair, make_tle_strings
from tle_clustering.parser import group_by_norad, parse_tle_pair, parse_tle_strings


class TestParseTlePair:
    def test_returns_correct_norad(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.64, 247.12, 0.000123)
        rec = parse_tle_pair(l1, l2)
        assert rec.norad_id == 25544

    def test_inclination_extracted_in_degrees(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.6400, 247.12, 0.000123)
        rec = parse_tle_pair(l1, l2)
        assert abs(rec.inclination_deg - 51.6400) < 0.0005

    def test_raan_extracted_in_degrees(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.64, 247.1234, 0.000123)
        rec = parse_tle_pair(l1, l2)
        assert abs(rec.raan_deg - 247.1234) < 0.001

    def test_eccentricity_extracted(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.64, 247.12, 0.0007654)
        rec = parse_tle_pair(l1, l2)
        assert abs(rec.eccentricity - 0.0007654) < 1e-6

    def test_epoch_is_utc_aware(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.64, 247.12, 0.000123)
        rec = parse_tle_pair(l1, l2)
        assert rec.epoch.tzinfo is not None

    def test_tle_property_roundtrips_lines(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.64, 247.12, 0.000123)
        rec = parse_tle_pair(l1, l2)
        assert rec.tle == f"{l1.strip()}\n{l2.strip()}"

    def test_elements_tuple(self) -> None:
        l1, l2 = make_tle_pair(25544, 51.64, 247.12, 0.000123)
        rec = parse_tle_pair(l1, l2)
        inc, raan, ecc = rec.elements
        assert math.isclose(inc, rec.inclination_deg)
        assert math.isclose(raan, rec.raan_deg)
        assert math.isclose(ecc, rec.eccentricity)


class TestParseTleStrings:
    def test_parses_two_lines(self, default_norad: int) -> None:
        lines = make_tle_strings(default_norad, [(51.64, 247.12, 0.000123)])
        records = parse_tle_strings(lines)
        assert len(records) == 1
        assert records[0].norad_id == default_norad

    def test_parses_multiple_pairs(self, default_norad: int) -> None:
        lines = make_tle_strings(
            default_norad,
            [(51.64, 247.12, 0.000123), (51.65, 247.13, 0.000124)],
        )
        records = parse_tle_strings(lines)
        assert len(records) == 2

    def test_skips_name_lines(self, default_norad: int) -> None:
        l1, l2 = make_tle_pair(default_norad, 51.64, 247.12, 0.000123)
        lines = ["ISS (ZARYA)", l1, l2]
        records = parse_tle_strings(lines)
        assert len(records) == 1

    def test_skips_blank_lines(self, default_norad: int) -> None:
        l1, l2 = make_tle_pair(default_norad, 51.64, 247.12, 0.000123)
        lines = ["", l1, "  ", l2, ""]
        records = parse_tle_strings(lines)
        assert len(records) == 1

    def test_empty_input_returns_empty(self) -> None:
        assert parse_tle_strings([]) == []

    def test_odd_line_count_truncates(self, default_norad: int) -> None:
        l1, l2 = make_tle_pair(default_norad, 51.64, 247.12, 0.000123)
        l3, _ = make_tle_pair(default_norad, 51.65, 247.13, 0.000124)
        # Three TLE lines — the orphaned l3 should be dropped
        records = parse_tle_strings([l1, l2, l3])
        assert len(records) == 1


class TestGroupByNorad:
    def test_single_norad_groups_together(self, default_norad: int) -> None:
        lines = make_tle_strings(
            default_norad,
            [(51.64, 247.12, 0.000123), (51.65, 247.13, 0.000124)],
        )
        records = parse_tle_strings(lines)
        groups = group_by_norad(records)
        assert list(groups.keys()) == [default_norad]
        assert len(groups[default_norad]) == 2

    def test_multiple_norads_split_correctly(self) -> None:
        lines_a = make_tle_strings(10001, [(51.64, 247.12, 0.000123)])
        lines_b = make_tle_strings(20002, [(28.50, 180.00, 0.000001)])
        records = parse_tle_strings(lines_a + lines_b)
        groups = group_by_norad(records)
        assert set(groups.keys()) == {10001, 20002}
        assert len(groups[10001]) == 1
        assert len(groups[20002]) == 1

    def test_empty_input_returns_empty(self) -> None:
        assert group_by_norad([]) == {}
