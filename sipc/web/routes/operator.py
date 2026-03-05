"""Operator dashboard and HTMX partial routes for SIPC web console."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from datetime import UTC, datetime

from sipc.domain.models import BlueAsset, RedTrack, RunConfig
from sipc.config.constants import STK_FOLDERS
from sipc.domain.scenario import ScenarioPlanner
from sipc.stk_adapter.exceptions import StkCommandError, StkConnectionError
from sipc.stk_adapter.fake import FakeStkSession
from sipc.web.auth import require_login
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter()


def _templates() -> object:
    from sipc.web.app import templates  # noqa: PLC0415

    return templates


# ── Dashboard ─────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Render the main operator console."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "operator.html",
        {
            "request": request,
            "user": current_user,
            "blue_assets": state.blue_assets,
            "red_tracks": state.red_tracks,
            "results": state.results,
            "log_entries": state.log_entries,
            "udl_user": state.udl_username,
            "stk_connected": state.stk_session is not None,
            "stk_scenario": state.stk_scenario,
        },
    )


# ── Asset management partials ─────────────────────────────────────────────────


@router.post("/assets/blue", response_class=HTMLResponse)
async def add_blue_asset(
    request: Request,
    name: Annotated[str, Form()],
    tle: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a blue asset and return the updated blue list partial."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    asset = BlueAsset(name=name.strip(), tle=tle.strip())
    state.blue_assets.append(asset)
    state.append_log(f"[BLUE] Added asset: {asset.stk_name}")

    if state.stk_session is not None:
        def _push_blue() -> None:
            state.append_log(f"[STK] Creating satellite object {asset.stk_name}…")
            state.stk_session.create_satellite(asset.stk_name, STK_FOLDERS[0])
            state.append_log(f"[STK] Loading TLE for {asset.stk_name}…")
            state.stk_session.set_propagator(asset.stk_name, asset.tle)

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _push_blue)
            state.append_log(f"[STK] {asset.stk_name} created and propagated")
        except Exception as exc:
            logger.warning("STK push failed for %s: %s", asset.stk_name, exc)
            state.append_log(f"[STK] WARNING: could not push {asset.stk_name} to STK — {exc}")

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/blue_list.html",
        {"request": request, "blue_assets": state.blue_assets},
    )


@router.delete("/assets/blue/{name}", response_class=HTMLResponse)
async def remove_blue_asset(
    request: Request,
    name: str,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a blue asset by name and return the updated partial."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    state.blue_assets = [a for a in state.blue_assets if a.name != name]
    state.append_log(f"[BLUE] Removed asset: {name}")
    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/blue_list.html",
        {"request": request, "blue_assets": state.blue_assets},
    )


@router.post("/assets/red", response_class=HTMLResponse)
async def add_red_track(
    request: Request,
    name: Annotated[str, Form()],
    tle: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a red track and return the updated red list partial."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    track = RedTrack(name=name.strip(), tle=tle.strip())
    state.red_tracks.append(track)
    state.append_log(f"[RED] Added track: {track.stk_name}")

    if state.stk_session is not None:
        def _push_red() -> None:
            state.append_log(f"[STK] Creating satellite object {track.stk_name}…")
            state.stk_session.create_satellite(track.stk_name, STK_FOLDERS[1])
            state.append_log(f"[STK] Loading TLE for {track.stk_name}…")
            state.stk_session.set_propagator(track.stk_name, track.tle)

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _push_red)
            state.append_log(f"[STK] {track.stk_name} created and propagated")
        except Exception as exc:
            logger.warning("STK push failed for %s: %s", track.stk_name, exc)
            state.append_log(f"[STK] WARNING: could not push {track.stk_name} to STK — {exc}")

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/red_list.html",
        {"request": request, "red_tracks": state.red_tracks},
    )


@router.delete("/assets/red/{name}", response_class=HTMLResponse)
async def remove_red_track(
    request: Request,
    name: str,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a red track by name and return the updated partial."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    state.red_tracks = [t for t in state.red_tracks if t.name != name]
    state.append_log(f"[RED] Removed track: {name}")
    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/red_list.html",
        {"request": request, "red_tracks": state.red_tracks},
    )


# ── Planning run ──────────────────────────────────────────────────────────────


@router.post("/plan", response_class=HTMLResponse)
async def run_plan(
    request: Request,
    operator: Annotated[str, Form()],
    source: Annotated[str, Form()],
    scenario: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Execute a planning run and return the results table partial."""
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if not state.blue_assets:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/results_table.html",
            {
                "request": request,
                "results": [],
                "error": "No blue assets defined. Add at least one blue asset before running.",
            },
        )
    if not state.red_tracks:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/results_table.html",
            {
                "request": request,
                "results": [],
                "error": "No red tracks defined. Add at least one red track before running.",
            },
        )

    config = RunConfig(operator=operator.strip(), source=source.strip())
    state.append_log(f"[RUN] Starting {config.run_id} — operator={operator}, source={source}")

    session_adapter = state.stk_session if state.stk_session is not None else FakeStkSession()
    if state.stk_session is None:
        state.append_log("[RUN] WARNING: STK not connected — using FakeStkSession (no real propagation)")
    planner = ScenarioPlanner(session_adapter, config)

    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(
            None, planner.plan, list(state.blue_assets), list(state.red_tracks)
        )
    except (StkConnectionError, StkCommandError) as exc:
        state.append_log(f"[RUN] ERROR: {exc}")
        logger.error("Planning run failed for operator %s: %s", current_user.username, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/results_table.html",
            {"request": request, "results": [], "error": str(exc)},
        )
    except Exception as exc:
        state.append_log(f"[RUN] ERROR: unexpected error — {exc}")
        logger.exception("Unexpected error in planning run for operator %s", current_user.username)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/results_table.html",
            {"request": request, "results": [], "error": f"Planning run failed: {exc}"},
        )

    state.results = results
    state.append_log(
        f"[RUN] {config.run_id} complete — {len(results)} intercept windows"
    )
    logger.info("Plan run %s complete: %d windows", config.run_id, len(results))

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/results_table.html",
        {"request": request, "results": results, "error": None},
    )


# ── STK connection ────────────────────────────────────────────────────────────


@router.post("/stk/connect", response_model=None)
async def stk_connect(
    request: Request,
    scenario_path: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Attach to a running STK instance and optionally load a scenario.

    Runs the blocking COM call in a thread-pool executor so the event loop
    is not blocked.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    from sipc.stk_adapter.com_session import StkComSession  # noqa: PLC0415

    session = StkComSession()
    path = scenario_path.strip()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, session.connect, path)
    except StkConnectionError as exc:
        logger.warning("STK connect failed for operator %s: %s", current_user.username, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/stk_status.html",
            {
                "request": request,
                "stk_connected": False,
                "stk_scenario": "",
                "error": str(exc),
            },
        )

    if state.stk_session is not None:
        state.stk_session.disconnect()
    state.stk_session = session
    state.stk_scenario = path
    state.append_log(
        f"[STK] Connected — {path or 'attached to running instance'}"
    )
    logger.info("STK connected for operator %s (scenario=%r)", current_user.username, path)

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/stk_status.html",
        {
            "request": request,
            "stk_connected": True,
            "stk_scenario": path,
            "error": None,
        },
    )


@router.post("/stk/new", response_model=None)
async def stk_new_scenario(
    request: Request,
    scenario_name: Annotated[str, Form()],
    scenario_start: Annotated[str, Form()] = "",
    scenario_stop: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Create a new blank STK scenario, closing any currently-open one.

    Runs the blocking COM call in a thread-pool executor.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    from sipc.stk_adapter.com_session import StkComSession  # noqa: PLC0415

    name = scenario_name.strip()
    if not name:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/stk_status.html",
            {
                "request": request,
                "stk_connected": False,
                "stk_scenario": "",
                "error": "Scenario name is required.",
            },
        )

    session = StkComSession()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, session.new_scenario, name)
    except StkConnectionError as exc:
        logger.warning("STK new_scenario failed for operator %s: %s", current_user.username, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/stk_status.html",
            {
                "request": request,
                "stk_connected": False,
                "stk_scenario": "",
                "error": str(exc),
            },
        )

    if state.stk_session is not None:
        state.stk_session.disconnect()
    state.stk_session = session
    state.stk_scenario = name
    state.append_log(f"[STK] New scenario created: {name}")
    logger.info("STK new scenario %r for operator %s", name, current_user.username)

    if scenario_start and scenario_stop:
        try:
            start_dt = datetime.fromisoformat(scenario_start).replace(tzinfo=UTC)
            stop_dt = datetime.fromisoformat(scenario_stop).replace(tzinfo=UTC)
            await loop.run_in_executor(None, session.set_scenario_time, start_dt, stop_dt)
            state.append_log(
                f"[STK] Scenario time: {scenario_start} → {scenario_stop} UTC"
            )
        except Exception as exc:
            logger.warning("Failed to set scenario time: %s", exc)
            state.append_log(f"[STK] WARNING: could not set scenario time — {exc}")

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/stk_status.html",
        {
            "request": request,
            "stk_connected": True,
            "stk_scenario": name,
            "error": None,
        },
    )


@router.post("/stk/disconnect", response_model=None)
async def stk_disconnect(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Release the STK COM session."""
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if state.stk_session is not None:
        state.stk_session.disconnect()
        state.stk_session = None
        state.stk_scenario = ""
    state.append_log("[STK] Disconnected")
    logger.info("STK disconnected for operator %s", current_user.username)

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/stk_status.html",
        {
            "request": request,
            "stk_connected": False,
            "stk_scenario": "",
            "error": None,
        },
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
    tmpl = _templates()
    state = get_session_state(current_user.username)
    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/run_log.html",
        {"request": request, "log_entries": state.log_entries},
    )


@router.post("/log/clear", response_class=HTMLResponse)
async def clear_log(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear the session run log and return the empty partial."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    state.log_entries.clear()
    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/run_log.html",
        {"request": request, "log_entries": state.log_entries},
    )
