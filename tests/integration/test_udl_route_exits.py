"""Every UDL route answers each way UDL can answer, in words the operator can act on (SPC-011).

The UDL routes were 85.5 per cent covered at 74d1105. The lines no test ran
were the refusals and fallbacks: a session that is not connected, a UDL that
times out, answers 4xx or 5xx, or answers with nothing usable. Every test
here stands UDL in with httpx's own MockTransport (tests/unit/_udl_stub.py),
so the request each route builds is the real one and nothing leaves the
process.

Writing them found one defect: a state vector fetch refused by UDL showed
"UDL returned 503 for SATNO ..." with no advice and logged no detail, the
one UDL call SPC-019's two fixed sentences had not reached.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any

import httpx
import pytest

from spectre.web import rate_limit
from spectre.web.auth import session_key_for
from spectre.web.routes import udl as udl_routes
from tests.conftest import csrf_headers
from tests.integration.conftest import session_state
from tests.unit._udl_stub import UdlStub, fails_with, reply

_LOGGER = "spectre.web.routes.udl"
_MARKER = "java.lang.IllegalStateException-SPC011-2207"
_NOT_CONNECTED = "Not connected to UDL — use the UDL panel to log in first."
_DETAIL = "the server log has the detail."
_UDL_FAULT = "That is a fault on the UDL side; try again later"
_ACCESS = "Check your UDL access and the request, then try again"
_SCENARIO_START = datetime(2026, 1, 26, 0, 0, tzinfo=UTC)
_L1 = "1 25544U 98067A   26025.79842163  .00000000  00000-0  10000-2 0  9998"
_L1_LATER = "1 25544U 98067A   26027.00000000  .00000000  00000-0  10000-2 0  9990"
_L2 = "2 25544  51.6400 359.1324 0003806 313.0884 153.0596 15.50000000 00009"


class _FixedClock(datetime):
    """The UDL module's ``datetime`` with ``now`` held at the scenario start, 26 January 2026, UTC."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return _SCENARIO_START.astimezone(tz)


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch) -> UdlStub:
    for name in ("_udl_auth_limiter", "_udl_data_limiter", "_udl_sync_limiter"):
        monkeypatch.setattr(rate_limit, name, rate_limit.SlidingWindowLimiter(100, 60))
    return UdlStub().install(monkeypatch)


@pytest.fixture
def state(auth_cookie: str) -> Iterator[Any]:
    """The signed-in session, connected to UDL in REAL with no scenario time."""
    held = session_state(auth_cookie)
    names = ("udl_username", "udl_password", "udl_data_mode", "udl_tle_source", "scenario_start", "elset_refresh",
             "udl_available_sources")
    saved = {name: getattr(held, name) for name in names}
    held.udl_username, held.udl_password, held.udl_data_mode = "op", "pw", "REAL"
    held.udl_tle_source, held.scenario_start = "", None
    yield held
    for name, value in saved.items():
        setattr(held, name, value)


def _page(resp: Any) -> str:
    assert resp.status_code == 200
    return html.unescape(" ".join(resp.text.split()))


@dataclass
class Operator:
    """The signed-in operator: the test client, their session cookie and their session state."""

    client: Any
    cookie: str
    state: Any

    def request(self, path: str, **params: Any) -> Any:
        return self.client.get(path, params=params, cookies={"spectre_session": self.cookie})

    def get(self, path: str, **params: Any) -> str:
        return _page(self.request(path, **params))

    def post(self, path: str, **data: Any) -> str:
        return _page(self.client.post(
            path, data=data, cookies={"spectre_session": self.cookie}, headers=csrf_headers(self.cookie),
        ))


@pytest.fixture
def op(client: Any, auth_cookie: str, state: Any) -> Operator:
    return Operator(client, auth_cookie, state)


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(r.getMessage() for r in caplog.records if r.name == _LOGGER)


class TestLogin:
    def test_rejected_credentials_say_so(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = reply({}, status=401)
        page = op.post("/udl/login", username="op", password="wrong")
        assert "Invalid UDL credentials (401)." in page

    def test_a_timeout_names_the_wait_and_the_network(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = fails_with(httpx.ReadTimeout("slow"))
        page = op.post("/udl/login", username="op", password="pw")
        assert "UDL connection timed out (10 s). Check network." in page

    def test_accepted_credentials_are_held_and_the_background_work_started(
        self, op: Operator, udl: UdlStub, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        started: list[str] = []

        def spawn(coro: Coroutine[Any, Any, None], _owner: Any) -> None:
            started.append(coro.__name__)
            coro.close()

        monkeypatch.setattr(udl_routes, "_spawn", spawn)
        op.state.udl_username = op.state.udl_password = None
        page = op.post("/udl/login", username="analyst", password="pw")
        assert "Connected as <strong>analyst</strong>" in page
        assert (op.state.udl_username, op.state.udl_password) == ("analyst", "pw")
        assert udl.credential() == "analyst:pw"
        assert op.state.log_entries[-1] == "[UDL] Connected as analyst"
        assert started == ["_fetch_onorbit_background", "_discover_tle_sources", "refresh_held_elsets"]


    def test_a_new_login_does_not_offer_the_last_accounts_providers(
        self, op: Operator, udl: UdlStub, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def spawn(coro: Coroutine[Any, Any, None], _owner: Any) -> None:
            coro.close()

        monkeypatch.setattr(udl_routes, "_spawn", spawn)
        op.state.udl_available_sources = ["EXO", "LeoLabs"]
        op.post("/udl/login", username="analyst", password="pw")
        assert op.state.udl_available_sources == [], "discovery adds to the list, so another account's stayed"

class TestSessionSettings:
    def test_a_source_is_set_and_a_blank_one_resets_to_the_default(self, op: Operator) -> None:
        assert "TLE Source: 18SDS" in op.post("/udl/tle-source", tle_source=" 18SDS ")
        assert op.state.log_entries[-1] == "[UDL] TLE source set to 18SDS"
        assert "TLE Source: UDL Default" in op.post("/udl/tle-source", tle_source=" ")
        assert op.state.log_entries[-1] == "[UDL] TLE source reset to UDL default"
        assert op.state.udl_tle_source == ""

    def test_logout_forgets_the_credential_and_stops_its_tasks(
        self, op: Operator, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cancelled: list[Any] = []
        monkeypatch.setattr(udl_routes, "_cancel_session_tasks", cancelled.append)
        op.state.elset_refresh = object()
        op.state.udl_available_sources = ["EXO", "LeoLabs"]
        op.post("/udl/logout")
        assert (op.state.udl_username, op.state.udl_password, op.state.elset_refresh) == (None, None, None)
        assert op.state.udl_available_sources == [], "the next login, perhaps on another account, offered these"
        assert cancelled == [session_key_for(op.cookie)], "the tasks holding this operator's password were not stopped"
        assert op.state.log_entries[-1] == "[UDL] Disconnected"


class TestTleFetch:
    def test_an_epoch_fetch_in_a_named_mode_asks_for_sets_before_the_scenario(self, op: Operator, udl: UdlStub) -> None:
        op.state.scenario_start = _SCENARIO_START
        udl.answer = reply([{"line1": _L1, "line2": _L2}, {"line1": _L1_LATER, "line2": _L2}])
        page = op.get("/udl/tle", satno=25544, mode="epoch", data_mode="EXERCISE")
        assert udl.paths[-1].endswith("/elset")
        assert udl.params() == {
            "satNo": "25544", "epoch": "<2026-01-26T00:00:00.000000Z", "maxResults": "100", "dataMode": "EXERCISE",
        }
        assert "26025.79842163" in page, "the set before the scenario start was not the one chosen"
        assert "26027.00000000" not in page

    def test_a_latest_fetch_asks_the_archive_over_72_hours_with_the_operators_source(
        self, op: Operator, udl: UdlStub, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Latest mode asked /elset/current, seen to answer for 18th SPCS alone with no source (charming-dirac 7ed9d0b).

        It now asks the archive over the last 72 hours first, narrowed to the operator's source when one is
        chosen; the epoch search still reaches back past any one provider.
        """
        monkeypatch.setattr(udl_routes, "datetime", _FixedClock)
        op.state.udl_tle_source, op.state.scenario_start = "18SDS", _SCENARIO_START
        udl.answer = reply([{"line1": _L1, "line2": _L2}])
        op.get("/udl/tle", satno=25544)
        op.get("/udl/tle", satno=25544, mode="epoch")
        assert udl.paths == ["/udl/elset", "/udl/elset"], "the current catalogue was asked although the archive held a set"
        assert udl.params(0) == {"satNo": "25544", "epoch": ">2026-01-23T00:00:00.000000Z", "source": "18SDS"}
        assert "source" not in udl.params(1)

    def test_a_latest_fetch_takes_the_newest_set_from_every_provider_and_carries_its_provider(
        self, op: Operator, udl: UdlStub,
    ) -> None:
        udl.answer = reply([{"line1": _L1, "line2": _L2, "source": "18th SPCS"},
                            {"line1": _L1_LATER, "line2": _L2, "source": "LeoLabs"}])
        page = op.get("/udl/tle", satno=25544)
        assert "26027.00000000" in page, "the newest set across providers was not the one chosen"
        assert '<input type="hidden" name="elset_source" value="LeoLabs" />' in page

    def test_a_latest_fetch_falls_back_to_the_current_catalogue_when_the_archive_is_empty(
        self, op: Operator, udl: UdlStub,
    ) -> None:
        current = {"line1": _L1, "line2": _L2, "source": "18th SPCS"}
        udl.answer = lambda request: httpx.Response(
            200, json=current if request.url.path.endswith("/elset/current") else [])
        page = op.get("/udl/tle", satno=25544)
        assert udl.paths == ["/udl/elset", "/udl/elset/current"]
        assert "epoch" not in udl.params(1), "the current catalogue takes no epoch"
        assert "26025.79842163" in page

    def test_an_elset_with_no_second_line_is_refused_not_shown(self, op: Operator, udl: UdlStub) -> None:
        """Audit F-140: it rendered as success with a TLE of a bare newline."""
        udl.answer = reply({"line1": _L1, "objectName": "ISS"})
        op.state.append_log("before the fetch")
        page = op.get("/udl/tle", satno=25544)
        assert "UDL returned an elset for SATNO 25544 with no element lines." in page
        assert _L1 not in page
        assert op.state.log_entries[-1] == "before the fetch", "a refused elset was logged as fetched"

    def test_an_epoch_fetch_without_scenario_time_is_refused_unasked(self, op: Operator, udl: UdlStub) -> None:
        page = op.get("/udl/tle", satno=25544, mode="epoch")
        assert "No scenario time set. Configure scenario time in the Scenario Configuration panel first." in page
        assert udl.requests == []

    def test_an_epoch_fetch_with_nothing_before_the_scenario_says_so(self, op: Operator, udl: UdlStub) -> None:
        op.state.scenario_start = datetime(2026, 1, 1, tzinfo=UTC)
        udl.answer = reply([{"line1": _L1, "line2": _L2}])
        page = op.get("/udl/tle", satno=25544, mode="epoch")
        assert "No elset found for SATNO 25544 with epoch ≤ 2026-01-01 00:00 UTC." in page

    def test_an_empty_answer_says_no_elset(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = reply([])
        assert "No elset found for SATNO 25544." in op.get("/udl/tle", satno=25544)

    def test_a_timeout_says_so(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = fails_with(httpx.ConnectTimeout("slow"))
        assert "UDL request timed out." in op.get("/udl/tle", satno=25544)

    @pytest.mark.parametrize(("status", "advice"), [(403, _ACCESS), (502, _UDL_FAULT)])
    def test_an_error_status_gives_the_advice_that_fits_it(
        self, op: Operator, udl: UdlStub, caplog: Any, status: int, advice: str,
    ) -> None:
        udl.answer = reply(text=_MARKER, status=status)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = op.get("/udl/tle", satno=25544)
        assert f"UDL answered the TLE fetch with HTTP {status}. {advice}; {_DETAIL}" in page
        assert _MARKER not in page
        assert _MARKER in _logged(caplog)

    def test_without_a_session_nothing_is_asked(self, op: Operator, udl: UdlStub) -> None:
        op.state.udl_password = None
        assert _NOT_CONNECTED in op.get("/udl/tle", satno=25544)
        assert udl.requests == []


_VECTOR = {"objectName": "ISS", "epoch": "2026-10-30T12:00:00.000000Z", "referenceFrame": "J2000",
           "xpos": 1.0, "ypos": 2.0, "zpos": 3.0, "xvel": 0.1, "yvel": 0.2, "zvel": 0.3}


class TestStateVectorFetch:
    def _fetch(self, op: Operator) -> str:
        return op.get("/udl/statevector", satno=25544)

    def test_without_a_session_nothing_is_asked(self, op: Operator, udl: UdlStub) -> None:
        op.state.udl_username = None
        assert _NOT_CONNECTED in self._fetch(op)
        assert udl.requests == []

    def test_the_newest_vector_in_the_week_is_the_one_shown(self, op: Operator, udl: UdlStub) -> None:
        older = {**_VECTOR, "epoch": "2026-10-29T12:00:00.000000Z", "objectName": "OLDER"}
        udl.answer = reply([older, _VECTOR, {"epoch": None}])
        page = self._fetch(op)
        assert "State vector loaded: <strong>ISS</strong> — epoch 2026-10-30T12:00:00.000000Z (J2000)" in page
        assert udl.params()["maxResults"] == "100"
        assert udl.params()["dataMode"] == "REAL"
        assert op.state.log_entries[-1] == "[UDL] Fetched state vector for SATNO 25544 (ISS) epoch 2026-10-30T12:00:00.000000Z"

    def test_no_dated_vector_names_the_window(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = reply({"objectName": "ISS"})
        assert "No state vector found for SATNO 25544 in the last 7 days." in self._fetch(op)

    def test_a_vector_with_no_frame_is_refused(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = reply({**_VECTOR, "referenceFrame": ""})
        page = self._fetch(op)
        assert "UDL state vector for SATNO 25544 has no referenceFrame; refused." in page
        assert "State vector loaded" not in page

    def test_a_timeout_says_so(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = fails_with(httpx.ReadTimeout("slow"))
        assert "UDL request timed out." in self._fetch(op)

    @pytest.mark.parametrize(("status", "advice"), [(404, _ACCESS), (503, _UDL_FAULT)])
    def test_an_error_status_gives_the_advice_that_fits_it(
        self, op: Operator, udl: UdlStub, caplog: Any, status: int, advice: str,
    ) -> None:
        """SPC-019's sentence: the call, the status, what to try; the body to the log only."""
        udl.answer = reply(text=_MARKER, status=status)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            page = self._fetch(op)
        assert f"UDL answered the state vector fetch with HTTP {status}. {advice}; {_DETAIL}" in page
        assert _MARKER not in page
        assert _MARKER in _logged(caplog), "the body UDL refused with never reached the log"


def _hrr(created_at: str, *sats: dict[str, Any]) -> dict[str, Any]:
    return {"createdAt": created_at, "msgBody": list(sats)}


class TestHrrFetch:
    def test_without_a_session_nothing_is_asked(self, op: Operator, udl: UdlStub) -> None:
        op.state.udl_username = None
        assert _NOT_CONNECTED in op.get("/udl/hrr")
        assert udl.requests == []

    def test_the_lookback_widens_until_a_list_is_found_and_the_newest_is_read(self, op: Operator, udl: UdlStub) -> None:
        op.state.udl_data_mode = "EXERCISE"
        older = _hrr("2026-10-01T00:00:00Z", {"satNo": "1", "commonName": "OLD", "country": "RUS"})
        newest = _hrr("2026-10-02T00:00:00",
                      {"satNo": "40258", "commonName": "LUCH", "country": "rus"},
                      {"satNo": "25544", "commonName": "ISS", "country": "USA"})
        udl.answer = lambda request: httpx.Response(
            200, json=[] if request.url.params["createdAt"] == ">now-1 days" else [older, newest])
        op.get("/udl/hrr")
        assert [r.url.params["createdAt"] for r in udl.requests] == [">now-1 days", ">now-2 days"]
        assert [r.url.params["dataMode"] for r in udl.requests] == ["EXERCISE"] * 2, "the session mode was not asked for"
        assert [o["name"] for o in op.state.hrr_objects] == ["ISS", "LUCH"]
        assert op.state.log_entries[-1] == "[HRR] lookback=2d — 1 Blue, 1 Red (2 sats)"

    def test_three_empty_days_say_how_far_back_was_searched(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = reply([])
        assert "No HRR notifications found in the last 3 days." in op.get("/udl/hrr")
        assert len(udl.requests) == 3

    def test_a_timeout_says_so(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = fails_with(httpx.PoolTimeout("slow"))
        assert "UDL request timed out." in op.get("/udl/hrr")


class TestCreatedAt:
    @pytest.mark.parametrize(("raw", "expected"), [
        ("2026-10-02T00:00:00", datetime(2026, 10, 2, tzinfo=UTC)),
        ("2026-10-02T01:00:00+01:00", datetime(2026, 10, 2, tzinfo=UTC)),
        ("not a date", datetime.min.replace(tzinfo=UTC)),
    ])
    def test_every_created_at_reads_as_utc(self, raw: str, expected: datetime) -> None:
        assert udl_routes._parse_created_at({"createdAt": raw}) == expected


class TestCatalogueSearch:
    def test_a_search_stops_at_fifty_and_says_so(self, op: Operator, monkeypatch: pytest.MonkeyPatch) -> None:
        catalogue = [{"satNo": 1, "name": "ELSEWHERE"}] + [{"satNo": n, "name": f"SAT {n}"} for n in range(100, 160)]
        monkeypatch.setattr(udl_routes, "get_onorbit_catalog", lambda: catalogue)
        monkeypatch.setattr(udl_routes, "get_catalog_status", lambda: "ready")
        page = op.get("/udl/catalog/search", q="sat")
        assert "ELSEWHERE" not in page
        assert "SAT 149" in page
        assert "SAT 150" not in page, "more than fifty matches were listed"
        assert "Showing first 50 matches" in page

    def test_a_search_without_a_udl_session_is_refused(self, op: Operator) -> None:
        op.state.udl_username = None
        page = op.get("/udl/catalog/search", q="sat")
        assert page == '<p class="error-msg">Log in to UDL to search the on-orbit catalogue.</p>'


class TestNotsoLookup:
    def _lookup(self, op: Operator) -> Any:
        return op.request("/udl/notso", satno=25544)

    def test_without_a_session_it_answers_401(self, op: Operator, udl: UdlStub) -> None:
        op.state.udl_username = None
        resp = self._lookup(op)
        assert (resp.status_code, resp.json()) == (401, {"error": "No active UDL session"})

    @pytest.mark.parametrize("answer", [reply({}, status=404), reply({}, status=501), reply(text="<html>")])
    def test_an_absent_endpoint_or_unreadable_body_is_an_empty_list(
        self, op: Operator, udl: UdlStub, answer: Any,
    ) -> None:
        udl.answer = answer
        resp = self._lookup(op)
        assert (resp.status_code, resp.json()) == (200, [])

    def test_records_are_read_under_either_field_name(self, op: Operator, udl: UdlStub) -> None:
        udl.answer = reply({"id": "N1", "date": "2026-10-01", "startTime": "s", "effectiveEnd": "e",
                            "type": "MANEUVER", "remarks": "r", "rawMessage": "raw"})
        assert self._lookup(op).json() == [{
            "message_id": "N1", "issue_date": "2026-10-01", "start": "s", "end": "e",
            "type": "MANEUVER", "description": "r", "raw": "raw",
        }]

    @pytest.mark.parametrize("case", [
        (reply(text=_MARKER, status=500), "UDL refused the NOTSO request; the server log has the detail.",
         "UDL NOTSO fetch error for 25544: Server error '500 Internal Server Error'"),
        (fails_with(httpx.ConnectError(_MARKER)), "UDL NOTSO fetch failed; the server log has the detail.",
         f"UDL NOTSO fetch failed for 25544: {_MARKER}"),
        (reply(["not an object"]), "UDL NOTSO fetch failed; the server log has the detail.",
         "UDL NOTSO fetch failed for 25544: 'str' object has no attribute"),
    ])
    def test_a_failure_answers_502_with_a_fixed_sentence_and_logs_the_detail(
        self, op: Operator, udl: UdlStub, caplog: pytest.LogCaptureFixture, case: tuple[Any, str, str],
    ) -> None:
        """Each case: what UDL does, the sentence the operator gets, and what the log must hold."""
        answer, sentence, detail = case
        udl.answer = answer
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            resp = self._lookup(op)
        assert (resp.status_code, resp.json()) == (502, {"error": sentence})
        assert _MARKER not in resp.text
        assert detail in _logged(caplog), "the sentence promises detail the log does not hold"


def test_the_udl_data_limit_refuses_before_udl_is_asked(
    op: Operator, udl: UdlStub, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit, "_udl_data_limiter", rate_limit.SlidingWindowLimiter(2, 60))
    udl.answer = reply(_VECTOR)
    codes = [op.request("/udl/statevector", satno=25544).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert len(udl.requests) == 2
