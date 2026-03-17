"""UDL (Unified Data Library) proxy routes for SIPC.

Provides session-scoped UDL authentication and TLE fetch endpoints.
Credentials are held in memory for the duration of the operator session
and are never written to disk or the database.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from math import inf
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from sipc.web.auth import require_login
from sipc.web.deps import render
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


def _parse_tle_epoch(line1: str) -> datetime | None:
    """Parse TLE line 1 epoch field (0-indexed cols 18-31, format YYDDD.FFFFFFFF) to UTC datetime.

    Returns None if the field cannot be parsed.
    """
    try:
        epoch_str = line1[18:32].strip()
        year_2d = int(epoch_str[:2])
        day_frac = float(epoch_str[2:])
        year = 2000 + year_2d if year_2d < 57 else 1900 + year_2d
        day_int = int(day_frac)
        frac = day_frac - day_int
        return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day_int - 1 + frac)
    except (ValueError, IndexError):
        return None

_UDL_BASE = "https://unifieddatalibrary.com/udl"


async def fetch_tle_for_satno(
    satno: int, username: str, password: str, data_mode: str = "REAL",
) -> str | None:
    """Fetch current TLE for a SATNO from UDL.

    Returns ``'line1\\nline2'`` or ``None`` on failure.
    """
    try:
        async with httpx.AsyncClient() as client:
            params: dict = {
                "satNo": satno,
                "epoch": ">now-1 days",
            }
            if data_mode != "REAL":
                params["dataMode"] = data_mode
            resp = await client.get(
                f"{_UDL_BASE}/elset",
                params=params,
                auth=(username, password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("fetch_tle_for_satno(%s) failed: %s", satno, exc)
        return None

    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        records = []

    if not records:
        return None

    rec = records[0]
    line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
    line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
    if not line1 or not line2:
        return None
    return f"{line1}\n{line2}"


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
            return render(request,
                "partials/udl_status.html",
                {"udl_user": None, "error": "Invalid UDL credentials (401)."},
            )
        if not resp.is_success:
            body = resp.text[:300].strip() or "(empty)"
            error = f"UDL probe returned HTTP {resp.status_code}: {body}"
            logger.warning("UDL login probe %d for operator %s: %s", resp.status_code, current_user.username, body)
            return render(request,
                "partials/udl_status.html",
                {"udl_user": None, "error": error},
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        error = f"UDL probe returned HTTP {exc.response.status_code}: {body}"
        logger.warning("UDL login probe HTTP error for operator %s: %s", current_user.username, exc)
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": error},
        )
    except httpx.TimeoutException:
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": "UDL connection timed out (10 s). Check network."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL login probe failed: %s", exc)
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": f"UDL unreachable: {exc}"},
        )

    state.udl_username = username
    state.udl_password = password
    state.append_log(f"[UDL] Connected as {username}")
    logger.info("UDL credentials stored for operator: %s", current_user.username)

    # Kick off background catalog fetch (no-op if already loaded).
    asyncio.create_task(_fetch_onorbit_background(username, password))

    return render(request,
        "partials/udl_status.html",
        {"udl_user": username, "error": None},
    )


_VALID_DATA_MODES = {"REAL", "TEST", "EXERCISE", "SIMULATED"}


@router.post("/data-mode", response_model=None)
async def set_data_mode(
    request: Request,
    data_mode: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Set the UDL data classification mode for this session."""
    state = get_session_state(current_user.username)
    mode = data_mode.strip().upper()
    if mode not in _VALID_DATA_MODES:
        mode = "REAL"
    state.udl_data_mode = mode
    state.append_log(f"[UDL] Data mode set to {mode}")
    logger.info("UDL data mode set to %s for operator %s", mode, current_user.username)
    return render(request,
        "partials/data_mode_status.html",
        {"udl_data_mode": mode},
    )


@router.post("/logout", response_model=None)
async def udl_logout(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear UDL credentials from the operator session."""
    state = get_session_state(current_user.username)
    state.udl_username = None
    state.udl_password = None
    state.append_log("[UDL] Disconnected")
    logger.info("UDL credentials cleared for operator: %s", current_user.username)

    return render(request,
        "partials/udl_status.html",
        {"udl_user": None, "error": None},
    )


# ── TLE fetch proxy ────────────────────────────────────────────────────────


@router.get("/tle", response_model=None)
async def fetch_tle(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    mode: str = Query("latest", description="'latest' for current elset, 'epoch' for closest to scenario start"),
    name_override: Annotated[str, Query(description="Pre-populated name (e.g. from HRR watchlist commonName)")] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch a TLE for *satno* from UDL and return a pre-filled form partial.

    Two modes are supported:

    * ``latest`` — uses ``/elset/current`` to retrieve the most recent available elset.
    * ``epoch`` — fetches up to 10 elsets with epoch ≤ scenario start time, then selects
      the one whose epoch is closest to (but not after) the scenario start.  Requires
      scenario time to be set first.  A staleness warning is shown
      when the selected TLE is more than 7 days from the scenario start.
    """
    state = get_session_state(current_user.username)

    _empty = {"name": "", "tle": "", "tle_epoch_str": None,
               "tle_age_days": None, "mode": mode, "error": None}

    if not state.udl_username or not state.udl_password:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": "Not connected to UDL — use the UDL panel to log in first."},
        )

    if mode == "epoch" and state.scenario_start is None:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": "No scenario time set. Configure scenario time in the Scenario Configuration panel first."},
        )

    # ── Fetch from UDL ───────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient() as client:
            dm = state.udl_data_mode or "REAL"
            if mode == "epoch":
                epoch_filter = state.scenario_start.strftime("%Y-%m-%dT%H:%M:%S.000000Z")  # type: ignore[union-attr]
                params: dict = {"satNo": satno, "epoch": f"<{epoch_filter}", "maxResults": 10}
                if dm != "REAL":
                    params["dataMode"] = dm
                resp = await client.get(
                    f"{_UDL_BASE}/elset",
                    params=params,
                    auth=(state.udl_username, state.udl_password),
                    timeout=10.0,
                )
            else:
                latest_params: dict = {
                    "satNo": satno,
                    "epoch": ">now-1 days",
                }
                if dm != "REAL":
                    latest_params["dataMode"] = dm
                resp = await client.get(
                    f"{_UDL_BASE}/elset",
                    params=latest_params,
                    auth=(state.udl_username, state.udl_password),
                    timeout=15.0,
                )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}: {body}"
        logger.warning(error)
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": error},
        )
    except httpx.TimeoutException:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL TLE fetch failed for SATNO %s: %s", satno, exc)
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": f"UDL unreachable: {exc}"},
        )

    # Normalise: /elset/current may return a single dict or a list
    if isinstance(data, dict):
        records: list = [data]
    elif isinstance(data, list):
        records = data
    else:
        records = []

    if not records:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": f"No elset found for SATNO {satno}."},
        )

    # ── Select the best record ───────────────────────────────────────────────
    logger.info(
        "UDL returned %d elset record(s) for SATNO %s mode=%s dataMode=%s",
        len(records), satno, mode, dm,
    )

    # Log the keys from the first record so we can verify field names.
    if records:
        sample = records[0]
        logger.info("UDL elset record keys: %s", list(sample.keys()))
        # Also check for any epoch-like top-level field
        for key in ("epoch", "EPOCH", "epochDate", "tle1", "TLE1"):
            if key in sample:
                logger.info("  record[%r] = %s", key, str(sample[key])[:80])

    # Log every candidate's TLE line1 epoch for diagnostics.
    for i, candidate in enumerate(records):
        l1_raw = str(
            candidate.get("line1") or candidate.get("TLE_LINE1") or candidate.get("tle1") or ""
        ).strip()
        ep = _parse_tle_epoch(l1_raw)
        logger.info(
            "  record[%d] line1[18:32]=%r  parsed_epoch=%s  objectName=%s",
            i,
            l1_raw[18:32] if len(l1_raw) > 32 else l1_raw,
            ep.isoformat() if ep else "None",
            candidate.get("objectName") or candidate.get("OBJECT_NAME") or "?",
        )

    if mode == "epoch":
        # Pick the record whose TLE epoch is closest to (and ≤) scenario_start.
        best_rec = None
        best_delta = inf
        for candidate in records:
            l1 = str(candidate.get("line1") or candidate.get("TLE_LINE1") or "").strip()
            ep = _parse_tle_epoch(l1)
            if ep is None or ep > state.scenario_start:  # type: ignore[operator]
                continue
            delta = (state.scenario_start - ep).total_seconds()  # type: ignore[operator]
            if delta < best_delta:
                best_delta = delta
                best_rec = candidate
        if best_rec is None:
            return render(request,
                "partials/tle_fields.html",
                {**_empty, "error": (
                    f"No elset found for SATNO {satno} with epoch ≤ "
                    f"{state.scenario_start.strftime('%Y-%m-%d %H:%M UTC')}."  # type: ignore[union-attr]
                )},
            )
        rec = best_rec
    else:
        # For "latest" mode: pick the record with the newest TLE epoch.
        best_rec = records[0]
        best_epoch = _parse_tle_epoch(
            str(best_rec.get("line1") or best_rec.get("TLE_LINE1") or "").strip()
        )
        for candidate in records[1:]:
            l1 = str(candidate.get("line1") or candidate.get("TLE_LINE1") or "").strip()
            ep = _parse_tle_epoch(l1)
            if ep is not None and (best_epoch is None or ep > best_epoch):
                best_epoch = ep
                best_rec = candidate
        rec = best_rec
        logger.info(
            "Latest mode selected record with epoch=%s",
            best_epoch.isoformat() if best_epoch else "None",
        )

    # ── Extract fields ───────────────────────────────────────────────────────
    name = name_override.strip() or str(rec.get("objectName") or rec.get("OBJECT_NAME") or satno).strip()
    line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
    line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
    tle = f"{line1}\n{line2}"

    # TLE epoch metadata for the partial
    tle_epoch_dt = _parse_tle_epoch(line1)
    tle_epoch_str: str | None = None
    tle_age_days: float | None = None
    if tle_epoch_dt is not None:
        tle_epoch_str = tle_epoch_dt.strftime("%Y-%m-%d %H:%M UTC")
        if state.scenario_start is not None:
            tle_age_days = abs((state.scenario_start - tle_epoch_dt).total_seconds()) / 86400.0

    state.append_log(
        f"[UDL] Fetched TLE for SATNO {satno} ({name}) mode={mode}"
        + (f" epoch={tle_epoch_str}" if tle_epoch_str else "")
    )
    logger.info(
        "TLE fetched for SATNO %s (%s) mode=%s by operator %s",
        satno, name, mode, current_user.username,
    )

    return render(request,
        "partials/tle_fields.html",
        {

            "name": name,
            "tle": tle,
            "tle_epoch_str": tle_epoch_str,
            "tle_age_days": tle_age_days,
            "mode": mode,
            "error": None,
        },
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
    state = get_session_state(current_user.username)

    if not state.udl_username or not state.udl_password:
        return render(request,
            "partials/statevector_fields.html",
            {
    
                "sv": None,
                "error": "Not connected to UDL — use the UDL panel to log in first.",
            },
        )

    dm = state.udl_data_mode or "REAL"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/statevector",
                params={"satNo": satno, "epoch": ">2020-01-01T00:00:00.000000Z",
                        "dataMode": dm, "maxResults": 1},
                auth=(state.udl_username, state.udl_password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}"
        logger.warning(error)
        return render(request,
            "partials/statevector_fields.html",
            {"sv": None, "error": error},
        )
    except httpx.TimeoutException:
        return render(request,
            "partials/statevector_fields.html",
            {"sv": None, "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL state vector fetch failed for SATNO %s: %s", satno, exc)
        return render(request,
            "partials/statevector_fields.html",
            {"sv": None, "error": f"UDL unreachable: {exc}"},
        )

    if not data:
        return render(request,
            "partials/statevector_fields.html",
            {
    
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

    return render(request,
        "partials/statevector_fields.html",
        {"sv": sv, "error": None},
    )


# ── HRR Watchlist ──────────────────────────────────────────────────────────

_RED_COUNTRIES = {"CHN", "RUS", "IRN", "PRK"}


def _parse_created_at(rec: dict) -> datetime:
    """Parse the UDL notification createdAt field to a UTC datetime.

    Returns datetime.min (UTC) if the field is absent or unparseable so the
    record sorts to the bottom when picking the newest notification.
    """
    raw = str(rec.get("createdAt") or "").strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)




async def fetch_hrr_objects(
    username: str,
    password: str,
    data_mode: str = "REAL",
) -> tuple[list[dict], list[dict], int, str | None]:
    """Fetch HRR satellites from UDL and return (blue, red, lookback_days, error).

    Reusable by both the HRR panel route and the threat sweep.  On success the
    returned lists contain normalised dicts with keys: satno, name, country,
    rank, orbit_regime, created_at.  On failure, both lists are empty and *error*
    contains a human-readable message.
    """
    _HRR_MAX_LOOKBACK_DAYS = 3
    notifications: list[dict] = []
    days_used = 0

    try:
        async with httpx.AsyncClient() as client:
            for day in range(1, _HRR_MAX_LOOKBACK_DAYS + 1):
                resp = await client.get(
                    f"{_UDL_BASE}/notification",
                    params={
                        "createdAt": f">now-{day} days",
                        "dataMode": data_mode,
                        "msgType": "JCO-HRR-SATELLITES",
                        "source": "JCO",
                        "maxResults": 10000,
                    },
                    auth=(username, password),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list) and data:
                    notifications = data
                    days_used = day
                    break
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:200].strip() or "(empty)"
        return [], [], 0, f"HRR fetch returned HTTP {exc.response.status_code}: {body}"
    except httpx.TimeoutException:
        return [], [], 0, "UDL request timed out."
    except httpx.RequestError as exc:
        return [], [], 0, f"UDL unreachable: {exc}"

    if not notifications:
        return [], [], 0, f"No HRR notifications found in the last {_HRR_MAX_LOOKBACK_DAYS} days."

    newest = max(notifications, key=_parse_created_at)
    msg_body: list[dict] = newest.get("msgBody") or []
    notification_created_at = str(newest.get("createdAt") or "").strip()

    hrr_blue: list[dict] = []
    hrr_red: list[dict] = []

    for sat in msg_body:
        satno = str(sat.get("satNo") or sat.get("satno") or "").strip()
        name = str(sat.get("commonName") or sat.get("objectName") or satno or "—").strip()
        country = str(sat.get("country") or "").strip().upper()
        rank = sat.get("rank")
        orbit_regime = str(sat.get("orbitRegime") or "").strip()
        entry = {
            "satno": satno,
            "name": name,
            "country": country,
            "rank": rank,
            "orbit_regime": orbit_regime,
            "created_at": notification_created_at,
        }
        if country in _RED_COUNTRIES:
            hrr_red.append(entry)
        else:
            hrr_blue.append(entry)

    return hrr_blue, hrr_red, days_used, None


@router.get("/hrr", response_model=None)
async def fetch_hrr(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch the UDL High Rate Revisit (HRR) satellite list and return a panel partial."""
    state = get_session_state(current_user.username)

    _empty_err = {"hrr_blue": [], "hrr_red": [], "hrr_lookback": 0}

    if not state.udl_username or not state.udl_password:
        return render(request,
            "partials/hrr_panel.html",
            {**_empty_err, "error": "Not connected to UDL — use the UDL panel to log in first."},
        )

    dm = state.udl_data_mode or "REAL"
    hrr_blue, hrr_red, days_used, error = await fetch_hrr_objects(
        state.udl_username, state.udl_password, dm,
    )

    if error:
        logger.warning("HRR fetch error for operator %s: %s", current_user.username, error)
        return render(request,
            "partials/hrr_panel.html", {**_empty_err, "error": error},
        )

    # Cache all HRR objects in session state for threat sweep use.
    state.hrr_objects = hrr_blue + hrr_red

    state.append_log(
        f"[HRR] lookback={days_used}d — "
        f"{len(hrr_blue)} Blue, {len(hrr_red)} Red ({len(hrr_blue) + len(hrr_red)} sats)"
    )
    logger.info(
        "HRR fetched for operator %s: lookback=%dd %d blue + %d red",
        current_user.username, days_used, len(hrr_blue), len(hrr_red),
    )

    return render(request,
        "partials/hrr_panel.html",
        {"hrr_blue": hrr_blue, "hrr_red": hrr_red,
         "hrr_lookback": days_used, "error": None},
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

    return render(request,
        "partials/catalog_results.html",
        {"results": results, "q": q,
         "status": status, "total": len(catalog)},
    )
