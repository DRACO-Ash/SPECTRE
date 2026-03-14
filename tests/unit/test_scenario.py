"""Unit tests for sipc.domain.scenario.ScenarioPlanner."""

from __future__ import annotations

from sipc.domain.models import BlueAsset, RedTrack, RunConfig
from sipc.domain.scenario import ScenarioPlanner


class TestScenarioPlanner:
    """Tests for ScenarioPlanner (now using sipc.astro, no STK)."""

    def test_plan_returns_empty_list(self, run_config: RunConfig) -> None:
        """plan() returns empty until access computation is implemented."""
        planner = ScenarioPlanner(config=run_config)
        blue = [BlueAsset(name="Alpha", tle="l1\nl2")]
        red = [RedTrack(name="Track01", tle="l1\nl2")]

        windows = planner.plan(blue, red)

        assert windows == []

    def test_plan_accepts_empty_assets(self, run_config: RunConfig) -> None:
        """plan() should handle empty asset lists gracefully."""
        planner = ScenarioPlanner(config=run_config)
        windows = planner.plan([], [])
        assert windows == []
