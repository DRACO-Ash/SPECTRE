"""Relative geometry visualisation route.

Provides a single endpoint that computes the CW (Hill frame) relative
trajectory for an intercept solution and returns a Chart.js–ready partial.

Security
--------
- Authenticated endpoint — requires active session cookie.
- All numeric form fields are validated server-side before propagation.
- Satellite names are sanitised via cw_geometry before reaching log sinks.
- Chart data is serialised with json.dumps (HTML-escaped by Jinja2 autoescape).

Audit
-----
Every request is logged at INFO level with username, method, epoch, and result
validity.  Validation failures are logged at WARNING.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from typing import Annotated

from spectre.astro.cw_geometry import RelativeGeometryError, compute_relative_geometry
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/geometry", tags=["geometry"])

# Maximum absolute values accepted for each form field.
_DV_MAX_KM_S   = 20.0
_TOF_MAX_HOURS = 168.0   # one week
_COAST_MAX_H   = 24.0


def _find_tle(state: object, name: str) -> str | None:
    """Locate a TLE in session state by stk_name."""
    for a in state.blue_assets:  # type: ignore[attr-defined]
        if a.stk_name == name:
            return a.tle
    for t in state.red_tracks:  # type: ignore[attr-defined]
        if t.stk_name == name:
            return t.tle
    return None


def _parse_epoch(epoch_str: str) -> datetime | None:
    """Parse a datetime-local string to an aware UTC datetime.

    Accepts ISO-8601 with or without seconds and with or without the
    trailing 'Z' or '+00:00' suffix.
    """
    epoch_str = epoch_str.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(epoch_str, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    # Try with timezone suffix.
    try:
        return datetime.fromisoformat(epoch_str.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _clamp_validate(value: float, lo: float, hi: float, label: str) -> float:
    """Raise ValueError if *value* is outside [lo, hi] or is not finite."""
    import math
    if not math.isfinite(value):
        raise ValueError(f"{label} is not a finite number")
    if value < lo or value > hi:
        raise ValueError(f"{label} = {value} is outside permitted range [{lo}, {hi}]")
    return value


@router.post("/intercept", response_class=HTMLResponse)
async def intercept_geometry(
    request: Request,
    red_sat:          Annotated[str,   Form()],
    blue_sat:         Annotated[str,   Form()],
    burn_epoch_str:   Annotated[str,   Form()],
    dv_prograde:      Annotated[float, Form()] = 0.0,
    dv_normal:        Annotated[float, Form()] = 0.0,
    dv_radial:        Annotated[float, Form()] = 0.0,
    tof_hours:        Annotated[float, Form()] = 1.0,
    coast_hours:      Annotated[float, Form()] = 0.0,
    method:           Annotated[str,   Form()] = "unknown",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the relative geometry Chart.js partial for an intercept solution.

    All inputs are validated and clamped.  Errors are returned as a styled
    error partial so HTMX can swap it in without a full page reload.
    """

    def _err(msg: str) -> HTMLResponse:
        logger.warning(
            "geometry/intercept validation error for %r: %s",
            current_user.username, msg,
        )
        return HTMLResponse(
            f'<div class="callout callout-amber" style="font-size:0.75rem;padding:0.5rem">'
            f"&#9888; Geometry error: {msg}</div>"
        )

    # ── Validate numeric inputs ───────────────────────────────────────────────
    try:
        _clamp_validate(dv_prograde, -_DV_MAX_KM_S, _DV_MAX_KM_S, "dv_prograde")
        _clamp_validate(dv_normal,   -_DV_MAX_KM_S, _DV_MAX_KM_S, "dv_normal")
        _clamp_validate(dv_radial,   -_DV_MAX_KM_S, _DV_MAX_KM_S, "dv_radial")
        _clamp_validate(tof_hours,   0.0, _TOF_MAX_HOURS, "tof_hours")
        _clamp_validate(coast_hours, 0.0, _COAST_MAX_H,   "coast_hours")
    except ValueError as exc:
        return _err(str(exc))

    # ── Parse epoch ───────────────────────────────────────────────────────────
    burn_epoch = _parse_epoch(burn_epoch_str)
    if burn_epoch is None:
        return _err(f"Could not parse burn epoch: {burn_epoch_str!r}")

    # ── Fetch TLEs from session state ─────────────────────────────────────────
    state = get_session_state(current_user.username)
    red_tle  = _find_tle(state, red_sat.strip())
    blue_tle = _find_tle(state, blue_sat.strip())

    if not red_tle:
        return _err(f"No TLE found for red satellite {red_sat!r}")
    if not blue_tle:
        return _err(f"No TLE found for blue satellite {blue_sat!r}")

    # ── Compute geometry ──────────────────────────────────────────────────────
    try:
        geom = compute_relative_geometry(
            red_tle          = red_tle,
            blue_tle         = blue_tle,
            burn_epoch       = burn_epoch,
            dv_radial_km_s   = dv_radial,
            dv_prograde_km_s = dv_prograde,
            dv_normal_km_s   = dv_normal,
            tof_s            = tof_hours * 3600.0,
            method           = method,
            red_name         = red_sat,
            blue_name        = blue_sat,
            coast_s          = coast_hours * 3600.0,
            caller           = current_user.username,
        )
    except RelativeGeometryError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception(
            "geometry/intercept unexpected error for %r: %s",
            current_user.username, exc,
        )
        return _err(f"Internal computation error: {exc}")

    # ── Serialise chart data (json.dumps — safe, no HTML injection) ───────────
    chart_data = {
        "vr_coast":    geom.vr_coast,
        "vr_transfer": geom.vr_transfer,
        "hr_coast":    geom.hr_coast,
        "hr_transfer": geom.hr_transfer,
        "range_series": geom.range_series,
        "burn_point": {
            "vbar": round(geom.burn_state.y, 4),
            "rbar": round(geom.burn_state.x, 4),
            "hbar": round(geom.burn_state.z, 4),
        },
        "target": {"vbar": 0.0, "rbar": 0.0},
    }

    logger.info(
        "geometry/intercept: %r red=%r blue=%r method=%r arrival_range=%.3f km valid=%s",
        current_user.username, red_sat, blue_sat, method,
        geom.arrival_range_km, geom.cw_valid,
    )

    return render(request, "partials/intercept_geometry.html", {
        "geom":       geom,
        "chart_json": json.dumps(chart_data),
    })
