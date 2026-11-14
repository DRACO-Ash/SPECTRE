"""The Pattern of Life history: what is asked of UDL, how the answer is read, and what is held (SPC-012).

Pattern of Life asks UDL twice per object, the archive and the current set,
and merges the two. These tests pin each half against a stand-in UDL: the
query each sends, the provenance read from the answer, which name and which
provenance win the merge, and the stated problem the sweep shows when the
held history cannot be had.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.pol_assessment import assess_pattern_of_life
from spectre.web.planning_state import SessionState
from spectre.web.routes import pol
from tests.unit._udl_stub import UdlStub, reply
from tests.unit.test_dv_estimation import TestTwoTierReporting

_L1 = "1 25544U 98067A   26025.79842163  .00000000  00000-0  10000-2 0  9999"
_L2 = "2 25544  51.6400 359.1324 0003806 313.0884 153.0596 15.50000000 00006"
_L1_NEXT = "1 25544U 98067A   26026.79842163  .00000000  00000-0  10000-2 0  9999"
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_MARKER = "internal-detail-SPC012-8830"


def _parse(stub_answer: httpx.Response) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    return pol._parse_udl_elset_response(stub_answer)


class TestReadingTheAnswer:
    def test_an_empty_body_is_no_history(self) -> None:
        assert _parse(httpx.Response(200, text="  ")) == ("", {}, {}, "")

    def test_plain_tle_text_passes_through_with_no_provenance(self) -> None:
        assert _parse(httpx.Response(200, text=f"{_L1}\n{_L2}\n")) == (f"{_L1}\n{_L2}", {}, {}, "")

    def test_json_that_is_neither_record_nor_list_is_no_history(self) -> None:
        assert _parse(httpx.Response(200, json=42)) == ("", {}, {}, "")

    def test_one_record_carries_its_provenance_and_fit(self) -> None:
        record = {"TLE_LINE1": _L1, "TLE_LINE2": _L2, "dataMode": "EXERCISE", "source": "18SDS",
                  "rmsResidual": 0.5, "OBJECT_NAME": "ISS (ZARYA)"}
        assert _parse(httpx.Response(200, json=record)) == (
            f"{_L1}\n{_L2}", {_L1: ("EXERCISE", "18SDS")}, {_L1: 0.5}, "ISS (ZARYA)",
        )

    def test_records_without_both_lines_are_skipped_and_the_first_name_wins(self) -> None:
        records = [
            {"line1": _L1, "objectName": "HALF"},
            {"tle1": _L1, "tle2": _L2, "data_mode": "real", "satName": "FIRST", "rms_residual": "0.25"},
            {"line1": _L1_NEXT, "line2": _L2, "name": "SECOND"},
        ]
        text, metadata, rms, name = _parse(httpx.Response(200, json=records))
        assert text == f"{_L1}\n{_L2}\n{_L1_NEXT}\n{_L2}"
        assert metadata == {_L1: ("real", ""), _L1_NEXT: ("", "")}
        assert rms == {_L1: 0.25, _L1_NEXT: None}
        assert name == "FIRST"


@pytest.fixture
def udl(monkeypatch: pytest.MonkeyPatch) -> UdlStub:
    return UdlStub().install(monkeypatch)


class TestWhatIsAskedOfUdl:
    async def test_the_archive_asks_for_everything_since_2015_as_real(self, udl: UdlStub) -> None:
        udl.answer = reply([{"line1": _L1, "line2": _L2}])
        text, *_ = await pol._fetch_udl_history(25544, "op", "pw", "REAL")
        assert text == f"{_L1}\n{_L2}"
        assert udl.paths[-1].endswith("/elset")
        assert udl.params() == {"satNo": "25544", "epoch": ">2015-01-01T00:00:00.000000Z", "maxResults": "5000"}
        assert udl.credential() == "op:pw"

    async def test_the_current_set_carries_a_named_mode_and_source(self, udl: UdlStub) -> None:
        await pol._fetch_udl_latest(25544, "op", "pw", "EXERCISE", source="18SDS")
        assert udl.paths[-1].endswith("/elset/current")
        assert udl.params() == {"satNo": "25544", "dataMode": "EXERCISE", "source": "18SDS"}

    async def test_an_archive_query_carries_a_named_mode_and_source(self, udl: UdlStub) -> None:
        await pol._fetch_udl_history(25544, "op", "pw", "TEST", source="JSC")
        assert udl.params()["dataMode"] == "TEST"
        assert udl.params()["source"] == "JSC"

    @pytest.mark.parametrize("status", [401, 503])
    async def test_an_error_status_is_raised_to_the_caller(self, udl: UdlStub, status: int) -> None:
        udl.answer = reply({"message": _MARKER}, status=status)
        with pytest.raises(httpx.HTTPStatusError):
            await pol._fetch_udl_latest(25544, "op", "pw", "REAL")


def _by_path(archive: Any, current: Any) -> Any:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=current if request.url.path.endswith("/current") else archive)
    return answer


class TestTheMerge:
    async def test_the_current_set_follows_the_archive_and_its_provenance_wins(self, udl: UdlStub) -> None:
        udl.answer = _by_path(
            [{"line1": _L1, "line2": _L2, "dataMode": "REAL", "source": "OLD", "objectName": "ARCHIVE"}],
            [{"line1": _L1, "line2": _L2, "dataMode": "REAL", "source": "NEW", "rms": 0.1}],
        )
        archive, merged, metadata, rms, name = await pol._fetch_merged_history(25544, "op", "pw", "")
        assert archive == f"{_L1}\n{_L2}"
        assert merged == f"{_L1}\n{_L2}\n{_L1}\n{_L2}"
        assert metadata == {_L1: ("REAL", "NEW")}
        assert rms == {_L1: 0.1}
        assert name == "ARCHIVE", "the archive's name was dropped when the current set had none"
        assert all("dataMode" not in udl.params(i) for i in range(2)), "a blank mode was not read as REAL"

    async def test_an_empty_archive_adds_no_blank_line(self, udl: UdlStub) -> None:
        udl.answer = _by_path([], [{"line1": _L1, "line2": _L2, "objectName": "CURRENT"}])
        _archive, merged, _m, _r, name = await pol._fetch_merged_history(25544, "op", "pw", "REAL")
        assert merged == f"{_L1}\n{_L2}"
        assert name == "CURRENT"

    async def test_when_both_halves_are_named_the_current_name_wins(self, udl: UdlStub) -> None:
        """An object renamed since launch is shown under the name UDL holds now."""
        udl.answer = _by_path([{"line1": _L1, "line2": _L2, "objectName": "ARCHIVE"}],
                              [{"line1": _L1, "line2": _L2, "objectName": "CURRENT"}])
        *_rest, name = await pol._fetch_merged_history(25544, "op", "pw", "REAL")
        assert name == "CURRENT"

    async def test_an_unnamed_object_is_named_by_its_number(self, udl: UdlStub) -> None:
        udl.answer = reply([])
        *_rest, name = await pol._fetch_merged_history(25544, "op", "pw", "REAL")
        assert name == "25544"


@pytest.fixture(scope="module")
def history_text() -> str:
    return "\n".join(r.tle for r in TestTwoTierReporting._catalogue())


def _connected() -> SessionState:
    state = SessionState()
    state.udl_username, state.udl_password = "op", "pw"
    return state


def _fetched(text: str) -> Any:
    async def fetched(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return text, text, {}, {}, "SIM"
    return fetched


class TestTheHeldHistory:
    async def test_without_udl_nothing_is_fetched_or_held(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pol, "_fetch_merged_history", pytest.fail)
        state = SessionState()
        held = await pol.held_history(state, 62902, _NOW)
        assert held.problem == "UDL is not connected, so no element-set history is held."
        assert state.elset_histories == {}

    async def test_a_fresh_history_answers_without_a_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _connected()
        state.elset_histories[62902] = kept = pol.HeldHistory(62902, _NOW, pol="held")
        monkeypatch.setattr(pol, "_fetch_merged_history", pytest.fail)
        assert await pol.held_history(state, 62902, _NOW + timedelta(minutes=29)) is kept

    async def test_a_stale_history_is_fetched_again_in_the_session_mode_and_source_and_held(
        self, monkeypatch: pytest.MonkeyPatch, history_text: str,
    ) -> None:
        state = _connected()
        state.udl_data_mode, state.udl_tle_source = "EXERCISE", "18SDS"
        state.elset_histories[62902] = pol.HeldHistory(62902, _NOW - pol.HELD_HISTORY_MAX_AGE, pol="old")
        asked: list[tuple[Any, ...]] = []
        fetch = _fetched(history_text)

        async def recorded(*args: Any, **kwargs: Any) -> Any:
            asked.append((*args, kwargs.get("source")))
            return await fetch(*args, **kwargs)

        monkeypatch.setattr(pol, "_fetch_merged_history", recorded)
        held = await pol.held_history(state, 62902, _NOW)
        assert asked == [(62902, "op", "pw", "EXERCISE", "18SDS")], "the operator's mode or source was not asked for"
        assert held.problem == ""
        assert held.pol.tle_count == 300
        assert state.elset_histories[62902] is held

    async def test_the_oldest_history_goes_first_past_twenty(
        self, monkeypatch: pytest.MonkeyPatch, history_text: str,
    ) -> None:
        state = _connected()
        for satno in range(1, 21):
            state.elset_histories[satno] = pol.HeldHistory(satno, _NOW, pol="held")
        monkeypatch.setattr(pol, "_fetch_merged_history", _fetched(history_text))
        await pol.held_history(state, 62902, _NOW)
        assert list(state.elset_histories) == [*range(2, 21), 62902]

    @pytest.mark.parametrize(("text", "problem"), [
        (" \n", "UDL returned no element sets for this object."),
        ("not an element set", "No usable element sets were in the UDL history."),
    ])
    async def test_an_unusable_answer_is_a_stated_problem_and_not_held(
        self, monkeypatch: pytest.MonkeyPatch, text: str, problem: str,
    ) -> None:
        state = _connected()
        monkeypatch.setattr(pol, "_fetch_merged_history", _fetched(text))
        held = await pol.held_history(state, 62902, _NOW)
        assert (held.pol, held.problem) == (None, problem)
        assert state.elset_histories == {}, "a failure was held, so the next request would not retry"

    async def test_a_failed_fetch_keeps_its_detail_in_the_log(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def refused(*_a: Any, **_k: Any) -> None:
            raise httpx.ConnectError(_MARKER)

        monkeypatch.setattr(pol, "_fetch_merged_history", refused)
        with caplog.at_level(logging.WARNING, logger=pol.logger.name):
            held = await pol.held_history(_connected(), 62902, _NOW)
        assert held.problem == "The element-set history could not be fetched from UDL."
        assert _MARKER in caplog.text

    async def test_a_failed_analysis_keeps_its_detail_in_the_log(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        def broken(*_a: Any) -> None:
            raise ValueError(_MARKER)

        monkeypatch.setattr(pol, "_fetch_merged_history", _fetched(f"{_L1}\n{_L2}"))
        monkeypatch.setattr(pol, "_analyse_merged", broken)
        with caplog.at_level(logging.ERROR, logger=pol.logger.name):
            held = await pol.held_history(_connected(), 62902, _NOW)
        assert held.problem == "The element-set history could not be analysed."
        assert _MARKER in caplog.text


class TestThePanelFallbacks:
    def test_a_history_the_model_cannot_read_leaves_the_panel_standing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, history_text: str,
    ) -> None:
        analysis = pol._analyse_merged(pol._MergedHistory("", history_text, {}, {}, "SIM"), 62902, 0.002, False)
        assert analysis is not None

        def broken(*_a: Any) -> None:
            raise ValueError(_MARKER)

        monkeypatch.setattr(tu, "history_signals", broken)
        result = analysis[0]
        with caplog.at_level(logging.WARNING, logger=pol.logger.name):
            view = pol._object_understanding(result, assess_pattern_of_life(result), None, _NOW)
        assert view is None
        assert _MARKER in caplog.text

    def test_an_analysis_with_no_element_sets_has_no_custody(self) -> None:
        assert pol._pol_custody(SimpleNamespace(records=[]), None, _NOW) is None

    def test_the_window_falls_back_to_the_manoeuvres_then_to_none(self) -> None:
        first, last = SimpleNamespace(epoch=_NOW - timedelta(days=9)), SimpleNamespace(epoch=_NOW)
        assert pol._analysis_window(SimpleNamespace(records=[], manoeuvres=[first, last])) == (first.epoch, _NOW)
        assert pol._analysis_window(SimpleNamespace(records=[], manoeuvres=[])) == (None, None)

    def test_a_history_with_no_window_has_no_behaviour_profile(self) -> None:
        empty = SimpleNamespace(records=[], manoeuvres=[], candidate_manoeuvres=[], satno=62902, regime="LEO")
        assert pol.notso_behaviour_profile(empty, []) == ([], None)
