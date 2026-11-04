"""The NOTSO prior beside each adversary row, and applying the ones the operator ticked (SPC-130).

The panel shows, for each adversary row, the P and Conf the bound red track's
NOTSO history suggests, with what they rest on and a labelled control to apply
them; or why none is offered. Nothing is filled in on the operator's behalf
(Threat Understanding concept, section 7.5, items 2 and 3).

The suggestion is read from the NOTSO cache the operator syncs and, for Conf,
from the red object's element-set history only when one is already held; no
call here fetches anything. Time before the start of the red object's launch
year, read from its element set's international designator, is not counted. Evaluate applies a ticked suggestion only while it
is still the one shown: each tick posts the row's id and the values the panel
showed, and a suggestion that has moved since is refused, never applied in its
new form unseen.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any, NamedTuple

from spectre.astro.notso import NOTSORecord
from spectre.data.notso_cache import get_notso_cache
from spectre.domain.decision import ActionType, AdversaryAction, BoundElset
from spectre.domain.notso_prior import NoPrior, NotsoPrior, notso_prior
from spectre.web.log_safety import log_safe
from spectre.web.routes.pol import notso_behaviour_profile, notsos_from_cache_records

logger = logging.getLogger(__name__)

#: The longest horizon the panel takes, h, as the evaluate route does.
MAX_HORIZON_H = 720.0
NO_RED = "Bind a red track to be offered a NOTSO suggestion for each row's P and Conf."
NO_HORIZON = "Enter a horizon above 0 h and at most 720 h to be offered a NOTSO suggestion."
_NO_SATNO = "{red} has no catalogue number to look up in the NOTSO cache, so no suggestion is offered."
_EMPTY_CACHE = "The NOTSO cache holds no records yet, so no suggestion is offered. Sync it from the NOTSO panel."
_UNDATED = (
    "The NOTSO cache's {n} records give no creation time up to now, so the time the cache covers is unknown and no "
    "suggestion is offered."
)
_UNREADABLE = "A NOTSO suggestion ticked cannot be read; reload the panel."
_TICK_NO_RED = "Row {row} asks for the NOTSO suggestion, but no red track is bound to suggest one for."
_TICK_NONE = "Row {row} asks for the NOTSO suggestion, but none is offered now: {reason}"
_TICK_MOVED = (
    "The NOTSO suggestion for row {row} has changed since it was shown; it now reads: {now} Tick it again to apply "
    "it, or untick it to keep your own values."
)
_TICK_PARTS = 3


def _profile(state: Any, satno: int, notices: list[NOTSORecord]) -> Any | None:
    """The behaviour profile from red's element-set history when one is held, whatever its age; else None."""
    held = getattr(state, "elset_histories", {}).get(satno)
    if held is None or held.pol is None:
        return None
    return notso_behaviour_profile(held.pol, list(notices))[1]


#: Line 1 of an element set: the catalogue number and class, then the international designator's launch year.
_LAUNCH_YEAR = re.compile(r"^1 .{6} (\d{2})\d{3}")
#: Two-digit launch years from this one up belong to the 1900s, as the element-set format reads them.
_LAST_CENTURY_FROM = 57


def launch_year(tle: str) -> int | None:
    """The launch year *tle*'s international designator gives, or None when it gives none."""
    for line in tle.splitlines():
        found = _LAUNCH_YEAR.match(line.strip())
        if found:
            year = int(found.group(1))
            return year + (1900 if year >= _LAST_CENTURY_FROM else 2000)
    return None


def offered_prior(
    state: Any, red: BoundElset, action_type: ActionType, horizon_hours: float, now: datetime,
) -> NotsoPrior | NoPrior:
    """The NOTSO prior for *action_type* by the bound *red* over *horizon_hours*, or why none is offered."""
    if red.satno is None:
        return NoPrior(_NO_SATNO.format(red=red.stk_name))
    cache = get_notso_cache()
    cover = cache.covered_periods(now)
    if not cover:
        held = cache.total_records()
        return NoPrior(_UNDATED.format(n=held) if held else _EMPTY_CACHE)
    # The one grammar the NOTSO panel parses its cached records with.
    notices = notsos_from_cache_records(cache.get_for_satno(red.satno), red.satno)
    return notso_prior(red.stk_name, action_type, notices, cover=cover, horizon_hours=horizon_hours,
                       profile=_profile(state, red.satno, notices), launched=launch_year(red.tle))


def horizon(raw: str) -> float | None:
    """The horizon posted, in (0, MAX_HORIZON_H], or None when it is not one."""
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and 0.0 < value <= MAX_HORIZON_H else None


class Tick(NamedTuple):
    """One ticked apply control: the row's id and the values the panel showed for it."""

    row_id: str
    token:  str


def ticks(raws: Sequence[str]) -> list[Tick] | None:
    """The ticks posted, or None when one cannot be read."""
    read: list[Tick] = []
    for raw in raws:
        parts = raw.split("|")
        if len(parts) != _TICK_PARTS or not parts[0]:
            return None
        read.append(Tick(parts[0], f"{parts[1]}|{parts[2]}"))
    return read


class Applied(NamedTuple):
    """The adversary rows with each ticked suggestion applied, or the sentence that refuses them."""

    actions: list[AdversaryAction]
    problem: str | None


def _applied(action: AdversaryAction, prior: NotsoPrior) -> AdversaryAction:
    """*action* holding *prior*'s P, and its Conf when it offers one, with the suggestion it accepted."""
    conf = action.confidence if prior.confidence is None else prior.confidence
    return dataclasses.replace(action, probability=prior.probability, confidence=conf, accepted_prior=prior)


class _Ask(NamedTuple):
    """What a suggestion is worked out from: the session, the bound red track, the horizon and the scenario epoch."""

    state: Any
    red:   BoundElset | None
    when:  tuple[float, datetime]


def _apply_one(ask: _Ask, action: AdversaryAction, tick: Tick, row: int) -> AdversaryAction | str:
    """*action* with its ticked suggestion applied, or why it cannot be."""
    if ask.red is None:
        return _TICK_NO_RED.format(row=row)
    prior = offered_prior(ask.state, ask.red, action.action_type, *ask.when)
    if isinstance(prior, NoPrior):
        return _TICK_NONE.format(row=row, reason=prior.reason)
    if prior.token != tick.token:
        return _TICK_MOVED.format(row=row, now=prior.suggestion)
    return _applied(action, prior)


def apply_priors(
    state: Any, actions: list[AdversaryAction], raws: Sequence[str], red: BoundElset | None,
    when: tuple[float, datetime],
) -> Applied:
    """*actions* with each ticked suggestion applied; *when* is the horizon and the scenario epoch.

    A tick for a row no longer on the form is ignored: the row it was ticked for is gone.
    """
    read = ticks(raws)
    if read is None:
        return Applied([], _UNREADABLE)
    by_id = {t.row_id: t for t in read}
    ask = _Ask(state, red, when)
    out: list[AdversaryAction] = []
    for row, action in enumerate(actions, start=1):
        tick = by_id.get(action.id)
        built = action if tick is None else _apply_one(ask, action, tick, row)
        if isinstance(built, str):
            return Applied([], built)
        out.append(built)
    accepted = [a.id for a in out if a.accepted_prior is not None]
    if accepted:
        logger.info("decision_prior: NOTSO suggestion applied to rows %s", log_safe(", ".join(accepted)))
    return Applied(out, None)


class RowView(NamedTuple):
    """One adversary row as the region lists it: its number, id, name and action, and its prior or why none."""

    row:    int
    row_id: str
    name:   str
    action: str
    prior:  NotsoPrior | None
    reason: str
    ticked: bool


def _action_type(raw: str) -> ActionType:
    try:
        return ActionType(raw)
    except ValueError:
        return ActionType.MANOEUVRE


class RowsAsked(NamedTuple):
    """The adversary rows the panel posts, as parallel columns, and the ticks it holds."""

    ids:   Sequence[str]
    names: Sequence[str]
    types: Sequence[str]
    ticks: Sequence[str]


def row_views(
    state: Any, asked: RowsAsked, red: BoundElset, when: tuple[float, datetime],
) -> list[RowView]:
    """Each posted row with its prior; a tick stays ticked only while it is the suggestion shown now."""
    shown = {(t.row_id, t.token) for t in (ticks(asked.ticks) or [])}
    views: list[RowView] = []
    for i, row_id in enumerate(asked.ids):
        action = _action_type(asked.types[i] if i < len(asked.types) else "")
        offered = offered_prior(state, red, action, *when)
        prior = offered if isinstance(offered, NotsoPrior) else None
        views.append(RowView(
            row=i + 1, row_id=row_id, name=asked.names[i] if i < len(asked.names) else "",
            action=action.value.replace("_", " "), prior=prior,
            reason=offered.reason if isinstance(offered, NoPrior) else "",
            ticked=prior is not None and (row_id, prior.token) in shown,
        ))
    return views
