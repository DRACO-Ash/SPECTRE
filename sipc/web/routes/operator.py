"""Operator dashboard and HTMX partial routes for SIPC web console."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from datetime import UTC, datetime

from sipc.app_logging.setup import configure_logging
from sipc.config.settings import get_settings
from sipc.domain.models import BlueAsset, RedTrack, RunConfig
from sipc.web.auth import require_login
from sipc.web.deps import get_templates, render
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Internal helpers ───────────────────────────────────────────────────────────


def _list_response(request: Request, template: str, context: dict) -> HTMLResponse:
    """Render a list partial plus OOB satellite-select updates for HTMX.

    On HTMX requests the response includes out-of-band ``<select>`` swaps
    so the Maneuver Options and Intercept Engine dropdowns stay in sync.
    """
    tmpl = get_templates()
    list_html = tmpl.get_template(template).render(context)  # type: ignore[union-attr]
    oob_html = tmpl.get_template("partials/sat_select_oob.html").render(context)  # type: ignore[union-attr]
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
) -> HTMLResponse:
    """Server-Sent Events endpoint streaming per-session log entries."""
    from fastapi.responses import StreamingResponse  # noqa: PLC0415

    state = get_session_state(current_user.username)

    async def _event_generator() -> object:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(state.log_queue.get(), timeout=15.0)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"

    return StreamingResponse(  # type: ignore[return-value]
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
