"""Decision Engine routes: scenario evaluation, from lookups, a sampled or computed closest approach and custody.

GET  /plan/decision/panel      → scenario builder input form, with a manoeuvre hypothesis per adversary row (SPC-114)
GET  /plan/decision/bind       → the bind fields, rebuilt from the held objects (SPC-100)
POST /plan/decision/evaluate   → the ranked results partial for a scenario that samples nothing; for one that
                                 samples, a job the page polls (SPC-113)
GET  /plan/decision/job        → the job's progress, or its results once done
POST /plan/decision/job/cancel → stop the job; nothing is scored
"""

from __future__ import annotations

import asyncio
import html
import logging
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NamedTuple, cast

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from spectre.astro.monte_carlo import MANOEUVRE_ARCHETYPES
from spectre.astro.response_burn import BurnAxis
from spectre.domain.decision import (
    BINDING_NOTE,
    MAX_SAMPLE_HOURS,
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    SelectorStrategy,
    evaluate_scenario,
    longest_horizon_h,
    needs_a_run,
    pre_manoeuvre_state,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.manoeuvre_calibration import from_km_s, to_km_s
from spectre.web.auth import require_login
from spectre.web.decision_binding import bind_scenario
from spectre.web.decision_custody import red_custody, with_red_custody
from spectre.web.decision_job import JobState, cancel_job, evaluated_line, job_view, new_job, start_job
from spectre.web.decision_trajectory import trajectory_links
from spectre.web.deps import render
from spectre.web.models import SessionKey, User
from spectre.web.planning_state import SessionState, get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/decision", tags=["decision"])

# Weights summing to less than this are treated as unset rather than scaled up.
_MIN_WEIGHT_TOTAL = 0.01
# Rows per side, as README.md documents, and the longest horizon in hours.
_MAX_ROWS = 5
_MAX_HORIZON_H = 720.0
# The hypothesis fields' ranges (SPC-114). A burn more than 72 h before the scenario epoch is older than the
# longest staleness limit, so the orbit it starts from would be refused as out of date anyway.
_MAX_DV_M_S = 1000.0
_MAX_SIGMA_M_S = 100.0
_MIN_SAMPLES, _MAX_SAMPLES, _DEFAULT_SAMPLES = 100, 2000, 500
_EARLIEST_BURN_H = -72.0
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
# Our burn per friendly row (SPC-121): a target separation up to this, km, and a budget up to this, m/s.
_MAX_TARGET_KM = 100_000.0
_MAX_BUDGET_M_S = 1000.0
_DEFAULT_BUDGET_M_S = 50.0
_RESPONSE_RELOAD = "The response fields do not match the friendly rows; reload the panel."
_AXIS_UNKNOWN = "Choose a listed axis for row {row}."
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
    """The adversary form's columns, one entry per row."""

    ids:   list[str]
    names: list[str]
    types: list[str]
    probs: list[float]
    confs: list[float]


def _adversary_rows(
    columns: _AdversaryColumns, hypotheses: Sequence[AdversaryHypothesis | None],
) -> list[AdversaryAction]:
    """Build the adversary actions from the form's parallel arrays, each with its hypothesis or None."""
    return [
        AdversaryAction(
            id=columns.ids[i],
            name=_at(columns.names, i, f"ADV-{i+1}"),
            action_type=_action_type(columns.types, i),
            probability=float(_at(columns.probs, i, 0.5)),
            confidence=float(_at(columns.confs, i, 0.5)),
            hypothesis=_at(hypotheses, i, None),
        )
        for i in range(len(columns.ids))
    ]


class _HypothesisColumns(NamedTuple):
    """The hypothesis section's eight columns as posted, one raw entry per adversary row (SPC-114)."""

    archetypes: list[str]
    dvs:        list[str]
    dir_r:      list[str]
    dir_i:      list[str]
    dir_c:      list[str]
    sigmas:     list[str]
    samples:    list[str]
    burns_h:    list[str]


class _HypothesisEntry(NamedTuple):
    """One row's checked hypothesis fields; None for a field left blank, which takes the archetype's."""

    archetype: str
    dv_m_s:    float | None
    direction: tuple[float, float, float] | None
    sigma_m_s: float | None
    samples:   int
    burn_h:    float


def _hypothesis_columns(form: _ScenarioForm, rows: int, inputs: _Inputs) -> _HypothesisColumns | None:
    """The eight columns, or None when the form posts none; columns of another length than the rows are refused.

    Every row posts all eight, blanks included, so the columns stay aligned with the adversary rows.
    """
    raw = (
        form.hyp_archetypes, form.hyp_dvs, form.hyp_dir_r, form.hyp_dir_i, form.hyp_dir_c, form.hyp_sigmas,
        form.hyp_samples, form.hyp_burns_h,
    )
    if all(column is None for column in raw):
        return None
    if any(len(column or []) != rows for column in raw):
        inputs.refuse(_HYPOTHESIS_RELOAD)
        return None
    return _HypothesisColumns(*(list(column or []) for column in raw))


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


def _entry(inputs: _Inputs, columns: _HypothesisColumns, index: int, horizon: float) -> _HypothesisEntry | None:
    """Row *index*'s checked fields, or None when its archetype is None, so the row stays a lookup."""
    archetype = columns.archetypes[index].strip()
    if not archetype:
        return None
    row = index + 1
    if archetype not in MANOEUVRE_ARCHETYPES:
        inputs.refuse(_HYPOTHESIS_UNKNOWN.format(row=row))
    return _HypothesisEntry(
        archetype=archetype,
        dv_m_s=inputs.optional(columns.dvs[index], f"delta-V (m/s) in row {row}", 0.0, _MAX_DV_M_S),
        direction=_direction(inputs, (columns.dir_r[index], columns.dir_i[index], columns.dir_c[index]), row),
        sigma_m_s=inputs.optional(
            columns.sigmas[index], f"delta-V spread, 1 sigma (m/s) in row {row}", 0.0, _MAX_SIGMA_M_S,
        ),
        samples=inputs.whole(columns.samples[index], f"samples in row {row}", _MIN_SAMPLES, _MAX_SAMPLES),
        burn_h=inputs.number(
            columns.burns_h[index], f"burn time (hours from the scenario epoch) in row {row}", horizon,
            low=_EARLIEST_BURN_H,
        ),
    )


def _entries(
    inputs: _Inputs, form: _ScenarioForm, rows: int, horizon: float,
) -> list[_HypothesisEntry | None]:
    """Each adversary row's hypothesis fields, checked; empty when the form posts no hypothesis section."""
    columns = _hypothesis_columns(form, rows, inputs)
    if columns is None:
        return []
    return [_entry(inputs, columns, i, horizon) for i in range(rows)]


def _hypothesis(entry: _HypothesisEntry, red_tle: str, now: datetime) -> AdversaryHypothesis | None:
    """The row's hypothesis from the red track's state at the burn time; None when it cannot be propagated there."""
    at = pre_manoeuvre_state(red_tle, now + timedelta(hours=entry.burn_h))
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
    return built if entry.sigma_m_s is None else built.with_spread(entry.sigma_m_s)


class _Hypotheses(NamedTuple):
    """Each row's hypothesis or None, or the sentence that refuses them."""

    carried: list[AdversaryHypothesis | None]
    problem: str | None


def _hypotheses(
    entries: Sequence[_HypothesisEntry | None], binding: ScenarioBinding | None, now: datetime,
) -> _Hypotheses:
    """Build each row's hypothesis from the bound red track at its burn time (SPC-114)."""
    red = None if binding is None else binding.red
    carried: list[AdversaryHypothesis | None] = []
    for row, entry in enumerate(entries, start=1):
        if entry is None:
            carried.append(None)
            continue
        if red is None:
            return _Hypotheses([], _HYPOTHESIS_NO_RED.format(row=row))
        built = _hypothesis(entry, red.tle, now)
        if built is None:
            return _Hypotheses([], _HYPOTHESIS_NO_STATE.format(row=row))
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


@router.get("/panel", response_class=HTMLResponse)
async def decision_panel(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Return the decision engine scenario builder panel."""
    state = get_session_state(current_user)
    pol   = getattr(state, "last_pol_analysis", None)
    return render(request, "partials/decision_panel.html", {
        "pol": pol,
        **_bind_context(state),
        **_hypothesis_context(),
    })


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


class _Parsed(NamedTuple):
    """The form's checked numbers: horizon, weights, both sides' columns and each row's hypothesis fields."""

    horizon:   float
    weights:   list[float]
    adversary: _AdversaryColumns
    friendly:  _ResponseColumns
    entries:   list[_HypothesisEntry | None]
    burns:     list[ResponseBurnSpec | None]


def _parse(inputs: _Inputs, form: _ScenarioForm) -> _Parsed:
    """Every number on the form, checked; the first problem is kept on *inputs*."""
    inputs.rows(form.adv_ids, form.fr_ids)
    horizon = inputs.number(form.horizon_hours, "the horizon in hours", _MAX_HORIZON_H, positive=True)
    weights = [
        inputs.number(w, "each scoring weight")
        for w in (form.w_custody, form.w_ca, form.w_dv, form.w_time, form.w_rev)
    ]
    adversary = _AdversaryColumns(
        form.adv_ids or [], form.adv_names or [], form.adv_types or [],
        inputs.column(form.adv_probs, "probability"), inputs.column(form.adv_confs, "confidence"),
    )
    friendly = _ResponseColumns(
        inputs.column(form.fr_costs, "cost"), inputs.column(form.fr_revs, "reversibility"),
        inputs.column(form.fr_times, "time to execute (hours)", _MAX_HORIZON_H),
    )
    entries = _entries(inputs, form, len(adversary.ids), horizon)
    return _Parsed(horizon, weights, adversary, friendly, entries, _burns(inputs, form))


@router.post("/evaluate", response_class=HTMLResponse)
async def decision_evaluate(
    request: Request,
    form: Annotated[_ScenarioForm, Form()],
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Evaluate a decision scenario and return the ranked results partial, or the job that will.

    The scenario epoch is now, the moment Evaluate is pressed; a hypothesis's burn time counts from it (SPC-114).
    A bound red track's custody is read here, as the sweep reads it (SPC-123), so the evaluation does no I/O.
    """
    inputs = _Inputs()
    parsed = _parse(inputs, form)
    if inputs.problem is not None:
        return _err(inputs.problem)
    now = datetime.now(UTC)
    state = get_session_state(current_user)
    bound = bind_scenario(state, form.red_sat.strip(), form.blue_sat.strip(), now)
    if bound.problem is not None:
        return _err(bound.problem)
    hypotheses = _hypotheses(parsed.entries, bound.binding, now)
    if hypotheses.problem is not None:
        return _err(hypotheses.problem)
    binding = bound.binding
    if binding is not None and binding.red is not None:
        binding = with_red_custody(binding, await red_custody(state, binding.red, now))
    scenario = _scenario(form, parsed, hypotheses.carried, binding, now)
    return await _answer(request, current_user, scenario, _strategy(form.strategy))


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
    )


async def _answer(request: Request, user: User, scenario: Scenario, strat: SelectorStrategy) -> HTMLResponse:
    """The results at once for a scenario that samples nothing; otherwise a job, and the partial that polls it.

    Lookups and rows refused before running evaluate in milliseconds. A scenario that samples can take up to the
    budget, so it runs as this sign-in's job (SPC-113), replacing any other.
    """
    state = get_session_state(user)
    key = cast("SessionKey", user.session_key)   # require_login admits only a sign-in
    if not await asyncio.to_thread(needs_a_run, scenario):
        state.decision_job = None   # an answer here replaces any job, whose poll would overwrite it
        return await _evaluate_inline(request, state, scenario, strat)
    job = new_job(scenario, strat)
    start_job(state, key, job)
    return render(request, "partials/decision_job.html", job_view(state, job.job_id))


async def _evaluate_inline(
    request: Request, state: SessionState, scenario: Scenario, strat: SelectorStrategy,
) -> HTMLResponse:
    """Evaluate on a worker thread, so no other session waits on it, and render the results."""
    try:
        result = await asyncio.to_thread(evaluate_scenario, scenario, strategy=strat)
        state.append_log(evaluated_line(scenario, result))
    # The traceback goes to the log; the page says only that it failed.
    except Exception:
        logger.exception("Decision evaluation failed")
        return _err("Evaluation error: the scenario could not be evaluated; the server log has the detail.")
    return render(request, "partials/decision_results.html", {"result": result, "links": trajectory_links(result)})


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
        return render(
            request, "partials/decision_results.html", {"result": job.result, "links": trajectory_links(job.result)},
        )
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
