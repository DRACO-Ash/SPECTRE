"""Interactions: what a satellite has approached, counted only when a burn of its own explains it.

Concept section 4.9 (docs/threat_confidence_concept.md). An edge from an
object v to a target x exists only when it is manoeuvre-attributable: a
confirmed burn by v preceded the approach within 7 days, and the approach
is closer than it was before the burn. A pass that orbital mechanics would
have brought anyway, with no burn behind it, adds nothing.

SPC-172 reads the first source, the warning change the sweep already flies
(``domain/warning_change.py``). That compares reach, not distance: warning
time is the shortest flight time among the intercepts the object can fly
within the sweep's delta-V budget. So closer here means in reach sooner than
before the burn, beyond the tolerance ``warning_change.classify`` reads a
change with: newly in reach, or warning cut. Lengthened, unchanged and no
longer in reach make no edge.

No propagation yet: hostile seeds and hops are SPC-174, conjunctions and
closest approaches held per object SPC-173.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from spectre.domain.warning_change import Change, TargetWarning, classify

__all__ = ["ATTRIBUTION_WINDOW", "Burn", "Edge", "warning_edges"]

#: A burn explains an approach only if it can have happened no longer than
#: this before it (section 4.9). Tuned, not sourced.
ATTRIBUTION_WINDOW: timedelta = timedelta(days=7)
#: The changes that bring a target closer: in reach sooner than before the burn.
_CLOSER = frozenset({Change.NEWLY_IN_REACH, Change.CUT})


@dataclass(frozen=True)
class Burn:
    """One burn the warning change was flown across, as the edge rule reads it.

    *earliest* and *latest* are the times it can have happened (Pattern of
    Life's ``burn_window``); *epoch* is the estimator's burn epoch, the age
    clock its evidence is dated by. *detection* is its ``astro/dv_estimation``
    grade and *provider* the source of the element sets it was detected in.
    """

    epoch: datetime
    earliest: datetime
    latest: datetime
    confirmed: bool
    detection: str
    provider: str
    long_gap: bool = False


@dataclass(frozen=True)
class Edge:
    """A manoeuvre-attributable approach of *actor* to *target*, and the burns it rests on."""

    actor: str
    target: str
    ours: bool
    change: Change
    before_h: float | None
    after_h: float | None
    approach_at: datetime
    burns: tuple[Burn, ...]

    def __post_init__(self) -> None:
        if not self.burns:
            raise ValueError(f"{self.actor} to {self.target}: an edge rests on at least one burn")

    @property
    def burn_at(self) -> datetime:
        """The latest burn's epoch: the age clock, since the approach exists only once the orbit after it is held.

        Dated by the earliest instead, a later burn the edge itself rests on
        would read as a hostile burn judged after it and end its floor.
        """
        return max(b.epoch for b in self.burns)


def _explains(burn: Burn, approach_at: datetime) -> bool:
    """Confirmed, and within the window before the approach at every time it can have happened."""
    return burn.confirmed and burn.latest <= approach_at and approach_at - burn.earliest <= ATTRIBUTION_WINDOW


def warning_edges(actor: str, rows: Iterable[TargetWarning], burns: Sequence[Burn],
                  approach_at: datetime) -> tuple[Edge, ...]:
    """An edge from *actor* to each target the burns brought in reach, or in reach sooner, by *approach_at*.

    *rows* are the warning change's, before and after the burns; *burns* are
    every burn the change was flown across. The before orbit predates the
    first of them, so the change rests on them all: each must be confirmed
    and fall within 7 days before the approach, or there is no edge. Each
    row's change is read again by ``classify``, the warning change's own
    rule, so a mislabelled row cannot make an edge.
    """
    held = tuple(burns)
    if not held or not all(_explains(b, approach_at) for b in held):
        return ()
    return tuple(Edge(actor, r.name, r.ours, change, r.before_h, r.after_h, approach_at, held)
                 for r in rows if (change := classify(r.before_h, r.after_h)) in _CLOSER)
