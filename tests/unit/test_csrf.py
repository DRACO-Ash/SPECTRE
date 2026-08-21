"""Tests for the global CSRF control and the session-cookie helpers.

The CSRF dependency is applied to every route in the application factory, so a
regression here silently unlocks every state-changing endpoint at once.
"""

from __future__ import annotations

import pytest

from spectre.web.csrf import make_csrf_token, verify_csrf_token


class TestTokenBinding:
    def test_a_token_verifies_against_its_own_session(self) -> None:
        session = "session-cookie-value"
        assert verify_csrf_token(session, make_csrf_token(session)) is True

    def test_a_token_is_stable_within_one_session(self) -> None:
        """Same session, same token: the page and its HTMX calls must agree."""
        session = "session-cookie-value"
        assert make_csrf_token(session) == make_csrf_token(session)

    def test_a_token_does_not_verify_against_another_session(self) -> None:
        """This is the whole point of the control: tokens are session-bound."""
        stolen = make_csrf_token("victim-session-cookie-aaaaaaaaaaaaaaaa")
        assert verify_csrf_token("attacker-session-cookie-bbbbbbbbbbbb", stolen) is False

    def test_tokens_differ_between_sessions(self) -> None:
        a = make_csrf_token("session-a-" + "a" * 32)
        b = make_csrf_token("session-b-" + "b" * 32)
        assert a != b

    @pytest.mark.parametrize("bad", ["", "not-a-token", "csrf.tampered", "..", "x" * 200])
    def test_rejects_malformed_tokens(self, bad: str) -> None:
        assert verify_csrf_token("a-session-cookie-value", bad) is False

    def test_rejects_an_empty_session(self) -> None:
        assert verify_csrf_token("", make_csrf_token("something")) is False

    def test_rejects_an_empty_token(self) -> None:
        assert verify_csrf_token("a-session-cookie-value", "") is False


class TestEnforcement:
    """The dependency is global, so these run against the real application."""

    def test_safe_methods_pass_without_a_token(self, client: object) -> None:
        assert client.get("/login").status_code == 200  # type: ignore[attr-defined]

    def test_post_without_a_token_is_rejected(self, client: object) -> None:
        resp = client.post("/scenario/time", data={})  # type: ignore[attr-defined]
        assert resp.status_code == 403

    def test_post_with_a_foreign_token_is_rejected(self, client: object) -> None:
        """A token minted for a different session must not be accepted."""
        resp = client.post(  # type: ignore[attr-defined]
            "/scenario/time",
            data={},
            headers={"X-CSRF-Token": make_csrf_token("some-other-session")},
            cookies={"spectre_session": "this-session"},
        )
        assert resp.status_code == 403

    def test_login_is_exempt_so_a_session_can_be_established(self, client: object) -> None:
        """Login cannot require a token: there is no session to bind one to yet."""
        resp = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "nobody", "password": "wrong"},
            follow_redirects=False,
        )
        assert resp.status_code != 403


class TestSessionCookies:
    def test_round_trips_a_username(self) -> None:
        from spectre.web.auth import decode_session_cookie, make_session_cookie

        assert decode_session_cookie(make_session_cookie("operator1")) == "operator1"

    @pytest.mark.parametrize("bad", ["", "garbage", "a.b.c", "eyJzdWIiOiJ4In0.tampered.sig"])
    def test_rejects_an_invalid_cookie(self, bad: str) -> None:
        from spectre.web.auth import decode_session_cookie

        assert decode_session_cookie(bad) is None

    def test_a_cookie_signed_with_another_key_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Forging a session requires the signing key; a different key must fail."""
        from spectre.web.auth import decode_session_cookie, make_session_cookie

        forged = make_session_cookie("admin")
        monkeypatch.setenv("SECRET_KEY", "a-completely-different-signing-key")
        assert decode_session_cookie(forged) is None


class TestPasswordHashing:
    def test_verifies_a_correct_password(self) -> None:
        from spectre.web.auth import hash_password, verify_password

        assert verify_password("correct horse battery", hash_password("correct horse battery"))

    def test_rejects_a_wrong_password(self) -> None:
        from spectre.web.auth import hash_password, verify_password

        assert not verify_password("wrong", hash_password("correct horse battery"))

    def test_hash_is_salted(self) -> None:
        """Equal passwords must not produce equal hashes."""
        from spectre.web.auth import hash_password

        assert hash_password("same-password") != hash_password("same-password")

    def test_hash_does_not_contain_the_plaintext(self) -> None:
        from spectre.web.auth import hash_password

        assert "s3cret-value" not in hash_password("s3cret-value")
