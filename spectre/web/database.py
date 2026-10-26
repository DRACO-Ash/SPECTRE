"""Async SQLAlchemy engine and session factory for SPECTRE."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from spectre.config.settings import get_settings, split_database_url

_settings = get_settings()

# The add-on hands over a libpq-style URL; asyncpg needs those parameters
# translated into connect arguments or it fails with a bare TypeError.
_url, _connect_args = split_database_url(_settings.database_url)

# Pool arguments. Reproduced against PostgreSQL 16: without pool_pre_ping, a
# backend the server has closed stays in the pool and the next checkout fails
# on its first statement with
#
#     InterfaceError: <asyncpg...InterfaceError>: connection is closed
#
# which is what the deployed app hit on login. pool_pre_ping makes SQLAlchemy
# test the connection on checkout and silently replace a dead one; pool_recycle
# discards connections before an intermediary is likely to.
#
# Kept a pure function so it can be tested without reloading this module. The
# engine is built at import time and other modules bind to it, so a reload in a
# test replaces an object the rest of the suite is already holding.
def build_pool_kwargs(url: str, recycle_seconds: int) -> dict[str, object]:
    """Return the pool arguments appropriate to *url*."""
    # Recycling exists to drop a TCP connection a database server or a
    # firewall may have closed under us. SQLite has no server and no socket,
    # and on an in-memory URL the pool IS the database: StaticPool holds one
    # connection and recycling it discards every table in it. Proved against
    # this helper's own output, with recycle at 2 seconds:
    #     immediately   -> 1 row
    #     after recycle -> OperationalError: no such table: users
    # Production is file-backed so the application was never affected, but the
    # test harness ran on a 300-second fuse, which is a second and independent
    # way for the Test stage to fail at random.
    if url.startswith("sqlite"):
        return {}

    kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": recycle_seconds,
    }
    # Sizing is a queue-pool concept for a networked server, which is what is
    # left once SQLite has returned above.
    kwargs["pool_size"] = 5
    kwargs["max_overflow"] = 10
    # Do not queue behind an exhausted pool indefinitely; fail the request
    # rather than hanging the worker that is holding it.
    kwargs["pool_timeout"] = 30
    return kwargs


_pool_kwargs = build_pool_kwargs(_url, _settings.db_pool_recycle)

engine = create_async_engine(
    _url, echo=False, connect_args=_connect_args, **_pool_kwargs
)

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
    # Import training models so their tables are registered on Base.metadata.
    # F401: the import is the point. It is never referenced; importing it is
    # what puts the training tables on Base.metadata before create_all runs.
    import spectre.training.models  # noqa: F401

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


# ALTER TABLE accepts no bind parameters. The table, the column and the type
# are part of the statement text rather than values, so this one statement has
# to be assembled by interpolation; there is no parameterised form of it to
# reach for. Every entry in the migration list is a literal declared three
# lines above the loop, so nothing operator-supplied reaches it today.
#
# This guard is what keeps that true. A migration sourced later from settings,
# an environment variable or a plugin would otherwise be concatenated into DDL
# unexamined, and the statement runs as the application's own database user.
# Anything that is not a bare identifier, or a type clause drawn from a narrow
# vocabulary, stops here rather than at the database.
_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")

# Uppercase keywords, digits, spaces, brackets and quotes: enough for the
# column types this project declares and nothing that can end a statement or
# open a comment. No semicolon, no hyphen, no slash, no double quote.
_SQL_COLUMN_DEFINITION = re.compile(r"[A-Z0-9 ()']{1,64}")


def _assert_safe_ddl(table: str, column: str, definition: str) -> None:
    """Raise unless all three parts of an ALTER TABLE are safe to interpolate.

    Raising is deliberate. A migration that fails this check is a programming
    error, and the alternative - skipping it - leaves the schema silently
    short of a column while the application starts and serves traffic.
    """
    for label, value, pattern in (
        ("table", table, _SQL_IDENTIFIER),
        ("column", column, _SQL_IDENTIFIER),
        ("definition", definition, _SQL_COLUMN_DEFINITION),
    ):
        if not pattern.fullmatch(value):
            raise ValueError(f"unsafe migration {label}: {value!r}")


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
    #
    # session_generation takes a CONSTANT default, which is the one kind
    # SQLite accepts in ALTER TABLE ADD COLUMN NOT NULL, and the definition
    # carries only uppercase letters, digits and spaces so it passes
    # _SQL_COLUMN_DEFINITION above without that guard being widened. A row
    # predating the column arrives at 0, which is where a fresh account
    # starts, so a migrated account and a new one behave identically.
    migrations: list[tuple[str, str, str]] = [
        ("training_challenge_results", "scored", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("users", "session_generation", "INTEGER NOT NULL DEFAULT 0"),
        # Existing rows take the empty nonce, and their tokens carry it too.
        ("users", "session_nonce", "VARCHAR(32) NOT NULL DEFAULT ''"),
    ]
    for table, column, definition in migrations:
        _assert_safe_ddl(table, column, definition)
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

    from spectre.web.auth import PASSWORD_TOO_LONG, hash_password, password_too_long
    from spectre.web.models import User

    settings = get_settings()
    username = settings.spectre_admin_user.strip()
    password = settings.spectre_admin_pass

    if password and password_too_long(password):
        # Raised from hash_password, this stopped the boot (audit F-150).
        logger.error("SPECTRE_ADMIN_PASS was not applied: %s Set a shorter one and redeploy.", PASSWORD_TOO_LONG)
        return

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
