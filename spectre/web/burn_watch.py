"""The burn watch: keep checking the red object last swept, and say when it burns (SPC-006).

A sweep answers what has already happened. The operator's question is "what
changed?", and the answer should arrive, not be asked for. After a sweep with
UDL connected, one watch per sign-in keeps checking that object while the
operator is signed in: every 10 minutes it asks UDL for the newest element
set, and only when that set is newer than the newest held does it fetch the
history again and look for a new confirmed burn. A new burn is announced with
what it changed, computed the same way the sweep computes it.

Bounded on purpose. One object, one task per sign-in, cancelled by UDL logout
(it is filed with the login's tasks) and stopping within one tick of the
sign-in ending, so the UDL password it reads is never held past the session.
Alerts live in the session state and die with it; the next sweep recomputes
the change from UDL, so a handover operator still gets it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from spectre.domain.models import ThreatTarget
from spectre.domain.warning_change import WarningChange, burns_in_window, is_new_burn
from spectre.web.elsets import limit_hours_for_regime
from spectre.web.log_safety import log_safe
from spectre.web.models import SessionKey
from spectre.web.planning_state import SessionState, session_alive, sign_in_expires_at

logger = logging.getLogger(__name__)

#: How often the loop checks it is still wanted. No I/O, so it is cheap; it
#: bounds how long the UDL password is held after the sign-in ends.
TICK_S: float = 30.0
#: How often UDL is asked for the newest element set: 6 requests an hour.
CHECK_EVERY: timedelta = timedelta(minutes=10)
#: How long the first check waits for the sweep's own history fetch, so one
#: fetch serves both on a cold sign-in.
FIRST_WAIT_S: float = 150.0

#: The computation the sweep route supplies: what the burns changed.
#: It takes ``(state, watch, (pol, assessment, new burns), now)``.
Compute = Callable[[SessionState, "BurnWatch", tuple[Any, Any, list[Any]], datetime], Awaitable[WarningChange]]


def _utc_now() -> datetime:
    """The watch's clock, a seam so tests can stand at a chosen moment."""
    return datetime.now(tz=UTC)


@dataclass
class BurnWatch:
    """What one watch holds: the object, what to fly it against, and how the checks went."""

    red_name: str
    red_satno: int
    red_regime: str
    targets: list[ThreatTarget]
    manual_tle_by_name: dict[str, str]
    max_dv_m_s: float
    #: The post-burn element set of the last burn already told to the operator.
    accounted_until: datetime | None
    started_at: datetime
    next_check_at: datetime
    checked_at: datetime | None = None
    last_good_at: datetime | None = None
    newest_epoch: datetime | None = None
    #: A fixed sentence when the last check failed, never exception text.
    problem: str = ""
    #: Why the watch stopped, empty while it runs.
    stopped: str = ""
    task: asyncio.Task[None] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class BurnAlert:
    """A burn the watch found, and what it changed."""

    red_name: str
    burn_when: str
    seen_at: datetime
    change: WarningChange


def _hm(moment: datetime) -> str:
    return f"{moment:%H:%M} UTC"


def still_wanted(state: SessionState, key: SessionKey, watch: BurnWatch) -> str:
    """Empty while the watch should run, else why it stops."""
    if not session_alive(key, state):
        return "this sign-in has ended"
    if not state.udl_username or not state.udl_password:
        return "UDL is disconnected"
    if state.burn_watch is not watch:
        return "a newer sweep replaced it"
    return ""


async def _probe(state: SessionState, watch: BurnWatch) -> datetime | None:
    """The epoch of the newest element set UDL holds for the object; raises when it cannot say."""
    from spectre.web.elsets import _epoch_of
    from spectre.web.routes.udl import fetch_tle_for_satno

    newest = await fetch_tle_for_satno(
        watch.red_satno, state.udl_username or "", state.udl_password or "",
        data_mode=state.udl_data_mode, source=state.udl_tle_source,
    )
    if newest is None:
        raise LookupError("UDL returned no element set")
    return _epoch_of(newest[0])


def _first_line(change: WarningChange) -> str:
    return change.headline if change.headline else "the change in your warning is not computed"


def _burn_when(burns: list[Any]) -> str:
    """When the latest of the burns happened, as the operator reads it."""
    latest = max(burns, key=lambda m: m.burn_window[0])
    return f"{latest.burn_epoch:%H:%M} UTC on {latest.burn_epoch.day} {latest.burn_epoch:%b}"


class _Stated(Exception):
    """A check that failed at a known stage, carrying the fixed sentence the operator is shown.

    ``unseen`` is whether burns since the last good check may still be unseen;
    it is false once the check has found the burn and failed only to compute it.
    """

    def __init__(self, lead: str, *, unseen: bool = True) -> None:
        super().__init__(lead)
        self.lead, self.unseen = lead, unseen


def _record(state: SessionState, watch: BurnWatch, burns: list[Any], change: WarningChange, now: datetime) -> BurnAlert:
    """Hold the alert, log it once and account for the burns it announced."""
    when = _burn_when(burns)
    alert = BurnAlert(watch.red_name, when, now, change)
    state.burn_alert = alert
    state.append_log(f"[BURN] {watch.red_name} burned at {when}: {_first_line(change)}")
    watch.accounted_until = max(m.tle_after.epoch for m in burns)
    return alert


async def _new_burns(
    state: SessionState, watch: BurnWatch, now: datetime, probed: datetime | None,
) -> tuple[Any, Any, list[Any]] | None:
    """The history that reaches the newest element set, and ``(pol, assessment, new burns)`` from it.

    A held history that already reaches the epoch just probed is used as it
    is, so on a cold sign-in the sweep's own fetch serves the first check.
    Otherwise the hold is dropped and the history fetched afresh.
    """
    from spectre.web.routes.pol import held_history, history_evidence, reserve_reset_for

    kept = state.elset_histories.get(watch.red_satno)
    reaches = (kept is not None and kept.pol is not None and kept.pol.records and probed is not None
               and kept.pol.records[-1].epoch >= probed)
    if not reaches:
        state.elset_histories.pop(watch.red_satno, None)
    held = await held_history(state, watch.red_satno, now)
    if held.pol is None:
        # held_history's problems are fixed sentences of its own, safe to show as they are.
        raise _Stated(held.problem or "No element-set history is held for this object.")
    loop = asyncio.get_running_loop()
    try:
        assessment, _ = await loop.run_in_executor(
            None, history_evidence, held.pol, reserve_reset_for(state, watch.red_satno),
        )
    except Exception as exc:
        raise _Stated("The element-set history could not be analysed.") from exc
    limit = limit_hours_for_regime(watch.red_regime)
    burns = [m for m in burns_in_window(held.pol.manoeuvres, now, limit) if is_new_burn(m, watch.accounted_until)]
    return held.pol, assessment, burns


#: What a failed check shows when it failed asking UDL for the newest set; never exception text.
_FETCH_FAILED = "The element set could not be fetched from UDL at {now}; trying again at {next}."
#: What follows the sentence of a check that failed at a later, known stage.
_STATED_TAIL = " Checked at {now}; trying again at {next}."


def _good(watch: BurnWatch, now: datetime, epoch: datetime | None) -> None:
    """The check succeeded: the newest set is seen and nothing is outstanding."""
    watch.newest_epoch = epoch
    watch.last_good_at, watch.problem = now, ""


async def check_once(
    state: SessionState, key: SessionKey, watch: BurnWatch, now: datetime, compute: Compute,
) -> BurnAlert | None:
    """One check: probe UDL, fetch the history only if it moved, announce any new burn.

    The newest set counts as seen only once the check has finished with it, so
    a computation that fails leaves the set unseen and the next check retries it.
    After each wait it asks again whether it is still wanted, so a sign-out
    mid-check uses the UDL password no further and leaves no alert behind.
    """
    watch.checked_at = now
    watch.next_check_at = now + CHECK_EVERY
    try:
        return await _check(state, key, watch, now, compute)
    except Exception as exc:  # noqa: BLE001 - one failed check must not end the watch; it says so and retries
        logger.warning("Burn watch check failed for %s: %s", log_safe(watch.red_satno),
                       log_safe(exc.__cause__ or exc))
        times = {"now": _hm(now), "next": _hm(watch.next_check_at)}
        if isinstance(exc, _Stated):
            sentence, unseen = exc.lead + _STATED_TAIL.format(**times), exc.unseen
        else:
            sentence, unseen = _FETCH_FAILED.format(**times), True
        since = f" Burns since {_hm(watch.last_good_at)}, the last good check, are not yet seen." if watch.last_good_at else ""
        watch.problem = sentence + (since if unseen else "")
        return None


async def _check(
    state: SessionState, key: SessionKey, watch: BurnWatch, now: datetime, compute: Compute,
) -> BurnAlert | None:
    """The body of one check; a failure past the probe raises :class:`_Stated` with its own sentence."""
    epoch = await _probe(state, watch)
    if still_wanted(state, key, watch):
        return None
    if watch.newest_epoch is not None and epoch is not None and epoch <= watch.newest_epoch:
        _good(watch, now, watch.newest_epoch)
        return None
    found = await _new_burns(state, watch, now, epoch)
    if found is None or not found[2]:
        _good(watch, now, epoch)
        return None
    if still_wanted(state, key, watch):
        return None
    try:
        change = await compute(state, watch, found, now)
    except Exception as exc:
        lead = f"{watch.red_name} burned at {_burn_when(found[2])}, but what it changed could not be computed."
        raise _Stated(lead, unseen=False) from exc
    if still_wanted(state, key, watch):
        return None
    _good(watch, now, epoch)
    return _record(state, watch, found[2], change, now)


async def watch_loop(
    state: SessionState, key: SessionKey, watch: BurnWatch,
    first_history: asyncio.Task[Any] | None, compute: Compute,
) -> None:
    """The first check once the sweep's history settles, then a check every 10 minutes until stopped."""
    if first_history is not None:
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(first_history), timeout=FIRST_WAIT_S)
    while True:
        reason = still_wanted(state, key, watch)
        if reason:
            watch.stopped = reason
            return
        now = _utc_now()
        if now >= watch.next_check_at:
            await check_once(state, key, watch, now, compute)
        await asyncio.sleep(TICK_S)


def start_watch(  # noqa: PLR0913 - the watch, its owner and the injected pieces, the last three named at the call
    state: SessionState, key: SessionKey, watch: BurnWatch, *,
    first_history: asyncio.Task[Any] | None, compute: Compute,
    spawn: Callable[[Any, SessionKey | None], asyncio.Task[None]],
) -> None:
    """Replace any watch this sign-in holds and start this one."""
    old = state.burn_watch
    if old is not None and old.task is not None and not old.task.done():
        old.task.cancel()
        old.stopped = "a newer sweep replaced it"
    state.burn_watch = watch
    watch.task = spawn(watch_loop(state, key, watch, first_history, compute), key)


def watch_view(state: SessionState, key: SessionKey | None, now: datetime) -> dict[str, Any]:
    """What the watch note shows: the watch, its latest alert and when the sign-in ends."""
    watch = state.burn_watch
    if watch is not None and not watch.stopped and key is not None:
        watch.stopped = still_wanted(state, key, watch)
    return {
        "burn_watch": watch,
        "burn_alert": state.burn_alert,
        "watch_ends_at": sign_in_expires_at(key, now) if key is not None else None,
    }
