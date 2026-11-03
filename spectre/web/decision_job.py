"""A sampled Decision Engine evaluation, run as a session job the page polls (SPC-113).

A scenario whose rows sample a closest approach can take up to two minutes,
and no request should wait that long. POST /plan/decision/evaluate starts a
job here and returns a partial that polls GET /plan/decision/job every 2 s,
showing which hypothesis is being sampled and how much of the budget is used,
until the result replaces it.

Bounded on purpose, after the burn watch (spectre.web.burn_watch):

* One job per sign-in. A newer evaluation replaces it, and the replaced job
  stops at its next sample.
* One sampled evaluation at a time on the server. Two threads sampling at once
  ran about four times slower, because the equations of motion hold Python's
  global interpreter lock, so a second job waits, QUEUED, and its 120 s budget
  starts only when it runs.
* It stops within one sample, at most about 2 s at the longest horizons the
  cap admits, when the operator cancels it, the sign-in ends, a newer
  evaluation replaces it, or the server shuts down. The asyncio task is never
  cancelled for these: cancelling it would free the slot while the worker
  thread kept sampling.
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
from collections.abc import Callable, Coroutine
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
    evaluate_scenario,
)
from spectre.web.log_safety import log_safe
from spectre.web.models import SessionKey
from spectre.web.planning_state import SessionState, session_alive

logger = logging.getLogger(__name__)

#: What the job evaluates with: evaluate_scenario, or a test's stand-in.
Evaluate = Callable[..., ScenarioResult]


class JobState(StrEnum):
    """Where a job is: waiting for the server's sampling slot, sampling, or finished one of three ways."""

    QUEUED = "queued"
    RUNNING = "running"
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


def new_job(scenario: Scenario, strategy: SelectorStrategy) -> DecisionJob:
    """A queued job for *scenario*, with an id the page cannot guess."""
    return DecisionJob(job_id=secrets.token_urlsafe(8), scenario=scenario, strategy=strategy)


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
        f"responses. Modelled recommendation: {result.robust_best_response.name} ({result.robust_strategy.value})"
        f"{bound}"
    )


def _stop(job: DecisionJob, reason: str) -> None:
    job.state, job.stopped = JobState.STOPPED, reason


async def run_job(state: SessionState, key: SessionKey, job: DecisionJob, *, evaluate: Evaluate | None = None) -> None:
    """Wait for the sampling slot, then evaluate on a worker thread under the budget; end DONE, STOPPED or FAILED.

    *evaluate* defaults to this module's evaluate_scenario, read when the job runs.
    """
    run_with = evaluate or evaluate_scenario

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
    _finish(state, key, job, result)


def _finish(state: SessionState, key: SessionKey, job: DecisionJob, result: ScenarioResult) -> None:
    """Hold the result and log it, unless the job stopped being wanted while its last sample ran."""
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


def cancel_job(state: SessionState, job_id: str) -> None:
    """Stop this sign-in's job if *job_id* names it and it has not finished; its thread stops at its next sample."""
    job = held_job(state, job_id)
    if job is not None and job.state in (JobState.QUEUED, JobState.RUNNING):
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
_STOPPED = "Evaluation stopped: {reason}. Nothing was scored; evaluate again to see the figures."
_FAILED = "The evaluation failed; the server log has the detail. Nothing was scored."
_DONE = "The evaluation finished."


def _message(job: DecisionJob) -> str:
    epoch, budget = job.scenario.epoch_utc, EVALUATION_BUDGET_S
    if job.state is JobState.QUEUED:
        return (_QUEUED if job.waiting else _STARTING_SOON).format(budget=budget)
    if job.state is JobState.RUNNING:
        if job.progress is None:
            return _STARTING.format(budget=budget, epoch=epoch)
        return _RUNNING.format(p=job.progress, budget=budget, epoch=epoch)
    return {
        JobState.STOPPED: _STOPPED.format(reason=job.stopped),
        JobState.FAILED: _FAILED,
    }.get(job.state, _DONE)


def job_view(state: SessionState, job_id: str) -> dict[str, Any]:
    """What the job partial shows: the job if *job_id* names it, the sentence for its state, and whether to poll."""
    job = held_job(state, job_id)
    if job is None:
        return {"job": None, "message": NO_JOB, "polling": False, "progress": None}
    return {
        "job": job,
        "message": _message(job),
        "polling": job.state in (JobState.QUEUED, JobState.RUNNING),
        "progress": job.progress if job.state is JobState.RUNNING else None,
    }
