"""Decision Engine routes — Phase 1 deterministic scenario evaluation.

GET  /plan/decision/panel   → scenario builder input form
POST /plan/decision/evaluate → evaluates scenario, returns ranked results partial
"""

from __future__ import annotations

import html
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

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


def _pol_blue_tle(state: object) -> str | None:
    """The latest element set from the session's active Pattern of Life, if any."""
    pol = getattr(state, "last_pol_analysis", None)
    if pol and pol.records:
        return pol.records[-1].tle if hasattr(pol.records[-1], "tle") else None
    return None


@router.get("/panel", response_class=HTMLResponse)
async def decision_panel(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the decision engine scenario builder panel."""
    state = get_session_state(current_user.username)
    pol   = getattr(state, "last_pol_analysis", None)
    return render(request, "partials/decision_panel.html", {
        "pol": pol,
    })


@router.post("/evaluate", response_class=HTMLResponse)
async def decision_evaluate(
    request: Request,
    scenario_name: Annotated[str, Form()] = "Unnamed Scenario",
    horizon_hours: Annotated[float, Form()] = 72.0,
    # Adversary actions (up to 4, passed as parallel form arrays)
    adv_ids:    Annotated[list[str] | None, Form(alias="adv_id")] = None,
    adv_names:  Annotated[list[str] | None, Form(alias="adv_name")] = None,
    adv_types:  Annotated[list[str] | None, Form(alias="adv_type")] = None,
    adv_probs:  Annotated[list[float] | None, Form(alias="adv_prob")] = None,
    adv_confs:  Annotated[list[float] | None, Form(alias="adv_conf")] = None,
    # Friendly responses (up to 4)
    fr_ids:    Annotated[list[str] | None, Form(alias="fr_id")] = None,
    fr_names:  Annotated[list[str] | None, Form(alias="fr_name")] = None,
    fr_types:  Annotated[list[str] | None, Form(alias="fr_type")] = None,
    fr_costs:  Annotated[list[float] | None, Form(alias="fr_cost")] = None,
    fr_revs:   Annotated[list[float] | None, Form(alias="fr_rev")] = None,
    fr_times:  Annotated[list[float] | None, Form(alias="fr_time")] = None,
    # Scoring weights
    w_custody:  Annotated[float, Form()] = 0.35,
    w_ca:       Annotated[float, Form()] = 0.25,
    w_dv:       Annotated[float, Form()] = 0.20,
    w_time:     Annotated[float, Form()] = 0.10,
    w_rev:      Annotated[float, Form()] = 0.10,
    strategy:   Annotated[str, Form()] = "minimax",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Evaluate a decision scenario and return the ranked results partial."""
    if not adv_ids or not fr_ids:
        return _err("Define at least one adversary action and one friendly response.")

    adversary_actions = _adversary_rows(adv_ids, adv_names or [], adv_types or [], adv_probs or [], adv_confs or [])
    friendly_responses = _friendly_rows(
        fr_ids, fr_names or [], fr_types or [],
        _ResponseColumns(fr_costs or [], fr_revs or [], fr_times or []),
    )
    strat = _strategy(strategy)
    w_custody, w_ca, w_dv, w_time, w_rev = _normalised_weights(w_custody, w_ca, w_dv, w_time, w_rev)

    scenario = Scenario(
        name=scenario_name,
        epoch_utc=datetime.now(UTC),
        adversary_actions=adversary_actions,
        friendly_responses=friendly_responses,
        horizon_hours=horizon_hours,
        w_custody=w_custody,
        w_closest_approach=w_ca,
        w_dv_cost=w_dv,
        w_time_to_exec=w_time,
        w_reversibility=w_rev,
    )

    state = get_session_state(current_user.username)
    blue_tle = _pol_blue_tle(state)

    try:
        result = evaluate_scenario(scenario, blue_tle=blue_tle, red_tle=None, strategy=strat)
        state.append_log(
            f"[Decision] Evaluated '{scenario_name}': "
            f"{len(adversary_actions)} adversary actions × {len(friendly_responses)} friendly responses. "
            f"Modelled recommendation: {result.robust_best_response.name} ({strat.value})"
        )
    except Exception as exc:
        logger.exception("Decision evaluation failed")
        return _err(f"Evaluation error: {exc}")

    return render(request, "partials/decision_results.html", {
        "result": result,
    })
