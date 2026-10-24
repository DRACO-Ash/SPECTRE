"""A training attempt is scored once.

Audit F-049. training_scenario_submit never checked whether the attempt had
been completed, so one result_id could be resubmitted indefinitely, each POST
re-awarding scenario_completed, challenge_passed and the first-try bonus and
incrementing the pass counters.
"""

from __future__ import annotations

import re

from tests.conftest import csrf_headers

_SCENARIO = "cadet_01_geo_stationkeeping"


def _post(client: object, auth_cookie: str, path: str, data: dict[str, str] | None = None) -> object:
    return client.post(  # type: ignore[attr-defined]
        path, data=data or {}, cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
    )


def test_a_completed_attempt_cannot_be_submitted_again(client: object, auth_cookie: str) -> None:
    start = _post(client, auth_cookie, f"/training/scenario/{_SCENARIO}/start")
    assert start.status_code == 200  # type: ignore[attr-defined]
    match = re.search(rb'name="result_id" value="(\d+)"', start.content)  # type: ignore[attr-defined]
    assert match, "the active-scenario partial carries the attempt id"
    submission = {"result_id": match.group(1).decode(), "objectives_completed": "[]", "time_taken_minutes": "5"}

    first = _post(client, auth_cookie, f"/training/scenario/{_SCENARIO}/submit", submission)
    again = _post(client, auth_cookie, f"/training/scenario/{_SCENARIO}/submit", submission)

    assert first.status_code == 200  # type: ignore[attr-defined]
    assert again.status_code == 409  # type: ignore[attr-defined]
    assert b"already" in again.content  # type: ignore[attr-defined]


def _attempt(client: object, auth_cookie: str, scenario: str, objectives: list[str]) -> str:
    import json

    start = _post(client, auth_cookie, f"/training/scenario/{scenario}/start")
    match = re.search(rb'name="result_id" value="(\d+)"', start.content)  # type: ignore[attr-defined]
    assert match
    resp = _post(client, auth_cookie, f"/training/scenario/{scenario}/submit", {
        "result_id": match.group(1).decode(), "objectives_completed": json.dumps(objectives),
        "time_taken_minutes": "5",
    })
    assert resp.status_code == 200  # type: ignore[attr-defined]
    return " ".join(resp.content.decode().split())  # type: ignore[attr-defined]


def test_a_repeated_objective_scores_once(client: object, auth_cookie: str) -> None:
    """Audit F-158: ["obj_select_optimal"] twice passed planner_03 on 60 points of 100."""
    debrief = _attempt(client, auth_cookie, "planner_03_multi_constraint", ["obj_select_optimal"] * 2)
    assert re.search(r">\s*60\s*<", debrief), "scored once, 60 points"
    assert "+150 training points earned" in debrief, "completed, not passed"


def test_a_free_play_pass_earns_no_challenge_award(client: object, auth_cookie: str) -> None:
    """Audit F-160: a passed free-play scenario earned 500 points, not 150."""
    debrief = _attempt(client, auth_cookie, "planner_03_multi_constraint",
                       ["obj_run_engine", "obj_eliminate_infeasible", "obj_select_optimal"])
    assert "+150 training points earned" in debrief
    assert "First Attempt Bonus" not in debrief


def test_the_debrief_claims_a_first_try_bonus_only_for_challenges() -> None:
    """Audit F-160: the bonus line read cr.first_try alone."""
    from pathlib import Path

    template = Path("spectre/web/templates/partials/training_debrief.html").read_text(encoding="utf-8")
    line = next(t for t in template.splitlines() if "First Attempt Bonus" in t)
    assert "scenario.challenge" in line
