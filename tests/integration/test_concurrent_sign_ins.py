"""Many sign-ins at once, and the work they leave running (SPC-073).

The planning-state store is one dictionary for the whole server, keyed by
sign-in, and three kinds of work outlive the request that started them: the
sampled Decision Engine evaluation (spectre.web.decision_job), the burn watch
(spectre.web.burn_watch) and the sweep's executor steps. Each test here puts
several sign-ins, or several jobs, on that machinery at the same moment and
checks the rules still hold: every sign-in has its own state, a sign-out stops
its work and nobody else's, a newer evaluation replaces a running one, one
sampled evaluation runs at a time on the server, and nothing crosses between
sign-ins.

Nothing here races the clock. Threads are lined up with barriers and events,
work in a worker thread is held at a gate until the test has made the change
it is testing, and the sampled evaluation is the event-driven stand-in from
test_decision_job, so no propagator runs and no network is reached.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.decision import RunControl, Scenario, ScenarioResult, SelectorStrategy
from spectre.web import decision_job, rate_limit
from spectre.web.auth import session_key_for, username_key
from spectre.web.burn_watch import BurnAlert, check_once
from spectre.web.decision_job import (
    NO_JOB,
    DecisionJob,
    JobState,
    cancel_job,
    held_job,
    job_view,
    new_job,
    start_job,
)
from spectre.web.models import SessionKey
from spectre.web.planning_state import _store, clear_account_state, get_session_state, has_session_state
from spectre.web.routes import login, pol, threat
from tests.conftest import csrf_headers
from tests.integration.test_admin_route_outcomes import remove_accounts
from tests.integration.test_all_intercepts_ranking import _BLUE_GEO, _RED_GEO
from tests.integration.test_burn_watch import _BURN_AT, _NOW, _burn, _compute, _no_live_udl, _Udl, _watch
from tests.integration.test_decision_job import _WAIT_S, _Fake, _release_every_fake, _settled, _wait
from tests.integration.test_login_hardening import _admin_cookies, _create_operator, _login
from tests.unit.test_decision_sampled import _scenario

# Imported so they apply here too: every fake is released when its test ends, and no burn-watch stand-in reaches UDL.
__all__ = ["_no_live_udl", "_release_every_fake"]

_ACCOUNTS = {"concurrent_a": "concurrent-a-pass", "concurrent_b": "concurrent-b-pass"}


@pytest.fixture(scope="module")
def accounts(client: Any) -> Iterator[dict[str, str]]:
    """Two operator accounts of this module's own, so signing one out ends nobody else's sessions."""
    admin = _admin_cookies(client)
    page = client.get("/admin/users", cookies=admin).text
    for name, password in _ACCOUNTS.items():
        if f">{name}<" not in page:
            _create_operator(client, admin, name, password)
    client.cookies.clear()
    yield _ACCOUNTS
    remove_accounts(client, tuple(_ACCOUNTS))


def _all_at_once(calls: list[Callable[[], Any]]) -> list[Any]:
    """Run every call on its own thread, released together by a barrier; results in call order."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)
    failures: list[BaseException] = []

    def run(index: int) -> None:
        try:
            barrier.wait(timeout=_WAIT_S)
            results[index] = calls[index]()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the test's thread below
            failures.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not failures, failures
    assert not any(thread.is_alive() for thread in threads), "a concurrent request never finished"
    return results


def _sign_in(client: Any, name: str, password: str) -> str:
    resp = _login(client, name, password)
    assert resp.status_code == 302, f"{name} could not sign in"
    return str(resp.cookies["spectre_session"])


def _key(cookie: str) -> SessionKey:
    key = session_key_for(cookie)
    assert key is not None
    return key


class TestManySignInsAtOnce:
    def test_each_sign_in_gets_its_own_state_and_keeps_its_own_values(
        self, client: Any, accounts: dict[str, str],
    ) -> None:
        """Twelve sign-ins of two accounts, made at once, then twelve writes at once: no value lands in another."""
        client.cookies.clear()
        names = [name for name in accounts for _ in range(6)]
        cookies = _all_at_once([lambda n=name: _sign_in(client, n, accounts[n]) for name in names])
        keys = [_key(cookie) for cookie in cookies]
        assert len(set(keys)) == len(keys), "two sign-ins were given one key"
        owners = {name: {k.user_id for k, n in zip(keys, names, strict=True) if n == name} for name in accounts}
        assert all(len(ids) == 1 for ids in owners.values()) and owners["concurrent_a"] != owners["concurrent_b"]

        def set_window(index: int) -> int:
            session = {"spectre_session": cookies[index]}
            start = f"2026-01-01T{index:02d}:00:00"
            return int(client.post("/scenario/time", data={"scenario_start": start, "scenario_stop": "2026-01-02T00:00:00"},
                                   cookies=session, headers=csrf_headers(session)).status_code)

        assert _all_at_once([lambda i=i: set_window(i) for i in range(len(cookies))]) == [200] * len(cookies)
        states = [get_session_state(key) for key in keys]
        assert len({id(state) for state in states}) == len(states), "two sign-ins share one state"
        assert [state.scenario_start.hour for state in states] == list(range(len(cookies)))
        for key in keys:
            _store.pop(key, None)

    def test_a_sign_out_ends_every_sign_in_of_that_account_and_no_other(
        self, client: Any, accounts: dict[str, str],
    ) -> None:
        client.cookies.clear()
        names = ["concurrent_a"] * 3 + ["concurrent_b"] * 3
        cookies = _all_at_once([lambda n=name: _sign_in(client, n, accounts[n]) for name in names])
        states = {cookie: get_session_state(_key(cookie)) for cookie in cookies}
        for cookie, state in states.items():
            state.udl_username, state.udl_password = "udl-user", f"udl-secret-{cookie[-6:]}"
        client.cookies.clear()
        session = {"spectre_session": cookies[0]}
        assert client.post("/logout", cookies=session, headers=csrf_headers(session),
                           follow_redirects=False).status_code == 302
        for cookie, name in zip(cookies, names, strict=True):
            ended = name == "concurrent_a"
            assert has_session_state(_key(cookie)) is not ended
            assert (states[cookie].udl_password is None) is ended, "a UDL password outlived, or left, the wrong sign-in"
        for cookie in cookies:
            _store.pop(_key(cookie), None)


class TestTheLoginBudgetUnderContention:
    def test_concurrent_failures_cannot_spend_more_than_the_budget(
        self, client: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Four wrong passwords arrive together with two failures left: two are refused at the charge.

        All four are past the up-front check before any is charged, because each
        waits at the barrier inside the password comparison, which comes after
        it. Each charge then checks the budget and records the call with no
        await between the two, on the one loop the TestClient serves every
        request from, so no charge can come between another's check and
        record: exactly the two the budget has room for are counted and the
        other two are refused. The limiter's lock is what would keep that true
        if an await were ever put between them; with none there, this test
        does not exercise the lock, and it passes with the lock removed.
        """
        held = SimpleNamespace(monotonic=lambda: 70_000.0)
        monkeypatch.setattr(rate_limit, "time", held)
        for limiter in (login._LOGIN_ADDRESS_LIMITER, login._LOGIN_USERNAME_LIMITER):
            monkeypatch.setattr(limiter, "_calls", defaultdict(deque))
            monkeypatch.setattr(limiter, "_last_sweep", 70_000.0)
        account = username_key("budget-race")
        for _ in range(8):
            assert asyncio.run(login._LOGIN_USERNAME_LIMITER.is_allowed(account))
        gate = threading.Barrier(4)

        def compared_together(_password: str, _hashed: str) -> bool:
            gate.wait(timeout=_WAIT_S)
            return False

        monkeypatch.setattr(login, "verify_password", compared_together)
        client.cookies.clear()
        statuses = _all_at_once([
            lambda i=i: int(_login(client, "budget-race", "wrong", address=f"198.51.100.{i}").status_code)
            for i in range(4)
        ])
        client.cookies.clear()
        assert sorted(statuses) == [401, 401, 429, 429]
        assert asyncio.run(login._LOGIN_USERNAME_LIMITER.is_blocked(account))


# ── The sampled evaluation jobs ──


class _Metered(_Fake):
    """A fake that says when it starts, on a queue, and counts how many run at once."""

    def __init__(self, meter: _Meter) -> None:
        super().__init__()
        self.meter = meter

    def __call__(self, scenario: Scenario, strategy: SelectorStrategy, *, run: RunControl) -> ScenarioResult:
        with self.meter.lock:
            self.meter.now += 1
            self.meter.most = max(self.meter.most, self.meter.now)
        self.meter.started.put(self)
        try:
            return super().__call__(scenario, strategy, run=run)
        finally:
            with self.meter.lock:
                self.meter.now -= 1


class _Meter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now = self.most = 0
        self.started: queue.Queue[_Metered] = queue.Queue()

    async def next_started(self) -> _Metered:
        return await asyncio.to_thread(self.started.get, True, _WAIT_S)


@pytest.fixture
def meter(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[_Meter, dict[int, _Metered]]]:
    """Each job's evaluation is the fake filed against its own scenario, so a job that never runs takes no fake."""
    gauge = _Meter()
    by_scenario: dict[int, _Metered] = {}

    def dispatch(scenario: Scenario, strategy: SelectorStrategy, *, run: RunControl) -> ScenarioResult:
        return by_scenario[id(scenario)](scenario, strategy, run=run)

    monkeypatch.setattr(decision_job, "evaluate_tree", dispatch)
    yield gauge, by_scenario


def _metered_job(gauge: _Meter, by_scenario: dict[int, _Metered]) -> tuple[DecisionJob, _Metered]:
    job = new_job(_scenario(), SelectorStrategy.MINIMAX)
    fake = by_scenario[id(job.scenario)] = _Metered(gauge)
    return job, fake


@pytest.fixture
def sign_ins() -> Iterator[Callable[[int, int], tuple[SessionKey, Any]]]:
    """Sign-ins of their own, made on demand and removed afterwards."""
    made: list[SessionKey] = []

    def make(user_id: int, index: int) -> tuple[SessionKey, Any]:
        key = SessionKey(user_id=user_id, session_id=f"concurrency-{user_id}-{index}")
        made.append(key)
        return key, get_session_state(key)

    yield make
    for key in made:
        _store.pop(key, None)


def _evaluated(state: Any) -> list[str]:
    return [line for line in state.log_entries if line.startswith("[Decision] Evaluated")]


class TestOneSampledEvaluationAtATime:
    async def test_five_sign_ins_starting_together_run_one_after_another(
        self, meter: Any, sign_ins: Any,
    ) -> None:
        gauge, by_scenario = meter
        owners = [sign_ins(880_100 + i, 0) for i in range(5)]
        jobs = {}
        for key, state in owners:
            job, fake = _metered_job(gauge, by_scenario)
            start_job(state, key, job)
            jobs[fake] = (job, state)
        finished: list[DecisionJob] = []
        for _ in owners:
            fake = await gauge.next_started()
            running, _state = jobs[fake]
            assert running.state is JobState.RUNNING
            waiting = [job for job, _ in jobs.values() if job is not running and job not in finished]
            assert all(job.state is JobState.QUEUED for job in waiting), "a second job left the queue early"
            assert all(job_view(s, j.job_id)["message"].startswith("Waiting for another evaluation")
                       for j, s in jobs.values() if j in waiting)
            fake.release.set()
            await _settled(running)
            finished.append(running)
        assert gauge.most == 1, f"{gauge.most} sampled evaluations ran at once"
        assert all(job.state is JobState.DONE for job in finished)
        assert all(len(_evaluated(state)) == 1 for _, state in owners), "a result was logged to the wrong sign-in"


class TestANewerEvaluationReplacesARunningOne:
    async def test_only_the_newest_of_a_burst_is_evaluated(self, meter: Any, sign_ins: Any) -> None:
        """The first is running; four more arrive. The three in between never sample; the newest is the one kept."""
        gauge, by_scenario = meter
        key, state = sign_ins(880_200, 0)
        burst = [_metered_job(gauge, by_scenario) for _ in range(5)]
        start_job(state, key, burst[0][0])
        first = await gauge.next_started()
        assert first is burst[0][1]
        for job, _ in burst[1:]:
            start_job(state, key, job)
        newest = await gauge.next_started()
        assert newest is burst[-1][1], "a replaced job reached its evaluation"
        newest.release.set()
        for job, _ in burst:
            await _settled(job)
        replaced = [job for job, _ in burst[:-1]]
        assert all(job.state is JobState.STOPPED and job.stopped == "a newer evaluation replaced it" for job in replaced)
        assert not any(fake.started.is_set() for _, fake in burst[1:-1])
        assert burst[-1][0].state is JobState.DONE
        assert all(job_view(state, job.job_id)["message"] == NO_JOB for job in replaced)
        assert len(_evaluated(state)) == 1
        assert gauge.most == 1


class TestASignOutDuringAJob:
    async def test_it_stops_that_accounts_jobs_running_and_queued_and_no_one_elses(
        self, client: Any, accounts: dict[str, str], meter: Any,
    ) -> None:
        """Through the real sign-out route, while the first job is mid-sample on its worker thread."""
        gauge, by_scenario = meter
        client.cookies.clear()
        a1, a2 = (_sign_in(client, "concurrent_a", accounts["concurrent_a"]) for _ in range(2))
        b1 = _sign_in(client, "concurrent_b", accounts["concurrent_b"])
        client.cookies.clear()
        owners = [(_key(c), get_session_state(_key(c))) for c in (a1, a2, b1)]
        started = []
        for key, state in owners:
            job, fake = _metered_job(gauge, by_scenario)
            start_job(state, key, job)
            started.append((job, fake))
        assert await gauge.next_started() is started[0][1]
        session = {"spectre_session": a1}
        client.post("/logout", cookies=session, headers=csrf_headers(session), follow_redirects=False)
        await _settled(started[0][0])
        await _settled(started[1][0])
        b_fake = await gauge.next_started()
        assert b_fake is started[2][1]
        b_fake.release.set()
        await _settled(started[2][0])
        (job_a1, _), (job_a2, fake_a2), (job_b1, _) = started
        assert (job_a1.state, job_a1.stopped) == (JobState.STOPPED, "this sign-in has ended")
        assert (job_a2.state, job_a2.stopped) == (JobState.STOPPED, "this sign-in has ended")
        assert not fake_a2.started.is_set(), "a job of a signed-out account began sampling"
        assert job_b1.state is JobState.DONE
        assert [len(_evaluated(state)) for _, state in owners] == [0, 0, 1]
        _store.pop(owners[2][0], None)


class TestNothingCrossesBetweenSignIns:
    async def test_two_sign_ins_of_one_account_cannot_see_or_stop_each_others_job(
        self, meter: Any, sign_ins: Any,
    ) -> None:
        gauge, by_scenario = meter
        (key_a, state_a), (_, state_b) = sign_ins(880_300, 1), sign_ins(880_300, 2)
        state_a.udl_password, state_b.udl_password = "first-sign-in", "second-sign-in"
        job, fake = _metered_job(gauge, by_scenario)
        start_job(state_a, key_a, job)
        await _wait(fake.started)
        assert held_job(state_b, job.job_id) is None
        assert job_view(state_b, job.job_id)["message"] == NO_JOB
        cancel_job(state_b, job.job_id)
        assert job.state is JobState.RUNNING and not job.cancelled.is_set()
        fake.release.set()
        await _settled(job)
        assert job.state is JobState.DONE
        assert (len(_evaluated(state_a)), len(_evaluated(state_b))) == (1, 0)
        assert state_b.decision_job is None
        assert (state_a.udl_password, state_b.udl_password) == ("first-sign-in", "second-sign-in")


# ── The burn watch's executor step ──


class TestTheBurnWatchAcrossSignIns:
    async def test_a_sign_out_while_checks_are_on_the_executor_stops_only_that_accounts(
        self, monkeypatch: pytest.MonkeyPatch, sign_ins: Any,
    ) -> None:
        """Three checks, two of one account, are held in the executor's analysis; the account signs out meanwhile."""
        _Udl(monkeypatch, [_burn(_BURN_AT, _BURN_AT + timedelta(hours=1))], _NOW - timedelta(minutes=30))
        entered, proceed = threading.Semaphore(0), threading.Event()

        def held_analysis(_pol: Any, _reset: Any = None) -> tuple[Any, None]:
            entered.release()
            assert proceed.wait(_WAIT_S), "the analysis was never released"
            return SimpleNamespace(manoeuvres=[]), None

        monkeypatch.setattr(pol, "history_evidence", held_analysis)
        owners = [sign_ins(880_400, 1), sign_ins(880_400, 2), sign_ins(880_401, 1)]
        for _, state in owners:
            state.udl_username, state.udl_password = "operator", "udl-secret"
        watches = [_watch(state, accounted=_NOW - timedelta(days=3)) for _, state in owners]
        checks = [asyncio.ensure_future(check_once(state, key, watch, _NOW, _compute))
                  for (key, state), watch in zip(owners, watches, strict=True)]
        for _ in checks:
            assert await asyncio.to_thread(entered.acquire, True, _WAIT_S), "a check never reached the executor"
        clear_account_state(880_400)
        proceed.set()
        results = await asyncio.wait_for(asyncio.gather(*checks), timeout=_WAIT_S)
        assert results[0] is None and results[1] is None
        assert isinstance(results[2], BurnAlert)
        assert [state.burn_alert is not None for _, state in owners] == [False, False, True]
        assert [sum("[BURN]" in line for line in state.log_entries) for _, state in owners] == [0, 0, 1]


# ── The sweep's executor step ──


class TestTheSweepsClusteringAgainstAConcurrentFetch:
    async def test_a_target_fetch_during_the_clustering_does_not_cost_the_sweep_its_reduction(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The sweep clusters on the executor while, on the loop, a target fetch for the same sign-in refills the set.

        The fetch clears the multi-provider set and writes the new group's
        histories into it. The clustering, mid-way through the old set on its
        worker thread, must finish what it started rather than fail and leave
        the sweep unreduced with only a warning in the log.
        """
        import tle_clustering

        state = SimpleNamespace(
            hrr_tle_multiset={"90002": [_BLUE_GEO, _BLUE_GEO], "90003": [_RED_GEO, _RED_GEO]},
            hrr_tle_cache={"90002": _BLUE_GEO, "90003": _RED_GEO},
        )
        inside, proceed = threading.Event(), threading.Event()
        real = tle_clustering.cluster_tle_strings

        def held_on_the_first_object(lines: list[str], config: Any) -> Any:
            if not inside.is_set():
                inside.set()
                assert proceed.wait(_WAIT_S), "the clustering was never released"
            return real(lines, config)

        monkeypatch.setattr(tle_clustering, "cluster_tle_strings", held_on_the_first_object)
        reducing = asyncio.ensure_future(threat._reduce_tle_clusters(state))
        assert await asyncio.to_thread(inside.wait, _WAIT_S)
        state.hrr_tle_multiset.clear()
        state.hrr_tle_multiset["90004"] = [_BLUE_GEO, _BLUE_GEO]
        proceed.set()
        summary = await asyncio.wait_for(reducing, timeout=_WAIT_S)
        assert summary is not None, "the clustering failed when the set changed under it"
        assert sorted(o.satno for o in summary.objects) == ["90002", "90003"]

    async def test_a_target_fetch_during_the_clustering_keeps_the_element_set_it_fetched(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A fetch that lands while the clustering runs wrote the newer element set; the clustering must not undo it.

        The clustering works on a copy of the old history. Its representative
        for an object the fetch has since refreshed is a representative of the
        superseded history, so the fetch's entry stands. An entry the fetch
        did not touch still takes the clustering's representative.
        """
        import tle_clustering
        from spectre.astro.tle_preprocessing import cluster_and_reduce_tle_cache
        from spectre.config.constants import TLE_CLUSTERING

        state = SimpleNamespace(
            hrr_tle_multiset={"90002": [_BLUE_GEO, _BLUE_GEO], "90003": [_RED_GEO, _RED_GEO]},
            hrr_tle_cache={"90002": "cached-90002", "90003": "cached-90003"},
        )
        representative = cluster_and_reduce_tle_cache(
            {"90003": [_RED_GEO, _RED_GEO]}, {"90003": "cached-90003"}, TLE_CLUSTERING,
        )[0]["90003"]
        assert representative != "cached-90003"
        inside, proceed = threading.Event(), threading.Event()
        real = tle_clustering.cluster_tle_strings

        def held_on_the_first_object(lines: list[str], config: Any) -> Any:
            if not inside.is_set():
                inside.set()
                assert proceed.wait(_WAIT_S), "the clustering was never released"
            return real(lines, config)

        monkeypatch.setattr(tle_clustering, "cluster_tle_strings", held_on_the_first_object)
        reducing = asyncio.ensure_future(threat._reduce_tle_clusters(state))
        assert await asyncio.to_thread(inside.wait, _WAIT_S)
        # What fetch_targets and _fetch_one do for the same sign-in, on the loop.
        state.hrr_tle_multiset.clear()
        state.hrr_tle_cache["90002"] = "fetched-during-clustering"
        proceed.set()
        summary = await asyncio.wait_for(reducing, timeout=_WAIT_S)
        assert summary is not None
        assert state.hrr_tle_cache["90002"] == "fetched-during-clustering"
        assert state.hrr_tle_cache["90003"] == representative

