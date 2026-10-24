"""Regression gates for three security controls that were correct but unpinned.

Audit F-059, F-060 and F-061. Each control was right in the code and each
could be reverted with the suite green: the Secure cookie flag (the suite runs
with the opt-out), CSRF on DELETE (no test sent a DELETE without a token), and
a revoked session on the public root page (the logout test sent no cookie at
all afterwards, so it never replayed the one it had just revoked).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login, _user_id


class TestTheSessionCookieIsSecureByDefault:
    """F-059. A regression to secure=False would send the token over plain HTTP."""

    def test_login_sets_secure_without_the_opt_out(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPECTRE_COOKIE_SECURE", raising=False)
        client.cookies.clear()
        resp = _login(client, "testadmin", "testpass123")
        cookie = next(h for h in resp.headers.get_list("set-cookie") if h.startswith("spectre_session="))
        attributes = {part.strip().lower() for part in cookie.split(";")}
        assert "secure" in attributes
        assert "httponly" in attributes


class TestDeleteNeedsACsrfToken:
    """F-060. Three state-changing routes use DELETE."""

    @pytest.mark.parametrize("path", ["/assets/blue/ANY", "/assets/red/ANY"])
    def test_asset_deletion_without_a_token_is_refused(self, client: TestClient, path: str) -> None:
        admin = _admin_cookies(client)
        client.cookies.clear()
        assert client.delete(path, cookies=admin).status_code == 403

    def test_user_deletion_without_a_token_is_refused_and_the_user_stays(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "csrf_delete_target", "kept-after-forgery")
        user_id = _user_id(client, admin, "csrf_delete_target")
        client.cookies.clear()
        assert client.delete(f"/admin/users/{user_id}", cookies=admin).status_code == 403
        assert _user_id(client, admin, "csrf_delete_target") == user_id


class TestARevokedSessionIsAnonymousOnTheRoot:
    """F-061. The public root must not greet a signed-out operator from a captured cookie."""

    def test_the_captured_cookie_gets_the_login_page(self, client: TestClient) -> None:
        from tests.conftest import csrf_headers

        admin = _admin_cookies(client)
        _create_operator(client, admin, "root_replay", "signed-out-at-handover")
        client.cookies.clear()
        session = str(_login(client, "root_replay", "signed-out-at-handover").cookies["spectre_session"])
        captured = {"spectre_session": session}
        client.cookies.clear()
        assert b"Blue Assets" in client.get("/", cookies=captured).content, "precondition: the console renders"

        client.post("/logout", cookies=captured, headers=csrf_headers(session), follow_redirects=False)
        client.cookies.clear()
        resp = client.get("/", cookies=captured, follow_redirects=False)
        assert resp.status_code == 200
        assert b"Blue Assets" not in resp.content
        assert b"root_replay" not in resp.content
