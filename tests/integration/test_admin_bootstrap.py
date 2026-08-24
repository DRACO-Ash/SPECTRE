"""Tests for the first-admin bootstrap.

This ran silently in every branch, which produced the worst kind of failure: a
container passing every health check while nobody could log in, and nothing in
the log to say why. It cost a deploy cycle to notice. Every path must now
announce itself.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture()
async def clean_db(monkeypatch: pytest.MonkeyPatch) -> object:
    """A fresh in-memory database with no users."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from spectre.web import database as db

    # StaticPool keeps every checkout on the same connection. Without it each
    # connection gets its own private in-memory database and the tables vanish.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "AsyncSessionLocal", maker)

    # Both modules must be imported before create_all, or their tables are
    # simply absent from the metadata and never created.
    import spectre.training.models  # noqa: F401
    import spectre.web.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    return db


async def _users(db: object) -> list[object]:
    from sqlalchemy import select

    from spectre.web.models import User

    async with db.AsyncSessionLocal() as session:  # type: ignore[attr-defined]
        return list((await session.execute(select(User))).scalars().all())


class TestFirstBoot:
    async def test_creates_the_admin_and_says_so(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "a-real-password")
        with caplog.at_level(logging.INFO):
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
        assert "created the initial admin account" in caplog.text
        users = await _users(clean_db)
        assert [u.username for u in users] == ["operator1"]  # type: ignore[attr-defined]

    async def test_missing_password_logs_an_error_naming_the_variable(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The exact failure seen in production: healthy pod, nobody can log in."""
        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.delenv("SPECTRE_ADMIN_PASS", raising=False)
        with caplog.at_level(logging.ERROR):
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
        assert "NO USERS EXIST" in caplog.text
        assert "SPECTRE_ADMIN_PASS" in caplog.text
        assert await _users(clean_db) == []

    async def test_the_error_never_prints_the_password(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.delenv("SPECTRE_ADMIN_USER", raising=False)
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "super-secret-value")
        with caplog.at_level(logging.ERROR):
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
        assert "super-secret-value" not in caplog.text


class TestSubsequentBoots:
    async def test_existing_users_are_left_alone_and_reported(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "first-password")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "a-different-password")
        with caplog.at_level(logging.INFO):
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
        assert "Admin bootstrap skipped" in caplog.text
        assert "SPECTRE_ADMIN_RESET" in caplog.text, "must name the recovery route"

    async def test_changing_the_password_alone_does_nothing(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A surprise worth pinning: editing the variable does not rotate it."""
        from spectre.web.auth import verify_password

        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "first-password")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "a-different-password")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
        user = (await _users(clean_db))[0]
        assert verify_password("first-password", user.hashed_password)  # type: ignore[attr-defined]


class TestBreakGlassReset:
    async def test_reset_rotates_the_password_when_explicitly_enabled(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from spectre.web.auth import verify_password

        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "first-password")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "recovered-password")
        monkeypatch.setenv("SPECTRE_ADMIN_RESET", "true")
        with caplog.at_level(logging.WARNING):
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        assert "ADMIN RESET APPLIED" in caplog.text
        assert "Unset it" in caplog.text, "must tell the operator to turn it off"
        user = next(u for u in await _users(clean_db) if u.username == "operator1")  # type: ignore[attr-defined]
        assert verify_password("recovered-password", user.hashed_password)  # type: ignore[attr-defined]

    async def test_reset_is_off_unless_explicitly_enabled(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from spectre.web.auth import verify_password

        monkeypatch.setenv("SPECTRE_ADMIN_USER", "operator1")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "first-password")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "attempted-change")
        for value in ("", "false", "0", "no", "off"):
            monkeypatch.setenv("SPECTRE_ADMIN_RESET", value)
            await clean_db._bootstrap_admin()  # type: ignore[attr-defined]
            user = (await _users(clean_db))[0]
            assert verify_password("first-password", user.hashed_password)  # type: ignore[attr-defined]

    async def test_reset_recreates_the_account_if_it_was_deleted(
        self, clean_db: object, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Someone deleting the last admin must still have a way back in."""
        from spectre.web.auth import verify_password

        monkeypatch.setenv("SPECTRE_ADMIN_USER", "someone-else")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "their-password")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        monkeypatch.setenv("SPECTRE_ADMIN_USER", "rescue-admin")
        monkeypatch.setenv("SPECTRE_ADMIN_PASS", "rescue-password")
        monkeypatch.setenv("SPECTRE_ADMIN_RESET", "true")
        await clean_db._bootstrap_admin()  # type: ignore[attr-defined]

        user = next(u for u in await _users(clean_db) if u.username == "rescue-admin")  # type: ignore[attr-defined]
        assert user.role == "admin"  # type: ignore[attr-defined]
        assert verify_password("rescue-password", user.hashed_password)  # type: ignore[attr-defined]
