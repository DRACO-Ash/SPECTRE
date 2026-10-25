"""Training scenario objects leave the operational session with the operator.

Audit F-051. Starting a scenario appended synthetic BLUE and RED objects to
the operator's live SessionState with no marker, and nothing removed them on
/training/leave, while the banner said "No operational systems are affected"
and three docstrings said training never touches session state.
"""

from __future__ import annotations

from spectre.training.scenarios import get_scenario
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_SCENARIO = "cadet_01_geo_stationkeeping"


def _names(cookie: str) -> set[str]:
    state = session_state(cookie)
    return {a.name for a in state.blue_assets} | {t.name for t in state.red_tracks}


def test_scenario_objects_are_removed_on_leave(client: object, auth_cookie: str) -> None:
    scenario_names = {o.name for o in get_scenario(_SCENARIO).objects}  # type: ignore[union-attr]
    assert scenario_names
    headers, cookies = csrf_headers(auth_cookie), {"spectre_session": auth_cookie}

    client.post(f"/training/scenario/{_SCENARIO}/start", cookies=cookies, headers=headers)  # type: ignore[attr-defined]
    assert scenario_names & _names(auth_cookie), "the exercise objects are present while training"

    client.post("/training/leave", cookies=cookies, headers=headers, follow_redirects=False)  # type: ignore[attr-defined]
    assert not (scenario_names & _names(auth_cookie)), "scenario objects stayed in the operational lists"


def test_operator_objects_with_the_same_session_survive_leave(client: object, auth_cookie: str) -> None:
    state = session_state(auth_cookie)
    before = {a.name for a in state.blue_assets if not getattr(a, "training", False)}
    headers, cookies = csrf_headers(auth_cookie), {"spectre_session": auth_cookie}
    client.post(f"/training/scenario/{_SCENARIO}/start", cookies=cookies, headers=headers)  # type: ignore[attr-defined]
    client.post("/training/leave", cookies=cookies, headers=headers, follow_redirects=False)  # type: ignore[attr-defined]
    assert before <= {a.name for a in state.blue_assets}
