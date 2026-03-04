"""Shared pytest fixtures for the SIPC test suite."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from sipc.domain.models import AccessInterval, RunConfig
from sipc.stk_adapter.fake import FakeStkSession


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to avoid PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests requiring a live STK COM connection "
        "(deselect with -m 'not integration')",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip integration tests unless STK_INTEGRATION_TESTS=1."""
    if os.environ.get("STK_INTEGRATION_TESTS") == "1":
        return
    skip_integration = pytest.mark.skip(
        reason="Set STK_INTEGRATION_TESTS=1 to run integration tests"
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_integration)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_session() -> FakeStkSession:
    """Return a fresh FakeStkSession for each test."""
    return FakeStkSession()


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
