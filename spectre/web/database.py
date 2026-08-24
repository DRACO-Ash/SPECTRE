"""Async SQLAlchemy engine and session factory for SPECTRE."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from spectre.config.settings import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, echo=False)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


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
    from sqlalchemy import inspect  # noqa: PLC0415

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
    from sqlalchemy import text  # noqa: PLC0415

    migrations: list[tuple[str, str, str]] = [
        # (table, column, column_definition)
        ("training_challenge_results", "scored", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ]
    for table, column, definition in migrations:
        existing = await conn.run_sync(_existing_columns, table)
        if not existing:
            continue  # table absent, so create_all will build it complete
        if column not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))



async def _bootstrap_admin() -> None:
    """Insert a default admin user when the users table is empty."""
    from spectre.web.auth import hash_password  # noqa: PLC0415
    from spectre.web.models import User  # noqa: PLC0415

    settings = get_settings()
    if not settings.spectre_admin_user or not settings.spectre_admin_pass:
        return

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select  # noqa: PLC0415

        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # table already has at least one user

        admin = User(
            username=settings.spectre_admin_user,
            hashed_password=hash_password(settings.spectre_admin_pass),
            role="admin",
        )
        session.add(admin)
        await session.commit()
