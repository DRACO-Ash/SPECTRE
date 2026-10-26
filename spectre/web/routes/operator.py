"""Operator dashboard and HTMX partial routes for SPECTRE web console."""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from spectre.astro.propagator import TLE_ERRORS, TLEOrbit
from spectre.config.constants import BLUE_PREFIX, RED_PREFIX
from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.auth import optional_login, require_login
from spectre.web.deps import get_templates, render
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Internal helpers ───────────────────────────────────────────────────────────


def _list_response(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    """Render a list partial plus OOB satellite-select updates for HTMX.

    On HTMX requests the response includes out-of-band ``<select>`` swaps
    so the Maneuver Options and Intercept Engine dropdowns stay in sync.
    """
    tmpl = get_templates()
    list_html = tmpl.get_template(template).render(context)
    oob_html = tmpl.get_template("partials/sat_select_oob.html").render(context)
    return HTMLResponse(list_html + oob_html)


# ── Dashboard ─────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: Annotated[User | None, Depends(optional_login)],
) -> HTMLResponse:
    """Render the main operator console, or the login page when anonymous.

    Returns 200 in both cases. The App Store router probes ``GET /`` and treats
    a 302 as a failed deploy, so an anonymous caller is served the login page
    directly rather than redirected. No console state is rendered without a
    valid session.
    """
    if current_user is None:
        from spectre.web.routes.login import render_login

        return render_login(request)

    state = get_session_state(current_user)
    return render(request, "operator.html", {
        "user": current_user,
        "blue_assets": state.blue_assets,
        "red_tracks": state.red_tracks,
        "results": state.results,
        "log_entries": state.log_entries,
        "udl_user": state.udl_username,
        "scenario_start": state.scenario_start,
        "udl_data_mode": state.udl_data_mode,
        "udl_tle_source": state.udl_tle_source,
        "udl_available_sources": state.udl_available_sources,
    })


# ── Asset management partials ─────────────────────────────────────────────────


def _as_utc(moment: datetime) -> datetime:
    """*moment* in UTC: converted when it carries an offset, assumed UTC when naive.

    ``.replace(tzinfo=UTC)`` relabelled an offset time instead of converting
    it, so "12:00+01:00" became 12:00 UTC, an hour late (audit F-266).
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _add_refusal(name: str, tle: str) -> str | None:
    """Why a hand-entered asset cannot be added, or ``None`` when it can.

    The add routes used to accept an empty name and any text as a TLE, and
    the bad TLE then failed far from here, in whichever solver met it first
    (audit F-267).
    """
    if not name:
        return "A name is required."
    lines = [ln.strip() for ln in tle.splitlines() if ln.strip()]
    if len(lines) < 2 or not lines[-2].startswith("1 ") or not lines[-1].startswith("2 "):  # noqa: PLR2004
        return "The TLE needs its line 1 and line 2."
    try:
        TLEOrbit(tle)
    except TLE_ERRORS:
        return "The TLE could not be parsed."
    return None


@router.post("/assets/blue", response_class=HTMLResponse)
async def add_blue_asset(
    request: Request,
    name: Annotated[str, Form()],
    tle: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a blue asset and return the updated blue list partial."""
    state = get_session_state(current_user)

    name = name.strip()
    tle = tle.strip()
    refusal = _add_refusal(name, tle)
    if refusal is not None:
        ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks, "error": refusal}
        return _list_response(request, "partials/blue_list.html", ctx)
    asset = BlueAsset(name=name, tle=tle)

    if any(a.stk_name == asset.stk_name for a in state.blue_assets):
        ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks, "error": f"{asset.stk_name} is already in the session."}
        return _list_response(request, "partials/blue_list.html", ctx)

    state.blue_assets.append(asset)
    state.append_log(f"[BLUE] Added asset: {asset.stk_name}")

    ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks, "error": None}
    return _list_response(request, "partials/blue_list.html", ctx)


@router.post("/assets/blue/quick-add", response_class=HTMLResponse)
async def quick_add_blue_asset(
    request: Request,
    satno: Annotated[int, Form()],
    name: Annotated[str, Form()],
    btn_id: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch TLE from UDL and immediately add the satellite as a blue asset.

    Called from the HRR watchlist "→ Blue" button for one-click ingestion.
    Returns the updated blue list partial with OOB select updates.
    """
    state = get_session_state(current_user)
    clean_name = name.strip() or str(satno)

    # Skip if already in the session.
    prospective_stk = f"{BLUE_PREFIX}{clean_name}"
    if any(a.stk_name == prospective_stk for a in state.blue_assets):
        ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks,
               "error": f"{prospective_stk} is already in the session."}
        return _list_response(request, "partials/blue_list.html", ctx)

    # Fetch TLE from UDL.
    if not state.udl_username or not state.udl_password:
        ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks,
               "error": "Not connected to UDL — cannot fetch TLE."}
        return _list_response(request, "partials/blue_list.html", ctx)

    from spectre.web.routes.udl import fetch_tle_for_satno

    _result = await fetch_tle_for_satno(
        satno, state.udl_username, state.udl_password,
        data_mode=state.udl_data_mode or "REAL",
        source=state.udl_tle_source,
    )
    tle = _result[0] if _result else None
    if not tle:
        ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks,
               "error": f"TLE fetch failed for {clean_name} ({satno})."}
        return _list_response(request, "partials/blue_list.html", ctx)

    asset = BlueAsset(name=clean_name, tle=tle)
    state.blue_assets.append(asset)
    state.append_log(f"[BLUE] Quick-added from HRR: {asset.stk_name} (SATNO {satno})")

    ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks, "error": None}
    resp_html = _list_response(request, "partials/blue_list.html", ctx)

    oob_badge = ""
    if btn_id:
        # btn_id arrives from a form field and is written into an id
        # attribute, so it must be escaped before it reaches the browser.
        oob_badge = (
            f'<span id="{html.escape(btn_id, quote=True)}" hx-swap-oob="true"'
            f' class="badge-ok" style="font-size:0.68rem">&#10003; Added</span>'
        )
    body = resp_html.body
    list_html = bytes(body).decode() if not isinstance(body, bytes) else body.decode()
    return HTMLResponse(list_html + oob_badge)


@router.post("/assets/red/quick-add", response_class=HTMLResponse)
async def quick_add_red_track(
    request: Request,
    satno: Annotated[int, Form()],
    name: Annotated[str, Form()],
    btn_id: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch TLE from UDL and immediately add the satellite as a red track.

    Called from the HRR watchlist "→ Red" button for one-click ingestion.
    Returns the updated red list partial with OOB select updates and an OOB
    badge replacing the button that was clicked.
    """
    state = get_session_state(current_user)
    clean_name = name.strip() or str(satno)

    prospective_stk = f"{RED_PREFIX}{clean_name}"
    if any(t.stk_name == prospective_stk for t in state.red_tracks):
        ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets,
               "error": f"{prospective_stk} is already in the session."}
        return _list_response(request, "partials/red_list.html", ctx)

    if not state.udl_username or not state.udl_password:
        ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets,
               "error": "Not connected to UDL — cannot fetch TLE."}
        return _list_response(request, "partials/red_list.html", ctx)

    from spectre.web.routes.udl import fetch_tle_for_satno

    _result = await fetch_tle_for_satno(
        satno, state.udl_username, state.udl_password,
        data_mode=state.udl_data_mode or "REAL",
        source=state.udl_tle_source,
    )
    tle = _result[0] if _result else None
    if not tle:
        ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets,
               "error": f"TLE fetch failed for {clean_name} ({satno})."}
        return _list_response(request, "partials/red_list.html", ctx)

    track = RedTrack(name=clean_name, tle=tle)
    state.red_tracks.append(track)
    state.append_log(f"[RED] Quick-added from HRR: {track.stk_name} (SATNO {satno})")

    ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": None}
    resp_html = _list_response(request, "partials/red_list.html", ctx)

    oob_badge = ""
    if btn_id:
        # btn_id arrives from a form field and is written into an id
        # attribute, so it must be escaped before it reaches the browser.
        oob_badge = (
            f'<span id="{html.escape(btn_id, quote=True)}" hx-swap-oob="true"'
            f' class="badge-red" style="font-size:0.68rem">&#10003; Added</span>'
        )
    body2 = resp_html.body
    list_html2 = bytes(body2).decode() if not isinstance(body2, bytes) else body2.decode()
    return HTMLResponse(list_html2 + oob_badge)


# {name:path}: a name may hold "/", which the template percent-encodes and the
# router decodes before matching (audit F-267).
@router.delete("/assets/blue/{name:path}", response_class=HTMLResponse)
async def remove_blue_asset(
    request: Request,
    name: str,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a blue asset by name and return the updated partial."""
    state = get_session_state(current_user)
    state.blue_assets = [a for a in state.blue_assets if a.name != name]
    state.append_log(f"[BLUE] Removed asset: {name}")
    ctx = {"blue_assets": state.blue_assets, "red_tracks": state.red_tracks, "error": None}
    return _list_response(request, "partials/blue_list.html", ctx)


@router.post("/assets/red", response_class=HTMLResponse)
async def add_red_track(
    request: Request,
    name: Annotated[str, Form()],
    tle: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a red track and return the updated red list partial."""
    state = get_session_state(current_user)

    name = name.strip()
    tle = tle.strip()
    refusal = _add_refusal(name, tle)
    if refusal is not None:
        ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": refusal}
        return _list_response(request, "partials/red_list.html", ctx)
    track = RedTrack(name=name, tle=tle)

    if any(t.stk_name == track.stk_name for t in state.red_tracks):
        ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": f"{track.stk_name} is already in the session."}
        return _list_response(request, "partials/red_list.html", ctx)

    state.red_tracks.append(track)
    state.append_log(f"[RED] Added track: {track.stk_name}")

    ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": None}
    return _list_response(request, "partials/red_list.html", ctx)


@router.delete("/assets/red/{name:path}", response_class=HTMLResponse)
async def remove_red_track(
    request: Request,
    name: str,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a red track by name and return the updated partial."""
    state = get_session_state(current_user)
    state.red_tracks = [t for t in state.red_tracks if t.name != name]
    state.append_log(f"[RED] Removed track: {name}")
    ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": None}
    return _list_response(request, "partials/red_list.html", ctx)


# ── Scenario time ────────────────────────────────────────────────────────────


@router.post("/scenario/time", response_model=None)
async def set_scenario_time(
    request: Request,
    scenario_start: Annotated[str, Form()],
    scenario_stop: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Set the scenario time window for event detection and planning."""
    state = get_session_state(current_user)

    try:
        start_dt = _as_utc(datetime.fromisoformat(scenario_start.strip()))
        stop_dt = _as_utc(datetime.fromisoformat(scenario_stop.strip()))
    except ValueError:
        # datetime.fromisoformat quotes the offending input verbatim in its
        # message, and this response is built by hand rather than by Jinja, so
        # echoing the exception reflected the operator's form field into the
        # page as live markup. Nothing from the exception reaches the browser.
        return HTMLResponse(
            '<p class="error-msg">Invalid date. Use ISO 8601, for example '
            '2026-01-01T00:00:00.</p>'
        )

    if stop_dt <= start_dt:
        return HTMLResponse('<p class="error-msg">Stop must be after start.</p>')

    state.scenario_start = start_dt
    state.scenario_stop = stop_dt
    state.append_log(
        f"[SCENARIO] Time set: {start_dt.strftime('%Y-%m-%d %H:%M')} → "
        f"{stop_dt.strftime('%Y-%m-%d %H:%M')} UTC"
    )

    return HTMLResponse(
        f'<p class="badge-ok">Scenario: {start_dt.strftime("%Y-%m-%d %H:%M")} → '
        f'{stop_dt.strftime("%Y-%m-%d %H:%M")} UTC</p>'
    )


# ── Run log ───────────────────────────────────────────────────────────────────


@router.get("/log/entries", response_class=HTMLResponse)
async def log_entries(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the run log partial. The console polls this; nothing streams.

    There was a Server-Sent Events endpoint beside it, built by interpolating
    a session log line straight into the frame, so a newline in operator input
    forged extra frames. No template, script or test ever opened it: the
    console has always polled this route. Removed rather than sanitised,
    because a live defect in code nobody runs is still a line in the scan.
    """
    state = get_session_state(current_user)
    return render(request, "partials/run_log.html", {"log_entries": state.log_entries})


@router.post("/log/clear", response_class=HTMLResponse)
async def clear_log(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear the session run log and return the empty partial."""
    state = get_session_state(current_user)
    state.log_entries.clear()
    return render(request, "partials/run_log.html", {"log_entries": state.log_entries})
