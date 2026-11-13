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

Over a scenario's horizon (SPC-123), custody_over_horizon carries the status
at the scenario epoch forward on the assumption that no newer element set
arrives. It is lost from the earliest of: the epoch, if it is lost already;
the moment the newest element set passes its limit; and a hypothesised burn
newer than the newest element set, which that element set cannot show. So
each gap it gives is an upper bound. Degraded custody can judge the warning
time but not whether a burn is normal, and the operator's custody needs both,
so it is neither held nor lost: it stays degraded until one of those rules
would lose it, and its degraded hours are counted apart from its lost hours.
The owner ruled on 2026-11-05 (SPC-179) that degraded scores between held and
lost; the weight it carries is the Decision Engine's, not this module's.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from typing import NamedTuple

from spectre.domain.normality import Normality

__all__ = [
    "BASIS",
    "Custody",
    "CustodyOverHorizon",
    "CustodyStatus",
    "Horizon",
    "LossCause",
    "age_text",
    "assess_custody",
    "custody_over_horizon",
]

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


def age_text(hours: float) -> str:
    """Hours under a day, days beyond it, as the element set ages are shown."""
    return f"{hours:.1f} h" if hours < _HOURS_PER_DAY else f"{hours / _HOURS_PER_DAY:.1f} d"


_age = age_text


# PLR0911, PLR0913: one return per custody state, checked in order; one argument per fact the rule reads, all
# named at the call.
def assess_custody(  # noqa: PLR0911, PLR0913
    *,
    elset_hours: float | None,
    limit_hours: float,
    elset_count: int,
    history_days: float,
    normality: Normality | None,
    history_problem: str,
    truncated_at: datetime | None,
    limit_figure: str = "",
    ahead_hours: float = 0.0,
) -> CustodyStatus:
    """Whether the object is in custody, from its orbit's age and its history.

    *elset_hours* is the newest element set's age, ``None`` when no epoch can
    be read. *normality* is the verdict on its latest burn, ``None`` when the
    history holds no burn. *history_problem* is why there is no history, empty
    when there is one. *limit_figure* says whose figure the limit is,
    "LEO figure applied to HEO/Molniya, unsourced for this regime", and is
    named beside the limit wherever it is shown (V0.40 review, SPC-215). *ahead_hours* is how far the newest set's
    epoch is after now, past the clock-skew tolerance (ElsetAge.ahead_hours): such a set is never current, so custody
    is lost and says why (SPC-226, evaluation F-38).
    """
    limit = f"{limit_hours:.0f} h"
    tail = _figure_tail(limit_figure)
    if elset_hours is None:
        return CustodyStatus(
            Custody.LOST,
            "Custody lost: there is no element set with a readable epoch, so neither "
            "its warning time nor its burns can be judged.",
        )
    if ahead_hours > 0.0:
        return CustodyStatus(
            Custody.LOST,
            f"Custody lost: its newest element set is dated {_age(ahead_hours)} in the future, so it cannot be read "
            "as current, and its warning time and its burns cannot be judged. Check the set's epoch and this "
            "server's clock.",
        )
    if elset_hours > limit_hours:
        return CustodyStatus(
            Custody.LOST,
            f"Custody lost: its newest element set is {_age(elset_hours)} old against a {limit} limit{tail}, "
            "so its warning time is out of date and a burn since then would not be seen.",
        )
    current = f"its orbit is current ({_age(elset_hours)} old, limit {limit}{tail})"
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
        f"Custody held: its orbit is {_age(elset_hours)} old (limit {limit}{tail}) and {elset_count} "
        f"element sets over {history_days:.0f} days judge its burns.",
    )


# ── Custody over a scenario's horizon (SPC-123) ──────────────────────────────

_SECONDS_PER_HOUR = 3600.0

_THROUGH = (
    "Custody {state} through the {h:g} h horizon: its newest element set stays within its {limit} limit{mid} until "
    "{until:%Y-%m-%d %H:%M} UTC, after the horizon ends."
)
#: _THROUGH when the newest element set reaches its limit exactly as the horizon ends: it is still within it then,
#: since custody is lost only once its age is strictly past the limit (SPC-119).
_THROUGH_TO_THE_END = (
    "Custody {state} through the {h:g} h horizon: its newest element set reaches its {limit} limit{mid} at "
    "{until:%Y-%m-%d %H:%M} UTC, as the horizon ends, and passes it only after."
)
_ALREADY_LOST = (
    "Custody lost for the whole {h:g} h horizon: its newest element set is already past its limit or has no "
    "readable epoch, so whether a burn is normal and how it changes your warning time cannot be judged until a "
    "newer one arrives."
)
_AGES_OUT = (
    "Custody lost from {at:%Y-%m-%d %H:%M} UTC, {from_h:.1f} h into the horizon, for up to {lost:.1f} h: its "
    "newest element set then passes its {limit} limit{tail}, so unless a newer one arrives, whether a burn is "
    "normal and how it changes your warning time cannot be judged."
)
#: Follows _THROUGH for custody degraded through the horizon, and precedes the loss for custody degraded first.
_DEGRADED_WHY = (
    "Degraded, neither held nor lost: how a burn changes your warning time can be judged, but whether it is normal "
    "cannot."
)
_DEGRADED_FIRST = "Custody degraded for {span} from the start of the horizon. " + _DEGRADED_WHY + " "
_BURN_AHEAD = (
    "Custody lost from the burn at {at:%Y-%m-%d %H:%M} UTC, {from_h:.1f} h into the horizon, for up to "
    "{lost:.1f} h: the burn is newer than the newest element set, so whether it is normal and how it changes your "
    "warning time cannot be judged until a newer element set arrives."
)
_BURN_MADE = (
    "Custody lost for the whole {h:g} h horizon: the burn at {at:%Y-%m-%d %H:%M} UTC, before the scenario epoch, "
    "is newer than the newest element set, so whether it was normal and how it changed your warning time cannot "
    "be judged until a newer element set arrives."
)


def span_text(hours: float) -> str:
    """A span of the horizon, *hours* above 0, to 0.1 h, or "under 0.1 h" for one that would read 0.0 h, so a short
    span of degraded custody is never shown as none (SPC-179)."""
    shown = f"{hours:.1f}"
    return "under 0.1 h" if shown == "0.0" else f"{shown} h"


class LossCause(StrEnum):
    """Why custody is lost within a horizon."""

    ALREADY_LOST = "already lost"
    AGES_OUT = "ages out"
    BURN = "burn"


class Horizon(NamedTuple):
    """The span custody is carried over: from the scenario epoch, for *hours*, with any hypothesised burn."""

    start_utc: datetime
    hours:     float
    burn_utc:  datetime | None = None


@dataclass(frozen=True)
class CustodyOverHorizon:
    """Custody at the scenario epoch, and when within the horizon it is lost, an upper bound; custody degraded at
    the epoch is degraded for *degraded_hours* before that (SPC-179)."""

    at_epoch:    Custody
    lost_from_h: float | None   # hours into the horizon; None when never lost within it
    lost_hours:  float
    cause:       LossCause | None
    sentence:    str
    degraded_hours: float = 0.0

    @property
    def maintained(self) -> bool:
        """Never lost and never degraded within the horizon: held throughout."""
        return self.lost_from_h is None and not self.degraded_hours

    @property
    def lost_from_epoch(self) -> bool:
        """Lost from the scenario epoch for the whole horizon, so no burn time could make it any worse."""
        return self.lost_from_h is not None and self.lost_from_h <= 0.0


def _burn_h(horizon: Horizon, elset_hours: float) -> float | None:
    """Hours from the epoch to a burn newer than the newest element set; None when there is none to count."""
    burn = horizon.burn_utc
    if burn is None or burn <= horizon.start_utc - timedelta(hours=elset_hours):
        return None
    return (burn - horizon.start_utc).total_seconds() / _SECONDS_PER_HOUR


def _figure_tail(figure: str) -> str:
    """", the LEO figure applied to HEO/Molniya, unsourced for this regime" beside a limit, or "" with none given."""
    return f", the {figure}" if figure else ""


def custody_over_horizon(
    status: CustodyStatus, *, elset_hours: float | None, limit_hours: float | None, horizon: Horizon,
    limit_figure: str = "",
) -> CustodyOverHorizon:
    """*status*, assessed at the horizon's start, carried over it assuming no newer element set arrives.

    *elset_hours* is the newest element set's age at the start and *limit_hours* its regime's limit, both None
    when its epoch cannot be read. The element set passes its limit once its age is strictly past it. Degraded
    custody cannot judge whether a burn is normal, so it is degraded, not held, until held custody would be lost.
    """
    h = horizon.hours
    if not h > 0.0:
        raise ValueError(f"a horizon has a length; got {h!r} h")
    if status.state is Custody.LOST or elset_hours is None or limit_hours is None or elset_hours > limit_hours:
        return CustodyOverHorizon(status.state, 0.0, h, LossCause.ALREADY_LOST, _ALREADY_LOST.format(h=h))
    over = _carried(status.state, elset_hours, limit_hours, horizon, limit_figure)
    if status.state is not Custody.DEGRADED:
        return over
    degraded_h = h if over.lost_from_h is None else over.lost_from_h
    if over.lost_from_h is None:
        sentence = f"{over.sentence} {_DEGRADED_WHY}"
    elif degraded_h > 0.0:
        sentence = _DEGRADED_FIRST.format(span=span_text(degraded_h)) + over.sentence
    else:
        sentence = over.sentence
    return dataclasses.replace(over, sentence=sentence, degraded_hours=degraded_h)


def _carried(
    state: Custody, elset_hours: float, limit_hours: float, horizon: Horizon, figure: str = "",
) -> CustodyOverHorizon:
    """Custody current at the epoch, *state* held or degraded, carried until the element set ages out or a burn
    newer than it, whichever is first."""
    h = horizon.hours
    limit = f"{limit_hours:.0f} h"
    # A limit within float tolerance of the end, on either side, is reached as the horizon ends (SPC-119).
    at_end = math.isclose(limit_hours - elset_hours, h)
    causes = [(h if at_end else limit_hours - elset_hours, LossCause.AGES_OUT)]
    burn_h = _burn_h(horizon, elset_hours)
    if burn_h is not None:
        causes.append((burn_h, LossCause.BURN))
    from_h, cause = min(causes, key=lambda c: c[0])
    if from_h >= h:
        until = horizon.start_utc + timedelta(hours=limit_hours - elset_hours)
        template = _THROUGH_TO_THE_END if at_end else _THROUGH
        mid = f"{_figure_tail(figure)}," if figure else ""
        sentence = template.format(state=state.value, h=h, limit=limit, mid=mid, until=until)
        return CustodyOverHorizon(state, None, 0.0, None, sentence)
    at = horizon.start_utc + timedelta(hours=from_h)
    if from_h < 0.0:
        return CustodyOverHorizon(state, 0.0, h, cause, _BURN_MADE.format(h=h, at=at))
    template = _BURN_AHEAD if cause is LossCause.BURN else _AGES_OUT
    sentence = template.format(at=at, from_h=from_h, lost=h - from_h, limit=limit, tail=_figure_tail(figure))
    return CustodyOverHorizon(state, from_h, h - from_h, cause, sentence)
