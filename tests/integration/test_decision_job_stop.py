"""A job writing its decision record when the server stops finishes the write, and leaves the database free (SPC-242).

Found as a test-order fault: some groupings of the suite failed every test in test_decision_record_route.py with
"database is locked". test_decision_custody_wait.py's last test starts a job through the route and returns; the
job reads custody, evaluates and writes its record while the module's TestClient closes. The lifespan's end set the
shutdown stop and returned without waiting for the jobs it held, so the event loop's own shutdown cancelled the job
in the middle of its record's transaction. Cancelled inside a statement that still had a row not yet fetched,
SQLAlchemy closes the aiosqlite connection, but the statement's cursor is still held by the CancelledError's
traceback, which the cancelled task keeps, which the job keeps, which the sign-in's planning state keeps. On Python
3.11 and later SQLite then keeps that connection open, with its write transaction and its lock, until the cursor
goes. Every later write in the run failed.

A job whose record is being written is meant to finish it (decision_job._finish): its record stands, and only its
results are not held. So the lifespan's end now waits, up to STOP_WAIT_S, for the jobs that are sampling or writing
a record. A job still reading custody or queued for the sampling slot holds no database connection and is cancelled
with the loop at once, as before.

The record tests hold the record's write open until the server begins to stop, and then until the stop either
cancels the write, which it did within milliseconds before the fix, or leaves it to finish.
"""

from __future__ import annotations

import asyncio
import dataclasses
import gc
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from spectre import __version__
from spectre.domain.decision import (
    EvaluationStoppedError,
    RunControl,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.web import database, decision_job, decision_record
from spectre.web.auth import session_key_for
from spectre.web.decision_job import CustodyRead, DecisionJob, JobState, new_job, start_job
from spectre.web.decision_record import Operator, write_record
from spectre.web.models import DecisionRecord, SessionKey
from spectre.web.planning_state import _store, get_session_state
from tests.integration.conftest import login_as, session_state
from tests.integration.test_login_hardening import _ADMIN, _ADMIN_PASSWORD
from tests.unit.test_decision_sampled import _scenario

_WAIT_S = 5.0
#: How long a held write waits, once the stop has begun, for the stop to cancel it. Before the fix the cancel came
#: within milliseconds of the stop; with it no cancel comes, and the write goes on once this has passed.
_CANCEL_WINDOW_S = 1.0
_POLL_S = 0.005
#: How much longer than the bound a stop may take: the lifespan's other steps and the test client's own close.
_STOP_MARGIN_S = 2.0
_ON_SQLITE = os.environ.get("DATABASE_URL", "").startswith("sqlite")


def _unique(name: str) -> str:
    """*name* made unique to this run, so a record count holds on a database an earlier run left records in."""
    return f"{name} {uuid.uuid4().hex[:12]}"


class _HeldWrite:
    """Holds a decision record's write, flushed and not committed, until the server stops and then until either the
    stop cancels it or the window for that has passed."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.job: DecisionJob | None = None

    def _cancelled(self) -> bool:
        task = None if self.job is None else self.job.task
        return task is not None and task.cancelling() > 0

    def wait_for_the_stop(self) -> None:
        """Block this thread until the server stops and then until the stop cancels the job or the window passes."""
        self.entered.set()
        decision_job._SHUTTING_DOWN.wait(_WAIT_S)
        pause = threading.Event()
        for _ in range(int(_CANCEL_WINDOW_S / _POLL_S)):
            if self._cancelled():
                return
            pause.wait(_POLL_S)

    async def between_statements(self, db: AsyncSession) -> None:
        """Hold between the record's insert and the check that its account exists, on the event loop."""
        self.entered.set()
        while not decision_job._SHUTTING_DOWN.is_set():
            await asyncio.sleep(_POLL_S)
        for _ in range(int(_CANCEL_WINDOW_S / _POLL_S)):
            if self._cancelled():
                break
            await asyncio.sleep(_POLL_S)

    async def inside_a_statement(self, db: AsyncSession) -> None:
        """Hold inside a statement: the database's worker thread runs a function that waits for the stop."""
        connection = await (await db.connection()).get_raw_connection()
        await connection.driver_connection.create_function("spc242_hold", 0, self._held_statement)
        await db.execute(text("SELECT spc242_hold()"))

    def _held_statement(self) -> int:
        self.wait_for_the_stop()
        return 1


@pytest.fixture
def quick_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evaluate one turn exactly, so a job reaches its record at once."""
    monkeypatch.setattr(decision_job, "evaluate_tree", lambda scenario, strategy, **_kw: evaluate_scenario(
        scenario, strategy,
    ))


@pytest.fixture
def held(
    monkeypatch: pytest.MonkeyPatch, quick_evaluation: None,
) -> Iterator[Callable[[Callable[..., Any]], _HeldWrite]]:
    """Install a hold in the record's write, between its insert and its account check, with the stage given."""
    real = decision_record._account_exists
    holds: list[_HeldWrite] = []

    def install(stage: Callable[[_HeldWrite, AsyncSession], Any]) -> _HeldWrite:
        hold = _HeldWrite()
        holds.append(hold)

        async def account_exists(db: AsyncSession, operator: Operator) -> bool:
            await stage(hold, db)
            return await real(db, operator)

        monkeypatch.setattr(decision_record, "_account_exists", account_exists)
        return hold

    yield install
    # A write the stop cancelled keeps its connection open while its cursor lives, and the cursor is held by the
    # CancelledError's traceback, whose frames refer back to it: a cycle. Dropping the task breaks the job's hold on
    # it, and only a collection frees the cycle, so a failure here cannot lock the database for the next test.
    for hold in holds:
        if hold.job is not None:
            hold.job.task = None
    gc.collect()


@pytest.fixture
def signed_in() -> Iterator[list[SessionKey]]:
    """The sign-ins a test makes, whose planning state is dropped after it."""
    keys: list[SessionKey] = []
    yield keys
    for key in keys:
        _store.pop(key, None)


def _sign_in(client: TestClient, keys: list[SessionKey]) -> tuple[str, SessionKey]:
    """A new sign-in as the admin: its cookie and its key."""
    cookie = login_as(client, _ADMIN, _ADMIN_PASSWORD)
    key = session_key_for(cookie)
    assert key is not None
    keys.append(key)
    return cookie, key


def _writer(key: SessionKey) -> Callable[[ScenarioResult], Awaitable[int | None]]:
    """The record writer for a job the admin's sign-in *key* runs."""
    operator = Operator(key.user_id, _ADMIN)

    async def record(result: ScenarioResult) -> int | None:
        return await write_record(result, operator)

    return record


def _start(client: TestClient, cookie: str, key: SessionKey, job: DecisionJob) -> None:
    """Start *job* as *cookie*'s evaluation on the server's own event loop."""

    async def start() -> None:
        start_job(session_state(cookie), key, job)  # type: ignore[arg-type]

    client.portal.call(start)  # type: ignore[union-attr]


def _stop_while_writing(app: object, hold: _HeldWrite, name: str, keys: list[SessionKey]) -> DecisionJob:
    """Serve *app*, start a job named *name* as the admin, and stop the server once the job's record write is held."""
    with TestClient(app) as client:  # type: ignore[arg-type]
        cookie, key = _sign_in(client, keys)
        job = new_job(dataclasses.replace(_scenario(), name=name), SelectorStrategy.MINIMAX, record=_writer(key))
        hold.job = job
        _start(client, cookie, key, job)
        assert hold.entered.wait(_WAIT_S), "the job never began to write its record"
    return job


def _records_named(name: str) -> int:
    async def count() -> int:
        async with database.AsyncSessionLocal() as db:
            found = await db.execute(
                select(func.count()).select_from(DecisionRecord).where(DecisionRecord.scenario_name == name)
            )
            return int(found.scalar_one())

    return asyncio.run(count())


def _write_lock_free() -> str:
    """Empty when another connection can take SQLite's write lock at once, else SQLite's refusal."""
    probe = sqlite3.connect(str(database.engine.url.database), timeout=0, isolation_level=None)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.execute("ROLLBACK")
    except sqlite3.OperationalError as refused:
        return str(refused)
    finally:
        probe.close()
    return ""


def _wait_until(done: Callable[[], bool]) -> bool:
    """Whether *done* holds within _WAIT_S, polled from this thread."""
    pause = threading.Event()
    for _ in range(int(_WAIT_S / _POLL_S)):
        if done():
            return True
        pause.wait(_POLL_S)
    return done()


def test_a_job_writing_its_record_when_the_server_stops_keeps_its_record(
    initialized_app: object, held: Callable[..., _HeldWrite], signed_in: list[SessionKey],
) -> None:
    """The stop waits for the job, which finishes its record and only then stops, as _finish says it does."""
    name = _unique("SPC-242 stopped between statements")
    hold = held(_HeldWrite.between_statements)
    job = _stop_while_writing(initialized_app, hold, name, signed_in)
    assert (job.state, job.stopped, job.record_id is not None) == (
        JobState.STOPPED, "the server is shutting down", True,
    )
    assert _records_named(name) == 1


@pytest.mark.skipif(not _ON_SQLITE, reason="the held statement is a SQLite function, and the lock SQLite's own")
def test_a_stop_while_a_record_statement_runs_leaves_the_database_free_to_write(
    initialized_app: object, held: Callable[..., _HeldWrite], signed_in: list[SessionKey],
) -> None:
    """The fault itself: cancelled inside a statement, the write kept SQLite's lock for as long as the job was held."""
    name = _unique("SPC-242 stopped inside a statement")
    hold = held(_HeldWrite.inside_a_statement)
    job = _stop_while_writing(initialized_app, hold, name, signed_in)
    assert _write_lock_free() == ""
    assert (job.state, job.record_id is not None) == (JobState.STOPPED, True)
    assert _records_named(name) == 1


def test_records_two_sign_ins_finish_at_different_times_both_stand(
    initialized_app: object, quick_evaluation: None, signed_in: list[SessionKey],
) -> None:
    """The stop waits for every job writing a record, not the first to finish nor only the first it holds.

    The first job's write ends 0.3 s into the stop and the second's 2 s in, longer than a 1.2 s bound would allow
    and well inside STOP_WAIT_S.
    """
    names = [_unique("SPC-242 first of two"), _unique("SPC-242 second of two")]
    after_stop = {names[0]: 0.3, names[1]: 2.0}
    entered: list[str] = []

    def slow_writer(key: SessionKey) -> Callable[[ScenarioResult], Awaitable[int | None]]:
        write = _writer(key)

        async def record(result: ScenarioResult) -> int | None:
            entered.append(result.scenario.name)
            while not decision_job._SHUTTING_DOWN.is_set():
                await asyncio.sleep(_POLL_S)
            await asyncio.sleep(after_stop[result.scenario.name])
            return await write(result)

        return record

    jobs = []
    with TestClient(initialized_app) as client:  # type: ignore[arg-type]
        for name in names:
            cookie, key = _sign_in(client, signed_in)
            job = new_job(dataclasses.replace(_scenario(), name=name), SelectorStrategy.MINIMAX,
                          record=slow_writer(key))
            jobs.append(job)
            _start(client, cookie, key, job)
            assert _wait_until(lambda name=name: name in entered), f"{name} never began to write its record"
    assert [(job.state, job.record_id is not None) for job in jobs] == [(JobState.STOPPED, True)] * 2
    assert [_records_named(name) for name in names] == [1, 1]


def test_a_record_that_does_not_end_holds_the_stop_only_to_the_bound_and_is_logged(
    initialized_app: object, quick_evaluation: None, signed_in: list[SessionKey],
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A write still running at the bound is left to the loop's close, the stop does not fail, and the log says so."""
    monkeypatch.setattr(decision_job, "STOP_WAIT_S", 0.5)
    entered = threading.Event()

    async def record(_result: ScenarioResult) -> int | None:
        entered.set()
        await asyncio.sleep(_WAIT_S)
        return None

    caplog.set_level(logging.INFO)
    with TestClient(initialized_app) as client:  # type: ignore[arg-type]
        cookie, key = _sign_in(client, signed_in)
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, record=record)
        _start(client, cookie, key, job)
        assert entered.wait(_WAIT_S), "the job never began to write its record"
        began = time.monotonic()
    took = time.monotonic() - began
    assert 0.5 <= took < 0.5 + _STOP_MARGIN_S, f"the stop took {took:.2f} s against a 0.5 s bound"
    said = [r.getMessage() for r in caplog.records if r.name in ("spectre.web.app", "spectre.web.decision_job")]
    assert [line for line in said if "shutting down" in line or "decision job" in line] == [
        f"SPECTRE {__version__} shutting down",
        "Waiting up to 0.5 s for 1 decision job(s) sampling or writing a record to end",
        "1 decision job(s) still running after 0.5 s left to the event loop's close; a record being written is lost",
    ]
    assert job.state is JobState.RECORDING


def test_a_job_sampling_when_the_server_stops_is_waited_on_until_it_stops_at_its_next_sample(
    initialized_app: object, signed_in: list[SessionKey], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job sampling ends STOPPED by the shutdown, rather than being cancelled with its worker thread still running."""
    sampling = threading.Event()

    def evaluate(scenario: Scenario, strategy: SelectorStrategy, *, run: RunControl) -> ScenarioResult:
        sampling.set()
        sample = threading.Event()
        for _ in range(int(_WAIT_S / 0.2)):
            sample.wait(0.2)   # one sample's work
            reason = run.stop()
            if reason:
                raise EvaluationStoppedError(reason)
        return evaluate_scenario(scenario, strategy)

    monkeypatch.setattr(decision_job, "evaluate_tree", evaluate)
    with TestClient(initialized_app) as client:  # type: ignore[arg-type]
        cookie, key = _sign_in(client, signed_in)
        job = new_job(_scenario(), SelectorStrategy.MINIMAX)
        _start(client, cookie, key, job)
        assert sampling.wait(_WAIT_S), "the job never began to sample"
    assert (job.state, job.stopped) == (JobState.STOPPED, "the server is shutting down")


def test_a_job_waiting_on_custody_does_not_delay_the_stop(
    initialized_app: object, signed_in: list[SessionKey],
) -> None:
    """A custody read waits on its UDL fetch for up to 20 s and holds no database connection: it is not waited on."""
    reading = threading.Event()
    never = asyncio.Event()

    async def read(scenario: Scenario) -> Scenario:
        reading.set()
        await never.wait()
        return scenario

    with TestClient(initialized_app) as client:  # type: ignore[arg-type]
        cookie, key = _sign_in(client, signed_in)
        job = new_job(_scenario(), SelectorStrategy.MINIMAX, custody=CustodyRead(read, 20.0, "a first fetch"))
        _start(client, cookie, key, job)
        assert reading.wait(_WAIT_S), "the job never began to read custody"
        began = time.monotonic()
    took = time.monotonic() - began
    assert took < _STOP_MARGIN_S, f"the stop waited {took:.2f} s on a job reading custody"
    assert (job.state, job.result) == (JobState.CUSTODY, None)


def test_a_job_on_another_event_loop_does_not_hold_this_servers_stop(
    initialized_app: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stop waits only for its own loop's jobs: another loop's, as another test client's, is not its to end."""
    monkeypatch.setattr(decision_job, "STOP_WAIT_S", 2.0)
    release = threading.Event()
    sampling = threading.Event()

    def evaluate(scenario: Scenario, strategy: SelectorStrategy, **_kw: Any) -> ScenarioResult:
        sampling.set()
        release.wait(_WAIT_S)
        return evaluate_scenario(scenario, strategy)

    monkeypatch.setattr(decision_job, "evaluate_tree", evaluate)
    key = SessionKey(user_id=876_602, session_id="decision-job-other-loop")
    other = asyncio.new_event_loop()
    runner = threading.Thread(target=other.run_forever, daemon=True)
    runner.start()
    job = new_job(_scenario(), SelectorStrategy.MINIMAX)
    decision_job.server_starting()   # a test client that closed earlier in the run leaves the stop set

    async def start() -> None:
        start_job(get_session_state(key), key, job)

    try:
        asyncio.run_coroutine_threadsafe(start(), other).result(_WAIT_S)
        assert sampling.wait(_WAIT_S), "the other loop's job never began to sample"
        with TestClient(initialized_app):  # type: ignore[arg-type]
            began = time.monotonic()
        took = time.monotonic() - began
    finally:
        release.set()
        if job.task is not None:
            asyncio.run_coroutine_threadsafe(asyncio.wait([job.task], timeout=_WAIT_S), other).result(_WAIT_S + 1)
        other.call_soon_threadsafe(other.stop)
        runner.join(_WAIT_S)
        other.close()
        _store.pop(key, None)
    assert took < 1.0, f"the stop waited {took:.2f} s on another loop's job"
    assert (job.state, job.stopped) == (JobState.STOPPED, "the server is shutting down")
