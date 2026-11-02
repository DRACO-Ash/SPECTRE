"""The burn watch: one object, checked while the operator is signed in (SPC-006).

Each test pins one rule of :mod:`spectre.web.burn_watch`. The history and the
probe are stood in with plain burns, so the rules are tested without orbital
physics; the sweep tests cover what a burn changed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.warning_change import Status, WarningChange
from spectre.web import burn_watch
from spectre.web.burn_watch import BurnWatch, check_once, start_watch, still_wanted, watch_loop, watch_view
from spectre.web.models import SessionKey
from spectre.web.planning_state import _store, clear_account_state, get_session_state
from spectre.web.routes import pol, udl

_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
_BURN_AT = _NOW - timedelta(hours=6)


def _burn(start: datetime, after: datetime) -> SimpleNamespace:
    return SimpleNamespace(burn_window=(start, start), burn_epoch=start, tle_after=SimpleNamespace(epoch=after),
                           tle_before=SimpleNamespace(epoch=start - timedelta(hours=6), tle="before"))


def _pol(burns: list[Any], newest: datetime) -> SimpleNamespace:
    return SimpleNamespace(manoeuvres=burns, candidate_manoeuvres=[], records=[SimpleNamespace(epoch=newest, tle="after")])


@pytest.fixture
def owner() -> Iterator[tuple[SessionKey, Any]]:
    """A sign-in of its own, with UDL connected, removed afterwards."""
    key = SessionKey(user_id=987_654, session_id="burn-watch-test")
    state = get_session_state(key)
    state.udl_username, state.udl_password = "operator", "udl-secret"
    yield key, state
    _store.pop(key, None)


def _watch(state: Any, accounted: datetime | None = None, newest: datetime | None = None) -> BurnWatch:
    watch = BurnWatch(red_name="RED-X", red_satno=90010, red_regime="GEO", targets=[], manual_tle_by_name={},
                      max_dv_m_s=500.0, accounted_until=accounted, started_at=_NOW - timedelta(hours=1),
                      next_check_at=_NOW, newest_epoch=newest)
    state.burn_watch = watch
    return watch


class _Udl:
    """The probe and the history, stood in; counts the history fetches."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, burns: list[Any], probe: datetime | Exception) -> None:
        self.burns, self.probe, self.fetches = burns, probe, 0

        async def probe_epoch(_state: Any, _watch: Any) -> datetime:
            if isinstance(self.probe, Exception):
                raise self.probe
            return self.probe

        async def held(state: Any, satno: int, now: datetime) -> Any:
            kept = state.elset_histories.get(satno)
            if kept is not None:
                return kept
            self.fetches += 1
            held_now = pol.HeldHistory(satno, now, pol=_pol(self.burns, self.probe if isinstance(self.probe, datetime)
                                                             else _NOW))
            state.elset_histories[satno] = held_now
            return held_now

        monkeypatch.setattr(burn_watch, "_probe", probe_epoch)
        monkeypatch.setattr(pol, "held_history", held)
        monkeypatch.setattr(pol, "history_evidence", lambda p, _r=None: (SimpleNamespace(manoeuvres=[]), None))


async def _compute(*_a: Any) -> WarningChange:
    return WarningChange(Status.FIGURES, "That burn cut your warning on BLUE-1 from 14h to 3h.")


def _burn_lines(state: Any) -> list[str]:
    return [line for line in state.log_entries if "[BURN]" in line]


class TestAnnouncing:
    async def test_a_new_burn_is_announced_once_with_what_it_changed(self, owner: Any,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """W1."""
        _, state = owner
        _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        alert = await check_once(state, _watch(state, accounted=_NOW - timedelta(days=3)), _NOW, _compute)
        assert alert is not None and state.burn_alert is alert
        assert _burn_lines(state)[-1] == ("[BURN] RED-X burned at 04:00 UTC on 2 Nov: That burn cut your warning on "
                                          "BLUE-1 from 14h to 3h.")

    @pytest.mark.parametrize("shift_minutes", [-2, 2])
    async def test_a_redated_burn_is_not_announced_again(self, owner: Any, monkeypatch: pytest.MonkeyPatch,
                                                         shift_minutes: int) -> None:
        """W2: two checks, then a re-estimate moving the burn a little, give one alert."""
        _, state = owner
        udl_stub = _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        before = len(_burn_lines(state))
        await check_once(state, watch, _NOW, _compute)
        udl_stub.probe = _NOW - timedelta(minutes=20)
        state.elset_histories.clear()
        await check_once(state, watch, _NOW + timedelta(minutes=10), _compute)
        redated = _BURN_AT + timedelta(minutes=shift_minutes)
        udl_stub.burns = [_burn(redated, _BURN_AT + timedelta(hours=1))]
        udl_stub.probe = _NOW - timedelta(minutes=10)
        state.elset_histories.clear()
        await check_once(state, watch, _NOW + timedelta(minutes=20), _compute)
        assert len(_burn_lines(state)) - before == 1

    async def test_burns_the_sweep_already_showed_are_not_announced(self, owner: Any,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        """W3: accounted for at the sweep, no alert; with the sweep still loading, the first check alerts."""
        _, state = owner
        after = _BURN_AT + timedelta(hours=1)
        _Udl(monkeypatch, [_burn(_BURN_AT, after)], _NOW - timedelta(minutes=30))
        state.burn_alert = None
        assert await check_once(state, _watch(state, accounted=after), _NOW, _compute) is None
        state.elset_histories.clear()
        assert await check_once(state, _watch(state, accounted=None), _NOW, _compute) is not None


class TestCheapChecks:
    async def test_an_unchanged_newest_set_fetches_no_history(self, owner: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
        """W4."""
        _, state = owner
        newest = _NOW - timedelta(hours=1)
        udl_stub = _Udl(monkeypatch, [], newest)
        await check_once(state, _watch(state, newest=newest), _NOW, _compute)
        assert udl_stub.fetches == 0

    async def test_a_held_history_that_reaches_the_newest_set_is_reused(self, owner: Any,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
        """W11: on a cold sign-in the sweep's own fetch serves the first check."""
        _, state = owner
        newest = _NOW - timedelta(minutes=30)
        udl_stub = _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], newest)
        state.elset_histories[90010] = pol.HeldHistory(90010, _NOW, pol=_pol(udl_stub.burns, newest))
        await check_once(state, _watch(state), _NOW, _compute)
        assert udl_stub.fetches == 0


class TestItStops:
    async def test_signing_out_of_the_app_stops_it_within_a_tick(self, owner: Any,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        """W5: no probe after the sign-in's state is cleared."""
        key, state = owner
        udl_stub = _Udl(monkeypatch, [], _NOW)
        watch = _watch(state)
        watch.next_check_at = _NOW + timedelta(days=1)
        monkeypatch.setattr(burn_watch, "TICK_S", 0.01)
        clear_account_state(key.user_id)
        await asyncio.wait_for(watch_loop(state, key, watch, None, _compute), timeout=2)
        assert watch.stopped == "this sign-in has ended"
        assert udl_stub.fetches == 0

    async def test_eight_hours_after_signing_in_it_stops(self, owner: Any) -> None:
        """W6: expiry runs from the sign-in, not from when the watch started."""
        key, state = owner
        watch = _watch(state)
        _store[key] = (time.monotonic() - (8 * 3600 + 60), state)
        assert still_wanted(state, key, watch) == "this sign-in has ended"

    async def test_udl_logout_cancels_it(self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """W7."""
        key, state = owner
        monkeypatch.setattr(burn_watch, "TICK_S", 0.01)
        watch = _watch(state)
        watch.next_check_at = _NOW + timedelta(days=1)
        state.burn_watch = None
        start_watch(state, key, watch, None, _compute, udl.spawn_session_task)
        await asyncio.sleep(0.05)
        state.udl_username = state.udl_password = None
        udl._cancel_session_tasks(key)
        await asyncio.sleep(0.05)
        assert watch.task is not None and watch.task.done()
        view = watch_view(state, key, _NOW)
        assert view["burn_watch"].stopped == "UDL is disconnected"

    async def test_a_newer_sweep_replaces_it(self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """W8: the old task is cancelled at once, not left asleep holding the password until its next tick."""
        key, state = owner
        monkeypatch.setattr(burn_watch, "TICK_S", 60.0)
        first, second = _watch(state), _watch(state)
        for w in (first, second):
            w.next_check_at = _NOW + timedelta(days=1)
        state.burn_watch = None
        start_watch(state, key, first, None, _compute, udl.spawn_session_task)
        await asyncio.sleep(0.05)  # the first loop is now asleep in its tick
        start_watch(state, key, second, None, _compute, udl.spawn_session_task)
        await asyncio.sleep(0.05)
        assert first.task is not None and first.task.done()
        assert second.task is not None and not second.task.done()
        second.task.cancel()


class TestFailuresAreStatedNotLeaked:
    async def test_a_failed_check_says_so_and_the_next_one_runs(self, owner: Any, monkeypatch: pytest.MonkeyPatch,
                                                                caplog: pytest.LogCaptureFixture) -> None:
        """W9 and W12."""
        _, state = owner
        udl_stub = _Udl(monkeypatch, [], RuntimeError("internal detail\n[BURN] forged"))
        watch = _watch(state)
        watch.last_good_at = _NOW - timedelta(minutes=10)
        with caplog.at_level(logging.WARNING, logger="spectre.web.burn_watch"):
            await check_once(state, watch, _NOW, _compute)
        assert watch.problem.startswith("The element set could not be fetched from UDL at 10:00 UTC; trying again at")
        assert "Burns since 09:50 UTC, the last good check, are not yet seen." in watch.problem
        assert "internal detail" not in watch.problem
        assert all("\n" not in r.getMessage() for r in caplog.records)
        udl_stub.probe = _NOW
        await check_once(state, watch, _NOW + timedelta(minutes=10), _compute)
        assert watch.problem == ""


class TestTheNote:
    def test_the_note_needs_a_sign_in(self, client: Any) -> None:
        """W10."""
        client.cookies.clear()
        resp = client.get("/plan/threat/burn-watch", follow_redirects=False)
        assert resp.status_code in (302, 303, 401)

    def test_watching_polls_and_stopped_does_not(self, client: Any, auth_cookie: str) -> None:
        from tests.integration.conftest import session_state

        state = session_state(auth_cookie)
        saved = (state.burn_watch, state.burn_alert, state.udl_username, state.udl_password)
        state.udl_username, state.udl_password = "operator", "udl-secret"
        try:
            state.burn_watch, state.burn_alert = _watch(state), None
            state.burn_watch.next_check_at = datetime.now(tz=UTC) + timedelta(minutes=10)
            page = client.get("/plan/threat/burn-watch", cookies={"spectre_session": auth_cookie}).text
            assert "Watching <strong>RED-X</strong> for burns" in page
            assert 'hx-trigger="every 60s"' in page
            state.burn_watch.stopped = "UDL is disconnected"
            page = client.get("/plan/threat/burn-watch", cookies={"spectre_session": auth_cookie}).text
            assert "Not watching RED-X for burns: UDL is disconnected." in page
            assert "hx-trigger" not in page
            state.burn_alert = burn_watch.BurnAlert("RED-X", "04:00 UTC on 2 Nov", _NOW,
                                                    WarningChange(Status.FIGURES, "That burn cut your warning."))
            page = client.get("/plan/threat/burn-watch", cookies={"spectre_session": auth_cookie}).text
            assert "RED-X burned at 04:00 UTC on 2 Nov" in page
            assert "Sweep again" in page
        finally:
            state.burn_watch, state.burn_alert, state.udl_username, state.udl_password = saved
