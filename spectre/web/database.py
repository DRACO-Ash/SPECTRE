"""Async SQLAlchemy engine and session factory for SPECTRE."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from spectre.config.settings import get_settings, split_database_url

_settings = get_settings()

# The add-on hands over a libpq-style URL; asyncpg needs those parameters
# translated into connect arguments or it fails with a bare TypeError.
_url, _connect_args = split_database_url(_settings.database_url)

engine = create_async_engine(_url, echo=False, connect_args=_connect_args)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency that yields a database session per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create all tables and bootstrap the default admin user if the table is empty."""
    # Import training models so their tables are registered on Base.metadata
    import spectre.training.models  # noqa: F401 — side-effect import registers ORM tables

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive migrations for columns added after initial deployment
        await _apply_migrations(conn)

    await _bootstrap_admin()


def _existing_columns(sync_conn: Any, table: str) -> set[str]:
    """Return the column names of *table*, or an empty set if it does not exist.

    Uses SQLAlchemy's inspector rather than a dialect-specific query. The
    previous implementation issued ``PRAGMA table_info``, which is SQLite-only
    and made the whole boot fail on PostgreSQL with a bare syntax error.
    """
    # Deferred: keeps the import cost on the boot path only.
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


async def _apply_migrations(conn: Any) -> None:
    """Apply additive ALTER TABLE migrations that are safe to re-run.

    These exist only for databases created before a column was added. A fresh
    database gets the column from ``create_all``, so on a new PostgreSQL
    instance every migration here is already satisfied and none of the
    SQLite-flavoured DDL below ever executes.
    """
    # Deferred: keeps the import cost on the boot path only.
    from sqlalchemy import text

    # Each entry is a table, a column, and the definition used to add it.
    migrations: list[tuple[str, str, str]] = [
        ("training_challenge_results", "scored", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ]
    for table, column, definition in migrations:
        existing = await conn.run_sync(_existing_columns, table)
        if not existing:
            continue  # table absent, so create_all will build it complete
        if column not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))



async def _bootstrap_admin() -> None:
    """Create the first admin account, and say plainly what happened.

    Every branch logs. A silent skip here produces the worst possible outcome:
    a container that passes every health check while nobody on earth can log
    in, with nothing in the log to explain it.
    """
    # Deferred: keeps the import cost on the boot path only.
    from sqlalchemy import select

    from spectre.web.auth import hash_password
    from spectre.web.models import User

    settings = get_settings()
    username = settings.spectre_admin_user.strip()
    password = settings.spectre_admin_pass

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(User))).scalars().all()

        if existing:
            if settings.admin_reset and username and password:
                # Break-glass recovery. Without it, a forgotten password means
                # dropping the database, because bootstrap only runs on an
                # empty table.
                target = next((u for u in existing if u.username == username), None)
                if target is None:
                    target = User(username=username, hashed_password="", role="admin")
                    session.add(target)
                target.hashed_password = hash_password(password)
                target.role = "admin"
                await session.commit()
                logger.warning(
                    "ADMIN RESET APPLIED for %r because SPECTRE_ADMIN_RESET is set. "
                    "Unset it and redeploy: leaving it on resets the password every boot.",
                    username,
                )
                return
            logger.info(
                "Admin bootstrap skipped: %d account(s) already exist. "
                "Set SPECTRE_ADMIN_RESET=true to reset %r if the password is lost.",
                len(existing), username or "the admin account",
            )
            return

        if not username or not password:
            logger.error(
                "NO USERS EXIST AND NO ADMIN CREDENTIALS WERE SUPPLIED, so nobody can "
                "log in. Set SPECTRE_ADMIN_USER and SPECTRE_ADMIN_PASS in the "
                "environment and redeploy. Currently: SPECTRE_ADMIN_USER=%s, "
                "SPECTRE_ADMIN_PASS=%s.",
                f"{username!r}" if username else "unset",
                "set" if password else "UNSET",
            )
            return

        session.add(
            User(
                username=username,
                hashed_password=hash_password(password),
                role="admin",
            )
        )
        await session.commit()
        logger.info("Admin bootstrap: created the initial admin account %r.", username)
