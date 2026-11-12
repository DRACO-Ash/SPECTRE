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

from spectre.web.elsets import RefusedElset
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


_ARCHIVE = "/udl/elset"
_CURRENT = "/udl/elset/current"
_XP_TYPE = 4


def _by_path(archive: Any, current: Any) -> Any:
    """An answer from the archive for ``/elset`` and from the current catalogue for ``/elset/current``."""
    def answer(request: httpx.Request) -> httpx.Response:
        return (current if request.url.path == _CURRENT else archive)(request)
    return answer


class TestTheNewestSet:
    """A latest fetch asks the archive over the last 72 hours, across every provider, first (charming-dirac 7ed9d0b).

    In service a GEO object came back three days old while commercial providers had filed sets that day:
    ``/elset/current`` asked with no source answered for 18th SPCS alone. The archive holds every provider's sets;
    the current catalogue is asked only when the archive holds no complete set in the window.
    """

    async def test_the_archive_is_asked_first_and_its_newest_set_comes_with_its_provider(
        self, stub: UdlStub, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(udl, "datetime", _FixedClock)
        stub.answer = reply([
            {"line1": _L1, "line2": _L2, "dataMode": "real", "source": "18th SPCS"},
            {"line1": _L1_NEWER, "line2": _L2, "dataMode": "exercise", "source": " LeoLabs "},
            {"line1": "1 25544U 98067A   26030.00000000", "dataMode": "real", "source": "KBR"},
        ])
        result = await udl.fetch_tle_for_satno(25544, "op", "pw", data_mode="EXERCISE", source="LeoLabs")
        assert stub.paths == [_ARCHIVE], "the current catalogue was asked although the archive held a set"
        assert result == udl.FetchedElset(f"{_L1_NEWER}\n{_L2}", "EXERCISE", "LeoLabs")
        assert stub.params() == {
            "satNo": "25544", "epoch": ">2026-05-29T12:00:00.000000Z", "dataMode": "EXERCISE", "source": "LeoLabs",
        }, "the archive was not asked over the 72 hours before the clock's now"
        assert stub.requests[0].extensions["timeout"]["read"] == udl._ARCHIVE_TIMEOUT_S

    @pytest.mark.parametrize("archive", [reply([]), reply([{"line1": _L1, "source": "EXO"}])],
                             ids=["empty", "no-complete-set"])
    async def test_the_current_catalogue_answers_when_the_archive_holds_no_complete_set(
        self, stub: UdlStub, archive: Any,
    ) -> None:
        stub.answer = _by_path(archive, reply({"line1": _L1, "line2": _L2, "source": "18th SPCS"}))
        result = await udl.fetch_tle_for_satno(25544, "op", "pw", source="18th SPCS")
        assert stub.paths == [_ARCHIVE, _CURRENT]
        assert result == udl.FetchedElset(f"{_L1}\n{_L2}", "REAL", "18th SPCS")
        assert stub.params() == {"satNo": "25544", "source": "18th SPCS"}, "the current catalogue takes no epoch"

    async def test_a_refused_newest_set_is_not_replaced_by_an_older_one_or_the_current_catalogue(
        self, stub: UdlStub,
    ) -> None:
        """HEAD's rule (SPC-201) holds over the wider archive: the newest set is what UDL holds now."""
        newest_xp = {"line1": _L1_NEWER, "line2": _L2, "ephemType": _XP_TYPE, "source": "EXO"}
        stub.answer = _by_path(reply([{"line1": _L1, "line2": _L2, "source": "18th SPCS"}, newest_xp]),
                               reply({"line1": _L1, "line2": _L2, "source": "18th SPCS"}))
        result = await udl.fetch_tle_for_satno(25544, "op", "pw")
        assert isinstance(result, RefusedElset)
        assert stub.paths == [_ARCHIVE]

    @pytest.mark.parametrize("xp_first", [True, False], ids=["xp-first", "sgp4-first"])
    async def test_on_a_tie_the_usable_set_is_taken_whatever_order_udl_answers_in(
        self, stub: UdlStub, xp_first: bool,
    ) -> None:
        """Two providers' fits at one epoch: neither is older, so the one the check accepts is taken, not whichever
        UDL listed first. The archive across every provider makes equal epochs common."""
        xp = {"line1": _L1, "line2": _L2, "ephemType": _XP_TYPE, "source": "EXO"}
        sgp4 = {"line1": _L1, "line2": _L2, "source": "18th SPCS"}
        stub.answer = reply([xp, sgp4] if xp_first else [sgp4, xp])
        assert await udl.fetch_tle_for_satno(25544, "op", "pw") == udl.FetchedElset(f"{_L1}\n{_L2}", "REAL", "18th SPCS")

    async def test_on_a_tie_where_every_set_is_refused_the_fetch_is_refused(self, stub: UdlStub) -> None:
        xp = {"line1": _L1, "line2": _L2, "ephemType": _XP_TYPE}
        stub.answer = reply([{**xp, "source": "KBR"}, {**xp, "source": "EXO"}])
        result = await udl.fetch_tle_for_satno(25544, "op", "pw")
        assert isinstance(result, RefusedElset)
        assert (result.satno, result.check.failures) == (25544, (
            "it is an SGP4-XP set (ephemeris type 4), which SGP4 would propagate to a wrong orbit without an error",
        ))

    async def test_a_record_with_no_mode_or_provider_carries_the_mode_asked_for(self, stub: UdlStub) -> None:
        stub.answer = reply({"line1": _L1, "line2": _L2})
        assert await udl.fetch_tle_for_satno(25544, "op", "pw", data_mode="simulated") == udl.FetchedElset(
            f"{_L1}\n{_L2}", "SIMULATED", "",
        )

    @pytest.mark.parametrize("answer", [
        reply([{"line1": _L1}, "not a record"]),
        reply(text="x", status=401),
        fails_with(httpx.ConnectError("refused")),
        _by_path(reply([]), reply(text="x", status=503)),
    ], ids=["incomplete", "archive-refused", "unreachable", "current-refused"])
    async def test_nothing_usable_is_none(self, stub: UdlStub, answer: Any) -> None:
        stub.answer = answer
        assert await udl.fetch_tle_for_satno(25544, "op", "pw") is None


class TestSourceDiscovery:
    async def test_the_providers_on_the_iss_archive_are_added_once_each_in_order(
        self, stub: UdlStub, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The list was built from ``/elset/current``, which answered for 18th SPCS alone, so it offered one."""
        monkeypatch.setattr(udl, "datetime", _FixedClock)
        stub.answer = reply([{"source": "JSC"}, {"source": " 18SDS "}, {"source": "JSC"}, {"source": "  "}, {}])
        state = SessionState()
        state.udl_available_sources = ["KRTL"]
        await udl._discover_tle_sources("op", "pw", state)
        assert state.udl_available_sources == ["18SDS", "JSC", "KRTL"], "the list was replaced, not added to"
        assert stub.paths == [_ARCHIVE]
        assert stub.params() == {"satNo": "25544", "epoch": ">2026-05-31T12:00:00.000000Z"}

    async def test_a_failed_probe_leaves_the_list_alone(self, stub: UdlStub) -> None:
        stub.answer = reply(text="x", status=503)
        state = SessionState()
        state.udl_available_sources = ["JSC"]
        await udl._discover_tle_sources("op", "pw", state)
        assert state.udl_available_sources == ["JSC"], "a failed probe wiped the sources already on offer"

    def test_remembered_providers_are_added_blank_ones_never(self) -> None:
        state = SessionState()
        state.udl_available_sources = ["LeoLabs"]
        udl.remember_sources(state, ["NorthStar", "", "LeoLabs"])
        assert state.udl_available_sources == ["LeoLabs", "NorthStar"]


def _page(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", f"{udl._UDL_BASE}/notification"))


class TestNotsoSyncPages:
    def test_a_single_record_page_is_one_record(self) -> None:
        assert udl._notso_page_records(_page({"id": "N1"}), 0) == ([{"id": "N1"}], None)

    def test_an_empty_object_page_ends_paging_with_no_records(self) -> None:
        assert udl._notso_page_records(_page({}), 2) == ([], None)
