"""Decide-by: the latest moment the operator can still act in time (SPC-008).

The operator's third output, joint second with the warning-time change: "what
do I need to decide, by when?" The decide-by time is the fastest credible
arrival at a target minus the operator's own response time, the hours it takes
to plan, approve and carry out a response. Past it, a response started now
would land after the arrival it is answering.

The response time is the operator's to set. Until they do, a default of 12
hours is used and every sentence says it is the default (owner, 2 November
2026: "don't ask me again, just crack on"; the value is Claude's choice, not a
ruling). 12 hours is conservative on purpose: a defensive manoeuvre needs
planning, approval and an upload pass, and an early decide-by costs less than
a late one. Tuned, not sourced.

"Credible" here means within the sweep's delta-V budget, the same filter the
worst case card uses. The caller withholds decide-by where custody is lost or
the object is assessed unable to fly the intercept, and says which.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

__all__ = [
    "DEFAULT_RESPONSE_H",
    "MAX_RESPONSE_H",
    "DecideBy",
    "Due",
    "decide_by",
    "earliest_arrival",
    "parse_response_hours",
    "withheld",
]

#: The response time used until the operator sets their own.
DEFAULT_RESPONSE_H: float = 12.0
#: The longest response time accepted: a week. Past it, decide-by stops being
#: a decision clock and becomes a planning horizon.
MAX_RESPONSE_H: float = 168.0


class Due(Enum):
    SET = "set"
    PASSED = "passed"
    NONE = "none"


@dataclass(frozen=True)
class DecideBy:
    """The decide-by time and its sentence, in the operator's words."""

    due: Due
    sentence: str
    decide_at: datetime | None = None
    arrival: datetime | None = None
    target: str = ""


def _when(moment: datetime) -> str:
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


def _hours(hours: float) -> str:
    """Hours as the response time is written: "12 h", "1.5 h"."""
    return f"{hours:g} h"


def _response(hours: float, is_default: bool) -> str:
    if is_default:
        return f"the default response time of {_hours(hours)}, which you have not set"
    return f"your response time of {_hours(hours)}"


def earliest_arrival(entries: Iterable[Any], budget_m_s: float) -> tuple[datetime, Any] | None:
    """The soonest any intercept within *budget_m_s* could arrive, and its entry.

    Arrival is the burn time plus the flight time, so a later burn on a faster
    transfer can arrive first; the worst case card ranks on flight time alone,
    which is the warning, not the arrival.
    """
    feasible = [(e.burn_epoch + timedelta(hours=e.tof_hours), e) for e in entries
                if e.delta_v_m_s <= budget_m_s and getattr(e, "arrives", True)]
    return min(feasible, key=lambda pair: pair[0], default=None)


def decide_by(
    arrival: tuple[datetime, Any] | None, response_h: float, is_default: bool, now: datetime, budget_m_s: float,
) -> DecideBy:
    """The decide-by time from the earliest arrival, or why there is none."""
    if arrival is None:
        return DecideBy(Due.NONE, f"No decide-by: no target is in reach within {budget_m_s:g} m/s.")
    at, entry = arrival
    target = entry.target.target_name
    decide_at = at - timedelta(hours=response_h)
    if decide_at <= now:
        left = max((at - now).total_seconds() / 3600.0, 0.0)
        return DecideBy(
            Due.PASSED,
            f"Decide-by has passed for {target}: an intercept could arrive at {_when(at)}, "
            f"{left:.1f} h from now, inside {_response(response_h, is_default)}.",
            decide_at, at, target,
        )
    return DecideBy(
        Due.SET,
        f"Decide by {_when(decide_at)} for {target}: its fastest intercept within {budget_m_s:g} m/s could arrive "
        f"at {_when(at)}, and that is {_response(response_h, is_default)}.",
        decide_at, at, target,
    )


def withheld(reason: str) -> DecideBy:
    """No decide-by, and why: custody lost, or the object assessed unable to fly it."""
    return DecideBy(Due.NONE, f"No decide-by: {reason}.")


def parse_response_hours(raw: str) -> tuple[float | None, str]:
    """The operator's response time from a form field: ``(hours, "")`` or ``(None, problem)``.

    Blank is ``(None, "")``: keep what is set, or the default.
    """
    text = raw.strip()
    if not text:
        return None, ""
    try:
        hours = float(text)
    except ValueError:
        return None, f"Response time must be a number of hours; got {text[:20]!r}."
    if not 0.0 < hours <= MAX_RESPONSE_H:  # NaN fails every comparison, so it is refused here too
        return None, f"Response time must be more than 0 and at most {MAX_RESPONSE_H:g} hours."
    return hours, ""
