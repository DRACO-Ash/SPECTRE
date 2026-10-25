"""A session belongs to an account, not to a name.

Step 4 of the audit remediation, the "identity keyed on username" cluster.
Sessions, planning state and revocation were all keyed on the username,
so anything bound to a name outlived the account that held it.
"""

from __future__ import annotations

import re

from tests.conftest import csrf_headers
from tests.integration.conftest import login_as

_ADMIN = ("testadmin", "testpass123")


def _admin(client: object) -> dict[str, str]:
    return {"spectre_session": login_as(client, *_ADMIN)}


def _create(client: object, admin: dict[str, str], username: str, role: str = "operator") -> None:
    resp = client.post(  # type: ignore[attr-defined]
        "/admin/users", data={"username": username, "password": "pass-123", "role": role},
        cookies=admin, headers=csrf_headers(admin),
    )
    assert resp.status_code == 200


def _user_id(client: object, admin: dict[str, str], username: str) -> str:
    page = client.get("/admin/users", cookies=admin).text  # type: ignore[attr-defined]
    rows = re.split(r'(?=id="user-row-\d+")', page)
    for row in rows:
        found = re.match(r'id="user-row-(\d+)"', row)
        if found and re.search(rf">\s*{re.escape(username)}\s*<", row):
            return found.group(1)
    raise AssertionError(f"no row for {username}")


def _delete(client: object, admin: dict[str, str], username: str) -> None:
    user_id = _user_id(client, admin, username)
    resp = client.delete(f"/admin/users/{user_id}", cookies=admin, headers=csrf_headers(admin))  # type: ignore[attr-defined]
    assert resp.status_code == 200


def _status(client: object, cookie: str) -> int:
    resp = client.get("/admin/users", cookies={"spectre_session": cookie}, follow_redirects=False)  # type: ignore[attr-defined]
    return int(resp.status_code)


class TestATokenIsBoundToItsAccount:
    """Audit F-048: a recreated account accepted the old account's tokens."""

    def test_a_deleted_accounts_token_does_not_open_its_namesake(self, client: object) -> None:
        admin = _admin(client)
        _create(client, admin, "f048-alice")
        old = login_as(client, "f048-alice", "pass-123")
        assert _status(client, old) == 403, "a live operator session reaches the admin page and is refused there"

        _delete(client, admin, "f048-alice")
        _create(client, admin, "f048-alice", role="admin")

        resp = client.get("/admin/users", cookies={"spectre_session": old}, follow_redirects=False)  # type: ignore[attr-defined]
        _delete(client, admin, "f048-alice")   # the suite shares one database; leave no extra admin
        assert resp.status_code == 302, "the old token opened the new admin account"
        assert resp.headers["location"] == "/login"

    def test_the_new_accounts_own_sign_in_works(self, client: object) -> None:
        admin = _admin(client)
        _create(client, admin, "f048-bob")
        _delete(client, admin, "f048-bob")
        _create(client, admin, "f048-bob", role="admin")
        status = _status(client, login_as(client, "f048-bob", "pass-123"))
        _delete(client, admin, "f048-bob")
        assert status == 200


class TestAnExistingDatabaseGainsTheNonce:
    """A database from before the column gets it, and its rows keep working."""

    async def test_an_old_users_table_is_migrated(self, tmp_path: object) -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from spectre.web.database import _apply_migrations

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/old.db")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE NOT NULL, "
                "hashed_password VARCHAR(256) NOT NULL, role VARCHAR(16) NOT NULL, created_at DATETIME NOT NULL)"
            ))
            await conn.execute(text(
                "INSERT INTO users VALUES (1, 'veteran', 'x', 'operator', '2026-01-01 00:00:00')"
            ))
            await _apply_migrations(conn)
            row = (await conn.execute(text("SELECT session_generation, session_nonce FROM users"))).one()
        await engine.dispose()
        assert tuple(row) == (0, ""), "a migrated account starts at generation 0 with the empty nonce"
