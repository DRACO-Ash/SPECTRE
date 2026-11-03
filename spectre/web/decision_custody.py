"""The bound red track's custody, read before a decision scenario is evaluated (SPC-123).

Custody is the operator's: timely and actionable information to judge
whether a burn is normal and how the warning time changed (SPC-018). It is
read here, where the sweep reads it: the red object's element-set history
through the one held copy every panel shares (``held_history``), waiting a
bounded time for a first fetch as the sweep does, and judged by the sweep's
own rule (``custody_from_history``). The route reads it after binding, so the
evaluation itself, and any job it runs as, does no I/O.

Never raises: no catalogue number, UDL not connected, a fetch still running
and a failed fetch each come back as the history problem custody states, so
the red track reads as degraded, never as held.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from typing import Any

from spectre.domain.custody import CustodyStatus
from spectre.domain.decision import BoundElset, ScenarioBinding
from spectre.domain.normality import BurnNormality
from spectre.web.routes.pol import HeldHistory, custody_from_history, held_history, history_evidence, reserve_reset_for

#: How long an evaluation waits for a first fetch of the red track's history, as the sweep waits.
HISTORY_WAIT_S: float = 20.0
_NO_SATNO = "The red track has no catalogue number to fetch a history for."
_STILL_LOADING = "Its element-set history is still loading from UDL; the next evaluation will use it."
# Fetches still running after an evaluation stopped waiting, held so the event loop keeps each until it ends.
_HISTORY_TASKS: set[asyncio.Task[HeldHistory]] = set()


async def _history(state: Any, satno: int | None, now: datetime, wait_s: float) -> tuple[Any, BurnNormality | None, str]:
    """The red object's analysed history and its latest burn's verdict, or None and why there is none."""
    if satno is None:
        return None, None, _NO_SATNO
    task = asyncio.create_task(held_history(state, satno, now))
    _HISTORY_TASKS.add(task)
    task.add_done_callback(_HISTORY_TASKS.discard)
    try:
        held = await asyncio.wait_for(asyncio.shield(task), timeout=wait_s)
    except TimeoutError:
        return None, None, _STILL_LOADING
    if held.pol is None:
        return None, None, held.problem
    _assessment, normality = await asyncio.to_thread(history_evidence, held.pol, reserve_reset_for(state, satno))
    return held.pol, normality, ""


async def red_custody(state: Any, red: BoundElset, now: datetime, *, wait_s: float = HISTORY_WAIT_S) -> CustodyStatus:
    """The bound red track's custody at *now*, as the sweep would judge it."""
    pol, normality, problem = await _history(state, red.satno, now, wait_s)
    return custody_from_history(red.tle, now, pol=pol, normality=normality, problem=problem)


def with_red_custody(binding: ScenarioBinding, custody: CustodyStatus) -> ScenarioBinding:
    """*binding* with *custody* on its red track; a binding with no red track is returned as it is."""
    if binding.red is None:
        return binding
    return dataclasses.replace(binding, red=dataclasses.replace(binding.red, custody=custody))
