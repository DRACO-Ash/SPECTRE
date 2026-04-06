"""Tests for tle_clustering.selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.tle_clustering.conftest import make_tle_pair
from tle_clustering.config import ClusteringConfig
from tle_clustering.models import TLERecord
from tle_clustering.parser import parse_tle_pair
from tle_clustering.selection import select_representative


def _rec(inc: float, raan: float, ecc: float, days_offset: int = 0) -> TLERecord:
    """Helper: build a TLERecord with controlled elements and epoch offset."""
    l1, l2 = make_tle_pair(25544, inc, raan, ecc)
    rec = parse_tle_pair(l1, l2)
    # Inject a controlled epoch via dataclass replace (frozen — use __class__)
    new_epoch = rec.epoch + timedelta(days=days_offset)
    return TLERecord(
        norad_id=rec.norad_id,
        line1=rec.line1,
        line2=rec.line2,
        epoch=new_epoch,
        inclination_deg=inc,
        raan_deg=raan,
        eccentricity=ecc,
    )


class TestSelectRepresentative:
    def test_single_member_returns_that_member(self) -> None:
        cfg = ClusteringConfig()
        r = _rec(51.64, 247.12, 0.000123)
        result = select_representative([r], 51.64, 247.12, 0.000123, cfg)
        assert result is r

    def test_selects_closest_to_centroid(self) -> None:
        cfg = ClusteringConfig()
        # centroid at (51.64, 247.12, 0.000100)
        # r1 is exactly at centroid
        # r2 is slightly off
        r1 = _rec(51.6400, 247.1200, 0.000100, days_offset=0)
        r2 = _rec(51.6450, 247.1250, 0.000105, days_offset=1)
        result = select_representative([r1, r2], 51.6400, 247.1200, 0.000100, cfg)
        assert result is r1

    def test_tie_broken_by_recency(self) -> None:
        cfg = ClusteringConfig()
        # Both members are exactly at the centroid — tie broken by epoch
        r_old = _rec(51.6400, 247.1200, 0.000100, days_offset=0)
        r_new = _rec(51.6400, 247.1200, 0.000100, days_offset=5)
        result = select_representative(
            [r_old, r_new], 51.6400, 247.1200, 0.000100, cfg
        )
        assert result is r_new

    def test_tie_broken_by_recency_multiple_candidates(self) -> None:
        cfg = ClusteringConfig()
        r1 = _rec(51.6400, 247.1200, 0.000100, days_offset=0)
        r2 = _rec(51.6400, 247.1200, 0.000100, days_offset=3)
        r3 = _rec(51.6400, 247.1200, 0.000100, days_offset=7)  # newest
        result = select_representative(
            [r1, r2, r3], 51.6400, 247.1200, 0.000100, cfg
        )
        assert result is r3

    def test_empty_members_raises(self) -> None:
        cfg = ClusteringConfig()
        with pytest.raises(ValueError, match="empty"):
            select_representative([], 51.64, 247.12, 0.000100, cfg)

    def test_respects_tolerances(self) -> None:
        """With tight RAAN tolerance, the member closest in RAAN wins."""
        cfg = ClusteringConfig(raan_tolerance_deg=0.001)  # very tight
        # centroid at raan=247.12
        r1 = _rec(51.64, 247.1200, 0.000100, days_offset=0)  # exactly at centroid RAAN
        r2 = _rec(51.64, 247.1210, 0.000100, days_offset=5)  # 0.001 off RAAN — bigger normalised dist
        result = select_representative([r1, r2], 51.64, 247.12, 0.000100, cfg)
        assert result is r1
