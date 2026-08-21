"""Fixtures for unit tests that need an HTTP client against the real app."""

from __future__ import annotations

import os

import pytest

# Must be set before importing anything that calls get_settings().
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-value")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def client() -> object:
    """TestClient wrapping the real application, lifespan included."""
    from fastapi.testclient import TestClient

    from spectre.web.app import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
