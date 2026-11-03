"""GET /udl/conjunction lists the close approaches UDL holds for one object (SPC-031).

UDL is stubbed throughout: this environment cannot reach it. Each test feeds
the route a realistic or a malformed reply and checks what the operator sees:
the other object, the time of closest approach in UTC, UDL's miss distance
with its unit, the probability of collision when given, and each record's
data mode. A failure shows a fixed sentence and keeps the detail in the log.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from spectre.web import rate_limit
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state

_MARKER = "MARKER-c0nj-internal-detail"
_LOGGER = "spectre.web.routes.udl"
_DETAIL = "the server log has the detail"
_SATNO = 25544

_AS_SAT1 = {
    "id": "c-1", "tca": "2026-11-02T10:15:30.000000Z", "missDistance": 812.4,
    "collisionProb": 1.2e-5, "dataMode": "REAL", "satNo1": _SATNO, "satNo2": 48274,
    "sat1": {"satNo": _SATNO, "objectName": "ISS (ZARYA)"},
    "sat2": {"satNo": 48274, "objectName": "CSS (TIANHE)"},
}
_AS_SAT2 = {
    "id": "c-2", "tca": "2026-11-03T04:00:00.000000Z", "missDistance": 1500.0,
    "dataMode": "REAL", "satNo1": 33591, "satNo2": _SATNO,
    "sat1": {"satNo": 33591, "objectName": "NOAA 19"},
    "sat2": {"satNo": _SATNO, "objectName": "ISS (ZARYA)"},
}
_NO_TCA = {"id": "c-3", "missDistance": 50.0, "satNo1": _SATNO, "satNo2": 99999}


def _ok(payload: Any) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    resp.text = "[]"
    return resp


def _not_json() -> MagicMock:
    resp = _ok(None)
    resp.json.side_effect = ValueError(f"Expecting value: {_MARKER}")
    resp.text = f"<html>proxy error {_MARKER}</html>"
    return resp


def _failing(status: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = f"java.lang.IllegalStateException: {_MARKER}"
    resp = MagicMock()
    resp.status_code = status
    resp.text = response.text
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"Client error {_MARKER}", request=MagicMock(), response=response,
    )
    return resp


def _by_side(sat1: Any, sat2: Any) -> AsyncMock:
    """A stubbed ``client.get`` answering the satNo1 query with *sat1*, satNo2 with *sat2*."""
    async def _get(url: str, **kwargs: Any) -> Any:
        return sat1 if "satNo1" in kwargs["params"] else sat2
    return AsyncMock(side_effect=_get)


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch, auth_cookie: str) -> Iterator[tuple[Any, Any]]:
    """A stubbed UDL client, a connected session in REAL, and that session's state."""
    from spectre.web.routes import udl as udl_routes

    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(100, 60))
    state = session_state(auth_cookie)
    saved = (state.udl_username, state.udl_password, state.udl_data_mode)
    state.udl_username, state.udl_password, state.udl_data_mode = "u", "p", "REAL"
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(udl_routes.httpx, "AsyncClient", lambda **_k: client)
    yield client, state
    state.udl_username, state.udl_password, state.udl_data_mode = saved


def _get(client: Any, cookie: str, **params: Any) -> str:
    resp = client.get("/udl/conjunction", params=params, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return " ".join(resp.text.split())


def _assert_kept_out(page: str, sentence: str, caplog: pytest.LogCaptureFixture) -> None:
    assert _MARKER not in page, "exception or response text reached the browser"
    assert sentence in page
    assert _DETAIL in page
    assert any(_MARKER in r.getMessage() for r in caplog.records if r.name == _LOGGER), "the detail never reached the log"


class TestTheRequest:
    def test_both_sides_are_asked_of_udl_conjunction(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([]), _ok([]))
        _get(client, auth_cookie, satno=_SATNO)
        calls = udl_client.get.call_args_list
        assert [c.args[0].rsplit("/", 1)[-1] for c in calls] == ["conjunction", "conjunction"]
        sides = [{k: v for k, v in c.kwargs["params"].items() if k.startswith("satNo")} for c in calls]
        assert sides == [{"satNo1": _SATNO}, {"satNo2": _SATNO}]
        assert all(c.kwargs["auth"] == ("u", "p") for c in calls)

    def test_the_session_mode_is_sent_when_none_is_named(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        state.udl_data_mode = "EXERCISE"
        udl_client.get = _by_side(_ok([]), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert {c.kwargs["params"]["dataMode"] for c in udl_client.get.call_args_list} == {"EXERCISE"}
        assert "this lookup only" not in page

    def test_a_named_mode_applies_to_this_lookup_only(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        udl_client.get = _by_side(_ok([]), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO, data_mode="test")
        assert {c.kwargs["params"]["dataMode"] for c in udl_client.get.call_args_list} == {"TEST"}
        assert state.udl_data_mode == "REAL"
        assert "this lookup only; session mode unchanged" in page

    def test_an_unknown_mode_is_refused_and_udl_never_asked(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        udl_client.get = AsyncMock()
        page = _get(client, auth_cookie, satno=_SATNO, data_mode="LIVE")
        assert "Data mode must be REAL, SIMULATED, EXERCISE or TEST" in page
        udl_client.get.assert_not_called()
        assert state.udl_data_mode == "REAL"

    @pytest.mark.parametrize(("username", "password"), [(None, None), ("u", None), (None, "p")])
    def test_no_udl_session_asks_for_a_login(
        self, client: Any, auth_cookie: str, udl: Any, username: str | None, password: str | None,
    ) -> None:
        udl_client, state = udl
        state.udl_username, state.udl_password = username, password
        udl_client.get = AsyncMock()
        page = _get(client, auth_cookie, satno=_SATNO)
        assert "Not connected to UDL" in page
        udl_client.get.assert_not_called()

    @pytest.mark.parametrize("satno", ["", "abc", "0", "-5", "1e3", "12345678901", "\u00b2", "\uff11\uff12"])
    def test_a_catalogue_number_that_is_not_one_is_refused(
        self, client: Any, auth_cookie: str, udl: Any, satno: str,
    ) -> None:
        udl_client, _state = udl
        udl_client.get = AsyncMock()
        page = _get(client, auth_cookie, satno=satno)
        assert "Enter a NORAD catalogue number" in page
        udl_client.get.assert_not_called()

    def test_the_udl_data_rate_limit_applies(
        self, client: Any, auth_cookie: str, udl: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([]), _ok([]))
        monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(1, 60))
        _get(client, auth_cookie, satno=_SATNO)
        resp = client.get("/udl/conjunction", params={"satno": _SATNO}, cookies={"spectre_session": auth_cookie})
        assert resp.status_code == 429
        assert udl_client.get.call_count == 2


class TestTheListing:
    def test_records_as_sat_1_and_sat_2_are_listed_newest_tca_first(
        self, client: Any, auth_cookie: str, udl: Any,
    ) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([_AS_SAT1, _NO_TCA]), _ok([_AS_SAT2]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert page.index("NOAA 19") < page.index("CSS (TIANHE)")
        assert "33591" in page
        assert "48274" in page
        assert "2026-11-03 04:00:00 UTC" in page
        assert "2026-11-02 10:15:30 UTC" in page
        assert "812.4 m" in page
        assert "1,500.0 m" in page
        assert "1.20e-05" in page
        assert "99999" not in page, "a record with no TCA was listed"
        assert "1 record without a usable time of closest approach was left out" in page
        assert "Showing the newest" not in page

    def test_the_miss_distance_is_labelled_as_udls_figure(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([_AS_SAT1]), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert "Miss distance (UDL)" in page
        assert "UDL's figures as filed, not computed by SPECTRE" in page

    def test_each_record_shows_its_data_mode(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([_AS_SAT1]), _ok([{**_AS_SAT2, "dataMode": "SIMULATED"}]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert "badge-ok\">REAL" in page
        assert "badge-warn\">SIMULATED" in page

    def test_at_most_fifty_are_shown_and_the_page_says_so(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        many = [{**_AS_SAT1, "id": f"r{i}", "tca": f"2026-10-01T00:{i:02d}:00Z"} for i in range(60)]
        udl_client.get = _by_side(_ok(many), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert page.count("<tr class=\"conj-row\">") == 50
        assert "2026-10-01 00:59:00 UTC" in page
        assert "2026-10-01 00:09:00 UTC" not in page
        assert "newest 50 of 60" in page

    def test_a_record_naming_two_other_objects_is_left_out_and_said(
        self, client: Any, auth_cookie: str, udl: Any,
    ) -> None:
        udl_client, _state = udl
        unrelated = {"id": "c-9", "tca": "2026-11-04T00:00:00Z", "missDistance": 5.0,
                     "satNo1": 11, "satNo2": 22, "sat2": {"satNo": 22, "objectName": "UNRELATED"}}
        udl_client.get = _by_side(_ok([_AS_SAT1, unrelated]), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert "UNRELATED" not in page
        assert "CSS (TIANHE)" in page
        assert "1 record naming two other objects, neither SATNO 25544, was left out" in page

    def test_a_tca_past_the_calendar_limits_still_renders(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        edge = {**_AS_SAT1, "id": "edge", "tca": "9999-12-31T23:59:59-01:00"}
        udl_client.get = _by_side(_ok([_AS_SAT1, edge]), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert page.count("<tr class=\"conj-row\">") == 1
        assert "1 record without a usable time of closest approach was left out" in page

    def test_nothing_usable_is_said_plainly(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([_NO_TCA]), _ok({"unexpected": "shape"}))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert "UDL returned no usable conjunction records for SATNO 25544" in page
        assert "<table" not in page

    def test_no_records_at_all_is_said_plainly(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([]), _ok([]))
        page = _get(client, auth_cookie, satno=_SATNO)
        assert "UDL returned no usable conjunction records for SATNO 25544" in page

    def test_a_lookup_is_noted_in_the_run_log(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, state = udl
        udl_client.get = _by_side(_ok([_AS_SAT1]), _ok([_AS_SAT2]))
        _get(client, auth_cookie, satno=_SATNO)
        assert any("Conjunction lookup for SATNO 25544: 2 record(s)" in line for line in state.log_entries)


class TestUdlSourcedTextIsEscaped:
    """Names and modes in a UDL reply are untrusted (audit F-038)."""

    def test_markup_in_a_name_unit_or_mode_renders_as_text(self, client: Any, auth_cookie: str, udl: Any) -> None:
        udl_client, _state = udl
        hostile = {
            **_AS_SAT1,
            "satNo2": "<i>48274</i>",
            "sat2": {"satNo": 48274, "objectName": "<script>alert(1)</script>"},
            "missDistanceUnit": "<b>km</b>",
            "dataMode": "<img src=x onerror=alert(2)>",
        }
        udl_client.get = _by_side(_ok([hostile]), _ok([]))
        resp = client.get("/udl/conjunction", params={"satno": _SATNO}, cookies={"spectre_session": auth_cookie})
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text
        assert "<b>km</b>" not in resp.text
        assert "&lt;b&gt;km&lt;/b&gt;" in resp.text
        assert "<i>48274</i>" not in resp.text
        assert "&lt;i&gt;48274&lt;/i&gt;" in resp.text
        # The mode is upper-cased on the way through, so look for that spelling.
        assert "<IMG" not in resp.text
        assert "&lt;IMG SRC=X ONERROR=ALERT(2)&gt;" in resp.text


class TestAFailureStaysInTheLog:
    def test_a_body_that_is_not_json(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_not_json(), _ok([]))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, satno=_SATNO)
        _assert_kept_out(page, "UDL answered the conjunction lookup with a body SPECTRE could not read", caplog)

    def test_a_403(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl_client, _state = udl
        udl_client.get = _by_side(_failing(403), _ok([]))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, satno=_SATNO)
        _assert_kept_out(page, "UDL answered the conjunction lookup with HTTP 403", caplog)
        assert "Check your UDL access and the request" in page

    def test_a_503_on_the_second_side_fails_the_whole_lookup(
        self, client: Any, auth_cookie: str, udl: Any, caplog: Any,
    ) -> None:
        """Half a listing would read as "no close approaches as sat 2"."""
        udl_client, _state = udl
        udl_client.get = _by_side(_ok([_AS_SAT1]), _failing(503))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, satno=_SATNO)
        _assert_kept_out(page, "UDL answered the conjunction lookup with HTTP 503", caplog)
        assert "That is a fault on the UDL side" in page
        assert "CSS (TIANHE)" not in page

    def test_a_timeout(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl_client, _state = udl
        udl_client.get = AsyncMock(side_effect=httpx.ReadTimeout(f"timed out {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, satno=_SATNO)
        _assert_kept_out(page, "UDL did not answer the conjunction lookup in time", caplog)

    def test_an_unreachable_udl(self, client: Any, auth_cookie: str, udl: Any, caplog: Any) -> None:
        udl_client, _state = udl
        udl_client.get = AsyncMock(side_effect=httpx.ConnectError(f"connect failed {_MARKER}"))
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = _get(client, auth_cookie, satno=_SATNO)
        _assert_kept_out(page, "UDL unreachable during the conjunction lookup", caplog)


class TestTheConsole:
    def test_the_intel_panel_has_a_labelled_lookup(self, client: Any, auth_cookie: str, udl: Any) -> None:
        page = " ".join(client.get("/", cookies={"spectre_session": auth_cookie}).text.split())
        start = page.index('id="conjunction-controls"')
        controls = page[start:page.index('id="conjunction-results"', start)]
        assert '<label for="conjunction-satno"' in controls
        assert 'id="conjunction-satno" name="satno"' in controls
        assert 'hx-get="/udl/conjunction"' in controls
        assert '<select id="conjunction-tle-data-mode" name="data_mode"' in controls

    def test_the_input_and_the_button_both_send_the_per_lookup_mode(
        self, client: Any, auth_cookie: str, udl: Any,
    ) -> None:
        """Enter on the input and a click on the button must each carry the data mode select."""
        page = " ".join(client.get("/", cookies={"spectre_session": auth_cookie}).text.split())
        start = page.index('id="conjunction-controls"')
        controls = page[start:page.index('id="conjunction-results"', start)]
        input_tag = controls[controls.index('<input id="conjunction-satno"'):]
        input_tag = input_tag[:input_tag.index(">")]
        button_tag = controls[controls.index("<button"):]
        button_tag = button_tag[:button_tag.index(">")]
        for tag in (input_tag, button_tag):
            assert 'hx-get="/udl/conjunction"' in tag
            assert 'hx-include="#conjunction-controls [name]"' in tag

    def test_setting_the_session_mode_relabels_the_lookup_default(
        self, client: Any, auth_cookie: str, udl: Any,
    ) -> None:
        resp = client.post(
            "/udl/data-mode", data={"data_mode": "EXERCISE"},
            cookies={"spectre_session": auth_cookie}, headers=csrf_headers(auth_cookie),
        )
        assert (
            '<option id="conjunction-tle-data-mode-session" value="" hx-swap-oob="innerHTML">'
            "Session mode (EXERCISE)</option>"
        ) in resp.text
