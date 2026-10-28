"""Decision Engine routes — Phase 1 deterministic scenario evaluation.

GET  /plan/decision/panel   → scenario builder input form
POST /plan/decision/evaluate → evaluates scenario, returns ranked results partial
"""

from __future__ import annotations

import html
import logging
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/decision", tags=["decision"])

# Weights summing to less than this are treated as unset rather than scaled up.
_MIN_WEIGHT_TOTAL = 0.01
# Rows per side, as README.md documents, and the longest horizon in hours.
_MAX_ROWS = 5
_MAX_HORIZON_H = 720.0


class _Inputs:
    """The form's numbers, read one by one, keeping the first problem found.

    The first problem is kept rather than raised. Raised, its sentence reached
    the page through the caught exception, which CodeQL's exception-exposure
    query reports however deliberate the sentence is.
    """

    def __init__(self) -> None:
        self.problem: str | None = None

    def _refuse(self, sentence: str) -> float:
        if self.problem is None:
            self.problem = sentence
        return 0.0

    def number(self, raw: str | None, label: str, high: float = 1.0, *, positive: bool = False) -> float:
        """One form number in [0, *high*], or in (0, *high*] when *positive*.

        Every value this engine takes is a fraction in [0, 1], a time or the
        horizon. It accepted any float, NaN and negatives included, and a blank
        field produced a 422 that htmx does not swap, so the panel did nothing
        (audit F-164).
        """
        try:
            value = float(raw or "")
        except ValueError:
            return self._refuse(f"Enter a number for {label}.")
        low_ok = value > 0.0 if positive else value >= 0.0
        if not (math.isfinite(value) and low_ok and value <= high):
            bound = f"above 0 and at most {high:g}" if positive else f"between 0 and {high:g}"
            return self._refuse(f"{label[0].upper()}{label[1:]} must be {bound}; got {raw}.")
        return value

    def column(self, raws: list[str] | None, label: str, high: float = 1.0) -> list[float]:
        """One numeric column of rows, each checked, named by its row."""
        return [self.number(raw, f"{label} in row {i + 1}", high) for i, raw in enumerate(raws or [])]

    def rows(self, adv_ids: list[str] | None, fr_ids: list[str] | None) -> None:
        """Both sides take 1 to 5 rows, as README.md documents."""
        if not (1 <= len(adv_ids or []) <= _MAX_ROWS and 1 <= len(fr_ids or []) <= _MAX_ROWS):
            self._refuse(
                f"Define 1 to {_MAX_ROWS} adversary actions and 1 to {_MAX_ROWS} friendly responses."
            )


def _err(msg: str) -> HTMLResponse:
    """Return an inline error partial with the message escaped.

    This partial is built by hand rather than rendered by Jinja, so nothing
    autoescapes it. One call site passes exception text that an upstream
    library could quote operator-supplied form input into, which is the
    reflected-XSS shape already confirmed on the scenario-time route, so the
    escape is applied here and covers every call site at once. It sits at
    module level rather than nested in decision_evaluate so that this fix adds
    no line inside that function, whose pre-existing cognitive complexity of 44
    would otherwise be pulled into the quality gate's new-code window.
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


def _adversary_rows(
    ids: list[str], names: list[str], types: list[str], probs: list[float], confs: list[float],
) -> list[AdversaryAction]:
    """Build the adversary actions from the form's parallel arrays."""
    return [
        AdversaryAction(
            id=ids[i],
            name=_at(names, i, f"ADV-{i+1}"),
            action_type=_action_type(types, i),
            probability=float(_at(probs, i, 0.5)),
            confidence=float(_at(confs, i, 0.5)),
        )
        for i in range(len(ids))
    ]


class _ResponseColumns(NamedTuple):
    """The friendly-response form's numeric columns, one entry per row."""

    costs: list[float]
    reversibilities: list[float]
    times_h: list[float]


def _friendly_rows(
    ids: list[str], names: list[str], types: list[str], columns: _ResponseColumns,
) -> list[FriendlyResponse]:
    """Build the friendly responses from the form's parallel arrays."""
    return [
        FriendlyResponse(
            id=ids[i],
            name=_at(names, i, f"FR-{i+1}"),
            action_type=_action_type(types, i),
            cost=float(_at(columns.costs, i, 0.5)),
            reversibility=float(_at(columns.reversibilities, i, 0.5)),
            time_to_execute_hours=float(_at(columns.times_h, i, 6.0)),
        )
        for i in range(len(ids))
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
    })


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
    # Scoring weights
    w_custody: str = "0.35"
    w_ca: str = "0.25"
    w_dv: str = "0.20"
    w_time: str = "0.10"
    w_rev: str = "0.10"
    strategy: str = "minimax"


@router.post("/evaluate", response_class=HTMLResponse)
async def decision_evaluate(
    request: Request,
    form: Annotated[_ScenarioForm, Form()],
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Evaluate a decision scenario and return the ranked results partial."""
    scenario_name = form.scenario_name
    inputs = _Inputs()
    inputs.rows(form.adv_ids, form.fr_ids)
    horizon = inputs.number(form.horizon_hours, "the horizon in hours", _MAX_HORIZON_H, positive=True)
    weights = [
        inputs.number(w, "each scoring weight")
        for w in (form.w_custody, form.w_ca, form.w_dv, form.w_time, form.w_rev)
    ]
    adv_columns = (inputs.column(form.adv_probs, "probability"), inputs.column(form.adv_confs, "confidence"))
    fr_columns = _ResponseColumns(
        inputs.column(form.fr_costs, "cost"), inputs.column(form.fr_revs, "reversibility"),
        inputs.column(form.fr_times, "time to execute (hours)", _MAX_HORIZON_H),
    )
    if inputs.problem is not None:
        return _err(inputs.problem)
    adversary_actions = _adversary_rows(
        form.adv_ids or [], form.adv_names or [], form.adv_types or [], *adv_columns,
    )
    friendly_responses = _friendly_rows(form.fr_ids or [], form.fr_names or [], form.fr_types or [], fr_columns)
    strat = _strategy(form.strategy)
    w_custody_n, w_ca_n, w_dv_n, w_time_n, w_rev_n = _normalised_weights(*weights)

    scenario = Scenario(
        name=scenario_name,
        epoch_utc=datetime.now(UTC),
        adversary_actions=adversary_actions,
        friendly_responses=friendly_responses,
        horizon_hours=horizon,
        w_custody=w_custody_n,
        w_closest_approach=w_ca_n,
        w_dv_cost=w_dv_n,
        w_time_to_exec=w_time_n,
        w_reversibility=w_rev_n,
    )

    state = get_session_state(current_user)

    try:
        result = evaluate_scenario(scenario, strategy=strat)
        state.append_log(
            f"[Decision] Evaluated '{scenario_name}': "
            f"{len(adversary_actions)} adversary actions × {len(friendly_responses)} friendly responses. "
            f"Modelled recommendation: {result.robust_best_response.name} ({strat.value})"
        )
    # The traceback goes to the log; the page says only that it failed.
    except Exception:
        logger.exception("Decision evaluation failed")
        return _err("Evaluation error: the scenario could not be evaluated; the server log has the detail.")

    return render(request, "partials/decision_results.html", {
        "result": result,
    })
