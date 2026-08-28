"""Kill the backend server-side, then exercise the app's OWN engine and the
real login query. Verifies the shipped configuration, not a reconstruction."""
import asyncio, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main() -> int:
    import spectre.web.database as db
    import spectre.web.models  # noqa: F401  register the User table

    print(f"  engine       : {db.engine.url.drivername}")
    print(f"  pre_ping     : {db.engine.pool._pre_ping}")
    print(f"  recycle      : {db.engine.pool._recycle}s")

    async with db.engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)

    from sqlalchemy import select
    from spectre.web.models import User

    async with db.AsyncSessionLocal() as s:           # warm the pool
        await s.execute(select(User).where(User.username == "admin"))
    print("  warmed the pool with the real login query")

    killer = create_async_engine(str(db.engine.url), echo=False)
    async with killer.connect() as c:
        n = await c.execute(text(
            "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"))
        print(f"  terminated {n.scalar()} backend(s) server-side")
    await killer.dispose()

    try:
        async with db.AsyncSessionLocal() as s:
            await s.execute(select(User).where(User.username == "admin"))
        print("  login query after the kill: RECOVERED")
        rc = 0
    except Exception as exc:
        print(f"  login query after the kill: FAILED -> {type(exc).__name__}")
        rc = 1
    await db.engine.dispose()
    return rc

sys.exit(asyncio.run(main()))
