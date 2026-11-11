"""The UDL fetches other panels call: what each asks for and what each falls back to (SPC-011).

The sweep, the clustering pipeline and source discovery call these without a
page of their own, so a failure has to come back as a value the caller can
act on: an empty list, None, or the default source list left alone. Each is
stood against httpx's MockTransport (tests/unit/_udl_stub.py).
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

import httpx
import pytest

from spectre.web.planning_state import SessionState
from spectre.web.routes import udl
from tests.unit._udl_stub import UdlStub, fails_with, reply

_L1 = "1 25544U 98067A   26025.79842163  .00000000  00000-0  10000-2 0  9998"
_L1_NEWER = "1 25544U 98067A   26026.50000000  .00000000  00000-0  10000-2 0  9994"
_L2 = "2 25544  51.6400 359.1324 0003806 313.0884 153.0596 15.50000000 00009"


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> UdlStub:
    return UdlStub().install(monkeypatch)


class _FixedClock(datetime):
    """The module's ``datetime`` with ``now`` held at noon on 1 June 2026, UTC."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 6, 1, 12, 0, tzinfo=tz)


class TestTheHistoryWindow:
    async def test_each_complete_record_is_one_element_set(self, stub: UdlStub, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(udl, "datetime", _FixedClock)
        stub.answer = reply([{"line1": _L1, "line2": _L2}, {"TLE_LINE1": _L1_NEWER, "TLE_LINE2": _L2},
                             {"line1": _L1}])
        tles = await udl.fetch_tle_history_for_satno(25544, "op", "pw", window_hours=6, data_mode="TEST", source="JSC")
        assert tles == [f"{_L1}\n{_L2}", f"{_L1_NEWER}\n{_L2}"]
        assert stub.params() == {
            "satNo": "25544", "epoch": ">2026-06-01T06:00:00.000000Z", "dataMode": "TEST", "source": "JSC",
        }, "the window did not reach back the six hours asked for from the clock's now"

    async def test_a_single_record_answer_is_read_and_real_is_not_sent(self, stub: UdlStub) -> None:
        stub.answer = reply({"line1": _L1, "line2": _L2})
        assert await udl.fetch_tle_history_for_satno(25544, "op", "pw") == [f"{_L1}\n{_L2}"]
        assert "dataMode" not in stub.params()
        assert "source" not in stub.params()

    @pytest.mark.parametrize("answer", [reply(text="x", status=500), reply(text="not json")])
    async def test_a_refusal_or_unreadable_body_is_an_empty_window(self, stub: UdlStub, answer: Any) -> None:
        stub.answer = answer
        assert await udl.fetch_tle_history_for_satno(25544, "op", "pw") == []


class TestTheCurrentSet:
    async def test_the_newest_complete_record_wins_with_its_own_mode(self, stub: UdlStub) -> None:
        stub.answer = reply([
            {"line1": _L1, "line2": _L2, "dataMode": "real"},
            {"line1": _L1_NEWER, "line2": _L2, "dataMode": "exercise"},
            {"line1": "1 25544U 98067A   26030.00000000", "dataMode": "real"},
        ])
        result = await udl.fetch_tle_for_satno(25544, "op", "pw", data_mode="EXERCISE", source="18SDS")
        assert result == (f"{_L1_NEWER}\n{_L2}", "EXERCISE")
        assert stub.params() == {"satNo": "25544", "dataMode": "EXERCISE", "source": "18SDS"}

    async def test_a_record_with_no_mode_carries_the_mode_asked_for(self, stub: UdlStub) -> None:
        stub.answer = reply({"line1": _L1, "line2": _L2})
        assert await udl.fetch_tle_for_satno(25544, "op", "pw", data_mode="simulated") == (f"{_L1}\n{_L2}", "SIMULATED")

    @pytest.mark.parametrize("answer", [
        reply([{"line1": _L1}, "not a record"]),
        reply(text="x", status=401),
        fails_with(httpx.ConnectError("refused")),
    ])
    async def test_nothing_usable_is_none(self, stub: UdlStub, answer: Any) -> None:
        stub.answer = answer
        assert await udl.fetch_tle_for_satno(25544, "op", "pw") is None


class TestSourceDiscovery:
    async def test_the_sources_on_offer_are_listed_once_each_in_order(self, stub: UdlStub) -> None:
        stub.answer = reply([{"source": "JSC"}, {"source": " 18SDS "}, {"source": "JSC"}, {"source": "  "}, {}])
        state = SessionState()
        await udl._discover_tle_sources("op", "pw", state)
        assert state.udl_available_sources == ["18SDS", "JSC"]
        assert stub.params() == {"satNo": "25544"}

    async def test_a_failed_probe_leaves_the_list_alone(self, stub: UdlStub) -> None:
        stub.answer = reply(text="x", status=503)
        state = SessionState()
        state.udl_available_sources = ["JSC"]
        await udl._discover_tle_sources("op", "pw", state)
        assert state.udl_available_sources == ["JSC"], "a failed probe wiped the sources already on offer"


def _page(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", f"{udl._UDL_BASE}/notification"))


class TestNotsoSyncPages:
    def test_a_single_record_page_is_one_record(self) -> None:
        assert udl._notso_page_records(_page({"id": "N1"}), 0) == ([{"id": "N1"}], None)

    def test_an_empty_object_page_ends_paging_with_no_records(self) -> None:
        assert udl._notso_page_records(_page({}), 2) == ([], None)
