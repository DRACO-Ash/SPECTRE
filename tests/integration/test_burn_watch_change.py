"""What the watch says a burn changed, and how a sweep starts the watch (SPC-006).

test_burn_watch pins the watch's rules with a stand-in computation. These run
the real one, threat._watch_change, on a held history built from element sets,
with only the probe, the UDL fetch and the sweep runner stood in, so the
selection, the custody refusal and which orbit is before and which after are
tested as the operator would read them. The last class pins what
threat._watch_after_sweep hands the watch when a sweep starts it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.astro.pattern_of_life import ParseCounts
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.models import ThreatTarget
from spectre.domain.warning_change import Change, Status, WarningChange
from spectre.web import burn_watch
from spectre.web.burn_watch import CHECK_EVERY, BurnWatch, check_once
from spectre.web.models import SessionKey
from spectre.web.planning_state import _store, get_session_state
from spectre.web.routes import pol, threat, udl
from tests.integration.test_sweep_burn_differential import (
    _BUDGET,
    _RECENT_RAISE,
    _ROUTINE,
    _confirmed,
    _events_history,
    _spy,
    _target_tle,
)

_SATNO = 90010


@pytest.fixture(autouse=True)
def _no_live_udl(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test here may reach UDL: the probe and the history fetch are stood in per test."""
    calls: list[Any] = []

    async def refuse(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(udl, "fetch_tle_for_satno", refuse)
    yield
    assert calls == [], "a watch-change test reached UDL"


@pytest.fixture
def owner() -> Iterator[tuple[SessionKey, Any]]:
    """A sign-in of its own, with UDL connected, removed afterwards."""
    key = SessionKey(user_id=987_655, session_id="burn-watch-change-test")
    state = get_session_state(key)
    state.udl_username, state.udl_password = "operator", "udl-secret"
    yield key, state
    _store.pop(key, None)


def _hold(monkeypatch: pytest.MonkeyPatch, records: list[Any]) -> None:
    """UDL's history for the object is *records*, and its newest set is the last of them."""

    async def merged(*_a: Any, **_k: Any) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        return "held", "held", {}, {}, "RED-LEO"

    async def probe(_state: Any, _watch: Any) -> datetime:
        return records[-1].epoch

    monkeypatch.setattr(pol, "_fetch_merged_history", merged)
    monkeypatch.setattr(pol, "parse_tle_history_counted", lambda *_a, **_k: (records, ParseCounts()))
    monkeypatch.setattr(burn_watch, "_probe", probe)


def _watch(state: Any, now: datetime, accounted: datetime | None) -> BurnWatch:
    watch = BurnWatch(red_name="RED-LEO", red_satno=_SATNO, red_regime="LEO",
                      targets=[ThreatTarget("BLUE-LEO", "", "manual", None)],
                      manual_tle_by_name={"BLUE-LEO": _target_tle()}, max_dv_m_s=_BUDGET,
                      accounted_until=accounted, started_at=now - timedelta(hours=1), next_check_at=now)
    state.burn_watch = watch
    return watch


class TestWhatTheBurnChanged:
    async def test_a_burn_in_custody_is_flown_before_and_after(self, owner: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
        """Before is the set from before the burn, after the newest held set: 14h cut to 3h (V0.9 review 19, 20).

        Every watch test used a stand-in computation, so swapping before and after
        in the real one, announcing this cut as a lengthening, stayed green.
        """
        key, state = owner
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = records[-1].epoch + timedelta(hours=1)
        _hold(monkeypatch, records)
        calls = _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        watch = _watch(state, now, accounted=burn.tle_before.epoch)
        alert = await check_once(state, key, watch, now, threat._watch_change)
        assert alert is not None
        change = alert.change
        assert change.status is Status.FIGURES
        assert change.headline.startswith("That burn cut the warning on BLUE-LEO from 14h to 3h.")
        assert [(r.name, r.before_h, r.after_h, r.change) for r in change.rows] == [("BLUE-LEO", 14.0, 3.0, Change.CUT)]
        assert [c["red_tle"] for c in calls] == [records[-1].tle, burn.tle_before.tle]
        assert watch.accounted_until == burn.tle_after.epoch

    async def test_the_object_is_named_by_its_own_catalogue_number(self, owner: Any,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        """The NOTSO cue is read for the watched object's number, as text, as the sweep reads it."""
        from spectre.data import notso_cache

        key, state = owner
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = records[-1].epoch + timedelta(hours=1)
        _hold(monkeypatch, records)
        _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        asked: list[Any] = []
        monkeypatch.setattr(notso_cache, "get_notso_cache", lambda: SimpleNamespace(
            get_for_satno=lambda satno: asked.append(satno) or [], last_sync_utc=lambda: None))
        await check_once(state, key, _watch(state, now, accounted=burn.tle_before.epoch), now, threat._watch_change)
        assert asked == [str(_SATNO)]

    async def test_custody_lost_gives_no_figures(self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A newest set older than LEO's 24-hour limit: the refusal, and nothing is flown."""
        _, state = owner
        records = _events_history(_RECENT_RAISE)
        burn = _confirmed(records)[-1]
        now = records[-1].epoch + timedelta(days=4)
        _hold(monkeypatch, records)
        calls = _spy(monkeypatch, {burn.tle_before.tle: 14.0, records[-1].tle: 3.0})
        held = await pol.held_history(state, _SATNO, now)
        assessment, _ = pol.history_evidence(held.pol)
        change = await threat._watch_change(state, _watch(state, now, accounted=None), (held.pol, assessment, [burn]),
                                            now)
        assert change.status is Status.NOT_COMPUTED
        assert change.headline == ("What the burn changed is not shown: custody is lost, so any figure would rest "
                                   "on an out-of-date orbit.")
        assert calls == []

    async def test_a_pre_burn_set_too_old_to_fly_gives_the_selection_refusal(
            self, owner: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """30 hours between the last set and the burn, against LEO's 24-hour limit."""
        key, state = owner
        records = _events_history([*_ROUTINE, (40, 150.0, 30 / 24)], tail_sets=1)
        now = records[-1].epoch + timedelta(hours=1)
        _hold(monkeypatch, records)
        calls = _spy(monkeypatch, {records[-1].tle: 3.0})
        alert = await check_once(state, key, _watch(state, now, accounted=None), now, threat._watch_change)
        assert alert is not None
        assert alert.change.status is Status.NOT_COMPUTED
        assert alert.change.headline.startswith("That burn's warning change is not computed: its last element set "
                                                "before the burn is")
        assert alert.change.headline.endswith("old against a 24 h limit, too old to fly to now.")
        assert calls == []

    @pytest.mark.parametrize("sets_between", [1, 2])
    async def test_a_new_burn_is_flown_from_its_own_pre_burn_set(self, owner: Any, monkeypatch: pytest.MonkeyPatch,
                                                                 sets_between: int) -> None:
        """The burn already announced is not flown again, worded again or allowed to refuse the new one.

        The watch reselected every burn in the window, so a second burn was flown
        from before the first and worded "Those 2 burns" (1 set between) or refused
        because the first burn's pre-burn set was 25 h old (2 sets) (V0.9 review 11).
        """
        key, state = owner
        records = _events_history([*_RECENT_RAISE, (sets_between, 25.0, None)])
        first, second = _confirmed(records)[-2:]
        now = records[-1].epoch + timedelta(hours=1)
        _hold(monkeypatch, records)
        calls = _spy(monkeypatch, {first.tle_before.tle: 20.0, second.tle_before.tle: 14.0, records[-1].tle: 3.0})
        alert = await check_once(state, key, _watch(state, now, accounted=first.tle_after.epoch), now,
                                 threat._watch_change)
        assert alert is not None
        assert alert.change.status is Status.FIGURES
        assert alert.change.headline.startswith("That burn cut the warning on BLUE-LEO from 14h to 3h.")
        assert len(alert.change.burns) == 1
        assert [c["red_tle"] for c in calls] == [records[-1].tle, second.tle_before.tle]


def _basis(now: datetime) -> Any:
    return threat._SweepBasis(targets=[ThreatTarget("BLUE-LEO", "", "manual", None)],
                              manual_tle_by_name={"BLUE-LEO": "manual set"}, frozen=threat._FrozenTargets({}),
                              red_regime="LEO", max_dv_m_s=_BUDGET, blue_satnos=frozenset(), now=now)


def _history(newest: datetime | None, afters: list[datetime]) -> Any:
    """A held history whose burns each happened an hour before the post-burn set in *afters*."""
    if newest is None:
        return threat._RedHistory(None, None, None, "Its element-set history is still loading from UDL.", None)
    burns = [SimpleNamespace(burn_window=(a - timedelta(hours=1), a - timedelta(hours=1)),
                             burn_epoch=a - timedelta(hours=1), tle_after=SimpleNamespace(epoch=a)) for a in afters]
    held = SimpleNamespace(manoeuvres=burns, candidate_manoeuvres=[], records=[SimpleNamespace(epoch=newest)])
    return threat._RedHistory(held, None, None, "", newest)


_HELD = CustodyStatus(Custody.HELD, "Custody held.")
_LOST = CustodyStatus(Custody.LOST, "Custody lost.")


class TestASweepStartsTheWatch:
    """V0.9 review 21: the sweep tests replaced start_watch and never read what it was given."""

    _NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)

    @pytest.fixture
    def started(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
        recorded: list[tuple[Any, ...]] = []
        monkeypatch.setattr(threat, "start_watch", lambda *a, **k: recorded.append((*a, k)))
        return recorded

    def _sweep_ends(self, udl_username: str | None, history: Any, *, satno: str | None = "90010",
                    session_key: Any = "sign-in", flown: tuple[CustodyStatus, datetime] | None = None,
                    ) -> tuple[Any, Any]:
        """The sweep ends; by default custody is held and it flew the history's newest set."""
        state = SimpleNamespace(udl_username=udl_username)
        user = SimpleNamespace(session_key=session_key)
        newest = history.pol.records[-1].epoch if history.pol is not None else None
        threat._watch_after_sweep(state, user, _basis(self._NOW), ("RED-LEO", satno), history=history,
                                  history_task=None, flown=flown or (_HELD, newest))
        return state, user

    def test_the_burns_the_sweep_showed_are_accounted_for(self, started: list[Any]) -> None:
        """The first check must not announce again the burns the sweep has just shown (W3)."""
        afters = [self._NOW - timedelta(hours=30), self._NOW - timedelta(hours=5)]
        state, _ = self._sweep_ends("operator", _history(self._NOW - timedelta(hours=2), afters))
        (owner_state, key, watch, kwargs), = started
        assert (owner_state, key) == (state, "sign-in")
        assert watch.accounted_until == self._NOW - timedelta(hours=5)
        assert watch.newest_epoch == self._NOW - timedelta(hours=2)
        assert watch.next_check_at == self._NOW + CHECK_EVERY
        assert (watch.red_name, watch.red_satno, watch.red_regime) == ("RED-LEO", 90010, "LEO")
        assert watch.manual_tle_by_name == {"BLUE-LEO": "manual set"}
        assert kwargs["compute"] is threat._watch_change

    def test_with_the_history_still_loading_the_first_check_runs_at_once(self, started: list[Any]) -> None:
        """Nothing is accounted for, so the first check announces any burn in the window, and it does not wait."""
        self._sweep_ends("operator", _history(None, []))
        (_, _, watch, _), = started
        assert watch.accounted_until is None and watch.newest_epoch is None
        assert watch.next_check_at == self._NOW

    def test_a_burn_refused_for_custody_lost_stays_announceable(self, started: list[Any]) -> None:
        """The sweep gave no figures, so the burn was never told: the first check runs at once (V0.9 review 13).

        The watch was told the burn was accounted for and the newest set seen, so
        it never announced the burn the sweep had refused to give figures for.
        """
        burn_after = self._NOW - timedelta(hours=5)
        self._sweep_ends("operator", _history(self._NOW - timedelta(hours=1), [burn_after]),
                         flown=(_LOST, self._NOW - timedelta(hours=30)))
        (_, _, watch, _), = started
        assert (watch.accounted_until, watch.newest_epoch, watch.next_check_at) == (None, None, self._NOW)

    def test_a_burn_after_the_set_the_sweep_flew_stays_announceable(self, started: list[Any]) -> None:
        """The flown set predates the second burn: only the first is in its figures, so only it is accounted."""
        afters = [self._NOW - timedelta(hours=20), self._NOW - timedelta(hours=5)]
        self._sweep_ends("operator", _history(self._NOW - timedelta(hours=1), afters),
                         flown=(_HELD, self._NOW - timedelta(hours=8)))
        (_, _, watch, _), = started
        assert (watch.accounted_until, watch.newest_epoch, watch.next_check_at) == (afters[0], None, self._NOW)

    def test_an_undated_burn_whose_pre_burn_set_was_flown_stays_announceable(self, started: list[Any]) -> None:
        """Flying the set at the start of an undated burn's bracket is not flying a set from after the burn.

        The sweep refuses figures for a set before the end of the bracket, so
        the burn was never told, and the watch must still announce it.
        """
        after = self._NOW - timedelta(hours=2)
        start, end = after - timedelta(hours=8), after - timedelta(hours=1)
        undated = SimpleNamespace(burn_window=(start, end), burn_epoch=None, tle_after=SimpleNamespace(epoch=after))
        newest = self._NOW - timedelta(hours=1)
        held = SimpleNamespace(manoeuvres=[undated], candidate_manoeuvres=[], records=[SimpleNamespace(epoch=newest)])
        self._sweep_ends("operator", threat._RedHistory(held, None, None, "", newest), flown=(_HELD, start))
        (_, _, watch, _), = started
        assert (watch.accounted_until, watch.newest_epoch, watch.next_check_at) == (None, None, self._NOW)

    async def test_the_first_check_then_announces_it(self, owner: Any, started: list[Any],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """The watch the custody-lost sweep started announces the burn when UDL holds nothing newer."""
        key, state = owner
        history = _history(self._NOW - timedelta(hours=1), [self._NOW - timedelta(hours=5)])
        state.elset_histories[_SATNO] = pol.HeldHistory(_SATNO, self._NOW, pol=history.pol)
        monkeypatch.setattr(threat, "_utc_now", lambda: self._NOW)
        monkeypatch.setattr(pol, "history_evidence", lambda *_a: (SimpleNamespace(manoeuvres=[]), None))

        async def probe(_state: Any, _watch: Any) -> datetime:
            return history.pol.records[-1].epoch

        async def compute(*_a: Any) -> Any:
            return WarningChange(Status.FIGURES, "That burn cut the warning on BLUE-LEO from 14h to 3h.")

        monkeypatch.setattr(burn_watch, "_probe", probe)
        threat._watch_after_sweep(state, SimpleNamespace(session_key=key), _basis(self._NOW), ("RED-LEO", str(_SATNO)),
                                  history=history, history_task=None, flown=(_LOST, self._NOW - timedelta(hours=30)))
        (_, _, watch, _), = started
        state.burn_watch = watch
        alert = await check_once(state, key, watch, watch.next_check_at, compute)
        assert alert is not None and alert.burn_when == "at 04:00 UTC on 2 Nov"
        assert alert.change.headline == "That burn cut the warning on BLUE-LEO from 14h to 3h."

    @pytest.mark.parametrize(("udl_username", "satno", "session_key"), [
        (None, "90010", "sign-in"), ("", "90010", "sign-in"), ("operator", None, "sign-in"), ("operator", "90010", None),
    ])
    def test_no_watch_without_udl_a_catalogue_number_or_a_sign_in(
            self, started: list[Any], udl_username: str | None, satno: str | None, session_key: Any) -> None:
        self._sweep_ends(udl_username, _history(self._NOW, [self._NOW - timedelta(hours=5)]), satno=satno,
                         session_key=session_key)
        assert started == []
