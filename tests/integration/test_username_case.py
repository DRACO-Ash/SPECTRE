"""Usernames do not tell accounts apart by letter case (SPC-020).

An operator who signs in as "Ash" on one shift and "ash" on the next is the
same person. Matching on the exact spelling refused them with "Invalid
username or password" and let an admin create a second account that differed
only in case, so two people could hold what reads as one name in the audit
log. Each class pins one half of the rule.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spectre.web.models import User
from tests.conftest import csrf_headers
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login
from tests.integration.test_training_integrity import _db

# An authenticated route any operator may reach.
_PANEL = "/plan/decision/panel"


def _signs_in(client: TestClient, username: str, password: str, address: str) -> bool:
    """Whether *username* signs in and the session it gets opens a page."""
    client.cookies.clear()
    resp = _login(client, username, password, address=address)
    if resp.status_code != 302:
        return False
    page = client.get(_PANEL, cookies=dict(resp.cookies), follow_redirects=False)
    return page.status_code == 200


class TestSignInIgnoresCase:
    def test_any_case_of_the_name_signs_in_to_the_same_account(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "CaseOperator", "watch-floor-one")
        for n, spelling in enumerate(("CaseOperator", "caseoperator", "CASEOPERATOR")):
            assert _signs_in(client, spelling, "watch-floor-one", f"198.51.110.{n}"), spelling

    def test_the_session_carries_the_stored_spelling(self, client: TestClient) -> None:
        # require_login finds the account by the name in the token. A token
        # carrying the typed spelling would sign in and then bounce straight
        # back to the login page on the first request.
        admin = _admin_cookies(client)
        _create_operator(client, admin, "MixedCaseName", "watch-floor-two")
        client.cookies.clear()
        resp = _login(client, "mixedcasename", "watch-floor-two", address="198.51.110.20")
        assert resp.status_code == 302
        page = client.get("/", cookies=dict(resp.cookies))
        assert b"MixedCaseName" in page.content

    def test_a_wrong_password_is_still_refused(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "CaseGuard", "the-right-one")
        assert not _signs_in(client, "caseguard", "the-wrong-one", "198.51.110.30")


class TestCreationRefusesANameThatDiffersOnlyInCase:
    def test_a_lower_case_copy_of_an_existing_name_is_refused(self, client: TestClient) -> None:
        admin = _admin_cookies(client)
        _create_operator(client, admin, "ShiftLead", "first-holder")
        resp = client.post(
            "/admin/users",
            data={"username": "shiftlead", "password": "second-holder", "role": "operator"},
            cookies=admin,
            headers=csrf_headers(admin),
        )
        assert resp.status_code == 200
        assert b"already taken" in resp.content

        async def holders(session: Any) -> int:
            rows = await session.execute(text("SELECT COUNT(*) FROM users WHERE lower(username) = 'shiftlead'"))
            return int(rows.scalar_one())

        assert _db(client, holders) == 1


class TestOneRateLimitBudgetPerAccount:
    def test_changing_the_case_does_not_buy_more_guesses(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Keyed on the typed name, "Target", "TARGET" and "tArGeT" would each
        # carry ten guesses against one account once sign-in ignores case.
        monkeypatch.setattr("spectre.web.routes.login.verify_password", lambda *_: False)
        spellings = ("CaseTarget", "casetarget", "CASETARGET", "cAsEtArGeT", "Casetarget")
        for attempt in range(10):
            resp = _login(client, spellings[attempt % 5], "wrong", address=f"198.51.111.{attempt}")
            assert resp.status_code == 401, f"attempt {attempt + 1} was throttled too early"
        refused = _login(client, "CASETarget", "wrong", address="198.51.111.200")
        assert refused.status_code == 429


class TestNamesThatAlreadyDifferOnlyInCase:
    """A database from before this change may hold "Pilot" and "pilot" as two accounts."""

    @pytest.fixture()
    def namesakes(self, client: TestClient) -> None:
        from spectre.web.auth import hash_password

        async def add(session: Any) -> None:
            held = await session.execute(text("SELECT COUNT(*) FROM users WHERE lower(username) = 'legacypilot'"))
            if held.scalar_one():
                return
            await session.execute(text("DROP INDEX IF EXISTS ux_users_username_lower"))
            for name in ("LegacyPilot", "legacypilot"):
                session.add(User(username=name, hashed_password=hash_password(f"{name}-pw"), role="operator"))
            await session.commit()

        _db(client, add)

    def test_each_signs_in_by_its_exact_spelling(self, client: TestClient, namesakes: None) -> None:
        assert _signs_in(client, "LegacyPilot", "LegacyPilot-pw", "198.51.112.1")
        assert _signs_in(client, "legacypilot", "legacypilot-pw", "198.51.112.2")

    def test_a_third_spelling_is_not_guessed_between_them(self, client: TestClient, namesakes: None) -> None:
        assert not _signs_in(client, "LEGACYPILOT", "LegacyPilot-pw", "198.51.112.3")
        assert not _signs_in(client, "LEGACYPILOT", "legacypilot-pw", "198.51.112.4")


class TestTheBootMigration:
    """The case-blind unique index is added at boot, unless names already clash."""

    @staticmethod
    async def _boot(names: tuple[str, ...]) -> list[str]:
        from sqlalchemy.ext.asyncio import create_async_engine

        from spectre.web.database import _apply_migrations

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE NOT NULL, "
                    "hashed_password VARCHAR(256) NOT NULL, role VARCHAR(16) NOT NULL, created_at DATETIME)"
                ))
                for name in names:
                    await conn.execute(
                        text("INSERT INTO users (username, hashed_password, role) VALUES (:n, '', 'operator')"),
                        {"n": name},
                    )
                await _apply_migrations(conn)
                await _apply_migrations(conn)  # a second boot changes nothing
                rows = await conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'users'"
                ))
                return [str(r[0]) for r in rows]
        finally:
            await engine.dispose()

    async def test_the_index_is_added_when_no_names_clash(self) -> None:
        assert "ux_users_username_lower" in await self._boot(("Alpha", "bravo"))

    async def test_clashing_names_leave_the_index_off_and_say_so(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger="spectre.web.database"):
            indexes = await self._boot(("Alpha", "alpha"))
        assert "ux_users_username_lower" not in indexes
        assert "differ only in letter case" in caplog.text


class TestTheMatchingRule:
    """account_named is the one rule sign-in and the break-glass admin reset share."""

    @staticmethod
    def _users(*names: str) -> list[User]:
        return [User(username=n, hashed_password="", role="operator") for n in names]

    def test_the_exact_spelling_wins(self) -> None:
        from spectre.web.auth import account_named

        found = account_named(self._users("Admin", "admin"), "admin")
        assert found is not None and found.username == "admin"

    def test_a_single_namesake_is_found_in_any_case(self) -> None:
        from spectre.web.auth import account_named

        found = account_named(self._users("Admin", "pilot"), "ADMIN")
        assert found is not None and found.username == "Admin"

    def test_two_namesakes_and_no_exact_spelling_find_nobody(self) -> None:
        from spectre.web.auth import account_named

        assert account_named(self._users("Admin", "admin"), "ADMIN") is None
