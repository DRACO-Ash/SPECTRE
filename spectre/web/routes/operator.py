"""Operator dashboard and HTMX partial routes for SPECTRE web console."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from spectre.config.constants import BLUE_PREFIX, RED_PREFIX
from spectre.domain.models import BlueAsset, RedTrack
from spectre.web.auth import require_login
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
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the main operator console."""
    state = get_session_state(current_user.username)
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


@router.post("/assets/blue", response_class=HTMLResponse)
async def add_blue_asset(
    request: Request,
    name: Annotated[str, Form()],
    tle: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a blue asset and return the updated blue list partial."""
    state = get_session_state(current_user.username)

    name = name.strip()
    tle = tle.strip()
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
    state = get_session_state(current_user.username)
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
        oob_badge = (
            f'<span id="{btn_id}" hx-swap-oob="true"'
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
    state = get_session_state(current_user.username)
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
        oob_badge = (
            f'<span id="{btn_id}" hx-swap-oob="true"'
            f' class="badge-red" style="font-size:0.68rem">&#10003; Added</span>'
        )
    body2 = resp_html.body
    list_html2 = bytes(body2).decode() if not isinstance(body2, bytes) else body2.decode()
    return HTMLResponse(list_html2 + oob_badge)


@router.delete("/assets/blue/{name}", response_class=HTMLResponse)
async def remove_blue_asset(
    request: Request,
    name: str,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a blue asset by name and return the updated partial."""
    state = get_session_state(current_user.username)
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
    state = get_session_state(current_user.username)

    name = name.strip()
    tle = tle.strip()
    track = RedTrack(name=name, tle=tle)

    if any(t.stk_name == track.stk_name for t in state.red_tracks):
        ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": f"{track.stk_name} is already in the session."}
        return _list_response(request, "partials/red_list.html", ctx)

    state.red_tracks.append(track)
    state.append_log(f"[RED] Added track: {track.stk_name}")

    ctx = {"red_tracks": state.red_tracks, "blue_assets": state.blue_assets, "error": None}
    return _list_response(request, "partials/red_list.html", ctx)


@router.delete("/assets/red/{name}", response_class=HTMLResponse)
async def remove_red_track(
    request: Request,
    name: str,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a red track by name and return the updated partial."""
    state = get_session_state(current_user.username)
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
    state = get_session_state(current_user.username)

    try:
        start_dt = datetime.fromisoformat(scenario_start.strip()).replace(tzinfo=UTC)
        stop_dt = datetime.fromisoformat(scenario_stop.strip()).replace(tzinfo=UTC)
    except ValueError as exc:
        return HTMLResponse(f'<p class="error-msg">Invalid date: {exc}</p>')

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


# ── Log streaming (SSE) ───────────────────────────────────────────────────────


@router.get("/log/stream", response_model=None)
async def log_stream(
    request: Request,
    current_user: User = Depends(require_login),
) -> StreamingResponse:
    """Server-Sent Events endpoint streaming per-session log entries."""


    state = get_session_state(current_user.username)

    from collections.abc import AsyncGenerator  # noqa: PLC0415

    async def _event_generator() -> AsyncGenerator[str, None]:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(state.log_queue.get(), timeout=15.0)
                yield f"data: {msg}\n\n"
            except TimeoutError:
                yield ": heartbeat\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/log/entries", response_class=HTMLResponse)
async def log_entries(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the run log partial (for polling fallback)."""
    state = get_session_state(current_user.username)
    return render(request, "partials/run_log.html", {"log_entries": state.log_entries})


@router.post("/log/clear", response_class=HTMLResponse)
async def clear_log(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear the session run log and return the empty partial."""
    state = get_session_state(current_user.username)
    state.log_entries.clear()
    return render(request, "partials/run_log.html", {"log_entries": state.log_entries})
