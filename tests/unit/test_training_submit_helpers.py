"""The pieces the training submit route is built from (audit F-165).

The route scored 40 for cognitive complexity and carried four integrity
defects; its level-up loop was copied verbatim into tutorial completion. It
is now composed of the helpers below, each tested on its own, and no
function in the module is over 15.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from spectre.training.scenarios import get_scenario
from spectre.web.routes import training

_ROOT = Path(__file__).resolve().parents[2]


def test_objective_ids_keep_distinct_strings_in_order() -> None:
    assert training._objective_ids('["b", "a", "b", 5, {}]') == ["b", "a"]
    assert training._objective_ids("5") == []
    assert training._objective_ids("not json") == []


class TestScoreObjectives:
    def _timed(self) -> object:
        scenario = get_scenario("planner_03_multi_constraint")
        assert scenario is not None
        return scenario

    def test_unknown_ids_score_nothing(self) -> None:
        total, axes, scored = training._score_objectives(self._timed(), ["nope"], {})
        assert (total, axes, scored) == (0, {}, [])

    def test_a_time_limited_objective_scores_in_time(self) -> None:
        total, axes, scored = training._score_objectives(self._timed(), ["obj_time_pressure"], {})
        assert (total, axes, scored) == (30, {"operational_tempo": 30.0}, ["obj_time_pressure"])

    def test_a_time_limited_objective_scores_nothing_late(self) -> None:
        total, _, scored = training._score_objectives(
            self._timed(), ["obj_time_pressure", "obj_run_engine"], {}, late=True,
        )
        assert (total, scored) == (30, ["obj_run_engine"])

    def test_a_wrong_answer_scores_nothing(self) -> None:
        scenario = get_scenario("observer_05_notso_correlation")
        assert scenario is not None
        assert training._score_objectives(scenario, ["obj_verdict"], {"obj_verdict": "noncompliant"})[0] == 0
        assert training._score_objectives(scenario, ["obj_verdict"], {"obj_verdict": " Compliant "})[0] == 45


class TestTime:
    def test_elapsed_reads_the_servers_clock_for_a_naive_start(self) -> None:
        started = (datetime.now(UTC) - timedelta(minutes=12)).replace(tzinfo=None)
        elapsed = training._elapsed_minutes(SimpleNamespace(started_at=started))  # type: ignore[arg-type]
        assert 11.9 < elapsed < 12.5

    def test_a_start_in_the_future_is_zero_not_negative(self) -> None:
        started = datetime.now(UTC) + timedelta(minutes=5)
        assert training._elapsed_minutes(SimpleNamespace(started_at=started)) == 0.0  # type: ignore[arg-type]

    def test_over_time_only_for_a_timed_scenario_past_its_limit(self) -> None:
        assert training._over_time(SimpleNamespace(time_limit_minutes=10), 10.5)
        assert not training._over_time(SimpleNamespace(time_limit_minutes=10), 10.0)
        assert not training._over_time(SimpleNamespace(time_limit_minutes=None), 9999.0)


def test_axis_change_reports_only_the_axes_that_moved() -> None:
    before = {"efficiency": 10.0, "decision_quality": 5.0}
    after = {"efficiency": 10.0, "decision_quality": 50.0, "operational_tempo": 30.0}
    assert training._axis_change(before, after) == {"decision_quality": 45.0, "operational_tempo": 30.0}


def test_level_ups_advance_through_every_level_reached() -> None:
    progress = SimpleNamespace(
        current_level=1, total_points=500, axis_points={}, tutorials_completed=["orientation"],
        scenarios_passed=3, challenges_passed=0, unlocked=[],
    )
    events, unlocked = training._apply_level_ups(progress)
    assert [e.level for e in events] == [2, 3]
    assert progress.current_level == 3
    assert "scenario:planner_03_multi_constraint" in unlocked
    assert progress.unlocked == unlocked


def test_no_function_in_the_training_routes_is_over_15() -> None:
    script = _ROOT / "scripts" / "cognitive_complexity.py"
    if not script.is_file():
        pytest.skip("scripts/ is excluded from the submission package")
    spec = importlib.util.spec_from_file_location("_cc_meter_training", script)
    assert spec is not None and spec.loader is not None
    meter = importlib.util.module_from_spec(spec)
    sys.modules["_cc_meter_training"] = meter
    spec.loader.exec_module(meter)
    source = Path(training.__file__).read_text(encoding="utf-8")
    over = [(r["name"], r["score"]) for r in meter.measure_source(source, "training.py") if r["score"] > 15]
    assert over == []
