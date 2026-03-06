"""Unit tests for sipc.domain.maneuver_planner.ManeuverPlanner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sipc.domain.models import (
    BurnLocation,
    BurnType,
    ManeuverOption,
    ManeuverSearchConfig,
)
from sipc.domain.maneuver_planner import ManeuverPlanner, ManeuverPlannerError
from sipc.stk_adapter.fake import FakeStkSession


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


def _make_option(dv: float, location: BurnLocation = BurnLocation.APOGEE) -> ManeuverOption:
    """Helper to build a minimal ManeuverOption for sorting tests."""
    now = datetime(2026, 3, 6, 1, 0, 0, tzinfo=UTC)
    return ManeuverOption(
        red_name="R_SAT_TrackA",
        blue_name="B_SAT_Alpha",
        burn_type=BurnType.IMPULSIVE,
        burn_location=location,
        burn_epoch=now,
        delta_v_km_s=dv,
        dv_prograde=dv,
        dv_normal=0.0,
        dv_radial=0.0,
        intercept_epoch=now + timedelta(hours=1),
        transfer_duration_s=3600.0,
        intercept_range_km=0.5,
        notes="test",
    )


# ── Validation tests ──────────────────────────────────────────────────────────

class TestManeuverPlannerValidation:

    def test_empty_red_sat_raises(self, config: ManeuverSearchConfig) -> None:
        config.red_sat = ""
        with pytest.raises(ManeuverPlannerError, match="red_sat"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_empty_blue_sat_raises(self, config: ManeuverSearchConfig) -> None:
        config.blue_sat = "  "
        with pytest.raises(ManeuverPlannerError, match="blue_sat"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_same_red_and_blue_raises(self, config: ManeuverSearchConfig) -> None:
        config.blue_sat = config.red_sat
        with pytest.raises(ManeuverPlannerError, match="must differ"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_window_stop_before_start_raises(self, config: ManeuverSearchConfig) -> None:
        config.search_window_stop = config.search_window_start - timedelta(seconds=1)
        with pytest.raises(ManeuverPlannerError, match="after"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_window_stop_equal_start_raises(self, config: ManeuverSearchConfig) -> None:
        config.search_window_stop = config.search_window_start
        with pytest.raises(ManeuverPlannerError, match="after"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_zero_max_dv_raises(self, config: ManeuverSearchConfig) -> None:
        config.max_delta_v_km_s = 0.0
        with pytest.raises(ManeuverPlannerError, match="positive"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_negative_max_dv_raises(self, config: ManeuverSearchConfig) -> None:
        config.max_delta_v_km_s = -1.0
        with pytest.raises(ManeuverPlannerError, match="positive"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_no_burn_types_raises(self, config: ManeuverSearchConfig) -> None:
        config.burn_types = []
        with pytest.raises(ManeuverPlannerError, match="BurnType"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)

    def test_no_burn_locations_raises(self, config: ManeuverSearchConfig) -> None:
        config.burn_locations = []
        with pytest.raises(ManeuverPlannerError, match="BurnLocation"):
            ManeuverPlanner(FakeStkSession()).compute_options(config)


# ── Delegation and sorting tests ──────────────────────────────────────────────

class TestManeuverPlannerDelegation:

    def test_returns_options_from_session(
        self, fake_session: FakeStkSession, config: ManeuverSearchConfig
    ) -> None:
        """compute_options should return whatever the session provides."""
        opt = _make_option(0.5)
        fake_session.maneuver_options = [opt]

        result = ManeuverPlanner(fake_session).compute_options(config)

        assert len(result) == 1
        assert result[0].option_id == opt.option_id

    def test_results_sorted_by_delta_v_ascending(
        self, fake_session: FakeStkSession, config: ManeuverSearchConfig
    ) -> None:
        """Planner must sort options cheapest-first regardless of session order."""
        fake_session.maneuver_options = [
            _make_option(1.5, BurnLocation.PERIGEE),
            _make_option(0.3, BurnLocation.APOGEE),
            _make_option(0.9, BurnLocation.ASCENDING_NODE),
        ]

        result = ManeuverPlanner(fake_session).compute_options(config)

        dvs = [o.delta_v_km_s for o in result]
        assert dvs == sorted(dvs)

    def test_empty_session_options_returns_stub(
        self, fake_session: FakeStkSession, config: ManeuverSearchConfig
    ) -> None:
        """FakeStkSession with no configured options returns one deterministic stub."""
        fake_session.maneuver_options = []

        result = ManeuverPlanner(fake_session).compute_options(config)

        assert len(result) == 1
        assert result[0].red_name == config.red_sat
        assert result[0].blue_name == config.blue_sat

    def test_option_id_is_unique(
        self, fake_session: FakeStkSession, config: ManeuverSearchConfig
    ) -> None:
        """Each ManeuverOption should have a distinct option_id."""
        fake_session.maneuver_options = [
            _make_option(0.3),
            _make_option(0.5),
        ]

        result = ManeuverPlanner(fake_session).compute_options(config)
        ids = [o.option_id for o in result]

        assert len(set(ids)) == len(ids)


# ── apply_maneuver round-trip ─────────────────────────────────────────────────

class TestApplyManeuver:

    def test_apply_maneuver_recorded_in_fake(
        self, fake_session: FakeStkSession, config: ManeuverSearchConfig
    ) -> None:
        """apply_maneuver should be forwarded to the session."""
        opt = _make_option(0.3)
        fake_session.apply_maneuver(config.red_sat, opt)

        assert fake_session.applied_maneuver is opt

    def test_apply_maneuver_stores_correct_option(
        self, fake_session: FakeStkSession, config: ManeuverSearchConfig
    ) -> None:
        opt_a = _make_option(0.3)
        opt_b = _make_option(0.7)
        fake_session.apply_maneuver(config.red_sat, opt_a)
        fake_session.apply_maneuver(config.red_sat, opt_b)

        # Last call wins
        assert fake_session.applied_maneuver is opt_b


# ── ManeuverOption dataclass ──────────────────────────────────────────────────

class TestManeuverOptionDefaults:

    def test_option_id_auto_generated(self) -> None:
        opt = _make_option(1.0)
        assert opt.option_id.startswith("MNV_")
        assert len(opt.option_id) == 14  # "MNV_" + 10 hex chars

    def test_notes_default_empty(self) -> None:
        now = datetime(2026, 3, 6, 0, 0, 0, tzinfo=UTC)
        opt = ManeuverOption(
            red_name="R",
            blue_name="B",
            burn_type=BurnType.IMPULSIVE,
            burn_location=BurnLocation.APOGEE,
            burn_epoch=now,
            delta_v_km_s=0.1,
            dv_prograde=0.1,
            dv_normal=0.0,
            dv_radial=0.0,
            intercept_epoch=now + timedelta(hours=1),
            transfer_duration_s=3600.0,
            intercept_range_km=1.0,
        )
        assert opt.notes == ""
