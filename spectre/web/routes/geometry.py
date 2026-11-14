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
from pydantic import BaseModel, Field

from spectre.astro.cw_geometry import RelativeGeometryError, compute_relative_geometry
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.elsets import _epoch_of
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
TOF_MAX_HOURS = 168.0   # one week
COAST_MAX_H   = 24.0


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


class _GeometryForm(BaseModel):
    """The geometry panel's fields, bound from the form by name; the burn components keep their posted names.

    The last four come only from a Decision Engine cell's Show trajectory form (SPC-124): the element-set epochs
    its evaluation used, which propagator its figures come from, and whether the burn drawn is ours.
    """

    red_sat:         str
    blue_sat:        str
    burn_epoch_str:  str
    dv_prograde_m_s: float = Field(default=0.0, alias="dv_prograde")
    dv_normal_m_s:   float = Field(default=0.0, alias="dv_normal")
    dv_radial_m_s:   float = Field(default=0.0, alias="dv_radial")
    tof_hours:       float = 1.0
    coast_hours:     float = 0.0
    method:          str   = "unknown"
    red_epoch:       str   = ""
    blue_epoch:      str   = ""
    context:         str   = ""
    our_burn:        bool  = False


#: What a Decision Engine cell's figures come from, by the context its form posts. Allowlisted: a context not
#: here shows no note, and nothing posted is echoed.
_DECISION_PROPAGATORS: dict[str, str] = {
    "decision-sgp4": "SGP4 for both orbits, from their element sets, with no burn",
    "decision-rk45": "RK45 with J2 and exponential drag for both orbits",
}
_DECISION_VIEW_NOTE = (
    "A Clohessy-Wiltshire picture of the red track relative to the blue asset, from both SGP4 states at its start: "
    "it shows the shape of the approach, not the figures in the cell, which come from {propagator}. Where they "
    "differ, the cell's figures stand."
)
_OUR_BURN_DRAWN = (
    "Our burn is drawn as the opposite change in the red track's velocity relative to the blue asset, which is how "
    "it moves the pair in this frame."
)
_HELD_NEWER = (
    "Drawn from the element set now held for {side}, epoch {held:%Y-%m-%d %H:%M} UTC, not the one this evaluation "
    "used, epoch {used:%Y-%m-%d %H:%M} UTC."
)


#: Which panel the view fills, by its id prefix, and the control that opened it. The intercept result has one
#: opener; the Decision Engine results mark the cell's form that was submitted. Both panels can be open on the
#: operator page at once, so they share no id and each returns focus to its own opener.
_INTERCEPT_PANEL = ("", "form[hx-target='#intercept-geometry-container'] button[type=submit]")
_DECISION_PANEL = ("decision-", "form.show-trajectory[data-geometry-opener] button[type=submit]")


def _held_note(side: str, held_tle: str, posted: str) -> str | None:
    """A sentence when the element set held for *side* is not the one the evaluation used; None when it is, or
    either epoch cannot be read. Built from parsed times, never the posted text."""
    used = _parse_epoch(posted) if posted.strip() else None
    held = _epoch_of(held_tle)
    # The form carries the epoch to the second, and a TLE's day fraction rounds below it.
    if used is None or held is None or abs((held - used).total_seconds()) < 1.0:
        return None
    return _HELD_NEWER.format(side=side, held=held, used=used)


def _decision_notes(form: _GeometryForm, red_tle: str, blue_tle: str) -> list[str]:
    """What the view is when a Decision Engine cell opened it, in fixed sentences; empty otherwise."""
    propagator = _DECISION_PROPAGATORS.get(form.context)
    notes = [] if propagator is None else [_DECISION_VIEW_NOTE.format(propagator=propagator)]
    if propagator is not None and form.our_burn:
        notes.append(_OUR_BURN_DRAWN)
    held = (_held_note("red", red_tle, form.red_epoch), _held_note("blue", blue_tle, form.blue_epoch))
    return notes + [note for note in held if note is not None]


def _geometry_error(username: str, msg: str) -> HTMLResponse:
    """Render a validation error. The message is escaped, never trusted.

    Callers interpolate user-supplied values (satellite names, epoch
    strings) into *msg*, and this response bypasses Jinja, so escaping here
    is the only thing standing between a crafted form field and reflected
    script execution in the operator's browser.
    """
    logger.warning(
        "geometry/intercept validation error for %r: %s",
        log_safe(username), log_safe(msg),
    )
    safe = html.escape(msg, quote=True)
    return HTMLResponse(
        f'<div class="callout callout-amber" style="font-size:0.75rem;padding:0.5rem">'
        f"&#9888; Geometry error: {safe}</div>"
    )


@router.post("/intercept", response_class=HTMLResponse)
async def intercept_geometry(
    request: Request,
    form: Annotated[_GeometryForm, Form()],
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Return the relative geometry Chart.js partial for an intercept solution.

    All inputs are validated and clamped.  Errors are returned as a styled
    error partial so HTMX can swap it in without a full page reload.
    """
    red_sat, blue_sat = form.red_sat, form.blue_sat

    def _err(msg: str) -> HTMLResponse:
        return _geometry_error(current_user.username, msg)

    # ── Validate numeric inputs ───────────────────────────────────────────────
    problem = next((p for p in (
        _range_problem(form.dv_prograde_m_s, -_DV_MAX_M_S, _DV_MAX_M_S, "dv_prograde"),
        _range_problem(form.dv_normal_m_s,   -_DV_MAX_M_S, _DV_MAX_M_S, "dv_normal"),
        _range_problem(form.dv_radial_m_s,   -_DV_MAX_M_S, _DV_MAX_M_S, "dv_radial"),
        _range_problem(form.tof_hours,   0.0, TOF_MAX_HOURS, "tof_hours"),
        _range_problem(form.coast_hours, 0.0, COAST_MAX_H,   "coast_hours"),
    ) if p is not None), None)
    if problem is not None:
        return _err(problem)

    # ── Parse epoch ───────────────────────────────────────────────────────────
    burn_epoch = _parse_epoch(form.burn_epoch_str)
    if burn_epoch is None:
        return _err(f"Could not parse burn epoch: {form.burn_epoch_str!r}")

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
            dv_radial_km_s   = form.dv_radial_m_s / 1000.0,
            dv_prograde_km_s = form.dv_prograde_m_s / 1000.0,
            dv_normal_km_s   = form.dv_normal_m_s / 1000.0,
            tof_s            = form.tof_hours * 3600.0,
            method           = form.method,
            red_name         = red_sat,
            blue_name        = blue_sat,
            coast_s          = form.coast_hours * 3600.0,
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
        log_safe(current_user.username), log_safe(red_sat), log_safe(blue_sat), log_safe(form.method),
        log_safe(format(geom.arrival_range_km, ".3f")), log_safe(geom.cw_valid),
    )

    id_prefix, opener = _DECISION_PANEL if form.context in _DECISION_PROPAGATORS else _INTERCEPT_PANEL
    return render(request, "partials/intercept_geometry.html", {
        "geom":       geom,
        "id_prefix":  id_prefix,
        "opener_selector": opener,
        # THIS IS THE UNIT BOUNDARY for the Hill-frame panel. CWState carries
        # km/s (cw_geometry.py), the operator reads m/s. Converted here so the
        # template performs no arithmetic of its own.
        "burn_xd_m_s": to_m_s(geom.burn_state.xd),
        "burn_yd_m_s": to_m_s(geom.burn_state.yd),
        "burn_zd_m_s": to_m_s(geom.burn_state.zd),
        "chart_json": json.dumps(chart_data),
        # Fixed sentences only (SPC-124): never the posted context or epochs.
        "decision_notes": _decision_notes(form, red_tle, blue_tle),
    })
