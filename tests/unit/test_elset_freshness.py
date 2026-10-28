"""Element sets are the newest UDL holds, refreshed at connect, and their age shown.

0.6.2 in service: with UDL connected and the HRR list refreshed, the threat
sweep's red card showed SY-12 02 at an epoch of 15 October on 28 October.
``fetch_tle_for_satno`` asked ``/elset/current``, which answers with one
current element set per source and in no order, and kept the first record.
``_select_latest_elset`` already existed for exactly that reason, and only the
TLE panel used it. Nothing refreshed a held element set either, and no panel
but the TLE panel said how old one was.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.elsets import elset_age, refresh_held_elsets
from spectre.web.planning_state import SessionState

_NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
_GEO_LINE2 = "2 50322   0.1200  96.0000 0002000 270.0000 264.0000  1.00273791 10006"
_LEO_MEAN_MOTION = "15.50000000"


def _checksummed(line: str) -> str:
    body = line[:68]
    total = sum(int(c) if c.isdigit() else int(c == "-") for c in body)
    return body + str(total % 10)


def _tle(epoch: datetime, *, leo: bool = False, satno: int = 50322) -> str:
    """A valid two-line element set for *satno* at *epoch*, GEO unless *leo*."""
    day = (epoch - datetime(epoch.year, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0 + 1.0
    field = f"{epoch.year % 100:02d}{day:012.8f}"
    line1 = f"1 {satno:05d}U 20001A   {field}  .00000000  00000-0  00000-0 0  9990"
    line2 = f"2 {satno:05d}" + _GEO_LINE2[7:]
    if leo:
        line2 = line2[:52] + _LEO_MEAN_MOTION + line2[63:]
    return f"{_checksummed(line1)}\n{_checksummed(line2)}"


def _record(epoch: datetime, *, source: str = "18SDS", mode: str = "REAL") -> dict[str, Any]:
    line1, line2 = _tle(epoch).split("\n")
    return {"line1": line1, "line2": line2, "source": source, "dataMode": mode}


def _udl_answering(payload: object) -> Any:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)
    return patch("httpx.AsyncClient", return_value=client)


class TestTheNewestEpochIsTaken:
    @pytest.mark.asyncio
    async def test_a_lagging_source_listed_first_does_not_win(self) -> None:
        from spectre.web.routes.udl import fetch_tle_for_satno

        stale, fresh = _NOW - timedelta(days=13), _NOW - timedelta(hours=6)
        with _udl_answering([_record(stale, source="LAGGING"), _record(fresh)]):
            got = await fetch_tle_for_satno(50322, "u", "p")
        assert got is not None
        assert got[0] == _tle(fresh), "the first record was taken, not the newest"

    @pytest.mark.asyncio
    async def test_the_newest_complete_record_wins_over_a_newer_empty_one(self) -> None:
        from spectre.web.routes.udl import fetch_tle_for_satno

        good, empty = _record(_NOW - timedelta(days=1)), _record(_NOW)
        empty["line1"] = empty["line2"] = ""
        with _udl_answering([empty, good]):
            got = await fetch_tle_for_satno(50322, "u", "p")
        assert got is not None
        assert got[0] == f"{good['line1']}\n{good['line2']}"

    @pytest.mark.asyncio
    async def test_the_mode_is_the_chosen_records_own(self) -> None:
        from spectre.web.routes.udl import fetch_tle_for_satno

        older = _record(_NOW - timedelta(days=2), mode="REAL")
        newer = _record(_NOW - timedelta(hours=1), mode="TEST")
        with _udl_answering([older, newer]):
            got = await fetch_tle_for_satno(50322, "u", "p")
        assert got is not None
        assert got[1] == "TEST"


class TestElementSetAge:
    def test_a_13_day_old_geo_set_is_stale(self) -> None:
        age = elset_age(_tle(_NOW - timedelta(days=13)), _NOW)
        assert age is not None
        assert age.days == pytest.approx(13.0)
        assert age.stale, "GEO is stale past 72 hours"
        assert age.label == "13.0 d"

    def test_a_geo_set_inside_72_hours_is_current(self) -> None:
        age = elset_age(_tle(_NOW - timedelta(hours=48)), _NOW)
        assert age is not None
        assert not age.stale

    def test_leo_is_held_to_24_hours(self) -> None:
        older = elset_age(_tle(_NOW - timedelta(hours=30), leo=True), _NOW)
        newer = elset_age(_tle(_NOW - timedelta(hours=10), leo=True), _NOW)
        assert older is not None and older.stale
        assert newer is not None and not newer.stale
        assert newer.label == "10.0 h"

    def test_an_unreadable_set_has_no_age(self) -> None:
        assert elset_age("not a tle", _NOW) is None


def _state_holding(*tracks: RedTrack, blue: tuple[BlueAsset, ...] = ()) -> SessionState:
    state = SessionState()
    state.red_tracks = list(tracks)
    state.blue_assets = list(blue)
    return state


def _fetch_returning(by_satno: dict[int, tuple[str, str] | None]) -> Any:
    async def fake(satno: int, *_args: object, **_kwargs: object) -> tuple[str, str] | None:
        return by_satno.get(satno)

    return patch("spectre.web.routes.udl.fetch_tle_for_satno", side_effect=fake)


class TestRefreshAtConnect:
    @pytest.mark.asyncio
    async def test_a_udl_track_is_replaced_by_a_newer_set(self) -> None:
        track = RedTrack(name="SY-12 02", tle=_tle(_NOW - timedelta(days=13)), data_mode="REAL")
        state = _state_holding(track)
        fresh = _tle(_NOW - timedelta(hours=6))
        with _fetch_returning({50322: (fresh, "REAL")}):
            await refresh_held_elsets(state, "u", "p")
        assert track.tle == fresh
        refresh = state.elset_refresh
        assert refresh is not None and not refresh.running
        assert refresh.updated == ["red SY-12 02"]
        assert refresh.finished_at is not None

    @pytest.mark.asyncio
    async def test_a_pasted_track_is_never_overwritten(self) -> None:
        pasted = _tle(_NOW - timedelta(days=13))
        track = RedTrack(name="Hypothetical", tle=pasted)
        assert track.data_mode == "MANUAL", "a pasted set is MANUAL unless it came from UDL"
        state = _state_holding(track)
        with _fetch_returning({50322: (_tle(_NOW), "REAL")}) as fetch:
            await refresh_held_elsets(state, "u", "p")
        assert track.tle == pasted
        fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_older_answer_keeps_the_held_set(self) -> None:
        held = _tle(_NOW - timedelta(hours=2))
        track = RedTrack(name="SY-12 02", tle=held, data_mode="REAL")
        state = _state_holding(track)
        with _fetch_returning({50322: (_tle(_NOW - timedelta(days=3)), "REAL")}):
            await refresh_held_elsets(state, "u", "p")
        assert track.tle == held
        assert state.elset_refresh is not None
        assert state.elset_refresh.current == 1

    @pytest.mark.asyncio
    async def test_a_failed_fetch_is_named(self) -> None:
        track = RedTrack(name="SY-12 02", tle=_tle(_NOW - timedelta(days=13)), data_mode="REAL")
        state = _state_holding(track)
        with _fetch_returning({}):
            await refresh_held_elsets(state, "u", "p")
        assert state.elset_refresh is not None
        assert state.elset_refresh.failed == ["red SY-12 02"]

    @pytest.mark.asyncio
    async def test_the_sweep_cache_is_refreshed_including_real_sets(self) -> None:
        state = _state_holding()
        state.hrr_tle_cache = {"50322": _tle(_NOW - timedelta(days=13)), "39034": _tle(_NOW, satno=39034)}
        state.hrr_tle_data_mode = {"50322": "REAL", "39034": "SYNTHETIC"}
        fresh = _tle(_NOW - timedelta(hours=1))
        real_39034 = _tle(_NOW - timedelta(hours=3), satno=39034)
        with _fetch_returning({50322: (fresh, "REAL"), 39034: (real_39034, "REAL")}):
            await refresh_held_elsets(state, "u", "p")
        assert state.hrr_tle_cache["50322"] == fresh
        assert state.hrr_tle_cache["39034"] == real_39034, "a synthetic set is replaced whatever its epoch"
        assert state.hrr_tle_data_mode["39034"] == "REAL"

    @pytest.mark.asyncio
    async def test_blue_assets_from_udl_are_refreshed_too(self) -> None:
        asset = BlueAsset(name="Alpha", tle=_tle(_NOW - timedelta(days=5), satno=41866), data_mode="REAL")
        state = _state_holding(blue=(asset,))
        fresh = _tle(_NOW - timedelta(hours=2), satno=41866)
        with _fetch_returning({41866: (fresh, "REAL")}):
            await refresh_held_elsets(state, "u", "p")
        assert asset.tle == fresh

    @pytest.mark.asyncio
    async def test_a_training_object_is_left_alone(self) -> None:
        track = RedTrack(name="Drill", tle=_tle(_NOW - timedelta(days=13)), training=True, data_mode="REAL")
        state = _state_holding(track)
        with _fetch_returning({50322: (_tle(_NOW), "REAL")}) as fetch:
            await refresh_held_elsets(state, "u", "p")
        fetch.assert_not_called()
