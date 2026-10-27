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

    def test_windows_open_and_close_with_the_range(self, run_config: RunConfig) -> None:
        """Two ISS-like orbits 5 degrees apart in RAAN close inside 500 km twice
        an orbit, so the planner reports a series of closed windows."""
        line1 = "1 25544U 98067A   26290.50000000  .00016717  00000-0  10270-3 0  9005"
        line2 = "2 25544  51.6400 {raan} 0006317  69.9862  25.2906 15.49541392 10001"
        blue = [BlueAsset(name="Alpha", tle=f"{line1}\n{line2.format(raan='208.9163')}")]
        red = [RedTrack(name="Track01", tle=f"{line1}\n{line2.format(raan='213.9163')}")]
        windows = ScenarioPlanner(config=run_config).plan(blue, red)
        assert len(windows) > 10
        assert all(w.start < w.end and w.min_range_km < 500.0 for w in windows)
        assert windows == sorted(windows, key=lambda w: w.start)
