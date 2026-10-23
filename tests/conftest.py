"""Shared pytest fixtures for the SPECTRE test suite."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from spectre.domain.models import AccessInterval, RunConfig


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
