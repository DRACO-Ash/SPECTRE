"""Every entry in gamification.yaml does something (audit F-169).

The file invited tuning "without changing any Python code", but six of its
nine point actions and its efficiency threshold were never read; its
scenario unlock lists were ignored in favour of each scenario's own
level_required; level 2 announced three Level 3 scenarios and level 6 two
challenges that do not exist.
"""

from __future__ import annotations

from pathlib import Path

from spectre.training.gamification import (
    GamificationConfig,
    LevelDef,
    LevelUnlockCondition,
    get_config,
    unlock_problems,
)

_ROUTES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "routes" / "training.py"


def _level(level: int, *unlocks: str) -> LevelDef:
    return LevelDef(level, "t", "d", 0, LevelUnlockCondition("default"), list(unlocks))


def test_every_point_action_is_awarded_by_the_routes() -> None:
    routes = _ROUTES.read_text(encoding="utf-8")
    unawarded = [a.action_id for a in get_config().point_actions if f'"{a.action_id}"' not in routes]
    assert unawarded == []


def test_the_unlock_lists_match_the_scenarios_and_tutorials() -> None:
    assert unlock_problems(get_config()) == []


class TestTheCheckFindsWhatWasWrong:
    """The checker itself, on the defects the shipped file had."""

    def _problems(self, *levels: LevelDef) -> list[str]:
        live = get_config()
        # Keep the live levels' announcements so only the planted defect differs.
        planted = {lv.level for lv in levels}
        kept = [lv for lv in live.levels if lv.level not in planted]
        return unlock_problems(GamificationConfig(live.skill_axes, live.point_actions, [*kept, *levels]))

    def test_a_scenario_announced_below_its_level(self) -> None:
        live = get_config().level_def(2)
        assert live is not None
        problems = self._problems(_level(2, *live.unlocks, "scenario:observer_03_geo_cola_budget"))
        assert "level 2 unlocks scenario:observer_03_geo_cola_budget, but the scenario requires level 3" in problems
        assert "scenario observer_03_geo_cola_budget is announced 2 times, not once" in problems

    def test_a_challenge_that_does_not_exist(self) -> None:
        problems = self._problems(_level(6, "challenge:instructor_multi_threat"))
        assert problems == ["level 6 unlocks challenge:instructor_multi_threat, which does not exist"]

    def test_a_challenge_listed_as_a_scenario(self) -> None:
        live = get_config().level_def(5)
        assert live is not None
        entries = [e.replace("challenge:planner_challenge", "scenario:planner_challenge") for e in live.unlocks]
        problems = self._problems(_level(5, *entries))
        assert problems == [
            "level 5 lists scenario:planner_challenge_theatre_defence, but its challenge flag says otherwise",
        ]
