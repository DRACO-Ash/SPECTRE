"""The burn watch: one object, checked while the operator is signed in (SPC-006).

Each test pins one rule of :mod:`spectre.web.burn_watch`. The history and the
probe are stood in with plain burns, so the rules are tested without orbital
physics; the sweep tests cover what a burn changed.
"""

from __future__ import annotations

import asyncio
import logging
import re
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


@pytest.fixture(autouse=True)
def _no_live_udl(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test here may reach UDL, and the watch's clock is pinned to the fixtures' day.

    The loop tests set their next check a day after _NOW. On the real clock that
    day arrived, and the loop's probe went to UDL with the test password; the
    failure was swallowed, so nothing went red. Found by the V0.9 review.
    """
    calls: list[Any] = []

    async def refuse(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(udl, "fetch_tle_for_satno", refuse)
    monkeypatch.setattr(burn_watch, "_utc_now", lambda: _NOW)
    yield
    assert calls == [], "a burn-watch test reached UDL"


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
        key, state = owner
        _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        alert = await check_once(state, key, _watch(state, accounted=_NOW - timedelta(days=3)), _NOW, _compute)
        assert alert is not None and state.burn_alert is alert
        assert _burn_lines(state)[-1] == ("[BURN] RED-X burned at 04:00 UTC on 2 Nov: That burn cut your warning on "
                                          "BLUE-1 from 14h to 3h.")

    @pytest.mark.parametrize(("dated", "said"), [
        (True, "at 04:00 UTC on 2 Nov"),
        (False, "between 22:00 UTC on 1 Nov and 05:00 UTC on 2 Nov"),
    ])
    async def test_it_says_when_it_burned_only_as_closely_as_that_is_known(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch, dated: bool, said: str) -> None:
        """An undated burn earned no single time: its epoch is the set after it, so the alert gives its bracket.

        The sweep already said "between X and Y" for it; the watch named the
        post-burn set's epoch as the moment it burned.
        """
        key, state = owner
        burn = _burn(_BURN_AT, _BURN_AT + timedelta(hours=1))
        if not dated:
            burn.burn_window = (burn.tle_before.epoch, burn.tle_after.epoch)
            burn.burn_epoch = burn.tle_after.epoch
        _Udl(monkeypatch, [burn], _NOW - timedelta(minutes=30))
        alert = await check_once(state, key, _watch(state, accounted=_NOW - timedelta(days=3)), _NOW, _compute)
        assert alert is not None and alert.burn_when == said
        assert _burn_lines(state)[-1].startswith(f"[BURN] RED-X burned {said}: ")

        async def fails(*_a: Any) -> WarningChange:
            raise RuntimeError("solver")

        state.elset_histories.clear()
        await check_once(state, key, _watch(state, accounted=_NOW - timedelta(days=3)), _NOW, fails)
        assert state.burn_watch.problem.startswith(f"RED-X burned {said}, but what it changed could not be computed.")

    @pytest.mark.parametrize("shift_minutes", [-2, 2])
    async def test_a_redated_burn_is_not_announced_again(self, owner: Any, monkeypatch: pytest.MonkeyPatch,
                                                         shift_minutes: int) -> None:
        """W2: two checks, then a re-estimate moving the burn a little, give one alert."""
        key, state = owner
        udl_stub = _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        before = len(_burn_lines(state))
        await check_once(state, key, watch, _NOW, _compute)
        udl_stub.probe = _NOW - timedelta(minutes=20)
        state.elset_histories.clear()
        await check_once(state, key, watch, _NOW + timedelta(minutes=10), _compute)
        redated = _BURN_AT + timedelta(minutes=shift_minutes)
        udl_stub.burns = [_burn(redated, _BURN_AT + timedelta(hours=1))]
        udl_stub.probe = _NOW - timedelta(minutes=10)
        state.elset_histories.clear()
        await check_once(state, key, watch, _NOW + timedelta(minutes=20), _compute)
        assert len(_burn_lines(state)) - before == 1

    async def test_burns_the_sweep_already_showed_are_not_announced(self, owner: Any,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        """W3: accounted for at the sweep, no alert; with the sweep still loading, the first check alerts."""
        key, state = owner
        after = _BURN_AT + timedelta(hours=1)
        _Udl(monkeypatch, [_burn(_BURN_AT, after)], _NOW - timedelta(minutes=30))
        state.burn_alert = None
        assert await check_once(state, key, _watch(state, accounted=after), _NOW, _compute) is None
        state.elset_histories.clear()
        assert await check_once(state, key, _watch(state, accounted=None), _NOW, _compute) is not None


class TestCheapChecks:
    async def test_an_unchanged_newest_set_fetches_no_history(self, owner: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
        """W4."""
        key, state = owner
        newest = _NOW - timedelta(hours=1)
        udl_stub = _Udl(monkeypatch, [], newest)
        await check_once(state, key, _watch(state, newest=newest), _NOW, _compute)
        assert udl_stub.fetches == 0

    async def test_a_held_history_that_reaches_the_newest_set_is_reused(self, owner: Any,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
        """W11: on a cold sign-in the sweep's own fetch serves the first check."""
        key, state = owner
        newest = _NOW - timedelta(minutes=30)
        udl_stub = _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], newest)
        state.elset_histories[90010] = pol.HeldHistory(90010, _NOW, pol=_pol(udl_stub.burns, newest))
        await check_once(state, key, _watch(state), _NOW, _compute)
        assert udl_stub.fetches == 0

    async def test_a_check_records_the_newest_set_so_the_next_one_stays_cheap(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """W4 seeded the newest epoch by hand, so dropping the check's own record of it stayed green (V0.9 review 27)."""
        key, state = owner
        newest = _NOW - timedelta(minutes=30)
        _Udl(monkeypatch, [], newest)
        looked: list[datetime | None] = []
        real = burn_watch._new_burns

        async def counted(*args: Any) -> Any:
            looked.append(args[-1])
            return await real(*args)

        monkeypatch.setattr(burn_watch, "_new_burns", counted)
        watch = _watch(state)
        await check_once(state, key, watch, _NOW, _compute)
        assert watch.newest_epoch == newest
        await check_once(state, key, watch, _NOW + timedelta(minutes=10), _compute)
        assert looked == [newest]


class TestTheProbe:
    """The probe was stood in by every test, so its own two answers went unrun (V0.9 review 19)."""

    async def test_it_asks_for_the_watched_object_and_returns_its_newest_epoch(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        from tests.integration.test_sweep_burn_differential import _base

        _, state = owner
        asked: list[Any] = []

        async def newest(satno: int, user: str, password: str, **kw: Any) -> udl.FetchedElset:
            asked.append((satno, user, password, kw))
            return udl.FetchedElset(_base(), "REAL", "18th SPCS")

        monkeypatch.setattr(udl, "fetch_tle_for_satno", newest)
        epoch = await burn_watch._probe(state, _watch(state))
        assert epoch == datetime(2026, 4, 10, tzinfo=UTC)
        assert [a[:3] for a in asked] == [(90010, "operator", "udl-secret")]
        assert asked[0][3] == {"data_mode": state.udl_data_mode, "source": state.udl_tle_source}

    async def test_no_element_set_from_udl_is_a_failed_check(self, owner: Any,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
        _, state = owner

        async def nothing(*_a: Any, **_k: Any) -> None:
            return None

        monkeypatch.setattr(udl, "fetch_tle_for_satno", nothing)
        with pytest.raises(LookupError):
            await burn_watch._probe(state, _watch(state))


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

    async def test_signing_out_during_a_check_fetches_no_history_and_raises_no_alert(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A sign-out while the probe is in flight ends the check there (V0.9 review 6).

        The loop asked whether it was still wanted only before each check, so the
        check went on to fetch the history with the signed-out operator's UDL
        password, fly the sweeps and write an alert into the discarded state.
        """
        key, state = owner
        udl_stub = _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW)
        computed: list[Any] = []

        async def signed_out_meanwhile(_state: Any, _watch: Any) -> datetime:
            clear_account_state(key.user_id)
            return _NOW - timedelta(minutes=30)

        async def compute(*args: Any) -> WarningChange:
            computed.append(args)
            return await _compute()

        monkeypatch.setattr(burn_watch, "_probe", signed_out_meanwhile)
        monkeypatch.setattr(burn_watch, "TICK_S", 0.01)
        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        state.burn_alert = None
        await asyncio.wait_for(watch_loop(state, key, watch, None, compute), timeout=2)
        assert watch.stopped == "this sign-in has ended"
        assert (udl_stub.fetches, computed, state.burn_alert, watch.newest_epoch) == (0, [], None, None)

    @pytest.mark.parametrize(("during", "computes"), [("history", 0), ("compute", 1)])
    async def test_signing_out_later_in_the_check_leaves_no_alert(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch, during: str, computes: int) -> None:
        """A sign-out during the history fetch flies nothing; one during the computation records nothing."""
        key, state = owner
        _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        computed: list[Any] = []
        fetch = pol.held_history

        async def held(*args: Any) -> Any:
            if during == "history":
                clear_account_state(key.user_id)
            return await fetch(*args)

        async def compute(*args: Any) -> WarningChange:
            computed.append(args)
            if during == "compute":
                clear_account_state(key.user_id)
            return await _compute()

        monkeypatch.setattr(pol, "held_history", held)
        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        state.burn_alert = None
        before = len(_burn_lines(state))
        assert await check_once(state, key, watch, _NOW, compute) is None
        assert (len(computed), state.burn_alert, len(_burn_lines(state)) - before) == (computes, None, 0)

    @pytest.mark.parametrize("stage", ["probe", "history"])
    async def test_a_check_in_flight_after_signing_out_makes_no_udl_request(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
        """Signing out takes the UDL credentials from the state the check still holds (V0.9 review 6).

        The real probe and the real history fetch run; only the UDL requests under
        them are stood in. Before, both went to UDL with the signed-out password.
        """
        key, state = owner
        requests: list[Any] = []

        async def newest_set(*args: Any, **_k: Any) -> None:
            requests.append(("newest set", args))

        async def history(*args: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
            requests.append(("history", args))
            return "", "", {}, {}, ""

        monkeypatch.setattr(udl, "fetch_tle_for_satno", newest_set)
        monkeypatch.setattr(pol, "_fetch_merged_history", history)
        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        state.elset_histories.clear()
        clear_account_state(key.user_id)
        if stage == "probe":
            assert await check_once(state, key, watch, _NOW, _compute) is None
        else:
            with pytest.raises(burn_watch._StatedError):
                await burn_watch._new_burns(state, watch, _NOW, _NOW)
        assert requests == []

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
        start_watch(state, key, watch, first_history=None, compute=_compute, spawn=udl.spawn_session_task)
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
        start_watch(state, key, first, first_history=None, compute=_compute, spawn=udl.spawn_session_task)
        await asyncio.sleep(0.05)  # the first loop is now asleep in its tick
        start_watch(state, key, second, first_history=None, compute=_compute, spawn=udl.spawn_session_task)
        await asyncio.sleep(0.05)
        assert first.task is not None and first.task.done()
        assert second.task is not None and not second.task.done()
        second.task.cancel()

    def test_a_watch_no_longer_held_says_a_newer_sweep_replaced_it(self, owner: Any) -> None:
        """W8 only pinned start_watch's cancel; the loop's own check went unpinned (V0.9 review 27)."""
        key, state = owner
        replaced, current = _watch(state), _watch(state)
        assert state.burn_watch is current
        assert still_wanted(state, key, current) == ""
        assert still_wanted(state, key, replaced) == "a newer sweep replaced it"


class TestFailuresAreStatedNotLeaked:
    async def test_a_failed_check_says_so_and_the_next_one_runs(self, owner: Any, monkeypatch: pytest.MonkeyPatch,
                                                                caplog: pytest.LogCaptureFixture) -> None:
        """W9 and W12."""
        key, state = owner
        udl_stub = _Udl(monkeypatch, [], RuntimeError("internal detail\n[BURN] forged"))
        watch = _watch(state)
        watch.last_good_at = _NOW - timedelta(minutes=10)
        with caplog.at_level(logging.WARNING, logger="spectre.web.burn_watch"):
            await check_once(state, key, watch, _NOW, _compute)
        assert watch.problem.startswith("The element set could not be fetched from UDL at 10:00 UTC; trying again at")
        assert "Burns since 09:50 UTC, the last good check, are not yet seen." in watch.problem
        assert "internal detail" not in watch.problem
        assert all("\n" not in r.getMessage() for r in caplog.records)
        udl_stub.probe = _NOW
        await check_once(state, key, watch, _NOW + timedelta(minutes=10), _compute)
        assert watch.problem == ""

    async def test_a_failed_computation_is_retried_and_not_blamed_on_udl(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A burn found but not computed is not lost: the next check on the same set computes it again.

        The newest epoch and the good check were recorded before the computation,
        so one failure left the set looking seen, the next check skipped it and
        cleared the problem, and the burn was never announced (V0.9 review 0, 5, 12, 16).
        """
        key, state = owner
        _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        calls: list[Any] = []

        async def fails_once(*args: Any) -> WarningChange:
            calls.append(args)
            if len(calls) == 1:
                raise RuntimeError("solver detail")
            return await _compute()

        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        watch.last_good_at = _NOW - timedelta(minutes=10)
        state.burn_alert = None
        assert await check_once(state, key, watch, _NOW, fails_once) is None
        assert watch.problem == ("RED-X burned at 04:00 UTC on 2 Nov, but what it changed could not be computed. "
                                 "Checked at 10:00 UTC; trying again at 10:10 UTC.")
        assert watch.newest_epoch is None and watch.last_good_at == _NOW - timedelta(minutes=10)
        later = _NOW + timedelta(minutes=10)
        alert = await check_once(state, key, watch, later, fails_once)
        assert len(calls) == 2
        assert alert is not None and state.burn_alert is alert
        assert watch.problem == "" and watch.last_good_at == later
        assert watch.newest_epoch == _NOW - timedelta(minutes=30)


    async def test_a_computation_that_keeps_failing_still_says_when_the_burn_was(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every retry names the burn, and claims no fresh fetch and no unseen burns (V0.10 review of 0, 5, 12, 16).

        The retries reuse the held history, so "a new element set was fetched"
        was false, and "burns since the last good check are not yet seen" denied
        the burn the check had just found, without ever saying when it was.
        """
        key, state = owner
        udl_stub = _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))

        async def always_fails(*_a: Any) -> WarningChange:
            raise RuntimeError("solver detail")

        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        watch.last_good_at = _NOW - timedelta(minutes=10)
        for minutes in (0, 10, 20):
            await check_once(state, key, watch, _NOW + timedelta(minutes=minutes), always_fails)
        assert watch.problem == ("RED-X burned at 04:00 UTC on 2 Nov, but what it changed could not be computed. "
                                 "Checked at 10:20 UTC; trying again at 10:30 UTC.")
        assert udl_stub.fetches == 1
        assert watch.newest_epoch is None and state.burn_alert is None

    @pytest.mark.parametrize("stage", ["held", "evidence"])
    async def test_a_history_that_cannot_be_used_is_not_blamed_on_the_udl_fetch(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
        """The history's own fixed sentence is shown, not "could not be fetched from UDL" (V0.10 review of 12, 16)."""
        key, state = owner
        _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        if stage == "held":
            async def unanalysed(_state: Any, satno: int, now: datetime) -> Any:
                return pol.HeldHistory(satno, now, problem="The element-set history could not be analysed.")
            monkeypatch.setattr(pol, "held_history", unanalysed)
        else:
            def evidence_fails(*_a: Any) -> Any:
                raise ValueError("estimator detail")
            monkeypatch.setattr(pol, "history_evidence", evidence_fails)
        watch = _watch(state, accounted=_NOW - timedelta(days=3))
        watch.last_good_at = _NOW - timedelta(minutes=10)
        await check_once(state, key, watch, _NOW, _compute)
        assert watch.problem == ("The element-set history could not be analysed. Checked at 10:00 UTC; trying again "
                                 "at 10:10 UTC. Burns since 09:50 UTC, the last good check, are not yet seen.")
        assert watch.newest_epoch is None


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
            state.burn_alert = burn_watch.BurnAlert("RED-X", "at 04:00 UTC on 2 Nov", _NOW,
                                                    WarningChange(Status.FIGURES, "That burn cut your warning."))
            page = client.get("/plan/threat/burn-watch", cookies={"spectre_session": auth_cookie}).text
            assert "RED-X burned at 04:00 UTC on 2 Nov" in page
            assert "Sweep again" in page
        finally:
            state.burn_watch, state.burn_alert, state.udl_username, state.udl_password = saved


def _note(**context: Any) -> str:
    """The note alone, through the sweep template tests' StrictUndefined environment and the app's filters."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    from spectre.web.app import templates as app_templates
    from tests.unit.test_threat_sweep_template import _TEMPLATE_DIR

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(app_templates.env.filters)
    return env.get_template("partials/burn_watch_note.html").render(**context)


def _opening_tag(html: str, element_id: str) -> str:
    found = re.search(rf'<div id="{element_id}"[^>]*>', html)
    assert found is not None, element_id
    return found.group(0)


class TestTheNoteRendering:
    def test_the_alert_and_the_problem_take_their_colours_from_the_band_tokens(self) -> None:
        """T2 rendered the note with no alert and no problem, so raw colours there stayed green (V0.9 review 29)."""
        watch = _watch(SimpleNamespace(), accounted=None)
        watch.problem = "The element set could not be fetched from UDL."
        alert = burn_watch.BurnAlert("RED-X", "at 03:12 UTC on 2 Nov", _NOW,
                                     WarningChange(Status.FIGURES, "That burn cut your warning."))
        html = _note(burn_watch=watch, burn_alert=alert, watch_ends_at=_NOW + timedelta(hours=7))
        alert_tag = re.search(r'<div class="burn-alert" style="([^"]*)"', html)
        problem_tag = re.search(r'<div style="([^"]*)">The element set could not be fetched', html)
        assert alert_tag is not None and problem_tag is not None
        assert alert_tag.group(1).startswith("border-left:4px solid var(--spectre-status-high); "
                                             "background:rgba(var(--spectre-status-high-rgb), 0.06);")
        assert problem_tag.group(1) == "color:var(--spectre-status-high)"
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", html)
        assert not re.search(r"(?<!var\(--spectre-status-)(?<![-\w])rgba?\((?!var\()", html)

    @pytest.mark.parametrize("stopped", ["", "UDL is disconnected"])
    def test_the_live_region_is_not_the_element_the_poll_replaces(self, stopped: str) -> None:
        """A live region swapped out every 60 s is not reliably announced (V0.9 review 18).

        The region stays put and the poll replaces only the note inside it, taking
        just the note from the response; the Sweep again button inside must not
        inherit that selection.
        """
        watch = _watch(SimpleNamespace(), accounted=None)
        watch.stopped = stopped
        alert = burn_watch.BurnAlert("RED-X", "at 03:12 UTC on 2 Nov", _NOW,
                                     WarningChange(Status.FIGURES, "That burn cut your warning."))
        html = _note(burn_watch=watch, burn_alert=alert, watch_ends_at=_NOW + timedelta(hours=7))
        live, note = _opening_tag(html, "burn-watch-live"), _opening_tag(html, "burn-watch-note")
        assert 'aria-live="polite"' in live and "hx-" not in live
        assert "aria-live" not in note
        assert html.index(live) < html.index(note)
        if not stopped:
            assert all(attr in note for attr in ('hx-swap="outerHTML"', 'hx-select="#burn-watch-note"',
                                                 'hx-disinherit="*"'))
        else:
            assert "hx-" not in note

    def test_the_sweep_again_button_fills_the_results_and_does_not_replace_them(self) -> None:
        """The button inherited the polled note's outerHTML swap (V0.10 review).

        htmx 1.9 reads hx-swap from the closest ancestor, so one click replaced
        #threat-sweep-results itself, and every later sweep, the main button's
        too, had no target. The button swaps inside the results, as the main
        Sweep Targets button does, and the note passes nothing down.
        """
        watch = _watch(SimpleNamespace(), accounted=None)
        alert = burn_watch.BurnAlert("RED-X", "at 03:12 UTC on 2 Nov", _NOW,
                                     WarningChange(Status.FIGURES, "That burn cut your warning."))
        html = _note(burn_watch=watch, burn_alert=alert, watch_ends_at=_NOW + timedelta(hours=7))
        button = re.search(r'<button[^>]*>Sweep again</button>', html)
        assert button is not None
        assert 'hx-target="#threat-sweep-results"' in button.group(0)
        assert 'hx-swap="innerHTML"' in button.group(0)
        assert 'hx-disinherit="*"' in _opening_tag(html, "burn-watch-note")
