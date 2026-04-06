"""Decision Engine routes — Phase 1 deterministic scenario evaluation.

GET  /plan/decision/panel   → scenario builder input form
POST /plan/decision/evaluate → evaluates scenario, returns ranked results partial
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from sipc.web.auth import require_login
from sipc.web.deps import render
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/decision", tags=["decision"])


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
    adv_ids:    Annotated[list[str], Form(alias="adv_id")] = [],
    adv_names:  Annotated[list[str], Form(alias="adv_name")] = [],
    adv_types:  Annotated[list[str], Form(alias="adv_type")] = [],
    adv_probs:  Annotated[list[float], Form(alias="adv_prob")] = [],
    adv_confs:  Annotated[list[float], Form(alias="adv_conf")] = [],
    # Friendly responses (up to 4)
    fr_ids:    Annotated[list[str], Form(alias="fr_id")] = [],
    fr_names:  Annotated[list[str], Form(alias="fr_name")] = [],
    fr_types:  Annotated[list[str], Form(alias="fr_type")] = [],
    fr_costs:  Annotated[list[float], Form(alias="fr_cost")] = [],
    fr_revs:   Annotated[list[float], Form(alias="fr_rev")] = [],
    fr_times:  Annotated[list[float], Form(alias="fr_time")] = [],
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
    from sipc.domain.decision import (
        ActionType,
        AdversaryAction,
        FriendlyResponse,
        Scenario,
        SelectorStrategy,
        evaluate_scenario,
    )

    def _err(msg: str) -> HTMLResponse:
        return HTMLResponse(f'<p class="error-msg">{msg}</p>')

    if not adv_ids or not fr_ids:
        return _err("Define at least one adversary action and one friendly response.")

    # Build adversary action list
    adversary_actions = []
    for i in range(len(adv_ids)):
        try:
            atype = ActionType(adv_types[i]) if i < len(adv_types) else ActionType.MANOEUVRE
        except ValueError:
            atype = ActionType.MANOEUVRE
        adversary_actions.append(AdversaryAction(
            id=adv_ids[i],
            name=adv_names[i] if i < len(adv_names) else f"ADV-{i+1}",
            action_type=atype,
            probability=float(adv_probs[i]) if i < len(adv_probs) else 0.5,
            confidence=float(adv_confs[i]) if i < len(adv_confs) else 0.5,
        ))

    # Build friendly response list
    friendly_responses = []
    for i in range(len(fr_ids)):
        try:
            ftype = ActionType(fr_types[i]) if i < len(fr_types) else ActionType.MANOEUVRE
        except ValueError:
            ftype = ActionType.MANOEUVRE
        friendly_responses.append(FriendlyResponse(
            id=fr_ids[i],
            name=fr_names[i] if i < len(fr_names) else f"FR-{i+1}",
            action_type=ftype,
            cost=float(fr_costs[i]) if i < len(fr_costs) else 0.5,
            reversibility=float(fr_revs[i]) if i < len(fr_revs) else 0.5,
            time_to_execute_hours=float(fr_times[i]) if i < len(fr_times) else 6.0,
        ))

    try:
        strat = SelectorStrategy(strategy)
    except ValueError:
        strat = SelectorStrategy.MINIMAX

    # Normalise weights
    total_w = w_custody + w_ca + w_dv + w_time + w_rev
    if total_w < 0.01:
        total_w = 1.0
    w_custody /= total_w
    w_ca      /= total_w
    w_dv      /= total_w
    w_time    /= total_w
    w_rev     /= total_w

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
    pol   = getattr(state, "last_pol_analysis", None)

    # Optional TLEs from active PoL session
    blue_tle = None
    red_tle  = None
    if pol and pol.records:
        blue_tle = pol.records[-1].tle if hasattr(pol.records[-1], "tle") else None

    try:
        result = evaluate_scenario(scenario, blue_tle=blue_tle, red_tle=red_tle, strategy=strat)
        state.append_log(
            f"[Decision] Evaluated '{scenario_name}': "
            f"{len(adversary_actions)} adversary actions × {len(friendly_responses)} friendly responses. "
            f"Robust recommendation: {result.robust_best_response.name} ({strat.value})"
        )
    except Exception as exc:
        logger.exception("Decision evaluation failed")
        return _err(f"Evaluation error: {exc}")

    return render(request, "partials/decision_results.html", {
        "result": result,
    })
