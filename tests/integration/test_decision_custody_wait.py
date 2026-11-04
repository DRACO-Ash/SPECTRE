"""While a bound evaluation waits on a first UDL history fetch for custody, the page says so (SPC-119).

A bound red track's custody is read from its element-set history, waiting up
to 20 s for a first fetch, as the sweep waits (SPC-123). That wait used to
happen on the request, so the page showed only "Evaluating" for up to 20 s
and could not say why. When a first fetch is needed, the evaluation now runs
as the session's job from the start: its first stage reads custody, and its
progress says it is waiting for the history, for how long at most, and what
happens if it does not arrive. A history already held, or UDL not connected,
needs no wait, and the evaluation goes on as before.

Every fetch is stood in with a fake that waits on a threading event, so no
test reaches the network or depends on the wall clock.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import BoundElset, Scenario, ScenarioBinding, SelectorStrategy, evaluate_scenario
from spectre.web import decision_custody, decision_job
from spectre.web.decision_job import DecisionJob, JobState, cancel_job, job_view, new_job, run_job
from spectre.web.models import SessionKey
from spectre.web.planning_state import _store, get_session_state
from spectre.web.routes import decision as decision_routes
from spectre.web.routes.pol import HeldHistory
from tests.integration.conftest import session_state
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.unit.test_decision_sampled import _scenario
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
_SATNO = 50322
_WAIT_S = 5.0
_WAITING = (
    "Reading custody: waiting up to 20 s for RX's element-set history, a first fetch from UDL, so its custody is "
    "judged as the sweep judges it. The evaluation starts when the history arrives or the wait ends; if it has not "
    "arrived by then, custody reads degraded, which counts as lost, and the next evaluation uses it."
)
_HELD = CustodyStatus(Custody.HELD, "Custody held.")


def _red() -> BoundElset:
    epoch = _NOW - timedelta(hours=5)
    return BoundElset(side="red", name="RX", stk_name="RX", satno=_SATNO, tle=_tle(epoch, satno=_SATNO),
                      data_mode="REAL", epoch=epoch, age_hours=5.0, limit_hours=72.0)


def _bound() -> Scenario:
    return dataclasses.replace(_scenario(), epoch_utc=_NOW, binding=ScenarioBinding(red=_red()))


_REFETCHING = _WAITING.replace(
    "a first fetch from UDL,", "a fresh fetch from UDL, as the copy held is 30 min old or more,",
)


class TestWhenAFirstFetchIsNeeded:
    def _state(self, **kw: Any) -> Any:
        return SimpleNamespace(**{"udl_username": "u", "udl_password": "p", "elset_histories": {}, **kw})

    def test_udl_connected_with_no_history_held_needs_one(self) -> None:
        assert decision_custody.history_fetch(self._state(), _red(), _NOW)

    def test_a_fresh_held_history_needs_none(self) -> None:
        state = self._state()
        state.elset_histories[_SATNO] = HeldHistory(_SATNO, _NOW - timedelta(minutes=5), pol=object())
        assert not decision_custody.history_fetch(state, _red(), _NOW)

    def test_a_held_history_past_its_age_needs_another(self) -> None:
        state = self._state()
        state.elset_histories[_SATNO] = HeldHistory(_SATNO, _NOW - timedelta(hours=2), pol=object())
        assert decision_custody.history_fetch(state, _red(), _NOW)

    def test_it_says_whether_the_fetch_is_a_first_one_or_a_fresh_one(self) -> None:
        """A held copy past its age is fetched again, not for the first time, and the progress says which."""
        state = self._state()
        assert decision_custody.history_fetch(state, _red(), _NOW) == decision_custody.FIRST_FETCH == (
            "a first fetch from UDL"
        )
        state.elset_histories[_SATNO] = HeldHistory(_SATNO, _NOW - timedelta(hours=2), pol=object())
        assert decision_custody.history_fetch(state, _red(), _NOW) == decision_custody.REFETCH == (
            "a fresh fetch from UDL, as the copy held is 30 min old or more"
        )

    @pytest.mark.parametrize(("age", "fetch"), [
        (timedelta(minutes=29, seconds=59), ""), (timedelta(minutes=30), "a fresh fetch from UDL, as the copy held "
                                                                         "is 30 min old or more"),
    ], ids=["just under 30 min", "exactly 30 min"])
    def test_a_held_copy_is_fetched_again_from_30_min_old_as_held_history_does(self, age: timedelta,
                                                                              fetch: str) -> None:
        state = self._state()
        state.elset_histories[_SATNO] = HeldHistory(_SATNO, _NOW - age, pol=object())
        assert decision_custody.history_fetch(state, _red(), _NOW) == fetch

    def test_udl_not_connected_or_no_catalogue_number_needs_none(self) -> None:
        assert not decision_custody.history_fetch(self._state(udl_password=""), _red(), _NOW)
        assert not decision_custody.history_fetch(
            SimpleNamespace(udl_username="", udl_password="", elset_histories={}), _red(), _NOW)
        assert not decision_custody.history_fetch(self._state(), dataclasses.replace(_red(), satno=None), _NOW)


@pytest.fixture(autouse=True)
def _server_running() -> None:
    """A test client that closed earlier in the run leaves the shutdown stop set; a running server has it clear."""
    decision_job.server_starting()


@pytest.fixture
def owner() -> Iterator[tuple[SessionKey, Any]]:
    key = SessionKey(user_id=876_601, session_id="decision-custody-wait")
    yield key, get_session_state(key)
    _store.pop(key, None)


class _Gate:
    """A custody read that waits until released, polling a threading event, so a failing test never hangs."""

    def __init__(self, *, fail: bool = False) -> None:
        self.release, self.fail, self.calls = threading.Event(), fail, 0

    async def __call__(self, scenario: Scenario) -> Scenario:
        self.calls += 1
        for _ in range(int(_WAIT_S / 0.005)):
            if self.release.is_set():
                break
            await asyncio.sleep(0.005)
        if self.fail:
            raise RuntimeError("secret detail that must never reach the page")
        binding = scenario.binding
        assert binding is not None
        return dataclasses.replace(scenario, binding=decision_custody.with_red_custody(binding, _HELD))


def _custody_job(gate: _Gate, fetch: str = decision_custody.FIRST_FETCH) -> DecisionJob:
    return new_job(_bound(), SelectorStrategy.MINIMAX, custody=decision_job.CustodyRead(gate, 20.0, fetch))


async def _settled(job: DecisionJob) -> None:
    assert job.task is not None
    await asyncio.wait_for(asyncio.shield(job.task), timeout=_WAIT_S)


class TestTheJobSaysItWaits:
    async def test_while_custody_is_read_the_progress_says_why_it_waits(self, owner: Any) -> None:
        key, state = owner
        gate = _Gate()
        job = _custody_job(gate)
        decision_job.start_job(state, key, job)
        view = job_view(state, job.job_id)
        assert job.state is JobState.CUSTODY
        assert view["message"] == _WAITING
        assert view["polling"] is True
        gate.release.set()
        await _settled(job)
        assert job.state is JobState.DONE
        assert job.result is not None
        red = job.result.scenario.binding.red
        assert red is not None and red.custody is _HELD

    async def test_refetching_a_held_copy_past_its_age_says_so(self, owner: Any) -> None:
        key, state = owner
        gate = _Gate()
        job = _custody_job(gate, decision_custody.REFETCH)
        decision_job.start_job(state, key, job)
        assert job_view(state, job.job_id)["message"] == _REFETCHING
        gate.release.set()
        await _settled(job)

    async def test_replaced_while_reading_custody_nothing_is_evaluated(
        self, owner: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A newer evaluation took its place during the read: the job stops there and evaluates nothing."""
        key, state = owner
        gate = _Gate()
        seen: list[Any] = []
        monkeypatch.setattr(decision_job, "evaluate_scenario", lambda *a, **kw: seen.append(a))
        monkeypatch.setattr(decision_job, "needs_a_run", lambda _s: False)
        job = _custody_job(gate)
        decision_job.start_job(state, key, job)
        await asyncio.sleep(0)
        state.decision_job = _custody_job(_Gate())
        gate.release.set()
        await _settled(job)
        assert (job.state, job.stopped, job.result, seen) == (
            JobState.STOPPED, "a newer evaluation replaced it", None, [],
        )

    async def test_a_lookup_scenario_evaluates_after_the_read_without_the_sampling_slot(
        self, owner: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key, state = owner
        gate = _Gate()
        gate.release.set()
        seen: list[Any] = []

        def evaluate(scenario: Scenario, strategy: SelectorStrategy, **kw: Any) -> Any:
            seen.append(kw)
            return evaluate_scenario(scenario, strategy)

        monkeypatch.setattr(decision_job, "evaluate_scenario", evaluate)
        monkeypatch.setattr(decision_job, "needs_a_run", lambda _s: False)
        job = _custody_job(gate)
        state.decision_job = job
        async with decision_job._slot():   # another evaluation holds the slot: this one must not wait for it
            await asyncio.wait_for(run_job(state, key, job), timeout=_WAIT_S)
        assert job.state is JobState.DONE
        assert seen == [{}]

    async def test_a_scenario_that_samples_goes_on_to_the_slot_under_its_budget(
        self, owner: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key, state = owner
        gate = _Gate()
        gate.release.set()
        seen: list[Any] = []

        def evaluate(scenario: Scenario, strategy: SelectorStrategy, **kw: Any) -> Any:
            seen.append(kw)
            return evaluate_scenario(scenario, strategy)

        monkeypatch.setattr(decision_job, "evaluate_scenario", evaluate)
        monkeypatch.setattr(decision_job, "needs_a_run", lambda _s: True)
        job = _custody_job(gate)
        state.decision_job = job
        await asyncio.wait_for(run_job(state, key, job), timeout=_WAIT_S)
        assert job.state is JobState.DONE
        assert [set(kw) for kw in seen] == [{"run"}]

    async def test_cancelled_while_reading_custody_nothing_is_scored(self, owner: Any) -> None:
        key, state = owner
        gate = _Gate()
        job = _custody_job(gate)
        decision_job.start_job(state, key, job)
        await asyncio.sleep(0)
        cancel_job(state, job.job_id)
        gate.release.set()
        await _settled(job)
        assert (job.state, job.stopped, job.result) == (JobState.STOPPED, "you cancelled it", None)

    async def test_a_failed_read_fails_the_job_with_no_detail_on_the_page(self, owner: Any) -> None:
        key, state = owner
        gate = _Gate(fail=True)
        gate.release.set()
        job = _custody_job(gate)
        decision_job.start_job(state, key, job)
        await _settled(job)
        assert job.state is JobState.FAILED
        assert "secret" not in job_view(state, job.job_id)["message"]


@pytest.fixture
def connected(auth_cookie: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, threading.Event]]:
    """UDL connected with no history held, and a first fetch that waits until released."""
    from spectre.domain.models import RedTrack

    state = session_state(auth_cookie)
    saved = (list(state.red_tracks), state.udl_username, state.udl_password, dict(state.elset_histories))
    release = threading.Event()

    async def fetch(_state: Any, satno: int, now: datetime) -> HeldHistory:
        for _ in range(int(_WAIT_S / 0.005)):
            if release.is_set():
                break
            await asyncio.sleep(0.005)
        return HeldHistory(satno, now, problem="UDL returned no element sets for this object.")

    monkeypatch.setattr(decision_routes, "_utc_now", lambda: _NOW)
    monkeypatch.setattr(decision_custody, "held_history", fetch)
    state.red_tracks = [RedTrack("RX", _red().tle, data_mode="REAL")]
    state.udl_username, state.udl_password, state.elset_histories = "u", "p", {}
    yield state, release
    release.set()
    state.red_tracks, state.udl_username, state.udl_password = saved[:3]
    state.elset_histories = saved[3]


def test_a_bound_evaluation_refetching_a_stale_history_says_it_is_a_fresh_fetch(
    client: Any, auth_cookie: str, connected: tuple[Any, threading.Event],
) -> None:
    state, release = connected
    state.elset_histories = {_SATNO: HeldHistory(_SATNO, _NOW - timedelta(hours=1), pol=object())}
    resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
    assert resp.status_code == 200
    assert _REFETCHING.replace("'", "&#39;") in " ".join(resp.text.split())
    release.set()


def test_a_bound_evaluation_waiting_on_a_first_fetch_answers_with_the_job_at_once(
    client: Any, auth_cookie: str, connected: tuple[Any, threading.Event],
) -> None:
    state, release = connected
    resp = _evaluate(client, auth_cookie, _form(red_sat="RX"))
    assert resp.status_code == 200
    text = " ".join(resp.text.split())
    assert _WAITING.replace("'", "&#39;") in text
    assert 'hx-trigger="every 2s"' in text
    assert "Heuristic ranking" not in text
    job = state.decision_job
    assert isinstance(job, DecisionJob) and job.state is JobState.CUSTODY
    release.set()
