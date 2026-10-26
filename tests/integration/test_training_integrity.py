"""Training scores what the operator did, at the level they have reached.

● F-159: only the detail view checked the level. Start, explore, submit and
  tutorial completion did not, so a Level 1 operator could start and submit a
  Level 5 challenge or bank every tutorial on first login, and a result row
  could be submitted against another scenario's objectives.
● F-168: the elapsed time was the client's word for it, so a "submit within
  the time limit" objective was self-certified and any number was stored.
● F-167: an exploration run, once submitted, showed in the activity history
  as a PASS or FAIL and counted towards the attempt number.
● F-172: the debrief's "Skill Points Earned" showed objective points per
  axis, which never reach the operator's axis totals; the axes move by the
  award actions' weights.

Each operator here is created for its test, so its progress is its own.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from spectre.training.gamification import get_config
from spectre.training.models import ChallengeResult, TrainingProgress
from tests.conftest import csrf_headers
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login

_LEVEL_5_CHALLENGE = "planner_challenge_theatre_defence"
_CADET = "cadet_01_geo_stationkeeping"
_TIMED = "planner_03_multi_constraint"  # level 3, 10-minute limit, obj_time_pressure


def _db(client: TestClient, work: Callable[[Any], Awaitable[Any]]) -> Any:
    """Run *work* against the application's own database, on its loop."""
    from spectre.web.database import AsyncSessionLocal

    async def run() -> Any:
        async with AsyncSessionLocal() as session:
            return await work(session)

    return client.portal.call(run)  # type: ignore[union-attr]


def _operator(client: TestClient, name: str) -> str:
    """A fresh operator signed in, with training progress at Level 1."""
    admin = _admin_cookies(client)
    _create_operator(client, admin, name, "training-integrity")
    client.cookies.clear()
    cookie = str(_login(client, name, "training-integrity").cookies["spectre_session"])  # type: ignore[attr-defined]
    client.cookies.clear()
    assert client.get("/training/dashboard", cookies={"spectre_session": cookie}).status_code == 200
    return cookie


def _progress(client: TestClient, name: str) -> TrainingProgress:
    async def read(session: Any) -> TrainingProgress:
        row = (await session.execute(
            select(TrainingProgress).where(TrainingProgress.username == name)
        )).scalar_one()
        return row  # type: ignore[no-any-return]

    return _db(client, read)  # type: ignore[no-any-return]


def _promote(client: TestClient, name: str, level: int) -> None:
    """Put *name* at *level* with every unlock up to it, as levelling would."""
    unlocks = [u for lv in get_config().levels if lv.level <= level for u in lv.unlocks]

    async def write(session: Any) -> None:
        row = (await session.execute(
            select(TrainingProgress).where(TrainingProgress.username == name)
        )).scalar_one()
        row.current_level = level
        row.unlocked = unlocks
        await session.commit()

    _db(client, write)


def _post(client: TestClient, cookie: str, path: str, data: dict[str, str] | None = None) -> Any:
    return client.post(
        path, data=data or {}, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
    )


def _start(client: TestClient, cookie: str, scenario: str, mode: str = "start") -> str:
    resp = _post(client, cookie, f"/training/scenario/{scenario}/{mode}")
    assert resp.status_code == 200
    match = re.search(rb'name="result_id" value="(\d+)"', resp.content)
    assert match
    return match.group(1).decode()


def _submit(client: TestClient, cookie: str, scenario: str, result_id: str, objectives: list[str]) -> Any:
    return _post(client, cookie, f"/training/scenario/{scenario}/submit", {
        "result_id": result_id, "objectives_completed": json.dumps(objectives),
    })


def _age_attempt(client: TestClient, result_id: str, minutes: float) -> None:
    """Move an open attempt's start back by *minutes*, as if it had run that long."""
    async def write(session: Any) -> None:
        cr = (await session.execute(
            select(ChallengeResult).where(ChallengeResult.id == int(result_id))
        )).scalar_one()
        cr.started_at = datetime.now(UTC) - timedelta(minutes=minutes)
        await session.commit()

    _db(client, write)


def _attempt(client: TestClient, result_id: str) -> ChallengeResult:
    async def read(session: Any) -> ChallengeResult:
        return (await session.execute(  # type: ignore[no-any-return]
            select(ChallengeResult).where(ChallengeResult.id == int(result_id))
        )).scalar_one()

    return _db(client, read)  # type: ignore[no-any-return]


class TestLevelGating:
    """F-159."""

    def test_a_level_1_operator_cannot_start_a_level_5_challenge(self, client: TestClient) -> None:
        cookie = _operator(client, "f159_start")
        assert _post(client, cookie, f"/training/scenario/{_LEVEL_5_CHALLENGE}/start").status_code == 403
        assert _post(client, cookie, f"/training/scenario/{_LEVEL_5_CHALLENGE}/explore").status_code == 403
        assert _progress(client, "f159_start").scenarios_started == 0

    def test_a_level_1_operator_can_start_a_level_1_scenario(self, client: TestClient) -> None:
        cookie = _operator(client, "f159_cadet")
        assert _post(client, cookie, f"/training/scenario/{_CADET}/start").status_code == 200
        assert _progress(client, "f159_cadet").scenarios_started == 1

    def test_submit_is_refused_once_the_level_is_lost(self, client: TestClient) -> None:
        cookie = _operator(client, "f159_submit")
        _promote(client, "f159_submit", 5)
        result_id = _start(client, cookie, _LEVEL_5_CHALLENGE)
        _promote(client, "f159_submit", 1)
        resp = _submit(client, cookie, _LEVEL_5_CHALLENGE, result_id, ["obj_triage"])
        assert resp.status_code == 403
        assert _progress(client, "f159_submit").total_points == 0

    def test_a_result_cannot_be_scored_against_another_scenario(self, client: TestClient) -> None:
        cookie = _operator(client, "f159_swap")
        result_id = _start(client, cookie, _CADET)
        resp = _submit(client, cookie, "cadet_02_leo_debris_conjunction", result_id, [])
        assert resp.status_code == 404
        assert _attempt(client, result_id).completed_at is None
        assert _progress(client, "f159_swap").total_points == 0

    def test_a_locked_tutorial_earns_nothing(self, client: TestClient) -> None:
        cookie = _operator(client, "f159_tutorial")
        resp = _post(client, cookie, "/training/tutorial/full_engagement_cycle/complete")
        assert resp.status_code == 403
        progress = _progress(client, "f159_tutorial")
        assert progress.total_points == 0
        assert progress.tutorials_completed == []

    def test_an_unlocked_tutorial_earns_its_points_once(self, client: TestClient) -> None:
        from spectre.training.tutorials import get_tutorial

        cookie = _operator(client, "f159_tutorial_ok")
        tutorial = get_tutorial("scenario_loading")
        assert tutorial is not None
        assert _post(client, cookie, "/training/tutorial/scenario_loading/complete").status_code == 200
        assert _post(client, cookie, "/training/tutorial/scenario_loading/complete").status_code == 200
        progress = _progress(client, "f159_tutorial_ok")
        assert progress.total_points == tutorial.points
        assert progress.tutorials_completed == ["scenario_loading"]


class TestTimeIsTheServers:
    """F-168."""

    def test_the_stored_time_is_measured_not_reported(self, client: TestClient) -> None:
        cookie = _operator(client, "f168_measured")
        result_id = _start(client, cookie, _CADET)
        _age_attempt(client, result_id, 7.0)
        resp = _post(client, cookie, f"/training/scenario/{_CADET}/submit", {
            "result_id": result_id, "objectives_completed": "[]", "time_taken_minutes": "-5",
        })
        assert resp.status_code == 200
        assert 6.9 < _attempt(client, result_id).time_taken_minutes < 8.0

    def test_a_late_submission_does_not_earn_the_time_objective(self, client: TestClient) -> None:
        cookie = _operator(client, "f168_late")
        _promote(client, "f168_late", 3)
        result_id = _start(client, cookie, _TIMED)
        _age_attempt(client, result_id, 11.0)
        resp = _submit(client, cookie, _TIMED, result_id, ["obj_time_pressure"])
        assert resp.status_code == 200
        attempt = _attempt(client, result_id)
        assert attempt.total_score == 0
        assert attempt.objectives_completed == []
        assert b"time limit" in resp.content

    def test_an_in_time_submission_earns_it(self, client: TestClient) -> None:
        cookie = _operator(client, "f168_in_time")
        _promote(client, "f168_in_time", 3)
        result_id = _start(client, cookie, _TIMED)
        _age_attempt(client, result_id, 9.0)
        _submit(client, cookie, _TIMED, result_id, ["obj_time_pressure"])
        assert _attempt(client, result_id).total_score == 30

    def test_a_non_list_objectives_value_scores_nothing(self, client: TestClient) -> None:
        cookie = _operator(client, "f168_shape")
        result_id = _start(client, cookie, _CADET)
        resp = _post(client, cookie, f"/training/scenario/{_CADET}/submit", {
            "result_id": result_id, "objectives_completed": "5",
        })
        assert resp.status_code == 200
        assert _attempt(client, result_id).total_score == 0


class TestExploreRunsAreNotHistory:
    """F-167."""

    def test_a_submitted_explore_run_is_not_listed_or_counted(self, client: TestClient) -> None:
        cookie = _operator(client, "f167_explore")
        from spectre.training.scenarios import get_scenario

        scenario = get_scenario(_CADET)
        assert scenario is not None
        every_objective = [o.id for o in scenario.objectives if not o.answer]
        result_id = _start(client, cookie, _CADET, mode="explore")
        _submit(client, cookie, _CADET, result_id, every_objective)

        verdict = re.compile(rb">\s*(PASS|FAIL)\s*<")
        dashboard = client.get("/training/dashboard", cookies={"spectre_session": cookie}).content
        assert verdict.search(dashboard) is None
        home = client.get("/training", cookies={"spectre_session": cookie}).content
        assert verdict.search(home) is None
        detail = client.get(f"/training/scenario/{_CADET}", cookies={"spectre_session": cookie}).content
        assert b"Attempt #1" in detail
        assert _progress(client, "f167_explore").total_points == 0


class TestDebriefShowsTheRealAxisChange:
    """F-172."""

    def test_skill_points_earned_equal_the_change_in_the_axis_totals(self, client: TestClient) -> None:
        cookie = _operator(client, "f172_axes")
        before = dict(_progress(client, "f172_axes").axis_points)
        result_id = _start(client, cookie, _CADET)
        resp = _submit(client, cookie, _CADET, result_id, ["obj_load"])
        after = _progress(client, "f172_axes").axis_points
        cfg = get_config()

        page = " ".join(resp.content.decode().split())
        earned = page.split("Skill Points Earned")[1].split("Debrief:")[0]
        for axis_id in set(before) | set(after):
            delta = after.get(axis_id, 0.0) - before.get(axis_id, 0.0)
            if round(delta) == 0:
                continue
            label = cfg.axes_by_id[axis_id].label
            assert re.search(rf"{label}\s*</span>\s*<span[^>]*>\s*\+{round(delta)}\s*<", earned), (axis_id, delta)
        assert "Objective points by axis" in page
