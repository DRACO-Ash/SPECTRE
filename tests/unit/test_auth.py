"""Unit tests for sipc.web.auth — password hashing and session cookie helpers."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")


from sipc.web.auth import (  # noqa: E402
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
