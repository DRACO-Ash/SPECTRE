"""Training records belong to the account, not the name.

Training progress, attempts and sessions were keyed on the username, so a
deleted account's history passed to anyone later created with the same name:
the pattern F-048 and F-148 fixed for sessions and planning state. Keying on
the account id alone is not enough either, because SQLite reuses a freed id,
so the rows are deleted with the account. Owner decision, 26 October 2026.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from spectre.training.models import ChallengeResult, TrainingProgress, TrainingSession
from tests.conftest import csrf_headers
from tests.integration.test_login_hardening import _admin_cookies, _user_id
from tests.integration.test_training_integrity import _CADET, _db, _operator, _promote, _start


def _rows(client: TestClient, user_id: int) -> dict[str, int]:
    async def count(session: Any) -> dict[str, int]:
        return {
            model.__tablename__: len((await session.execute(
                select(model).where(model.user_id == user_id)
            )).scalars().all())
            for model in (TrainingProgress, TrainingSession, ChallengeResult)
        }

    return _db(client, count)  # type: ignore[no-any-return]


def _delete(client: TestClient, admin: dict[str, str], user_id: int) -> None:
    resp = client.delete(f"/admin/users/{user_id}", cookies=admin, headers=csrf_headers(admin))
    assert resp.status_code == 200


class TestANamesakeStartsClean:
    def test_a_recreated_account_does_not_inherit_level_or_attempts(self, client: TestClient) -> None:
        cookie = _operator(client, "namesake_trainee")
        _promote(client, "namesake_trainee", 4)
        assert client.get("/training/", cookies={"spectre_session": cookie}).status_code == 200
        _start(client, cookie, _CADET)
        admin = _admin_cookies(client)
        old_id = _user_id(client, admin, "namesake_trainee")
        assert _rows(client, old_id) == {
            "training_progress": 1, "training_sessions": 1, "training_challenge_results": 1,
        }

        _delete(client, admin, old_id)
        assert _rows(client, old_id) == {
            "training_progress": 0, "training_sessions": 0, "training_challenge_results": 0,
        }, "the deleted account's training records survived it"

        _operator(client, "namesake_trainee")
        new_id = _user_id(client, _admin_cookies(client), "namesake_trainee")

        async def progress(session: Any) -> TrainingProgress:
            return (await session.execute(  # type: ignore[no-any-return]
                select(TrainingProgress).where(TrainingProgress.user_id == new_id)
            )).scalar_one()

        row = _db(client, progress)
        assert row.current_level == 1, "the namesake inherited the deleted account's level"
        assert _rows(client, new_id)["training_challenge_results"] == 0


class TestALegacyDatabaseIsMigrated:
    """A database created before the change: username keys, unique on the name."""

    @staticmethod
    async def _legacy(conn: Any) -> None:
        for statement in (
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL, "
            "hashed_password VARCHAR(128) NOT NULL DEFAULT '', role VARCHAR(16) NOT NULL DEFAULT 'operator')",
            "CREATE TABLE training_progress (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL, "
            "current_level INTEGER NOT NULL DEFAULT 1)",
            "CREATE UNIQUE INDEX ix_training_progress_username ON training_progress (username)",
            "CREATE TABLE training_sessions (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL)",
            "CREATE TABLE training_challenge_results (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL, "
            "scenario_id VARCHAR(128) NOT NULL DEFAULT 'x')",
            "INSERT INTO users (id, username) VALUES (5, 'alice')",
            "INSERT INTO training_progress (username, current_level) VALUES ('alice', 3), ('ghost', 6)",
            "INSERT INTO training_sessions (username) VALUES ('alice'), ('ghost')",
            "INSERT INTO training_challenge_results (username) VALUES ('alice'), ('ghost'), ('ghost')",
        ):
            await conn.execute(text(statement))

    async def test_rows_take_the_account_id_and_orphans_go(self) -> None:
        from sqlalchemy import inspect
        from sqlalchemy.ext.asyncio import create_async_engine

        from spectre.web.database import _apply_migrations

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await self._legacy(conn)
                await _apply_migrations(conn)
                await _apply_migrations(conn)  # a second boot changes nothing

                for table in ("training_progress", "training_sessions", "training_challenge_results"):
                    rows = (await conn.execute(text(f"SELECT username, user_id FROM {table}"))).all()  # noqa: S608
                    assert [tuple(r) for r in rows] == [("alice", 5)], table

                indexes = await conn.run_sync(
                    lambda c: {ix["name"]: ix["unique"] for ix in inspect(c).get_indexes("training_progress")}
                )
                assert indexes["ix_training_progress_username"] in (0, False)
                assert indexes["ix_training_progress_user_id"] in (1, True)

                # A namesake on another account can now hold its own progress.
                await conn.execute(text(
                    "INSERT INTO training_progress (username, user_id, current_level) VALUES ('alice', 9, 1)"
                ))
        finally:
            await engine.dispose()
