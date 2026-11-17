"""The Orbital Watch routes under /training/m (SPC-248): locks, start, the HUD, scoring, the pass and the clean-up.

● Every condition is read from the console's own record, never ticked: an objective is met only once the tool ran.
● An answer is checked against the figure the mission computed at start, within its tolerance, and is final.
● A hint costs its points and the third star; a first pass pays training points through the existing path, once.
● A start puts the mission's objects and clock in the training state only; finish and abandon take them away, and
  an exercise inject's set is put back.

Each operator here is created for its test, so its progress is its own. What a route hands its template is read from
the context it renders with (the contract's keys), so these tests hold whichever templates render it.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from spectre.training.models import MissionAttempt
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.integration.test_training_integrity import _db, _operator, _progress, _promote

_FRAME = {"X-Spectre-Frame": "training"}


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Each context the mission routes render, newest last."""
    from spectre.web.routes import missions

    contexts: list[dict[str, Any]] = []
    real = missions.render

    def record(request: Any, name: str, context: dict[str, Any] | None = None, status_code: int = 200) -> Any:
        contexts.append(dict(context or {}))
        return real(request, name, context, status_code)

    monkeypatch.setattr(missions, "render", record)
    return contexts


def _post(client: TestClient, cookie: str, path: str, data: dict[str, str] | None = None) -> Any:
    return client.post(path, data=data or {}, cookies={"spectre_session": cookie},
                       headers={**csrf_headers(cookie), **_FRAME})


def _get(client: TestClient, cookie: str, path: str) -> Any:
    return client.get(path, cookies={"spectre_session": cookie}, headers=_FRAME)


def _training(cookie: str) -> Any:
    from spectre.web.auth import session_key_for
    from spectre.web.planning_state import get_training_state

    key = session_key_for(cookie)
    assert key is not None
    return get_training_state(key)


def _statuses(html: str) -> dict[str, str]:
    return dict(re.findall(r'data-objective-id="([^"]+)" data-status="([^"]+)"', html))


def _attempt(client: TestClient, name: str, mission: str) -> MissionAttempt:
    async def read(session: Any) -> MissionAttempt:
        return (await session.execute(select(MissionAttempt).where(  # type: ignore[no-any-return]
            MissionAttempt.username == name, MissionAttempt.mission_id == mission,
        ).order_by(MissionAttempt.id.desc()).limit(1))).scalar_one()

    return _db(client, read)  # type: ignore[no-any-return]


def _passed(client: TestClient, name: str, user_cookie: str, mission: str) -> None:
    """Record a finished one-star attempt at *mission* for *name*, as a pass would, to open the next mission."""
    from spectre.web.auth import session_key_for

    key = session_key_for(user_cookie)
    assert key is not None

    async def write(session: Any) -> None:
        session.add(MissionAttempt(user_id=key.user_id, username=name, mission_id=mission, status="finished",
                                   stars=1, score=10, finished_at=datetime.now(UTC)))
        await session.commit()

    _db(client, write)


def _ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def _set(client: TestClient, name: str, **fields: Any) -> None:
    """Write *fields* onto *name*'s latest attempt, as time passing would."""
    async def write(session: Any) -> None:
        row = (await session.execute(select(MissionAttempt).where(MissionAttempt.username == name)
                                     .order_by(MissionAttempt.id.desc()).limit(1))).scalar_one()
        for key, value in fields.items():
            setattr(row, key, value)
        await session.commit()

    _db(client, write)


def _option(html: str, objective: str, label: str) -> str:
    """The option_id the HUD offers for *label*, read from each <label> however the template lays it out."""
    block = html.split(f'data-objective-id="{objective}"', 1)[1].split("</li>", 1)[0]
    for inner in re.findall(r"<label\b[^>]*>(.*?)</label>", block, re.S):
        value = re.search(r'name="option_id"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="option_id"', inner)
        if value and re.sub(r"<[^>]+>", " ", inner).split() == label.split():
            return value.group(1) or value.group(2)
    raise AssertionError(block)


class TestTheCampaign:
    def test_chapter_two_is_locked_until_observer_and_says_why(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_campaign")
        assert _get(client, cookie, "/training/m/campaign").status_code == 200
        chapters = {c["id"]: c for c in seen[-1]["chapters"]}
        assert chapters["shadows"]["locked"] and not chapters["first_watch"]["locked"]
        assert chapters["shadows"]["lock_reason"].startswith("Reach Observer: ")
        assert "Orientation" in chapters["shadows"]["lock_reason"]
        assert all(m["locked"] for m in chapters["shadows"]["missions"])
        assert seen[-1]["rank"]["next_title"] == "Observer" and seen[-1]["medals_count"] == 0
        assert _post(client, cookie, "/training/m/the_tug/start").status_code == 403

    def test_a_mission_opens_with_a_star_on_the_one_before(self, client: TestClient) -> None:
        cookie = _operator(client, "m_order")
        refused = _post(client, cookie, "/training/m/who_is_near/start")
        assert refused.status_code == 403
        assert "Earn a star on Know your asset first." in refused.text
        _passed(client, "m_order", cookie, "know_your_asset")
        assert _post(client, cookie, "/training/m/who_is_near/start").status_code == 200


class TestStart:
    def test_it_loads_the_objects_and_the_clock_into_the_training_state_only(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_start")
        resp = _post(client, cookie, "/training/m/know_your_asset/start")
        assert resp.status_code == 200
        assert resp.headers["HX-Trigger"] == "training-changed, training-console-stale"
        alert = seen[-1]
        assert alert["alert_line"] == "SKYNET 5A is on your Blue list. Find where it sits."
        assert alert["brief"][0].startswith("Mission clock: 01 Oct 2026 12:00 UTC.")
        assert alert["data_note"] == "Element sets: bundled, SYNTHETIC"
        assert alert["exercise_inject"] is None and alert["intel_card"] is None
        training = _training(cookie)
        assert [(a.name, a.training) for a in training.blue_assets] == [("SKYNET 5A", True)]
        assert training.scenario_start == datetime(2026, 10, 1, 12, tzinfo=UTC)
        assert session_state(cookie).blue_assets == []
        assert session_state(cookie).scenario_start is None

    def test_an_exercise_inject_replaces_the_set_until_the_mission_ends(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_inject")
        _promote(client, "m_inject", 2)
        for earlier in ("know_your_asset", "who_is_near", "the_sweep", "read_a_threat", "the_tug"):
            _passed(client, "m_inject", cookie, earlier)
        held = _training(cookie).hrr_tle_cache["50321"]
        resp = _post(client, cookie, "/training/m/the_inspector/start")
        assert resp.status_code == 200
        assert seen[-1]["exercise_inject"].startswith("EXERCISE: SY-12 01 burns at 01 Oct 12:00 UTC")
        assert seen[-1]["data_note"].endswith("SY-12 01: EXERCISE inject")
        assert seen[-1]["intel_card"]["source"] == "SWF Global Counterspace Capabilities 2025"
        _get(client, cookie, "/training/m/the_inspector/hud")
        assert seen[-1]["exercise"] == seen[-2]["exercise_inject"]
        training = _training(cookie)
        assert training.hrr_tle_cache["50321"] != held
        assert training.hrr_tle_data_mode["50321"] == "EXERCISE"
        assert [t.data_mode for t in training.red_tracks if t.name == "SY-12 01"] == ["EXERCISE"]
        _post(client, cookie, "/training/m/the_inspector/abandon")
        assert training.hrr_tle_cache["50321"] == held
        assert training.hrr_tle_data_mode["50321"] == "SYNTHETIC"
        assert training.red_tracks == [] and training.scenario_start is None


class TestTheHud:
    def test_answers_are_checked_against_the_computed_figure_once(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_answer")
        _post(client, cookie, "/training/m/know_your_asset/start")
        lon = float(_attempt(client, "m_answer", "know_your_asset").quantities["lon"])
        shown = f"{abs(lon):.2f}° {'E' if lon >= 0 else 'W'}"
        resp = _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "longitude", "value": shown})
        assert _statuses(resp.text)["longitude"] == "met"
        assert resp.headers["HX-Trigger"] == "training-changed"
        assert seen[-1]["just_met"] == ["longitude"] and seen[-1]["score"] == 100
        assert seen[-1]["exercise"] is None
        resp = _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "inclination", "value": "3"})
        assert _statuses(resp.text)["inclination"] == "failed"
        assert seen[-1]["objectives"][1]["miss_band"] == "far"
        again = _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "inclination",
                                                                              "value": "0.04"})
        # A repeat to a settled objective (a double click, a second tab) shows the HUD as it is: no error, no change.
        assert again.status_code == 200 and seen[-1]["error"] is None
        assert _statuses(again.text)["inclination"] == "failed"

    def test_a_near_miss_is_close_and_says_nothing_more(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_close")
        _post(client, cookie, "/training/m/know_your_asset/start")
        inc = float(_attempt(client, "m_close", "know_your_asset").quantities["inc"])
        _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "inclination",
                                                                      "value": f"{inc + 0.025:.3f}"})
        inclination = seen[-1]["objectives"][1]
        assert inclination["status"] == "failed" and inclination["miss_band"] == "close"
        assert seen[-1]["objectives"][0]["miss_band"] is None

    def test_a_decimal_comma_reads_as_a_point(self, client: TestClient) -> None:
        cookie = _operator(client, "m_comma")
        _post(client, cookie, "/training/m/know_your_asset/start")
        lon = float(_attempt(client, "m_comma", "know_your_asset").quantities["lon"])
        resp = _post(client, cookie, "/training/m/know_your_asset/answer",
                     {"objective_id": "longitude", "value": f"{lon:.2f}".replace(".", ",")})
        assert _statuses(resp.text)["longitude"] == "met"

    def test_an_implausible_reading_is_refused_without_spending_it(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_implausible")
        _post(client, cookie, "/training/m/know_your_asset/start")
        for objective, value in (("longitude", "279.72"), ("inclination", "-0.04"), ("inclination", "190")):
            resp = _post(client, cookie, "/training/m/know_your_asset/answer",
                         {"objective_id": objective, "value": value})
            assert resp.status_code == 422 and seen[-1]["error"]
            assert _statuses(resp.text)[objective] == "open"

    def test_an_unreadable_answer_is_refused_without_spending_it(self, client: TestClient) -> None:
        cookie = _operator(client, "m_unread")
        _post(client, cookie, "/training/m/know_your_asset/start")
        resp = _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "longitude",
                                                                             "value": "east-ish"})
        assert resp.status_code == 422
        assert _statuses(resp.text)["longitude"] == "open"

    def test_a_condition_is_met_only_once_the_tool_has_run(self, client: TestClient) -> None:
        cookie = _operator(client, "m_condition")
        _passed(client, "m_condition", cookie, "know_your_asset")
        _post(client, cookie, "/training/m/who_is_near/start")
        assert _statuses(_get(client, cookie, "/training/m/who_is_near/hud").text)["screened"] == "open"
        assert _post(client, cookie, "/plan/threat/screen", {"asset_satno": "30793"}).status_code == 200
        hud = _get(client, cookie, "/training/m/who_is_near/hud")
        assert _statuses(hud.text)["screened"] == "met"
        assert hud.headers["HX-Trigger"] == "training-changed"
        assert "HX-Trigger" not in _get(client, cookie, "/training/m/who_is_near/hud").headers

    def test_a_hint_is_offered_on_an_open_objective_only(self, client: TestClient, seen: list[Any]) -> None:
        """N10."""
        cookie = _operator(client, "m_hint_shut")
        _post(client, cookie, "/training/m/know_your_asset/start")
        hud = _get(client, cookie, "/training/m/know_your_asset/hud").text
        _post(client, cookie, "/training/m/know_your_asset/choose",
              {"objective_id": "regime", "option_id": _option(hud, "regime", "LEO")})
        assert not {o["id"]: o for o in seen[-1]["objectives"]}["regime"]["hint_available"]
        resp = _post(client, cookie, "/training/m/know_your_asset/hint", {"objective_id": "regime"})
        assert resp.status_code == 422 and seen[-1]["hints_used"] == 0

    def test_the_time_runs_from_the_first_hud_not_the_start(self, client: TestClient, seen: list[Any]) -> None:
        """Reading the alert does not count against par: the clock starts when the watch is taken."""
        cookie = _operator(client, "m_watch")
        _post(client, cookie, "/training/m/know_your_asset/start")
        assert _attempt(client, "m_watch", "know_your_asset").watched_at is None
        _set(client, "m_watch", started_at=_ago(1000))
        _get(client, cookie, "/training/m/know_your_asset/hud")
        watched = datetime.fromisoformat(seen[-1]["clock"]["started_at_iso"])
        assert (datetime.now(UTC) - watched).total_seconds() < 60
        _set(client, "m_watch", watched_at=_ago(100))
        _post(client, cookie, "/training/m/know_your_asset/finish")
        assert 99 <= seen[-1]["seconds"] <= 160

    def test_a_hint_shows_its_words_and_spotlight_and_costs_its_points(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_hint")
        _post(client, cookie, "/training/m/know_your_asset/start")
        _get(client, cookie, "/training/m/know_your_asset/hud")
        offered = {o["id"]: o for o in seen[-1]["objectives"]}["regime"]
        assert offered["hint_available"] and offered["hint_cost"] == 25 and offered["hint_text"] is None
        _post(client, cookie, "/training/m/know_your_asset/hint", {"objective_id": "regime"})
        regime = {o["id"]: o for o in seen[-1]["objectives"]}["regime"]
        assert regime["spotlight"] == "#blue-list details.elset-card summary"
        assert regime["hint_text"] == "Read Regime on the card for SKYNET 5A."
        assert not regime["hint_available"] and seen[-1]["hints_used"] == 1
        attempt = _attempt(client, "m_hint", "know_your_asset")
        assert attempt.hints_used == 1 and attempt.score == 0

    def test_a_choice_is_right_only_for_the_option_the_engine_marked(self, client: TestClient) -> None:
        cookie = _operator(client, "m_choice")
        _post(client, cookie, "/training/m/know_your_asset/start")
        hud = _get(client, cookie, "/training/m/know_your_asset/hud").text
        resp = _post(client, cookie, "/training/m/know_your_asset/choose",
                     {"objective_id": "regime", "option_id": _option(hud, "regime", "LEO")})
        assert _statuses(resp.text)["regime"] == "failed"
        assert _attempt(client, "m_choice", "know_your_asset").objectives["regime"]["points"] == 0


class TestFinish:
    def _fly(self, client: TestClient, cookie: str, name: str) -> Any:
        _post(client, cookie, "/training/m/know_your_asset/start")
        values = _attempt(client, name, "know_your_asset").quantities
        _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "longitude",
                                                                      "value": f"{values['lon']:.2f}"})
        _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "inclination",
                                                                      "value": f"{values['inc']:.2f}"})
        hud = _get(client, cookie, "/training/m/know_your_asset/hud").text
        _post(client, cookie, "/training/m/know_your_asset/choose",
              {"objective_id": "regime", "option_id": _option(hud, "regime", "GEO")})
        return _post(client, cookie, "/training/m/know_your_asset/finish")

    def test_a_clean_pass_earns_three_stars_pays_once_and_opens_the_next(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_pass")
        before = _progress(client, "m_pass").total_points
        resp = self._fly(client, cookie, "m_pass")
        debrief = seen[-1]
        assert debrief["stars"] == 3 and all(r["earned"] for r in debrief["star_reasons"])
        assert re.fullmatch(r"Finished in 0:\d\d against a par of 2:30\.", debrief["star_reasons"][1]["why"])
        assert debrief["points"] == 300 and debrief["hints_used"] == 0
        assert debrief["unlocked"] == ["Who is near?"]
        assert debrief["next_mission"] == {"id": "who_is_near", "title": "Who is near?"}
        assert debrief["objectives"][0]["accepted"].endswith((" E", " W"))
        assert debrief["best_answer_note"].startswith("SKYNET 5A sat at ")
        assert (debrief["score"], debrief["rank_points_earned"], debrief["rank_note"]) == (300, 150, "")
        assert resp.headers["HX-Trigger"] == "training-changed, training-console-stale"
        progress = _progress(client, "m_pass")
        assert progress.total_points == before + 150 and progress.scenarios_passed == 1
        training = _training(cookie)
        assert training.blue_assets == [] and training.scenario_start is None
        self._fly(client, cookie, "m_pass")
        assert _progress(client, "m_pass").total_points == before + 150   # a replay pays nothing
        assert (seen[-1]["rank_points_earned"], seen[-1]["rank_note"]) == (0, "Replays pay no rank points.")
        _post(client, cookie, "/training/m/know_your_asset/start")
        _get(client, cookie, "/training/m/know_your_asset/hud")
        assert seen[-1]["best_seconds"] is not None and seen[-1]["best_seconds"] >= 0
        _get(client, cookie, "/training/m/campaign")
        assert seen[-1]["running_mission"] == {"id": "know_your_asset", "title": "Know your asset"}
        _post(client, cookie, "/training/m/know_your_asset/abandon")
        assert seen[-1]["running_mission"] is None
        _get(client, cookie, "/training/m/campaign")
        assert seen[-1]["running_mission"] is None
        first = seen[-1]["chapters"][0]["missions"][0]
        assert (first["id"], first["stars"], first["best_points"]) == ("know_your_asset", 3, 300)

    def test_a_finish_with_an_objective_open_earns_nothing(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_short")
        _post(client, cookie, "/training/m/know_your_asset/start")
        _post(client, cookie, "/training/m/know_your_asset/finish")
        assert seen[-1]["stars"] == 0 and seen[-1]["next_mission"] is None
        assert [o["accepted"] for o in seen[-1]["objectives"]] == [None, None, None]   # no answer key
        assert _progress(client, "m_short").total_points == 0

    def test_nothing_runs_once_finished(self, client: TestClient) -> None:
        cookie = _operator(client, "m_done")
        _post(client, cookie, "/training/m/know_your_asset/start")
        _post(client, cookie, "/training/m/know_your_asset/finish")
        assert _get(client, cookie, "/training/m/know_your_asset/hud").status_code == 409
        assert _post(client, cookie, "/training/m/know_your_asset/finish").status_code == 409


def test_leaving_training_abandons_a_mission_in_flight(client: TestClient) -> None:
    cookie = _operator(client, "m_leave")
    _post(client, cookie, "/training/m/know_your_asset/start")
    client.post("/training/leave", cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
                follow_redirects=False)
    assert _attempt(client, "m_leave", "know_your_asset").status == "abandoned"


def test_the_screen_records_what_it_ranked(client: TestClient) -> None:
    """The record the screening_run check reads (routes.threat.threat_screen)."""
    cookie = _operator(client, "m_record")
    assert _post(client, cookie, "/plan/threat/screen", {"asset_satno": "30793"}).status_code == 200
    record = _training(cookie).last_screening
    assert record.asset_satno == "30793" and record.ranked
    assert json.dumps(record.ranked)


def test_a_named_form_sent_as_a_field_of_its_own_is_ignored(client: TestClient) -> None:
    """htmx sends a form's name as a field; the answer must still be read from its value."""
    cookie = _operator(client, "m_named")
    _post(client, cookie, "/training/m/know_your_asset/start")
    inc = _attempt(client, "m_named", "know_your_asset").quantities["inc"]
    resp = _post(client, cookie, "/training/m/know_your_asset/answer", {
        "mission-answer": "[object HTMLInputElement]", "objective_id": "inclination", "value": f"{inc:.2f}"})
    assert _statuses(resp.text)["inclination"] == "met"


class TestScreeningQuestionsReadTheOperatorsScreening:
    """B2: the first-ranked actor changes within minutes, so a question is graded on the operator's own screening."""

    def _record(self, cookie: str, top: str) -> None:
        from spectre.training.mission_checks import default_budget
        from spectre.web.planning_state import ScreeningRecord

        names = {"TJS-13": "62188", "SJ-21": "49330", "Cosmos 2589": "64467", "TJS-3": "43874"}
        ranked = tuple((names[n], n, "HIGH" if n == top else "MINIMAL") for n in [top, *sorted(set(names) - {top})])
        _training(cookie).last_screening = ScreeningRecord("30793", "SKYNET 5A", datetime.now(UTC), ranked,
                                                           considered=11, budget_m_s=default_budget())

    def test_unanswerable_until_screened_then_graded_on_that_screening(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_own_screen")
        _passed(client, "m_own_screen", cookie, "know_your_asset")
        _post(client, cookie, "/training/m/who_is_near/start")
        _get(client, cookie, "/training/m/who_is_near/hud")
        top = {o["id"]: o for o in seen[-1]["objectives"]}["top"]
        assert top["options"] == [] and "Screen SKYNET 5A first" in top["text"]
        refused = _post(client, cookie, "/training/m/who_is_near/choose", {"objective_id": "top", "option_id": "sj-21"})
        assert refused.status_code == 422
        self._record(cookie, "SJ-21")   # whatever the engine would rank now, the operator's screening said SJ-21
        hud = _get(client, cookie, "/training/m/who_is_near/hud").text
        assert _statuses(hud)["screened"] == "met"
        assert {o["label"] for o in {o["id"]: o for o in seen[-1]["objectives"]}["top"]["options"]} >= {"SJ-21"}
        resp = _post(client, cookie, "/training/m/who_is_near/answer", {"objective_id": "candidates", "value": "11"})
        assert _statuses(resp.text)["candidates"] == "met"
        resp = _post(client, cookie, "/training/m/who_is_near/choose",
                     {"objective_id": "top", "option_id": _option(hud, "top", "SJ-21")})
        assert _statuses(resp.text)["top"] == "met"

    def test_a_later_screening_of_the_asset_is_the_one_graded(self, client: TestClient) -> None:
        cookie = _operator(client, "m_rescreen")
        _passed(client, "m_rescreen", cookie, "know_your_asset")
        _post(client, cookie, "/training/m/who_is_near/start")
        self._record(cookie, "SJ-21")
        _get(client, cookie, "/training/m/who_is_near/hud")
        self._record(cookie, "TJS-3")
        hud = _get(client, cookie, "/training/m/who_is_near/hud").text
        resp = _post(client, cookie, "/training/m/who_is_near/choose",
                     {"objective_id": "top", "option_id": _option(hud, "top", "TJS-3")})
        assert _statuses(resp.text)["top"] == "met"


def test_a_lost_training_state_ends_the_mission_and_says_so(client: TestClient) -> None:
    """N15: after a restart or an expiry the state is fresh; grading on it would grade an unburned orbit."""
    from spectre.web.auth import session_key_for
    from spectre.web.planning_state import discard_training_state

    cookie = _operator(client, "m_lost")
    _post(client, cookie, "/training/m/know_your_asset/start")
    key = session_key_for(cookie)
    assert key is not None
    discard_training_state(key)
    resp = _get(client, cookie, "/training/m/know_your_asset/hud")
    assert resp.status_code == 409
    assert "Know your asset has ended, unscored. Ended because the training console was reset" in resp.text
    assert _attempt(client, "m_lost", "know_your_asset").status == "abandoned"


def test_one_open_attempt_per_account_is_held_by_the_database(client: TestClient) -> None:
    """B1: two concurrent starts cannot both leave an attempt open."""
    from sqlalchemy.exc import IntegrityError

    async def two(session: Any) -> None:
        for _ in range(2):
            session.add(MissionAttempt(user_id=987654, username="m_twice", mission_id="know_your_asset"))
        await session.commit()

    with pytest.raises(IntegrityError):
        _db(client, two)


def test_an_htmx_request_without_a_sign_in_is_sent_to_the_login_page(client: TestClient) -> None:
    """A 302 under the HUD's poll swapped the login page into the HUD; htmx is told to go there instead."""
    client.cookies.clear()
    polled = client.get("/training/m/campaign", headers={"HX-Request": "true"}, follow_redirects=False)
    assert polled.status_code == 401 and polled.headers["HX-Redirect"] == "/login"
    loaded = client.get("/training/m/campaign", follow_redirects=False)
    assert loaded.status_code == 302 and loaded.headers["Location"] == "/login"


def test_the_dashboard_says_what_is_checked_and_what_is_synthetic(client: TestClient) -> None:
    cookie = _operator(client, "m_dashboard")
    text = " ".join(_get(client, cookie, "/training/dashboard").text.split())
    assert "self-assess" not in text.lower()
    assert "flown in the real console on real catalogue objects" in text
    assert "classic scenarios</strong> use synthetic orbital data" in text


def test_a_write_that_lost_a_race_settles_on_the_winner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1, made deterministic: another request settles an objective between this one's read and its write. The write
    must not land over it (compare and set on the version), and this answer must still settle on a fresh read."""
    from spectre.web.database import AsyncSessionLocal
    from spectre.web.routes import missions

    cookie = _operator(client, "m_race")
    _post(client, cookie, "/training/m/know_your_asset/start")
    lon = float(_attempt(client, "m_race", "know_your_asset").quantities["lon"])
    real_read = missions._read
    raced: list[int] = []

    async def racing_read(db: Any, attempt_id: int) -> Any:
        row = await real_read(db, attempt_id)
        if not raced:
            raced.append(attempt_id)
            async with AsyncSessionLocal() as other:
                rival = (await other.execute(
                    select(MissionAttempt).where(MissionAttempt.id == attempt_id))).scalar_one()
                states = rival.objectives
                states["inclination"].update(status="failed", given="3")
                rival.objectives = states
                rival.version += 1
                await other.commit()
        return row

    monkeypatch.setattr(missions, "_read", racing_read)
    resp = _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "longitude",
                                                                         "value": f"{lon:.2f}"})
    assert raced
    assert _statuses(resp.text) == {"longitude": "met", "inclination": "failed", "regime": "open"}



class TestReleaseReview:
    """The final play-through's engine items (SPC-248)."""

    def test_a_screening_at_another_budget_says_why_it_does_not_count(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_budget")
        _passed(client, "m_budget", cookie, "know_your_asset")
        _post(client, cookie, "/training/m/who_is_near/start")
        _post(client, cookie, "/plan/threat/screen", {"asset_satno": "30793", "max_dv_m_s": "400"})
        _get(client, cookie, "/training/m/who_is_near/hud")
        note = "Your screening at 400 m/s does not count: screen at the default Max ΔV, 500 m/s."
        hud = {o["id"]: o for o in seen[-1]["objectives"]}
        assert hud["screened"]["status"] == "open" and note in hud["screened"]["text"]
        assert note in hud["top"]["text"] and "Screen SKYNET 5A first" in hud["top"]["text"]
        resp = _post(client, cookie, "/training/m/who_is_near/answer", {"objective_id": "candidates", "value": "14"})
        assert resp.status_code == 422 and note in seen[-1]["error"]

    def test_no_hint_is_offered_or_taken_on_a_question_not_yet_answerable(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_nohint")
        _passed(client, "m_nohint", cookie, "know_your_asset")
        _post(client, cookie, "/training/m/who_is_near/start")
        _get(client, cookie, "/training/m/who_is_near/hud")
        assert not {o["id"]: o for o in seen[-1]["objectives"]}["top"]["hint_available"]
        resp = _post(client, cookie, "/training/m/who_is_near/hint", {"objective_id": "top"})
        assert resp.status_code == 422 and seen[-1]["hints_used"] == 0
        assert seen[-1]["error"].startswith("No hint yet. Screen SKYNET 5A first")

    def test_a_miss_says_the_stars_are_lost_and_restart_starts_afresh(
        self, client: TestClient, seen: list[Any],
    ) -> None:
        cookie = _operator(client, "m_restart")
        _post(client, cookie, "/training/m/know_your_asset/start")
        _get(client, cookie, "/training/m/know_your_asset/hud")
        assert seen[-1]["star_lost"] is False
        _post(client, cookie, "/training/m/know_your_asset/answer", {"objective_id": "inclination", "value": "3"})
        assert seen[-1]["star_lost"] is True
        first = _attempt(client, "m_restart", "know_your_asset").id
        resp = _post(client, cookie, "/training/m/know_your_asset/restart")
        assert resp.status_code == 200 and seen[-1]["alert_line"].startswith("SKYNET 5A is on your Blue list")
        fresh = _attempt(client, "m_restart", "know_your_asset")
        assert fresh.id != first and fresh.status == "open"
        assert all(v["status"] == "open" for v in fresh.objectives.values())
        assert _get(client, cookie, "/training/m/know_your_asset/hud").status_code == 200
        assert seen[-1]["star_lost"] is False

    def test_a_mission_will_not_start_over_a_classic_scenario_and_says_so(self, client: TestClient) -> None:
        cookie = _operator(client, "m_classic")
        assert _post(client, cookie, "/training/scenario/cadet_01_geo_stationkeeping/start").status_code == 200
        held = [a.name for a in _training(cookie).blue_assets]
        resp = _post(client, cookie, "/training/m/know_your_asset/start")
        assert resp.status_code == 409
        assert "classic scenario" in resp.text and "Submit or abandon it on the Free-Play tab first" in resp.text
        assert [a.name for a in _training(cookie).blue_assets] == held   # its objects are untouched

    def test_a_classic_scenario_will_not_start_over_a_mission_and_says_so(self, client: TestClient) -> None:
        cookie = _operator(client, "m_classic_back")
        _post(client, cookie, "/training/m/know_your_asset/start")
        resp = _post(client, cookie, "/training/scenario/cadet_01_geo_stationkeeping/start")
        assert resp.status_code == 409
        assert "The mission Know your asset is running" in resp.text and "Campaign tab" in resp.text
        assert _get(client, cookie, "/training/m/know_your_asset/hud").status_code == 200

    def test_a_mission_that_is_not_running_says_why(self, client: TestClient) -> None:
        cookie = _operator(client, "m_why")
        _passed(client, "m_why", cookie, "know_your_asset")
        _post(client, cookie, "/training/m/know_your_asset/start")
        _post(client, cookie, "/training/m/who_is_near/start")
        resp = _get(client, cookie, "/training/m/know_your_asset/hud")
        assert resp.status_code == 409
        assert "Know your asset is not running: Ended because you started Who is near?." in resp.text
        _post(client, cookie, "/training/m/who_is_near/finish")
        again = _post(client, cookie, "/training/m/who_is_near/finish")
        assert again.status_code == 409 and "it was finished" in again.text
        _post(client, cookie, "/training/m/know_your_asset/start")
        _post(client, cookie, "/training/m/know_your_asset/abandon")
        assert "you abandoned it." in _get(client, cookie, "/training/m/know_your_asset/hud").text

    def test_the_debrief_says_why_the_next_chapter_is_shut(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_shut")
        for earlier in ("know_your_asset", "who_is_near", "the_sweep"):
            _passed(client, "m_shut", cookie, earlier)
        _post(client, cookie, "/training/m/read_a_threat/start")
        _post(client, cookie, "/training/m/read_a_threat/finish")
        assert seen[-1]["next_mission"] is None
        assert seen[-1]["next_lock_reason"].startswith("Shadows in the Belt opens at Observer: ")
        assert "Orientation" in seen[-1]["next_lock_reason"]

    def test_the_inject_names_where_its_set_came_from(self, client: TestClient, seen: list[Any]) -> None:
        cookie = _operator(client, "m_inject_mode")
        _promote(client, "m_inject_mode", 2)
        for earlier in ("know_your_asset", "who_is_near", "the_sweep", "read_a_threat", "the_tug"):
            _passed(client, "m_inject_mode", cookie, earlier)
        _post(client, cookie, "/training/m/the_inspector/start")
        assert "on the element set held for it (SYNTHETIC)" in seen[-1]["exercise_inject"]
        _post(client, cookie, "/training/m/the_inspector/abandon")

    def test_the_training_console_strip_says_not_operational_and_the_sets_it_holds(self, client: TestClient) -> None:
        cookie = _operator(client, "m_strip")
        page = " ".join(_get(client, cookie, "/").text.split())
        assert "TRAINING CONSOLE: not operational · SYNTHETIC sets" in page
        assert "synthetic, not operational" not in page

    def test_the_dashboard_starts_at_the_campaigns_next_mission(self, client: TestClient) -> None:
        cookie = _operator(client, "m_start_here")
        page = " ".join(_get(client, cookie, "/training/dashboard").text.split())
        assert "Start Here: Know your asset" in page and 'data-tab="campaign"' in page
        _passed(client, "m_start_here", cookie, "know_your_asset")
        page = " ".join(_get(client, cookie, "/training/dashboard").text.split())
        assert "Start Here: Who is near?" in page
