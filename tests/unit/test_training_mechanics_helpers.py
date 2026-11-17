"""The helpers behind the 0.47.0 training fixes, each on its own."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from spectre.training.scenarios import (
    ScenarioObjective,
    content_title,
    get_scenario,
    load_scenarios,
    with_titles,
    workflow_steps,
)
from spectre.web.routes import training


class TestWorkflowSteps:
    """Audit 2-5, 3-17: folded YAML ran the numbered steps together."""

    def test_folded_steps_split_on_their_numbers(self) -> None:
        intro, steps = workflow_steps("Read first. 1. Open the console. 2. Pick BLUE-02,\n   then RED-01. 3. Submit.")
        assert intro == "Read first."
        assert steps == ["Open the console.", "Pick BLUE-02, then RED-01.", "Submit."]

    def test_figures_and_out_of_order_numbers_are_not_steps(self) -> None:
        _, steps = workflow_steps("1. Drift 0.5 deg from slot 3. today, or 1. again. 2. Then this.")
        assert steps == ["Drift 0.5 deg from slot 3. today, or 1. again.", "Then this."]

    def test_lettered_sub_items_keep_their_own_lines(self) -> None:
        _, steps = workflow_steps("1. Check:\n   a. Timing.\n   b. Size.\n2. Done.")
        assert steps == ["Check:\na. Timing.\nb. Size.", "Done."]

    def test_text_with_no_step_one_is_all_intro(self) -> None:
        assert workflow_steps("Just prose.") == ("Just prose.", [])

    def test_every_shipped_workflow_numbers_its_steps_from_one(self) -> None:
        for scenario in load_scenarios():
            if scenario.tool_workflow:
                assert scenario.workflow[1], scenario.id


class TestTitles:
    """Audit 1-24, 4-16."""

    def test_unlock_entries_name_their_content(self) -> None:
        assert content_title("challenge:analyst_gauntlet") == "Challenge: Analyst Gauntlet — Back-to-Back Sprint"
        assert content_title("tutorial:orientation") == "Tutorial: Orientation — Welcome to SPECTRE"
        assert content_title("cadet_01_geo_stationkeeping") == get_scenario("cadet_01_geo_stationkeeping").title  # type: ignore[union-attr]
        assert content_title("scenario:no_such") == "Scenario: no_such"

    def test_scenario_ids_in_text_become_titles(self) -> None:
        title = get_scenario("planner_03_multi_constraint").title  # type: ignore[union-attr]
        assert with_titles("Complete planner_03_multi_constraint above") == f"Complete {title} above"


class TestAnswers:
    """Audit 3-3, 1-16."""

    @pytest.mark.parametrize("given", ["T+18h", "t + 18 h", "18 h", "18h", "18 hours", "18.0", " 18 "])
    def test_hours_are_read_with_or_without_t_plus_and_unit(self, given: str) -> None:
        obj = ScenarioObjective("o", "d", "a", 10, answer="18.0", tolerance=2.0, unit="hours")
        assert training._answer_ok(obj, given)

    def test_only_the_objectives_unit_is_stripped(self) -> None:
        obj = ScenarioObjective("o", "d", "a", 10, answer="2.0", tolerance=1.0, unit="km")
        assert training._answer_ok(obj, "2 km")
        assert not training._answer_ok(obj, "2 h")
        assert not training._answer_ok(obj, "T+2"), "T+ is a time, read for an answer in hours only"

    @pytest.mark.parametrize("given", ["1_8", "nan", "inf", "1.8e1", "18e0h", "T-18", "T+", "", "18 km", "1 8"])
    def test_only_a_plain_number_is_read(self, given: str) -> None:
        obj = ScenarioObjective("o", "d", "a", 10, answer="18.0", tolerance=2.0, unit="hours")
        assert not training._answer_ok(obj, given)

    def test_a_signed_number_is_read(self) -> None:
        obj = ScenarioObjective("o", "d", "a", 10, answer="18.0", tolerance=2.0, unit="hours")
        assert training._answer_ok(obj, "+18")
        assert training._answer_ok(obj, "T+19.5 h")

    def test_degrees_with_a_symbol(self) -> None:
        obj = ScenarioObjective("o", "d", "a", 10, answer="45.0", tolerance=0.5, unit="degrees")
        assert training._answer_ok(obj, "45.0°")

    def test_an_answer_ticks_its_objective(self) -> None:
        scenario = get_scenario("cadet_01_geo_stationkeeping")
        ticked = training._ticked(scenario, ["obj_load"], {"obj_read_elements": "45", "obj_confirm_dv": " "})
        assert ticked == ["obj_load", "obj_read_elements"]

    def test_the_accepted_answer_reads_as_the_debrief_shows_it(self) -> None:
        assert ScenarioObjective("o", "d", "a", 1, answer="45.0", tolerance=0.5, unit="degrees").accepted_answer \
            == "45.0 ± 0.5 degrees"
        assert ScenarioObjective("o", "d", "a", 1, answer="compliant").accepted_answer == "Compliant"
        assert ScenarioObjective("o", "d", "a", 1).accepted_answer == ""


class TestAwardsNeedAPass:
    """Audit G-1, 1-20."""

    def test_a_fail_earns_nothing(self) -> None:
        assert training._award({}, is_scored=True, passed=False, first_try=True, challenge=True) == (0, {})

    def test_a_pass_earns_the_scenario_award(self) -> None:
        earned, axes = training._award({}, is_scored=True, passed=True, first_try=False, challenge=False)
        assert earned == 150
        assert round(axes["decision_quality"]) == 45


class TestScenarioTime:
    """Audit 2-7, X3."""

    def test_the_epoch_is_utc(self) -> None:
        scenario = get_scenario("cadet_01_geo_stationkeeping")
        assert scenario is not None
        assert scenario.epoch == datetime(2025, 6, 15, tzinfo=UTC)

    def test_a_start_sets_the_window_on_the_state_given(self) -> None:
        state = SimpleNamespace(scenario_start=None, scenario_stop=None)
        second = get_scenario("cadet_02_leo_debris_conjunction")
        training._set_scenario_time(state, get_scenario("cadet_01_geo_stationkeeping"))  # type: ignore[arg-type]
        training._set_scenario_time(state, second)  # type: ignore[arg-type]
        assert (state.scenario_start, state.scenario_stop) == (
            datetime(2025, 6, 10, 8, tzinfo=UTC), datetime(2025, 6, 11, 8, tzinfo=UTC))

    def test_a_scenario_with_no_readable_epoch_leaves_the_time_alone(self) -> None:
        state = SimpleNamespace(scenario_start=None, scenario_stop=None)
        training._set_scenario_time(state, SimpleNamespace(epoch=None))  # type: ignore[arg-type]
        assert state.scenario_start is None


class TestEachSideReadsItsOwnWindow:
    """0.47.0 review B1: a training request reads the training state, every other request the operational one."""

    def test_get_session_state_follows_the_request(self) -> None:
        from spectre.web.models import SessionKey
        from spectre.web.planning_state import (
            discard_training_state,
            get_session_state,
            get_training_state,
            training_request,
        )
        from spectre.web.routes.udl import _tle_epoch_metadata

        key = SessionKey(user_id=424_242, session_id="b1-window")
        try:
            get_session_state(key).scenario_start = datetime(2026, 1, 1, tzinfo=UTC)
            get_training_state(key).scenario_start = datetime(2025, 6, 15, tzinfo=UTC)
            line1 = get_scenario("cadet_01_geo_stationkeeping").objects[0].tle_line1  # type: ignore[union-attr]

            # The UDL epoch-mode reader measures against whichever window its request reads.
            _, operational_age = _tle_epoch_metadata(line1, get_session_state(key).scenario_start)
            with training_request():
                assert get_session_state(key) is get_training_state(key)
                _, training_age = _tle_epoch_metadata(line1, get_session_state(key).scenario_start)
            assert get_session_state(key) is not get_training_state(key)
            assert training_age is not None and training_age < 1.0
            assert operational_age is not None and operational_age > 150.0
        finally:
            discard_training_state(key)

    def test_discarding_leaves_the_operational_state(self) -> None:
        from spectre.web.models import SessionKey
        from spectre.web.planning_state import discard_training_state, get_session_state, get_training_state

        key = SessionKey(user_id=424_243, session_id="b1-discard")
        operational = get_session_state(key)
        training_state = get_training_state(key)
        training_state.scenario_start = datetime(2025, 6, 15, tzinfo=UTC)
        discard_training_state(key)
        assert get_session_state(key) is operational
        assert get_training_state(key) is not training_state
        assert get_training_state(key).scenario_start is None
        discard_training_state(key)


class TestTheTrainingFrame:
    """Review B1, audit 1-23: which requests are training requests."""

    def test_by_path_header_query_or_sec_fetch_dest(self) -> None:
        from spectre.web.training_frame import is_training_request

        assert is_training_request("/training", {}, "")
        assert is_training_request("/training/scenario/x/start", {}, "")
        assert is_training_request("/plan", {"x-spectre-frame": "training"}, "")
        assert is_training_request("/", {}, "frame=training")
        assert is_training_request("/", {"sec-fetch-dest": "iframe"}, "")
        assert not is_training_request("/", {}, "")
        assert not is_training_request("/trainingx", {}, "")
        assert not is_training_request("/", {"sec-fetch-dest": "document"}, "frame=other")
