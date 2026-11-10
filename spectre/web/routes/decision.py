"""Decision Engine routes: scenario evaluation, from lookups, a sampled or computed closest approach and custody.

GET  /plan/decision/panel      → scenario builder input form, with a manoeuvre hypothesis per adversary row (SPC-114)
GET  /plan/decision/bind       → the bind fields, rebuilt from the held objects (SPC-100)
GET  /plan/decision/from-sweep → the panel filled from an entry of the held threat sweep (SPC-150); nothing evaluated
GET  /plan/decision/prior      → the NOTSO suggestion beside each adversary row, with its basis (SPC-130)
POST /plan/decision/evaluate   → the ranked results partial for a scenario that samples nothing; for one that
                                 samples, a job the page polls (SPC-113); with a game tree of 2 or 3 turns beside
                                 the matrix when asked for (SPC-142)
GET  /plan/decision/job        → the job's progress, or its results once done
POST /plan/decision/job/cancel → stop the job; nothing is scored
"""

from __future__ import annotations

import asyncio
import dataclasses
import html
import itertools
import logging
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NamedTuple, cast

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES
from spectre.astro.propagator import TLE_ERRORS
from spectre.astro.response_burn import BurnAxis
from spectre.domain.decision import (
    ADVERSARY_FIELDS_NOTE,
    BINDING_NOTE,
    DEFAULT_CUSTODY_GAP_FRACTION,
    DEFAULT_PROBABILITY,
    MAX_SAMPLE_HOURS,
    MAX_TURNS,
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    Seen,
    SelectorStrategy,
    longest_horizon_h,
    needs_a_run,
    pre_manoeuvre_state,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.decision_transfer import MAX_BURN_M_S, MAX_TRANSFER_BURNS, TransferBurn
from spectre.domain.decision_tree import depth_refusal, evaluate_tree
from spectre.domain.manoeuvre_calibration import from_km_s, to_km_s
from spectre.web.auth import require_login
from spectre.web.decision_binding import bind_scenario
from spectre.web.decision_custody import HISTORY_WAIT_S, history_fetch, red_custody, with_red_custody
from spectre.web.decision_from_sweep import (
    DEFAULT_SAMPLES,
    EARLIEST_BURN_H,
    MAX_SAMPLES,
    MIN_SAMPLES,
    SweepPrefill,
    detected_burn,
    open_from_sweep,
)
from spectre.web.decision_job import (
    CustodyRead,
    JobState,
    cancel_job,
    evaluated_line,
    job_view,
    new_job,
    start_job,
)
from spectre.web.decision_prior import (
    NO_HORIZON,
    NO_RED,
    RowsAsked,
    apply_priors,
    edited_rows,
    horizon,
    row_views,
)
from spectre.web.decision_threat import held_picture
from spectre.web.decision_trajectory import trajectory_links
from spectre.web.deps import render
from spectre.web.log_safety import log_safe
from spectre.web.models import SessionKey, User
from spectre.web.planning_state import SessionState, get_session_state
from spectre.web.tree_view import tree_view

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/decision", tags=["decision"])

# Weights summing to less than this are treated as unset rather than scaled up.
_MIN_WEIGHT_TOTAL = 0.01
# Rows per side, as README.md documents, and the longest horizon in hours.
_MAX_ROWS = 5
_MAX_HORIZON_H = 720.0
# The hypothesis fields' ranges (SPC-114). A burn more than 72 h before the scenario epoch is older than the
# longest staleness limit, so the orbit it starts from would be refused as out of date anyway.
_MAX_DV_M_S = MAX_BURN_M_S
_MAX_SIGMA_M_S = 100.0
_MIN_SAMPLES, _MAX_SAMPLES, _DEFAULT_SAMPLES = MIN_SAMPLES, MAX_SAMPLES, DEFAULT_SAMPLES
_EARLIEST_BURN_H = EARLIEST_BURN_H
_DIRECTION_LABELS = ("radial direction", "in-track direction", "cross-track direction")
_HYPOTHESIS_RELOAD = "The hypothesis fields do not match the adversary rows; reload the panel."
_HYPOTHESIS_UNKNOWN = "Choose a listed archetype for row {row}."
_HYPOTHESIS_ZERO = (
    "The direction in row {row} is zero in all three parts; leave all three blank for the archetype's assumed "
    "in-track direction."
)
_HYPOTHESIS_NO_RED = (
    "A manoeuvre hypothesis in row {row} starts from the bound red track: bind a red track, or set its archetype "
    "to None."
)
_HYPOTHESIS_NO_STATE = "The red element set cannot be propagated to the burn time in row {row}."
# A burn the sweep fixed at its own UTC time (SPC-150), and the detected burn evaluate builds from the history.
_BURN_AT_UNREAD = "The burn time in row {row} cannot be read; reload the panel."
_BURN_AT_OLD = (
    "The burn time fixed in row {row}, {at}, is more than 72 h before the scenario epoch. Open the scenario from "
    "the sweep again."
)
_BURN_AT_LATE = "The burn time fixed in row {row}, {at}, is after the horizon. Lengthen the horizon to cover it."
_DETECTED_NO_TIME = "A detected burn in row {row} needs its burn time; reload the panel."
_DETECTED_GONE = (
    "The detected burn in row {row}, at {at}, is no longer in the held history for {red}. Open the scenario from "
    "the sweep again."
)
# The transfer's later burns, posted beside the first burn's fixed time (SPC-184).
_THEN_UNREAD = "The transfer's later burns in row {row} cannot be read; reload the panel."
_THEN_ORDER = "The transfer's later burns in row {row} are not in time order after its first; reload the panel."
_THEN_LATE = "Burn {k} of the transfer in row {row}, at {at}, is after the horizon. Lengthen the horizon to cover it."
_THEN_MANY = "The transfer in row {row} carries more than {most} burns; reload the panel."
_THEN_UNFIXED = "The transfer's later burns in row {row} need its first burn's fixed time; reload the panel."
_THEN_TOO_BIG = (
    "Burn {k} of the transfer in row {row} is {dv:,.0f} m/s, over the {most:,.0f} m/s a burn may be. Set the row's "
    "archetype to None to keep it a lookup, or open a cheaper entry from the sweep."
)
#: A later burn posts its UTC time and its prograde, normal and radial parts.
_THEN_FIELDS = 4
_SECONDS_PER_HOUR = 3600.0
# Our burn per friendly row (SPC-121): a target separation up to this, km, and a budget up to this, m/s.
_MAX_TARGET_KM = 100_000.0
_MAX_BUDGET_M_S = 1000.0
_DEFAULT_BUDGET_M_S = 50.0
_RESPONSE_RELOAD = "The response fields do not match the friendly rows; reload the panel."
_AXIS_UNKNOWN = "Choose a listed axis for row {row}."
# The game tree (SPC-142): what the operator states turn 1 showed of red, by the form's names.
_OBSERVED_UNKNOWN = "Choose a listed observation for turn 1."
_OBSERVED_ONE_TURN = (
    "What turn 1 shows is read only by a tree: set a turn depth of 2 or 3, or leave turn 1's observation not "
    "stated. With one turn there is no later pick for it to update."
)
_OBSERVATIONS: dict[str, Seen] = {seen.name.lower(): seen for seen in Seen}
_OBSERVATION_LABELS: dict[Seen, str] = {
    Seen.BURN: "A burn: custody lost at a burn in turn 1",
    Seen.NO_BURN: "No burn: custody held through turn 1",
    Seen.NOTHING: "Nothing: custody degraded, lost for another reason, or not read",
}
_AXIS_LABELS: dict[BurnAxis, str] = {
    BurnAxis.CHEAPEST: "Cheapest, from the manoeuvre library",
    BurnAxis.RADIAL: "Radial",
    BurnAxis.IN_TRACK: "In-track",
    BurnAxis.CROSS_TRACK: "Cross-track",
}


class _Inputs:
    """The form's numbers, read one by one, keeping the first problem found.

    The first problem is kept rather than raised. Raised, its sentence reached
    the page through the caught exception, which CodeQL's exception-exposure
    query reports however deliberate the sentence is.
    """

    def __init__(self) -> None:
        self.problem: str | None = None

    def refuse(self, sentence: str) -> float:
        if self.problem is None:
            self.problem = sentence
        return 0.0

    def number(
        self, raw: str | None, label: str, high: float = 1.0, *, positive: bool = False, low: float = 0.0,
    ) -> float:
        """One form number in [*low*, *high*], or in (*low*, *high*] when *positive*.

        Every value this engine takes is a fraction in [0, 1], a time, the
        horizon or a hypothesis field. It accepted any float, NaN and negatives
        included, and a blank field produced a 422 that htmx does not swap, so
        the panel did nothing (audit F-164).
        """
        try:
            value = float(raw or "")
        except ValueError:
            return self.refuse(f"Enter a number for {label}.")
        low_ok = value > low if positive else value >= low
        if not (math.isfinite(value) and low_ok and value <= high):
            bound = f"above {low:g} and at most {high:g}" if positive else f"between {low:g} and {high:g}"
            return self.refuse(f"{_capital(label)} must be {bound}; got {raw}.")
        return value

    def optional(self, raw: str | None, label: str, low: float, high: float) -> float | None:
        """A number in [*low*, *high*], or None when the field is blank: a blank takes the archetype's value."""
        if not (raw or "").strip():
            return None
        return self.number(raw, label, high, low=low)

    def whole(self, raw: str | None, label: str, low: int, high: int) -> int:
        """A whole number in [*low*, *high*]; anything else, a blank included, is refused naming the field."""
        try:
            value = int((raw or "").strip())
        except ValueError:
            value = low - 1
        if not low <= value <= high:
            got = raw if (raw or "").strip() else "a blank field"
            self.refuse(f"{_capital(label)} must be a whole number between {low} and {high}; got {got}.")
            return low
        return value

    def column(self, raws: list[str] | None, label: str, high: float = 1.0) -> list[float]:
        """One numeric column of rows, each checked, named by its row."""
        return [self.number(raw, f"{label} in row {i + 1}", high) for i, raw in enumerate(raws or [])]

    def rows(self, adv_ids: list[str] | None, fr_ids: list[str] | None) -> None:
        """Both sides take 1 to 5 rows, as README.md documents."""
        if not (1 <= len(adv_ids or []) <= _MAX_ROWS and 1 <= len(fr_ids or []) <= _MAX_ROWS):
            self.refuse(
                f"Define 1 to {_MAX_ROWS} adversary actions and 1 to {_MAX_ROWS} friendly responses."
            )


def _capital(label: str) -> str:
    return f"{label[0].upper()}{label[1:]}"


def _err(msg: str) -> HTMLResponse:
    """Return an inline error partial with the message escaped.

    This partial is built by hand rather than rendered by Jinja, so nothing
    autoescapes it. One call site passes exception text that an upstream
    library could quote operator-supplied form input into, which is the
    reflected-XSS shape already confirmed on the scenario-time route, so the
    escape is applied here and covers every call site at once. It sits at
    module level so that every route shares it.
    """
    return HTMLResponse(f'<p class="error-msg">{html.escape(msg)}</p>')


def _at[T](values: Sequence[T], index: int, default: T) -> T:
    """Return ``values[index]``, or *default* when the form sent fewer rows."""
    return values[index] if index < len(values) else default


def _action_type(types: Sequence[str], index: int) -> ActionType:
    """Parse one row's action type, falling back to a manoeuvre."""
    try:
        return ActionType(types[index]) if index < len(types) else ActionType.MANOEUVRE
    except ValueError:
        return ActionType.MANOEUVRE


class _AdversaryColumns(NamedTuple):
    """The adversary form's columns, one entry per row: each row's custody gap share apart from its confidence, and
    the ids of the rows whose P was edited (SPC-183)."""

    ids:   list[str]
    names: list[str]
    types: list[str]
    probs: list[float]
    confs: list[float]
    gaps:  list[float]
    edited: tuple[str, ...] = ()


def _adversary_rows(
    columns: _AdversaryColumns, hypotheses: Sequence[AdversaryHypothesis | None],
) -> list[AdversaryAction]:
    """Build the adversary actions from the form's parallel arrays, each with its hypothesis or None."""
    return [
        AdversaryAction(
            id=columns.ids[i],
            name=_at(columns.names, i, f"ADV-{i+1}"),
            action_type=_action_type(columns.types, i),
            probability=float(_at(columns.probs, i, DEFAULT_PROBABILITY)),
            confidence=float(_at(columns.confs, i, 0.5)),
            hypothesis=_at(hypotheses, i, None),
            custody_gap_fraction=_at(columns.gaps, i, DEFAULT_CUSTODY_GAP_FRACTION),
            probability_edited=columns.ids[i] in columns.edited,
        )
        for i in range(len(columns.ids))
    ]


class _HypothesisColumns(NamedTuple):
    """The hypothesis section's columns as posted, one raw entry per adversary row (SPC-114).

    The last three are hidden and optional (SPC-150, SPC-184): a burn the sweep fixed at its own UTC time, whether it
    is the detected burn to build from the held history, and the transfer's later burns. A form without them reads
    each as blank on every row.
    """

    archetypes: list[str]
    dvs:        list[str]
    dir_r:      list[str]
    dir_i:      list[str]
    dir_c:      list[str]
    sigmas:     list[str]
    samples:    list[str]
    burns_h:    list[str]
    burns_at:   list[str]
    detected:   list[str]
    then:       list[str]


class _HypothesisEntry(NamedTuple):
    """One row's checked hypothesis fields; None for a field left blank, which takes the archetype's."""

    archetype: str
    dv_m_s:    float | None
    direction: tuple[float, float, float] | None
    sigma_m_s: float | None
    samples:   int
    burn_h:    float
    #: The burn's own UTC time when the sweep fixed it (SPC-150); burn_h is then counted from it, not read.
    burn_at:   datetime | None = None
    #: Build from the held history's detected burn at burn_at, from the element set before it (SPC-001).
    detected:  bool = False
    #: The transfer's later burns, each at its own UTC time, one action with the first (SPC-184).
    then:      tuple[TransferBurn, ...] = ()


def _hypothesis_columns(form: _ScenarioForm, rows: int, inputs: _Inputs) -> _HypothesisColumns | None:
    """The columns, or None when the form posts none; columns of another length than the rows are refused.

    Every row posts all eight, blanks included, so the columns stay aligned with the adversary rows. The two
    hidden columns (SPC-150) may be absent, and are then blank on every row; posted, they align too.
    """
    raw = (
        form.hyp_archetypes, form.hyp_dvs, form.hyp_dir_r, form.hyp_dir_i, form.hyp_dir_c, form.hyp_sigmas,
        form.hyp_samples, form.hyp_burns_h,
    )
    if all(column is None for column in raw):
        return None
    optional = (form.hyp_burns_at, form.hyp_detected, form.hyp_then)
    if any(len(column or []) != rows for column in raw) or any(
        column is not None and len(column) != rows for column in optional
    ):
        inputs.refuse(_HYPOTHESIS_RELOAD)
        return None
    filled = [[""] * rows if column is None else list(column) for column in optional]
    return _HypothesisColumns(*(list(column or []) for column in raw), *filled)


def _direction(inputs: _Inputs, parts: Sequence[str], row: int) -> tuple[float, float, float] | None:
    """A RIC direction, each part in [-1, 1]; all blank is the archetype's assumed in-track, all zero is refused."""
    values = [inputs.optional(raw, f"{label} in row {row}", -1.0, 1.0) for raw, label in zip(
        parts, _DIRECTION_LABELS, strict=True,
    )]
    if all(v is None for v in values):
        return None
    r, i, c = (v or 0.0 for v in values)
    if r == i == c == 0.0:
        inputs.refuse(_HYPOTHESIS_ZERO.format(row=row))
    return (r, i, c)


def _when(moment: datetime) -> str:
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


def _hours_from(moment: datetime, now: datetime) -> float:
    return (moment - now).total_seconds() / _SECONDS_PER_HOUR


def _read_burn_at(raw: str) -> datetime | None:
    """A posted UTC burn time, or None when it is not a time with its offset."""
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _fixed_burn(
    inputs: _Inputs, columns: _HypothesisColumns, index: int, now: datetime, horizon: float,
) -> tuple[datetime | None, bool]:
    """The burn time the sweep fixed in row *index*, checked against the hypothesis limits, and whether it is the
    detected burn; (None, False) when the row counts its burn in hours from the scenario epoch (SPC-150)."""
    raw_at, row = columns.burns_at[index], index + 1
    detected = bool(columns.detected[index].strip())
    if not raw_at.strip():
        if detected:
            inputs.refuse(_DETECTED_NO_TIME.format(row=row))
        return None, False
    moment = _read_burn_at(raw_at.strip())
    if moment is None:
        inputs.refuse(_BURN_AT_UNREAD.format(row=row))
        return None, False
    hours = _hours_from(moment, now)
    if hours < _EARLIEST_BURN_H:
        inputs.refuse(_BURN_AT_OLD.format(row=row, at=_when(moment)))
    elif hours > horizon:
        inputs.refuse(_BURN_AT_LATE.format(row=row, at=_when(moment)))
    return moment, detected


def _later_burn(raw: str) -> TransferBurn | None:
    """One posted later burn, "UTC prograde normal radial" in m/s; None unless each part reads and is in range."""
    parts = raw.split()
    if len(parts) != _THEN_FIELDS:
        return None
    at = _read_burn_at(parts[0])
    try:
        values = [float(p) for p in parts[1:]]
    except ValueError:
        return None
    if at is None or not all(math.isfinite(v) for v in values):
        return None
    return TransferBurn(at, values[0], values[1], values[2])


def _then_problem(burns: Sequence[TransferBurn], first: datetime, row: int, end: datetime) -> str | None:
    """Why the read later burns cannot be carried: out of time order from the first, or after the horizon."""
    big = next(((k, b) for k, b in enumerate(burns, 2) if b.dv_m_s > MAX_BURN_M_S), None)
    if big is not None:   # by its size, as burn 1's delta-V field is held
        return _THEN_TOO_BIG.format(k=big[0], row=row, dv=big[1].dv_m_s, most=MAX_BURN_M_S)
    times = [first, *(b.at_utc for b in burns)]
    if any(later < earlier for earlier, later in itertools.pairwise(times)):
        return _THEN_ORDER.format(row=row)
    late = next(((k, b) for k, b in enumerate(burns, 2) if b.at_utc > end), None)
    return None if late is None else _THEN_LATE.format(k=late[0], row=row, at=_when(late[1].at_utc))


def _later_burns(
    inputs: _Inputs, raw: str, fixed: tuple[datetime | None, bool], row: int, end: datetime,
) -> tuple[TransferBurn, ...]:
    """Row *row*'s posted later burns, checked; empty when blank. *fixed* is the first burn's fixed time and whether
    the row is a detected burn, which carries none; *end* is the horizon's end (SPC-184)."""
    text = raw.strip()
    if not text:
        return ()
    first, detected = fixed
    pieces = text.split(";")
    burns = [_later_burn(piece) for piece in pieces]
    if first is None or detected:
        problem: str | None = _THEN_UNFIXED.format(row=row)
    elif len(pieces) + 1 > MAX_TRANSFER_BURNS:
        problem = _THEN_MANY.format(row=row, most=MAX_TRANSFER_BURNS)
    elif any(b is None for b in burns):
        problem = _THEN_UNREAD.format(row=row)
    else:
        problem = _then_problem(cast("list[TransferBurn]", burns), first, row, end)
    if problem is not None:
        inputs.refuse(problem)
        return ()
    return tuple(cast("list[TransferBurn]", burns))


def _entered(
    inputs: _Inputs, columns: _HypothesisColumns, index: int, *, detected: bool,
) -> tuple[float | None, tuple[float, float, float] | None]:
    """Row *index*'s entered delta-V and direction; none for a detected burn, which carries its own (SPC-150)."""
    if detected:
        return None, None
    row = index + 1
    dv = inputs.optional(columns.dvs[index], f"delta-V (m/s) in row {row}", 0.0, _MAX_DV_M_S)
    return dv, _direction(inputs, (columns.dir_r[index], columns.dir_i[index], columns.dir_c[index]), row)


def _entry(
    inputs: _Inputs, columns: _HypothesisColumns, index: int, horizon: float, now: datetime,
) -> _HypothesisEntry | None:
    """Row *index*'s checked fields, or None when its archetype is None, so the row stays a lookup."""
    archetype = columns.archetypes[index].strip()
    if not archetype:
        return None
    row = index + 1
    if archetype not in MANOEUVRE_ARCHETYPES:
        inputs.refuse(_HYPOTHESIS_UNKNOWN.format(row=row))
    burn_at, detected = _fixed_burn(inputs, columns, index, now, horizon)
    dv_m_s, direction = _entered(inputs, columns, index, detected=detected)
    return _HypothesisEntry(
        archetype=archetype,
        dv_m_s=dv_m_s,
        direction=direction,
        sigma_m_s=inputs.optional(
            columns.sigmas[index], f"delta-V spread, 1 sigma (m/s) in row {row}", 0.0, _MAX_SIGMA_M_S,
        ),
        samples=inputs.whole(columns.samples[index], f"samples in row {row}", _MIN_SAMPLES, _MAX_SAMPLES),
        burn_h=_hours_from(burn_at, now) if burn_at is not None else inputs.number(
            columns.burns_h[index], f"burn time (hours from the scenario epoch) in row {row}", horizon,
            low=_EARLIEST_BURN_H,
        ),
        burn_at=burn_at,
        detected=detected,
        then=_later_burns(inputs, columns.then[index], (burn_at, detected), row, now + timedelta(hours=horizon)),
    )


def _entries(
    inputs: _Inputs, form: _ScenarioForm, rows: int, horizon: float, now: datetime,
) -> list[_HypothesisEntry | None]:
    """Each adversary row's hypothesis fields, checked; empty when the form posts no hypothesis section."""
    columns = _hypothesis_columns(form, rows, inputs)
    if columns is None:
        return []
    return [_entry(inputs, columns, i, horizon, now) for i in range(rows)]


def _hypothesis(entry: _HypothesisEntry, red_tle: str, now: datetime) -> AdversaryHypothesis | None:
    """The row's hypothesis from the red track's state at the burn time; None when it cannot be propagated there.

    A burn the sweep fixed is at its own UTC time, however long the panel was open before Evaluate (SPC-150).
    """
    at = pre_manoeuvre_state(red_tle, entry.burn_at or now + timedelta(hours=entry.burn_h))
    if at is None:
        return None
    if entry.dv_m_s is None:
        built = AdversaryHypothesis.from_archetype(
            entry.archetype, at, direction_ric=entry.direction, n_samples=entry.samples,
        )
    else:
        built = AdversaryHypothesis.from_entered(
            entry.dv_m_s, entry.direction, at, archetype=entry.archetype, n_samples=entry.samples,
        )
    built = built if entry.sigma_m_s is None else built.with_spread(entry.sigma_m_s)
    return built.with_transfer(entry.then) if entry.then else built


class _Hypotheses(NamedTuple):
    """Each row's hypothesis or None, or the sentence that refuses them."""

    carried: list[AdversaryHypothesis | None]
    problem: str | None


def _detected_hypothesis(entry: _HypothesisEntry, burn: Any) -> AdversaryHypothesis | None:
    """The detected *burn*'s hypothesis, from the element set before it (hypothesis_from_tle_record, SPC-001), with
    the row's archetype's dispersions; None when that element set cannot be propagated to the burn."""
    try:
        built = AdversaryHypothesis.from_detection(
            burn.tle_before, burn, archetype=entry.archetype, n_samples=entry.samples,
        )
    except TLE_ERRORS:
        logger.warning("Detected-burn hypothesis could not be propagated for %s", log_safe(entry.burn_at))
        return None
    return built if entry.sigma_m_s is None else built.with_spread(entry.sigma_m_s)


def _row_hypothesis(
    state: SessionState, entry: _HypothesisEntry, red: BoundElset, row: int, now: datetime,
) -> AdversaryHypothesis | str:
    """One row's hypothesis, or the sentence that refuses it: a detected burn from the held history, any other
    from the bound red track's state at its burn time."""
    if entry.detected and entry.burn_at is not None:
        burn = detected_burn(state, red.satno, entry.burn_at)
        if burn is None:
            return _DETECTED_GONE.format(row=row, at=_when(entry.burn_at), red=red.stk_name)
        built = _detected_hypothesis(entry, burn)
    else:
        built = _hypothesis(entry, red.tle, now)
    return _HYPOTHESIS_NO_STATE.format(row=row) if built is None else built


def _hypotheses(
    entries: Sequence[_HypothesisEntry | None], binding: ScenarioBinding | None, now: datetime,
    state: SessionState,
) -> _Hypotheses:
    """Build each row's hypothesis from the bound red track at its burn time (SPC-114), or from the held history's
    detected burn (SPC-150)."""
    red = None if binding is None else binding.red
    carried: list[AdversaryHypothesis | None] = []
    for row, entry in enumerate(entries, start=1):
        if entry is None:
            carried.append(None)
            continue
        if red is None:
            return _Hypotheses([], _HYPOTHESIS_NO_RED.format(row=row))
        built = _row_hypothesis(state, entry, red, row, now)
        if isinstance(built, str):
            return _Hypotheses([], built)
        carried.append(built)
    return _Hypotheses(carried, None)


class _ResponseColumns(NamedTuple):
    """The friendly-response form's numeric columns, one entry per row."""

    costs: list[float]
    reversibilities: list[float]
    times_h: list[float]


def _friendly_rows(
    ids: list[str], names: list[str], types: list[str], columns: _ResponseColumns,
    burns: Sequence[ResponseBurnSpec | None] = (),
) -> list[FriendlyResponse]:
    """Build the friendly responses from the form's parallel arrays, each manoeuvre with its burn or None."""
    return [
        FriendlyResponse(
            id=ids[i],
            name=_at(names, i, f"FR-{i+1}"),
            action_type=_action_type(types, i),
            cost=float(_at(columns.costs, i, 0.5)),
            reversibility=float(_at(columns.reversibilities, i, 0.5)),
            time_to_execute_hours=float(_at(columns.times_h, i, 6.0)),
            burn=_at(burns, i, None),
        )
        for i in range(len(ids))
    ]


def _burn_columns(form: _ScenarioForm, rows: int, inputs: _Inputs) -> tuple[list[str], list[str], list[str]] | None:
    """The three burn columns, or None when the form posts none; columns of another length than the rows are
    refused. Every row posts all three, blanks included, so they stay aligned with the friendly rows (SPC-121)."""
    raw = (form.fr_targets, form.fr_budgets, form.fr_axes)
    if all(column is None for column in raw):
        return None
    if any(len(column or []) != rows for column in raw):
        inputs.refuse(_RESPONSE_RELOAD)
        return None
    targets, budgets, axes = (list(column or []) for column in raw)
    return targets, budgets, axes


def _burn_spec(inputs: _Inputs, target: str, budget: str, axis: str, row: int) -> ResponseBurnSpec | None:
    """One manoeuvre row's burn: None with no target; the budget 50 m/s when blank; the axis from the list."""
    if not target.strip():
        return None
    target_km = inputs.number(target, f"target separation (km) in row {row}", _MAX_TARGET_KM, positive=True)
    budget_m_s = _DEFAULT_BUDGET_M_S
    if budget.strip():
        budget_m_s = inputs.number(budget, f"delta-V budget (m/s) in row {row}", _MAX_BUDGET_M_S, positive=True)
    try:
        chosen = BurnAxis(axis.strip())
    except ValueError:
        inputs.refuse(_AXIS_UNKNOWN.format(row=row))
        return None
    if inputs.problem is not None:
        return None
    return ResponseBurnSpec(target_km=target_km, budget_km_s=to_km_s(budget_m_s), axis=chosen)


def _burns(inputs: _Inputs, form: _ScenarioForm) -> list[ResponseBurnSpec | None]:
    """Each friendly row's burn, read only for a manoeuvre row; empty when the form posts no burn fields."""
    types = form.fr_types or []
    columns = _burn_columns(form, len(form.fr_ids or []), inputs)
    if columns is None:
        return []
    return [
        _burn_spec(inputs, target, budget, axis, i + 1) if _action_type(types, i) is ActionType.MANOEUVRE else None
        for i, (target, budget, axis) in enumerate(zip(*columns, strict=True))
    ]


def _strategy(raw: str) -> SelectorStrategy:
    """Parse the selector, falling back to minimax, the cautious rule."""
    try:
        return SelectorStrategy(raw)
    except ValueError:
        return SelectorStrategy.MINIMAX


def _normalised_weights(*weights: float) -> tuple[float, ...]:
    """Scale the scoring weights to sum to one; all-zero weights are left as given."""
    total = sum(weights)
    if total < _MIN_WEIGHT_TOTAL:
        total = 1.0
    return tuple(w / total for w in weights)


def _bind_context(state: SessionState, red_sat: str = "", blue_sat: str = "") -> dict[str, object]:
    """The bind fields' context: the held objects, and each choice only while it is still held on its side."""
    held_red = {t.stk_name for t in state.red_tracks}
    held_blue = {a.stk_name for a in state.blue_assets}
    return {
        "red_tracks": state.red_tracks,
        "blue_assets": state.blue_assets,
        "selected_red": red_sat if red_sat in held_red else "",
        "selected_blue": blue_sat if blue_sat in held_blue else "",
        "binding_note": BINDING_NOTE,
    }


def _panel_context(state: SessionState, prefill: SweepPrefill | None = None) -> dict[str, object]:
    """The scenario builder's context, filled from a sweep entry when *prefill* fills it (SPC-150)."""
    filled = prefill is not None and not prefill.problem
    red, blue = (prefill.red, prefill.blue) if filled and prefill is not None else ("", "")
    return {
        "pol": getattr(state, "last_pol_analysis", None),
        "adversary_fields_note": ADVERSARY_FIELDS_NOTE,
        "default_gap": DEFAULT_CUSTODY_GAP_FRACTION,
        "default_probability": DEFAULT_PROBABILITY,
        "prefill": prefill,
        **_bind_context(state, red, blue),
        **_hypothesis_context(),
    }


@router.get("/panel", response_class=HTMLResponse)
async def decision_panel(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Return the decision engine scenario builder panel."""
    return render(request, "partials/decision_panel.html", _panel_context(get_session_state(current_user)))


@router.get("/from-sweep", response_class=HTMLResponse)
async def decision_from_sweep(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    entry: Annotated[str, Query()] = "",
    sweep: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """The panel filled from entry *entry* of the held sweep whose epoch is *sweep* (SPC-150).

    It fills the red track, the blue asset when the target is held as one, the departure burn and the latest
    detected burn, and says so; it fills no probability or confidence and evaluates nothing. A sweep that is no
    longer the latest, or an entry it does not hold, opens the panel unfilled with the reason.
    """
    state = get_session_state(current_user)
    prefill = await asyncio.to_thread(open_from_sweep, state, entry, sweep, _utc_now())
    logger.info(
        "decision_from_sweep: entry %s of sweep %s by %s: %s",
        log_safe(entry), log_safe(sweep), log_safe(current_user.username), log_safe(prefill.problem or "filled"),
    )
    return render(request, "partials/decision_panel.html", _panel_context(state, prefill))


class _PriorQuery(BaseModel):
    """The panel's fields the NOTSO suggestion reads, sent with every change (SPC-130); the rest are ignored."""

    red_sat:       str = ""
    horizon_hours: str = ""
    adv_ids:       list[str] = Field(default_factory=list, alias="adv_id")
    adv_names:     list[str] = Field(default_factory=list, alias="adv_name")
    adv_types:     list[str] = Field(default_factory=list, alias="adv_type")
    adv_priors:    list[str] = Field(default_factory=list, alias="adv_prior")
    # The rows loaded from NOTSO (SPC-131): each loaded row's hidden field, and the id of the row whose Load from
    # NOTSO control sent this request.
    adv_loaded:    list[str] = Field(default_factory=list, alias="adv_loaded")
    # Each row's P as posted, and the rows recorded as edited by an earlier change (SPC-183).
    adv_probs:     list[str] = Field(default_factory=list, alias="adv_prob")
    adv_p_edited:  list[str] = Field(default_factory=list, alias="adv_p_edited")


def _prior_context(state: SessionState, query: _PriorQuery, now: datetime) -> dict[str, object]:
    """The region's context: each adversary row's NOTSO suggestion for the bound red track, or the one note why none
    can be worked out yet; and, whatever it says, the rows whose P was edited (SPC-183)."""
    edited = edited_rows(query.adv_ids[:_MAX_ROWS], query.adv_probs, query.adv_p_edited)
    hours = horizon(query.horizon_hours)
    red_sat = query.red_sat.strip()
    if not red_sat or hours is None:
        return {"note": NO_HORIZON if red_sat else NO_RED, "rows": [], "edited": edited}
    bound = bind_scenario(state, red_sat, "", now)
    red = None if bound.binding is None else bound.binding.red
    if red is None:
        return {"note": bound.problem or NO_RED, "rows": [], "edited": edited}
    asked = RowsAsked(query.adv_ids[:_MAX_ROWS], query.adv_names, query.adv_types, query.adv_priors,
                      query.adv_loaded)
    return {"note": "", "rows": row_views(state, asked, red, (hours, now)), "edited": edited}


@router.get("/prior", response_class=HTMLResponse)
async def decision_prior_region(
    request: Request,
    query: Annotated[_PriorQuery, Query()],
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """The NOTSO suggestion beside each adversary row, with its basis and a labelled control to apply it (SPC-130).

    The panel asks again on every change, sending its fields, so the suggestion follows the red track, the horizon
    and each row's type. Nothing fills P or Conf here; a tick is applied at Evaluate, and only while it still matches.
    """
    context = await asyncio.to_thread(_prior_context, get_session_state(current_user), query, _utc_now())
    return render(request, "partials/decision_prior.html", context)


def _hypothesis_context() -> dict[str, object]:
    """The hypothesis section's choices and hint (SPC-114): each archetype with its typical delta-V in m/s."""
    return {
        "archetypes": [
            (key, f"{row.name}, typical {from_km_s(row.typical_delta_v_km_s):g} m/s")
            for key, row in MANOEUVRE_ARCHETYPES.items()
        ],
        "default_samples": _DEFAULT_SAMPLES,
        "min_samples": _MIN_SAMPLES,
        "max_samples": _MAX_SAMPLES,
        "max_sample_hours": f"{MAX_SAMPLE_HOURS:,.0f}",
        "longest_horizon": f"{longest_horizon_h(_DEFAULT_SAMPLES):.1f}",
        # Our burns to size count against the cap too (SPC-121).
        "longest_horizon_one_burn": f"{longest_horizon_h(_DEFAULT_SAMPLES, burns=1):.1f}",
        "longest_horizon_five_burns": f"{longest_horizon_h(_DEFAULT_SAMPLES, burns=5):.1f}",
        "burn_axes": [(axis.value, label) for axis, label in _AXIS_LABELS.items()],
        "default_budget": f"{_DEFAULT_BUDGET_M_S:g}",
        "max_budget": f"{_MAX_BUDGET_M_S:g}",
        "max_target": f"{_MAX_TARGET_KM:g}",
        # The game tree's fields (SPC-142).
        "max_turns": MAX_TURNS,
        "observations": [(seen.name.lower(), _OBSERVATION_LABELS[seen]) for seen in Seen],
    }


@router.get("/bind", response_class=HTMLResponse)
async def decision_bind(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    red_sat: Annotated[str, Query()] = "",
    blue_sat: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """Return the bind fields rebuilt from the session, keeping a choice that is still held.

    The panel re-fetches these each time the block comes into view, so an
    object added or removed since the panel loaded is offered or dropped.
    """
    state = get_session_state(current_user)
    return render(request, "partials/decision_bind_fields.html", _bind_context(state, red_sat, blue_sat))


class _ScenarioForm(BaseModel):
    """The decision panel's fields, bound from the form by name.

    One model rather than twenty route parameters (python:S107). Each table
    column arrives as a parallel form array under its singular field name,
    which the alias keeps.
    """

    scenario_name: str = "Unnamed Scenario"
    # No default: FastAPI reads a blank field as absent, and a default would
    # turn a cleared horizon into a silent 72 h.
    horizon_hours: str | None = None
    # Adversary actions (up to 4)
    adv_ids: list[str] | None = Field(default=None, alias="adv_id")
    adv_names: list[str] | None = Field(default=None, alias="adv_name")
    adv_types: list[str] | None = Field(default=None, alias="adv_type")
    adv_probs: list[str] | None = Field(default=None, alias="adv_prob")
    adv_confs: list[str] | None = Field(default=None, alias="adv_conf")
    # Each row's custody gap share (SPC-161), apart from its confidence; a form without the column takes the default.
    adv_gaps: list[str] | None = Field(default=None, alias="adv_gap")
    # Friendly responses (up to 4)
    fr_ids: list[str] | None = Field(default=None, alias="fr_id")
    fr_names: list[str] | None = Field(default=None, alias="fr_name")
    fr_types: list[str] | None = Field(default=None, alias="fr_type")
    fr_costs: list[str] | None = Field(default=None, alias="fr_cost")
    fr_revs: list[str] | None = Field(default=None, alias="fr_rev")
    fr_times: list[str] | None = Field(default=None, alias="fr_time")
    # Our burn per friendly row (SPC-121): every row posts all three, blanks included; only manoeuvre rows are read.
    fr_targets: list[str] | None = Field(default=None, alias="fr_target")
    fr_budgets: list[str] | None = Field(default=None, alias="fr_budget")
    fr_axes: list[str] | None = Field(default=None, alias="fr_axis")
    # Scoring weights
    w_custody: str = "0.35"
    w_ca: str = "0.25"
    w_dv: str = "0.20"
    w_time: str = "0.10"
    w_rev: str = "0.10"
    strategy: str = "minimax"
    # The game tree (SPC-142): its turn depth, 1 to 3, and what the operator states turn 1 showed, blank for none.
    turns: str = "1"
    observed: str = ""
    # The held objects the scenario is about (SPC-100), by stk_name; blank is not bound.
    # These are the intercept engine's field names; the sweep posts only red_sat.
    red_sat: str = ""
    blue_sat: str = ""
    # A manoeuvre hypothesis per adversary row (SPC-114): every row posts all eight, blanks included.
    hyp_archetypes: list[str] | None = Field(default=None, alias="hyp_archetype")
    hyp_dvs: list[str] | None = Field(default=None, alias="hyp_dv")
    hyp_dir_r: list[str] | None = None
    hyp_dir_i: list[str] | None = None
    hyp_dir_c: list[str] | None = None
    hyp_sigmas: list[str] | None = Field(default=None, alias="hyp_sigma")
    hyp_samples: list[str] | None = None
    hyp_burns_h: list[str] | None = Field(default=None, alias="hyp_burn_h")
    # Hidden and optional (SPC-150): a burn the sweep fixed at its own UTC time, and whether it is the detected burn.
    hyp_burns_at: list[str] | None = Field(default=None, alias="hyp_burn_at")
    hyp_detected: list[str] | None = None
    # Hidden and optional (SPC-184): the transfer's later burns, each "UTC prograde normal radial" in m/s, by ";".
    hyp_then: list[str] | None = None
    # Each NOTSO suggestion the operator ticked to apply (SPC-130): the row's id and the P and Conf it showed.
    adv_priors: list[str] | None = Field(default=None, alias="adv_prior")
    # The rows whose P the NOTSO region recorded as edited (SPC-183), by id; a form without them records none.
    adv_p_edited: list[str] | None = Field(default=None, alias="adv_p_edited")


class _Parsed(NamedTuple):
    """The form's checked numbers: horizon, weights, both sides' columns, each row's hypothesis fields, our burns,
    and the game tree's turn depth and stated observation (SPC-142)."""

    horizon:   float
    weights:   list[float]
    adversary: _AdversaryColumns
    friendly:  _ResponseColumns
    entries:   list[_HypothesisEntry | None]
    burns:     list[ResponseBurnSpec | None]
    turns:     int = 1
    observed:  Seen | None = None


def _observed(inputs: _Inputs, raw: str) -> Seen | None:
    """What the operator states turn 1 showed, by its listed name; None when blank, and anything else refused."""
    key = raw.strip()
    if not key:
        return None
    seen = _OBSERVATIONS.get(key)
    if seen is None:
        inputs.refuse(_OBSERVED_UNKNOWN)
    return seen


def _parse(inputs: _Inputs, form: _ScenarioForm, now: datetime) -> _Parsed:
    """Every number on the form, checked at scenario epoch *now*; the first problem is kept on *inputs*."""
    inputs.rows(form.adv_ids, form.fr_ids)
    horizon = inputs.number(form.horizon_hours, "the horizon in hours", _MAX_HORIZON_H, positive=True)
    weights = [
        inputs.number(w, "each scoring weight")
        for w in (form.w_custody, form.w_ca, form.w_dv, form.w_time, form.w_rev)
    ]
    adversary = _AdversaryColumns(
        form.adv_ids or [], form.adv_names or [], form.adv_types or [],
        inputs.column(form.adv_probs, "probability"), inputs.column(form.adv_confs, "confidence"),
        inputs.column(form.adv_gaps, "custody gap share"),
        tuple(edited_rows(form.adv_ids or [], form.adv_probs or [], form.adv_p_edited or [])),
    )
    friendly = _ResponseColumns(
        inputs.column(form.fr_costs, "cost"), inputs.column(form.fr_revs, "reversibility"),
        inputs.column(form.fr_times, "time to execute (hours)", _MAX_HORIZON_H),
    )
    entries = _entries(inputs, form, len(adversary.ids), horizon, now)
    turns = inputs.whole(form.turns, "the turn depth", 1, MAX_TURNS)
    observed = _observed(inputs, form.observed)
    if observed is not None and turns == 1:
        # One turn has no later pick for it to update, and no tree to say so on: refused, not dropped unsaid.
        inputs.refuse(_OBSERVED_ONE_TURN)
    return _Parsed(horizon, weights, adversary, friendly, entries, _burns(inputs, form), turns, observed)


def _utc_now() -> datetime:
    """The scenario epoch's clock, a seam so a test can stand at a chosen moment."""
    return datetime.now(UTC)


@router.post("/evaluate", response_class=HTMLResponse)
async def decision_evaluate(
    request: Request,
    form: Annotated[_ScenarioForm, Form()],
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Evaluate a decision scenario and return the ranked results partial, or the job that will.

    The scenario epoch is now, the moment Evaluate is pressed; a hypothesis's burn time counts from it (SPC-114).
    A bound red track's custody is read here, as the sweep reads it (SPC-123), so the evaluation does no I/O; when
    that would wait on a UDL history fetch, the read is the first stage of a job whose progress says so
    (SPC-119). The sweep's Threat picture for the bound red track is read from the session (SPC-171).
    """
    inputs = _Inputs()
    now = _utc_now()
    parsed = _parse(inputs, form, now)
    if inputs.problem is not None:
        return _err(inputs.problem)
    state = get_session_state(current_user)
    bound = bind_scenario(state, form.red_sat.strip(), form.blue_sat.strip(), now)
    if bound.problem is not None:
        return _err(bound.problem)
    hypotheses = _hypotheses(parsed.entries, bound.binding, now, state)
    if hypotheses.problem is not None:
        return _err(hypotheses.problem)
    binding, custody = await _with_custody(state, bound.binding, now)
    # The sweep's picture for this red track, beside the rows: its collect-first rows are listed, never scored (SPC-171).
    scenario = _scenario(form, parsed, hypotheses.carried, binding, now)
    scenario = dataclasses.replace(scenario, threat=held_picture(state, binding, now))
    # Each NOTSO suggestion the operator ticked, applied only while it is the one shown (SPC-130).
    applied = await asyncio.to_thread(
        apply_priors, state, scenario.adversary_actions, form.adv_priors or [],
        None if binding is None else binding.red, (parsed.horizon, now),
    )
    if applied.problem is not None:
        return _err(applied.problem)
    scenario = dataclasses.replace(scenario, adversary_actions=applied.actions)
    # A turn depth whose tree cannot fit is refused here, naming the largest that would, before anything runs (SPC-142).
    too_deep = await asyncio.to_thread(depth_refusal, scenario)
    if too_deep is not None:
        return _err(too_deep)
    return await _answer(request, current_user, scenario, _strategy(form.strategy), custody)


async def _with_custody(
    state: SessionState, binding: ScenarioBinding | None, now: datetime,
) -> tuple[ScenarioBinding | None, CustodyRead | None]:
    """The binding with the red track's custody read now, or, when that would wait on a UDL history fetch, the
    binding as it is and the read for the job to make first, so its progress can say what it waits on (SPC-119)."""
    red = None if binding is None else binding.red
    if binding is None or red is None:
        return binding, None
    fetch = history_fetch(state, red, now)
    if fetch:
        return binding, _custody_reader(state, now, fetch)
    return with_red_custody(binding, await red_custody(state, red, now)), None


def _custody_reader(state: SessionState, now: datetime, fetch: str) -> CustodyRead:
    """The job's first stage: read the bound red track's custody, waiting at most HISTORY_WAIT_S on *fetch*."""
    async def read(scenario: Scenario) -> Scenario:
        binding = cast("ScenarioBinding", scenario.binding)
        status = await red_custody(state, cast("BoundElset", binding.red), now)
        return dataclasses.replace(scenario, binding=with_red_custody(binding, status))
    return CustodyRead(read, HISTORY_WAIT_S, fetch)


def _scenario(
    form: _ScenarioForm, parsed: _Parsed, hypotheses: list[AdversaryHypothesis | None],
    binding: ScenarioBinding | None, now: datetime,
) -> Scenario:
    """The scenario the form describes, at epoch *now*."""
    w_custody_n, w_ca_n, w_dv_n, w_time_n, w_rev_n = _normalised_weights(*parsed.weights)
    return Scenario(
        name=form.scenario_name,
        epoch_utc=now,
        adversary_actions=_adversary_rows(parsed.adversary, hypotheses),
        friendly_responses=_friendly_rows(
            form.fr_ids or [], form.fr_names or [], form.fr_types or [], parsed.friendly, parsed.burns,
        ),
        horizon_hours=parsed.horizon,
        w_custody=w_custody_n,
        w_closest_approach=w_ca_n,
        w_dv_cost=w_dv_n,
        w_time_to_exec=w_time_n,
        w_reversibility=w_rev_n,
        binding=binding,
        turns=parsed.turns,
        observed=parsed.observed,
    )


async def _answer(
    request: Request, user: User, scenario: Scenario, strat: SelectorStrategy, custody: CustodyRead | None = None,
) -> HTMLResponse:
    """The results at once for a scenario that samples nothing; otherwise a job, and the partial that polls it.

    Lookups and rows refused before running evaluate in milliseconds. A scenario that samples can take up to the
    budget, so it runs as this sign-in's job (SPC-113), replacing any other. So does one whose custody must first
    wait on a UDL history fetch, *custody*, whatever it samples (SPC-119).
    """
    state = get_session_state(user)
    key = cast("SessionKey", user.session_key)   # require_login admits only a sign-in
    if custody is None and not await asyncio.to_thread(needs_a_run, scenario):
        state.decision_job = None   # an answer here replaces any job, whose poll would overwrite it
        return await _evaluate_inline(request, state, scenario, strat)
    job = new_job(scenario, strat, custody=custody)
    start_job(state, key, job)
    return render(request, "partials/decision_job.html", job_view(state, job.job_id))


async def _evaluate_inline(
    request: Request, state: SessionState, scenario: Scenario, strat: SelectorStrategy,
) -> HTMLResponse:
    """Evaluate on a worker thread, so no other session waits on it, and render the results."""
    try:
        result = await asyncio.to_thread(evaluate_tree, scenario, strat)
        state.append_log(evaluated_line(scenario, result))
    # The traceback goes to the log; the page says only that it failed.
    except Exception:
        logger.exception("Decision evaluation failed")
        return _err("Evaluation error: the scenario could not be evaluated; the server log has the detail.")
    return render(request, "partials/decision_results.html", _results_context(result))


def _results_context(result: ScenarioResult) -> dict[str, Any]:
    """The results partial's context: the result, each cell's Show trajectory values, and the tree's view (SPC-142)."""
    return {"result": result, "links": trajectory_links(result), "tree": tree_view(result)}


@router.get("/job", response_class=HTMLResponse)
async def decision_job_status(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    job_id: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """The job's progress, which polls again; or its results once done, which do not, so polling ends."""
    return _job_page(request, job_view(get_session_state(current_user), job_id))


def _job_page(request: Request, view: dict[str, Any]) -> HTMLResponse:
    """The results of a finished job, else the job partial for *view*."""
    job = view["job"]
    if job is not None and job.state is JobState.DONE and job.result is not None:
        return render(request, "partials/decision_results.html", _results_context(job.result))
    return render(request, "partials/decision_job.html", view)


class _CancelForm(BaseModel):
    """The job the cancel button names."""

    job_id: str = ""


@router.post("/job/cancel", response_class=HTMLResponse)
async def decision_job_cancel(
    request: Request,
    form: Annotated[_CancelForm, Form()],
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Stop this sign-in's job; its worker thread stops at its next sample, and nothing is scored.

    A job that finished before the Cancel arrived is left alone, and its results are shown.
    """
    state = get_session_state(current_user)
    cancel_job(state, form.job_id)
    return _job_page(request, job_view(state, form.job_id))
