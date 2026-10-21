"""Historical Pattern of Life (PoL) routes for SPECTRE.

Fetches historical TLEs from UDL, runs the PoL analysis engine, and returns
rendered partials for the Historical PoL hero tab.
"""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from spectre.astro.pattern_of_life import analyse_pattern_of_life, parse_tle_history
from spectre.astro.tle_filter import filter_tle_history
from spectre.data.intel import get_intel
from spectre.domain.pol_assessment import assess_pattern_of_life
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.format_units import to_m_s
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
    params: dict[str, Any] = {
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
    params: dict[str, Any] = {"satNo": satno}
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

        quality_flags: list[Any] = []
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
        **_pol_view(pol, _reserve_reset_for(state, satno)),
    })


def _reserve_reset_for(state: object, satno: int) -> datetime | None:
    """The operator-recorded refuelling date for *satno*, if any.

    The assessment's fourth watchlist recommendation is to track refuelling as
    a capability multiplier: SJ-25 class activity removes the end-of-life ΔV
    constraint on a GEO inspector. Cumulative ΔV is monotonic, so without this
    a refuelled object reads as progressively more exhausted exactly as it
    becomes more capable.
    """
    resets = getattr(state, "pol_reserve_resets", None)
    if not isinstance(resets, dict):
        return None
    return resets.get(satno)


def _pol_view(pol: object, reserve_reset: datetime | None = None) -> dict[str, object]:
    """Every delta-v figure ``pol_results.html`` shows, converted once, here.

    THIS IS THE UNIT BOUNDARY for the pattern-of-life panel. ``pol`` is an
    astro ``PatternOfLifeResult`` and carries km/s, because the astro package
    works in km and km/s throughout. Everything this function returns is m/s
    and says so in its name.

    The template used to scale inline in twelve places. Each was correct on its
    own, and together they were a trap: this route ALSO converts at its
    boundary, so finishing the job here would have left the template scaling an
    already-converted value, putting the charts at 1,000,000x and the table at
    1,000x in the same panel, both rendering without error.

    ``manoeuvre_rows`` wraps each manoeuvre rather than replacing it, so the
    template keeps full access to the original object (epoch, type, altitude
    and inclination deltas) and reads only ``delta_v_m_s`` from the wrapper.
    """
    stats = getattr(pol, "dv_stats", None)
    assessment = assess_pattern_of_life(pol, reserve_reset)

    return {
        "assessment": assessment,
        "intel": assessment.intel,
        "anomaly": assessment.anomaly,
        "propellant": assessment.propellant,
        "limits": assessment.detection,
        "reserve_reset": reserve_reset,
        "total_dv_m_s": to_m_s(getattr(pol, "total_dv_km_s", None)),
        "dv_threshold_m_s": to_m_s(getattr(pol, "dv_threshold_km_s", None)),
        "pol_high_dv_m_s": to_m_s(getattr(pol, "pol_high_dv", None)),
        "dv_mean_m_s": to_m_s(stats.mean) if stats else None,
        "dv_std_m_s": to_m_s(stats.std) if stats else None,
        "dv_low_2sigma_m_s": to_m_s(stats.low_2sigma) if stats else None,
        "dv_high_2sigma_m_s": to_m_s(stats.high_2sigma) if stats else None,
        "dv_p95_m_s": to_m_s(stats.p95) if stats else None,
        # The assessment already works in m/s, so these need no conversion and
        # must not get one. Converting a converted figure is the trap that put
        # the charts at 1,000,000x in 0.5.16.
        "budget_total_dv_m_s": assessment.propellant.spent_m_s,
        "budget_annual_dv_m_s": assessment.propellant.annual_rate_m_s,
        "manoeuvre_rows": [{"m": v.manoeuvre, "v": v, "delta_v_m_s": v.delta_v_m_s}
                           for v in assessment.manoeuvres],
        "candidate_rows": [{"m": v.manoeuvre, "v": v, "delta_v_m_s": v.delta_v_m_s}
                           for v in assessment.candidates],
        "detection": _detection_view(pol),
    }


def _detection_view(pol: object) -> dict[str, object]:
    """What the detector examined, measured, and threw away.

    The manoeuvre count on its own is not defensible. This is the audit trail
    behind it: the threshold the object's own element sets forced, how many
    pairs fell under it, and how many were discarded on evidence rather than on
    magnitude. Every ΔV here is converted once, as everywhere else in this
    module.
    """
    noise = getattr(pol, "noise_model", None)
    return {
        "pairs_examined":       getattr(pol, "pairs_examined", 0),
        "rejected_below_floor": getattr(pol, "rejected_below_floor", 0),
        "rejected_on_evidence": getattr(pol, "rejected_on_evidence", 0),
        "skipped_long_gap":     getattr(pol, "skipped_long_gap", 0),
        "merged_duplicates":    getattr(pol, "merged_duplicates", 0),
        "breakdowns_truncated": getattr(pol, "breakdowns_truncated", 0),
        "confirmed":            len(getattr(pol, "manoeuvres", [])),
        "candidates":           len(getattr(pol, "candidate_manoeuvres", [])),
        "noise_floor_m_s":      to_m_s(noise.floor_km_s) if noise else None,
        "noise_median_m_s":     to_m_s(noise.median_km_s) if noise else None,
        "noise_mad_m_s":        to_m_s(noise.mad_km_s) if noise else None,
        "noise_samples":        noise.samples if noise else 0,
        "noise_method":         noise.method if noise else "",
    }


# ── Manoeuvre drill-down ──────────────────────────────────────────────────────

#: Suffix on a ``DvComponent.inputs`` key to the unit it is measured in. The
#: keys are symbols from the formula, so the unit has to come from somewhere;
#: taking it from the name keeps the two from ever drifting apart.
_INPUT_UNITS = {
    "_km_s":   "km/s",
    "_rad_s":  "rad/s",
    "_deg_day": "°/day",
    "_km":     "km",
    "_deg":    "°",
}


def _input_rows(inputs: dict[str, float]) -> list[dict[str, object]]:
    """One display row per number that entered a ΔV component.

    Values are left in the units the physics uses. Only ΔV is converted to m/s,
    and that happens on the component itself, not here: an operator checking
    ``Δv = n · Δa / 2`` by hand needs ``n`` in rad/s and ``Δa`` in km, which is
    what the formula is written in.
    """
    rows: list[dict[str, object]] = []
    for key, value in inputs.items():
        unit = ""
        for suffix, label in _INPUT_UNITS.items():
            if key.endswith(suffix):
                unit = label
                break
        rows.append({
            "key":   key,
            "label": key.replace("_", " "),
            "unit":  unit,
            "value": value,
            # Element differences run from 1e-7 to 1e4, so a fixed number of
            # decimal places is unreadable at one end and lossy at the other.
            "text":  f"{value:,.6g}",
        })
    return rows


def _estimate_view(est: object, headline_method: str) -> dict[str, object]:
    """One estimator's result, converted at this boundary."""
    return {
        "method":      getattr(est, "method", ""),
        "label":       getattr(est, "label", ""),
        "dv_m_s":      to_m_s(getattr(est, "dv_km_s", 0.0)),
        "notes":       list(getattr(est, "notes", ()) or ()),
        "failed":      bool(getattr(est, "failed", False)),
        "failure":     getattr(est, "failure_reason", ""),
        "is_headline": getattr(est, "method", "") == headline_method,
    }


def _snapshot_view(s: object) -> dict[str, object]:
    """One element set, flattened for the side-by-side table."""
    return {
        "epoch":          getattr(s, "epoch", None),
        "sma_km":         getattr(s, "sma_km", 0.0),
        "alt_km":         getattr(s, "alt_km", 0.0),
        "ecc":            getattr(s, "ecc", 0.0),
        "inc_deg":        getattr(s, "inc_deg", 0.0),
        "raan_deg":       getattr(s, "raan_deg", 0.0),
        "argp_deg":       getattr(s, "argp_deg", 0.0),
        "ma_deg":         getattr(s, "mean_anomaly_deg", 0.0),
        "mm_revday":      getattr(s, "mean_motion_revday", 0.0),
        "period_min":     getattr(s, "period_min", 0.0),
        "bstar":          getattr(s, "bstar", 0.0),
        "speed_km_s":     getattr(s, "orbital_speed_km_s", 0.0),
        "provenance":     getattr(s, "provenance_label", ""),
        "source":         getattr(s, "source", ""),
        "data_mode":      getattr(s, "data_mode", ""),
        "rms_residual":   getattr(s, "rms_residual", None),
        "element_set_no": getattr(s, "element_set_no", 0),
    }


def _breakdown_view(m: object) -> dict[str, object]:
    """Everything behind one manoeuvre's ΔV, ready for the drill-down.

    THIS IS THE UNIT BOUNDARY for the manoeuvre detail panel, on the same terms
    as :func:`_pol_view`. Every ΔV leaves here in m/s and says so in its name.
    Element values stay in the units the formulas are written in, labelled.

    Every key is always present, including when there is no breakdown to show.
    A partial context is how a panel comes to reference an undefined name, and
    Jinja's StrictUndefined turns that into a blank panel in production rather
    than a failure in test.
    """
    view: dict[str, object] = {
        # The interpreted view of this manoeuvre, supplied by the route. Named
        # here with a None default so a caller that spreads this dict cannot
        # leave the template reading an undefined name: under StrictUndefined
        # that is a 500, and under Jinja's default it is a silently blank panel.
        "v":                    None,
        "has_breakdown":        False,
        "delta_v_m_s":          to_m_s(getattr(m, "delta_v_km_s", 0.0)),
        "headline_method":      "",
        "confidence":           getattr(m, "confidence", "UNASSESSED"),
        "confidence_reason":    "",
        "warnings":             [],
        "gap_days":             float(getattr(m, "gap_days", 0.0) or 0.0),
        "agreement_ratio":      None,
        "snr":                  None,
        "burn_epoch":           None,
        "burn_ambiguous":       False,
        "position_mismatch_km": None,
        "cross_source":         False,
        "estimates":            [],
        "components":           [],
        "component_total_m_s":  None,
        "before":               {},
        "after":                {},
        "deltas":               {},
        "noise_floor_m_s":      None,
        "noise_median_m_s":     None,
        "noise_mad_m_s":        None,
        "noise_samples":        0,
    }

    bd = getattr(m, "breakdown", None)
    if bd is None:
        return view

    headline = getattr(bd, "headline_method", "")
    before, after = bd.before, bd.after
    view.update({
        "has_breakdown":        True,
        "delta_v_m_s":          to_m_s(bd.dv_km_s),
        "headline_method":      headline,
        "confidence":           bd.confidence,
        "confidence_reason":    bd.confidence_reason,
        "warnings":             list(bd.warnings),
        "gap_days":             bd.gap_days,
        "agreement_ratio":      bd.agreement_ratio,
        "snr":                  bd.snr,
        "burn_epoch":           bd.burn_epoch,
        "burn_ambiguous":       bool(getattr(bd.swept, "burn_epoch_ambiguous", False)),
        "position_mismatch_km": getattr(bd.swept, "position_mismatch_km", None),
        "cross_source":         bd.cross_source,
        "estimates":            [_estimate_view(e, headline) for e in bd.estimates],
        "components": [
            {
                "channel": c.channel,
                "label":   c.label,
                "dv_m_s":  to_m_s(c.dv_km_s),
                "driver":  c.driver,
                "formula": c.formula,
                "note":    c.note,
                "inputs":  _input_rows(c.inputs),
            }
            for c in bd.components
        ],
        "component_total_m_s": to_m_s(bd.elements.dv_km_s),
        "before": _snapshot_view(before),
        "after":  _snapshot_view(after),
        "deltas": {
            "sma_km":     after.sma_km - before.sma_km,
            "alt_km":     after.alt_km - before.alt_km,
            "ecc":        after.ecc - before.ecc,
            "inc_deg":    after.inc_deg - before.inc_deg,
            "raan_deg":   after.raan_deg - before.raan_deg,
            "argp_deg":   after.argp_deg - before.argp_deg,
            "mm_revday":  after.mean_motion_revday - before.mean_motion_revday,
            "period_min": after.period_min - before.period_min,
        },
        "noise_floor_m_s":  to_m_s(bd.noise.floor_km_s) if bd.noise else None,
        "noise_median_m_s": to_m_s(bd.noise.median_km_s) if bd.noise else None,
        "noise_mad_m_s":    to_m_s(bd.noise.mad_km_s) if bd.noise else None,
        "noise_samples":    bd.noise.samples if bd.noise else 0,
    })
    return view


@router.post("/reserve-reset", response_class=HTMLResponse)
async def pol_reserve_reset(
    request: Request,
    satno: Annotated[int, Form()],
    reset_date: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Record or clear a refuelling date, and re-render against it.

    Cumulative ΔV is monotonic, so an object that has been refuelled reads as
    progressively more exhausted exactly as it becomes more capable. SJ-21 was
    refuelled by SJ-25 in 2025 and its spend since 2022 keeps counting against
    it. Everything before the reset is retained and reported separately.

    The transferred quantity is deliberately not modelled. The one reported
    figure, 142 kg of hydrazine, is secondary reporting that the open-source
    assessment marks unconfirmed, and inventing a number here would put a
    fabricated reserve into a capability verdict.
    """
    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)
    if pol is None or pol.satno != satno:
        return HTMLResponse(
            '<p class="error-msg">No PoL analysis for this SATNO. Run Pattern of Life first.</p>'
        )

    resets = getattr(state, "pol_reserve_resets", None)
    if not isinstance(resets, dict):
        resets = {}
        state.pol_reserve_resets = resets  # type: ignore[attr-defined]

    cleared = not reset_date.strip()
    if cleared:
        resets.pop(satno, None)
    else:
        try:
            parsed = datetime.strptime(reset_date.strip()[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return HTMLResponse(
                f'<p class="error-msg">Could not read "{html.escape(reset_date)}" as a '
                "date. Use YYYY-MM-DD.</p>"
            )
        resets[satno] = parsed

    state.append_log(
        f"[POL] Reserve reset for {satno} "
        + ("cleared" if cleared else f"set to {reset_date.strip()[:10]}")
    )
    return render(request, "partials/pol_results.html", {
        "pol": pol,
        "source": "UDL",
        "pair": get_intel(satno),
        **_pol_view(pol, resets.get(satno)),
    })


@router.post("/manoeuvre-detail", response_class=HTMLResponse)
async def pol_manoeuvre_detail(
    request: Request,
    satno: Annotated[int, Form()],
    manoeuvre_epoch: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """The full working behind one manoeuvre's ΔV figure.

    Both element sets side by side with their provenance, every term in the
    decomposition with the numbers that produced it, all three estimators, and
    why the result was or was not believed.
    """
    state = get_session_state(current_user.username)
    pol = getattr(state, "last_pol_analysis", None)

    if pol is None or pol.satno != satno:
        return HTMLResponse(
            '<p class="error-msg">No PoL analysis for this SATNO. Run Pattern of Life first.</p>'
        )

    target = manoeuvre_epoch[:19]
    everything = list(pol.manoeuvres) + list(getattr(pol, "candidate_manoeuvres", []))
    matching = [m for m in everything
                if m.epoch.strftime("%Y-%m-%dT%H:%M:%S") == target]
    if not matching:
        return HTMLResponse(
            f'<p class="error-msg">Manoeuvre at {html.escape(manoeuvre_epoch)} '
            "not found in PoL results.</p>"
        )

    m = matching[0]
    # The interpretation comes from the same assessment the results panel uses,
    # so the drill-down cannot disagree with the row it was opened from.
    assessment = assess_pattern_of_life(pol, _reserve_reset_for(state, satno))
    view = next((v for v in (*assessment.manoeuvres, *assessment.candidates)
                 if v.manoeuvre is m), None)
    return render(request, "partials/pol_manoeuvre_detail.html", {
        "m": m,
        "v": view,
        "satno": satno,
        "confirmed": m in pol.manoeuvres,
        **_breakdown_view(m),
    })


@router.post("/monte-carlo", response_class=HTMLResponse)
async def pol_monte_carlo(  # noqa: PLR0913, PLR0917 - FastAPI form parameters
    request: Request,
    satno: Annotated[int, Form()],
    manoeuvre_epoch: Annotated[str, Form()],
    manoeuvre_type: Annotated[str, Form()] = "orbit_raise",
    n_samples: Annotated[int, Form()] = 500,
    horizon_h: Annotated[float, Form()] = 48.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Run Monte Carlo simulation for a specific detected manoeuvre."""
    import asyncio

    from spectre.astro.monte_carlo import (
        MANOEUVRE_ARCHETYPES,
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
            f'<p class="error-msg">Manoeuvre at {html.escape(manoeuvre_epoch)} not found in PoL results.</p>'
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
        return HTMLResponse(f'<p class="error-msg">Monte Carlo error: {html.escape(str(exc))}</p>')

    return render(request, "partials/pol_mc_results.html", {
        "mc": result,
        "manoeuvre": manoeuvre,
        # Converted here, not in the template. See _pol_view.
        "manoeuvre_dv_m_s": to_m_s(manoeuvre.delta_v_km_s),
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
            # pattern_of_life is an astro module and reports km/s; the operator
            # reads m/s. This is the conversion boundary for this panel.
            "dv_mean_m_s": pol.dv_stats.mean * 1000.0 if pol.dv_stats else None,  # km/s -> m/s
            "dv_2sigma_high_m_s": pol.pol_high_dv * 1000.0 if pol.pol_high_dv else None,  # km/s -> m/s
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
        return HTMLResponse(f'<p class="error-msg">Correlation error: {html.escape(str(exc))}</p>')

    return render(request, "partials/notso_results.html", {
        # Rows carry their own m/s figures so the template does no arithmetic.
        "correlation_rows": [
            {
                "c": c,
                "manoeuvre_dv_m_s": to_m_s(
                    c.manoeuvre.delta_v_km_s if c.manoeuvre else None
                ),
                "predicted_dv_m_s": to_m_s(
                    c.notso.predicted_delta_v_km_s if c.notso else None
                ),
            }
            for c in correlations
        ],
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
        return HTMLResponse(f'<p class="error-msg">Analysis error: {html.escape(str(exc))}</p>')

    return render(request, "partials/photometry_results.html", {
        "result": result,
        "n_observations": len(observations),
        "pol": pol,
    })
