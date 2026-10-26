"""Passwords longer than bcrypt can hash are refused, not crashed on (audit F-150).

bcrypt reads at most 72 bytes. The pinned release raises ValueError past that
instead of truncating, and nothing caught it: a long password at /login was an
unmetered 500 on the one unauthenticated form, a long admin-set password was a
500, and a long SPECTRE_ADMIN_PASS stopped the boot. The limit is in bytes, so
a password of 72 characters can be over it once it holds anything but ASCII.
"""

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from spectre.web.auth import MAX_PASSWORD_BYTES, hash_password, password_too_long, verify_password
from tests.conftest import csrf_headers
from tests.integration.test_admin_bootstrap import _users, clean_db  # noqa: F401
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login, _user_id

_LONG = "x" * 100
# 36 characters, 72 bytes: exactly the limit.
_AT_LIMIT = "é" * 36
# 37 characters, 74 bytes: under 72 characters, over 72 bytes.
_OVER_IN_BYTES = "é" * 37


class TestTheLimitIsInBytes:
    def test_the_limit_is_bcrypts(self) -> None:
        assert MAX_PASSWORD_BYTES == 72

    def test_exactly_72_bytes_is_allowed(self) -> None:
        assert not password_too_long(_AT_LIMIT)

    def test_fewer_than_72_characters_can_still_be_too_long(self) -> None:
        assert len(_OVER_IN_BYTES) < 72
        assert password_too_long(_OVER_IN_BYTES)

    def test_an_over_long_password_never_matches(self) -> None:
        hashed = hash_password("short")
        assert verify_password(_LONG, hashed) is False

    def test_hashing_an_over_long_password_says_why(self) -> None:
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password(_LONG)


class TestLoginRefusesIt:
    def test_a_long_password_is_a_failed_sign_in_not_a_500(self, client: TestClient) -> None:
        resp = _login(client, "testadmin", _LONG, address="203.0.113.150")
        assert resp.status_code == 401
        assert b"Invalid username or password." in resp.content

    def test_it_is_charged_to_the_limiter(self, client: TestClient) -> None:
        # Ten failures exhaust an address; an eleventh attempt is refused.
        address = "203.0.113.151"
        codes = [_login(client, "nobody-f150", _LONG, address=address).status_code for _ in range(11)]
        assert codes[:10] == [401] * 10
        assert codes[10] == 429


class TestAdminRefusesIt:
    def test_create_refuses_with_a_form_error(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        resp = client.post(
            "/admin/users",
            data={"username": "f150_create", "password": _OVER_IN_BYTES, "role": "operator"},
            cookies=admin, headers=csrf_headers(admin),
        )
        assert resp.status_code == 200
        assert b"72 bytes" in resp.content
        assert b"f150_create" not in client.get("/admin/users", cookies=admin).content

    def test_update_refuses_and_changes_nothing(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "f150_update", "first-password")
        user_id = _user_id(client, admin, "f150_update")
        resp = client.post(
            f"/admin/users/{user_id}",
            data={"role": "admin", "new_password": _LONG},
            cookies=admin, headers=csrf_headers(admin),
        )
        assert resp.status_code == 200
        assert b"72 bytes" in resp.content
        # Neither the role nor the password moved.
        page = client.get("/admin/users", cookies=admin).content.decode()
        row = re.search(rf'<tr id="user-row-{user_id}".*?</tr>', page, re.S)
        assert row is not None
        assert ">operator</span>" in row.group(0)
        assert _login(client, "f150_update", "first-password", address="203.0.113.152").status_code == 302
        # The shared database counts admins elsewhere; leave none behind.
        admin = _admin_cookies(client)
        client.delete(f"/admin/users/{user_id}", cookies=admin, headers=csrf_headers(admin))
        client.cookies.clear()


class TestBootstrapRefusesIt:
    async def test_a_long_admin_password_is_refused_and_logged(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", _LONG)
        with caplog.at_level(logging.ERROR):
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
        assert "SPECTRE_ADMIN_PASS" in caplog.text
        assert "72 bytes" in caplog.text
        assert await _users(clean_db) == []
