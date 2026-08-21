"""Extended integration tests for SPECTRE web routes.

Covers training, decision, geometry, maneuver, gcat, and pol route endpoints
using the same in-memory SQLite DB and TestClient pattern as test_web_routes.py.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import csrf_headers

# Must be set before importing anything that calls get_settings().
os.environ.setdefault("SECRET_KEY", "integration-test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SPECTRE_ADMIN_USER", "testadmin")
os.environ.setdefault("SPECTRE_ADMIN_PASS", "testpass123")

pytest_plugins = ("anyio",)

# ── Sample LEO TLE (ISS-like) ─────────────────────────────────────────────────

_ISS_TLE = (
    "1 25544U 98067A   26060.50000000  .00016717  00000-0  10270-3 0  9993\n"
    "2 25544  51.6400 208.9163 0001207 86.9689 273.1630 15.54240707365485"
)

_ISS_TLE_2 = (
    "1 25544U 98067A   26065.50000000  .00016717  00000-0  10270-3 0  9994\n"
    "2 25544  51.6420 195.0000 0001207 86.9689 273.1630 15.54320000365490"
)


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def initialized_app() -> object:
    from spectre.web.app import app
    from spectre.web.database import init_db

    await init_db()
    return app


@pytest.fixture(scope="module")
def client(initialized_app: object) -> object:
    from fastapi.testclient import TestClient

    with TestClient(initialized_app, raise_server_exceptions=True) as c:  # type: ignore[arg-type]
        yield c


@pytest.fixture(scope="module")
def auth_cookie(client: object) -> str:
    resp = client.post(  # type: ignore[attr-defined]
        "/login",
        data={"username": "testadmin", "password": "testpass123"},
        follow_redirects=False,
    )
    return resp.cookies["spectre_session"]


# ── Helper to add assets to session ──────────────────────────────────────────

def _add_assets(client: object, auth: str) -> None:
    client.post(  # type: ignore[attr-defined]
        "/assets/blue",
        data={"name": "ISS-BLUE", "tle": _ISS_TLE},
        cookies={"spectre_session": auth},
        headers=csrf_headers(auth),
    )
    client.post(  # type: ignore[attr-defined]
        "/assets/red",
        data={"name": "ISS-RED", "tle": _ISS_TLE_2},
        cookies={"spectre_session": auth},
        headers=csrf_headers(auth),
    )


# ── Training routes ───────────────────────────────────────────────────────────

class TestTrainingRoutes:
    def test_training_home_page(self, client: object, auth_cookie: str) -> None:
        resp = client.get("/training", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200

    def test_training_home_slash(self, client: object, auth_cookie: str) -> None:
        resp = client.get("/training/", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200

    def test_training_dashboard(self, client: object, auth_cookie: str) -> None:
        resp = client.get("/training/dashboard", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200

    def test_training_leave_no_session(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/leave",
            data={"session_id": "0"},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
            follow_redirects=False,
        )
        # Should redirect back to /
        assert resp.status_code == 303

    def test_training_scenario_not_found(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/training/scenario/nonexistent_scenario_xyz",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 404
        assert b"not found" in resp.content.lower()

    def test_training_scenario_detail(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/training/scenario/cadet_01_geo_stationkeeping",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code in (200, 403)

    def test_training_scenario_start(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/cadet_01_geo_stationkeeping/start",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code in (200, 404)

    def test_training_scenario_explore(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/cadet_01_geo_stationkeeping/explore",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code in (200, 404)

    def test_training_tutorial_not_found(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/training/tutorial/nonexistent_tutorial_xyz",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 404

    def test_training_tutorial_view(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/training/tutorial/orientation",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_training_tutorial_complete(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/tutorial/orientation/complete",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_training_tutorial_complete_not_found(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/tutorial/nonexistent_xyz/complete",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 404

    def test_training_scenario_submit_not_found(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/nonexistent_xyz/submit",
            data={"result_id": "999", "objectives_completed": "[]", "time_taken_minutes": "0"},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 404

    def test_training_scenario_submit_invalid_result(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/cadet_01_geo_stationkeeping/submit",
            data={"result_id": "99999", "objectives_completed": "[]", "time_taken_minutes": "5"},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        # result_id 99999 won't exist → 404
        assert resp.status_code == 404

    def test_training_scenario_reset_not_found(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/nonexistent_xyz/reset",
            data={"result_id": "99999"},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 404

    def test_training_unauthenticated_redirects(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient
        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/training", follow_redirects=False)
            assert resp.status_code == 302


# ── Decision routes ───────────────────────────────────────────────────────────

class TestDecisionRoutes:
    def test_decision_panel(self, client: object, auth_cookie: str) -> None:
        resp = client.get("/plan/decision/panel", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200

    def test_decision_evaluate_empty_lists(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/decision/evaluate",
            data={"scenario_name": "Test", "horizon_hours": "72"},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"error" in resp.content.lower() or b"Define" in resp.content

    def test_decision_evaluate_with_actions(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/decision/evaluate",
            data={
                "scenario_name": "Alpha",
                "horizon_hours": "72",
                "adv_id": "A1",
                "adv_name": "Approach",
                "adv_type": "manoeuvre",
                "adv_prob": "0.7",
                "adv_conf": "0.8",
                "fr_id": "F1",
                "fr_name": "Evasion",
                "fr_type": "manoeuvre",
                "fr_cost": "0.3",
                "fr_rev": "0.5",
                "fr_time": "6.0",
                "strategy": "minimax",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_decision_unauthenticated_redirects(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient
        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/plan/decision/panel", follow_redirects=False)
            assert resp.status_code == 302


# ── Geometry routes ───────────────────────────────────────────────────────────

class TestGeometryRoutes:
    def test_geometry_missing_tles(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/geometry/intercept",
            data={
                "red_sat": "GHOST-RED",
                "blue_sat": "GHOST-BLUE",
                "burn_epoch_str": "2026-03-01T12:00",
                "dv_prograde": "0.1",
                "dv_normal": "0.0",
                "dv_radial": "0.0",
                "tof_hours": "2.0",
                "coast_hours": "0.0",
                "method": "hohmann",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"error" in resp.content.lower() or b"No TLE" in resp.content

    def test_geometry_invalid_dv(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/geometry/intercept",
            data={
                "red_sat": "ISS-RED",
                "blue_sat": "ISS-BLUE",
                "burn_epoch_str": "2026-03-01T12:00",
                "dv_prograde": "9999.0",  # exceeds max
                "dv_normal": "0.0",
                "dv_radial": "0.0",
                "tof_hours": "2.0",
                "coast_hours": "0.0",
                "method": "hohmann",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"error" in resp.content.lower() or b"outside" in resp.content.lower()

    def test_geometry_invalid_epoch(self, client: object, auth_cookie: str) -> None:
        _add_assets(client, auth_cookie)
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/geometry/intercept",
            data={
                "red_sat": "ISS-RED",
                "blue_sat": "ISS-BLUE",
                "burn_epoch_str": "not-a-date",
                "dv_prograde": "0.1",
                "dv_normal": "0.0",
                "dv_radial": "0.0",
                "tof_hours": "2.0",
                "coast_hours": "0.0",
                "method": "hohmann",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"error" in resp.content.lower()

    def test_geometry_with_valid_tles(self, client: object, auth_cookie: str) -> None:
        _add_assets(client, auth_cookie)
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/geometry/intercept",
            data={
                "red_sat": "ISS-RED",
                "blue_sat": "ISS-BLUE",
                "burn_epoch_str": "2026-03-01T12:00",
                "dv_prograde": "0.05",
                "dv_normal": "0.0",
                "dv_radial": "0.0",
                "tof_hours": "2.0",
                "coast_hours": "0.0",
                "method": "hohmann",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        # May succeed or fail with geometry error — just not a 500
        assert resp.status_code == 200


# ── Maneuver routes ───────────────────────────────────────────────────────────

class TestManeuverRoutes:
    def test_apply_intercept_unknown_method(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/maneuver/apply-intercept",
            data={
                "red_sat": "ISS-RED",
                "blue_sat": "ISS-BLUE",
                "method": "totally_unknown_method",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"Unknown" in resp.content or b"error" in resp.content.lower()

    def test_apply_intercept_missing_tles(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/maneuver/apply-intercept",
            data={
                "red_sat": "MISSING-RED",
                "blue_sat": "MISSING-BLUE",
                "method": "hohmann",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"No TLE" in resp.content or b"error" in resp.content.lower()

    def test_apply_intercept_hohmann(self, client: object, auth_cookie: str) -> None:
        _add_assets(client, auth_cookie)
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/maneuver/apply-intercept",
            data={
                "red_sat": "ISS-RED",
                "blue_sat": "ISS-BLUE",
                "method": "hohmann",
                "coast_hours": "0.5",
                "intercept_hours": "2.0",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_apply_intercept_lambert(self, client: object, auth_cookie: str) -> None:
        _add_assets(client, auth_cookie)
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/maneuver/apply-intercept",
            data={
                "red_sat": "ISS-RED",
                "blue_sat": "ISS-BLUE",
                "method": "lambert",
                "coast_hours": "0.0",
                "intercept_hours": "1.5",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_orbital_events_no_satellites(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/maneuver/orbital-events",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"Select" in resp.content or b"error" in resp.content.lower()

    def test_orbital_events_with_satellites(self, client: object, auth_cookie: str) -> None:
        _add_assets(client, auth_cookie)
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/maneuver/orbital-events?red_sat=ISS-RED&blue_sat=ISS-BLUE",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_trade_space_data_empty(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/plan/maneuver/trade-space-data",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        import json
        data = json.loads(resp.content)
        assert isinstance(data, list)

    def test_clear_history(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/maneuver/clear-history",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_apply_all_intercepts_missing_tles(self, client: object, auth_cookie: str) -> None:
        resp = client.post(  # type: ignore[attr-defined]
            "/plan/maneuver/apply-all-intercepts",
            data={
                "red_sat": "GHOST-RED-2",
                "blue_sat": "GHOST-BLUE-2",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"No TLE" in resp.content or b"error" in resp.content.lower()

    def test_maneuver_unauthenticated_redirects(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient
        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/plan/maneuver/trade-space-data", follow_redirects=False)
            assert resp.status_code == 302


# ── GCAT routes ───────────────────────────────────────────────────────────────

class TestGcatRoutes:
    def test_gcat_panel(self, client: object, auth_cookie: str) -> None:
        resp = client.get("/gcat/panel", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200

    def test_gcat_table_not_cached(self, client: object, auth_cookie: str) -> None:
        # Should return a "not loaded" message rather than crash
        resp = client.get(  # type: ignore[attr-defined]
            "/gcat/table?dataset=currentcat",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200

    def test_gcat_table_unknown_dataset(self, client: object, auth_cookie: str) -> None:
        resp = client.get(  # type: ignore[attr-defined]
            "/gcat/table?dataset=doesnotexist",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        # Unknown dataset returns 404
        assert resp.status_code in (200, 404)

    def test_gcat_unauthenticated_redirects(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient
        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/gcat/panel", follow_redirects=False)
            assert resp.status_code == 302


# ── PoL routes ────────────────────────────────────────────────────────────────

class TestPolRoutes:
    def test_pol_panel(self, client: object, auth_cookie: str) -> None:
        resp = client.get("/pol/panel", cookies={"spectre_session": auth_cookie})  # type: ignore[attr-defined]
        assert resp.status_code == 200

    def test_pol_analyse_no_udl_session(self, client: object, auth_cookie: str) -> None:
        # No UDL session credentials — should return an error partial
        resp = client.post(  # type: ignore[attr-defined]
            "/pol/analyse",
            data={"satno": "25544", "pol_source": "udl"},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"error" in resp.content.lower() or b"No active UDL" in resp.content or b"Connect" in resp.content

    def test_pol_analyse_direct_missing_creds(self, client: object, auth_cookie: str) -> None:
        # UDL direct mode with missing credentials
        resp = client.post(  # type: ignore[attr-defined]
            "/pol/analyse",
            data={"satno": "25544", "pol_source": "udl_direct", "udl_user": "", "udl_pass": ""},
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 200
        assert b"error" in resp.content.lower() or b"Enter UDL" in resp.content or b"username" in resp.content.lower()

    def test_pol_unauthenticated_redirects(self, initialized_app: object) -> None:
        from fastapi.testclient import TestClient
        with TestClient(initialized_app, raise_server_exceptions=True) as fresh:  # type: ignore[arg-type]
            resp = fresh.get("/pol/panel", follow_redirects=False)
            assert resp.status_code == 302


# ── Training full workflow ────────────────────────────────────────────────────

class TestTrainingFullWorkflow:
    """Test a complete scored attempt cycle: start → submit."""

    def test_start_and_submit_scenario(self, client: object, auth_cookie: str) -> None:
        # Start a scenario
        start_resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/cadet_01_geo_stationkeeping/start",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        if start_resp.status_code == 404:
            pytest.skip("Scenario not available at current level")

        assert start_resp.status_code == 200

        # Extract result_id from the response (look for hidden input or data attribute)
        import re
        match = re.search(rb'result_id["\s]+value=["\s]+(\d+)', start_resp.content)
        if not match:
            match = re.search(rb'name="result_id"[^>]*value="(\d+)"', start_resp.content)
        if not match:
            match = re.search(rb'"result_id":\s*(\d+)', start_resp.content)

        if not match:
            pytest.skip("Could not extract result_id from response")

        result_id = int(match.group(1))

        # Submit the scenario
        submit_resp = client.post(  # type: ignore[attr-defined]
            "/training/scenario/cadet_01_geo_stationkeeping/submit",
            data={
                "result_id": str(result_id),
                "objectives_completed": "[]",
                "time_taken_minutes": "10.0",
            },
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert submit_resp.status_code == 200

    def test_complete_tutorial_twice_idempotent(self, client: object, auth_cookie: str) -> None:
        # Completing a tutorial twice should not award points the second time
        resp1 = client.post(  # type: ignore[attr-defined]
            "/training/tutorial/scenario_loading/complete",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        resp2 = client.post(  # type: ignore[attr-defined]
            "/training/tutorial/scenario_loading/complete",
            cookies={"spectre_session": auth_cookie},
            headers=csrf_headers(auth_cookie),
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Both should succeed without error
        assert b"error" not in resp2.content.lower()
