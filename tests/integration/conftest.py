"""Shared fixtures for the integration suite.

Every integration module needs the same four things: a test environment, an
initialised application, an HTTP client, and an authenticated session. Defining
them once here keeps the suite below the duplication threshold and means a
change to the harness happens in one place.
"""

from __future__ import annotations

import os

import pytest

# Must be set before importing anything that calls get_settings().
os.environ.setdefault("SECRET_KEY", "integration-test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SPECTRE_ADMIN_USER", "testadmin")
os.environ.setdefault("SPECTRE_ADMIN_PASS", "testpass123")
# The test client speaks plain HTTP, so a Secure cookie would never be returned.
# Production defaults to Secure; this is the explicit, test-only opt-out.
os.environ.setdefault("SPECTRE_COOKIE_SECURE", "false")

_TEST_USER = "testadmin"
# Fixture credential for an in-memory database created and destroyed inside
# the test process. It authenticates against nothing that outlives the run.
_TEST_PASSWORD = "testpass123"


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def initialized_app() -> object:
    """Return the FastAPI app with its tables created."""
    from spectre.web.app import app
    from spectre.web.database import init_db

    await init_db()
    return app


@pytest.fixture(scope="module")
def client(initialized_app: object) -> object:
    """Synchronous TestClient wrapping the initialised app."""
    from fastapi.testclient import TestClient

    with TestClient(initialized_app, raise_server_exceptions=True) as c:  # type: ignore[arg-type]
        yield c


def login_as(client: object, username: str, password: str) -> str:
    """Log in and return the session cookie value."""
    resp = client.post(  # type: ignore[attr-defined]
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    return str(resp.cookies["spectre_session"])


@pytest.fixture(scope="module")
def auth_cookie(client: object) -> str:
    """An authenticated admin session cookie."""
    return login_as(client, _TEST_USER, _TEST_PASSWORD)
