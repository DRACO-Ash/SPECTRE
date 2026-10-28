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
_SQL_IDENTIFIER = re.compile(r"[A-Za-z_]\w{0,62}", re.ASCII)

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
        # Training rows keyed on the account. Nullable here only because a
        # legacy row has no value until _key_training_on_account fills it.
        ("training_progress", "user_id", "INTEGER"),
        ("training_sessions", "user_id", "INTEGER"),
        ("training_challenge_results", "user_id", "INTEGER"),
    ]
    for table, column, definition in migrations:
        _assert_safe_ddl(table, column, definition)
        existing = await conn.run_sync(_existing_columns, table)
        if not existing:
            continue  # table absent, so create_all will build it complete
        if column not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
    await _key_training_on_account(conn)


# Whole statements, one set per table, so no SQL is assembled from strings at
# all: backfill the account id from the username, remove what no account
# holds, and index the new key (progress takes its unique index separately).
_TRAINING_KEY_SQL: dict[str, tuple[str, str, str | None]] = {
    "training_progress": (
        "UPDATE training_progress SET user_id = (SELECT users.id FROM users "
        "WHERE users.username = training_progress.username) WHERE user_id IS NULL",
        "DELETE FROM training_progress WHERE user_id IS NULL",
        None,
    ),
    "training_sessions": (
        "UPDATE training_sessions SET user_id = (SELECT users.id FROM users "
        "WHERE users.username = training_sessions.username) WHERE user_id IS NULL",
        "DELETE FROM training_sessions WHERE user_id IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_training_sessions_user_id ON training_sessions (user_id)",
    ),
    "training_challenge_results": (
        "UPDATE training_challenge_results SET user_id = (SELECT users.id FROM users "
        "WHERE users.username = training_challenge_results.username) WHERE user_id IS NULL",
        "DELETE FROM training_challenge_results WHERE user_id IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_training_challenge_results_user_id "
        "ON training_challenge_results (user_id)",
    ),
}


def _index_uniqueness(sync_conn: Any, table: str) -> dict[str, bool]:
    """Each index on *table*, by name, mapped to whether it is unique."""
    from sqlalchemy import inspect

    return {str(ix["name"]): bool(ix["unique"]) for ix in inspect(sync_conn).get_indexes(table)}


async def _key_training_on_account(conn: Any) -> None:
    """Move legacy training rows from the username key to the account id.

    Training rows were keyed on the username, so a deleted account's history
    passed to a namesake created later. Legacy rows take the id of the
    account that holds their username now; rows whose username no account
    holds belong to a deleted account and are removed. Progress was unique on
    the username: that index becomes a plain one, and uniqueness moves to the
    account id. Safe to re-run: every step is a no-op once applied.
    """
    from sqlalchemy import text

    removed = 0
    for table, (backfill, drop_orphans, index) in _TRAINING_KEY_SQL.items():
        if "user_id" not in await conn.run_sync(_existing_columns, table):
            continue
        await conn.execute(text(backfill))
        orphans = await conn.execute(text(drop_orphans))
        removed += orphans.rowcount or 0
        if index is not None:
            await conn.execute(text(index))
    if removed:
        logger.warning(
            "Removed %d training record(s) whose account no longer exists while keying "
            "training on the account id.", removed,
        )
    if not await conn.run_sync(_existing_columns, "training_progress"):
        return
    indexes = await conn.run_sync(_index_uniqueness, "training_progress")
    if indexes.get("ix_training_progress_username"):
        await conn.execute(text("DROP INDEX ix_training_progress_username"))
        await conn.execute(text(
            "CREATE INDEX ix_training_progress_username ON training_progress (username)"
        ))
    if not indexes.get("ix_training_progress_user_id"):
        await conn.execute(text("DROP INDEX IF EXISTS ix_training_progress_user_id"))
        await conn.execute(text(
            "CREATE UNIQUE INDEX ix_training_progress_user_id ON training_progress (user_id)"
        ))



def _admin_password_refused(password: str) -> bool:
    """Whether SPECTRE_ADMIN_PASS is too long for bcrypt; logged if so.

    Raised from hash_password, it stopped the boot (audit F-150).
    """
    from spectre.web.auth import password_too_long

    if not password_too_long(password):
        return False
    # A literal message: nothing derived from a password-named value reaches
    # the log, so CodeQL's clear-text logging query has nothing to trace. The
    # 72 is auth.MAX_PASSWORD_BYTES, bcrypt's own limit, which does not move.
    logger.error(
        "SPECTRE_ADMIN_PASS was not applied: it is over bcrypt's 72 bytes "
        "(fewer characters if it is not plain ASCII). Set a shorter one and redeploy.",
    )
    return True


def _admin_username_refused(username: str) -> bool:
    """Log and return ``True`` when SPECTRE_ADMIN_USER fails the username rule.

    The admin form enforced the pattern and bootstrap did not, so the one
    account made from the environment could hold a name no form would accept
    (audit F-261). An empty name is left to the "no credentials" branch.
    """
    from spectre.web.auth import USERNAME_PATTERN

    if not username or USERNAME_PATTERN.fullmatch(username):
        return False
    logger.error(
        "SPECTRE_ADMIN_USER was not applied: a username is 1 to 64 characters of "
        "letters, digits and . _ @ -. Set a valid one and redeploy.",
    )
    return True


async def _break_glass(
    session: AsyncSession, existing: list[Any], username: str, password: str, promote: bool,
) -> None:
    """Reset *username*'s password, creating the admin account if it has gone."""
    from spectre.web.auth import hash_password
    from spectre.web.models import User

    target = next((u for u in existing if u.username == username), None)
    if target is not None and target.role != "admin" and not promote:
        logger.error(
            "ADMIN RESET REFUSED for %r: the account exists and is not an admin. "
            "Set SPECTRE_ADMIN_RESET_PROMOTE=true as well to promote it, or name an admin.",
            username,
        )
        return
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

    if _admin_password_refused(password) or _admin_username_refused(username):
        return

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(User))).scalars().all()

        if existing:
            if settings.admin_reset and username and password:
                # Break-glass recovery. Without it, a forgotten password means
                # dropping the database, because bootstrap only runs on an
                # empty table.
                await _break_glass(
                    session, list(existing), username, password, settings.admin_reset_promote,
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
