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

import html
import json
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from spectre.astro.cw_geometry import RelativeGeometryError, compute_relative_geometry
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.format_units import to_m_s
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/geometry", tags=["geometry"])

# Maximum absolute values accepted for each form field.
#
# The burn components arrive in m/s, because they are posted straight back from
# the intercept result panel, which the operator reads in m/s. They are handed
# to the astro layer in km/s. That conversion is the whole reason this constant
# changed: at ±20 km/s the clamp silently rejected any burn above 20 m/s the
# moment the panel started emitting m/s, and anything that got through would
# have reached the Clohessy-Wiltshire propagator a thousand times too large.
_DV_MAX_M_S    = 20_000.0
_TOF_MAX_HOURS = 168.0   # one week
_COAST_MAX_H   = 24.0


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


def _range_problem(value: float, lo: float, hi: float, label: str) -> str | None:
    """Why *value* is not usable, or ``None`` when it is finite and in [lo, hi].

    Returned rather than raised: a message carried by an exception and then
    shown to the operator is what CodeQL's exception-exposure query reports.
    """
    import math
    if not math.isfinite(value):
        return f"{label} is not a finite number"
    if value < lo or value > hi:
        return f"{label} = {value} is outside permitted range [{lo}, {hi}]"
    return None


@router.post("/intercept", response_class=HTMLResponse)
async def intercept_geometry(
    request: Request,
    red_sat:          Annotated[str,   Form()],
    blue_sat:         Annotated[str,   Form()],
    burn_epoch_str:   Annotated[str,   Form()],
    *,
    dv_prograde_m_s:  Annotated[float, Form(alias="dv_prograde")] = 0.0,
    dv_normal_m_s:    Annotated[float, Form(alias="dv_normal")] = 0.0,
    dv_radial_m_s:    Annotated[float, Form(alias="dv_radial")] = 0.0,
    tof_hours:        Annotated[float, Form()] = 1.0,
    coast_hours:      Annotated[float, Form()] = 0.0,
    method:           Annotated[str,   Form()] = "unknown",
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Return the relative geometry Chart.js partial for an intercept solution.

    All inputs are validated and clamped.  Errors are returned as a styled
    error partial so HTMX can swap it in without a full page reload.
    """

    def _err(msg: str) -> HTMLResponse:
        """Render a validation error. The message is escaped, never trusted.

        Callers interpolate user-supplied values (satellite names, epoch
        strings) into *msg*, and this response bypasses Jinja, so escaping here
        is the only thing standing between a crafted form field and reflected
        script execution in the operator's browser.
        """
        logger.warning(
            "geometry/intercept validation error for %r: %s",
            log_safe(current_user.username), log_safe(msg),
        )
        safe = html.escape(msg, quote=True)
        return HTMLResponse(
            f'<div class="callout callout-amber" style="font-size:0.75rem;padding:0.5rem">'
            f"&#9888; Geometry error: {safe}</div>"
        )

    # ── Validate numeric inputs ───────────────────────────────────────────────
    problem = next((p for p in (
        _range_problem(dv_prograde_m_s, -_DV_MAX_M_S, _DV_MAX_M_S, "dv_prograde"),
        _range_problem(dv_normal_m_s,   -_DV_MAX_M_S, _DV_MAX_M_S, "dv_normal"),
        _range_problem(dv_radial_m_s,   -_DV_MAX_M_S, _DV_MAX_M_S, "dv_radial"),
        _range_problem(tof_hours,   0.0, _TOF_MAX_HOURS, "tof_hours"),
        _range_problem(coast_hours, 0.0, _COAST_MAX_H,   "coast_hours"),
    ) if p is not None), None)
    if problem is not None:
        return _err(problem)

    # ── Parse epoch ───────────────────────────────────────────────────────────
    burn_epoch = _parse_epoch(burn_epoch_str)
    if burn_epoch is None:
        return _err(f"Could not parse burn epoch: {burn_epoch_str!r}")

    # ── Fetch TLEs from session state ─────────────────────────────────────────
    state = get_session_state(current_user)
    red_tle  = state.tle_of(red_sat.strip())
    blue_tle = state.tle_of(blue_sat.strip())

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
            # The astro layer takes km/s; the form carries m/s. One conversion.
            dv_radial_km_s   = dv_radial_m_s / 1000.0,
            dv_prograde_km_s = dv_prograde_m_s / 1000.0,
            dv_normal_km_s   = dv_normal_m_s / 1000.0,
            tof_s            = tof_hours * 3600.0,
            method           = method,
            red_name         = red_sat,
            blue_name        = blue_sat,
            coast_s          = coast_hours * 3600.0,
            caller           = current_user.username,
        )
    # The detail goes to the log, not the page: exception text can carry
    # internals (TLE fragments, solver state) the operator has no use for.
    except RelativeGeometryError as exc:
        logger.warning("geometry/intercept refused: %s", log_safe(exc))
        return _err("the relative geometry could not be computed from these inputs; see the server log.")
    except Exception as exc:
        logger.exception(
            "geometry/intercept unexpected error for %r: %s",
            log_safe(current_user.username), log_safe(exc),
        )
        return _err("internal computation error; see the server log.")

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
        "geometry/intercept: %r red=%r blue=%r method=%r arrival_range=%s km valid=%s",
        log_safe(current_user.username), log_safe(red_sat), log_safe(blue_sat), log_safe(method),
        log_safe(format(geom.arrival_range_km, ".3f")), log_safe(geom.cw_valid),
    )

    return render(request, "partials/intercept_geometry.html", {
        "geom":       geom,
        # THIS IS THE UNIT BOUNDARY for the Hill-frame panel. CWState carries
        # km/s (cw_geometry.py), the operator reads m/s. Converted here so the
        # template performs no arithmetic of its own.
        "burn_xd_m_s": to_m_s(geom.burn_state.xd),
        "burn_yd_m_s": to_m_s(geom.burn_state.yd),
        "burn_zd_m_s": to_m_s(geom.burn_state.zd),
        "chart_json": json.dumps(chart_data),
    })
