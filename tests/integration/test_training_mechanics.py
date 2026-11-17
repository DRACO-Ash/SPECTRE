"""The training system's mechanics, as the 0.47.0 training audit found them.

● Review B1: training shared the sign-in's planning state, so its objects and
  epoch reached every operations tab. It now has a state of its own.
● X3, 2-7, 4-8: a scenario never set the console's scenario time, so every
  tool propagated its synthetic objects to today, months past their epoch.
● 1-21: scenario objects left the planning lists only through the two Return
  to Operations buttons; a new scenario, Reset, Abandon and Submit left them.
● G-1, 1-20: a scored submission that failed, even with nothing ticked,
  earned 150 points and axis points, and could level the operator up.
● 4-7: a timed challenge submitted after its limit still passed.
● G-3: Abandon left the attempt open, so the next one lost the first-try bonus.
● 1-18, G-4: nothing told the page to refresh after a completion or a submit.
● 1-16: the debrief did not list the objectives.
● 3-3: "T+18h" and "18h" were refused for an answer in hours.
● 1-19: the advice and the sidebar hid every level condition but points.
● 1-23, 1-24, 1-25, 1-26, 2-5: the nested Training link, ids for titles, US
  dates, readable locked tutorials and run-together workflow steps.

Each operator here is created for its test, so its progress is its own.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from spectre.training.scenarios import get_scenario
from tests.integration.conftest import session_state
from tests.integration.test_training_integrity import (
    _age_attempt,
    _attempt,
    _operator,
    _post,
    _progress,
    _promote,
    _start,
    _submit,
)

_CADET = "cadet_01_geo_stationkeeping"
_CADET_2 = "cadet_02_leo_debris_conjunction"
_TIMED_CHALLENGE = "operator_timed_full_cycle"
_HOURS = "observer_03_geo_cola_budget"
#: cadet_01 passed: 10 + 20 + 30 against a pass of 50.
_CADET_PASS = {"objectives_completed": '["obj_load"]', "answer_obj_read_elements": "45",
               "answer_obj_confirm_dv": "2"}


def _objects(scenario_id: str) -> set[str]:
    scenario = get_scenario(scenario_id)
    assert scenario is not None
    return {o.name for o in scenario.objects}


def _get(client: TestClient, cookie: str, path: str) -> Any:
    return client.get(path, cookies={"spectre_session": cookie})


def _flat(resp: Any) -> str:
    return " ".join(resp.content.decode().split())


def _open_sessions(client: TestClient, name: str) -> int:
    """How many training sessions *name* has open."""
    from sqlalchemy import select

    from spectre.training.models import TrainingSession
    from tests.integration.test_training_integrity import _db

    async def read(session: Any) -> int:
        rows = (await session.execute(select(TrainingSession).where(
            TrainingSession.username == name, TrainingSession.ended_at.is_(None)))).scalars().all()
        return len(rows)

    return int(_db(client, read))


def _give_points(client: TestClient, name: str, points: int) -> None:
    """Set *name*'s total points, as earlier awards would have."""
    from sqlalchemy import select

    from spectre.training.models import TrainingProgress
    from tests.integration.test_training_integrity import _db

    async def write(session: Any) -> None:
        row = (await session.execute(select(TrainingProgress).where(TrainingProgress.username == name))).scalar_one()
        row.total_points = points
        await session.commit()

    _db(client, write)


def _key(cookie: str) -> Any:
    from spectre.web.auth import session_key_for

    key = session_key_for(cookie)
    assert key is not None
    return key


def _training_state(cookie: str) -> Any:
    """The sign-in's training planning state, where training puts everything (0.47.0 review B1)."""
    from spectre.web.planning_state import get_training_state

    return get_training_state(_key(cookie))


def _names(cookie: str) -> set[str]:
    """The objects in the sign-in's training state."""
    state = _training_state(cookie)
    return {a.name for a in state.blue_assets} | {t.name for t in state.red_tracks}


def _operational_names(cookie: str) -> set[str]:
    state: Any = session_state(cookie)
    return {a.name for a in state.blue_assets} | {t.name for t in state.red_tracks}


#: The X-Spectre-Frame header every request from the console in the training frame carries (base.html, core.js).
_FRAME = {"X-Spectre-Frame": "training"}


def _frame_post(client: TestClient, cookie: str, path: str, data: dict[str, str]) -> Any:
    from tests.conftest import csrf_headers

    return client.post(path, data=data, cookies={"spectre_session": cookie},
                       headers={**csrf_headers(cookie), **_FRAME})


def _add_blue(client: TestClient, cookie: str, name: str, *, in_frame: bool) -> None:
    """Add a blue asset by hand, from the console in the training frame or from operations."""
    scenario = get_scenario(_CADET)
    assert scenario is not None
    obj = scenario.objects[0]
    data = {"name": name, "tle": f"{obj.tle_line1}\n{obj.tle_line2}"}
    resp = _frame_post(client, cookie, "/assets/blue", data) if in_frame else _post(client, cookie, "/assets/blue", data)
    assert resp.status_code == 200


_OWN = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))


class TestTrainingHasItsOwnState:
    """0.47.0 review B1, with X3, 2-7, 4-8 and 1-21: training reads and writes a planning state of its own."""

    def test_operations_keep_their_window_and_lists_while_the_frame_sees_the_scenarios(
            self, client: TestClient) -> None:
        cookie = _operator(client, "b1_split")
        ops: Any = session_state(cookie)
        ops.scenario_start, ops.scenario_stop = _OWN
        _start(client, cookie, _CADET)

        assert (ops.scenario_start, ops.scenario_stop) == _OWN
        assert not _objects(_CADET) & _operational_names(cookie)
        training = _training_state(cookie)
        assert (training.scenario_start, training.scenario_stop) == (
            datetime(2025, 6, 15, tzinfo=UTC), datetime(2025, 6, 16, tzinfo=UTC))
        assert _objects(_CADET) <= _names(cookie)

        operations_page = _get(client, cookie, "/").text
        assert 'value="2026-01-01T00:00:00"' in operations_page
        assert "2025-06-15T00:00:00" not in operations_page
        for frame_request in ({"params": {"frame": "training"}}, {"headers": _FRAME},
                              {"headers": {"Sec-Fetch-Dest": "iframe"}}):
            page = client.get("/", cookies={"spectre_session": cookie}, **frame_request).text  # type: ignore[arg-type]
            assert 'value="2025-06-15T00:00:00"' in page, frame_request
            assert 'href="/training"' not in page, frame_request
            assert '"X-Spectre-Frame": "training"' in page, "the frame's own requests say so"

    def test_a_window_set_in_the_frame_stays_in_the_training_state(self, client: TestClient) -> None:
        cookie = _operator(client, "b1_window")
        ops: Any = session_state(cookie)
        ops.scenario_start, ops.scenario_stop = _OWN
        _start(client, cookie, _CADET)
        window = {"scenario_start": "2026-11-16T00:00:00", "scenario_stop": "2026-11-17T00:00:00"}
        assert _frame_post(client, cookie, "/scenario/time", window).status_code == 200
        assert _training_state(cookie).scenario_start == datetime(2026, 11, 16, tzinfo=UTC)
        assert (ops.scenario_start, ops.scenario_stop) == _OWN

    def test_the_console_page_changes_nothing(self, client: TestClient) -> None:
        cookie = _operator(client, "b1_get")
        assert _get(client, cookie, "/training").status_code == 200
        result_id = _start(client, cookie, _CADET)
        assert _get(client, cookie, "/").status_code == 200
        assert _objects(_CADET) <= _names(cookie)
        assert _open_sessions(client, "b1_get") == 1
        assert _attempt(client, result_id).completed_at is None
        assert _progress(client, "b1_get").scenarios_started == 1

    def test_two_sign_ins_of_one_operator_do_not_disturb_each_other(self, client: TestClient) -> None:
        from tests.integration.conftest import login_as

        first = _operator(client, "b1_two")
        client.cookies.clear()
        second = login_as(client, "b1_two", "training-integrity")
        client.cookies.clear()
        assert first != second
        result_id = _start(client, first, _CADET)
        assert _get(client, second, "/").status_code == 200
        assert not _objects(_CADET) & (_names(second) | _operational_names(second))
        assert _training_state(second).scenario_start is None
        assert _objects(_CADET) <= _names(first)
        resp = _post(client, first, f"/training/scenario/{_CADET}/submit", {"result_id": result_id, **_CADET_PASS})
        assert resp.status_code == 200
        assert _attempt(client, result_id).passed

    def test_leaving_discards_the_training_state(self, client: TestClient) -> None:
        cookie = _operator(client, "b1_leave")
        assert _get(client, cookie, "/training").status_code == 200
        _start(client, cookie, _CADET)
        before = _training_state(cookie)
        _post(client, cookie, "/training/leave")
        after = _training_state(cookie)
        assert after is not before
        assert (after.scenario_start, after.blue_assets, after.red_tracks) == (None, [], [])
        assert _open_sessions(client, "b1_leave") == 0
        assert _progress(client, "b1_leave").scenarios_started == 0, "the open attempt is cancelled"

    def test_hand_added_objects_stay_on_their_own_side(self, client: TestClient) -> None:
        cookie = _operator(client, "b1_hand")
        result_id = _start(client, cookie, _CADET)
        # Both added after the start, as an operator would.
        _add_blue(client, cookie, "MY-FRAME-SAT", in_frame=True)
        _add_blue(client, cookie, "MY-OWN-SAT", in_frame=False)
        assert "MY-FRAME-SAT" in _names(cookie) and "MY-FRAME-SAT" not in _operational_names(cookie)
        assert "MY-OWN-SAT" in _operational_names(cookie) and "MY-OWN-SAT" not in _names(cookie)

        _post(client, cookie, f"/training/scenario/{_CADET}/abandon", {"result_id": result_id})
        assert "MY-FRAME-SAT" in _names(cookie), "a scenario's end removes only the scenario's objects"
        _start(client, cookie, _CADET_2)
        _post(client, cookie, "/training/leave")
        assert "MY-FRAME-SAT" not in _names(cookie), "it went with the training state"
        assert "MY-OWN-SAT" in _operational_names(cookie)

    def test_the_active_panel_shows_the_epoch(self, client: TestClient) -> None:
        cookie = _operator(client, "x3_shown")
        page = _flat(_post(client, cookie, f"/training/scenario/{_CADET}/start"))
        assert "Scenario time:</strong> 15 Jun 2025 00:00 UTC, 24 h horizon" in page


class TestObjectsLeaveWithTheScenario:
    """1-21."""

    def test_a_new_scenario_removes_the_last_ones_objects(self, client: TestClient) -> None:
        cookie = _operator(client, "x121_new")
        _start(client, cookie, _CADET)
        _start(client, cookie, _CADET_2)
        names = _names(cookie)
        assert _objects(_CADET_2) <= names
        assert not (_objects(_CADET) - _objects(_CADET_2)) & names
        assert _training_state(cookie).scenario_start == datetime(2025, 6, 10, 8, tzinfo=UTC)

    def test_reset_abandon_and_submit_each_remove_them(self, client: TestClient) -> None:
        cookie = _operator(client, "x121_end")
        for ending in ("reset", "abandon", "submit"):
            result_id = _start(client, cookie, _CADET)
            assert _objects(_CADET) <= _names(cookie)
            resp = _post(client, cookie, f"/training/scenario/{_CADET}/{ending}", {"result_id": result_id})
            assert resp.status_code == 200, ending
            assert not _objects(_CADET) & _names(cookie), ending


class TestPointsNeedAPass:
    """G-1, 1-20."""

    def test_an_empty_submission_earns_nothing(self, client: TestClient) -> None:
        cookie = _operator(client, "g1_empty")
        result_id = _start(client, cookie, _CADET)
        page = _flat(_submit(client, cookie, _CADET, result_id, []))
        assert "NOT PASSED" in page and "No training points earned" in page
        progress = _progress(client, "g1_empty")
        assert progress.total_points == 0
        assert progress.axis_points == {}
        assert progress.current_level == 1

    def test_a_pass_earns_the_scenario_award(self, client: TestClient) -> None:
        cookie = _operator(client, "g1_pass")
        result_id = _start(client, cookie, _CADET)
        page = _flat(_post(client, cookie, f"/training/scenario/{_CADET}/submit",
                           {"result_id": result_id, **_CADET_PASS}))
        assert "PASSED" in page and "+150 training points earned" in page
        progress = _progress(client, "g1_pass")
        assert progress.total_points == 150
        assert round(progress.axis_points["decision_quality"]) == 45


class TestALateChallengeDoesNotPass:
    """4-7."""

    def _all(self) -> list[str]:
        scenario = get_scenario(_TIMED_CHALLENGE)
        assert scenario is not None
        return [o.id for o in scenario.objectives]

    def test_full_marks_after_the_limit_do_not_pass(self, client: TestClient) -> None:
        cookie = _operator(client, "x47_late")
        _promote(client, "x47_late", 5)
        result_id = _start(client, cookie, _TIMED_CHALLENGE)
        _age_attempt(client, result_id, 21.0)
        page = _flat(_submit(client, cookie, _TIMED_CHALLENGE, result_id, self._all()))
        assert _attempt(client, result_id).total_score == 400
        assert not _attempt(client, result_id).passed
        assert "a late submission does not pass" in page
        progress = _progress(client, "x47_late")
        assert (progress.challenges_passed, progress.total_points) == (0, 0)

    def test_the_same_in_time_passes(self, client: TestClient) -> None:
        cookie = _operator(client, "x47_in_time")
        _promote(client, "x47_in_time", 5)
        result_id = _start(client, cookie, _TIMED_CHALLENGE)
        _age_attempt(client, result_id, 19.0)
        _submit(client, cookie, _TIMED_CHALLENGE, result_id, self._all())
        assert _attempt(client, result_id).passed
        assert _progress(client, "x47_in_time").challenges_passed == 1


class TestAFailedChallengeEarnsNothing:
    """G-1 for a challenge: neither the completion nor the challenge awards."""

    def test_an_in_time_fail_earns_nothing(self, client: TestClient) -> None:
        cookie = _operator(client, "g1_challenge")
        _promote(client, "g1_challenge", 5)
        result_id = _start(client, cookie, _TIMED_CHALLENGE)
        page = _flat(_submit(client, cookie, _TIMED_CHALLENGE, result_id, ["obj_detect"]))
        assert "NOT PASSED" in page and "First Attempt Bonus" not in page
        progress = _progress(client, "g1_challenge")
        assert (progress.total_points, progress.challenges_passed, progress.axis_points) == (0, 0, {})


class TestAbandonCancelsTheAttempt:
    """G-3. Abandon and Reset give the first-try bonus back: the coordinator's call, for the owner to confirm."""

    def test_abandon_does_not_cost_the_first_try_bonus(self, client: TestClient) -> None:
        cookie = _operator(client, "g3_abandon")
        result_id = _start(client, cookie, _CADET)
        resp = _post(client, cookie, f"/training/scenario/{_CADET}/abandon", {"result_id": result_id})
        assert (resp.status_code, resp.text) == (200, "")
        assert _progress(client, "g3_abandon").scenarios_started == 0

        second = _start(client, cookie, _CADET)
        attempt = _attempt(client, second)
        assert (attempt.attempt_num, attempt.first_try) == (1, True)

    def test_abandon_never_touches_a_submitted_attempt(self, client: TestClient) -> None:
        cookie = _operator(client, "g3_submitted")
        result_id = _start(client, cookie, _CADET)
        _submit(client, cookie, _CADET, result_id, [])
        before = _attempt(client, result_id)
        _post(client, cookie, f"/training/scenario/{_CADET}/abandon", {"result_id": result_id})
        after = _attempt(client, result_id)
        assert (after.id, after.completed_at, after.attempt_num) == (before.id, before.completed_at, 1)
        assert _progress(client, "g3_submitted").scenarios_started == 1

    def test_the_delete_rechecks_that_the_attempt_is_open(self, client: TestClient) -> None:
        """Review S4: an attempt submitted between the select and the delete is kept, and stays counted."""
        from types import SimpleNamespace

        from spectre.training.models import ChallengeResult
        from spectre.web.database import AsyncSessionLocal
        from spectre.web.routes import training
        from tests.integration.test_training_integrity import _db

        cookie = _operator(client, "s4_race")
        result_id = int(_start(client, cookie, _CADET))
        owner = SimpleNamespace(id=_attempt(client, str(result_id)).user_id, username="s4_race")

        async def submit_elsewhere() -> None:
            async with AsyncSessionLocal() as other:
                cr = await other.get(ChallengeResult, result_id)
                cr.completed_at = datetime.now(UTC)  # type: ignore[union-attr]
                await other.commit()

        async def race(session: Any) -> None:
            select_then_submit = session.execute

            async def execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
                result = await select_then_submit(statement, *args, **kwargs)
                if not getattr(execute, "done", False):  # after the select, before the delete
                    execute.done = True  # type: ignore[attr-defined]
                    await submit_elsewhere()
                return result

            session.execute = execute
            await training._cancel_open_attempts(session, owner, result_id)  # type: ignore[arg-type]
            await session.commit()

        _db(client, race)
        assert _attempt(client, str(result_id)).completed_at is not None, "the submitted attempt is kept"
        assert _progress(client, "s4_race").scenarios_started == 1, "and still counted"


class TestThePageIsToldToRefresh:
    """1-18, G-4."""

    def test_each_change_raises_training_changed(self, client: TestClient) -> None:
        cookie = _operator(client, "x118_events")
        start = _post(client, cookie, f"/training/scenario/{_CADET}/start")
        assert start.headers["HX-Trigger"] == "training-changed, training-console-stale"
        result_id = re.search(r'name="result_id" value="(\d+)"', start.text).group(1)  # type: ignore[union-attr]
        submit = _submit(client, cookie, _CADET, result_id, [])
        assert "training-console-stale" in submit.headers["HX-Trigger"]
        tutorial = _post(client, cookie, "/training/tutorial/orientation/complete")
        assert tutorial.headers["HX-Trigger"] == "training-changed"

    def test_the_refresh_carries_every_panel_out_of_band(self, client: TestClient) -> None:
        cookie = _operator(client, "x118_refresh")
        _give_points(client, "x118_refresh", 60)
        _post(client, cookie, "/training/tutorial/orientation/complete")
        page = _get(client, cookie, "/training/refresh").text
        for region in ("training-banner-status", "training-sidebar-status", "training-dashboard", "scenario-list",
                       "training-challenge-list", "training-tutorial-list"):
            assert re.search(rf'id="{region}" hx-swap-oob="innerHTML"', page), region
        assert "Level 2 · Observer · 110 pts" in " ".join(page.split())
        assert "Threat Assessment Fundamentals" in page, "the tutorial Level 2 unlocks is listed"

    def test_the_training_page_asks_for_the_refresh(self, client: TestClient) -> None:
        cookie = _operator(client, "x118_page")
        page = _get(client, cookie, "/training").text
        assert 'hx-get="/training/refresh" hx-trigger="training-changed from:body" hx-swap="none"' in page


def _listed(resp: Any) -> str:
    return _flat(resp).split('id="debrief-objectives"')[1].split("</ol>")[0]


_ACCEPTED = "Accepted answer: <strong"


class TestTheDebriefListsEveryObjective:
    """1-16, and review S3: the debrief is not an answer key."""

    def test_met_and_unmet_with_the_answers_given(self, client: TestClient) -> None:
        cookie = _operator(client, "x116_debrief")
        result_id = _start(client, cookie, _CADET)
        listed = _listed(_post(client, cookie, f"/training/scenario/{_CADET}/submit", {
            "result_id": result_id, "objectives_completed": '["obj_load"]',
            "answer_obj_read_elements": "128.5",
        }))
        assert listed.count("<li") == 3
        assert re.search(r"Met\s*</span> <span[^>]*>Confirm BLUE-01 is loaded", listed)
        assert ": outside tolerance" in listed and ">128.5</strong>" in listed
        assert ": not answered" in listed and ">none given</strong>" in listed

    def test_a_failed_attempt_hides_the_accepted_values(self, client: TestClient) -> None:
        cookie = _operator(client, "s3_failed")
        result_id = _start(client, cookie, _CADET)
        listed = _listed(_post(client, cookie, f"/training/scenario/{_CADET}/submit", {
            "result_id": result_id, "objectives_completed": "[]", "answer_obj_read_elements": "45",
            "answer_obj_confirm_dv": "9",
        }))
        assert "45.0 ± 0.5 degrees" in listed, "a met objective shows what it accepted"
        assert "2.0 ± 1 m/s" not in listed
        assert listed.count(_ACCEPTED) == 1

    def test_a_passed_scored_attempt_shows_every_accepted_answer(self, client: TestClient) -> None:
        cookie = _operator(client, "s3_passed")
        result_id = _start(client, cookie, _CADET)
        listed = _listed(_post(client, cookie, f"/training/scenario/{_CADET}/submit", {
            "result_id": result_id, "objectives_completed": "[]", "answer_obj_read_elements": "45",
            "answer_obj_confirm_dv": "2",
        }))
        assert "45.0 ± 0.5 degrees" in listed and "2.0 ± 1 m/s" in listed

    def test_an_explore_run_never_shows_one(self, client: TestClient) -> None:
        cookie = _operator(client, "s3_explore")
        result_id = _start(client, cookie, _CADET, mode="explore")
        listed = _listed(_post(client, cookie, f"/training/scenario/{_CADET}/submit", {
            "result_id": result_id, "objectives_completed": '["obj_load"]', "answer_obj_read_elements": "45",
            "answer_obj_confirm_dv": "2",
        }))
        assert _ACCEPTED not in listed
        assert "45.0" not in listed and "2.0 ± 1" not in listed


class TestAnswersInHours:
    """3-3."""

    def test_t_plus_and_a_unit_are_read_and_typing_ticks(self, client: TestClient) -> None:
        cookie = _operator(client, "x33_hours")
        _promote(client, "x33_hours", 3)
        scenario = get_scenario(_HOURS)
        assert scenario is not None
        timed = next(o for o in scenario.objectives if o.unit == "hours")
        for given in ("T+18h", "18 h", "18h", "18"):
            result_id = _start(client, cookie, _HOURS)
            _post(client, cookie, f"/training/scenario/{_HOURS}/submit", {
                "result_id": result_id, "objectives_completed": "[]", f"answer_{timed.id}": given,
            })
            assert _attempt(client, result_id).objectives_completed == [timed.id], given


class TestLevelConditionsAreShown:
    """1-19."""

    def test_the_sidebar_and_dashboard_list_the_next_levels_conditions(self, client: TestClient) -> None:
        cookie = _operator(client, "x119_gates")
        _promote(client, "x119_gates", 2)
        home = _flat(_get(client, cookie, "/training"))
        assert "Pass 3 scored scenarios or missions (you have passed 0)" in home
        assert "400 total points (you have 0)" in home
        dashboard = _flat(_get(client, cookie, "/training/dashboard"))
        assert "Level 3 (Planner) needs 400 total points (you have 0) and pass 3 scored scenarios or missions" in dashboard


class TestResetOfALockedScenario:
    """Review S5: Reset returned the briefing of a scenario the detail route refuses."""

    def test_reset_refuses_a_locked_briefing(self, client: TestClient) -> None:
        cookie = _operator(client, "s5_reset")
        resp = _post(client, cookie, "/training/scenario/planner_challenge_theatre_defence/reset",
                     {"result_id": "999999"})
        assert resp.status_code == 403
        assert "Reach Level 5" in resp.text
        assert "Theatre" not in resp.text


class TestTitlesDatesAndLocks:
    """1-23, 1-24, 4-16, 1-25, 1-26, 2-5."""

    def test_the_console_in_the_training_frame_has_no_training_link(self, client: TestClient) -> None:
        cookie = _operator(client, "x123_link")
        assert 'href="/training"' in _get(client, cookie, "/").text
        assert 'href="/training"' not in _get(client, cookie, "/?frame=training").text
        assert 'href="/training"' not in client.get(
            "/", cookies={"spectre_session": cookie}, headers={"Sec-Fetch-Dest": "iframe"}).text

    def test_unlocks_and_gauntlet_objectives_show_titles(self, client: TestClient) -> None:
        cookie = _operator(client, "x124_titles")
        _give_points(client, "x124_titles", 60)
        page = _flat(_post(client, cookie, "/training/tutorial/orientation/complete"))
        assert "Tutorial: Threat Assessment Fundamentals" in page
        assert get_scenario("cadet_03_inspection_approach").title in page  # type: ignore[union-attr]
        assert "cadet_03_inspection_approach" not in page
        _promote(client, "x124_titles", 4)
        detail = _get(client, cookie, "/training/scenario/analyst_gauntlet").text
        assert "observer_02_proximity_threat" not in detail
        assert get_scenario("observer_02_proximity_threat").title in detail  # type: ignore[union-attr]

    def test_a_level_up_debrief_names_what_it_unlocked(self, client: TestClient) -> None:
        cookie = _operator(client, "x124_debrief")
        _post(client, cookie, "/training/tutorial/orientation/complete")
        result_id = _start(client, cookie, _CADET)
        resp = _post(client, cookie, f"/training/scenario/{_CADET}/submit", {"result_id": result_id, **_CADET_PASS})
        assert resp.status_code == 200
        page = _flat(resp)
        assert "LEVEL UP — Level 2: Observer" in page
        assert "Tutorial: Threat Assessment Fundamentals" in page
        assert "tutorial:threat_assessment" not in page

    def test_recent_activity_names_the_scenario_and_dates_day_first(self, client: TestClient) -> None:
        cookie = _operator(client, "x125_dates")
        result_id = _start(client, cookie, _CADET)
        _submit(client, cookie, _CADET, result_id, [])
        started = _attempt(client, result_id).started_at
        page = _flat(_get(client, cookie, "/training/dashboard"))
        assert get_scenario(_CADET).title in page  # type: ignore[union-attr]
        assert started.strftime("%d %b %H:%M") in page

    def test_a_locked_tutorial_cannot_be_read(self, client: TestClient) -> None:
        cookie = _operator(client, "x126_locked")
        assert _get(client, cookie, "/training/tutorial/full_engagement_cycle").status_code == 403
        assert _get(client, cookie, "/training/tutorial/orientation").status_code == 200

    def test_workflow_steps_are_an_ordered_list(self, client: TestClient) -> None:
        cookie = _operator(client, "x25_steps")
        page = _post(client, cookie, f"/training/scenario/{_CADET}/start").text
        steps = page.split('id="scenario-workflow-steps"')[1].split("</ol>")[0]
        assert steps.count("<li") == 5
        assert "Tick all objectives and click Submit &amp; Score." in steps

