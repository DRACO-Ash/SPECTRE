"""The NOTSO prior beside each adversary row, and applying the ones the operator ticked (SPC-130).

Every adversary row's suggestion is loaded when the panel opens, and again
on every change in the form (SPC-185, the owner's ruling of 2026-11-05 on
concept section 9, decision 16). Each row shows the P and Conf the bound red
track's NOTSO history suggests, with what they rest on, P's interval
(SPC-132) and a labelled control to apply them; or why none is offered.
Showing is not applying: applying stays the operator's tick, honoured at
Evaluate, and nothing is filled in on the operator's behalf (Threat
Understanding concept, section 7.5, items 2 and 3).

The suggestion is read from the NOTSO cache the operator syncs and, for Conf,
from the red object's element-set history only when one is already held; no
call here fetches anything. Time before the start of the red object's launch
year, read from its element set's international designator, is not counted. Evaluate applies a ticked suggestion only while it
is still the one shown: each tick posts the row's id and the values the panel
showed, and a suggestion that has moved since is refused, never applied in its
new form unseen.

The region also carries the record of which rows' P the operator edited
(SPC-183, the owner's ruling of 2026-11-05 on concept section 9, decision 11),
as a hidden field per edited row keyed by the row's id. It is asked again on
every change in the form, so a P posted as anything but the text the panel gave
every row is recorded then, and stays recorded after, through later changes and
re-renders; a removed row's record goes with it. htmx 1.9.12 names in
HX-Trigger-Name the element that asks, this region, not the field that changed,
so the record compares each row's P with the panel's text instead.
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
from spectre.domain.decision import DEFAULT_PROBABILITY, ActionType, AdversaryAction, BoundElset
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
#: The text the panel gives every row's P, the server-rendered rows, those opened from the sweep and those the Add
#: button builds alike: a P posted as anything else was edited (SPC-183).
UNEDITED_PROBABILITY = f"{DEFAULT_PROBABILITY}"


def edited_rows(ids: Sequence[str], probs: Sequence[str], recorded: Sequence[str]) -> list[str]:
    """The ids of the rows on the form whose P the operator edited: recorded as edited by an earlier change, or
    posted now as anything but UNEDITED_PROBABILITY. A recorded id no longer on the form is dropped (SPC-183)."""
    kept = set(recorded)
    return [
        row_id for i, row_id in enumerate(ids)
        if row_id in kept or (i < len(probs) and probs[i].strip() != UNEDITED_PROBABILITY)
    ]


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


class _Read(NamedTuple):
    """What every suggestion for the bound red track rests on: the cache's cover, red's notices and its profile."""

    cover:   Any
    notices: list[NOTSORecord]
    profile: Any | None


def _read(state: Any, red: BoundElset, now: datetime) -> _Read | NoPrior:
    """The NOTSO cache read once for *red* at *now*, or why no suggestion can be offered for any row."""
    if red.satno is None:
        return NoPrior(_NO_SATNO.format(red=red.stk_name))
    cache = get_notso_cache()
    cover = cache.covered_periods(now)
    if not cover:
        held = cache.total_records()
        return NoPrior(_UNDATED.format(n=held) if held else _EMPTY_CACHE)
    # The one grammar the NOTSO panel parses its cached records with.
    notices = notsos_from_cache_records(cache.get_for_satno(red.satno), red.satno)
    return _Read(cover, notices, _profile(state, red.satno, notices))


class _Offering:
    """One request's suggestions for the bound red track: the cache read once, when first asked, and each action
    type's suggestion worked out once, however many rows share it (SPC-185 asks for every row on every change)."""

    def __init__(self, state: Any, red: BoundElset, horizon_hours: float, now: datetime) -> None:
        self.state, self.red, self.horizon_hours, self.now = state, red, horizon_hours, now
        self.found: dict[ActionType, NotsoPrior | NoPrior] = {}
        self.base: _Read | NoPrior | None = None

    def prior(self, action_type: ActionType) -> NotsoPrior | NoPrior:
        if action_type not in self.found:
            if self.base is None:
                self.base = _read(self.state, self.red, self.now)
            self.found[action_type] = self._work_out(self.base, action_type)
        return self.found[action_type]

    def _work_out(self, base: _Read | NoPrior, action_type: ActionType) -> NotsoPrior | NoPrior:
        if isinstance(base, NoPrior):
            return base
        red = self.red
        return notso_prior(red.stk_name, action_type, base.notices, cover=base.cover, horizon_hours=self.horizon_hours,
                           profile=base.profile, launched=launch_year(red.tle), until=self.now)


def offered_prior(
    state: Any, red: BoundElset, action_type: ActionType, horizon_hours: float, now: datetime,
) -> NotsoPrior | NoPrior:
    """The NOTSO prior for *action_type* by the bound *red* over *horizon_hours*, or why none is offered."""
    return _Offering(state, red, horizon_hours, now).prior(action_type)


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
    """*action* holding *prior*'s P, and its Conf when it offers one, with the suggestion it accepted: P edited by
    the operator's tick, so never untouched (SPC-183)."""
    conf = action.confidence if prior.confidence is None else prior.confidence
    return dataclasses.replace(
        action, probability=prior.probability, confidence=conf, accepted_prior=prior, probability_edited=True,
    )


def _apply_one(offering: _Offering | None, action: AdversaryAction, tick: Tick, row: int) -> AdversaryAction | str:
    """*action* with its ticked suggestion applied, or why it cannot be; *offering* is None with no red track."""
    if offering is None:
        return _TICK_NO_RED.format(row=row)
    prior = offering.prior(action.action_type)
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
    offering = None if red is None else _Offering(state, red, *when)
    out: list[AdversaryAction] = []
    for row, action in enumerate(actions, start=1):
        tick = by_id.get(action.id)
        built = action if tick is None else _apply_one(offering, action, tick, row)
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

    ids:    Sequence[str]
    names:  Sequence[str]
    types:  Sequence[str]
    ticks:  Sequence[str]


def row_views(
    state: Any, asked: RowsAsked, red: BoundElset, when: tuple[float, datetime],
) -> list[RowView]:
    """Every posted row with its prior, read as the panel opens and on every change (SPC-185); a tick stays ticked
    only while it is the suggestion shown now."""
    read = ticks(asked.ticks) or []
    shown = {(t.row_id, t.token) for t in read}
    offering = _Offering(state, red, *when)
    views: list[RowView] = []
    for i, row_id in enumerate(asked.ids):
        action = _action_type(asked.types[i] if i < len(asked.types) else "")
        name = asked.names[i] if i < len(asked.names) else ""
        offered = offering.prior(action)
        prior = offered if isinstance(offered, NotsoPrior) else None
        views.append(RowView(
            row=i + 1, row_id=row_id, name=name,
            action=action.value.replace("_", " "), prior=prior,
            reason=offered.reason if isinstance(offered, NoPrior) else "",
            ticked=prior is not None and (row_id, prior.token) in shown,
        ))
    return views
