"""Unit tests for spectre.web.auth — password hashing and session cookie helpers."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")


from spectre.web.auth import (
    decode_session_cookie,
    hash_password,
    make_session_cookie,
    verify_password,
)


class TestPasswordHelpers:
    def test_hash_is_not_plaintext(self) -> None:
        hashed = hash_password("hunter2")
        assert hashed != "hunter2"

    def test_verify_correct_password(self) -> None:
        hashed = hash_password("correct-horse")
        assert verify_password("correct-horse", hashed) is True

    def test_verify_wrong_password(self) -> None:
        hashed = hash_password("correct-horse")
        assert verify_password("wrong-horse", hashed) is False

    def test_different_hashes_for_same_password(self) -> None:
        h1 = hash_password("same")
        h2 = hash_password("same")
        # bcrypt salts should differ
        assert h1 != h2


class TestSessionCookie:
    def test_round_trip(self) -> None:
        token = make_session_cookie("alice")
        assert decode_session_cookie(token) == "alice"

    def test_invalid_token_returns_none(self) -> None:
        assert decode_session_cookie("garbage-token") is None

    def test_tampered_token_returns_none(self) -> None:
        token = make_session_cookie("alice")
        tampered = token[:-4] + "XXXX"
        assert decode_session_cookie(tampered) is None

    def test_a_cookie_signed_with_another_key_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Forging a session requires the signing key; a different key must fail.

        Moved from test_csrf.py, whose copies of this module's other cookie
        and hashing tests were removed as duplicates (audit F-156).
        """
        forged = make_session_cookie("admin")
        monkeypatch.setenv("SECRET_KEY", "a-completely-different-signing-key")
        assert decode_session_cookie(forged) is None
