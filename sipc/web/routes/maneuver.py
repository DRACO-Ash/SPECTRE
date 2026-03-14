"""Maneuver planning routes — Astrogator intercept option generation.

Provides endpoints for searching, refreshing, and selecting intercept
maneuver options for a Red satellite against a Blue target.  All heavy
computation is delegated to :class:`~sipc.domain.maneuver_planner.ManeuverPlanner`
which calls the STK Astrogator adapter in a thread-pool executor.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta as _timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sgp4.api import Satrec, jday

from sipc.domain.models import BurnLocation, BurnType, InterceptConfig, InterceptMethod, ManeuverSearchConfig, OrbitalEvent
from sipc.domain.maneuver_planner import ManeuverPlanner, ManeuverPlannerError
from sipc.web.auth import require_login
from sipc.web.deps import _com_executor, get_templates
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/maneuver")

_BURN_TYPE_MAP: dict[str, BurnType] = {bt.value: bt for bt in BurnType}
_BURN_LOCATION_MAP: dict[str, BurnLocation] = {bl.value: bl for bl in BurnLocation}
_INTERCEPT_METHOD_MAP: dict[str, InterceptMethod] = {m.value: m for m in InterceptMethod}

_MU_EARTH = 398600.4418  # km³/s² — standard gravitational parameter


def _compute_orbital_events(
    tle: str,
    sc_start: datetime,
    sc_stop: datetime,
    count: int = 3,
    step_s: float = 30.0,
) -> list[OrbitalEvent]:
    """Compute apogee, perigee, ascending/descending node times from a TLE.

    Propagates the TLE with sgp4, computes true anomaly and latitude at
    each timestep, and detects zero-crossings.
    """
    lines = [ln.strip() for ln in tle.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return []

    line1, line2 = lines[-2], lines[-1]
    try:
        sat = Satrec.twoline2rv(line1, line2)
    except Exception as exc:
        logger.warning("_compute_orbital_events: bad TLE: %s", exc)
        return []

    events: list[OrbitalEvent] = []
    counts: dict[BurnLocation, int] = {}

    window_s = (sc_stop - sc_start).total_seconds()
    n_steps = max(2, int(window_s / step_s))

    prev_ta: float | None = None
    prev_lat: float | None = None

    for i in range(n_steps + 1):
        t = sc_start + _timedelta(seconds=i * step_s)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)

        e, r, v = sat.sgp4(jd, fr)
        if e != 0:
            continue

        x, y, z = r  # km — TEME frame
        vx, vy, vz = v

        # Compute orbital elements from state vector.
        r_mag = math.sqrt(x**2 + y**2 + z**2)
        v_mag = math.sqrt(vx**2 + vy**2 + vz**2)

        # Specific angular momentum h = r × v
        hx = y * vz - z * vy
        hy = z * vx - x * vz
        hz = x * vy - y * vx
        h_mag = math.sqrt(hx**2 + hy**2 + hz**2)

        # Radial velocity
        v_r = (x * vx + y * vy + z * vz) / r_mag

        # True anomaly via v_r sign and vis-viva
        semi_latus = h_mag**2 / _MU_EARTH
        ecc_vec_factor = v_mag**2 - _MU_EARTH / r_mag
        ex = (ecc_vec_factor * x - r_mag * v_r * vx) / _MU_EARTH
        ey = (ecc_vec_factor * y - r_mag * v_r * vy) / _MU_EARTH
        ez = (ecc_vec_factor * z - r_mag * v_r * vz) / _MU_EARTH
        ecc = math.sqrt(ex**2 + ey**2 + ez**2)

        if ecc > 1e-10:
            cos_ta = (ex * x + ey * y + ez * z) / (ecc * r_mag)
            cos_ta = max(-1.0, min(1.0, cos_ta))
            ta = math.degrees(math.acos(cos_ta))
            if v_r < 0:
                ta = 360.0 - ta
        else:
            ta = 0.0

        # Geocentric latitude (TEME ≈ inertial for node detection)
        lat = math.degrees(math.asin(z / r_mag)) if r_mag > 0 else 0.0

        if prev_ta is not None:
            # Apogee: TA crosses 180° (ascending past apoapsis)
            if prev_ta < 180.0 <= ta:
                loc = BurnLocation.APOGEE
                if counts.get(loc, 0) < count:
                    label = f"Apogee @ {t.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    events.append(OrbitalEvent(event_type=loc, epoch=t, label=label))
                    counts[loc] = counts.get(loc, 0) + 1

            # Perigee: TA wraps from >300 to <60
            if prev_ta > 300.0 and ta < 60.0:
                loc = BurnLocation.PERIGEE
                if counts.get(loc, 0) < count:
                    label = f"Perigee @ {t.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    events.append(OrbitalEvent(event_type=loc, epoch=t, label=label))
                    counts[loc] = counts.get(loc, 0) + 1

        if prev_lat is not None:
            # Ascending node: latitude crosses 0 going positive
            if prev_lat < 0.0 <= lat:
                loc = BurnLocation.ASCENDING_NODE
                if counts.get(loc, 0) < count:
                    label = f"Ascending Node @ {t.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    events.append(OrbitalEvent(event_type=loc, epoch=t, label=label))
                    counts[loc] = counts.get(loc, 0) + 1

            # Descending node: latitude crosses 0 going negative
            if prev_lat >= 0.0 and lat < 0.0:
                loc = BurnLocation.DESCENDING_NODE
                if counts.get(loc, 0) < count:
                    label = f"Descending Node @ {t.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    events.append(OrbitalEvent(event_type=loc, epoch=t, label=label))
                    counts[loc] = counts.get(loc, 0) + 1

        prev_ta = ta
        prev_lat = lat

    events.sort(key=lambda ev: ev.epoch)
    return events


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
        options = await loop.run_in_executor(_com_executor, planner.compute_options, config)
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


@router.get("/orbital-events", response_model=None)
async def orbital_events(
    request: Request,
    red_sat: Annotated[str, Query()] = "",
    blue_sat: Annotated[str, Query()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Compute upcoming orbital events for both red and blue satellites.

    Uses sgp4 to propagate the satellite TLEs and detect apogee, perigee,
    ascending node, and descending node crossings.  No STK dependency.
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

    # Look up TLEs from session state.
    def _find_tle(stk_name: str) -> str | None:
        for a in state.blue_assets:
            if a.stk_name == stk_name:
                return a.tle
        for t in state.red_tracks:
            if t.stk_name == stk_name:
                return t.tle
        return None

    # Use scenario time if available, otherwise default to now + 24h.
    sc_start = state.scenario_start or datetime.now(tz=UTC)
    sc_stop = state.scenario_stop or (sc_start + _timedelta(hours=24))

    red_events: list = []
    blue_events: list = []

    if red_sat.strip():
        tle = _find_tle(red_sat.strip())
        if tle:
            red_events = _compute_orbital_events(tle, sc_start, sc_stop)
        else:
            logger.warning("orbital_events: no TLE found for red %s", red_sat)

    if blue_sat.strip():
        tle = _find_tle(blue_sat.strip())
        if tle:
            blue_events = _compute_orbital_events(tle, sc_start, sc_stop)
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
            "partials/intercept_result.html",
            {"request": request, "result": None, "error": "Not connected to STK — connect via the STK panel first."},
        )

    if method not in _INTERCEPT_METHOD_MAP:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/intercept_result.html",
            {"request": request, "result": None, "error": f"Unknown intercept method: {method!r}"},
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
        result = await loop.run_in_executor(
            _com_executor, state.stk_session.apply_intercept_plan, config
        )
    except Exception as exc:
        logger.error(
            "apply_intercept failed for operator %s: %s", current_user.username, exc
        )
        state.append_log(f"[INTERCEPT] {config.method.value} failed: {exc}")
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/intercept_result.html",
            {"request": request, "result": None, "error": f"Intercept calculation failed: {exc}"},
        )

    state.last_intercept_result = result
    burn_summary = ", ".join(
        f"burn{b.burn_number} ΔV={b.delta_v_km_s:.3f}" for b in result.burns
    )
    state.append_log(
        f"[INTERCEPT] {config.method.value} applied: "
        f"total ΔV={result.total_delta_v_km_s:.3f} km/s, "
        f"{len(result.burns)} burn(s) [{burn_summary}], "
        f"arrival={result.arrival_epoch.strftime('%Y-%m-%d %H:%M UTC')}, "
        f"miss={result.intercept_range_km:.1f} km"
    )
    logger.info(
        "apply_intercept: %s for operator %s (%s → %s total_dv=%.3f km/s, burns=%d)",
        config.method.value, current_user.username,
        config.red_sat, config.blue_sat, result.total_delta_v_km_s, len(result.burns),
    )

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/intercept_result.html",
        {"request": request, "result": result, "error": None},
    )
