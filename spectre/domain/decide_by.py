"""Decide-by: the latest moment the operator can still act in time (SPC-008).

The operator's third output, joint second with the warning-time change: "what
do I need to decide, by when?" Each target's decide-at is its fastest credible
arrival minus the operator's response time for it, the hours it takes to plan,
approve and carry out a response; the decide-by time is the earliest of those.
Past it, a response started now would land after the arrival it is answering.

The response time is the operator's to set, for the sign-in and, where it
differs, for a named target (SPC-022): a target's own time is used for it, else
the sign-in's. Until either is set, a default of 12
hours is used and every sentence says which it used (owner, 2 November
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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

__all__ = [
    "DEFAULT_RESPONSE_H",
    "MAX_RESPONSE_H",
    "DecideBy",
    "Due",
    "ResponseTimes",
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


@dataclass(frozen=True)
class ResponseTimes:
    """The operator's response times: one per named target where set, and the sign-in's (SPC-022).

    A target's own time is used for it; a target with none takes the
    sign-in's, and with neither set the default is used and said to be the
    default. Hours, already checked by :func:`parse_response_hours`.
    """

    sign_in: float | None = None
    by_target: Mapping[str, float] = field(default_factory=dict)

    def for_target(self, name: str) -> tuple[float, str]:
        """The hours used for *name*, and how the sentence names which time they are."""
        own = self.by_target.get(name)
        if own is not None:
            return own, f"your response time for {name} of {_hours(own)}"
        if self.sign_in is not None:
            return self.sign_in, f"your response time of {_hours(self.sign_in)}"
        return DEFAULT_RESPONSE_H, f"the default response time of {_hours(DEFAULT_RESPONSE_H)}, which you have not set"


def _arrivals(entries: Iterable[Any], budget_m_s: float) -> list[tuple[datetime, Any]]:
    """Each intercept within *budget_m_s* that arrives, with its arrival: burn time plus flight time."""
    return [(e.burn_epoch + timedelta(hours=e.tof_hours), e) for e in entries
            if e.delta_v_m_s <= budget_m_s and getattr(e, "arrives", True)]


def earliest_arrival(entries: Iterable[Any], budget_m_s: float) -> tuple[datetime, Any] | None:
    """The soonest any intercept within *budget_m_s* could arrive, and its entry.

    Arrival is the burn time plus the flight time, so a later burn on a faster
    transfer can arrive first; the worst case card ranks on flight time alone,
    which is the warning, not the arrival.
    """
    return min(_arrivals(entries, budget_m_s), key=lambda pair: pair[0], default=None)


def decide_by(entries: Iterable[Any], times: ResponseTimes, now: datetime, budget_m_s: float) -> DecideBy:
    """The earliest decide-at across the targets in reach, or why there is none.

    Each intercept's decide-at is its arrival minus the response time for its
    target. With response times that differ, a later arrival with a longer
    response time can need deciding first, so the earliest arrival minus one
    response time is not the answer. A tie goes to the sooner arrival.
    """
    decisions = [(at - timedelta(hours=times.for_target(e.target.target_name)[0]), at, e)
                 for at, e in _arrivals(entries, budget_m_s)]
    if not decisions:
        return DecideBy(Due.NONE, f"No decide-by: no target is in reach within {budget_m_s:g} m/s.")
    decide_at, at, entry = min(decisions, key=lambda d: (d[0], d[1]))
    target = entry.target.target_name
    response = times.for_target(target)[1]
    if decide_at <= now:
        left = max((at - now).total_seconds() / 3600.0, 0.0)
        return DecideBy(
            Due.PASSED,
            f"Decide-by has passed for {target}: an intercept could arrive at {_when(at)}, "
            f"{left:.1f} h from now, inside {response}.",
            decide_at, at, target,
        )
    return DecideBy(
        Due.SET,
        f"Decide by {_when(decide_at)} for {target}: its fastest intercept within {budget_m_s:g} m/s could arrive "
        f"at {_when(at)}, and that is {response}.",
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
