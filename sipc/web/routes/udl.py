"""UDL (Unified Data Library) proxy routes for SIPC.

Provides session-scoped UDL authentication and TLE fetch endpoints.
Credentials are held in memory for the duration of the operator session
and are never written to disk or the database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from sipc.web.auth import require_login
from sipc.web.models import User
from sipc.web.planning_state import (
    get_onorbit_catalog,
    get_catalog_status,
    get_session_state,
    set_catalog_status,
    set_onorbit_catalog,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/udl")

_UDL_BASE = "https://unifieddatalibrary.com/udl"


async def _fetch_onorbit_background(username: str, password: str) -> None:
    """Fetch the UDL on-orbit catalog in the background and cache it app-wide.

    Called as an asyncio background task immediately after successful UDL login.
    Only runs when the catalog has not already been loaded (status != 'ready').
    """
    if get_catalog_status() == "ready":
        return  # Already loaded — no need to fetch again
    set_catalog_status("loading")
    logger.info("Background: fetching on-orbit catalog from UDL")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/onorbit",
                auth=(username, password),
                timeout=60.0,
            )
        resp.raise_for_status()
        data = resp.json()
        set_onorbit_catalog(data if isinstance(data, list) else [])
        logger.info("Background: on-orbit catalog ready (%d objects)", len(get_onorbit_catalog()))
    except Exception as exc:
        set_catalog_status("error")
        logger.warning("Background: on-orbit catalog fetch failed: %s", exc)


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
                params={"satNo": 25544, "epoch": ">2020-01-01T00:00:00.000000Z", "maxResults": 1},
                auth=(username, password),
                timeout=10.0,
            )
        if resp.status_code == 401:
            logger.warning("UDL login rejected for operator %s", current_user.username)
            return tmpl.TemplateResponse(  # type: ignore[attr-defined]
                "partials/udl_status.html",
                {"request": request, "udl_user": None, "error": "Invalid UDL credentials (401)."},
            )
        if not resp.is_success:
            body = resp.text[:300].strip() or "(empty)"
            error = f"UDL probe returned HTTP {resp.status_code}: {body}"
            logger.warning("UDL login probe %d for operator %s: %s", resp.status_code, current_user.username, body)
            return tmpl.TemplateResponse(  # type: ignore[attr-defined]
                "partials/udl_status.html",
                {"request": request, "udl_user": None, "error": error},
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        error = f"UDL probe returned HTTP {exc.response.status_code}: {body}"
        logger.warning("UDL login probe HTTP error for operator %s: %s", current_user.username, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/udl_status.html",
            {"request": request, "udl_user": None, "error": error},
        )
    except httpx.TimeoutException:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/udl_status.html",
            {"request": request, "udl_user": None, "error": "UDL connection timed out (10 s). Check network."},
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

    # Kick off background catalog fetch (no-op if already loaded).
    asyncio.create_task(_fetch_onorbit_background(username, password))

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
                params={"satNo": satno, "epoch": ">2020-01-01T00:00:00.000000Z", "maxResults": 1},
                auth=(state.udl_username, state.udl_password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}: {body}"
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

    # UDL field names vary — try the known variants for each value
    name = str(
        rec.get("objectName") or rec.get("OBJECT_NAME") or satno
    ).strip()
    line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
    line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
    tle = f"{line1}\n{line2}"

    state.append_log(f"[UDL] Fetched TLE for SATNO {satno} ({name})")
    logger.info("TLE fetched for SATNO %s (%s) by operator %s", satno, name, current_user.username)

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/tle_fields.html",
        {"request": request, "name": name, "tle": tle, "error": None},
    )


# ── State vector fetch proxy ───────────────────────────────────────────────


@router.get("/statevector", response_model=None)
async def fetch_statevector(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch the latest Cartesian state vector for *satno* from UDL.

    Returns position (km) and velocity (km s⁻¹) in the J2000 reference frame
    at the most recent available epoch. Useful for initialising high-fidelity
    intercept geometry without propagating a TLE.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if not state.udl_username or not state.udl_password:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/statevector_fields.html",
            {
                "request": request,
                "sv": None,
                "error": "Not connected to UDL — use the UDL panel to log in first.",
            },
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/statevector",
                params={"satNo": satno, "epoch": ">2020-01-01T00:00:00.000000Z", "maxResults": 1},
                auth=(state.udl_username, state.udl_password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}"
        logger.warning(error)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/statevector_fields.html",
            {"request": request, "sv": None, "error": error},
        )
    except httpx.TimeoutException:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/statevector_fields.html",
            {"request": request, "sv": None, "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL state vector fetch failed for SATNO %s: %s", satno, exc)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/statevector_fields.html",
            {"request": request, "sv": None, "error": f"UDL unreachable: {exc}"},
        )

    if not data:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/statevector_fields.html",
            {
                "request": request,
                "sv": None,
                "error": f"No state vector found for SATNO {satno}.",
            },
        )

    rec = data[0]
    sv = {
        "name": str(rec.get("objectName") or rec.get("OBJECT_NAME", satno)).strip(),
        "epoch": rec.get("epoch", "—"),
        "x": rec.get("x"),
        "y": rec.get("y"),
        "z": rec.get("z"),
        "x_dot": rec.get("xDot"),
        "y_dot": rec.get("yDot"),
        "z_dot": rec.get("zDot"),
        "ref_frame": rec.get("refFrame", "J2000"),
    }

    state.append_log(
        f"[UDL] Fetched state vector for SATNO {satno} ({sv['name']}) epoch {sv['epoch']}"
    )
    logger.info(
        "State vector fetched for SATNO %s (%s) by operator %s",
        satno,
        sv["name"],
        current_user.username,
    )

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/statevector_fields.html",
        {"request": request, "sv": sv, "error": None},
    )


# ── HRR Watchlist ──────────────────────────────────────────────────────────


@router.get("/hrr", response_model=None)
async def fetch_hrr(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch the UDL High Rate Revisit (HRR) satellite list and return a panel partial.

    The HRR notification endpoint is queried for the last 7 days.  Records are
    split into Blue, Red, and unclassified buckets by inspecting common UDL
    team/side field names.
    """
    tmpl = _templates()
    state = get_session_state(current_user.username)

    if not state.udl_username or not state.udl_password:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/hrr_panel.html",
            {"request": request, "hrr_blue": [], "hrr_red": [], "hrr_other": [],
             "error": "Not connected to UDL — use the UDL panel to log in first."},
        )

    cutoff = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/notification",
                params={"createdAt": f">{cutoff}", "msgType": "JCO-HRR-SATELLITES"},
                auth=(state.udl_username, state.udl_password),
                timeout=30.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:200].strip() or "(empty)"
        error = f"HRR fetch returned HTTP {exc.response.status_code}: {body}"
        logger.warning("HRR fetch error for operator %s: %s", current_user.username, error)
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/hrr_panel.html",
            {"request": request, "hrr_blue": [], "hrr_red": [], "hrr_other": [], "error": error},
        )
    except httpx.TimeoutException:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/hrr_panel.html",
            {"request": request, "hrr_blue": [], "hrr_red": [], "hrr_other": [],
             "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        return tmpl.TemplateResponse(  # type: ignore[attr-defined]
            "partials/hrr_panel.html",
            {"request": request, "hrr_blue": [], "hrr_red": [], "hrr_other": [],
             "error": f"UDL unreachable: {exc}"},
        )

    hrr_blue: list[dict] = []
    hrr_red: list[dict] = []
    hrr_other: list[dict] = []

    for rec in data if isinstance(data, list) else []:
        sat_no = rec.get("satNo") or rec.get("satno") or rec.get("SATNO") or ""
        name = str(
            rec.get("objectName") or rec.get("name") or rec.get("OBJECT_NAME") or sat_no or "—"
        ).strip()
        # Try common UDL field names for team/side classification
        team = str(
            rec.get("team") or rec.get("side") or rec.get("tag") or
            rec.get("nation") or rec.get("classification") or ""
        ).upper()
        entry = {"satno": sat_no, "name": name, "team": team}
        if "BLUE" in team or team in ("B", "BLU"):
            hrr_blue.append(entry)
        elif "RED" in team or team == "R":
            hrr_red.append(entry)
        else:
            hrr_other.append(entry)

    state.append_log(
        f"[HRR] Loaded {len(data)} records — {len(hrr_blue)} Blue, "
        f"{len(hrr_red)} Red, {len(hrr_other)} unclassified"
    )
    logger.info("HRR fetched for operator %s: %d records", current_user.username, len(data))

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/hrr_panel.html",
        {"request": request, "hrr_blue": hrr_blue, "hrr_red": hrr_red,
         "hrr_other": hrr_other, "error": None},
    )


# ── On-orbit catalog search ────────────────────────────────────────────────


@router.get("/catalog/search", response_model=None)
async def search_catalog(
    request: Request,
    q: str = Query("", description="Search query — name substring or SATNO prefix"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Search the cached on-orbit catalog and return a results partial.

    Returns up to 50 matching objects.  When *q* is empty the partial shows
    the current catalog status (loading, ready, error) so the operator can
    see progress without searching.
    """
    tmpl = _templates()
    catalog = get_onorbit_catalog()
    status = get_catalog_status()

    results: list[dict] = []
    if q.strip():
        q_lower = q.strip().lower()
        for obj in catalog:
            name = str(obj.get("name") or obj.get("objectName") or "").lower()
            satno = str(obj.get("satNo") or obj.get("satno") or "")
            if q_lower in name or q_lower in satno:
                results.append({
                    "satno": obj.get("satNo") or obj.get("satno") or "—",
                    "name": obj.get("name") or obj.get("objectName") or "—",
                    "obj_type": obj.get("objectType") or obj.get("type") or "—",
                    "country": obj.get("country") or "—",
                })
                if len(results) >= 50:
                    break

    return tmpl.TemplateResponse(  # type: ignore[attr-defined]
        "partials/catalog_results.html",
        {"request": request, "results": results, "q": q,
         "status": status, "total": len(catalog)},
    )
