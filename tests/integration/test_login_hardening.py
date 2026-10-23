"""Integration tests for the hardened login path.

A security gate attacked a running instance and proved four defects here:
unthrottled credential brute force, bcrypt run on the event loop, a timing
oracle that read out which usernames exist, and a logout that left the session
token valid for its full 8 hours. Each test below states the property the fix
restored, so breaking a guard turns one of them red rather than all of them.

Nothing here measures wall-clock time. The clock is the weather: it says what
the machine was doing, not what the code does. Where the defect was a timing
one, the test counts the work instead.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.conftest import csrf_headers

_ADMIN = "testadmin"
# Fixture credential for an in-memory database created and destroyed inside
# the test process. It authenticates against nothing that outlives the run.
_ADMIN_PASSWORD = "testpass123"

# An authenticated route any operator may reach, so a refusal here is about
# the session rather than the role.
_PANEL = "/plan/decision/panel"


def _login(
    client: TestClient, username: str, password: str, address: str | None = None
) -> object:
    """Post credentials, optionally from a nominated source address."""
    headers = {"X-Forwarded-For": address} if address else {}
    return client.post(
        "/login",
        data={"username": username, "password": password},
        headers=headers,
        follow_redirects=False,
    )


def _admin_cookies(client: TestClient) -> dict[str, str]:
    """Return a fresh authenticated admin session."""
    client.cookies.clear()
    resp = _login(client, _ADMIN, _ADMIN_PASSWORD)
    assert resp.status_code == 302, "the admin fixture credential no longer authenticates"
    return dict(resp.cookies)


def _create_operator(
    client: TestClient, admin: dict[str, str], username: str, password: str
) -> None:
    """Create an operator account through the admin route."""
    resp = client.post(
        "/admin/users",
        data={"username": username, "password": password, "role": "operator"},
        cookies=admin,
        headers=csrf_headers(admin),
    )
    assert resp.status_code == 200
    assert username.encode() in resp.content


def _user_id(client: TestClient, admin: dict[str, str], username: str) -> int:
    """Return the row id the admin table shows for *username*."""
    page = client.get("/admin/users", cookies=admin)
    assert page.status_code == 200
    for row in re.finditer(r'<tr id="user-row-(\d+)".*?</tr>', page.content.decode(), re.S):
        if f">{username}<" in row.group(0):
            return int(row.group(1))
    raise AssertionError(f"{username} is not in the admin user table")


class TestFailedLoginRateLimit:
    """DEFECT 1: 40 consecutive failed logins answered 40 x 401 and never 429."""

    def test_the_eleventh_failure_in_the_window_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The comparison is stubbed so 11 attempts cost milliseconds rather
        # than three seconds. The limiter is what is under test here, not
        # bcrypt's work factor.
        monkeypatch.setattr("spectre.web.routes.login.verify_password", lambda *_: False)
        address = "203.0.113.10"

        for attempt in range(10):
            resp = _login(client, "ghost-operator", "wrong", address=address)
            assert resp.status_code == 401, f"attempt {attempt + 1} was throttled too early"

        refused = _login(client, "ghost-operator", "wrong", address=address)
        assert refused.status_code == 429
        # A browser is what reaches this endpoint, so the refusal has to be the
        # login page carrying the reason, not a bare JSON body.
        assert b"Operator Authentication" in refused.content
        assert b"Too many failed sign-in attempts" in refused.content

    def test_a_different_source_address_keeps_its_own_budget(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("spectre.web.routes.login.verify_password", lambda *_: False)
        exhausted = "203.0.113.20"
        untouched = "203.0.113.21"

        for _ in range(10):
            assert _login(client, "ghost-operator", "wrong", address=exhausted).status_code == 401
        assert _login(client, "ghost-operator", "wrong", address=exhausted).status_code == 429

        # One address under attack must not sign out everyone else.
        assert _login(client, "ghost-operator", "wrong", address=untouched).status_code == 401


class TestTimingEquivalence:
    """DEFECT 3: an unknown username skipped bcrypt entirely (CWE-204).

    2.6 ms against 270.2 ms told an attacker which operators exist however
    generic the error text was.
    """

    def test_an_absent_and_a_known_username_both_pay_for_one_comparison(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compared: list[str] = []

        def _record(plaintext: str, hashed: str) -> bool:
            compared.append(hashed)
            return False

        monkeypatch.setattr("spectre.web.routes.login.verify_password", _record)

        assert _login(client, "no-such-operator", "wrong", address="203.0.113.30").status_code == 401
        assert _login(client, _ADMIN, "wrong", address="203.0.113.31").status_code == 401

        assert len(compared) == 2, "the absent username skipped the bcrypt comparison"
        absent, known = compared
        # The stand-in has to be a real hash at the same cost factor, or the
        # work is only equivalent on paper.
        assert absent.startswith("$2b$"), "the stand-in is not a bcrypt hash"
        assert known.startswith("$2b$")
        assert absent.split("$")[2] == known.split("$")[2], "different bcrypt cost factors"
        assert absent != known


class TestBcryptOffTheEventLoop:
    """DEFECT 2: 32 concurrent anonymous logins took /healthz to a 833 ms median."""

    def test_the_comparison_is_awaited_in_the_threadpool(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import starlette.concurrency

        from spectre.web.auth import verify_password

        awaited: list[object] = []

        async def _spy(func: object, *args: object, **kwargs: object) -> object:
            awaited.append(func)
            return await starlette.concurrency.run_in_threadpool(func, *args, **kwargs)

        monkeypatch.setattr("spectre.web.routes.login.run_in_threadpool", _spy)

        resp = _login(client, _ADMIN, _ADMIN_PASSWORD, address="203.0.113.40")
        assert resp.status_code == 302
        # Awaited, not called: a synchronous call would never reach the spy.
        assert awaited == [verify_password], "bcrypt still runs on the event loop"


class TestSessionRevocation:
    """DEFECT 4: a cookie captured before POST /logout stayed good for 8 hours."""

    def test_logout_refuses_the_captured_cookie(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "hardening_logout", "shift-handover-one")

        client.cookies.clear()
        session = str(_login(client, "hardening_logout", "shift-handover-one").cookies["spectre_session"])
        captured = {"spectre_session": session}
        assert client.get(_PANEL, cookies=captured).status_code == 200

        client.cookies.clear()
        out = client.post(
            "/logout",
            cookies=captured,
            headers=csrf_headers(session),
            follow_redirects=False,
        )
        assert out.status_code == 302

        client.cookies.clear()
        after = client.get(_PANEL, cookies=captured, follow_redirects=False)
        assert after.status_code == 302, "the token outlived the logout that was meant to end it"
        assert "/login" in after.headers["location"]

    def test_a_password_change_ends_a_live_session(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "hardening_reset", "shift-handover-two")

        client.cookies.clear()
        session = str(_login(client, "hardening_reset", "shift-handover-two").cookies["spectre_session"])
        live = {"spectre_session": session}
        assert client.get(_PANEL, cookies=live).status_code == 200

        client.cookies.clear()
        reset = client.post(
            f"/admin/users/{_user_id(client, admin, 'hardening_reset')}",
            data={"role": "operator", "new_password": "rotated-after-the-incident"},
            cookies=admin,
            headers=csrf_headers(admin),
        )
        assert reset.status_code == 200

        client.cookies.clear()
        after = client.get(_PANEL, cookies=live, follow_redirects=False)
        assert after.status_code == 302, "the reset left the session it was meant to answer alive"
        assert "/login" in after.headers["location"]


class TestEpochComparison:
    """The two shapes the stored epoch arrives in, neither of which is a session."""

    def test_a_row_written_before_the_column_existed_is_never_revoked(self) -> None:
        from spectre.web.auth import _session_revoked
        from spectre.web.models import User

        migrated = User(username="row_from_before", hashed_password="x", role="operator")
        assert migrated.session_epoch is None
        assert _session_revoked(migrated, datetime.now(tz=UTC)) is False

    def test_an_epoch_read_back_without_a_time_zone_still_compares(self) -> None:
        """SQLite hands back a naive datetime for a column declared with a zone."""
        from spectre.web.auth import _session_revoked
        from spectre.web.models import User

        user = User(username="row_from_sqlite", hashed_password="x", role="operator")
        now = datetime.now(tz=UTC)
        user.session_epoch = now.replace(tzinfo=None)

        assert _session_revoked(user, now - timedelta(seconds=5)) is True
        assert _session_revoked(user, now + timedelta(seconds=5)) is False
