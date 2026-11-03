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
so it counts as lost for the whole horizon: nothing within it brings the
missing history.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

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


# ── Custody over a scenario's horizon (SPC-123) ──────────────────────────────

_SECONDS_PER_HOUR = 3600.0

_THROUGH = (
    "Custody {state} through the {h:g} h horizon: its newest element set stays within its {limit} limit until "
    "{until:%Y-%m-%d %H:%M} UTC, after the horizon ends."
)
_ALREADY_LOST = (
    "Custody lost for the whole {h:g} h horizon: its newest element set is already past its limit or has no "
    "readable epoch, so whether a burn is normal and how it changes your warning time cannot be judged until a "
    "newer one arrives."
)
_AGES_OUT = (
    "Custody lost from {at:%Y-%m-%d %H:%M} UTC, {from_h:.1f} h into the horizon, for up to {lost:.1f} h: its "
    "newest element set then passes its {limit} limit, so unless a newer one arrives, whether a burn is normal and "
    "how it changes your warning time cannot be judged."
)
_DEGRADED = (
    "Custody degraded for the whole {h:g} h horizon, which counts as lost: its orbit is current, so how a burn "
    "changes your warning time can be judged, but whether it is normal cannot, and custody needs both."
)
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


class LossCause(StrEnum):
    """Why custody is lost within a horizon."""

    ALREADY_LOST = "already lost"
    DEGRADED = "degraded"
    AGES_OUT = "ages out"
    BURN = "burn"


class Horizon(NamedTuple):
    """The span custody is carried over: from the scenario epoch, for *hours*, with any hypothesised burn."""

    start_utc: datetime
    hours:     float
    burn_utc:  datetime | None = None


@dataclass(frozen=True)
class CustodyOverHorizon:
    """Custody at the scenario epoch, and when within the horizon it is lost, an upper bound."""

    at_epoch:    Custody
    lost_from_h: float | None   # hours into the horizon; None when held throughout
    lost_hours:  float
    cause:       LossCause | None
    sentence:    str

    @property
    def maintained(self) -> bool:
        """Never lost within the horizon: held throughout."""
        return self.lost_from_h is None

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


def custody_over_horizon(
    status: CustodyStatus, *, elset_hours: float | None, limit_hours: float | None, horizon: Horizon,
) -> CustodyOverHorizon:
    """*status*, assessed at the horizon's start, carried over it assuming no newer element set arrives.

    *elset_hours* is the newest element set's age at the start and *limit_hours* its regime's limit, both None
    when its epoch cannot be read. The element set passes its limit once its age is strictly past it. Degraded
    custody cannot judge whether a burn is normal, so it is lost for the whole horizon.
    """
    h = horizon.hours
    if not h > 0.0:
        raise ValueError(f"a horizon has a length; got {h!r} h")
    if status.state is Custody.LOST or elset_hours is None or limit_hours is None or elset_hours > limit_hours:
        return CustodyOverHorizon(status.state, 0.0, h, LossCause.ALREADY_LOST, _ALREADY_LOST.format(h=h))
    if status.state is Custody.DEGRADED:
        return CustodyOverHorizon(status.state, 0.0, h, LossCause.DEGRADED, _DEGRADED.format(h=h))
    limit = f"{limit_hours:.0f} h"
    causes = [(limit_hours - elset_hours, LossCause.AGES_OUT)]
    burn_h = _burn_h(horizon, elset_hours)
    if burn_h is not None:
        causes.append((burn_h, LossCause.BURN))
    from_h, cause = min(causes, key=lambda c: c[0])
    if from_h >= h:
        until = horizon.start_utc + timedelta(hours=limit_hours - elset_hours)
        sentence = _THROUGH.format(state=status.state.value, h=h, limit=limit, until=until)
        return CustodyOverHorizon(status.state, None, 0.0, None, sentence)
    at = horizon.start_utc + timedelta(hours=from_h)
    if from_h < 0.0:
        return CustodyOverHorizon(status.state, 0.0, h, cause, _BURN_MADE.format(h=h, at=at))
    template = _BURN_AHEAD if cause is LossCause.BURN else _AGES_OUT
    sentence = template.format(at=at, from_h=from_h, lost=h - from_h, limit=limit)
    return CustodyOverHorizon(status.state, from_h, h - from_h, cause, sentence)
