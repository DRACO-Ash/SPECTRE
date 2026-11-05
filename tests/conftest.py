"""Shared pytest fixtures for the SPECTRE test suite."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import pytest

from spectre.domain.models import AccessInterval, RunConfig

# The data directory, where the NOTSO cache is seeded on first use (audit
# F-062), is a scratch directory for the suite rather than ./data in the tree.
os.environ.setdefault("SPECTRE_DATA_DIR", tempfile.mkdtemp(prefix="spectre-test-data-"))


@pytest.fixture()
def run_config() -> RunConfig:
    """Return a deterministic RunConfig for testing."""
    return RunConfig(
        operator="test_operator",
        source="TEST",
        timestamp=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
        run_id="RUN_TEST000001",
    )


@pytest.fixture()
def sample_access_interval() -> AccessInterval:
    """Return a sample AccessInterval for test assertions."""
    return AccessInterval(
        start=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
        end=datetime(2026, 3, 4, 12, 10, 0, tzinfo=UTC),
    )


def csrf_headers(session: str | dict[str, str]) -> dict[str, str]:
    """Return the CSRF header a browser (or HTMX) would send for *session*.

    Accepts either the raw ``spectre_session`` cookie value or the cookies dict
    a login response yields. The application enforces CSRF globally via
    ``spectre.web.csrf.require_csrf``, so every non-safe request in the suite
    must carry a valid token. Minting it here exercises the real control rather
    than disabling it under test.
    """
    # Deferred so the import happens after the test environment is configured.
    from spectre.web.csrf import make_csrf_token

    cookie = session if isinstance(session, str) else session.get("spectre_session", "")
    return {"X-CSRF-Token": make_csrf_token(cookie)}


def keep_each_connection_on_its_own_loop() -> None:
    """On a networked database, open a connection per checkout instead of pooling them (SPC-070).

    The suite runs the app on more than one event loop: init_db on the test's
    loop, each module's TestClient on a loop of its own, and async tests on
    theirs. asyncpg binds a connection to the loop that opened it, so a pooled
    connection handed to a second loop fails with "attached to a different
    loop". The server runs one loop and never meets this; aiosqlite does not
    bind connections to a loop, so on SQLite the suite never met it either.

    Only the pool's class changes. Pre-ping and recycle are carried over, so
    the pool contract test still reads the engine's real settings, and the
    engine object every module imported is the same one. A no-op on SQLite.
    """
    from sqlalchemy.pool import NullPool

    from spectre.web import database

    sync_engine = database.engine.sync_engine
    if sync_engine.dialect.name == "sqlite" or isinstance(sync_engine.pool, NullPool):
        return
    pooled = sync_engine.pool
    # The engine's listeners, the one that reads the server version on first connect among them, live on the pool.
    sync_engine.pool = NullPool(
        pooled._creator, recycle=pooled._recycle, pre_ping=pooled._pre_ping, dialect=pooled._dialect,
        reset_on_return=pooled._reset_on_return, _dispatch=pooled.dispatch,
    )
