"""Custody of an object: can we still judge it?

The operator's definition (28 October 2026): custody is having timely and
actionable information to determine the first two things they need when
something moves, whether the burn is normal and how the warning time changed.
Custody is not about what the information says. An object doing something
alarming, seen clearly, is in custody; a quiet object seen through a two-week
old orbit is not.

Two inputs decide it:

● The newest element set's age against its regime's limit (72 hours for GEO
  and deep space, 24 otherwise, the limits the sweep already marks STALE).
  Past it, warning time is computed from an out-of-date orbit and a burn since
  that epoch is invisible: custody is LOST, whatever else is held.
● Whether the element-set history can judge a burn. Without one, or with too
  little, or with a gap UDL's record cap left, the orbit is current but
  whether a burn is normal cannot be said: custody is DEGRADED.

Pure function over plain data. No I/O, no framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from spectre.domain.normality import Normality

__all__ = ["BASIS", "Custody", "CustodyStatus", "assess_custody"]

_HOURS_PER_DAY = 24.0

#: Shown with every custody line.
BASIS = (
    "Custody here means timely and actionable information to judge whether a burn is normal "
    "and how the warning time changed (operator definition, 28 October 2026)."
)


class Custody(Enum):
    HELD = "held"
    DEGRADED = "degraded"
    LOST = "lost"


@dataclass(frozen=True)
class CustodyStatus:
    """Custody, in the operator's words, and what it rests on."""

    state: Custody
    sentence: str
    basis: str = field(default=BASIS)


def _age(hours: float) -> str:
    """Hours under a day, days beyond it, as the element set ages are shown."""
    return f"{hours:.1f} h" if hours < _HOURS_PER_DAY else f"{hours / _HOURS_PER_DAY:.1f} d"


def assess_custody(  # noqa: PLR0913 - one argument per fact the rule reads, all named at the call
    *,
    elset_hours: float | None,
    limit_hours: float,
    elset_count: int,
    history_days: float,
    normality: Normality | None,
    history_problem: str,
    truncated_at: datetime | None,
) -> CustodyStatus:
    """Whether the object is in custody, from its orbit's age and its history.

    *elset_hours* is the newest element set's age, ``None`` when no epoch can
    be read. *normality* is the verdict on its latest burn, ``None`` when the
    history holds no burn. *history_problem* is why there is no history, empty
    when there is one.
    """
    limit = f"{limit_hours:.0f} h"
    if elset_hours is None:
        return CustodyStatus(
            Custody.LOST,
            "Custody lost: there is no element set with a readable epoch, so neither "
            "its warning time nor its burns can be judged.",
        )
    if elset_hours > limit_hours:
        return CustodyStatus(
            Custody.LOST,
            f"Custody lost: its newest element set is {_age(elset_hours)} old against a {limit} limit, "
            "so its warning time is out of date and a burn since then would not be seen.",
        )
    current = f"its orbit is current ({_age(elset_hours)} old, limit {limit})"
    if history_problem:
        return CustodyStatus(
            Custody.DEGRADED,
            f"Custody degraded: {current}, but whether its burns are normal cannot be judged. "
            f"{history_problem}",
        )
    if normality is Normality.NOT_ENOUGH_HISTORY:
        return CustodyStatus(
            Custody.DEGRADED,
            f"Custody degraded: {current}, but {elset_count} element sets over "
            f"{history_days:.0f} days is too little history to judge its burns.",
        )
    if truncated_at is not None:
        return CustodyStatus(
            Custody.DEGRADED,
            f"Custody degraded: {current}, but its history is missing after "
            f"{truncated_at:%Y-%m-%d}, where UDL's record cap cut it, so a burn there would not be seen.",
        )
    return CustodyStatus(
        Custody.HELD,
        f"Custody held: its orbit is {_age(elset_hours)} old (limit {limit}) and {elset_count} "
        f"element sets over {history_days:.0f} days judge its burns.",
    )
