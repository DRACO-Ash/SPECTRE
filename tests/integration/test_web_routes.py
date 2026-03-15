"""Integration tests for SIPC web routes using FastAPI TestClient.

Requires the web dependencies (httpx, fastapi, etc.) to be installed.
These tests use an in-memory SQLite database and a test SECRET_KEY.
"""

from __future__ import annotations

import os

import pytest

# Must be set before importing anything that calls get_settings().
os.environ["SECRET_KEY"] = "integration-test-secret"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SIPC_ADMIN_USER"] = "testadmin"
os.environ["SIPC_ADMIN_PASS"] = "testpass123"

pytest_plugins = ("anyio",)


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def initialized_app() -> object:
    """Return the FastAPI app with DB tables created."""
    from sipc.web.app import app
    from sipc.web.database import init_db

    await init_db()
    return app


@pytest.fixture(scope="module")
def client(initialized_app: object) -> object:
    """Synchronous TestClient wrapping the initialized app."""
    from fastapi.testclient import TestClient

    with TestClient(initialized_app, raise_server_exceptions=True) as c:  # type: ignore[arg-type]
        yield c


class TestLoginFlow:
    def test_get_login_page(self, client: object) -> None:
        resp = client.get("/login")  # type: ignore[attr-defined]
        assert resp.status_code == 200
        assert b"SIPC" in resp.content and b"login" in resp.content.lower()

    def test_login_wrong_password(self, client: object) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/login", data={"username": "testadmin", "password": "wrong"}, follow_redirects=False
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, client: object) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/login", data={"username": "ghost", "password": "x"}, follow_redirects=False
        )
        assert resp.status_code == 401

    def test_login_success_redirects(self, client: object) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "testadmin", "password": "testpass123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_login_sets_session_cookie(self, client: object) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "testadmin", "password": "testpass123"},
            follow_redirects=False,
        )
        assert "sipc_session" in resp.cookies


class TestProtectedRoutes:
    def test_unauthenticated_dashboard_redirects(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient

        # Use a fresh client with no cookies to test unauthenticated access.
        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/", follow_redirects=False)
            assert resp.status_code == 302
            assert "/login" in resp.headers["location"]

    def test_authenticated_dashboard(self, client: object) -> None:
        # Login first to get a session cookie
        login = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "testadmin", "password": "testpass123"},
            follow_redirects=False,
        )
        session_cookie = login.cookies["sipc_session"]
        resp = client.get("/", cookies={"sipc_session": session_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200
        assert b"Blue Assets" in resp.content


class TestAssetManagement:
    @pytest.fixture(autouse=True)
    def auth_cookie(self, client: object) -> str:
        login = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "testadmin", "password": "testpass123"},
            follow_redirects=False,
        )
        return login.cookies["sipc_session"]

    def test_add_blue_asset_returns_partial(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/assets/blue",
            data={"name": "Alpha", "tle": "line1\nline2"},
            cookies={"sipc_session": auth_cookie},
        )
        assert resp.status_code == 200
        assert b"B_SAT_Alpha" in resp.content

    def test_add_red_track_returns_partial(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/assets/red",
            data={"name": "Track01", "tle": "line1\nline2"},
            cookies={"sipc_session": auth_cookie},
        )
        assert resp.status_code == 200
        assert b"R_SAT_Track01" in resp.content


class TestScenarioTime:
    @pytest.fixture(autouse=True)
    def auth_cookie(self, client: object) -> str:
        login = client.post(  # type: ignore[attr-defined]
            "/login",
            data={"username": "testadmin", "password": "testpass123"},
            follow_redirects=False,
        )
        return login.cookies["sipc_session"]

    def test_set_scenario_time(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/scenario/time",
            data={"scenario_start": "2026-01-01T00:00", "scenario_stop": "2026-01-02T00:00"},
            cookies={"sipc_session": auth_cookie},
        )
        assert resp.status_code == 200
        assert b"Scenario" in resp.content

    def test_set_scenario_time_invalid(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/scenario/time",
            data={"scenario_start": "bad", "scenario_stop": "bad"},
            cookies={"sipc_session": auth_cookie},
        )
        assert resp.status_code == 200
        assert b"Invalid" in resp.content or b"error" in resp.content.lower()
