"""Decide-by: the latest moment the operator can still act in time (SPC-008).

The operator's third output, joint second with the warning-time change: "what
do I need to decide, by when?" Each target's decide-at is its fastest credible
arrival minus the operator's response time for it, the hours it takes to plan,
approve and carry out a response; the decide-by time is the earliest of those.
Past it, a response started now would land after the arrival it is answering.

The response time is the operator's to set, for the sign-in and, where it
differs, for a named target (SPC-022): a target's own time is used for it, else
the sign-in's. With neither set for a target in reach there is no decide-by:
the sentence says it needs a response time, names the targets that have none,
and shows no time (SPC-211, evaluation F-23: the lead's ruling). Until 0.38.0 a
12 h default chosen by the developer stood in, tuned, not sourced, and moved
every decide-by and collect-first deadline with it. Without one target's time
no decide-at is known for it, and it could be the earliest, so none is shown
for the others either. A decision record keeps the decide-by the sweep set in
its stored Threat picture, time and sentence, and a replay reads them back as
stored, so a record from before replays exactly.

"Credible" here means within the sweep's delta-V budget, the same filter the
worst case card uses. The caller withholds decide-by where custody is lost or
computed evidence has earned a MINIMAL Threat ceiling (SPC-167; a recorded
status alone never does), and says which.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

__all__ = [
    "MAX_RESPONSE_H",
    "NEEDS_TIME",
    "DecideBy",
    "Due",
    "ResponseTimes",
    "decide_by",
    "earliest_arrival",
    "parse_response_hours",
    "withheld",
]

#: The longest response time accepted: a week. Past it, decide-by stops being
#: a decision clock and becomes a planning horizon.
MAX_RESPONSE_H: float = 168.0


#: What decide-by says with no response time set for a target in reach (SPC-211): it needs one, and shows no time.
NEEDS_TIME = (
    "No decide-by: it needs your response time, the hours you need to plan, approve and carry out a response, and "
    "none is set for {targets}. Set it on the sweep form, for every target or for one, and sweep again."
)


class Due(Enum):
    SET = "set"
    PASSED = "passed"
    NONE = "none"
    #: No response time is set for a target in reach, so no decide-by can be worked out (SPC-211).
    NEEDS_TIME = "needs time"


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
    sign-in's, and with neither set it has none (SPC-211). Hours, already
    checked by :func:`parse_response_hours`.
    """

    sign_in: float | None = None
    by_target: Mapping[str, float] = field(default_factory=dict)

    def for_target(self, name: str) -> tuple[float, str] | None:
        """The hours used for *name*, and how the sentence names which time they are; None with neither set."""
        own = self.by_target.get(name)
        if own is not None:
            return own, f"your response time for {name} of {_hours(own)}"
        if self.sign_in is not None:
            return self.sign_in, f"your response time of {_hours(self.sign_in)}"
        return None


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
    response time is not the answer. A tie goes to the sooner arrival. A target
    in reach with no response time set gives no decide-at, and could be the
    earliest, so then no decide-by is shown and the sentence says it needs one,
    naming each such target in the order they could arrive (SPC-211).
    """
    arrivals = sorted(_arrivals(entries, budget_m_s), key=lambda pair: pair[0])
    if not arrivals:
        return DecideBy(Due.NONE, f"No decide-by: no target is in reach within {budget_m_s:g} m/s.")
    held = {e.target.target_name: times.for_target(e.target.target_name) for _, e in arrivals}
    unset = [name for name, found in held.items() if found is None]
    if unset:
        return DecideBy(Due.NEEDS_TIME, NEEDS_TIME.format(targets=_listed(unset)), target=unset[0])
    known = {name: found for name, found in held.items() if found is not None}
    decisions = [(at - timedelta(hours=known[e.target.target_name][0]), at, e) for at, e in arrivals]
    decide_at, at, entry = min(decisions, key=lambda d: (d[0], d[1]))
    target = entry.target.target_name
    response = known[target][1]
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


def _listed(names: list[str]) -> str:
    """Names joined in words: "A", "A and B", "A, B and C"."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def withheld(reason: str) -> DecideBy:
    """No decide-by, and why: custody lost, or an earned MINIMAL Threat ceiling."""
    return DecideBy(Due.NONE, f"No decide-by: {reason}.")


def parse_response_hours(raw: str) -> tuple[float | None, str]:
    """The operator's response time from a form field: ``(hours, "")`` or ``(None, problem)``.

    Blank is ``(None, "")``: keep what is set, or none.
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
