"""Failure paths that had never run under a test until 0.6.6 touched them.

0.6.6 moved noqa rationales and hoisted literals on these lines, which puts
them in the Code Quality gate's new-code window, coverage included: measured
against 0.6.5, the changed lines were 68% covered against a floor of 80. Each
is a path an operator does reach: an admin acting on a user deleted in another
tab, a UDL outage mid-fetch, a mistyped refuelling date, a sweep group with no
objects in it.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_MISSING_USER = 987654


def _udl_client(**get: Any) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(**get)
    return client


def _status_error(code: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://udl.invalid/x")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(code, text=body, request=request))


@pytest.fixture
def state(auth_cookie: str) -> Iterator[Any]:
    held = session_state(auth_cookie)
    saved = (
        held.udl_username, held.udl_password, list(held.hrr_objects),
        getattr(held, "last_pol_analysis", None),
    )
    yield held
    held.udl_username, held.udl_password, held.hrr_objects, held.last_pol_analysis = saved


class TestAdminActsOnAUserWhoIsGone:
    @pytest.mark.parametrize("path", [f"/admin/users/{_MISSING_USER}/edit", f"/admin/users/{_MISSING_USER}/cancel"])
    def test_the_row_says_so(self, client: Any, auth_cookie: str, path: str) -> None:
        resp = client.get(path, cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 404
        assert "User not found." in resp.text

    def test_saving_a_role_says_so(self, client: Any, auth_cookie: str) -> None:
        resp = client.post(
            f"/admin/users/{_MISSING_USER}", data={"role": "operator"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        assert resp.status_code == 404
        assert "User not found." in resp.text


class TestTheDatabaseProbe:
    @pytest.mark.asyncio
    async def test_a_driver_failure_is_not_ready_and_named(self) -> None:
        from spectre.web.health import check_database

        with patch("spectre.web.database.AsyncSessionLocal", side_effect=RuntimeError("socket closed")):
            healthy, detail = await check_database()
        assert not healthy
        assert detail == "database probe failed: RuntimeError"


class TestPatternOfLife:
    def _analyse(self, client: Any, cookie: str, **form: str) -> str:
        with patch("spectre.web.routes.pol._fetch_merged_history", side_effect=RuntimeError("UDL went away")):
            resp = client.post(
                "/pol/analyse", data={"satno": "25544", **form},
                cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
            )
        assert resp.status_code == 200
        return resp.text

    def test_a_failed_fetch_with_typed_credentials_is_reported(
        self, client: Any, auth_cookie: str, state: Any,
    ) -> None:
        text = self._analyse(client, auth_cookie, pol_source="udl_direct", udl_user="u", udl_pass="p")
        assert "UDL fetch failed: UDL went away" in text

    def test_a_failed_fetch_on_the_session_is_reported(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.udl_username, state.udl_password = "u", "p"
        text = self._analyse(client, auth_cookie, pol_source="udl")
        assert "UDL fetch failed: UDL went away" in text

    def test_an_unreadable_refuelling_date_is_refused(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.last_pol_analysis = SimpleNamespace(satno=25544)
        resp = client.post(
            "/pol/reserve-reset", data={"satno": "25544", "reset_date": "next tuesday"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        assert 'Could not read "next tuesday" as a date' in resp.text


class TestSweepGroupPrefetch:
    def _fetch(self, client: Any, cookie: str, group: str) -> str:
        resp = client.post(
            "/plan/threat/fetch-targets", data={"tgt_group": group},
            cookies={"spectre_session": cookie}, headers=csrf_headers(cookie),
        )
        assert resp.status_code == 200
        return resp.text

    def test_a_malformed_rank(self, client: Any, auth_cookie: str, state: Any) -> None:
        assert "Invalid rank: abc" in self._fetch(client, auth_cookie, "red:abc")

    def test_an_empty_group(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.hrr_objects = []
        assert "No HRR objects found for selected group." in self._fetch(client, auth_cookie, "red:1")

    def test_no_udl_session(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.hrr_objects = [{"satno": "43874", "rank": 1, "country": "CHN"}]
        state.udl_username = state.udl_password = None
        assert "Not connected to UDL" in self._fetch(client, auth_cookie, "red:1")

    def test_a_group_is_fetched_and_counted(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.hrr_objects = [{"satno": "43874", "rank": 1, "country": "CHN"}]
        state.udl_username, state.udl_password = "u", "p"
        with patch("spectre.web.routes.threat._prefetch_group_tle", AsyncMock(return_value=True)):
            text = " ".join(self._fetch(client, auth_cookie, "red:1").split())
        assert "1/1 TLEs ready" in text and "error-msg" not in text


class TestUdlFailures:
    @pytest.mark.asyncio
    async def test_the_history_fetch_reads_every_record(self) -> None:
        from spectre.web.routes.udl import fetch_tle_history_for_satno

        resp = MagicMock(raise_for_status=MagicMock())
        resp.json.return_value = {"line1": "1 A", "line2": "2 B"}
        with patch("httpx.AsyncClient", return_value=_udl_client(return_value=resp)):
            assert await fetch_tle_history_for_satno(25544, "u", "p") == ["1 A\n2 B"]

    @pytest.mark.asyncio
    async def test_a_catalogue_failure_reaches_the_status_flag(self) -> None:
        from spectre.web.planning_state import get_catalog_status, set_catalog_status
        from spectre.web.routes import udl

        set_catalog_status("idle")
        with patch("httpx.AsyncClient", return_value=_udl_client(side_effect=RuntimeError("down"))):
            await udl._fetch_onorbit_background("u", "p")
        assert get_catalog_status() == "error"

    @pytest.mark.asyncio
    async def test_source_discovery_failing_keeps_the_list(self) -> None:
        from spectre.web.planning_state import SessionState
        from spectre.web.routes.udl import _discover_tle_sources

        held = SessionState()
        held.udl_available_sources = ["18th SPCS"]
        with patch("httpx.AsyncClient", return_value=_udl_client(side_effect=RuntimeError("down"))):
            await _discover_tle_sources("u", "p", held)
        assert held.udl_available_sources == ["18th SPCS"]

    def test_a_login_probe_error_with_no_body(self, client: Any, auth_cookie: str, state: Any) -> None:
        refused = MagicMock(status_code=503, is_success=False, text="")
        with patch("httpx.AsyncClient", return_value=_udl_client(return_value=refused)):
            resp = client.post(
                "/udl/login", data={"username": "u", "password": "p"},
                cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
            )
        assert "UDL probe returned HTTP 503: (empty)" in resp.text

    def test_a_tle_fetch_error_with_no_body(self, client: Any, auth_cookie: str, state: Any) -> None:
        state.udl_username, state.udl_password = "u", "p"
        with patch("httpx.AsyncClient", return_value=_udl_client(side_effect=_status_error(502))):
            resp = client.get("/udl/tle?satno=25544", cookies={"spectre_session": auth_cookie})
        assert "UDL returned 502 for SATNO 25544: (empty)" in resp.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("failure", "expected"), [
        (_status_error(500), "HRR fetch returned HTTP 500: (empty)"),
        (httpx.ReadTimeout("slow"), "UDL request timed out."),
    ])
    async def test_an_hrr_fetch_failure_is_named(self, failure: Exception, expected: str) -> None:
        from spectre.web.routes.udl import fetch_hrr_objects

        with patch("httpx.AsyncClient", return_value=_udl_client(side_effect=failure)):
            blue, red, _days, error = await fetch_hrr_objects("u", "p")
        assert (blue, red, error) == ([], [], expected)
