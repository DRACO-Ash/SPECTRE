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
    def test_pre_ping_is_always_enabled(self) -> None:
        """Without this, a server-closed connection is handed to the next caller."""
        for url in (_POSTGRES, _SQLITE):
            assert build_pool_kwargs(url, 300)["pool_pre_ping"] is True, url

    def test_recycle_is_applied_to_both_dialects(self) -> None:
        for url in (_POSTGRES, _SQLITE):
            assert build_pool_kwargs(url, 300)["pool_recycle"] == 300, url

    def test_postgres_sizing_is_bounded(self) -> None:
        """An unbounded pool starves the server; an unbounded wait hangs a worker."""
        kwargs = build_pool_kwargs(_POSTGRES, 300)
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10
        assert kwargs["pool_timeout"] == 30

    def test_sqlite_gets_no_sizing_arguments(self) -> None:
        assert set(build_pool_kwargs(_SQLITE, 300)) == {"pool_pre_ping", "pool_recycle"}


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
    def test_the_engine_actually_carries_the_arguments(self) -> None:
        """Guards against the arguments being computed but never passed."""
        assert engine.pool._pre_ping is True
        assert engine.pool._recycle == DEFAULT_POOL_RECYCLE_SECONDS
