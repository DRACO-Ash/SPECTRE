"""Unit tests for sipc.domain.scenario.ScenarioPlanner."""

from __future__ import annotations

from datetime import UTC, datetime

from sipc.domain.models import AccessInterval, BlueAsset, RedTrack, RunConfig
from sipc.domain.scenario import ScenarioPlanner
from sipc.stk_adapter.fake import FakeStkSession


class TestScenarioPlanner:
    """Tests for ScenarioPlanner using FakeStkSession."""

    def test_plan_returns_empty_when_no_access(
        self, fake_session: FakeStkSession, run_config: RunConfig
    ) -> None:
        """plan() should return an empty list when compute_access returns no intervals."""
        planner = ScenarioPlanner(session=fake_session, config=run_config)
        blue = [BlueAsset(name="Alpha", tle="l1\nl2")]
        red = [RedTrack(name="Track01", tle="l1\nl2")]

        windows = planner.plan(blue, red)

        assert windows == []

    def test_plan_creates_assets_in_session(
        self, fake_session: FakeStkSession, run_config: RunConfig
    ) -> None:
        """plan() should create both blue and red satellite objects via the session."""
        planner = ScenarioPlanner(session=fake_session, config=run_config)
        blue = [BlueAsset(name="Alpha", tle="l1\nl2")]
        red = [RedTrack(name="Track01", tle="l1\nl2")]

        planner.plan(blue, red)

        assert "B_SAT_Alpha" in fake_session.satellites
        assert "R_SAT_Track01" in fake_session.satellites

    def test_plan_sets_propagators(
        self, fake_session: FakeStkSession, run_config: RunConfig
    ) -> None:
        """plan() should call set_propagator for all assets."""
        planner = ScenarioPlanner(session=fake_session, config=run_config)
        blue = [BlueAsset(name="Alpha", tle="alpha_tle")]
        red = [RedTrack(name="Track01", tle="track_tle")]

        planner.plan(blue, red)

        assert fake_session.propagators["B_SAT_Alpha"] == "alpha_tle"
        assert fake_session.propagators["R_SAT_Track01"] == "track_tle"

    def test_plan_converts_access_to_windows(
        self,
        fake_session: FakeStkSession,
        run_config: RunConfig,
        sample_access_interval: AccessInterval,
    ) -> None:
        """plan() should convert access intervals to InterceptWindow objects."""
        fake_session.access_intervals = [sample_access_interval]
        planner = ScenarioPlanner(session=fake_session, config=run_config)
        blue = [BlueAsset(name="Alpha", tle="l1\nl2")]
        red = [RedTrack(name="Track01", tle="l1\nl2")]

        windows = planner.plan(blue, red)

        assert len(windows) == 1
        assert windows[0].start == sample_access_interval.start
        assert windows[0].end == sample_access_interval.end

    def test_plan_logs_actions_with_run_id(
        self, fake_session: FakeStkSession, run_config: RunConfig
    ) -> None:
        """plan() should log actions tagged with the correct run_id."""
        planner = ScenarioPlanner(session=fake_session, config=run_config)
        blue = [BlueAsset(name="Alpha", tle="l1\nl2")]
        red = [RedTrack(name="Track01", tle="l1\nl2")]

        planner.plan(blue, red)

        run_ids = {entry[0] for entry in fake_session.actions_log}
        assert run_config.run_id in run_ids

    def test_plan_windows_sorted_by_start(
        self, fake_session: FakeStkSession, run_config: RunConfig
    ) -> None:
        """plan() should return windows in ascending start-time order."""
        later = AccessInterval(
            start=datetime(2026, 3, 4, 14, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 4, 14, 10, 0, tzinfo=UTC),
        )
        earlier = AccessInterval(
            start=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
            end=datetime(2026, 3, 4, 12, 10, 0, tzinfo=UTC),
        )
        fake_session.access_intervals = [later, earlier]
        planner = ScenarioPlanner(session=fake_session, config=run_config)
        blue = [BlueAsset(name="Alpha", tle="l1\nl2")]
        red = [RedTrack(name="Track01", tle="l1\nl2")]

        windows = planner.plan(blue, red)

        assert windows[0].start < windows[1].start
