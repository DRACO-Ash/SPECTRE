"""Unit tests for spectre.domain.models."""

from __future__ import annotations

from datetime import UTC, datetime

from spectre.config.constants import BLUE_PREFIX, RED_PREFIX
from spectre.domain.models import (
    AccessInterval,
    BlueAsset,
    InterceptWindow,
    RedTrack,
    RunConfig,
)


class TestBlueAsset:
    """Tests for BlueAsset dataclass."""

    def test_stk_name_auto_derived(self) -> None:
        """stk_name should be prefixed with BLUE_PREFIX."""
        asset = BlueAsset(name="Alpha", tle="line1\nline2")
        assert asset.stk_name == f"{BLUE_PREFIX}Alpha"

    def test_stk_name_includes_full_name(self) -> None:
        """stk_name should preserve the full name including spaces (edge case)."""
        asset = BlueAsset(name="Phoenix 01", tle="line1\nline2")
        assert asset.stk_name == f"{BLUE_PREFIX}Phoenix 01"

    def test_tle_stored_verbatim(self) -> None:
        """TLE string should be stored exactly as provided."""
        tle = (
            "1 25544U 98067A   24001.00000000  .00000000  00000-0  00000-0 0  9990\n"
            "2 25544  51.6000 000.0000 0001000   0.0000   0.0000 15.50000000000000"
        )
        asset = BlueAsset(name="ISS", tle=tle)
        assert asset.tle == tle


class TestRedTrack:
    """Tests for RedTrack dataclass."""

    def test_stk_name_auto_derived(self) -> None:
        """stk_name should be prefixed with RED_PREFIX."""
        track = RedTrack(name="Track01", tle="line1\nline2")
        assert track.stk_name == f"{RED_PREFIX}Track01"


class TestAccessInterval:
    """Tests for AccessInterval dataclass."""

    def test_duration_seconds(self, sample_access_interval: AccessInterval) -> None:
        """duration_seconds should return the correct interval length."""
        assert sample_access_interval.duration_seconds == 600.0

    def test_zero_duration(self) -> None:
        """duration_seconds should be 0 for same start/end."""
        t = datetime(2026, 1, 1, tzinfo=UTC)
        interval = AccessInterval(start=t, end=t)
        assert interval.duration_seconds == 0.0


class TestInterceptWindow:
    """Tests for InterceptWindow dataclass."""

    def test_fields_stored(self) -> None:
        """All constructor fields should be stored correctly."""
        start = datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 4, 12, 30, 0, tzinfo=UTC)
        window = InterceptWindow(
            start=start, end=end, min_range_km=250.5,
            blue_name="Alpha", red_name="Track01",
        )
        assert window.min_range_km == 250.5
        assert window.start == start
        assert window.end == end
        assert window.blue_name == "Alpha"
        assert window.red_name == "Track01"


class TestRunConfig:
    """Tests for RunConfig dataclass."""

    def test_run_id_auto_generated(self) -> None:
        """run_id should be auto-generated when not supplied."""
        config = RunConfig(operator="analyst", source="MANUAL")
        assert config.run_id.startswith("RUN_")
        assert len(config.run_id) > 4

    def test_explicit_run_id(self, run_config: RunConfig) -> None:
        """Explicitly supplied run_id should be used verbatim."""
        assert run_config.run_id == "RUN_TEST000001"

    def test_timestamp_utc_aware(self) -> None:
        """Auto-generated timestamp should be UTC-aware."""
        config = RunConfig(operator="analyst", source="MANUAL")
        assert config.timestamp.tzinfo is not None
