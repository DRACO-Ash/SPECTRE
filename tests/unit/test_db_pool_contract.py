"""The database engine must survive a connection closed by the server.

Reproduced against PostgreSQL 16 before this was fixed: with no pool
arguments, a backend closed server-side stays in SQLAlchemy's pool and the
next checkout fails on its first statement with

    InterfaceError: <asyncpg...InterfaceError>: connection is closed

The deployed app hit exactly that on login, which is a low-traffic path and so
the likeliest place for a long-idle connection to be handed out.

The decision is tested through a pure function rather than by reloading the
data layer. The engine is built at import time and the rest of the suite binds
to it, so a reload here would hand other tests an engine with no tables.
"""

from __future__ import annotations

from spectre.config.settings import DEFAULT_POOL_RECYCLE_SECONDS, Settings
from spectre.web.database import build_pool_kwargs, engine

_POSTGRES = "postgresql+asyncpg://u:p@localhost:5432/spectre"
_SQLITE = "sqlite+aiosqlite:///./data/spectre.db"


class TestPoolArguments:
    """Pre-ping and recycle are for a networked server, and only for one.

    These originally applied to both dialects, which was wrong in a way that
    only a long-running test could show. Recycling exists to drop a TCP
    connection a server or a firewall may have closed underneath the pool.
    SQLite has neither, and on an in-memory URL the pool IS the database:
    StaticPool holds a single connection and recycling it discards every table
    in it. Measured against this helper's own output with recycle at two
    seconds, a query that returned a row immediately raised
    ``OperationalError: no such table: users`` after the recycle.

    Production is file-backed, so the application was never affected. The test
    harness was: it ran on a 300-second fuse, an independent way for the Test
    stage to fail at random on a slow run.
    """

    def test_pre_ping_is_enabled_for_a_networked_dialect(self) -> None:
        """Without this, a server-closed connection is handed to the next caller.

        This is the original defect, reproduced against PostgreSQL 16 and
        still the reason this module exists. It must not be lost while fixing
        the SQLite half.
        """
        assert build_pool_kwargs(_POSTGRES, 300)["pool_pre_ping"] is True

    def test_recycle_is_applied_to_a_networked_dialect(self) -> None:
        assert build_pool_kwargs(_POSTGRES, 300)["pool_recycle"] == 300

    def test_postgres_sizing_is_bounded(self) -> None:
        """An unbounded pool starves the server; an unbounded wait hangs a worker."""
        kwargs = build_pool_kwargs(_POSTGRES, 300)
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10
        assert kwargs["pool_timeout"] == 30

    def test_sqlite_gets_no_pool_arguments_at_all(self) -> None:
        """Not merely no sizing: no recycle and no pre-ping either."""
        for url in (_SQLITE, "sqlite+aiosqlite:///:memory:"):
            assert build_pool_kwargs(url, 300) == {}, url

    def test_recycling_an_in_memory_database_would_destroy_it(self) -> None:
        """The reason the rule above exists, demonstrated rather than asserted.

        If a future change reinstates recycling for SQLite, this is what it
        costs. The engine here is built locally and thrown away, so it cannot
        disturb the engine the rest of the suite is bound to.
        """
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        async def exercise() -> str:
            engine_with_recycle = create_async_engine(
                "sqlite+aiosqlite:///:memory:", pool_pre_ping=True, pool_recycle=1,
            )
            try:
                async with engine_with_recycle.begin() as conn:
                    await conn.execute(text("CREATE TABLE probe (id INTEGER)"))
                    await conn.execute(text("INSERT INTO probe VALUES (1)"))
                await asyncio.sleep(1.2)   # outlive the recycle
                async with engine_with_recycle.begin() as conn:
                    await conn.execute(text("SELECT COUNT(*) FROM probe"))
            except Exception as exc:        # noqa: BLE001 - the point is the class
                return type(exc).__name__
            else:
                return "survived"
            finally:
                await engine_with_recycle.dispose()

        assert asyncio.run(exercise()) != "survived", (
            "recycling an in-memory SQLite database no longer destroys it, so "
            "the rule above may be obsolete; re-derive it before relaxing it"
        )


class TestRecycleSetting:
    def test_default_is_below_common_proxy_idle_timeouts(self) -> None:
        """Managed PostgreSQL proxies commonly cut idle connections at 350s."""
        assert 0 < DEFAULT_POOL_RECYCLE_SECONDS < 350

    def test_reads_the_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("SPECTRE_DB_POOL_RECYCLE", "120")
        assert Settings().db_pool_recycle == 120

    def test_a_nonsense_value_falls_back_rather_than_disabling(self, monkeypatch) -> None:
        """A typo must not silently switch recycling off."""
        for bad in ("not-a-number", "-5", ""):
            monkeypatch.setenv("SPECTRE_DB_POOL_RECYCLE", bad)
            assert Settings().db_pool_recycle == DEFAULT_POOL_RECYCLE_SECONDS, bad

    def test_zero_disables_recycling_deliberately(self, monkeypatch) -> None:
        """An explicit 0 is a real choice, unlike a typo."""
        monkeypatch.setenv("SPECTRE_DB_POOL_RECYCLE", "0")
        assert Settings().db_pool_recycle == 0


class TestLiveEngine:
    def test_the_engine_actually_carries_what_its_dialect_calls_for(self) -> None:
        """Guards against the arguments being computed but never passed.

        Dialect-aware, because the suite's own engine is SQLite and must now
        carry no recycle at all. Asserting the PostgreSQL shape here would
        pass only on a deployment nobody runs the tests against.
        """
        expected = build_pool_kwargs(str(engine.url), DEFAULT_POOL_RECYCLE_SECONDS)
        if expected:
            assert engine.pool._pre_ping is True
            assert engine.pool._recycle == DEFAULT_POOL_RECYCLE_SECONDS
        else:
            assert engine.pool._recycle == -1, (
                "a SQLite engine is carrying a recycle, which on an in-memory "
                "URL discards the schema mid-run"
            )
