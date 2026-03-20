"""Maneuver planning routes — intercept option generation.

Provides endpoints for intercept calculations and orbital event detection.
All computations use the pure-Python ``sipc.astro`` package (Lambert, Hohmann,
bi-elliptic).  Orbital event detection uses SGP4 via ``sipc.astro.events``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta as _timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from sipc.astro.events import EventType, find_orbital_events
from sipc.astro.maneuvers import (
    InterceptSolution,
    lambert_intercept,
    hohmann_intercept,
    bielliptic_intercept,
    phasing_intercept,
    cw_radial_intercept,
    cw_drift_intercept,
    vbar_hop_intercept,
    hbar_hop_intercept,
    plane_change_intercept,
    j2_drift_intercept,
    cola_intercept,
    geo_drift_intercept,
    manoeuvre_detect_intercept,
    nmc_intercept,
    detectability_intercept,
    evasion_intercept,
    intent_predict_intercept,
    intercept_envelope_intercept,
    stability_intercept,
    fingerprint_intercept,
    formation_intercept,
    terrain_intercept,
    min_time_intercept_wrapper,
)
from sipc.domain.models import (
    BurnLocation,
    BurnResult,
    InterceptMethod,
    InterceptResult,
    OrbitalEvent,
)
from sipc.web.auth import require_login
from sipc.web.deps import render
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/maneuver")

# ── Intelligence helper sets ──────────────────────────────────────────────────

_OFFENSIVE_METHODS = {
    InterceptMethod.LAMBERT, InterceptMethod.HOHMANN, InterceptMethod.BIELLIPTIC,
    InterceptMethod.RENDEZVOUS, InterceptMethod.PROXIMITY, InterceptMethod.PHASING,
    InterceptMethod.RBAR_HOP, InterceptMethod.VBAR_HOP, InterceptMethod.HBAR_HOP,
    InterceptMethod.CW_DRIFT, InterceptMethod.MIN_TIME,
}
_REPOSITIONING_METHODS = {
    InterceptMethod.PLANE_CHANGE, InterceptMethod.J2_DRIFT,
    InterceptMethod.GEO_DRIFT, InterceptMethod.NMC,
}
_DEFENSIVE_METHODS = {
    InterceptMethod.COLA, InterceptMethod.EVASION, InterceptMethod.FORMATION,
}
_ASSESSMENT_METHODS = {
    InterceptMethod.DETECTABILITY, InterceptMethod.INTENT_PREDICT,
    InterceptMethod.INTERCEPT_ENVELOPE, InterceptMethod.STABILITY,
    InterceptMethod.FINGERPRINT, InterceptMethod.TERRAIN,
    InterceptMethod.MANOEUVRE_DETECT,
}

_INTENT_LABELS: dict[InterceptMethod, str] = {
    InterceptMethod.LAMBERT: "Close-Proximity Operation",
    InterceptMethod.PROXIMITY: "Close-Proximity Operation",
    InterceptMethod.RENDEZVOUS: "Close-Proximity Operation",
    InterceptMethod.HOHMANN: "Orbital Transfer — Energy Change",
    InterceptMethod.BIELLIPTIC: "Orbital Transfer — Energy Change",
    InterceptMethod.PHASING: "Phasing Rendezvous",
    InterceptMethod.RBAR_HOP: "R-Bar Hop (Radial Proximity Approach)",
    InterceptMethod.VBAR_HOP: "V-Bar Hop Sequence (Along-Track Approach)",
    InterceptMethod.HBAR_HOP: "H-Bar Hop Sequence (Orbit-Normal Approach)",
    InterceptMethod.CW_DRIFT: "Proximity Manoeuvre (CW)",
    InterceptMethod.NMC: "Proximity Manoeuvre (CW)",
    InterceptMethod.PLANE_CHANGE: "Plane Change — Orbit Alignment",
    InterceptMethod.J2_DRIFT: "J2-Assisted RAAN Drift",
    InterceptMethod.COLA: "Collision Avoidance",
    InterceptMethod.GEO_DRIFT: "GEO Longitude Relocation",
    InterceptMethod.MANOEUVRE_DETECT: "Observed Manoeuvre — Classification",
    InterceptMethod.DETECTABILITY: "Detectability Assessment",
    InterceptMethod.EVASION: "Evasion Manoeuvre",
    InterceptMethod.INTENT_PREDICT: "Adversary Intent Assessment",
    InterceptMethod.INTERCEPT_ENVELOPE: "Intercept Reachability Envelope",
    InterceptMethod.STABILITY: "Relative Motion Stability Analysis",
    InterceptMethod.FINGERPRINT: "Behavioural Fingerprint Analysis",
    InterceptMethod.FORMATION: "Formation-Aware Defensive Burn",
    InterceptMethod.TERRAIN: "Orbital Terrain Risk Assessment",
    InterceptMethod.MIN_TIME: "Minimum-Time Intercept",
}


def _compute_intercept_intel(result: "InterceptResult") -> dict:
    """Pre-compute all intelligence analysis data for the intercept result template.

    Returns a plain dict that is Jinja-safe — no custom objects, all primitives.
    """
    import math

    method = result.method
    dv = result.total_delta_v_km_s
    miss = result.intercept_range_km

    # ── Threat classification ────────────────────────────────────────────────
    if method in _ASSESSMENT_METHODS:
        manoeuvre_type = "ASSESSMENT"
        threat_level = "ASSESSMENT"
        threat_color = "#6b7280"
        threat_bg = "rgba(107,114,128,0.04)"
    elif method in _DEFENSIVE_METHODS:
        manoeuvre_type = "DEFENSIVE"
        threat_level = "LOW"
        threat_color = "#22c55e"
        threat_bg = "rgba(34,197,94,0.04)"
    else:
        if method in _OFFENSIVE_METHODS:
            manoeuvre_type = "OFFENSIVE"
        else:
            manoeuvre_type = "REPOSITIONING"
        if dv >= 2.0:
            threat_level = "CRITICAL"
            threat_color = "#ef4444"
            threat_bg = "rgba(239,68,68,0.04)"
        elif dv >= 0.5:
            threat_level = "HIGH"
            threat_color = "#f59e0b"
            threat_bg = "rgba(245,158,11,0.04)"
        elif dv >= 0.1:
            threat_level = "MEDIUM"
            threat_color = "#3b8beb"
            threat_bg = "rgba(59,139,235,0.04)"
        else:
            threat_level = "LOW"
            threat_color = "#22c55e"
            threat_bg = "rgba(34,197,94,0.04)"

    # ── Operational intent ───────────────────────────────────────────────────
    intent_label = _INTENT_LABELS.get(method, "Intercept Calculation")

    # ── ΔV classification ────────────────────────────────────────────────────
    if dv < 0.01:
        dv_class = "Micro-manoeuvre"
    elif dv < 0.05:
        dv_class = "Station-keeping"
    elif dv < 0.3:
        dv_class = "Minor Transfer"
    elif dv < 1.0:
        dv_class = "Moderate Transfer"
    elif dv < 3.0:
        dv_class = "Major Transfer"
    else:
        dv_class = "High-Energy Transfer"

    # ── Time of flight ───────────────────────────────────────────────────────
    if result.burns:
        tof_s = (result.arrival_epoch - result.burns[0].burn_epoch).total_seconds()
    else:
        tof_s = 0.0
    tof_hours = tof_s / 3600.0

    if tof_s < 60:
        tof_label = "< 1m"
    elif tof_s < 3600:
        tof_label = f"{int(tof_s // 60)}m"
    elif tof_s < 86400:
        h = int(tof_s // 3600)
        m = int((tof_s % 3600) // 60)
        tof_label = f"{h}h {m}m" if m else f"{h}h"
    else:
        d = int(tof_s // 86400)
        h = int((tof_s % 86400) // 3600)
        tof_label = f"{d}d {h}h" if h else f"{d}d"

    # ── ΔV budget percentage ─────────────────────────────────────────────────
    dv_budget_pct = min(100.0, dv / 3.0 * 100.0)

    # ── Per-burn analysis ────────────────────────────────────────────────────
    burn_intel = []
    for burn in result.burns:
        b_dv = burn.delta_v_km_s
        b_dv_ms = b_dv * 1000.0
        pro = burn.dv_prograde
        nor = burn.dv_normal
        rad = burn.dv_radial
        dv_total = math.sqrt(pro ** 2 + nor ** 2 + rad ** 2)
        if dv_total == 0.0:
            dv_total = 1e-12  # guard against division by zero

        pro_pct = min(100.0, abs(pro) / dv_total * 100.0)
        nor_pct = min(100.0, abs(nor) / dv_total * 100.0)
        rad_pct = min(100.0, abs(rad) / dv_total * 100.0)

        # Direction
        threshold = 0.7 * dv_total
        if abs(pro) >= threshold:
            direction = "Prograde" if pro >= 0 else "Retrograde"
            detail_map = {
                "Prograde": "Raises apogee — increases orbital energy",
                "Retrograde": "Lowers perigee — decreases orbital energy",
            }
        elif abs(nor) >= threshold:
            direction = "Normal" if nor >= 0 else "Anti-normal"
            detail_map = {
                "Normal": "Positive plane change — inclination increase",
                "Anti-normal": "Negative plane change — inclination decrease",
            }
        elif abs(rad) >= threshold:
            direction = "Radial" if rad >= 0 else "Anti-radial"
            detail_map = {
                "Radial": "Radial thrust — eccentricity adjustment",
                "Anti-radial": "Anti-radial thrust — eccentricity reduction",
            }
        else:
            direction = "Combined"
            detail_map = {"Combined": "Multi-axis manoeuvre — combined orbit change"}

        direction_detail = detail_map.get(direction, "Multi-axis manoeuvre — combined orbit change")

        burn_intel.append({
            "number": burn.burn_number,
            "epoch": burn.burn_epoch.strftime("%Y-%m-%d %H:%M UTC"),
            "dv_ms": round(b_dv_ms, 2),
            "direction": direction,
            "direction_detail": direction_detail,
            "pro_pct": round(pro_pct, 1),
            "nor_pct": round(nor_pct, 1),
            "rad_pct": round(rad_pct, 1),
        })

    # ── Observability assessment ─────────────────────────────────────────────
    if dv > 1.0:
        obs_level = "HIGH"
        obs_color = "#ef4444"
        obs_reason = "Large ΔV signature — high probability of SSN detection and attribution"
    elif dv > 0.1:
        obs_level = "MEDIUM"
        obs_color = "#f59e0b"
        obs_reason = "Moderate ΔV — detectable by tasked sensors, may evade routine surveillance"
    elif dv > 0.01:
        obs_level = "LOW"
        obs_color = "#22c55e"
        obs_reason = "Small ΔV — may fall below SSN detection threshold for routine cataloguing"
    else:
        obs_level = "VERY LOW"
        obs_color = "#6b7280"
        obs_reason = "Micro-manoeuvre — consistent with propellant settling or thermal cycling"

    # ── Method-specific insights ─────────────────────────────────────────────
    if method == InterceptMethod.RBAR_HOP:
        method_insights = [
            {"label": "Hop Type", "value": "R-Bar (radial)"},
            {"label": "Separation", "value": f"{miss:.2f} km"},
            {"label": "Burns", "value": "1 radial impulse"},
        ]
    elif method == InterceptMethod.VBAR_HOP:
        method_insights = [
            {"label": "Hop Type", "value": "V-Bar (along-track)"},
            {"label": "Total Advance", "value": f"{miss:.1f} km"},
            {"label": "Burns", "value": "2 radial (entry + correction)"},
            {"label": "Signature", "value": "Low — mimics perturbation drift"},
        ]
    elif method == InterceptMethod.HBAR_HOP:
        method_insights = [
            {"label": "Hop Type", "value": "H-Bar (orbit-normal)"},
            {"label": "Total Advance", "value": f"{miss:.1f} km"},
            {"label": "Burns", "value": "Normal burns at node crossings"},
            {"label": "Signature", "value": "Low — ACS/propellant settling cover"},
        ]
    elif method in (InterceptMethod.LAMBERT, InterceptMethod.PROXIMITY, InterceptMethod.RENDEZVOUS):
        method_insights = [
            {"label": "Miss Distance", "value": f"{miss:.2f} km"},
            {"label": "Transfer Type", "value": "Lambert arc"},
        ]
    elif method in (InterceptMethod.HOHMANN, InterceptMethod.BIELLIPTIC):
        method_insights = [
            {"label": "Miss Distance", "value": "0.0 km (coplanar)"},
            {"label": "Burn Count", "value": str(len(result.burns))},
        ]
    elif method == InterceptMethod.PHASING:
        method_insights = [
            {"label": "Miss Distance", "value": "0.0 km"},
            {"label": "Transfer Type", "value": "Phasing orbit"},
        ]
    elif method == InterceptMethod.DETECTABILITY:
        score = miss / 100.0
        method_insights = [
            {"label": "Observability Score", "value": f"{score * 100:.0f}/100"},
            {"label": "Detection Probability", "value": "High" if score > 0.6 else ("Medium" if score > 0.3 else "Low")},
        ]
    elif method == InterceptMethod.INTENT_PREDICT:
        likelihood = miss / 100.0
        method_insights = [
            {"label": "Intercept Likelihood", "value": f"{likelihood * 100:.0f}%"},
            {"label": "Assessment", "value": (
                "High confidence intercept intent" if likelihood > 0.7
                else ("Possible intercept intent" if likelihood > 0.4 else "Low probability of intercept intent")
            )},
        ]
    elif method == InterceptMethod.STABILITY:
        score = miss / 100.0
        method_insights = [
            {"label": "Stability Score", "value": f"{score * 100:.0f}/100"},
            {"label": "Assessment", "value": (
                "Stable relative motion" if score > 0.6
                else ("Marginally stable" if score > 0.3 else "Unstable — natural drift likely")
            )},
        ]
    elif method == InterceptMethod.FINGERPRINT:
        conf = miss / 100.0
        method_insights = [
            {"label": "Fingerprint Confidence", "value": f"{conf * 100:.0f}%"},
            {"label": "Estimated ΔV", "value": f"{dv * 1000:.1f} m/s"},
        ]
    elif method == InterceptMethod.TERRAIN:
        risk = miss / 100.0
        method_insights = [
            {"label": "Operational Risk", "value": f"{risk * 100:.0f}/100"},
            {"label": "Risk Level", "value": "High" if risk > 0.6 else ("Medium" if risk > 0.3 else "Low")},
        ]
    elif method == InterceptMethod.MANOEUVRE_DETECT:
        conf = miss / 100.0
        method_insights = [
            {"label": "Detection Confidence", "value": f"{conf * 100:.0f}%"},
            {"label": "Estimated ΔV", "value": f"{dv * 1000:.1f} m/s"},
        ]
    elif method == InterceptMethod.INTERCEPT_ENVELOPE:
        method_insights = [
            {"label": "Feasible Solutions", "value": f"{int(miss)}"},
            {"label": "Min Feasible ΔV", "value": f"{dv * 1000:.1f} m/s"},
        ]
    elif method == InterceptMethod.COLA:
        method_insights = [
            {"label": "Achieved Miss", "value": f"{miss:.2f} km"},
            {"label": "Strategy", "value": "Optimal COLA manoeuvre"},
        ]
    elif method == InterceptMethod.EVASION:
        method_insights = [
            {"label": "Achieved Miss", "value": f"{miss:.2f} km"},
            {"label": "Type", "value": "Defensive evasion"},
        ]
    elif method == InterceptMethod.GEO_DRIFT:
        method_insights = [
            {"label": "Longitude Gap", "value": f"{miss:.2f}\u00b0"},
            {"label": "Type", "value": "GEO station relocation"},
        ]
    elif method == InterceptMethod.J2_DRIFT:
        method_insights = [
            {"label": "RAAN \u0394 Target", "value": f"{miss:.2f}\u00b0"},
            {"label": "Type", "value": "J2-assisted drift"},
        ]
    else:
        method_insights = [
            {"label": "Miss Distance", "value": f"{miss:.2f} km"},
        ]

    # ── Summary text ─────────────────────────────────────────────────────────
    arrival_str = result.arrival_epoch.strftime("%Y-%m-%d %H:%M UTC")
    if method == InterceptMethod.RBAR_HOP:
        summary = (
            f"R-Bar hop places {result.red_name} {miss:.1f} km radially from "
            f"{result.blue_name} using {dv:.3f} km/s \u0394V in {tof_label}."
        )
    elif method == InterceptMethod.VBAR_HOP:
        summary = (
            f"V-Bar hop sequence advances {result.red_name} {miss:.1f} km along V-bar "
            f"toward {result.blue_name} via {len(result.burns)} burns "
            f"({dv:.3f} km/s total \u0394V, {tof_label} TOF). "
            f"Low observability — each hop mimics natural drift."
        )
    elif method == InterceptMethod.HBAR_HOP:
        summary = (
            f"H-Bar hop sequence advances {result.red_name} {miss:.1f} km in orbit-normal "
            f"toward {result.blue_name} via {len(result.burns)} normal burns "
            f"({dv:.3f} km/s total \u0394V, {tof_label} TOF). "
            f"Low observability — consistent with ACS activity."
        )
    elif method in (InterceptMethod.LAMBERT, InterceptMethod.PROXIMITY, InterceptMethod.RENDEZVOUS):
        summary = (
            f"Lambert transfer achieves {miss:.1f} km close approach to {result.blue_name} "
            f"with {dv:.3f} km/s total \u0394V in {tof_label}."
        )
    elif method in (InterceptMethod.HOHMANN, InterceptMethod.BIELLIPTIC):
        summary = (
            f"Hohmann transfer to {result.blue_name} requires {dv:.3f} km/s across "
            f"{len(result.burns)} burn(s), arriving {arrival_str}."
        )
    elif method == InterceptMethod.INTENT_PREDICT:
        likelihood_pct = int(miss)
        summary = (
            f"Intent assessment indicates {likelihood_pct}% probability of intercept "
            f"intent against {result.blue_name}."
        )
    elif method == InterceptMethod.DETECTABILITY:
        score_pct = int(miss)
        summary = (
            f"Detectability assessment scores {score_pct}/100 observability for "
            f"{result.red_name} manoeuvre against {result.blue_name}."
        )
    elif method == InterceptMethod.COLA:
        summary = (
            f"COLA manoeuvre achieves {miss:.1f} km miss distance with "
            f"{dv:.3f} km/s \u0394V, arriving {arrival_str}."
        )
    elif method == InterceptMethod.EVASION:
        summary = (
            f"Evasion manoeuvre places {result.red_name} {miss:.1f} km from threat "
            f"using {dv:.3f} km/s \u0394V."
        )
    elif method == InterceptMethod.MIN_TIME:
        summary = (
            f"Minimum-time intercept of {result.blue_name} achieved in {tof_label} "
            f"with {dv:.3f} km/s \u0394V."
        )
    else:
        summary = (
            f"{intent_label} for {result.red_name} \u2192 {result.blue_name}: "
            f"{dv:.3f} km/s \u0394V, arriving {arrival_str}."
        )

    return {
        "manoeuvre_type": manoeuvre_type,
        "threat_level": threat_level,
        "threat_color": threat_color,
        "threat_bg": threat_bg,
        "intent_label": intent_label,
        "dv_class": dv_class,
        "tof_hours": round(tof_hours, 3),
        "tof_label": tof_label,
        "dv_budget_pct": round(dv_budget_pct, 1),
        "burn_intel": burn_intel,
        "obs_level": obs_level,
        "obs_color": obs_color,
        "obs_reason": obs_reason,
        "method_insights": method_insights,
        "summary": summary,
    }

_INTERCEPT_METHOD_MAP: dict[str, InterceptMethod] = {m.value: m for m in InterceptMethod}


@router.get("/orbital-events", response_model=None)
async def orbital_events(
    request: Request,
    red_sat: Annotated[str, Query()] = "",
    blue_sat: Annotated[str, Query()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Compute upcoming orbital events for both red and blue satellites.

    Uses sgp4 to propagate the satellite TLEs and detect apogee, perigee,
    ascending node, and descending node crossings.
    """
    logger.info(
        "orbital_events called: red_sat=%r blue_sat=%r by %s",
        red_sat, blue_sat, current_user.username,
    )
    state = get_session_state(current_user.username)

    if not red_sat.strip() and not blue_sat.strip():
        return render(request, "partials/orbital_events.html", {
            "red_events": [], "blue_events": [],
            "red_name": "", "blue_name": "", "error": "Select satellites first.",
        })

    # Use scenario time if available, otherwise default to now + 24h.
    sc_start = state.scenario_start or datetime.now(tz=UTC)
    sc_stop = state.scenario_stop or (sc_start + _timedelta(hours=24))

    red_events: list = []
    blue_events: list = []

    if red_sat.strip():
        tle = _find_tle(state, red_sat.strip())
        if tle:
            raw = find_orbital_events(tle, sc_start, sc_stop)
            red_events = [_astro_event_to_domain(e) for e in raw]
        else:
            logger.warning("orbital_events: no TLE found for red %s", red_sat)

    if blue_sat.strip():
        tle = _find_tle(state, blue_sat.strip())
        if tle:
            raw = find_orbital_events(tle, sc_start, sc_stop)
            blue_events = [_astro_event_to_domain(e) for e in raw]
        else:
            logger.warning("orbital_events: no TLE found for blue %s", blue_sat)

    error = None
    if not red_events and not blue_events:
        error = "No orbital events found — check that satellites have valid TLEs."

    return render(request, "partials/orbital_events.html", {
        "red_events": red_events,
        "blue_events": blue_events,
        "red_name": red_sat.strip(),
        "blue_name": blue_sat.strip(),
        "error": error,
    })


@router.post("/apply-intercept", response_model=None)
async def apply_intercept(
    request: Request,
    red_sat: Annotated[str, Form()],
    blue_sat: Annotated[str, Form()],
    method: Annotated[str, Form()],
    manoeuvre_start: Annotated[str, Form()] = "",
    coast_hours: Annotated[float, Form()] = 1.0,
    intercept_hours: Annotated[float, Form()] = 6.0,
    number_of_burns: Annotated[int, Form()] = 1,
    target_distance_m: Annotated[float, Form()] = 0.0,
    minimize_delta_v: Annotated[bool, Form()] = True,
    max_dv: Annotated[float, Form()] = 3.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Calculate an intercept trajectory using sipc.astro solvers.

    Runs Lambert, Hohmann, or bi-elliptic transfer calculations using
    the pure-Python astro package.

    Returns the intercept result partial with per-burn breakdown.
    """
    state = get_session_state(current_user.username)

    if method not in _INTERCEPT_METHOD_MAP:
        return render(request, "partials/intercept_result.html", {
            "result": None, "error": f"Unknown intercept method: {method!r}",
        })

    # Parse manoeuvre start time.
    manoeuvre_start_dt = datetime.now(tz=UTC)
    if manoeuvre_start.strip():
        try:
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass

    # Look up TLEs.
    red_tle = _find_tle(state, red_sat.strip())
    blue_tle = _find_tle(state, blue_sat.strip())

    if not red_tle or not blue_tle:
        missing = []
        if not red_tle:
            missing.append(f"red ({red_sat})")
        if not blue_tle:
            missing.append(f"blue ({blue_sat})")
        return render(request, "partials/intercept_result.html", {
            "result": None, "error": f"No TLE found for: {', '.join(missing)}",
        })

    intercept_method = _INTERCEPT_METHOD_MAP[method]
    coast_s = coast_hours * 3600.0
    tof_s = intercept_hours * 3600.0
    target_km = target_distance_m / 1000.0

    loop = asyncio.get_running_loop()
    try:
        sol = await loop.run_in_executor(
            None,
            lambda: _run_intercept(
                intercept_method, red_tle, blue_tle,
                manoeuvre_start_dt, coast_s, tof_s, target_km,
            ),
        )
    except Exception as exc:
        logger.error(
            "apply_intercept failed for operator %s: %s", current_user.username, exc
        )
        state.append_log(f"[INTERCEPT] {method} failed: {exc}")
        return render(request, "partials/intercept_result.html", {
            "result": None, "error": f"Intercept calculation failed: {exc}",
        })

    # Map astro InterceptSolution → domain InterceptResult for the template.
    result = _solution_to_result(sol, red_sat.strip(), blue_sat.strip(), intercept_method)

    state.last_intercept_result = result
    state.intercept_history.append(result)
    burn_summary = ", ".join(
        f"burn{b.burn_number} ΔV={b.delta_v_km_s:.3f}" for b in result.burns
    )
    state.append_log(
        f"[INTERCEPT] {method} applied: "
        f"total ΔV={result.total_delta_v_km_s:.3f} km/s, "
        f"{len(result.burns)} burn(s) [{burn_summary}], "
        f"arrival={result.arrival_epoch.strftime('%Y-%m-%d %H:%M UTC')}, "
        f"miss={result.intercept_range_km:.1f} km"
    )
    logger.info(
        "apply_intercept: %s for operator %s (%s → %s total_dv=%.3f km/s, burns=%d)",
        method, current_user.username,
        red_sat, blue_sat, result.total_delta_v_km_s, len(result.burns),
    )

    intel = _compute_intercept_intel(result)

    return render(request, "partials/intercept_result.html", {
        "result": result, "error": None,
        "intercept_history": state.intercept_history,
        "intel": intel,
    })


# ── All-methods batch calculation ─────────────────────────────────────────

_ALL_METHODS_SEQUENCE: list[InterceptMethod] = [
    # Classical transfers
    InterceptMethod.LAMBERT,
    InterceptMethod.HOHMANN,
    InterceptMethod.BIELLIPTIC,
    InterceptMethod.MIN_TIME,
    # Tactical proximity
    InterceptMethod.PHASING,
    InterceptMethod.RBAR_HOP,
    InterceptMethod.VBAR_HOP,
    InterceptMethod.HBAR_HOP,
    InterceptMethod.CW_DRIFT,
    InterceptMethod.NMC,
    # Orbital manoeuvres
    InterceptMethod.PLANE_CHANGE,
    InterceptMethod.J2_DRIFT,
    InterceptMethod.GEO_DRIFT,
    # Defensive
    InterceptMethod.COLA,
    InterceptMethod.EVASION,
    InterceptMethod.FORMATION,
    # Assessment
    InterceptMethod.DETECTABILITY,
    InterceptMethod.INTENT_PREDICT,
    InterceptMethod.STABILITY,
    InterceptMethod.FINGERPRINT,
    InterceptMethod.TERRAIN,
    InterceptMethod.MANOEUVRE_DETECT,
    InterceptMethod.INTERCEPT_ENVELOPE,
]

_THREAT_SORT_ORDER: dict[str, int] = {
    "CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "ASSESSMENT": 4,
}


@router.post("/apply-all-intercepts", response_model=None)
async def apply_all_intercepts(
    request: Request,
    red_sat: Annotated[str, Form()],
    blue_sat: Annotated[str, Form()],
    manoeuvre_start: Annotated[str, Form()] = "",
    coast_hours: Annotated[float, Form()] = 1.0,
    intercept_hours: Annotated[float, Form()] = 6.0,
    target_distance_m: Annotated[float, Form()] = 0.0,
    max_dv: Annotated[float, Form()] = 3.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Run all intercept methods and return a ranked comparison table.

    Executes all 23 methods concurrently using sensible shared parameters,
    computes intelligence assessments for each successful result, and returns
    a sortable table where every row can expand to show the full analysis.
    """
    state = get_session_state(current_user.username)

    manoeuvre_start_dt = datetime.now(tz=UTC)
    if manoeuvre_start.strip():
        try:
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass

    red_tle = _find_tle(state, red_sat.strip())
    blue_tle = _find_tle(state, blue_sat.strip())

    if not red_tle or not blue_tle:
        missing = []
        if not red_tle:
            missing.append(f"red ({red_sat})")
        if not blue_tle:
            missing.append(f"blue ({blue_sat})")
        return render(request, "partials/all_intercepts_result.html", {
            "items": [], "error": f"No TLE found for: {', '.join(missing)}",
            "red_name": red_sat.strip(), "blue_name": blue_sat.strip(),
            "intercept_history": state.intercept_history,
        })

    coast_s = coast_hours * 3600.0
    tof_s = intercept_hours * 3600.0
    target_km = target_distance_m / 1000.0

    loop = asyncio.get_running_loop()

    def _run_all() -> list[tuple[InterceptMethod, "InterceptResult | None", "str | None"]]:
        out = []
        for method in _ALL_METHODS_SEQUENCE:
            try:
                sol = _run_intercept(
                    method, red_tle, blue_tle,
                    manoeuvre_start_dt, coast_s, tof_s, target_km,
                )
                result = _solution_to_result(sol, red_sat.strip(), blue_sat.strip(), method)
                out.append((method, result, None))
            except Exception as exc:
                out.append((method, None, str(exc)))
        return out

    raw = await loop.run_in_executor(None, _run_all)

    items: list[dict] = []
    for method, result, error in raw:
        if result is not None:
            intel = _compute_intercept_intel(result)
            items.append({"method": method, "result": result, "intel": intel, "error": None})
        else:
            items.append({"method": method, "result": None, "intel": None, "error": error})

    def _sort_key(item: dict) -> tuple[int, float]:
        if item["result"] is None:
            return (99, 0.0)
        level = item["intel"]["threat_level"]
        return (_THREAT_SORT_ORDER.get(level, 5), item["result"].total_delta_v_km_s)

    items.sort(key=_sort_key)

    # Replace history with current batch so trade-space shows the full comparison
    state.intercept_history.clear()
    for item in items:
        if item["result"]:
            state.intercept_history.append(item["result"])
    state.last_intercept_result = items[0]["result"] if items and items[0]["result"] else None

    n_ok = sum(1 for i in items if i["result"])
    state.append_log(
        f"[INTERCEPT] All-methods batch: {red_sat.strip()} → {blue_sat.strip()}, "
        f"{n_ok}/{len(_ALL_METHODS_SEQUENCE)} methods succeeded"
    )
    logger.info(
        "apply_all_intercepts: %s → %s, %d/%d ok, by %s",
        red_sat.strip(), blue_sat.strip(),
        n_ok, len(_ALL_METHODS_SEQUENCE), current_user.username,
    )

    return render(request, "partials/all_intercepts_result.html", {
        "items": items,
        "error": None,
        "red_name": red_sat.strip(),
        "blue_name": blue_sat.strip(),
        "intercept_history": state.intercept_history,
    })


@router.get("/trade-space-data", response_model=None)
async def trade_space_data(
    current_user: User = Depends(require_login),
) -> JSONResponse:
    """Return JSON array of trade-space points from intercept history."""
    state = get_session_state(current_user.username)
    points = []
    for r in state.intercept_history:
        if r.burns:
            transfer_s = (r.arrival_epoch - r.burns[0].burn_epoch).total_seconds()
        else:
            transfer_s = 0.0
        points.append({
            "method": r.method.value,
            "delta_v": round(r.total_delta_v_km_s, 4),
            "transfer_time_min": round(transfer_s / 60.0, 2),
            "label": f"{r.method.value}: {r.red_name}→{r.blue_name}",
            "miss_km": round(r.intercept_range_km, 2),
        })
    return JSONResponse(content=points)


@router.post("/clear-history", response_model=None)
async def clear_history(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear intercept history and last result."""
    state = get_session_state(current_user.username)
    state.intercept_history.clear()
    state.last_intercept_result = None
    state.append_log("[INTERCEPT] Trade-space history cleared")
    return render(request, "partials/intercept_result.html", {
        "result": None, "error": None,
        "intercept_history": [],
        "intel": None,
    })


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_tle(state: object, sat_name: str) -> str | None:
    """Look up a satellite TLE from session state by object name."""
    for a in state.blue_assets:  # type: ignore[attr-defined]
        if a.stk_name == sat_name:
            return a.tle
    for t in state.red_tracks:  # type: ignore[attr-defined]
        if t.stk_name == sat_name:
            return t.tle
    return None


def _run_intercept(
    method: InterceptMethod,
    red_tle: str,
    blue_tle: str,
    start: datetime,
    coast_s: float,
    tof_s: float,
    target_km: float,
) -> InterceptSolution:
    """Dispatch to the appropriate sipc.astro solver."""
    if method in (InterceptMethod.LAMBERT, InterceptMethod.PROXIMITY):
        return lambert_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, tof_s=tof_s, coast_s=coast_s,
            target_distance_km=target_km,
        )
    elif method in (InterceptMethod.HOHMANN, InterceptMethod.RENDEZVOUS):
        return hohmann_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.BIELLIPTIC:
        return bielliptic_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.PHASING:
        # Use coast_hours as n_revolutions (integer), tof_s is unused
        n_revs = max(1, int(coast_s / 3600.0)) if coast_s > 3600 else 1
        return phasing_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, n_revolutions=n_revs,
        )
    elif method == InterceptMethod.RBAR_HOP:
        return cw_radial_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            desired_separation_km=max(target_km, 5.0),
            time_s=tof_s,
            coast_s=coast_s,
        )
    elif method == InterceptMethod.VBAR_HOP:
        n_hops = max(1, int(coast_s / 3600.0)) if coast_s > 3600 else 3
        hop_km = target_km if target_km > 0 else None
        return vbar_hop_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            n_hops=n_hops,
            hop_distance_km=hop_km,
            coast_s=0.0,
        )
    elif method == InterceptMethod.HBAR_HOP:
        n_hops = max(1, int(coast_s / 3600.0)) if coast_s > 3600 else 3
        hop_km = target_km if target_km > 0 else None
        return hbar_hop_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            n_hops=n_hops,
            hop_distance_km=hop_km,
            coast_s=0.0,
        )
    elif method == InterceptMethod.CW_DRIFT:
        return cw_drift_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            desired_drift_km=max(target_km, 10.0),
            time_s=tof_s,
            coast_s=coast_s,
        )
    elif method == InterceptMethod.PLANE_CHANGE:
        return plane_change_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.J2_DRIFT:
        return j2_drift_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.COLA:
        return cola_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            desired_miss_km=max(target_km, 1.0),
            time_before_tca_s=tof_s,
            coast_s=coast_s,
        )
    elif method == InterceptMethod.GEO_DRIFT:
        drift_days = coast_s / 3600.0 if coast_s > 3600 else None
        return geo_drift_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            drift_time_days=drift_days,
        )
    elif method == InterceptMethod.MANOEUVRE_DETECT:
        return manoeuvre_detect_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.NMC:
        return nmc_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            along_track_km=max(target_km, 2.0),
            coast_s=coast_s,
        )
    elif method == InterceptMethod.DETECTABILITY:
        return detectability_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            tof_s=tof_s, coast_s=coast_s,
        )
    elif method == InterceptMethod.EVASION:
        return evasion_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            desired_miss_km=max(target_km, 10.0),
            time_before_tca_s=tof_s,
            fuel_budget_km_s=coast_s / 3600.0 if coast_s > 0 else 0.5,
            coast_s=0.0,
        )
    elif method == InterceptMethod.INTENT_PREDICT:
        return intent_predict_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.INTERCEPT_ENVELOPE:
        return intercept_envelope_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, tof_s=tof_s,
            coast_s=coast_s, target_distance_km=target_km,
        )
    elif method == InterceptMethod.STABILITY:
        return stability_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.FINGERPRINT:
        return fingerprint_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.FORMATION:
        return formation_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start,
            desired_miss_km=max(target_km, 5.0),
            tof_s=tof_s, coast_s=coast_s,
        )
    elif method == InterceptMethod.TERRAIN:
        return terrain_intercept(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    elif method == InterceptMethod.MIN_TIME:
        max_dv = target_km if target_km > 0 else 3.0
        return min_time_intercept_wrapper(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, max_delta_v=max_dv,
            coast_s=coast_s,
        )
    else:
        raise ValueError(f"Unsupported intercept method: {method}")


def _solution_to_result(
    sol: InterceptSolution,
    red_name: str,
    blue_name: str,
    method: InterceptMethod,
) -> InterceptResult:
    """Convert an astro InterceptSolution to a domain InterceptResult."""
    burns = [
        BurnResult(
            burn_number=b.burn_number,
            segment_name=f"Burn {b.burn_number}",
            burn_epoch=b.epoch,
            delta_v_km_s=b.delta_v_mag,
            dv_prograde=b.dv_prograde,
            dv_normal=b.dv_normal,
            dv_radial=b.dv_radial,
        )
        for b in sol.burns
    ]
    return InterceptResult(
        red_name=red_name,
        blue_name=blue_name,
        method=method,
        burns=burns,
        total_delta_v_km_s=sol.total_delta_v,
        arrival_epoch=sol.arrival_epoch,
        intercept_range_km=sol.miss_distance_km,
        notes=f"Computed via sipc.astro {sol.method} solver",
    )


# Map astro EventType → domain BurnLocation for template compatibility.
_EVENT_TYPE_TO_BURN_LOCATION = {
    EventType.APOGEE: BurnLocation.APOGEE,
    EventType.PERIGEE: BurnLocation.PERIGEE,
    EventType.ASCENDING_NODE: BurnLocation.ASCENDING_NODE,
    EventType.DESCENDING_NODE: BurnLocation.DESCENDING_NODE,
}


def _astro_event_to_domain(ev: object) -> OrbitalEvent:
    """Convert an astro OrbitalEvent to a domain OrbitalEvent."""
    return OrbitalEvent(
        event_type=_EVENT_TYPE_TO_BURN_LOCATION[ev.event_type],  # type: ignore[attr-defined]
        epoch=ev.epoch,  # type: ignore[attr-defined]
        label=ev.label,  # type: ignore[attr-defined]
    )
