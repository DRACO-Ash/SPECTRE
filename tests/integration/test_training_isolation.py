"""The training planning state, through the routes (0.47.0 review round c).

● B1: a UDL Disconnect in the training frame ended the operational UDL session's tasks, and the reverse.
● S3: Decision Engine evaluations in the frame wrote permanent operational decision records.
● S4: a console served to training looked operational.
● N6: logout, a password change and account deletion must clear the training state with the operational one, and
  UDL credentials entered in the frame stay in the training state.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from spectre.web import planning_state as ps
from spectre.web.auth import session_key_for
from spectre.web.models import DecisionRecord
from tests.conftest import csrf_headers
from tests.integration.conftest import login_as, session_state
from tests.integration.test_decision_input_validation import _form
from tests.integration.test_identity_is_the_account import _admin, _create, _delete, _user_id
from tests.integration.test_training_integrity import _db, _operator

_FRAME = {"X-Spectre-Frame": "training"}


def _key(cookie: str) -> Any:
    key = session_key_for(cookie)
    assert key is not None
    return key


def _post(client: TestClient, cookie: str, path: str, data: dict[str, Any] | None = None, *,
          frame: bool = False) -> Any:
    headers = {**csrf_headers(cookie), **(_FRAME if frame else {})}
    return client.post(path, data=data or {}, cookies={"spectre_session": cookie}, headers=headers)


def _records(client: TestClient, username: str) -> int:
    async def count(session: Any) -> int:
        query = select(func.count()).select_from(DecisionRecord).where(DecisionRecord.username == username)
        return int((await session.execute(query)).scalar_one())

    return int(_db(client, count))


class TestUdlCredentialsStayOnTheirSide:
    """B1 and N6 through the UDL Disconnect route."""

    def _signed_in_both_sides(self, client: TestClient, name: str) -> tuple[str, Any, Any]:
        cookie = _operator(client, name)
        operational: Any = session_state(cookie)
        training = ps.get_training_state(_key(cookie))
        operational.udl_username, operational.udl_password = "ops", "ops-secret"
        training.udl_username, training.udl_password = "trainee", "training-secret"
        return cookie, operational, training

    def test_a_disconnect_in_the_frame_leaves_operations_connected(self, client: TestClient) -> None:
        cookie, operational, training = self._signed_in_both_sides(client, "c_udl_frame")
        assert _post(client, cookie, "/udl/logout", frame=True).status_code == 200
        assert training.udl_password is None
        assert operational.udl_password == "ops-secret"

    def test_an_operational_disconnect_leaves_the_frame_connected(self, client: TestClient) -> None:
        cookie, operational, training = self._signed_in_both_sides(client, "c_udl_ops")
        assert _post(client, cookie, "/udl/logout").status_code == 200
        assert operational.udl_password is None
        assert training.udl_password == "training-secret"

    def test_leaving_training_blanks_the_frames_credentials(self, client: TestClient) -> None:
        cookie, operational, training = self._signed_in_both_sides(client, "c_udl_leave")
        _post(client, cookie, "/training/leave")
        assert training.udl_password is None
        assert operational.udl_password == "ops-secret"


class TestEndingASignInClearsTheTrainingState:
    """N6."""

    def _training(self, cookie: str) -> Any:
        training = ps.get_training_state(_key(cookie))
        training.udl_password = "training-secret"
        return training

    def test_logout(self, client: TestClient) -> None:
        cookie = _operator(client, "c_logout")
        training = self._training(cookie)
        client.post("/logout", cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
        assert _key(cookie) not in ps._training_store
        assert training.udl_password is None

    def test_a_password_change(self, client: TestClient) -> None:
        admin = _admin(client)
        _create(client, admin, "c-pass")
        cookie = login_as(client, "c-pass", "pass-123")
        training = self._training(cookie)
        resp = client.post(f"/admin/users/{_user_id(client, admin, 'c-pass')}",
                           data={"role": "operator", "new_password": "new-pass-456"},
                           cookies=admin, headers=csrf_headers(admin))
        assert resp.status_code == 200
        assert _key(cookie) not in ps._training_store
        assert training.udl_password is None
        _delete(client, admin, "c-pass")

    def test_account_deletion(self, client: TestClient) -> None:
        admin = _admin(client)
        _create(client, admin, "c-del")
        cookie = login_as(client, "c-del", "pass-123")
        training = self._training(cookie)
        _delete(client, admin, "c-del")
        assert _key(cookie) not in ps._training_store
        assert training.udl_password is None


class TestTrainingWritesNoDecisionRecord:
    """S3."""

    def test_an_evaluation_in_the_frame_is_not_recorded(self, client: TestClient) -> None:
        cookie = _operator(client, "c_decision_frame")
        resp = _post(client, cookie, "/plan/decision/evaluate", _form(scenario_name="Frame"), frame=True)
        assert resp.status_code == 200
        assert "Training: not recorded." in resp.text
        assert _records(client, "c_decision_frame") == 0

    def test_an_operational_evaluation_still_is(self, client: TestClient) -> None:
        cookie = _operator(client, "c_decision_ops")
        resp = _post(client, cookie, "/plan/decision/evaluate", _form(scenario_name="Ops"))
        assert resp.status_code == 200
        assert "Training: not recorded." not in resp.text
        assert _records(client, "c_decision_ops") == 1


class TestATrainingConsoleSaysSo:
    """S4."""

    def _get(self, client: TestClient, cookie: str, path: str, **headers: str) -> str:
        return client.get(path, cookies={"spectre_session": cookie}, headers=headers).text

    def test_the_frame_shows_the_strip_and_operations_do_not(self, client: TestClient) -> None:
        cookie = _operator(client, "c_strip")
        assert 'id="training-console-strip"' in self._get(client, cookie, "/?frame=training")
        assert 'id="training-console-strip"' in self._get(client, cookie, "/", **{"Sec-Fetch-Dest": "iframe"})
        assert 'id="training-console-strip"' not in self._get(client, cookie, "/")

    def test_the_frame_url_opened_in_a_tab_is_the_operational_console(self, client: TestClient) -> None:
        cookie = _operator(client, "c_tab")
        ps.get_training_state(_key(cookie)).udl_username = "trainee"
        page = self._get(client, cookie, "/?frame=training", **{"Sec-Fetch-Dest": "document"})
        assert 'id="training-console-strip"' not in page
        assert 'href="/training"' in page
        assert "X-Spectre-Frame" not in page
        assert "trainee" not in page, "it is served from the operational state, not the training one"
        assert "trainee" in self._get(client, cookie, "/?frame=training", **{"Sec-Fetch-Dest": "iframe"})


class TestTheLogsSayTraining:
    """N5."""

    def test_the_access_line_marks_a_training_request(self, client: TestClient, caplog: Any) -> None:
        cookie = _operator(client, "c_access")
        with caplog.at_level(logging.INFO, logger="spectre.access"):
            client.get("/training/dashboard", cookies={"spectre_session": cookie})
            client.get("/log/entries", cookies={"spectre_session": cookie})
        lines = [r.getMessage() for r in caplog.records if r.name == "spectre.access"]
        assert any(line.startswith("GET /training/dashboard 200") and line.endswith(" training") for line in lines)
        assert any(line.startswith("GET /log/entries") and not line.endswith(" training") for line in lines)

    def test_the_udl_close_line_marks_training(self, client: TestClient, caplog: Any) -> None:
        cookie = _operator(client, "c_udl_log")
        with caplog.at_level(logging.INFO, logger="spectre.web.routes.udl"):
            _post(client, cookie, "/udl/logout", frame=True)
            _post(client, cookie, "/udl/logout")
        closes = [r.getMessage() for r in caplog.records if "UDL session closed" in r.getMessage()]
        assert closes == ["UDL session closed for operator: c_udl_log (training)",
                          "UDL session closed for operator: c_udl_log"]
