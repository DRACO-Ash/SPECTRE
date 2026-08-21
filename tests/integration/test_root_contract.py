"""Tests for the root route contract and the optional-authentication path.

The App Store router probes ``GET /`` and treats anything other than 200 as a
failed deploy. That requirement must never be met by weakening authentication,
so every branch of the optional-auth dependency is asserted here: the console
renders only for a real, current session.
"""

from __future__ import annotations

from tests.conftest import csrf_headers


class TestRootAlwaysReturns200:
    def test_anonymous_gets_the_login_page(self, client: object) -> None:
        resp = client.get("/", cookies={}, follow_redirects=False)  # type: ignore[attr-defined]
        assert resp.status_code == 200
        assert b"login" in resp.content.lower()

    def test_a_malformed_cookie_is_treated_as_anonymous(self, client: object) -> None:
        """A tampered cookie must not raise; it must fall through to login."""
        resp = client.get(  # type: ignore[attr-defined]
            "/", cookies={"spectre_session": "not-a-valid-token"}, follow_redirects=False
        )
        assert resp.status_code == 200
        assert b"Blue Assets" not in resp.content

    def test_a_cookie_for_a_deleted_user_is_treated_as_anonymous(self, client: object) -> None:
        """A validly signed session for a user who no longer exists grants nothing."""
        from spectre.web.auth import make_session_cookie

        ghost = make_session_cookie("user-that-was-deleted")
        resp = client.get(  # type: ignore[attr-defined]
            "/", cookies={"spectre_session": ghost}, follow_redirects=False
        )
        assert resp.status_code == 200
        assert b"Blue Assets" not in resp.content

    def test_an_authenticated_session_gets_the_console(
        self, client: object, auth_cookie: str
    ) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/", cookies={"spectre_session": auth_cookie}, follow_redirects=False
        )
        assert resp.status_code == 200
        assert b"Blue Assets" in resp.content


class TestSessionCookieAttributes:
    def test_login_sets_httponly_and_samesite(self, client: object) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "testadmin", "password": "testpass123"},
            follow_redirects=False,
        )
        header = resp.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=lax" in header

    def test_secure_flag_is_on_by_default(self, monkeypatch: object) -> None:
        """Production must send the session cookie over HTTPS only."""
        import os

        from spectre.config.settings import _resolve_cookie_secure

        saved = os.environ.pop("SPECTRE_COOKIE_SECURE", None)
        try:
            assert _resolve_cookie_secure() is True
        finally:
            if saved is not None:
                os.environ["SPECTRE_COOKIE_SECURE"] = saved

    def test_secure_flag_can_be_opted_out_explicitly(self) -> None:
        """Local HTTP development needs an explicit opt-out, never an inferred one."""
        import os

        from spectre.config.settings import _resolve_cookie_secure

        saved = os.environ.get("SPECTRE_COOKIE_SECURE")
        try:
            for value in ("false", "FALSE", "0", "no", "off"):
                os.environ["SPECTRE_COOKIE_SECURE"] = value
                assert _resolve_cookie_secure() is False
            os.environ["SPECTRE_COOKIE_SECURE"] = "true"
            assert _resolve_cookie_secure() is True
        finally:
            if saved is None:
                os.environ.pop("SPECTRE_COOKIE_SECURE", None)
            else:
                os.environ["SPECTRE_COOKIE_SECURE"] = saved


class TestLogoutClearsSession:
    def test_logout_then_root_is_anonymous_again(
        self, client: object, auth_cookie: str
    ) -> None:
        client.post(  # type: ignore[attr-defined]
            "/logout",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
            follow_redirects=False,
        )
        resp = client.get("/", cookies={}, follow_redirects=False)  # type: ignore[attr-defined]
        assert resp.status_code == 200
        assert b"Blue Assets" not in resp.content
