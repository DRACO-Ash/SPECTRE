"""What a burn changed in the warning an operator has.

The operator's second question when something moves: "how long have I got, and
how did that burn change it?" The motivating sentence, from the handover case:
"that burn cut your warning on asset X from 14 hours to 3". The output is the
differential, not the state (owner and operator, 28 October 2026).

Warning time here is the figure the worst case card already shows: for each
target, the shortest flight time among the intercepts the object can fly
within the sweep's delta-V budget, from the moment it burns to arrival. The
caller works out that figure twice, once from the orbit before the burn and
once from the orbit after it, against the same targets at the same moment;
this module compares the two and words the result.

Pure functions over plain data. No I/O, no framework.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

__all__ = [
    "UNCHANGED_WITHIN_H",
    "BurnLine",
    "Change",
    "Status",
    "TargetWarning",
    "WarningChange",
    "burns_in_window",
    "classify",
    "compare",
    "footer",
    "headline",
    "is_new_burn",
    "least_warning_by_target",
    "newest_unconfirmed",
]

#: A change smaller than this reads as unchanged. Each orbit is offered its own
#: burn times, so a quarter of an hour either way can be timing rather than
#: reach. Tuned, not sourced, and the basis line on screen says so.
UNCHANGED_WITHIN_H: float = 0.25
#: At most this many targets are named in the headline; the table has the rest.
_NAMED_IN_HEADLINE: int = 3


class Change(Enum):
    NEWLY_IN_REACH = "newly in reach"
    CUT = "cut"
    UNCHANGED = "unchanged"
    LENGTHENED = "lengthened"
    NO_LONGER_IN_REACH = "no longer in reach"


class Status(Enum):
    """Whether the section shows figures, and if not, why."""

    FIGURES = "figures"
    NOT_COMPUTED = "not computed"
    CANNOT_SAY = "cannot say"
    NO_BURN = "no burn"


#: How much a change should draw the eye, most first.
_SEVERITY: dict[Change, int] = {
    Change.NEWLY_IN_REACH: 4, Change.CUT: 3, Change.LENGTHENED: 1, Change.NO_LONGER_IN_REACH: 1, Change.UNCHANGED: 0,
}


@dataclass(frozen=True)
class TargetWarning:
    """One target's warning before and after, in hours; ``None`` when out of reach."""

    name: str
    ours: bool
    before_h: float | None
    after_h: float | None
    change: Change


@dataclass(frozen=True)
class BurnLine:
    """One burn in the window: when, the is-this-normal verdict, and any caveat."""

    when: str
    verdict: str
    caveat: str = ""


@dataclass(frozen=True)
class WarningChange:
    """The section the sweep shows under "What the burn changed"."""

    status: Status
    headline: str
    rows: tuple[TargetWarning, ...] = ()
    footer: str = ""
    burns: tuple[BurnLine, ...] = ()
    notes: tuple[str, ...] = ()
    basis: str = ""
    worst: Change | None = None
    #: The changed rows only, for the table.
    changed: tuple[TargetWarning, ...] = field(default=())


def least_warning_by_target(entries: Iterable[Any], budget_m_s: float) -> dict[str, float]:
    """Each target's shortest flight time among intercepts within *budget_m_s*.

    Takes sweep entries (``target.target_name``, ``delta_v_m_s``,
    ``tof_hours``). A target with no feasible intercept is absent.
    """
    best: dict[str, float] = {}
    for e in entries:
        if e.delta_v_m_s > budget_m_s:
            continue
        name = e.target.target_name
        if name not in best or e.tof_hours < best[name]:
            best[name] = e.tof_hours
    return best


def classify(before_h: float | None, after_h: float | None) -> Change:
    """One target's change under the tolerance."""
    if before_h is None:
        return Change.UNCHANGED if after_h is None else Change.NEWLY_IN_REACH
    if after_h is None:
        return Change.NO_LONGER_IN_REACH
    if abs(after_h - before_h) <= UNCHANGED_WITHIN_H:
        return Change.UNCHANGED
    return Change.CUT if after_h < before_h else Change.LENGTHENED


def compare(
    targets: Sequence[tuple[str, bool]], before: Mapping[str, float], after: Mapping[str, float],
) -> list[TargetWarning]:
    """Every target's row, the shortest warning after the burn first, out of reach last.

    *targets* is ``(name, ours)``: ``ours`` marks a friendly asset, which the
    operator reads as "your warning".
    """
    rows = [
        TargetWarning(name, ours, before.get(name), after.get(name), classify(before.get(name), after.get(name)))
        for name, ours in targets
    ]
    return sorted(rows, key=lambda r: (r.after_h is None, r.after_h if r.after_h is not None else 0.0, r.name))


def worst_change(rows: Sequence[TargetWarning]) -> Change | None:
    """The change that should draw the eye most, or ``None`` with no rows."""
    return max((r.change for r in rows), key=lambda c: _SEVERITY[c], default=None)


def _whose(row: TargetWarning) -> str:
    return "your" if row.ours else "the"


def _clause(row: TargetWarning, hours: Callable[[float], str]) -> str:
    if row.change is Change.NEWLY_IN_REACH and row.after_h is not None:
        return f"put {row.name} in reach with {hours(row.after_h)} warning"
    before = hours(row.before_h) if row.before_h is not None else "out of reach"
    after = hours(row.after_h) if row.after_h is not None else "out of reach"
    return f"cut {_whose(row)} warning on {row.name} from {before} to {after}"


def _join(clauses: Sequence[str]) -> str:
    return clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _quiet_headline(rows: Sequence[TargetWarning], burns: str, budget_m_s: float, hours: Callable[[float], str]) -> str:
    """The headline when no warning was cut and nothing came into reach."""
    count = len(rows)
    if all(r.before_h is None and r.after_h is None for r in rows):
        return (f"None of the {count} targets swept is in reach within {budget_m_s:g} m/s, "
                f"before or after {'that burn' if burns == 'That burn' else 'those burns'}.")
    moved = [r for r in rows if r.change is not Change.UNCHANGED and r.before_h is not None and r.after_h is not None]
    whose = "your" if rows and all(r.ours for r in rows) else "the"
    line = f"{burns} did not shorten {whose} warning on any of the {count} targets swept."
    if not moved:
        return f"{line} None changed by more than {UNCHANGED_WITHIN_H * 60:.0f} minutes."
    biggest = max(moved, key=lambda r: abs((r.after_h or 0.0) - (r.before_h or 0.0)))
    before = hours(biggest.before_h) if biggest.before_h is not None else "out of reach"
    after = hours(biggest.after_h) if biggest.after_h is not None else "out of reach"
    return f"{line} Largest change: {biggest.name}, {before} to {after}."


def headline(
    rows: Sequence[TargetWarning], burn_count: int, budget_m_s: float, hours: Callable[[float], str],
) -> str:
    """The main line: which warnings the burn cut, and what it put in reach.

    The targets named are those cut or newly in reach, the shortest warning
    after the burn first, at most three; *hours* formats a duration as the
    worst case card does.
    """
    burns = "That burn" if burn_count == 1 else f"Those {burn_count} burns"
    shortened = [r for r in rows if r.change in (Change.CUT, Change.NEWLY_IN_REACH)]
    if not shortened:
        return _quiet_headline(rows, burns, budget_m_s, hours)
    named = shortened[:_NAMED_IN_HEADLINE]
    line = f"{burns} {_join([_clause(r, hours) for r in named])}."
    extra = len(shortened) - len(named)
    return f"{line} {extra} more changed: see the table." if extra else line


def footer(rows: Sequence[TargetWarning]) -> str:
    """How many targets did not change, so the table's absences are accounted for."""
    unchanged = sum(1 for r in rows if r.change is Change.UNCHANGED and r.before_h is not None)
    unreached = sum(1 for r in rows if r.before_h is None and r.after_h is None)
    parts = []
    if unchanged:
        parts.append(f"{unchanged} other target{'s' if unchanged != 1 else ''} unchanged")
    if unreached:
        parts.append(f"{unreached} out of reach before and after")
    return "; ".join(parts) + "." if parts else ""


def burns_in_window(manoeuvres: Iterable[Any], now: datetime, limit_hours: float) -> list[Any]:
    """Confirmed burns whose latest possible time is within *limit_hours* of *now*.

    The latest possible time, the end of ``burn_window``, so a burn that could
    have happened inside the window is never dropped for being undated. The
    window is the regime's element-set age limit, the one custody uses.
    """
    return [m for m in manoeuvres if (now - m.burn_window[1]).total_seconds() / 3600.0 <= limit_hours]


def is_new_burn(manoeuvre: Any, accounted_until: datetime | None) -> bool:
    """Whether a burn has not yet been told to the operator.

    New only when the earliest time it can have happened is after the
    post-burn element set of the last burn already accounted for, so a
    re-estimate that moves a known burn's epoch a few minutes is not
    announced twice.
    """
    return accounted_until is None or manoeuvre.burn_window[0] > accounted_until


def newest_unconfirmed(candidates: Iterable[Any], after: datetime | None) -> Any | None:
    """The newest unconfirmed detection later than *after*, to name and not count."""
    newer = [c for c in candidates if after is None or c.burn_window[0] > after]
    return max(newer, key=lambda c: c.burn_window[0], default=None)
