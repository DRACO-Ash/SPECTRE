"""Async SQLAlchemy engine and session factory for SIPC."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from sipc.config.settings import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, echo=False)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create all tables and bootstrap the default admin user if the table is empty."""
    from sipc.web.models import User  # noqa: PLC0415  (avoid circular import at module load)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _bootstrap_admin()


async def _bootstrap_admin() -> None:
    """Insert a default admin user when the users table is empty."""
    from passlib.context import CryptContext  # noqa: PLC0415

    from sipc.web.models import User  # noqa: PLC0415

    settings = get_settings()
    if not settings.sipc_admin_user or not settings.sipc_admin_pass:
        return

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select  # noqa: PLC0415

        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # table already has at least one user

        pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = User(
            username=settings.sipc_admin_user,
            hashed_password=pwd_ctx.hash(settings.sipc_admin_pass),
            role="admin",
        )
        session.add(admin)
        await session.commit()
