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
