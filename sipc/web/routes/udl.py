"""UDL (Unified Data Library) proxy routes for SIPC.

Provides session-scoped UDL authentication and TLE fetch endpoints.
Credentials are held in memory for the duration of the operator session
and are never written to disk or the database.
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from sipc.web.auth import require_login
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/udl")

_UDL_BASE = "https://unifieddatalibrary.com/udl"


def _templates() -> object:
    """Import templates lazily to avoid circular import at module load."""
    from sipc.web.app import templates  # noqa: PLC0415

    return templates


# ── UDL session management ─────────────────────────────────────────────────


@router.post("/login", response_model=None)
async def udl_login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Validate UDL credentials and store them in the operator session.

    Performs a lightweight probe request to UDL to confirm the credentials
    are accepted before storing them.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/elset",
                params={"maxResults": 1},
                auth=(username, password),
                timeout=10.0,
            )
        if resp.status_code == 401:
            logger.warning("UDL login rejected for operator %s", current_user.username)
            return tmpl.TemplateResponse(  # type: ignore[attr-defined]
                "partials/udl_status.html",
                {"request": request, "udl_user": None, "error": "Invalid UDL credentials."},
            )
        resp.raise_for_status()
    except httpx.TimeoutException:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/udl_status.html",
            {"request": request, "udl_user": None, "error": "UDL connection timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL login probe failed: %s", exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/udl_status.html",
            {"request": request, "udl_user": None, "error": f"UDL unreachable: {exc}"},
        )

    state.udl_username = username
    state.udl_password = password
    state.append_log(f"[UDL] Connected as {username}")
    logger.info("UDL credentials stored for operator: %s", current_user.username)

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/udl_status.html",
        {"request": request, "udl_user": username, "error": None},
    )


@router.post("/logout", response_model=None)
async def udl_logout(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear UDL credentials from the operator session."""
    tmpl = _templates()
    state = get_session_state(current_user.username)
    state.udl_username = None
    state.udl_password = None
    state.append_log("[UDL] Disconnected")
    logger.info("UDL credentials cleared for operator: %s", current_user.username)

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/udl_status.html",
        {"request": request, "udl_user": None, "error": None},
    )


# ── TLE fetch proxy ────────────────────────────────────────────────────────


@router.get("/tle", response_model=None)
async def fetch_tle(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch the latest TLE for *satno* from UDL and return a pre-filled form partial.

    The returned partial replaces the name/TLE fields in the add-asset form
    so the operator can immediately submit without manual entry.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if not state.udl_username or not state.udl_password:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/tle_fields.html",
            {
                "request": request,
                "name": "",
                "tle": "",
                "error": "Not connected to UDL — use the UDL panel to log in first.",
            },
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/elset",
                params={"catalogId": satno, "maxResults": 1, "orderby": "EPOCH desc"},
                auth=(state.udl_username, state.udl_password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}"
        logger.warning(error)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/tle_fields.html",
            {"request": request, "name": "", "tle": "", "error": error},
        )
    except httpx.TimeoutException:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/tle_fields.html",
            {"request": request, "name": "", "tle": "", "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL TLE fetch failed for SATNO %s: %s", satno, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/tle_fields.html",
            {"request": request, "name": "", "tle": "", "error": f"UDL unreachable: {exc}"},
        )

    if not data:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/tle_fields.html",
            {
                "request": request,
                "name": "",
                "tle": "",
                "error": f"No elset found for SATNO {satno}.",
            },
        )

    rec = data[0]
    name = str(rec.get("OBJECT_NAME", satno)).strip()
    line1 = str(rec.get("TLE_LINE1", "")).strip()
    line2 = str(rec.get("TLE_LINE2", "")).strip()
    tle = f"{line1}\n{line2}"

    state.append_log(f"[UDL] Fetched TLE for SATNO {satno} ({name})")
    logger.info("TLE fetched for SATNO %s (%s) by operator %s", satno, name, current_user.username)

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/tle_fields.html",
        {"request": request, "name": name, "tle": tle, "error": None},
    )
