"""Is this burn normal for this object?

The operator's first question when something moves (owner and operator,
28 October 2026). Pattern of Life already labels each burn against the
regime's cited budgets: station keeping, relocation, plane change. That says
whether a burn is routine for a satellite of its kind. It does not say whether
it is routine for THIS satellite, and that is the comparison an analyst makes
first: "this burn is consistent with its station keeping" and "this burn is
unlike anything in 200 days of history" are different sentences, and the data
to write both was already held.

Each burn is judged only against the burns before it, so the verdict on an
old burn never changes when a newer one arrives. The rules are below, each
with the reason for its threshold. The thresholds are tuned, not sourced, and
the basis line shown with every verdict says so.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

__all__ = ["BASIS", "Burn", "BurnNormality", "Normality", "burns_from_views", "judge_burn", "judge_history"]


class Normality(Enum):
    ROUTINE = "routine"
    UNUSUAL = "unusual"
    UNPRECEDENTED = "unprecedented"
    NOT_ENOUGH_HISTORY = "not enough history"


#: Shown with every verdict, so it is never read as more than it is.
BASIS = (
    "Judged against this object's own history only, not against similar objects. "
    "Burns below the detection floor are not seen, so a quiet history can hide small burns. "
    "The thresholds are tuned, not sourced."
)

# Fewer earlier burns than this, or a shorter history, and there is no pattern
# to compare with. Five is the fewest that gives four intervals for a cadence.
_MIN_PRIOR_BURNS: int = 5
_MIN_HISTORY_DAYS: float = 30.0

# A burn this many times the largest earlier burn of any kind is "unlike
# anything". Element-set noise moves a station-keeping estimate by tenths of a
# m/s, so a burn a little above the largest is not, and a factor rather than
# an offset keeps that true for a 2 m/s keeper and a 40 m/s relocator alike.
# At 1.5 a 21 m/s raise among 14 m/s ones read as unlike anything in 80 days,
# which is unusual, not unprecedented; double is unmistakable.
_UNPRECEDENTED_SIZE_FACTOR: float = 2.0
# The same test within the burn's own kind, at a lower bar: large for what
# this object usually does of that kind, but not beyond everything it has done.
_UNUSUAL_SIZE_FACTOR: float = 1.25
# A kind needs this many earlier examples before "large for its kind" means
# anything.
_MIN_SAME_KIND: int = 5
# A kind making up less than this share of the earlier burns is one the object
# rarely flies.
_RARE_KIND_SHARE: float = 0.10
# A burn sooner than this fraction of the usual interval breaks the cadence.
_EARLY_FRACTION: float = 0.25


@dataclass(frozen=True)
class Burn:
    """One confirmed burn, as the judgement needs it."""

    epoch: datetime
    delta_v_m_s: float
    label: str
    #: The element sets either side were far enough apart to hide other burns.
    long_gap: bool = False


@dataclass(frozen=True)
class BurnNormality:
    """The verdict on one burn, in the operator's words, and what it rests on."""

    verdict: Normality
    sentence: str
    burn: Burn
    prior_burns: int
    history_days: float
    reasons: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    basis: str = field(default=BASIS)

    @property
    def is_alert(self) -> bool:
        """Whether this verdict should draw the eye."""
        return self.verdict in (Normality.UNUSUAL, Normality.UNPRECEDENTED)


def _m_s(value: float) -> str:
    """Delta-V as an operator reads it: tenths below 10 m/s, whole above."""
    return f"{value:.1f}" if value < 10.0 else f"{value:.0f}"


def _days(value: float) -> str:
    return f"{value:.0f}"


def _a(label: str) -> str:
    """The indefinite article for *label*."""
    return "an" if label[:1].lower() in "aeiou" else "a"


def _usual_interval_days(earlier: list[Burn]) -> float | None:
    epochs = sorted(b.epoch for b in earlier)
    gaps = [(b - a).total_seconds() / 86400.0 for a, b in zip(epochs, epochs[1:], strict=False)]
    return statistics.median(gaps) if len(gaps) >= _MIN_PRIOR_BURNS - 1 else None


def _unprecedented(burn: Burn, earlier: list[Burn], same: list[Burn]) -> list[str]:
    reasons = []
    if not same:
        reasons.append(f"No earlier burn was {_a(burn.label)} {burn.label}.")
    largest = max(b.delta_v_m_s for b in earlier)
    if burn.delta_v_m_s > largest * _UNPRECEDENTED_SIZE_FACTOR:
        reasons.append(f"The largest of its {len(earlier)} earlier burns was {_m_s(largest)} m/s.")
    return reasons


def _unusual(burn: Burn, earlier: list[Burn], same: list[Burn]) -> list[str]:
    reasons = []
    if len(same) / len(earlier) < _RARE_KIND_SHARE:
        reasons.append(f"{len(same)} of its {len(earlier)} earlier burns was {_a(burn.label)} {burn.label}.")
    if len(same) >= _MIN_SAME_KIND:
        largest_same = max(b.delta_v_m_s for b in same)
        if burn.delta_v_m_s > largest_same * _UNUSUAL_SIZE_FACTOR:
            reasons.append(
                f"Larger than any of its {len(same)} earlier {burn.label} burns "
                f"(up to {_m_s(largest_same)} m/s)."
            )
    usual = _usual_interval_days(earlier)
    previous = max(b.epoch for b in earlier)
    gap = (burn.epoch - previous).total_seconds() / 86400.0
    if usual is not None and gap < usual * _EARLY_FRACTION:
        reasons.append(f"It came {_days(gap)} days after the previous burn, against a usual {_days(usual)}.")
    return reasons


def _routine_sentence(burn: Burn, earlier: list[Burn], same: list[Burn], days: float) -> str:
    kin = (f"in line with its {len(earlier)} earlier burns" if len(same) == len(earlier)
           else f"like {len(same)} of its {len(earlier)} earlier burns")
    low = min(b.delta_v_m_s for b in same)
    high = max(b.delta_v_m_s for b in same)
    return (
        f"Routine for this object: this {_m_s(burn.delta_v_m_s)} m/s {burn.label} is "
        f"{kin} over {_days(days)} days ({_m_s(low)} to {_m_s(high)} m/s)."
    )


def judge_burn(burn: Burn, history: list[Burn], history_start: datetime) -> BurnNormality:
    """Judge *burn* against the burns in *history* that came before it.

    *history_start* is the first element set held, so a quiet stretch at the
    start of the history still counts towards how long the object was watched.
    """
    earlier = [b for b in history if b.epoch < burn.epoch]
    days = (burn.epoch - history_start).total_seconds() / 86400.0
    caveats = ("the element sets either side were far enough apart to hide other burns",) if burn.long_gap else ()

    def verdict(kind: Normality, sentence: str, reasons: list[str] | None = None) -> BurnNormality:
        return BurnNormality(kind, sentence, burn, len(earlier), days, tuple(reasons or ()), caveats)

    if len(earlier) < _MIN_PRIOR_BURNS or days < _MIN_HISTORY_DAYS:
        return verdict(
            Normality.NOT_ENOUGH_HISTORY,
            f"Too little history to judge: {len(earlier)} earlier burns over {_days(days)} days.",
        )

    same = [b for b in earlier if b.label == burn.label]
    reasons = _unprecedented(burn, earlier, same)
    if reasons:
        return verdict(
            Normality.UNPRECEDENTED,
            f"Unlike anything in its last {_days(days)} days: this "
            f"{_m_s(burn.delta_v_m_s)} m/s {burn.label}. " + " ".join(reasons),
            reasons,
        )
    reasons = _unusual(burn, earlier, same)
    if reasons:
        return verdict(
            Normality.UNUSUAL,
            f"Unusual for this object: this {_m_s(burn.delta_v_m_s)} m/s {burn.label}. "
            + " ".join(reasons),
            reasons,
        )
    return verdict(Normality.ROUTINE, _routine_sentence(burn, earlier, same, days))


def judge_history(burns: list[Burn], history_start: datetime) -> list[BurnNormality]:
    """Every burn in *burns*, oldest first, each judged against those before it."""
    ordered = sorted(burns, key=lambda b: b.epoch)
    return [judge_burn(b, ordered, history_start) for b in ordered]


def burns_from_views(views: list[Any]) -> list[Burn]:
    """Pattern of Life's confirmed manoeuvre views as burns to judge.

    Takes ``pol_assessment.ManoeuvreView`` items: their m/s figure, their
    operator label, and the astro manoeuvre's measured burn epoch.
    """
    return [
        Burn(
            epoch=v.manoeuvre.burn_epoch,
            delta_v_m_s=v.delta_v_m_s,
            label=v.classification,
            long_gap=bool(getattr(v.manoeuvre, "long_gap", False)),
        )
        for v in views
    ]
