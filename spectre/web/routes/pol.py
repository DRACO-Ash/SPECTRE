"""Historical Pattern of Life (PoL) routes for SPECTRE.

Fetches historical TLEs from UDL, runs the PoL analysis engine, and returns
rendered partials for the Historical PoL hero tab.
"""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from spectre.astro.pattern_of_life import analyse_pattern_of_life, parse_tle_history
from spectre.astro.tle_filter import filter_tle_history
from spectre.data.intel import get_intel
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pol")

_UDL_BASE = "https://unifieddatalibrary.com/udl"

# Maximum TLEs to fetch from UDL historical endpoint.
_UDL_MAX_RESULTS = 5000


# ── UDL helper ────────────────────────────────────────────────────────────────

def _parse_udl_elset_response(
    resp: httpx.Response,
) -> tuple[str, dict[str, tuple[str, str]], dict[str, float | None], str]:
    """Extract TLE text and provenance metadata from a UDL /elset response.

    Returns ``(tle_text, metadata, rms_metadata, sat_name)`` where *metadata*
    maps TLE line-1 strings to ``(data_mode, source)`` pairs, *rms_metadata*
    maps line-1 strings to RMS residuals, and *sat_name* is the first non-empty
    satellite name found in the JSON records (empty string if not available).
    """
    raw = resp.text.strip()
    if not raw:
        return "", {}, {}, ""

    try:
        data = resp.json()
    except Exception:
        # Plain TLE text — no provenance metadata available.
        return raw, {}, {}, ""

    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        return "", {}, {}, ""

    lines: list[str] = []
    metadata: dict[str, tuple[str, str]] = {}
    rms_metadata: dict[str, float | None] = {}
    sat_name: str = ""
    for rec in records:
        l1 = str(rec.get("line1") or rec.get("TLE_LINE1") or rec.get("tle1") or "").strip()
        l2 = str(rec.get("line2") or rec.get("TLE_LINE2") or rec.get("tle2") or "").strip()
        if l1.startswith("1 ") and l2.startswith("2 "):
            lines.append(l1)
            lines.append(l2)
            dm  = str(rec.get("dataMode") or rec.get("data_mode") or "").strip()
            src = str(rec.get("source") or "").strip()
            metadata[l1] = (dm, src)
            rms_raw = rec.get("rmsResidual") or rec.get("rms_residual") or rec.get("rms")
            rms_metadata[l1] = float(rms_raw) if rms_raw is not None else None
            # Capture satellite name from first valid record that has one
            if not sat_name:
                sat_name = str(
                    rec.get("satName") or rec.get("objectName") or
                    rec.get("OBJECT_NAME") or rec.get("name") or ""
                ).strip()

    logger.info("PoL UDL: parsed %d TLE pairs from %d records", len(lines) // 2, len(records))
    return "\n".join(lines), metadata, rms_metadata, sat_name


async def _fetch_udl_history(
    satno: int, username: str, password: str, data_mode: str, source: str = "",
) -> tuple[str, dict[str, tuple[str, str]], dict[str, float | None], str]:
    """Fetch historical TLEs from UDL elset endpoint (2015 → now, max 5 000).

    Returns ``(tle_text, metadata, rms_metadata)``.
    Records may arrive in any order — the parser will sort chronologically.
    """
    params: dict = {
        "satNo": satno,
        "epoch": ">2015-01-01T00:00:00.000000Z",
        "maxResults": _UDL_MAX_RESULTS,
    }
    if data_mode and data_mode != "REAL":
        params["dataMode"] = data_mode
    if source:
        params["source"] = source

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(
            f"{_UDL_BASE}/elset",
            params=params,
            auth=(username, password),
        )
        resp.raise_for_status()

    return _parse_udl_elset_response(resp)


async def _fetch_udl_latest(
    satno: int, username: str, password: str, data_mode: str, source: str = "",
) -> tuple[str, dict[str, tuple[str, str]], dict[str, float | None], str]:
    """Fetch the current/latest TLE from UDL ``/elset/current``.

    A satellite with many historical TLEs can exhaust the 5 000-record cap
    on ``/elset`` before reaching the present.  This second call guarantees
    the most recent elset is always included regardless of archive depth.

    Returns ``(tle_text, metadata, rms_metadata, sat_name)``.
    """
    params: dict = {"satNo": satno}
    if data_mode and data_mode != "REAL":
        params["dataMode"] = data_mode
    if source:
        params["source"] = source

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{_UDL_BASE}/elset/current",
            params=params,
            auth=(username, password),
        )
        resp.raise_for_status()

    return _parse_udl_elset_response(resp)


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
    cadence_filter: Annotated[str, Form()] = "",
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
            tle_text, meta, rms_meta, _hist_name = await _fetch_udl_history(
                satno, udl_user.strip(), udl_pass.strip(), "REAL",
                source=state.udl_tle_source,
            )
            latest_text, latest_meta, latest_rms, latest_name = await _fetch_udl_latest(
                satno, udl_user.strip(), udl_pass.strip(), "REAL",
                source=state.udl_tle_source,
            )
            name = latest_name or _hist_name or str(satno)
            logger.info("PoL: %d chars from UDL (direct) for %d", len(tle_text), satno)
        except Exception as exc:
            logger.warning("PoL: UDL direct failed: %s", exc)
            return _err(f"UDL fetch failed: {exc}")

    # ── UDL session credentials ───────────────────────────────────────────────
    else:  # pol_source == "udl"
        if not state.udl_username or not state.udl_password:
            return _err("No active UDL session. Connect UDL first, or choose 'UDL (credentials)'.")
        try:
            tle_text, meta, rms_meta, _hist_name = await _fetch_udl_history(
                satno, state.udl_username, state.udl_password,
                state.udl_data_mode or "REAL",
                source=state.udl_tle_source,
            )
            latest_text, latest_meta, latest_rms, latest_name = await _fetch_udl_latest(
                satno, state.udl_username, state.udl_password,
                state.udl_data_mode or "REAL",
                source=state.udl_tle_source,
            )
            name = latest_name or _hist_name or str(satno)
            logger.info("PoL: %d chars from UDL (session) for %d", len(tle_text), satno)
        except Exception as exc:
            logger.warning("PoL: UDL session failed: %s", exc)
            return _err(f"UDL fetch failed: {exc}")

    # Merge historical + latest: latest entries override historical (newer provenance).
    merged_meta = {**meta, **latest_meta}
    merged_rms  = {**rms_meta, **latest_rms}
    merged_text = tle_text + ("\n" if tle_text else "") + latest_text

    if not merged_text.strip():
        return _err(
            f"No TLE data returned from UDL for SATNO {satno}. "
            "Check the SATNO and credentials, and verify the object exists in the catalogue."
        )

    # ── Parse + analyse ───────────────────────────────────────────────────────
    try:
        threshold_km_s = dv_threshold_ms / 1000.0
        apply_filter = bool(cadence_filter)
        records = parse_tle_history(
            merged_text, satno=satno,
            metadata=merged_meta, rms_metadata=merged_rms,
        )
        if not records:
            return render(request, "partials/pol_panel.html", {
                "has_udl": bool(state.udl_username),
                "pol": None,
                "error": f"No valid TLEs parsed from UDL response for SATNO {satno}.",
            })

        quality_flags = []
        if apply_filter:
            raw_count = len(records)
            records, quality_flags = filter_tle_history(records)
            logger.info(
                "PoL cadence filter: %d → %d records, %d flags for %d",
                raw_count, len(records), len(quality_flags), satno,
            )

        pol = analyse_pattern_of_life(
            records,
            satno=satno,
            name=name,
            dv_threshold=threshold_km_s,
            quality_flags=quality_flags,
        )
        state.last_pol_analysis = pol  # type: ignore[attr-defined]
        filter_note = f" [cadence-filtered, {len(quality_flags)} flags]" if apply_filter else ""
        state.append_log(
            f"[POL] Analysed {satno}: {pol.tle_count} TLEs, "
            f"{len(pol.manoeuvres)} manoeuvres, status={pol.pol_status} [UDL]{filter_note}"
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
        "pair": get_intel(satno),
    })


@router.post("/monte-carlo", response_class=HTMLResponse)
async def pol_monte_carlo(
    request: Request,
    satno: Annotated[int, Form()],
    manoeuvre_epoch: Annotated[str, Form()],
    dv_km_s: Annotated[float, Form()],
    manoeuvre_type: Annotated[str, Form()] = "orbit_raise",
    n_samples: Annotated[int, Form()] = 500,
    horizon_h: Annotated[float, Form()] = 48.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Run Monte Carlo simulation for a specific detected manoeuvre."""
    import asyncio

    from spectre.astro.monte_carlo import (
        MANOEUVRE_ARCHETYPES,
        ManoeuvreHypothesis,
        hypothesis_from_tle_record,
        run_monte_carlo,
    )

    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)

    if pol is None or pol.satno != satno:
        return HTMLResponse(
            '<p class="error-msg">No PoL analysis for this SATNO. Run Pattern of Life first.</p>'
        )

    # Find the manoeuvre matching the requested epoch
    target_epoch_str = manoeuvre_epoch[:19]  # trim to seconds
    matching = [
        m for m in pol.manoeuvres
        if m.epoch.strftime("%Y-%m-%dT%H:%M:%S") == target_epoch_str
    ]
    if not matching:
        return HTMLResponse(
            f'<p class="error-msg">Manoeuvre at {manoeuvre_epoch} not found in PoL results.</p>'
        )

    manoeuvre = matching[0]

    try:
        hypothesis = hypothesis_from_tle_record(
            manoeuvre.tle_before,
            manoeuvre,
            n_samples=min(max(n_samples, 50), 2000),
            archetype_override=manoeuvre_type,
        )
        hypothesis.prediction_horizon_hours = horizon_h  # type: ignore[attr-defined]

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_monte_carlo(hypothesis, satno=satno, prediction_horizon_hours=horizon_h),
        )
    except Exception as exc:
        logger.exception("Monte Carlo failed for %d", satno)
        return HTMLResponse(f'<p class="error-msg">Monte Carlo error: {exc}</p>')

    return render(request, "partials/pol_mc_results.html", {
        "mc": result,
        "manoeuvre": manoeuvre,
        "archetypes": list(MANOEUVRE_ARCHETYPES.keys()),
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



@router.get("/notso-panel", response_class=HTMLResponse)
async def pol_notso_panel(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the NOTSO correlation input panel."""
    from spectre.data.notso_cache import get_notso_cache
    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)
    cache = get_notso_cache()
    cache_count_for_sat = len(cache.get_for_satno(pol.satno)) if pol else 0
    return render(request, "partials/notso_panel.html", {
        "has_udl": bool(state.udl_username),
        "pol": pol,
        "cache_total": cache.total_records(),
        "cache_last_sync": cache.last_sync_utc(),
        "cache_count_for_sat": cache_count_for_sat,
    })


@router.post("/notso-correlate", response_class=HTMLResponse)
async def pol_notso_correlate(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Correlate NOTSOs with the last PoL analysis.

    Source priority:
      1. Operator-pasted text (``notso_text`` form field, if non-empty).
      2. Local NOTSO cache for the current satno (automatic if text is empty).
    """
    from spectre.astro.notso import (
        NOTSORecord,
        NOTSOType,
        correlate_notsos_with_manoeuvres,
        extract_behaviour_profile,
        parse_notso_text,
    )
    from spectre.data.notso_cache import get_notso_cache

    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)

    if pol is None:
        return HTMLResponse(
            '<p class="error-msg">Run Pattern of Life analysis first before correlating NOTSOs.</p>'
        )

    form = await request.form()
    notso_text = str(form.get("notso_text") or "").strip()

    notsos: list[NOTSORecord] = []
    source_label = ""

    if notso_text:
        # Path 1: operator-pasted text
        notsos = parse_notso_text(notso_text)
        source_label = "pasted text"
        if not notsos:
            return HTMLResponse(
                '<p class="error-msg">No NOTSO records could be parsed. '
                'Check the message format (SATNO, effective window, and type fields are required).</p>'
            )
    else:
        # Path 2: load from local cache for this satno
        cache = get_notso_cache()
        raw_records = cache.get_for_satno(pol.satno)
        if not raw_records:
            return HTMLResponse(
                '<p class="error-msg">No NOTSOs in local cache for SATNO '
                f'{pol.satno}. Run a cache sync first, or paste NOTSO messages manually.</p>'
            )
        # Convert raw cache dicts → NOTSORecord using the existing text parser
        # Each record has a msgText field (full notification text) or we reconstruct it.
        for rec in raw_records:
            msg_text = str(rec.get("msgText") or rec.get("message") or "")
            if not msg_text:
                # Reconstruct minimal parseable text from structured fields
                created = rec.get("createdAt") or ""
                msg_text = (
                    f"MSGID: {rec.get('msgId', '')}\n"
                    f"SATNO: {rec.get('satNo', '')}\n"
                    f"ISSUE DATE: {created}\n"
                    f"EFFECTIVE START: {created}\n"
                    f"TYPE: MANOEUVRE\n"
                    f"DESCRIPTION: {rec.get('msgType', 'TACREP_NOTSO')}"
                )
            parsed = parse_notso_text(msg_text)
            # If parser couldn't extract satno, force it from the record
            for p in parsed:
                if p.norad_id == 0 or p.norad_id is None:
                    p.norad_id = int(rec.get("satNo") or 0)
            notsos.extend(parsed)
        source_label = f"local cache ({len(raw_records)} records)"
        if not notsos:
            return HTMLResponse(
                f'<p class="error-msg">Cache has {len(raw_records)} record(s) for SATNO '
                f'{pol.satno} but none could be parsed. Try pasting the text manually.</p>'
            )

    try:
        correlations = correlate_notsos_with_manoeuvres(
            notsos, pol.manoeuvres, pol.satno
        )

        start = pol.records[0].epoch if pol.records else (pol.manoeuvres[0].epoch if pol.manoeuvres else None)
        end   = pol.records[-1].epoch if pol.records else (pol.manoeuvres[-1].epoch if pol.manoeuvres else None)
        profile = extract_behaviour_profile(pol.satno, correlations, start, end) if (start and end) else None

        state.append_log(
            f"[NOTSO] Correlated {len(notsos)} NOTSOs ({source_label}) for {pol.satno}: "
            f"{sum(1 for c in correlations if c.correlation_type == 'matched')} matched, "
            f"{sum(1 for c in correlations if c.correlation_type == 'notso_only')} NOTSO-only, "
            f"{sum(1 for c in correlations if c.correlation_type == 'manoeuvre_only')} manoeuvre-only"
        )
    except Exception as exc:
        logger.exception("NOTSO correlation failed for %d", pol.satno)
        return HTMLResponse(f'<p class="error-msg">Correlation error: {exc}</p>')

    return render(request, "partials/notso_results.html", {
        "correlations": correlations,
        "profile": profile,
        "pol": pol,
        "source_label": source_label,
    })


# ── Photometry routes ─────────────────────────────────────────────────────────

@router.get("/photometry-panel", response_class=HTMLResponse)
async def pol_photometry_panel(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the photometry analysis input panel."""
    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)
    return render(request, "partials/photometry_panel.html", {
        "pol": pol,
    })


@router.post("/photometry-analyse", response_class=HTMLResponse)
async def pol_photometry_analyse(
    request: Request,
    csv_text: Annotated[str, Form()] = "",
    recent_window_days: Annotated[float, Form()] = 30.0,
    baseline_window_days: Annotated[float, Form()] = 90.0,
    extinction_coeff: Annotated[float, Form()] = 0.12,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Parse photometry CSV and run change-detection analysis."""
    from spectre.astro.photometry import assess_photometry, parse_photometry_csv

    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)

    if not csv_text.strip():
        return HTMLResponse('<p class="error-msg">Paste a CSV with at least epoch_utc and apparent_magnitude columns.</p>')

    try:
        observations = parse_photometry_csv(csv_text)
        if len(observations) < 5:
            return HTMLResponse(
                f'<p class="error-msg">Need at least 5 valid observations, got {len(observations)}.</p>'
            )

        manoeuvres = pol.manoeuvres if pol else []
        result = assess_photometry(
            observations,
            manoeuvres=manoeuvres,
            extinction_coeff=extinction_coeff,
            recent_window_days=recent_window_days,
            baseline_window_days=baseline_window_days,
        )

        state.append_log(
            f"[Photometry] Analysed {len(observations)} obs"
            + (f" for SATNO {pol.satno}" if pol else "")
            + f": {result.change_direction} (p={result.p_value:.4f})"
        )
    except Exception as exc:
        logger.exception("Photometry analysis failed")
        return HTMLResponse(f'<p class="error-msg">Analysis error: {exc}</p>')

    return render(request, "partials/photometry_results.html", {
        "result": result,
        "n_observations": len(observations),
        "pol": pol,
    })
