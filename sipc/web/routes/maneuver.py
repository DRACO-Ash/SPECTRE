"""Maneuver planning routes — intercept option generation.

Provides endpoints for intercept calculations and orbital event detection.
All computations use the pure-Python ``sipc.astro`` package (Lambert, Hohmann,
bi-elliptic).  Orbital event detection uses SGP4 via ``sipc.astro.events``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta as _timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from sipc.astro.events import EventType, find_orbital_events
from sipc.astro.maneuvers import (
    InterceptSolution,
    lambert_intercept,
    hohmann_intercept,
    bielliptic_intercept,
)
from sipc.domain.models import (
    BurnLocation,
    BurnResult,
    InterceptMethod,
    InterceptResult,
    OrbitalEvent,
)
from sipc.web.auth import require_login
from sipc.web.deps import get_templates
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/maneuver")

_INTERCEPT_METHOD_MAP: dict[str, InterceptMethod] = {m.value: m for m in InterceptMethod}


@router.get("/orbital-events", response_model=None)
async def orbital_events(
    request: Request,
    red_sat: Annotated[str, Query()] = "",
    blue_sat: Annotated[str, Query()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Compute upcoming orbital events for both red and blue satellites.

    Uses sgp4 to propagate the satellite TLEs and detect apogee, perigee,
    ascending node, and descending node crossings.
    """
    logger.info(
        "orbital_events called: red_sat=%r blue_sat=%r by %s",
        red_sat, blue_sat, current_user.username,
    )
    tmpl = get_templates()
    state = get_session_state(current_user.username)

    if not red_sat.strip() and not blue_sat.strip():
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/orbital_events.html",
            {"request": request, "red_events": [], "blue_events": [],
             "red_name": "", "blue_name": "", "error": "Select satellites first."},
        )

    # Use scenario time if available, otherwise default to now + 24h.
    sc_start = state.scenario_start or datetime.now(tz=UTC)
    sc_stop = state.scenario_stop or (sc_start + _timedelta(hours=24))

    red_events: list = []
    blue_events: list = []

    if red_sat.strip():
        tle = _find_tle(state, red_sat.strip())
        if tle:
            raw = find_orbital_events(tle, sc_start, sc_stop)
            red_events = [_astro_event_to_domain(e) for e in raw]
        else:
            logger.warning("orbital_events: no TLE found for red %s", red_sat)

    if blue_sat.strip():
        tle = _find_tle(state, blue_sat.strip())
        if tle:
            raw = find_orbital_events(tle, sc_start, sc_stop)
            blue_events = [_astro_event_to_domain(e) for e in raw]
        else:
            logger.warning("orbital_events: no TLE found for blue %s", blue_sat)

    error = None
    if not red_events and not blue_events:
        error = "No orbital events found — check that satellites have valid TLEs."

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/orbital_events.html",
        {
            "request": request,
            "red_events": red_events,
            "blue_events": blue_events,
            "red_name": red_sat.strip(),
            "blue_name": blue_sat.strip(),
            "error": error,
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
    """Calculate an intercept trajectory using sipc.astro solvers.

    Runs Lambert, Hohmann, or bi-elliptic transfer calculations using
    the pure-Python astro package.

    Returns the intercept result partial with per-burn breakdown.
    """
    tmpl = get_templates()
    state = get_session_state(current_user.username)

    if method not in _INTERCEPT_METHOD_MAP:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/intercept_result.html",
            {"request": request, "result": None, "error": f"Unknown intercept method: {method!r}"},
        )

    # Parse manoeuvre start time.
    manoeuvre_start_dt = datetime.now(tz=UTC)
    if manoeuvre_start.strip():
        try:
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass

    # Look up TLEs.
    red_tle = _find_tle(state, red_sat.strip())
    blue_tle = _find_tle(state, blue_sat.strip())

    if not red_tle or not blue_tle:
        missing = []
        if not red_tle:
            missing.append(f"red ({red_sat})")
        if not blue_tle:
            missing.append(f"blue ({blue_sat})")
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/intercept_result.html",
            {"request": request, "result": None,
             "error": f"No TLE found for: {', '.join(missing)}"},
        )

    intercept_method = _INTERCEPT_METHOD_MAP[method]
    coast_s = coast_hours * 3600.0
    tof_s = intercept_hours * 3600.0
    target_km = target_distance_m / 1000.0

    loop = asyncio.get_running_loop()
    try:
        sol = await loop.run_in_executor(
            None,
            lambda: _run_intercept(
                intercept_method, red_tle, blue_tle,
                manoeuvre_start_dt, coast_s, tof_s, target_km,
            ),
        )
    except Exception as exc:
        logger.error(
            "apply_intercept failed for operator %s: %s", current_user.username, exc
        )
        state.append_log(f"[INTERCEPT] {method} failed: {exc}")
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/intercept_result.html",
            {"request": request, "result": None, "error": f"Intercept calculation failed: {exc}"},
        )

    # Map astro InterceptSolution → domain InterceptResult for the template.
    result = _solution_to_result(sol, red_sat.strip(), blue_sat.strip(), intercept_method)

    state.last_intercept_result = result
    burn_summary = ", ".join(
        f"burn{b.burn_number} ΔV={b.delta_v_km_s:.3f}" for b in result.burns
    )
    state.append_log(
        f"[INTERCEPT] {method} applied: "
        f"total ΔV={result.total_delta_v_km_s:.3f} km/s, "
        f"{len(result.burns)} burn(s) [{burn_summary}], "
        f"arrival={result.arrival_epoch.strftime('%Y-%m-%d %H:%M UTC')}, "
        f"miss={result.intercept_range_km:.1f} km"
    )
    logger.info(
        "apply_intercept: %s for operator %s (%s → %s total_dv=%.3f km/s, burns=%d)",
        method, current_user.username,
        red_sat, blue_sat, result.total_delta_v_km_s, len(result.burns),
    )

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/intercept_result.html",
        {"request": request, "result": result, "error": None},
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_tle(state: object, sat_name: str) -> str | None:
    """Look up a satellite TLE from session state by stk_name."""
    for a in state.blue_assets:  # type: ignore[attr-defined]
        if a.stk_name == sat_name:
            return a.tle
    for t in state.red_tracks:  # type: ignore[attr-defined]
        if t.stk_name == sat_name:
            return t.tle
    return None


def _run_intercept(
    method: InterceptMethod,
    red_tle: str,
    blue_tle: str,
    start: datetime,
    coast_s: float,
    tof_s: float,
    target_km: float,
) -> InterceptSolution:
    """Dispatch to the appropriate sipc.astro solver."""
    if method in (InterceptMethod.LAMBERT, InterceptMethod.PROXIMITY):
        return lambert_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, tof_s=tof_s, coast_s=coast_s,
            target_distance_km=target_km,
        )
    elif method in (InterceptMethod.HOHMANN, InterceptMethod.RENDEZVOUS):
        return hohmann_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.OPTIMAL:
        # Optimal not yet implemented — fall back to Lambert.
        return lambert_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, tof_s=tof_s, coast_s=coast_s,
            target_distance_km=target_km,
        )
    else:
        raise ValueError(f"Unsupported intercept method: {method}")


def _solution_to_result(
    sol: InterceptSolution,
    red_name: str,
    blue_name: str,
    method: InterceptMethod,
) -> InterceptResult:
    """Convert an astro InterceptSolution to a domain InterceptResult."""
    burns = [
        BurnResult(
            burn_number=b.burn_number,
            segment_name=f"Burn {b.burn_number}",
            burn_epoch=b.epoch,
            delta_v_km_s=b.delta_v_mag,
            dv_prograde=b.dv_prograde,
            dv_normal=b.dv_normal,
            dv_radial=b.dv_radial,
        )
        for b in sol.burns
    ]
    return InterceptResult(
        red_name=red_name,
        blue_name=blue_name,
        method=method,
        burns=burns,
        total_delta_v_km_s=sol.total_delta_v,
        arrival_epoch=sol.arrival_epoch,
        intercept_range_km=sol.miss_distance_km,
        notes=f"Computed via sipc.astro {sol.method} solver",
    )


# Map astro EventType → domain BurnLocation for template compatibility.
_EVENT_TYPE_TO_BURN_LOCATION = {
    EventType.APOGEE: BurnLocation.APOGEE,
    EventType.PERIGEE: BurnLocation.PERIGEE,
    EventType.ASCENDING_NODE: BurnLocation.ASCENDING_NODE,
    EventType.DESCENDING_NODE: BurnLocation.DESCENDING_NODE,
}


def _astro_event_to_domain(ev: object) -> OrbitalEvent:
    """Convert an astro OrbitalEvent to a domain OrbitalEvent."""
    return OrbitalEvent(
        event_type=_EVENT_TYPE_TO_BURN_LOCATION[ev.event_type],  # type: ignore[attr-defined]
        epoch=ev.epoch,  # type: ignore[attr-defined]
        label=ev.label,  # type: ignore[attr-defined]
    )
