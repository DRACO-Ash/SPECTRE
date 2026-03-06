"""Maneuver planning routes — Astrogator intercept option generation.

Provides endpoints for searching, refreshing, and selecting intercept
maneuver options for a Red satellite against a Blue target.  All heavy
computation is delegated to :class:`~sipc.domain.maneuver_planner.ManeuverPlanner`
which calls the STK Astrogator adapter in a thread-pool executor.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from sipc.domain.models import BurnLocation, BurnType, ManeuverSearchConfig
from sipc.domain.maneuver_planner import ManeuverPlanner, ManeuverPlannerError
from sipc.web.auth import require_login
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/maneuver")

_BURN_TYPE_MAP: dict[str, BurnType] = {bt.value: bt for bt in BurnType}
_BURN_LOCATION_MAP: dict[str, BurnLocation] = {bl.value: bl for bl in BurnLocation}


def _templates() -> object:
    from sipc.web.app import templates  # noqa: PLC0415
    return templates


def _parse_burn_types(raw: list[str]) -> list[BurnType]:
    return [_BURN_TYPE_MAP[v] for v in raw if v in _BURN_TYPE_MAP]


def _parse_burn_locations(raw: list[str]) -> list[BurnLocation]:
    return [_BURN_LOCATION_MAP[v] for v in raw if v in _BURN_LOCATION_MAP]


async def _run_search(
    request: Request,
    current_user: User,
    config: ManeuverSearchConfig,
) -> HTMLResponse:
    """Common search execution shared by /search and /refresh."""
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if not state.stk_session:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": "Not connected to STK — connect via the STK panel first.",
                "selected_id": None,
            },
        )

    planner = ManeuverPlanner(state.stk_session)
    loop = asyncio.get_event_loop()
    try:
        options = await loop.run_in_executor(None, planner.compute_options, config)
    except ManeuverPlannerError as exc:
        logger.warning("Maneuver search validation error for %s: %s", current_user.username, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": str(exc),
                "selected_id": None,
            },
        )
    except Exception as exc:
        logger.error(
            "Maneuver search failed for operator %s: %s", current_user.username, exc
        )
        state.append_log(f"[MANEUVER] Search failed: {exc}")
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": f"Search failed: {exc}",
                "selected_id": None,
            },
        )

    state.maneuver_options = options
    state.selected_maneuver = None
    state.append_log(
        f"[MANEUVER] Search complete: {len(options)} option(s) for "
        f"{config.red_sat} vs {config.blue_sat}"
    )
    logger.info(
        "Maneuver search: %d options for operator %s (%s vs %s)",
        len(options), current_user.username, config.red_sat, config.blue_sat,
    )

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/maneuver_options_table.html",
        {
            "request": request,
            "options": options,
            "error": None,
            "selected_id": None,
        },
    )


@router.post("/search", response_model=None)
async def maneuver_search(
    request: Request,
    red_sat: Annotated[str, Form()],
    blue_sat: Annotated[str, Form()],
    window_start: Annotated[str, Form()],
    window_stop: Annotated[str, Form()],
    max_dv: Annotated[float, Form()] = 3.0,
    burn_types: Annotated[list[str], Form()] = [],  # noqa: B006
    burn_locations: Annotated[list[str], Form()] = [],  # noqa: B006
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Trigger a new Astrogator maneuver option search.

    Accepts the operator's search configuration from the Intel/Mission panel
    form, runs the Astrogator MCS search in a thread-pool executor, and
    returns the maneuver options table partial.
    """
    try:
        start_dt = datetime.fromisoformat(window_start).replace(tzinfo=UTC)
        stop_dt = datetime.fromisoformat(window_stop).replace(tzinfo=UTC)
    except ValueError as exc:
        tmpl = _templates()
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": f"Invalid date format: {exc}",
                "selected_id": None,
            },
        )

    config = ManeuverSearchConfig(
        red_sat=red_sat.strip(),
        blue_sat=blue_sat.strip(),
        search_window_start=start_dt,
        search_window_stop=stop_dt,
        max_delta_v_km_s=max_dv,
        burn_types=_parse_burn_types(burn_types) or list(BurnType),
        burn_locations=_parse_burn_locations(burn_locations) or list(BurnLocation),
    )

    return await _run_search(request, current_user, config)


@router.post("/refresh", response_model=None)
async def maneuver_refresh(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Re-run the maneuver search using the last stored configuration.

    Useful when the red satellite's orbit has been updated in STK (e.g. the
    operator already has a satellite in the scenario and wants fresh options
    based on its current propagated state).
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if not state.maneuver_options and state.selected_maneuver is None:
        # No previous search to refresh from
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": "No previous search to refresh — run a search first.",
                "selected_id": None,
            },
        )

    # Reconstruct config from the stored options (use first option's sat names)
    existing = state.maneuver_options
    if not existing:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": "No previous options stored — run a fresh search.",
                "selected_id": None,
            },
        )

    first = existing[0]
    config = ManeuverSearchConfig(
        red_sat=first.red_name,
        blue_sat=first.blue_name,
        search_window_start=state.scenario_start or datetime.now(tz=UTC),
        search_window_stop=state.scenario_stop or datetime.now(tz=UTC),
        max_delta_v_km_s=3.0,
        burn_types=list(BurnType),
        burn_locations=list(BurnLocation),
    )

    return await _run_search(request, current_user, config)


@router.post("/select", response_model=None)
async def maneuver_select(
    request: Request,
    option_id: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Store the operator-selected maneuver option in session state.

    The selected option is held in ``SessionState.selected_maneuver``.
    Returns a status partial confirming the selection.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    option = next(
        (o for o in state.maneuver_options if o.option_id == option_id), None
    )
    if option is None:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_status.html",
            {
                "request": request,
                "selected": None,
                "error": f"Option {option_id!r} not found — run a new search.",
            },
        )

    state.selected_maneuver = option
    state.append_log(
        f"[MANEUVER] Selected option {option.option_id}: "
        f"{option.burn_location.value} {option.burn_type.value} "
        f"ΔV={option.delta_v_km_s:.3f} km/s "
        f"burn@{option.burn_epoch.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    logger.info(
        "Maneuver selected by %s: %s (dv=%.3f km/s)",
        current_user.username, option.option_id, option.delta_v_km_s,
    )

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/maneuver_status.html",
        {
            "request": request,
            "selected": option,
            "error": None,
        },
    )
