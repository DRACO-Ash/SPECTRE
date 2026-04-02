"""Unit tests for sipc.domain.maneuver_planner validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sipc.domain.maneuver_planner import ManeuverPlannerError, validate_search_config
from sipc.domain.models import (
    BurnLocation,
    BurnType,
    ManeuverSearchConfig,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def config() -> ManeuverSearchConfig:
    """A valid, fully-populated search config for use across tests."""
    return ManeuverSearchConfig(
        red_sat="R_SAT_TrackA",
        blue_sat="B_SAT_Alpha",
        search_window_start=datetime(2026, 3, 6, 0, 0, 0, tzinfo=UTC),
        search_window_stop=datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC),
        max_delta_v_km_s=2.0,
        burn_types=[BurnType.IMPULSIVE],
        burn_locations=[BurnLocation.APOGEE, BurnLocation.ASCENDING_NODE],
    )


# ── Validation tests ──────────────────────────────────────────────────────────

class TestManeuverPlannerValidation:

    def test_valid_config_passes(self, config: ManeuverSearchConfig) -> None:
        validate_search_config(config)  # should not raise

    def test_empty_red_sat_raises(self, config: ManeuverSearchConfig) -> None:
        config.red_sat = ""
        with pytest.raises(ManeuverPlannerError, match="red_sat"):
            validate_search_config(config)

    def test_empty_blue_sat_raises(self, config: ManeuverSearchConfig) -> None:
        config.blue_sat = "  "
        with pytest.raises(ManeuverPlannerError, match="blue_sat"):
            validate_search_config(config)

    def test_same_red_and_blue_raises(self, config: ManeuverSearchConfig) -> None:
        config.blue_sat = config.red_sat
        with pytest.raises(ManeuverPlannerError, match="must differ"):
            validate_search_config(config)

    def test_window_stop_before_start_raises(self, config: ManeuverSearchConfig) -> None:
        config.search_window_stop = config.search_window_start - timedelta(seconds=1)
        with pytest.raises(ManeuverPlannerError, match="after"):
            validate_search_config(config)

    def test_window_stop_equal_start_raises(self, config: ManeuverSearchConfig) -> None:
        config.search_window_stop = config.search_window_start
        with pytest.raises(ManeuverPlannerError, match="after"):
            validate_search_config(config)

    def test_zero_max_dv_raises(self, config: ManeuverSearchConfig) -> None:
        config.max_delta_v_km_s = 0.0
        with pytest.raises(ManeuverPlannerError, match="positive"):
            validate_search_config(config)

    def test_negative_max_dv_raises(self, config: ManeuverSearchConfig) -> None:
        config.max_delta_v_km_s = -1.0
        with pytest.raises(ManeuverPlannerError, match="positive"):
            validate_search_config(config)

    def test_no_burn_types_raises(self, config: ManeuverSearchConfig) -> None:
        config.burn_types = []
        with pytest.raises(ManeuverPlannerError, match="BurnType"):
            validate_search_config(config)

    def test_no_burn_locations_raises(self, config: ManeuverSearchConfig) -> None:
        config.burn_locations = []
        with pytest.raises(ManeuverPlannerError, match="BurnLocation"):
            validate_search_config(config)
