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

from sipc.domain.models import BurnLocation, BurnType, InterceptConfig, InterceptMethod, ManeuverSearchConfig
from sipc.domain.maneuver_planner import ManeuverPlanner, ManeuverPlannerError
from sipc.web.auth import require_login
from sipc.web.deps import get_templates
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/maneuver")

_BURN_TYPE_MAP: dict[str, BurnType] = {bt.value: bt for bt in BurnType}
_BURN_LOCATION_MAP: dict[str, BurnLocation] = {bl.value: bl for bl in BurnLocation}
_INTERCEPT_METHOD_MAP: dict[str, InterceptMethod] = {m.value: m for m in InterceptMethod}


def _parse_burn_types(raw: list[str]) -> list[BurnType]:
    return [_BURN_TYPE_MAP[v] for v in raw if v in _BURN_TYPE_MAP]


def _parse_burn_locations(raw: list[str]) -> list[BurnLocation]:
    return [_BURN_LOCATION_MAP[v] for v in raw if v in _BURN_LOCATION_MAP]


def _parse_intercept_methods(raw: list[str]) -> list[InterceptMethod]:
    return [_INTERCEPT_METHOD_MAP[v] for v in raw if v in _INTERCEPT_METHOD_MAP]


async def _run_search(
    request: Request,
    current_user: User,
    config: ManeuverSearchConfig,
) -> HTMLResponse:
    """Common search execution shared by /search and /refresh."""
    tmpl = get_templates()
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
    loop = asyncio.get_running_loop()
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
    state.last_maneuver_config = config
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
    # ── Intercept engine fields (optional) ───────────────────────────────────
    intercept_methods: Annotated[list[str], Form()] = [],  # noqa: B006
    manoeuvre_start: Annotated[str, Form()] = "",
    coast_hours: Annotated[float, Form()] = 1.0,
    intercept_hours: Annotated[float, Form()] = 6.0,
    number_of_burns: Annotated[int, Form()] = 1,
    target_distance_m: Annotated[float, Form()] = 0.0,
    minimize_delta_v: Annotated[bool, Form()] = True,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Trigger a new Astrogator maneuver option search.

    Accepts the operator's search configuration from the Intel/Mission panel
    form, runs the Astrogator MCS search in a thread-pool executor, and
    returns the maneuver options table partial.

    The optional intercept engine fields (``intercept_methods``, ``coast_hours``,
    etc.) are forwarded to :class:`~sipc.domain.models.ManeuverSearchConfig`
    and activate the intercept engine algorithms when present.
    """
    try:
        start_dt = datetime.fromisoformat(window_start).replace(tzinfo=UTC)
        stop_dt = datetime.fromisoformat(window_stop).replace(tzinfo=UTC)
    except ValueError as exc:
        tmpl = get_templates()
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": f"Invalid date format: {exc}",
                "selected_id": None,
            },
        )

    # Parse optional manoeuvre start epoch (empty string → None → scenario epoch).
    manoeuvre_start_dt = None
    if manoeuvre_start.strip():
        try:
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass  # Silently ignore bad input; scenario epoch will be used.

    config = ManeuverSearchConfig(
        red_sat=red_sat.strip(),
        blue_sat=blue_sat.strip(),
        search_window_start=start_dt,
        search_window_stop=stop_dt,
        max_delta_v_km_s=max_dv,
        burn_types=_parse_burn_types(burn_types) or list(BurnType),
        burn_locations=_parse_burn_locations(burn_locations) or list(BurnLocation),
        intercept_methods=_parse_intercept_methods(intercept_methods),
        manoeuvre_start=manoeuvre_start_dt,
        coast_hours=coast_hours,
        intercept_hours=intercept_hours,
        number_of_burns=max(1, number_of_burns),
        target_distance_m=max(0.0, target_distance_m),
        minimize_delta_v=minimize_delta_v,
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
    tmpl = get_templates()
    state = get_session_state(current_user.username)

    if state.last_maneuver_config is None:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_options_table.html",
            {
                "request": request,
                "options": [],
                "error": "No previous search to refresh — run a search first.",
                "selected_id": None,
            },
        )

    return await _run_search(request, current_user, state.last_maneuver_config)


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
    tmpl = get_templates()
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


@router.post("/apply-intercept", response_model=None)
async def apply_intercept(
    request: Request,
    red_sat: Annotated[str, Form()],
    blue_sat: Annotated[str, Form()],
    method: Annotated[str, Form()],
    manoeuvre_start: Annotated[str, Form()] = "",
    coast_hours: Annotated[float, Form()] = 1.0,
    intercept_hours: Annotated[float, Form()] = 6.0,
    number_of_burns: Annotated[int, Form()] = 1,
    target_distance_m: Annotated[float, Form()] = 0.0,
    minimize_delta_v: Annotated[bool, Form()] = True,
    max_dv: Annotated[float, Form()] = 3.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Calculate and apply a specific intercept trajectory to the red satellite.

    Builds an Astrogator MCS using the selected intercept engine algorithm,
    runs the differential corrector to solve for the required ΔV, then
    encodes the solved trajectory as a fixed MCS so the satellite moves in STK.

    Returns the maneuver status partial showing what was applied.
    """
    tmpl = get_templates()
    state = get_session_state(current_user.username)

    if not state.stk_session:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_status.html",
            {
                "request": request,
                "selected": None,
                "error": "Not connected to STK — connect via the STK panel first.",
            },
        )

    if method not in _INTERCEPT_METHOD_MAP:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_status.html",
            {
                "request": request,
                "selected": None,
                "error": f"Unknown intercept method: {method!r}",
            },
        )

    manoeuvre_start_dt = None
    if manoeuvre_start.strip():
        try:
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass

    config = InterceptConfig(
        red_sat=red_sat.strip(),
        blue_sat=blue_sat.strip(),
        method=_INTERCEPT_METHOD_MAP[method],
        manoeuvre_start=manoeuvre_start_dt,
        coast_hours=coast_hours,
        intercept_hours=intercept_hours,
        number_of_burns=max(1, number_of_burns),
        target_distance_m=max(0.0, target_distance_m),
        minimize_delta_v=minimize_delta_v,
        max_delta_v_km_s=max_dv,
    )

    loop = asyncio.get_running_loop()
    try:
        option = await loop.run_in_executor(
            None, state.stk_session.apply_intercept_plan, config
        )
    except Exception as exc:
        logger.error(
            "apply_intercept failed for operator %s: %s", current_user.username, exc
        )
        state.append_log(f"[INTERCEPT] {config.method.value} failed: {exc}")
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/maneuver_status.html",
            {
                "request": request,
                "selected": None,
                "error": f"Intercept calculation failed: {exc}",
            },
        )

    # Store the applied option in session state so the operator can see it.
    state.selected_maneuver = option
    state.maneuver_options = [option]
    state.append_log(
        f"[INTERCEPT] {config.method.value} applied: "
        f"ΔV={option.delta_v_km_s:.3f} km/s "
        f"burn@{option.burn_epoch.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    logger.info(
        "apply_intercept: %s for operator %s (%s → %s dv=%.3f km/s)",
        config.method.value, current_user.username,
        config.red_sat, config.blue_sat, option.delta_v_km_s,
    )

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/maneuver_status.html",
        {
            "request": request,
            "selected": option,
            "error": None,
        },
    )
