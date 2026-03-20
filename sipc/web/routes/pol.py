"""Historical Pattern of Life (PoL) routes for SIPC.

Fetches historical TLEs from UDL, runs the PoL analysis engine, and returns
rendered partials for the Historical PoL hero tab.
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from sipc.astro.pattern_of_life import analyse_pattern_of_life, parse_tle_history
from sipc.web.auth import require_login
from sipc.web.deps import render
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pol")

_UDL_BASE = "https://unifieddatalibrary.com/udl"

# Maximum TLEs to fetch from UDL historical endpoint.
_UDL_MAX_RESULTS = 5000


# ── UDL helper ────────────────────────────────────────────────────────────────

async def _fetch_udl_history(satno: int, username: str, password: str, data_mode: str) -> str:
    """Fetch historical TLEs from UDL elset endpoint.

    UDL's /elset endpoint supports filtering by satNo and epoch range.
    We request everything from 2015 onward with a high maxResults cap.
    Records may arrive in any order — the parser will sort chronologically.
    """
    params: dict = {
        "satNo": satno,
        "epoch": ">2015-01-01T00:00:00.000000Z",
        "maxResults": _UDL_MAX_RESULTS,
    }
    if data_mode and data_mode != "REAL":
        params["dataMode"] = data_mode

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(
            f"{_UDL_BASE}/elset",
            params=params,
            auth=(username, password),
        )
        resp.raise_for_status()

    raw = resp.text.strip()
    if not raw:
        return ""

    try:
        data = resp.json()
    except Exception:
        # UDL returned plain TLE text rather than JSON
        return raw

    if isinstance(data, dict):
        records = data.get("data", data.get("items", [data]))
    elif isinstance(data, list):
        records = data
    else:
        return ""

    lines: list[str] = []
    for rec in records:
        l1 = str(rec.get("line1") or rec.get("TLE_LINE1") or rec.get("tle1") or "").strip()
        l2 = str(rec.get("line2") or rec.get("TLE_LINE2") or rec.get("tle2") or "").strip()
        if l1.startswith("1 ") and l2.startswith("2 "):
            lines.append(l1)
            lines.append(l2)

    logger.info("PoL UDL: parsed %d TLE pairs from %d records", len(lines) // 2, len(records))
    return "\n".join(lines)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/panel", response_class=HTMLResponse)
async def pol_panel(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the PoL panel — credential form + results placeholder."""
    state = get_session_state(current_user.username)
    return render(request, "partials/pol_panel.html", {
        "has_udl": bool(state.udl_username),
        "pol": getattr(state, "last_pol_analysis", None),
        "error": None,
    })


@router.post("/analyse", response_class=HTMLResponse)
async def pol_analyse(
    request: Request,
    satno: Annotated[int, Form()],
    pol_source: Annotated[str, Form()] = "udl",
    udl_user: Annotated[str, Form()] = "",
    udl_pass: Annotated[str, Form()] = "",
    dv_threshold_ms: Annotated[float, Form()] = 2.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Fetch historical TLEs from UDL and run PoL analysis."""
    state = get_session_state(current_user.username)
    tle_text = ""
    name = str(satno)

    def _err(msg: str) -> HTMLResponse:
        return render(request, "partials/pol_panel.html", {
            "has_udl": bool(state.udl_username),
            "pol": None,
            "error": msg,
        })

    # ── UDL direct credentials ────────────────────────────────────────────────
    if pol_source == "udl_direct":
        if not udl_user.strip() or not udl_pass.strip():
            return _err("Enter UDL username and password.")
        try:
            tle_text = await _fetch_udl_history(
                satno, udl_user.strip(), udl_pass.strip(), "REAL",
            )
            logger.info("PoL: %d chars from UDL (direct) for %d", len(tle_text), satno)
        except Exception as exc:
            logger.warning("PoL: UDL direct failed: %s", exc)
            return _err(f"UDL fetch failed: {exc}")

    # ── UDL session credentials ───────────────────────────────────────────────
    else:  # pol_source == "udl"
        if not state.udl_username or not state.udl_password:
            return _err("No active UDL session. Connect UDL first, or choose 'UDL (credentials)'.")
        try:
            tle_text = await _fetch_udl_history(
                satno, state.udl_username, state.udl_password,
                state.udl_data_mode or "REAL",
            )
            logger.info("PoL: %d chars from UDL (session) for %d", len(tle_text), satno)
        except Exception as exc:
            logger.warning("PoL: UDL session failed: %s", exc)
            return _err(f"UDL fetch failed: {exc}")

    if not tle_text or not tle_text.strip():
        return _err(
            f"No TLE data returned from UDL for SATNO {satno}. "
            "Check the SATNO and credentials, and verify the object exists in the catalogue."
        )

    # ── Parse + analyse ───────────────────────────────────────────────────────
    try:
        threshold_km_s = dv_threshold_ms / 1000.0
        records = parse_tle_history(tle_text, satno=satno)
        if not records:
            return render(request, "partials/pol_panel.html", {
                "has_udl": bool(state.udl_username),
                "pol": None,
                "error": f"No valid TLEs parsed from UDL response for SATNO {satno}.",
            })

        pol = analyse_pattern_of_life(
            records,
            satno=satno,
            name=name,
            dv_threshold=threshold_km_s,
        )
        state.last_pol_analysis = pol  # type: ignore[attr-defined]
        state.append_log(
            f"[POL] Analysed {satno}: {pol.tle_count} TLEs, "
            f"{len(pol.manoeuvres)} manoeuvres, status={pol.pol_status} [UDL]"
        )
    except Exception as exc:
        logger.exception("PoL analysis failed for %d", satno)
        return render(request, "partials/pol_panel.html", {
            "has_udl": bool(state.udl_username),
            "pol": None,
            "error": f"Analysis error: {exc}",
        })

    return render(request, "partials/pol_results.html", {
        "pol": pol,
        "source": "UDL",
    })


@router.get("/chart-data/{satno}", response_class=JSONResponse)
async def pol_chart_data(
    satno: int,
    request: Request,
    current_user: User = Depends(require_login),
) -> JSONResponse:
    """Return Chart.js-ready JSON for the most recent PoL analysis."""
    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)
    if pol is None or pol.satno != satno:
        return JSONResponse({"error": "No PoL analysis available"}, status_code=404)

    TYPE_COLORS = {
        "station_keeping": "#3b8beb",
        "plane_change": "#f59e0b",
        "repositioning": "#ef4444",
        "unknown": "#6b7280",
    }

    drift_phase_data = [
        {
            "start": ph.start_epoch.strftime("%Y-%m-%d"),
            "end": ph.end_epoch.strftime("%Y-%m-%d"),
            "direction": ph.direction,
            "rate": ph.rate_deg_day,
            "start_lon": ph.start_lon,
            "end_lon": ph.end_lon,
        }
        for ph in pol.drift_phases
    ]

    man_lons = [
        round(m.tle_after.geo_longitude_deg, 2)
        if m.tle_after.geo_longitude_deg is not None else None
        for m in pol.manoeuvres
    ]

    return JSONResponse({
        "elements": {
            "epochs": pol.chart_epochs,
            "altitude": pol.chart_alts,
            "inclination": pol.chart_incs,
            "eccentricity": pol.chart_eccs,
            "raan": pol.chart_raans,
            "period": pol.chart_periods,
        },
        "geo": {
            "epochs": pol.chart_epochs,
            "longitude": pol.chart_longitudes,
            "drift_rate": pol.chart_drift_rates,
            "drift_phases": drift_phase_data,
        },
        "manoeuvres": {
            "epochs": pol.manoeuvre_epochs,
            "dvs_ms": pol.manoeuvre_dvs,
            "types": pol.manoeuvre_types,
            "colors": [TYPE_COLORS.get(t, "#6b7280") for t in pol.manoeuvre_types],
            "alts": pol.manoeuvre_alts,
            "drift_deltas": pol.manoeuvre_drift_deltas,
            "lons": man_lons,
        },
        "stats": {
            "dv_mean": pol.dv_stats.mean * 1000 if pol.dv_stats else None,
            "dv_2sigma_high": pol.pol_high_dv * 1000 if pol.pol_high_dv else None,
            "interval_mean": pol.interval_stats.mean if pol.interval_stats else None,
            "interval_low": pol.pol_low_interval,
            "interval_high": pol.pol_high_interval,
        },
    })
