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
