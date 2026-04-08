"""Unit tests for spectre.domain.scenario.ScenarioPlanner."""

from __future__ import annotations

from spectre.domain.models import BlueAsset, RedTrack, RunConfig
from spectre.domain.scenario import ScenarioPlanner


class TestScenarioPlanner:
    """Tests for ScenarioPlanner using spectre.astro propagation."""

    def test_plan_accepts_empty_assets(self, run_config: RunConfig) -> None:
        """plan() should handle empty asset lists gracefully."""
        planner = ScenarioPlanner(config=run_config)
        windows = planner.plan([], [])
        assert windows == []

    def test_plan_with_invalid_tle_skips_pair(self, run_config: RunConfig) -> None:
        """plan() should skip pairs with invalid TLEs without crashing."""
        planner = ScenarioPlanner(config=run_config)
        blue = [BlueAsset(name="Alpha", tle="bad\ntle")]
        red = [RedTrack(name="Track01", tle="bad\ntle")]
        windows = planner.plan(blue, red)
        assert windows == []
