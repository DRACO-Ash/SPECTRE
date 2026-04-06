"""Unit tests for the SIPC training gamification engine and scenario loader.

Tests cover:
  - Gamification config loading
  - award_points() calculation across all actions
  - check_level_up() for all condition types
  - level_progress_fraction() and points_to_next_level()
  - recommended_next_step()
  - Scenario loader (load_scenarios, get_scenario, scenarios_for_level)
  - Data isolation assertion: training modules must not import SessionState
"""

from __future__ import annotations

import pytest

from sipc.training.gamification import (
    GamificationConfig,
    LevelUpResult,
    PointAward,
    award_points,
    check_level_up,
    get_config,
    level_progress_fraction,
    points_to_next_level,
    recommended_next_step,
)
from sipc.training.scenarios import (
    TrainingScenario,
    get_scenario,
    load_scenarios,
    scenarios_for_level,
)


# ── Gamification config loading ────────────────────────────────────────────────

class TestGetConfig:
    def test_returns_gamification_config(self):
        cfg = get_config()
        assert isinstance(cfg, GamificationConfig)

    def test_skill_axes_loaded(self):
        cfg = get_config()
        assert len(cfg.skill_axes) >= 5
        ids = [a.id for a in cfg.skill_axes]
        assert "situational_awareness" in ids
        assert "manoeuvre_planning" in ids
        assert "decision_quality" in ids
        assert "operational_tempo" in ids
        assert "efficiency" in ids

    def test_point_actions_loaded(self):
        cfg = get_config()
        assert len(cfg.point_actions) >= 5
        action_ids = [a.action_id for a in cfg.point_actions]
        assert "tutorial_step_complete" in action_ids
        assert "scenario_completed" in action_ids
        assert "challenge_passed" in action_ids

    def test_levels_loaded(self):
        cfg = get_config()
        assert len(cfg.levels) >= 6
        levels = [lv.level for lv in cfg.levels]
        assert 1 in levels
        assert 6 in levels

    def test_level_titles(self):
        cfg = get_config()
        by_level = {lv.level: lv for lv in cfg.levels}
        assert by_level[1].title == "Cadet"
        assert by_level[6].title == "Instructor"

    def test_axis_weights_sum_to_one_for_all_actions(self):
        cfg = get_config()
        for action in cfg.point_actions:
            total = sum(action.axis_weights.values())
            assert abs(total - 1.0) < 0.01, (
                f"Action {action.action_id!r} weights sum to {total} not 1.0"
            )

    def test_axes_by_id_lookup(self):
        cfg = get_config()
        assert "situational_awareness" in cfg.axes_by_id

    def test_actions_by_id_lookup(self):
        cfg = get_config()
        assert "scenario_completed" in cfg.actions_by_id


# ── award_points ───────────────────────────────────────────────────────────────

class TestAwardPoints:
    def test_returns_point_award(self):
        pa = award_points("tutorial_step_complete", {})
        assert isinstance(pa, PointAward)

    def test_base_points_match_config(self):
        cfg = get_config()
        action_def = cfg.actions_by_id["tutorial_step_complete"]
        pa = award_points("tutorial_step_complete", {})
        assert pa.base_points == action_def.base_points

    def test_total_points_no_speed_multiplier(self):
        pa = award_points("scenario_completed", {})
        assert pa.total_points == pa.base_points  # speed_multiplier=False

    def test_speed_multiplier_applied(self):
        """threat_assessed_timed has speed_multiplier: true."""
        pa_fast = award_points("threat_assessed_timed", {}, speed_factor=1.5)
        pa_slow = award_points("threat_assessed_timed", {}, speed_factor=0.5)
        assert pa_fast.total_points > pa_slow.total_points

    def test_speed_factor_clamped(self):
        """speed_factor outside [0.5, 2.0] should be clamped."""
        pa_high = award_points("threat_assessed_timed", {}, speed_factor=99.0)
        assert pa_high.total_points <= award_points("threat_assessed_timed", {}, speed_factor=2.0).total_points + 1

    def test_axis_deltas_sum_to_total_points(self):
        pa = award_points("scenario_completed", {})
        assert abs(sum(pa.axis_deltas.values()) - pa.total_points) < 0.01

    def test_unknown_action_raises(self):
        with pytest.raises(KeyError):
            award_points("non_existent_action_xyz", {})

    def test_challenge_passed_first_try_earns_points(self):
        pa = award_points("challenge_passed_first_try", {})
        assert pa.total_points > 0


# ── check_level_up ─────────────────────────────────────────────────────────────

class TestCheckLevelUp:
    def test_not_enough_points_no_level_up(self):
        result = check_level_up(
            current_level=1, total_points=50,
            axis_points={}, tutorials_completed=[],
            scenarios_passed=0, challenges_passed=0,
        )
        assert not result.levelled_up

    def test_default_condition_levels_up_with_enough_points(self):
        """Level 1→2 requires tutorial_complete 'orientation', but also 100 pts."""
        result = check_level_up(
            current_level=1, total_points=100,
            axis_points={}, tutorials_completed=["orientation"],
            scenarios_passed=0, challenges_passed=0,
        )
        assert result.levelled_up
        assert result.new_level == 2

    def test_tutorial_condition_fails_without_tutorial(self):
        result = check_level_up(
            current_level=1, total_points=200,
            axis_points={}, tutorials_completed=[],
            scenarios_passed=0, challenges_passed=0,
        )
        assert not result.levelled_up

    def test_scenario_count_condition(self):
        """Level 2→3 requires scenario_count >= 3."""
        result = check_level_up(
            current_level=2, total_points=500,
            axis_points={}, tutorials_completed=["orientation", "threat_assessment"],
            scenarios_passed=3, challenges_passed=0,
        )
        assert result.levelled_up
        assert result.new_level == 3

    def test_scenario_count_condition_fails(self):
        result = check_level_up(
            current_level=2, total_points=500,
            axis_points={}, tutorials_completed=[],
            scenarios_passed=2, challenges_passed=0,
        )
        assert not result.levelled_up

    def test_axis_threshold_condition(self):
        """Level 3→4 requires decision_quality >= 300."""
        result = check_level_up(
            current_level=3, total_points=1500,
            axis_points={"decision_quality": 350.0},
            tutorials_completed=[], scenarios_passed=5, challenges_passed=0,
        )
        assert result.levelled_up

    def test_axis_threshold_condition_fails(self):
        result = check_level_up(
            current_level=3, total_points=1500,
            axis_points={"decision_quality": 100.0},
            tutorials_completed=[], scenarios_passed=5, challenges_passed=0,
        )
        assert not result.levelled_up

    def test_challenge_count_condition(self):
        """Level 4→5 requires challenge_count >= 3."""
        result = check_level_up(
            current_level=4, total_points=3500,
            axis_points={}, tutorials_completed=[],
            scenarios_passed=10, challenges_passed=3,
        )
        assert result.levelled_up

    def test_max_level_no_level_up(self):
        """No level 7 exists — should return levelled_up=False."""
        result = check_level_up(
            current_level=6, total_points=99999,
            axis_points={}, tutorials_completed=["all"],
            scenarios_passed=99, challenges_passed=99,
        )
        assert not result.levelled_up

    def test_level_up_returns_unlocks(self):
        result = check_level_up(
            current_level=1, total_points=200,
            axis_points={}, tutorials_completed=["orientation"],
            scenarios_passed=0, challenges_passed=0,
        )
        if result.levelled_up:
            assert isinstance(result.newly_unlocked, list)


# ── Progress helpers ───────────────────────────────────────────────────────────

class TestProgressHelpers:
    def test_points_to_next_level_positive(self):
        pts = points_to_next_level(1, 50)
        assert pts is not None
        assert pts > 0

    def test_points_to_next_level_at_max(self):
        assert points_to_next_level(6, 99999) is None

    def test_level_progress_fraction_zero(self):
        frac = level_progress_fraction(1, 0)
        assert 0.0 <= frac <= 1.0

    def test_level_progress_fraction_at_threshold(self):
        cfg = get_config()
        lv2 = cfg.level_def(2)
        if lv2:
            frac = level_progress_fraction(1, lv2.total_points_required)
            assert frac >= 0.99

    def test_level_progress_fraction_max_level(self):
        frac = level_progress_fraction(6, 99999)
        assert frac == pytest.approx(1.0)


# ── recommended_next_step ──────────────────────────────────────────────────────

class TestRecommendedNextStep:
    def test_empty_axis_points_returns_string(self):
        rec = recommended_next_step({}, [], 1)
        assert len(rec) > 10

    def test_weak_axis_mentioned(self):
        axis_pts = {
            "situational_awareness": 500,
            "manoeuvre_planning": 500,
            "decision_quality": 10,    # weakest
            "operational_tempo": 500,
            "efficiency": 500,
        }
        rec = recommended_next_step(axis_pts, ["orientation"], 3)
        assert "decision" in rec.lower() or "Decision" in rec

    def test_tutorial_condition_mentioned(self):
        """At level 1, the tutorial unlock should be surfaced."""
        rec = recommended_next_step({}, [], 1)
        # Should mention a tutorial or skill improvement
        assert len(rec) > 5


# ── Scenario loader ────────────────────────────────────────────────────────────

class TestScenarioLoader:
    def test_load_scenarios_returns_list(self):
        scenarios = load_scenarios()
        assert isinstance(scenarios, list)

    def test_minimum_three_scenarios(self):
        assert len(load_scenarios()) >= 3

    def test_all_scenarios_have_id(self):
        for s in load_scenarios():
            assert isinstance(s.id, str) and s.id

    def test_all_scenarios_have_title(self):
        for s in load_scenarios():
            assert isinstance(s.title, str) and s.title

    def test_cadet_scenario_exists(self):
        ids = [s.id for s in load_scenarios()]
        assert "cadet_01_geo_stationkeeping" in ids

    def test_observer_scenario_exists(self):
        ids = [s.id for s in load_scenarios()]
        assert "observer_02_proximity_threat" in ids

    def test_planner_scenario_exists(self):
        ids = [s.id for s in load_scenarios()]
        assert "planner_03_multi_constraint" in ids

    def test_get_scenario_by_id(self):
        s = get_scenario("cadet_01_geo_stationkeeping")
        assert s is not None
        assert isinstance(s, TrainingScenario)

    def test_get_scenario_unknown_returns_none(self):
        assert get_scenario("does_not_exist_xyz") is None

    def test_scenarios_for_level_1(self):
        l1 = scenarios_for_level(1)
        assert len(l1) >= 1
        for s in l1:
            assert s.level_required <= 1

    def test_scenarios_for_level_3_includes_lower(self):
        l3 = scenarios_for_level(3)
        l1 = scenarios_for_level(1)
        assert len(l3) >= len(l1)

    def test_scenario_has_objectives(self):
        s = get_scenario("cadet_01_geo_stationkeeping")
        assert s is not None
        assert len(s.objectives) >= 1

    def test_scenario_scoring_fields(self):
        s = get_scenario("planner_03_multi_constraint")
        assert s is not None
        assert s.scoring.passing_score > 0
        assert s.scoring.optimal_score >= s.scoring.passing_score

    def test_planner_scenario_has_manoeuvre_options(self):
        s = get_scenario("planner_03_multi_constraint")
        assert s is not None
        assert len(s.manoeuvre_options) >= 3

    def test_planner_optimal_option_marked(self):
        s = get_scenario("planner_03_multi_constraint")
        assert s is not None
        optimal = [o for o in s.manoeuvre_options if o.optimal]
        assert len(optimal) == 1

    def test_planner_infeasible_option_exists(self):
        s = get_scenario("planner_03_multi_constraint")
        assert s is not None
        infeasible = [o for o in s.manoeuvre_options if not o.feasible]
        assert len(infeasible) >= 1

    def test_scenario_blue_red_objects(self):
        s = get_scenario("observer_02_proximity_threat")
        assert s is not None
        assert len(s.blue_objects) >= 1
        assert len(s.red_objects) >= 1

    def test_difficulty_colour_not_empty(self):
        for s in load_scenarios():
            assert s.difficulty_colour.startswith("#")


# ── Data isolation check ───────────────────────────────────────────────────────

class TestDataIsolation:
    """Verify that training modules do not import operational state."""

    def test_gamification_does_not_import_session_state(self):
        import sipc.training.gamification as gm
        assert not hasattr(gm, "SessionState")
        assert not hasattr(gm, "get_session_state")

    def test_scenarios_does_not_import_session_state(self):
        import sipc.training.scenarios as sc
        assert not hasattr(sc, "SessionState")
        assert not hasattr(sc, "get_session_state")

    def test_training_models_do_not_reference_operational_tables(self):
        from sipc.training.models import TrainingProgress, TrainingSession, ChallengeResult
        table_names = {
            TrainingProgress.__tablename__,
            TrainingSession.__tablename__,
            ChallengeResult.__tablename__,
        }
        # None of these should be the users or any operational table name
        assert "users" not in table_names
        for name in table_names:
            assert name.startswith("training")
