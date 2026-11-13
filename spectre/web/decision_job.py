"""A sampled Decision Engine evaluation, run as a session job the page polls (SPC-113).

A scenario whose rows sample a closest approach can take up to five minutes,
the 300 s budget the owner ruled on 2026-11-05 (SPC-178), and no request
should wait that long. POST /plan/decision/evaluate starts a
job here and returns a partial that polls GET /plan/decision/job every 2 s,
showing which hypothesis is being sampled and how much of the budget is used,
until the result replaces it.

Bounded on purpose, after the burn watch (spectre.web.burn_watch):

* One job per sign-in. A newer evaluation replaces it, and the replaced job
  stops at its next sample.
* One sampled evaluation at a time on the server. Two threads sampling at once
  ran about four times slower, because the equations of motion hold Python's
  global interpreter lock, so a second job waits, QUEUED, and its 300 s budget
  starts only when it runs: behind a full run it can wait up to five minutes.
* It stops within one sample, a few seconds at most at the longest spans an
  element set's limit and a burn 72 h back admit, when the operator cancels it, the sign-in ends, a newer
  evaluation replaces it, or the server shuts down. The asyncio task is never
  cancelled for these: cancelling it would free the slot while the worker
  thread kept sampling.
* Once sampling finishes it writes the evaluation's decision record (SPC-192) before the page shows the
  results, and Cancel no longer stops it then; a job that stops before that, or fails, writes none.
* It is not filed with the UDL login's tasks: a UDL logout ends the UDL
  connection, not the sign-in, and the job holds no UDL password.

Every outcome is named on the page with a fixed sentence; exception text goes
to the server log only.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import threading
import weakref
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    EvaluationStoppedError,
    RunControl,
    SamplingProgress,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    needs_a_run,
)
from spectre.domain.decision_transfer import ledger_sentence
from spectre.domain.decision_tree import evaluate_tree
from spectre.domain.rule_comparison import RULE_WORDS, matrix_picks, pick_words
from spectre.web.decision_record import primary_rule
from spectre.web.log_safety import log_safe
from spectre.web.models import SessionKey
from spectre.web.planning_state import SessionState, session_alive

logger = logging.getLogger(__name__)

#: What the job evaluates with: evaluate_tree, which is evaluate_scenario for one turn (SPC-142), or a test's stand-in.
Evaluate = Callable[..., ScenarioResult]
#: What a finished job hands its result to (SPC-192): write its decision record, answering the record's id, or None
#: when it could not be written.
Record = Callable[[ScenarioResult], Awaitable[int | None]]
#: What a job does before it evaluates (SPC-119): read the bound red track's custody, which may wait on a UDL
#: history fetch, and return the scenario with it.
Prepare = Callable[[Scenario], Awaitable[Scenario]]


@dataclass(frozen=True)
class CustodyRead:
    """A job's first stage (SPC-119): the read, how long it waits at most, and the fetch it waits on, in the words
    its progress uses."""

    read: Prepare
    wait_s: float
    fetch: str


class JobState(StrEnum):
    """Where a job is: reading custody, waiting for the server's sampling slot, sampling, writing its decision record
    once sampling has finished (SPC-192), or finished one of three ways."""

    CUSTODY = "custody"
    QUEUED = "queued"
    RUNNING = "running"
    RECORDING = "recording"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class DecisionJob:
    """One sampled evaluation for one sign-in, and how it is going."""

    job_id: str
    scenario: Scenario
    strategy: SelectorStrategy
    state: JobState = JobState.QUEUED
    #: Whether another evaluation held the server's sampling slot when this one last asked for it; until then the
    #: page says only that the job is starting.
    waiting: bool = False
    #: Set from the worker thread after each sample; a single assignment, safe under the GIL.
    progress: SamplingProgress | None = None
    #: Why the job stopped: a fixed sentence, never exception text.
    stopped: str = ""
    result: ScenarioResult | None = None
    cancelled: threading.Event = field(default_factory=threading.Event, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    #: Read before the evaluation (SPC-119): the bound red track's custody, which waits on a UDL history fetch.
    #: None when custody is read already.
    custody: CustodyRead | None = field(default=None, repr=False)
    #: Writes the decision record once the evaluation finishes (SPC-192); None writes none, as a test's job may.
    record: Record | None = field(default=None, repr=False)
    #: The decision record's id once written; None before, and when it could not be.
    record_id: int | None = None


def new_job(
    scenario: Scenario, strategy: SelectorStrategy, *, custody: CustodyRead | None = None, record: Record | None = None,
) -> DecisionJob:
    """A job for *scenario*, with an id the page cannot guess: reading custody first when *custody* is given, else
    queued; writing its decision record with *record* when it finishes (SPC-192)."""
    return DecisionJob(
        job_id=secrets.token_urlsafe(8), scenario=scenario, strategy=strategy,
        state=JobState.QUEUED if custody is None else JobState.CUSTODY, custody=custody, record=record,
    )


# ── Server-wide: the sampling slot, the shutdown stop and the tasks held ──

#: Set by the lifespan when the server shuts down, so a worker thread stops at its next sample rather than
#: holding the exit for up to the budget; cleared when it starts.
_SHUTTING_DOWN = threading.Event()
#: The loop holds only weak references to tasks, so a job's task could be collected before it finished
#: (audit F-143); this set holds them until they are done.
_TASKS: set[asyncio.Task[None]] = set()
#: One sampling slot per event loop. The server runs one loop; a semaphore is tied to the loop it first waits
#: on, so each loop a test runs gets its own.
_SLOTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _slot() -> asyncio.Semaphore:
    """The server's one sampling slot on the running loop."""
    loop = asyncio.get_running_loop()
    slot = _SLOTS.get(loop)
    if slot is None:
        slot = _SLOTS[loop] = asyncio.Semaphore(1)
    return slot


def server_starting() -> None:
    """The lifespan's start: jobs may run."""
    _SHUTTING_DOWN.clear()


def server_stopping() -> None:
    """The lifespan's end: every job stops at its next sample."""
    _SHUTTING_DOWN.set()


def still_wanted(state: SessionState, key: SessionKey, job: DecisionJob) -> str:
    """Empty while the job should run, else why it stops; checked in this order."""
    reasons: tuple[tuple[Callable[[], bool], str], ...] = (
        (job.cancelled.is_set, "you cancelled it"),
        (_SHUTTING_DOWN.is_set, "the server is shutting down"),
        (lambda: not session_alive(key, state), "this sign-in has ended"),
        (lambda: state.decision_job is not job, "a newer evaluation replaced it"),
    )
    return next((reason for unwanted, reason in reasons if unwanted()), "")


def evaluated_line(scenario: Scenario, result: ScenarioResult) -> str:
    """The session log's line for an evaluation that finished, naming what it is bound to."""
    binding = scenario.binding
    bound = "" if binding is None else " Bound to " + " and ".join(f"{b.side} {b.stk_name}" for b in binding.bound) + "."
    return (
        f"[Decision] Evaluated '{log_safe(scenario.name)}': "
        f"{len(scenario.adversary_actions)} adversary actions × {len(scenario.friendly_responses)} friendly "
        f"responses. Modelled recommendation: {_recommendation(result)}{_training(result)}{bound}"
        f"{_transfers_line(scenario, result)}"
    )


def _training(result: ScenarioResult) -> str:
    """The result's training-only label beside its recommendation, naming each unsourced relation it rests on, as
    the results page shows it first (SPC-207); nothing when it rests on none."""
    label = result.training_only
    return "" if label is None else f" {label}"


def _recommendation(result: ScenarioResult) -> str:
    """The recommendation as the results showed it: the deployment's primary rule's pick (SPC-194), with the rule
    chosen's beside it when that was another rule."""
    primary, chosen, picks = primary_rule(), result.robust_strategy, matrix_picks(result)

    def said(rule: SelectorStrategy) -> str:
        return log_safe(pick_words(result.scenario, picks[rule]))

    if chosen is primary:
        return f"{said(primary)}, the pick of {RULE_WORDS[primary]}, the primary rule and the rule chosen."
    return (f"{said(primary)}, the pick of {RULE_WORDS[primary]}, the primary rule; the rule chosen, "
            f"{RULE_WORDS[chosen]}, picks {said(chosen)}.")


def _transfers_line(scenario: Scenario, result: ScenarioResult) -> str:
    """Each row of several burns, with the burns it applied and those it dropped (SPC-184); empty for none."""
    said = [
        f" Row {log_safe(action.id)} ({log_safe(action.name)}): {sentence}"
        for action, burns in zip(scenario.adversary_actions, result.row_burns, strict=False)
        if burns is not None and (sentence := ledger_sentence(burns)) is not None
    ]
    return "".join(said)


def _stop(job: DecisionJob, reason: str) -> None:
    job.state, job.stopped = JobState.STOPPED, reason


async def _prepared(state: SessionState, key: SessionKey, job: DecisionJob) -> bool:
    """Read custody first, when the job must (SPC-119): True to go on, False once it has stopped or failed.

    A scenario that samples nothing then evaluates on a worker thread at once, without the sampling slot, as the
    route answers it when no read is needed, and the job ends here.
    """
    if job.custody is None:
        return True
    try:
        job.scenario = await job.custody.read(job.scenario)
        reason = still_wanted(state, key, job)
        if reason:
            _stop(job, reason)
            return False
        if await asyncio.to_thread(needs_a_run, job.scenario):
            job.state = JobState.QUEUED
            return True
        result = await asyncio.to_thread(evaluate_tree, job.scenario, job.strategy)
    except Exception:
        logger.exception("Decision evaluation %s failed", log_safe(job.job_id))
        job.state = JobState.FAILED
        return False
    await _finish(state, key, job, result)
    return False


async def run_job(state: SessionState, key: SessionKey, job: DecisionJob, *, evaluate: Evaluate | None = None) -> None:
    """Read custody when the job must, then wait for the sampling slot and evaluate on a worker thread under the
    budget; end DONE, STOPPED or FAILED.

    *evaluate* defaults to this module's evaluate_tree, read when the job runs: one turn is evaluate_scenario
    exactly, and more build the game tree under the same budget (SPC-142).
    """
    if not await _prepared(state, key, job):
        return
    run_with = evaluate or evaluate_tree

    def progress(seen: SamplingProgress) -> None:
        job.progress = seen

    control = RunControl(EVALUATION_BUDGET_S, stop=lambda: still_wanted(state, key, job) or None, progress=progress)
    slot = _slot()
    job.waiting = slot.locked()
    async with slot:
        reason = still_wanted(state, key, job)
        if reason:
            _stop(job, reason)
            return
        job.state = JobState.RUNNING
        try:
            result = await asyncio.to_thread(run_with, job.scenario, job.strategy, run=control)
        except EvaluationStoppedError as stopped:
            _stop(job, stopped.reason)
            return
        except Exception:
            logger.exception("Decision evaluation %s failed", log_safe(job.job_id))
            job.state = JobState.FAILED
            return
    await _finish(state, key, job, result)


async def _finish(state: SessionState, key: SessionKey, job: DecisionJob, result: ScenarioResult) -> None:
    """Write the decision record, then hold the result and log it, unless the job stopped being wanted while its
    last sample ran, when nothing is written (SPC-192).

    While the record is written the job is RECORDING: the page polls on, and Cancel no longer stops it, since
    sampling, the thing Cancel stops, has finished. A job that stops being wanted while its record is written, by
    a newer evaluation, a sign-out or shutdown, stops there: its record stands, for an evaluation that finished,
    and is decided on the Decision records page, but its results are not held.
    """
    reason = still_wanted(state, key, job)
    if reason:
        _stop(job, reason)
        return
    if job.record is not None:
        job.state = JobState.RECORDING
        job.record_id = await job.record(result)
        reason = still_wanted(state, key, job)
        if reason:
            _stop(job, reason)
            return
    job.result, job.state = result, JobState.DONE
    state.append_log(evaluated_line(job.scenario, result))
    logger.info("[Decision] Evaluated %s as job %s", log_safe(job.scenario.name), log_safe(job.job_id))


def _spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """Start *coro* as a task held until it finishes."""
    task = asyncio.get_running_loop().create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


def start_job(
    state: SessionState, key: SessionKey, job: DecisionJob, *,
    spawn: Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]] = _spawn,
) -> None:
    """Hold *job* as this sign-in's evaluation, replacing any other, and start it.

    A replaced job is not cancelled: it stops at its next sample, so the slot is freed only once its thread is.
    Whether the slot is held is read here, so the first page, rendered before the task runs, says which.
    """
    job.waiting = _slot().locked()
    state.decision_job = job
    job.task = spawn(run_job(state, key, job))


#: The states a job is still underway in, and the page polls; Cancel stops all but the last, writing its record.
_CANCELLABLE = (JobState.CUSTODY, JobState.QUEUED, JobState.RUNNING)
_UNDERWAY = (*_CANCELLABLE, JobState.RECORDING)


def cancel_job(state: SessionState, job_id: str) -> None:
    """Stop this sign-in's job if *job_id* names it and it has not finished; its thread stops at its next sample."""
    job = held_job(state, job_id)
    if job is not None and job.state in _CANCELLABLE:
        job.cancelled.set()
        _stop(job, "you cancelled it")


def held_job(state: SessionState, job_id: str) -> DecisionJob | None:
    """This sign-in's job, if *job_id* names it."""
    job = state.decision_job
    if isinstance(job, DecisionJob) and hmac.compare_digest(job.job_id.encode(), job_id.encode()):
        return job
    return None


# ── What the page says ──

NO_JOB = "No evaluation is held for this sign-in: a newer one replaced it, or the sign-in changed."
_STARTING_SOON = (
    "Starting: no other evaluation holds the sampling slot on this server, and the {budget:g} s budget starts when "
    "sampling does."
)
_QUEUED = (
    "Waiting for another evaluation on this server to finish: one sampled evaluation runs at a time, because two "
    "at once run about four times slower. Yours starts after it, and its {budget:g} s budget starts then."
)
_STARTING = (
    "Sampling has started: no sample has finished yet, and the {budget:g} s budget is running. Scenario epoch "
    "{epoch:%H:%M} UTC."
)
_RUNNING = (
    "Sampling hypothesis {p.row} of {p.rows}: {p.done:,} of {p.total:,} samples, {p.elapsed_s:.0f} s of the "
    "{budget:g} s budget used. Scenario epoch {epoch:%H:%M} UTC."
)
_SIZING = (
    "Sizing our burn for {label}: trial {p.done} of at most {p.total}, {p.elapsed_s:.0f} s of the {budget:g} s "
    "budget used. Scenario epoch {epoch:%H:%M} UTC."
)
_CUSTODY = (
    "Reading custody: waiting up to {wait:g} s for {red}'s element-set history, {fetch}, so its custody is judged "
    "as the sweep judges it. The evaluation starts when the history arrives or the wait ends; if "
    "it has not arrived by then, custody reads degraded, which scores between held and lost, and the next evaluation "
    "uses it."
)
_STOPPED = "Evaluation stopped: {reason}. Nothing was scored; evaluate again to see the figures."
_FAILED = "The evaluation failed; the server log has the detail. Nothing was scored."
_DONE = "The evaluation finished."
_RECORDING = "The evaluation finished; writing its decision record."


def _red_name(job: DecisionJob) -> str:
    binding = job.scenario.binding
    red = None if binding is None else binding.red
    return "the red track" if red is None else red.stk_name


def _message(job: DecisionJob) -> str:
    epoch, budget = job.scenario.epoch_utc, EVALUATION_BUDGET_S
    if job.state is JobState.CUSTODY and job.custody is not None:   # the red track's name is escaped where rendered
        return _CUSTODY.format(wait=job.custody.wait_s, red=_red_name(job), fetch=job.custody.fetch)
    if job.state is JobState.QUEUED:
        return (_QUEUED if job.waiting else _STARTING_SOON).format(budget=budget)
    if job.state is JobState.RUNNING:
        if job.progress is None:
            return _STARTING.format(budget=budget, epoch=epoch)
        if job.progress.stage == "sizing":   # SPC-121: the label is the response's name, escaped where rendered
            return _SIZING.format(label=job.progress.label, p=job.progress, budget=budget, epoch=epoch)
        return _RUNNING.format(p=job.progress, budget=budget, epoch=epoch)
    return {
        JobState.STOPPED: _STOPPED.format(reason=job.stopped),
        JobState.FAILED: _FAILED,
        JobState.RECORDING: _RECORDING,
    }.get(job.state, _DONE)


def job_view(state: SessionState, job_id: str) -> dict[str, Any]:
    """What the job partial shows: the job if *job_id* names it, the sentence for its state, and whether to poll."""
    job = held_job(state, job_id)
    if job is None:
        return {"job": None, "message": NO_JOB, "polling": False, "cancellable": False, "progress": None}
    return {
        "job": job,
        "message": _message(job),
        "polling": job.state in _UNDERWAY,
        "cancellable": job.state in _CANCELLABLE,
        "progress": job.progress if job.state is JobState.RUNNING else None,
    }
