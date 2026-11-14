"""A failed UDL call tells the operator what failed, never what the exception said.

SPC-019. The UDL routes put ``{exc}`` and the raw UDL response body into the
page on their error paths. An httpx exception carries the full request URL,
query string included, and a UDL error body can carry a server stack trace;
neither belongs in an operator's browser, and CodeQL reports the pattern as
stack-trace exposure. Each path now shows a fixed sentence naming the call
that failed and what to try, and the detail goes to the log through log_safe.

Every test stubs the failing call with an exception or a body carrying
``_MARKER`` and asserts the marker is absent from the page, present in the
log, and that the fixed sentence is shown instead.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from spectre.data import notso_cache
from spectre.web import rate_limit
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_MARKER = "MARKER-7f3a-internal-detail"
_LOGGER = "spectre.web.routes.udl"
_DETAIL = "the server log has the detail"


def _status_error(status: int) -> httpx.HTTPStatusError:
    """An HTTPStatusError whose message and response body both carry the marker."""
    response = MagicMock()
    response.status_code = status
    response.text = f"java.lang.IllegalStateException: {_MARKER}"
    return httpx.HTTPStatusError(f"Server error {_MARKER}", request=MagicMock(), response=response)


def _failing_response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.is_success = False
    resp.text = f"java.lang.IllegalStateException: {_MARKER}"
    resp.raise_for_status.side_effect = _status_error(status)
    return resp


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch, auth_cookie: str) -> Iterator[Any]:
    """A stubbed UDL client and a connected session; set ``client.get`` per test."""
    from spectre.web.routes import udl as udl_routes

    monkeypatch.setattr(rate_limit, "_udl_auth_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rate_limit, "_udl_sync_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_password, state.udl_data_mode)
    state.udl_username, state.udl_password, state.udl_data_mode = "u", "p", "REAL"
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(udl_routes.httpx, "AsyncClient", lambda **_k: client)
    yield client
    state.udl_username, state.udl_password, state.udl_data_mode = saved


def _get(client: Any, cookie: str, path: str, **params: Any) -> str:
    resp = client.get(path, params=params, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _post(client: Any, cookie: str, path: str, **data: Any) -> str:
    resp = client.post(path, data=data, cookies={"spectre_session": cookie}, headers=csrf_headers(cookie))
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _assert_kept_out(page: str, sentence: str, caplog: pytest.LogCaptureFixture) -> None:
    assert _MARKER not in page, "exception or response text reached the browser"
    assert sentence in page
    assert _DETAIL in page
    assert any(_MARKER in r.getMessage() for r in caplog.records if r.name == _LOGGER), "the detail never reached the log"


class TestLogin:
    def test_an_unreachable_udl(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(side_effect=httpx.ConnectError(f"connect failed {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _post(client, auth_cookie, "/udl/login", username="op", password="pw")
        _assert_kept_out(page, "UDL unreachable during the login check", caplog)

    def test_a_probe_that_fails_with_a_body(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(return_value=_failing_response(503))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _post(client, auth_cookie, "/udl/login", username="op", password="pw")
        _assert_kept_out(page, "UDL answered the login check with HTTP 503", caplog)


_ACCESS_ADVICE = "Check your UDL access and the request"
_UDL_FAULT_ADVICE = "That is a fault on the UDL side; try again later"


class TestTheAdviceFollowsTheStatus:
    """A 4xx points the operator at their access or request; a 5xx is UDL's own fault.

    Every status once read "Check your UDL access and the request", which told
    an operator with good credentials that a UDL outage was their doing.
    """

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 499])
    def test_a_client_error_points_at_access_and_request(self, status: int) -> None:
        from spectre.web.routes.udl import _udl_refused

        sentence = _udl_refused("TLE fetch", status)
        assert sentence.startswith(f"UDL answered the TLE fetch with HTTP {status}.")
        assert _ACCESS_ADVICE in sentence
        assert _UDL_FAULT_ADVICE not in sentence

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_a_server_error_is_named_as_udls(self, status: int) -> None:
        from spectre.web.routes.udl import _udl_refused

        sentence = _udl_refused("TLE fetch", status)
        assert sentence.startswith(f"UDL answered the TLE fetch with HTTP {status}.")
        assert _UDL_FAULT_ADVICE in sentence
        assert _ACCESS_ADVICE not in sentence
        assert sentence.endswith(_DETAIL + ".")

    def test_a_login_probe_refused_for_access_says_so(
        self, client: Any, auth_cookie: str, udl: Any, caplog: Any,
    ) -> None:
        # 403, not 401: a 401 has its own "Invalid UDL credentials" sentence.
        udl.get = AsyncMock(return_value=_failing_response(403))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _post(client, auth_cookie, "/udl/login", username="op", password="pw")
        _assert_kept_out(page, "UDL answered the login check with HTTP 403", caplog)
        assert _ACCESS_ADVICE in page

    def test_a_login_probe_answered_503_blames_udl_not_the_operator(
        self, client: Any, auth_cookie: str, udl: Any, caplog: Any,
    ) -> None:
        udl.get = AsyncMock(return_value=_failing_response(503))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _post(client, auth_cookie, "/udl/login", username="op", password="pw")
        assert _UDL_FAULT_ADVICE in page
        assert _ACCESS_ADVICE not in page


class TestTleFetch:
    def test_an_unreachable_udl(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(side_effect=httpx.ConnectError(f"connect failed {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, "/udl/tle", satno=25544)
        _assert_kept_out(page, "UDL unreachable during the TLE fetch", caplog)

    def test_an_error_status_with_a_body(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(return_value=_failing_response(500))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, "/udl/tle", satno=25544)
        _assert_kept_out(page, "UDL answered the TLE fetch with HTTP 500", caplog)


class TestStateVectorFetch:
    def test_an_unreachable_udl(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(side_effect=httpx.ConnectError(f"connect failed {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, "/udl/statevector", satno=25544)
        _assert_kept_out(page, "UDL unreachable during the state vector fetch", caplog)


class TestHrrFetch:
    def test_an_unreachable_udl(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(side_effect=httpx.ConnectError(f"connect failed {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, "/udl/hrr")
        _assert_kept_out(page, "UDL unreachable during the HRR fetch", caplog)

    def test_an_error_status_with_a_body(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(return_value=_failing_response(502))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, "/udl/hrr")
        _assert_kept_out(page, "UDL answered the HRR fetch with HTTP 502", caplog)


class TestNotsoSync:
    @pytest.fixture(autouse=True)
    def _cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        cache = notso_cache.NotsoCache(path=tmp_path / "c.json")
        monkeypatch.setattr(notso_cache, "get_notso_cache", lambda: cache)

    def test_an_error_status_on_a_page(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(return_value=_failing_response(500))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _post(client, auth_cookie, "/udl/notso/sync")
        # "HTTP error on page" is the prefix the sync route tests already pin.
        _assert_kept_out(page, "HTTP error on page 0: UDL answered the NOTSO sync with HTTP 500", caplog)

    def test_a_sync_that_fails_outright(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl.get = AsyncMock(side_effect=RuntimeError(f"disk full {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _post(client, auth_cookie, "/udl/notso/sync")
        _assert_kept_out(page, "The NOTSO sync stopped before it finished", caplog)


_FORGED = "2026-11-02 INFO spectre.web.auth Successful login: root"


class TestBackgroundFailuresLogOneLine:
    """The background UDL calls log their failure through log_safe too.

    They wrote the exception text raw, so an exception carrying a newline
    forged a second record in the log.
    """

    @pytest.fixture
    def failing_udl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spectre.web.routes import udl as udl_routes

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get = AsyncMock(side_effect=httpx.ConnectError(f"boom\n{_FORGED}"))
        monkeypatch.setattr(udl_routes.httpx, "AsyncClient", lambda **_k: client)

    @staticmethod
    def _assert_one_line(caplog: pytest.LogCaptureFixture) -> None:
        messages = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
        assert any(_FORGED in m for m in messages), "the failure was never logged"
        assert all("\n" not in m for m in messages), "exception text forged a log line"

    async def test_the_tle_history_fetch(self, failing_udl: None, caplog: Any) -> None:
        from spectre.web.routes.udl import fetch_tle_history_for_satno

        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert await fetch_tle_history_for_satno(25544, "u", "p") == []
        self._assert_one_line(caplog)

    async def test_the_onorbit_catalogue_fetch(
        self, failing_udl: None, monkeypatch: pytest.MonkeyPatch, caplog: Any,
    ) -> None:
        from spectre.web.routes import udl as udl_routes

        statuses: list[str] = []
        monkeypatch.setattr(udl_routes, "get_catalog_status", lambda: "idle")
        monkeypatch.setattr(udl_routes, "set_catalog_status", statuses.append)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            await udl_routes._fetch_onorbit_background("u", "p")
        assert statuses[-1] == "error"
        self._assert_one_line(caplog)

    async def test_the_tle_source_discovery(self, failing_udl: None, caplog: Any) -> None:
        from spectre.web.planning_state import SessionState
        from spectre.web.routes.udl import _discover_tle_sources

        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            await _discover_tle_sources("u", "p", SessionState())
        self._assert_one_line(caplog)
