"""Maneuver planning routes — intercept option generation.

Provides endpoints for intercept calculations and orbital event detection.
All computations use the pure-Python ``spectre.astro`` package (Lambert, Hohmann,
bi-elliptic).  Orbital event detection uses SGP4 via ``spectre.astro.events``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from datetime import timedelta as _timedelta
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from spectre.astro.constants import regimes_compatible
from spectre.astro.events import EventType, find_orbital_events
from spectre.astro.maneuvers import (
    InterceptSolution,
    bielliptic_intercept,
    cola_intercept,
    cw_drift_intercept,
    cw_radial_intercept,
    detectability_intercept,
    evasion_intercept,
    fingerprint_intercept,
    formation_intercept,
    geo_drift_intercept,
    hbar_hop_intercept,
    hohmann_intercept,
    intent_predict_intercept,
    intercept_envelope_intercept,
    j2_drift_intercept,
    lambert_intercept,
    manoeuvre_detect_intercept,
    min_time_intercept_wrapper,
    nmc_intercept,
    phasing_intercept,
    plane_change_intercept,
    stability_intercept,
    terrain_intercept,
    vbar_hop_intercept,
)
from spectre.astro.propagator import regime_from_tle
from spectre.data.intel import get_intel, satno_from_tle
from spectre.domain.manoeuvre_calibration import (
    DEFAULT_SWEEP_BUDGET_M_S,
    Posture,
    classify_posture,
    from_km_s,
    kind_for_method,
    per_event_station_keeping_m_s,
    to_km_s,
)
from spectre.domain.models import (
    BurnLocation,
    BurnResult,
    InterceptMethod,
    InterceptResult,
    OrbitalEvent,
)
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.format_units import format_tof_label
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/maneuver")

# Human-readable altitude hint for each orbit regime — used in error messages.
_REGIME_ALT_HINT: dict[str, str] = {
    "LEO": "200–2,000 km",
    "MEO": "2,000–35,400 km",
    "GEO": "~35,786 km",
    "GTO": "LEO→GEO transfer orbit",
    "HEO": "highly elliptical",
    "DEEP": ">36,200 km",
}

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


#: Delta-v landmarks in m/s, from the manoeuvre assessment. Named rather than
#: inlined so the same figure cannot drift between the two panels that use it.
#:
#: 1 m/s      the top of a collision avoidance burn (Table 4)
#: 50 m/s     one year of GEO north-south station-keeping (Table 3)
#: 170 m/s    the most aggressive GEO relocation on record, 90 deg in 3 days
#: 500 m/s    the point at which an on-station manoeuvre is a strong anomaly
#: 3,000 m/s  beyond the reserve of every flown platform class (Table 2)
_CAM_SCALE_M_S: float = 1.0
#: One routine station-keeping burn, derived from Table 3's annual budget and a
#: fortnightly GEO cadence rather than asserted. The band below used to run
#: from 1 m/s straight to the ANNUAL figure and was labelled "Station-keeping
#: scale", so a 34 m/s burn — eighteen real station-keeping burns at once, and
#: the cost of a 180 degree GEO relocation — read as routine housekeeping.
_SINGLE_SK_BURN_M_S: float = per_event_station_keeping_m_s("GEO")[0]
_ANNUAL_STATION_KEEPING_M_S: float = 50.0
_MOST_AGGRESSIVE_OBSERVED_M_S: float = 170.0
_ANOMALY_M_S: float = 500.0
_BEYOND_PLATFORM_M_S: float = 3000.0


#: How each posture is presented on the intercept panel. An AGGRESSIVE profile
#: is the alarming one: it is the manoeuvre an actor would only make for effect.
_POSTURE_PRESENTATION: dict[Posture, tuple[str, str, str]] = {
    Posture.BENIGN: ("LOW", "#22c55e", "rgba(34,197,94,0.04)"),
    Posture.ANNOYANCE: ("MEDIUM", "#3b8beb", "rgba(59,139,235,0.04)"),
    Posture.AGGRESSIVE: ("HIGH", "#f59e0b", "rgba(245,158,11,0.04)"),
    Posture.BEYOND_PLATFORM: ("CRITICAL", "#ef4444", "rgba(239,68,68,0.04)"),
}



# ── Pieces of the intercept intelligence panel ───────────────────────────────
#
# _compute_intercept_intel was 163 statements across 56 branches, past the
# point where a reader can hold it or a reviewer can check it. Each piece below
# is pure: it reads its inputs and returns a value, with no shared state, so it
# can be read and tested on its own. The behaviour they had before the split is
# pinned by tests/unit/test_intercept_intel_characterisation.py.


#: The ΔV bands an operator reads, each as (upper edge in m/s, label), lowest
#: first. A burn takes the label of the first band whose edge it is below.
#: A table rather than a ladder of seven returns: the edges above already carry
#: their own provenance, and in this form an edge out of order, or a label
#: reused between two bands, is visible on one screen instead of spread down a
#: chain that has to be read in order to be checked.
_DV_BANDS: tuple[tuple[float, str], ...] = (
    (_CAM_SCALE_M_S, "Micro-manoeuvre"),
    (_SINGLE_SK_BURN_M_S, "Station-keeping scale"),
    (_ANNUAL_STATION_KEEPING_M_S, "Within a year's station-keeping budget"),
    (_MOST_AGGRESSIVE_OBSERVED_M_S, "Minor Transfer"),
    (_ANOMALY_M_S, "Moderate Transfer"),
    (_BEYOND_PLATFORM_M_S, "Major Transfer"),
)
#: Reported above every band edge.
_DV_BAND_ABOVE_ALL: str = "High-Energy Transfer"


def _dv_classification(dv: float) -> str:
    """Name the scale of a burn, given its magnitude in m/s.

    The boundaries come from observed behaviour, not round numbers: 1 m/s is
    the top of a collision-avoidance burn, about 2 m/s one ROUTINE station-
    keeping burn, 50 m/s a whole YEAR of GEO north-south station-keeping,
    170 m/s the most aggressive GEO relocation on record, and 500 m/s the point
    at which an on-station manoeuvre is a strong anomaly.

    The distinction between the second and the third matters. Spending a year's
    budget in one burn is what a relocation costs, and calling that
    "station-keeping scale" describes the arithmetic while hiding the
    behaviour.
    """
    for edge_m_s, label in _DV_BANDS:
        if dv < edge_m_s:
            return label
    return _DV_BAND_ABOVE_ALL


def _observability(dv: float) -> tuple[str, str, str]:
    """How visible a burn of this size is to space surveillance.

    Thresholds in m/s. They were 1.0 / 0.1 / 0.01 km/s, so against m/s values
    every burn above 1 m/s read HIGH. A manoeuvre at station-keeping scale is
    the one that hides in routine traffic, which is the point of this panel.
    """
    if dv > _MOST_AGGRESSIVE_OBSERVED_M_S:
        return ("HIGH", "#ef4444",
                "Large ΔV signature — high probability of SSN detection and attribution")
    if dv > _ANNUAL_STATION_KEEPING_M_S:
        return ("MEDIUM", "#f59e0b",
                "Moderate ΔV — detectable by tasked sensors, may evade routine surveillance")
    if dv > _CAM_SCALE_M_S:
        return ("LOW", "#22c55e",
                "Small ΔV — may fall below SSN detection threshold for routine cataloguing")
    return ("VERY LOW", "#6b7280",
            "Micro-manoeuvre — consistent with propellant settling or thermal cycling")


#: What each named burn direction does to the orbit. The branches below
#: each built their own one or two entry copy of this map, so the same
#: wording was written out four times and could drift between them.
_BURN_DIRECTION_DETAIL: dict[str, str] = {
    "Prograde": "Raises apogee — increases orbital energy",
    "Retrograde": "Lowers perigee — decreases orbital energy",
    "Normal": "Positive plane change — inclination increase",
    "Anti-normal": "Negative plane change — inclination decrease",
    "Radial": "Radial thrust — eccentricity adjustment",
    "Anti-radial": "Anti-radial thrust — eccentricity reduction",
    "Combined": "Multi-axis manoeuvre — combined orbit change",
}


def _burn_direction(pro: float, nor: float, rad: float, threshold: float) -> str:
    """Name the dominant axis of a burn, or "Combined" if no axis dominates.

    *threshold* is the share of the burn's vector magnitude an axis has to
    carry before it is named; the caller sets it.

    Lifted out of _burn_breakdown whole rather than split in half: the chain
    sat inside the per-burn loop, and the nesting penalty it carried there
    was most of that function's cognitive complexity score.
    """
    if abs(pro) >= threshold:
        return "Prograde" if pro >= 0 else "Retrograde"
    if abs(nor) >= threshold:
        return "Normal" if nor >= 0 else "Anti-normal"
    if abs(rad) >= threshold:
        return "Radial" if rad >= 0 else "Anti-radial"
    return "Combined"


#: Most recent intercepts kept for the trade space (F-134). The history grew
#: by one per apply-intercept call, in process-global state that survives
#: session expiry, until the operator cleared it.
_MAX_INTERCEPT_HISTORY = 200


def _record_intercept(state: Any, result: InterceptResult) -> None:
    """Make *result* the latest intercept and keep the history bounded."""
    state.last_intercept_result = result
    state.intercept_history.append(result)
    del state.intercept_history[:-_MAX_INTERCEPT_HISTORY]


def _burn_breakdown(result: InterceptResult) -> list[dict[str, Any]]:
    """Per-burn magnitude in m/s, dominant axis, and component percentages."""
    burn_intel: list[dict[str, Any]] = []
    burn_intel = []
    for burn in result.burns:
        b_dv = burn.delta_v_m_s
        b_dv_ms = b_dv  # already m/s
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
        direction = _burn_direction(pro, nor, rad, threshold)
        direction_detail = _BURN_DIRECTION_DETAIL.get(direction, "Multi-axis manoeuvre — combined orbit change")

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
    return burn_intel



#: A score above this reads High, above the lower one Medium, else Low. The
#: same band serves detectability, stability and terrain risk, which each
#: carried their own copy of the two numbers.
_SCORE_HIGH: float = 0.6
_SCORE_MEDIUM: float = 0.3


def _score_band(score: float) -> str:
    """Name a 0-1 score. One definition for three panels that share it."""
    if score > _SCORE_HIGH:
        return "High"
    return "Medium" if score > _SCORE_MEDIUM else "Low"


#: Intent inference is banded higher than the others: calling an approach
#: deliberate is a stronger claim than calling an orbit unstable.
_INTENT_CONFIDENT: float = 0.7
_INTENT_POSSIBLE: float = 0.4


def _banded(
    score: float,
    phrasings: tuple[str, str, str],
    bounds: tuple[float, float] = (_SCORE_HIGH, _SCORE_MEDIUM),
) -> str:
    """Pick one of three phrasings for a 0-1 score, high to low."""
    high, medium, low = phrasings
    high_at, medium_at = bounds
    if score > high_at:
        return high
    return medium if score > medium_at else low


#: Headings on the intercept insight table, as the operator reads them.
#: Seven methods show the miss distance and four name the transfer, so the
#: wording is written once: two methods heading the same quantity
#: differently would read as two different quantities.
_LABEL_MISS_DISTANCE: str = "Miss Distance"
_LABEL_TRANSFER_TYPE: str = "Transfer Type"
#: The transfer flown by the three methods that solve the same two-point
#: boundary value problem.
_TRANSFER_LAMBERT_ARC: str = "Lambert arc"


#: Intercept method -> the figures its panel shows.
#:
#: This was a twenty-way if/elif chain, which was most of the branching the
#: intelligence panel ever did. A table says what it actually is: a lookup, not
#: a decision. Adding a method is one row, and a method with no row of its own
#: still gets its miss distance rather than nothing.
#: Typed rather than ``Any``: an untyped value here makes every call site's
#: return type Any, which silently switches off checking in the callers.
_InsightBuilder = Callable[[InterceptResult, float, float], list[dict[str, Any]]]
_METHOD_INSIGHT_BUILDERS: dict[InterceptMethod, _InsightBuilder] = {
    InterceptMethod.RBAR_HOP:
        lambda result, dv, miss: (
            [
                {"label": "Hop Type", "value": "R-Bar (radial)"},
                {"label": "Separation", "value": f"{miss:.2f} km"},
                {"label": "Burns", "value": "1 radial impulse"},
            ]
        ),
    InterceptMethod.VBAR_HOP:
        lambda result, dv, miss: (
            [
                {"label": "Hop Type", "value": "V-Bar (along-track)"},
                {"label": "Total Advance", "value": f"{miss:.1f} km"},
                {"label": "Burns", "value": "2 radial (entry + correction)"},
                {"label": "Signature", "value": "Low — mimics perturbation drift"},
            ]
        ),
    InterceptMethod.HBAR_HOP:
        lambda result, dv, miss: (
            [
                {"label": "Hop Type", "value": "H-Bar (orbit-normal)"},
                {"label": "Total Advance", "value": f"{miss:.1f} km"},
                {"label": "Burns", "value": "Normal burns at node crossings"},
                {"label": "Signature", "value": "Low — ACS/propellant settling cover"},
            ]
        ),
    InterceptMethod.LAMBERT:
        lambda result, dv, miss: (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
                {"label": _LABEL_TRANSFER_TYPE, "value": _TRANSFER_LAMBERT_ARC},
            ]
        ),
    InterceptMethod.PROXIMITY:
        lambda result, dv, miss: (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
                {"label": _LABEL_TRANSFER_TYPE, "value": _TRANSFER_LAMBERT_ARC},
            ]
        ),
    InterceptMethod.RENDEZVOUS:
        lambda result, dv, miss: (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
                {"label": _LABEL_TRANSFER_TYPE, "value": _TRANSFER_LAMBERT_ARC},
            ]
        ),
    InterceptMethod.HOHMANN:
        lambda result, dv, miss: (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
                {"label": "Burn Count", "value": str(len(result.burns))},
            ]
        ),
    InterceptMethod.BIELLIPTIC:
        lambda result, dv, miss: (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
                {"label": "Burn Count", "value": str(len(result.burns))},
            ]
        ),
    InterceptMethod.PHASING:
        lambda result, dv, miss: (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
                {"label": _LABEL_TRANSFER_TYPE, "value": "Phasing orbit"},
            ]
        ),
    InterceptMethod.DETECTABILITY:
        lambda result, dv, miss: (
            [
                {"label": "Observability Score", "value": f"{miss:.0f}/100"},
                {"label": "Detection Probability", "value": _score_band(miss / 100.0)},
            ]
        ),
    InterceptMethod.INTENT_PREDICT:
        lambda result, dv, miss: (
            [
                {"label": "Intercept Likelihood", "value": f"{miss:.0f}%"},
                {"label": "Assessment", "value": _banded(
                    miss / 100.0,
                    (
                        "High confidence intercept intent",
                        "Possible intercept intent",
                        "Low probability of intercept intent",
                    ),
                    bounds=(_INTENT_CONFIDENT, _INTENT_POSSIBLE),
                )},
            ]
        ),
    InterceptMethod.STABILITY:
        lambda result, dv, miss: (
            [
                {"label": "Stability Score", "value": f"{miss:.0f}/100"},
                {"label": "Assessment", "value": _banded(
                    miss / 100.0,
                    (
                        "Stable relative motion",
                        "Marginally stable",
                        "Unstable — natural drift likely",
                    ),
                )},
            ]
        ),
    InterceptMethod.FINGERPRINT:
        lambda result, dv, miss: (
            [
                {"label": "Fingerprint Confidence", "value": f"{miss:.0f}%"},
                {"label": "Estimated ΔV", "value": f"{dv:.0f} m/s"},
            ]
        ),
    InterceptMethod.TERRAIN:
        lambda result, dv, miss: (
            [
                {"label": "Operational Risk", "value": f"{miss:.0f}/100"},
                {"label": "Risk Level", "value": _score_band(miss / 100.0)},
            ]
        ),
    InterceptMethod.MANOEUVRE_DETECT:
        lambda result, dv, miss: (
            [
                {"label": "Detection Confidence", "value": f"{miss:.0f}%"},
                {"label": "Estimated ΔV", "value": f"{dv:.0f} m/s"},
            ]
        ),
    InterceptMethod.INTERCEPT_ENVELOPE:
        lambda result, dv, miss: (
            [
                {"label": "Feasible Solutions", "value": f"{int(miss)}"},
                {"label": "Min Feasible ΔV", "value": f"{dv:.0f} m/s"},
            ]
        ),
    InterceptMethod.COLA:
        lambda result, dv, miss: (
            [
                {"label": "Achieved Miss", "value": f"{miss:.2f} km"},
                {"label": "Strategy", "value": "Optimal COLA manoeuvre"},
            ]
        ),
    InterceptMethod.EVASION:
        lambda result, dv, miss: (
            [
                {"label": "Achieved Miss", "value": f"{miss:.2f} km"},
                {"label": "Type", "value": "Defensive evasion"},
            ]
        ),
    InterceptMethod.GEO_DRIFT:
        lambda result, dv, miss: (
            [
                {"label": "Longitude Gap", "value": f"{miss:.2f}\u00b0"},
                {"label": "Type", "value": "GEO station relocation"},
            ]
        ),
    InterceptMethod.J2_DRIFT:
        lambda result, dv, miss: (
            [
                {"label": "RAAN \u0394 Target", "value": f"{miss:.2f}\u00b0"},
                {"label": "Type", "value": "J2-assisted drift"},
            ]
        ),
}


def _method_insights(
    result: InterceptResult, dv: float, miss: float,
) -> list[dict[str, Any]]:
    """The two or three figures that matter for THIS intercept method."""
    builder = _METHOD_INSIGHT_BUILDERS.get(result.method)
    if builder is None:
        return (
            [
                {"label": _LABEL_MISS_DISTANCE, "value": f"{miss:.2f} km"},
            ]
        )
    return builder(result, dv, miss)


# Two sentences are shared by more than one method, so they are named rather
# than written twice: a repeated f-string is where the Lambert wording comes to
# differ between the proximity and the rendezvous solver. Every builder takes
# the same five values whether or not it quotes them, so the table can call any
# row the same way; in these two the unused ones carry the leading underscore
# this codebase already uses for a deliberately unread parameter.
def _lambert_summary(
    result: InterceptResult, dv: float, miss: float, tof_label: str, _arrival: str,
) -> str:
    return (
        f"Lambert transfer achieves {miss:.1f} km close approach to {result.blue_name} "
        f"with {dv:.0f} m/s total \u0394V in {tof_label}."
    )


def _hohmann_summary(
    result: InterceptResult, dv: float, _miss: float, _tof_label: str, arrival: str,
) -> str:
    return (
        f"Hohmann transfer to {result.blue_name} requires {dv:.0f} m/s across "
        f"{len(result.burns)} burn(s), arriving {arrival}."
    )


#: Intercept method -> the one sentence its panel leads with.
#:
#: The same shape as _METHOD_INSIGHT_BUILDERS above, for the same reason: this
#: was an eleven-way if/elif chain over a fixed set of methods, which is a
#: lookup written as a decision. A method with no row of its own still gets the
#: generic sentence rather than nothing.
_SummaryBuilder = Callable[[InterceptResult, float, float, str, str], str]
_METHOD_SUMMARY_BUILDERS: dict[InterceptMethod, _SummaryBuilder] = {
    InterceptMethod.RBAR_HOP:
        lambda result, dv, miss, tof_label, arrival: (
            f"R-Bar hop places {result.red_name} {miss:.1f} km radially from "
            f"{result.blue_name} using {dv:.0f} m/s \u0394V in {tof_label}."
        ),
    InterceptMethod.VBAR_HOP:
        lambda result, dv, miss, tof_label, arrival: (
            f"V-Bar hop sequence advances {result.red_name} {miss:.1f} km along V-bar "
            f"toward {result.blue_name} via {len(result.burns)} burns "
            f"({dv:.0f} m/s total \u0394V, {tof_label} TOF). "
            f"Low observability — each hop mimics natural drift."
        ),
    InterceptMethod.HBAR_HOP:
        lambda result, dv, miss, tof_label, arrival: (
            f"H-Bar hop sequence advances {result.red_name} {miss:.1f} km in orbit-normal "
            f"toward {result.blue_name} via {len(result.burns)} normal burns "
            f"({dv:.0f} m/s total \u0394V, {tof_label} TOF). "
            f"Low observability — consistent with ACS activity."
        ),
    InterceptMethod.LAMBERT:    _lambert_summary,
    InterceptMethod.PROXIMITY:  _lambert_summary,
    InterceptMethod.RENDEZVOUS: _lambert_summary,
    InterceptMethod.HOHMANN:    _hohmann_summary,
    InterceptMethod.BIELLIPTIC: _hohmann_summary,
    InterceptMethod.INTENT_PREDICT:
        lambda result, dv, miss, tof_label, arrival: (
            f"Intent assessment indicates {int(miss)}% probability of intercept "
            f"intent against {result.blue_name}."
        ),
    InterceptMethod.DETECTABILITY:
        lambda result, dv, miss, tof_label, arrival: (
            f"Detectability assessment scores {int(miss)}/100 observability for "
            f"{result.red_name} manoeuvre against {result.blue_name}."
        ),
    InterceptMethod.COLA:
        lambda result, dv, miss, tof_label, arrival: (
            f"COLA manoeuvre achieves {miss:.1f} km miss distance with "
            f"{dv:.0f} m/s \u0394V, arriving {arrival}."
        ),
    InterceptMethod.EVASION:
        lambda result, dv, miss, tof_label, arrival: (
            f"Evasion manoeuvre places {result.red_name} {miss:.1f} km from threat "
            f"using {dv:.0f} m/s \u0394V."
        ),
    InterceptMethod.MIN_TIME:
        lambda result, dv, miss, tof_label, arrival: (
            f"Minimum-time intercept of {result.blue_name} achieved in {tof_label} "
            f"with {dv:.0f} m/s \u0394V."
        ),
}


def _summary_text(
    result: InterceptResult, dv: float, miss: float,
    intent_label: str, tof_label: str,
) -> str:
    """One sentence describing what this intercept would do."""
    arrival = result.arrival_epoch.strftime("%Y-%m-%d %H:%M UTC")
    builder = _METHOD_SUMMARY_BUILDERS.get(result.method)
    if builder is None:
        return (
            f"{intent_label} for {result.red_name} \u2192 {result.blue_name}: "
            f"{dv:.0f} m/s \u0394V, arriving {arrival}."
        )
    return builder(result, dv, miss, tof_label, arrival)


def _compute_intercept_intel(result: InterceptResult, regime: str = "") -> dict[str, Any]:
    """Pre-compute all intelligence analysis data for the intercept result template.

    Returns a plain dict that is Jinja-safe — no custom objects, all primitives.
    """
    method = result.method
    dv = result.total_delta_v_m_s
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
        manoeuvre_type = (
            "OFFENSIVE" if method in _OFFENSIVE_METHODS else "REPOSITIONING"
        )
        # Banded on posture, not on a bare delta-v figure. These thresholds
        # were 2.0, 0.5 and 0.1 km/s; against m/s values every intercept above
        # 2 m/s would read CRITICAL. Posture also asks the better question:
        # what does this cost say about how the actor would have to behave?
        posture = classify_posture(dv, regime, kind_for_method(method.value))
        threat_level, threat_color, threat_bg = _POSTURE_PRESENTATION[
            posture.posture
        ]

    # ── Operational intent ───────────────────────────────────────────────────
    intent_label = _INTENT_LABELS.get(method, "Intercept Calculation")

    dv_class = _dv_classification(dv)

    # ── Time of flight ───────────────────────────────────────────────────────
    tof_s = (
        (result.arrival_epoch - result.burns[0].burn_epoch).total_seconds()
        if result.burns else 0.0
    )
    tof_hours = tof_s / 3600.0
    tof_label = format_tof_label(tof_hours)

    # ── ΔV budget percentage ─────────────────────────────────────────────────
    # Against the default realistic budget rather than a hardcoded 3.0, which
    # in m/s would read 100 per cent for any burn above 3 m/s.
    dv_budget_pct = min(100.0, dv / DEFAULT_SWEEP_BUDGET_M_S * 100.0)

    burn_intel = _burn_breakdown(result)

    obs_level, obs_color, obs_reason = _observability(dv)

    method_insights = _method_insights(result, dv, miss)
    summary = _summary_text(result, dv, miss, intent_label, tof_label)

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
        # The denominator travels with the percentage. The template used to
        # carry its own hardcoded "3.0 m/s", which survived the 0.5.15 move to
        # the realistic 500 m/s budget and left the panel reporting a figure
        # against a number 167 times smaller than the one it was computed with.
        "dv_budget_m_s": DEFAULT_SWEEP_BUDGET_M_S,
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
    ascending node, and descending node crossings. The search runs in a
    worker thread, not on the event loop (audit F-040).
    """
    logger.info(
        "orbital_events called: red_sat=%r blue_sat=%r by %s",
        log_safe(red_sat), log_safe(blue_sat), log_safe(current_user.username),
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

    red_events: list[Any] = []
    blue_events: list[Any] = []

    if red_sat.strip():
        tle = _find_tle(state, red_sat.strip())
        if tle:
            raw = await asyncio.to_thread(find_orbital_events, tle, sc_start, sc_stop)
            red_events = [_astro_event_to_domain(e) for e in raw]
        else:
            logger.warning("orbital_events: no TLE found for red %s", log_safe(red_sat))

    if blue_sat.strip():
        tle = _find_tle(state, blue_sat.strip())
        if tle:
            raw = await asyncio.to_thread(find_orbital_events, tle, sc_start, sc_stop)
            blue_events = [_astro_event_to_domain(e) for e in raw]
        else:
            logger.warning("orbital_events: no TLE found for blue %s", log_safe(blue_sat))

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
    max_dv_m_s: Annotated[float, Form(ge=0.0, le=100000.0)] = DEFAULT_SWEEP_BUDGET_M_S,
    intercept_data_mode: Annotated[str, Form()] = "",
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Calculate an intercept trajectory using spectre.astro solvers.

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
        with contextlib.suppress(ValueError):
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)

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

    # Re-fetch TLEs if a per-panel data mode override was requested.
    effective_dm = intercept_data_mode.strip().upper() or state.udl_data_mode or "REAL"
    if intercept_data_mode.strip():
        red_tle, blue_tle = await _refetch_tles(red_tle, blue_tle, effective_dm, state)

    # Regime compatibility check — block cross-belt intercepts.
    try:
        red_regime = regime_from_tle(red_tle)
        blue_regime = regime_from_tle(blue_tle)
    except Exception:
        red_regime = blue_regime = "LEO"  # assume compatible on parse failure

    if not regimes_compatible(red_regime, blue_regime):
        return render(request, "partials/intercept_result.html", {
            "result": None,
            "intercept_data_mode": effective_dm,
            "error": (
                f"Regime mismatch — {red_sat} is {red_regime} "
                f"({_REGIME_ALT_HINT.get(red_regime, red_regime)}) but "
                f"{blue_sat} is {blue_regime} "
                f"({_REGIME_ALT_HINT.get(blue_regime, blue_regime)}). "
                "Cross-regime intercepts require impractical delta-V and are not supported."
            ),
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
                manoeuvre_start_dt, coast_s, tof_s, target_km, max_dv_m_s,
            ),
        )
    # BLE001: any solver failure is reported to the operator, not raised.
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "apply_intercept failed for operator %s: %s", log_safe(current_user.username), exc
        )
        state.append_log(f"[INTERCEPT] {method} failed: {exc}")
        return render(request, "partials/intercept_result.html", {
            "result": None, "error": f"Intercept calculation failed: {exc}",
        })

    # Map astro InterceptSolution → domain InterceptResult for the template.
    result = _solution_to_result(sol, red_sat.strip(), blue_sat.strip(), intercept_method)

    _record_intercept(state, result)
    burn_summary = ", ".join(
        f"burn{b.burn_number} ΔV={b.delta_v_m_s:.3f}" for b in result.burns
    )
    state.append_log(
        f"[INTERCEPT] {method} applied: "
        f"total ΔV={result.total_delta_v_m_s:.0f} m/s, "
        f"{len(result.burns)} burn(s) [{burn_summary}], "
        f"arrival={result.arrival_epoch.strftime('%Y-%m-%d %H:%M UTC')}, "
        f"miss={result.intercept_range_km:.1f} km"
    )
    logger.info(
        "apply_intercept: %s for operator %s (%s → %s total_dv=%.0f m/s, burns=%d)",
        log_safe(method), log_safe(current_user.username),
        log_safe(red_sat), log_safe(blue_sat), result.total_delta_v_m_s, len(result.burns),
    )

    intel = _compute_intercept_intel(result, red_regime)
    pair = get_intel(satno_from_tle(red_tle))

    return render(request, "partials/intercept_result.html", {
        "result": result, "error": None,
        "intercept_history": state.intercept_history,
        "intel": intel,
        "pair": pair,
        "intercept_data_mode": effective_dm,
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


class _InterceptArgs(NamedTuple):
    """One intercept run's solver inputs, carried together.

    The batch runs twenty-three methods over the same inputs and the solver
    dispatch table keys off them, so passing them as one value keeps both off
    the long positional signature that made ``_run_intercept`` unreadable.
    """

    red_tle: str
    blue_tle: str
    start: datetime
    coast_s: float
    tof_s: float
    target_km: float
    max_dv_m_s: float


def _missing_tle_labels(
    red_tle: str | None,
    red_sat: str,
    blue_tle: str | None,
    blue_sat: str,
) -> list[str]:
    """Name the sides whose TLE was not found, red before blue.

    The operator reads these in the error, so the order is fixed here rather
    than left to whatever the caller happens to check first.
    """
    missing: list[str] = []
    if not red_tle:
        missing.append(f"red ({red_sat})")
    if not blue_tle:
        missing.append(f"blue ({blue_sat})")
    return missing


def _run_all_methods(
    args: _InterceptArgs,
    red_name: str,
    blue_name: str,
) -> list[tuple[InterceptMethod, InterceptResult | None, str | None]]:
    """Run every method of the batch, keeping each one's failure beside it.

    A closure would have carried the route's nesting into its own branching and
    charged the route for it, which is how the batch came to be reported by the
    Code Quality gate in the first place.
    """
    out: list[tuple[InterceptMethod, InterceptResult | None, str | None]] = []
    for method in _ALL_METHODS_SEQUENCE:
        try:
            sol = _run_intercept(
                method, args.red_tle, args.blue_tle,
                args.start, args.coast_s, args.tof_s, args.target_km, args.max_dv_m_s,
            )
            result = _solution_to_result(sol, red_name, blue_name, method)
            out.append((method, result, None))
        # BLE001: any solver failure is reported per method, not raised.
        except Exception as exc:  # noqa: BLE001
            out.append((method, None, str(exc)))
    return out


def _items_from_solutions(
    raw: list[tuple[InterceptMethod, InterceptResult | None, str | None]],
    red_regime: str,
) -> list[dict[str, Any]]:
    """Turn each method's outcome into one row of the comparison table.

    A method that failed keeps its row and carries its error, so the panel
    accounts for all twenty-three rather than quietly listing fewer than it ran.
    """
    items: list[dict[str, Any]] = []
    for method, result, error in raw:
        if result is not None:
            intel = _compute_intercept_intel(result, red_regime)
            items.append({"method": method, "result": result, "intel": intel, "error": None})
        else:
            items.append({"method": method, "result": None, "intel": None, "error": error})
    return items


def _sort_key(item: dict[str, Any]) -> tuple[int, float]:
    """Rank one row by threat level, then by the delta-v it costs.

    A method whose solver failed sorts behind every assessment.
    """
    if item["result"] is None:
        return (99, 0.0)
    level = item["intel"]["threat_level"]
    return (_THREAT_SORT_ORDER.get(level, 5), item["result"].total_delta_v_m_s)


@router.post("/apply-all-intercepts", response_model=None)
async def apply_all_intercepts(
    request: Request,
    red_sat: Annotated[str, Form()],
    blue_sat: Annotated[str, Form()],
    manoeuvre_start: Annotated[str, Form()] = "",
    coast_hours: Annotated[float, Form()] = 1.0,
    intercept_hours: Annotated[float, Form()] = 6.0,
    target_distance_m: Annotated[float, Form()] = 0.0,
    max_dv_m_s: Annotated[float, Form(ge=0.0, le=100000.0)] = DEFAULT_SWEEP_BUDGET_M_S,
    intercept_data_mode: Annotated[str, Form()] = "",
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
        with contextlib.suppress(ValueError):
            manoeuvre_start_dt = datetime.fromisoformat(manoeuvre_start.strip()).replace(tzinfo=UTC)

    red_tle = _find_tle(state, red_sat.strip())
    blue_tle = _find_tle(state, blue_sat.strip())

    if not red_tle or not blue_tle:
        missing = _missing_tle_labels(red_tle, red_sat, blue_tle, blue_sat)
        return render(request, "partials/all_intercepts_result.html", {
            "items": [], "error": f"No TLE found for: {', '.join(missing)}",
            "red_name": red_sat.strip(), "blue_name": blue_sat.strip(),
            "intercept_history": state.intercept_history,
        })

    # Re-fetch TLEs if a per-panel data mode override was requested.
    effective_dm = intercept_data_mode.strip().upper() or state.udl_data_mode or "REAL"
    if intercept_data_mode.strip():
        red_tle, blue_tle = await _refetch_tles(red_tle, blue_tle, effective_dm, state)

    # Regime compatibility check — block cross-belt intercepts.
    try:
        red_regime = regime_from_tle(red_tle)
        blue_regime = regime_from_tle(blue_tle)
    except Exception:
        red_regime = blue_regime = "LEO"  # assume compatible on parse failure

    if not regimes_compatible(red_regime, blue_regime):
        return render(request, "partials/all_intercepts_result.html", {
            "items": [], "error": (
                f"Regime mismatch — {red_sat} is {red_regime} "
                f"({_REGIME_ALT_HINT.get(red_regime, red_regime)}) but "
                f"{blue_sat} is {blue_regime} "
                f"({_REGIME_ALT_HINT.get(blue_regime, blue_regime)}). "
                "Cross-regime intercepts require impractical delta-V and are not supported."
            ),
            "red_name": red_sat.strip(), "blue_name": blue_sat.strip(),
            "intercept_history": state.intercept_history,
            "intercept_data_mode": effective_dm,
        })

    coast_s = coast_hours * 3600.0
    tof_s = intercept_hours * 3600.0
    target_km = target_distance_m / 1000.0

    args = _InterceptArgs(
        red_tle, blue_tle, manoeuvre_start_dt, coast_s, tof_s, target_km, max_dv_m_s,
    )

    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None, lambda: _run_all_methods(args, red_sat.strip(), blue_sat.strip())
    )

    items = _items_from_solutions(raw, red_regime)
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
        log_safe(red_sat.strip()), log_safe(blue_sat.strip()),
        n_ok, len(_ALL_METHODS_SEQUENCE), log_safe(current_user.username),
    )

    return render(request, "partials/all_intercepts_result.html", {
        "items": items,
        "error": None,
        "red_name": red_sat.strip(),
        "blue_name": blue_sat.strip(),
        "intercept_history": state.intercept_history,
        "intercept_data_mode": effective_dm,
    })


@router.get("/trade-space-data", response_model=None)
async def trade_space_data(
    current_user: User = Depends(require_login),
) -> JSONResponse:
    """Return JSON array of trade-space points from intercept history."""
    state = get_session_state(current_user.username)
    points = []
    for r in state.intercept_history:
        transfer_s = (
            (r.arrival_epoch - r.burns[0].burn_epoch).total_seconds()
            if r.burns else 0.0
        )
        point: dict[str, Any] = {
            "method": r.method.value,
            "delta_v": round(r.total_delta_v_m_s, 1),  # m/s
            "transfer_time_min": round(transfer_s / 60.0, 2),
            "label": f"{r.method.value}: {r.red_name}→{r.blue_name}",
        }
        # An assessment method carries a 0-100 score in intercept_range_km;
        # emitted as miss_km, a score of 73 was plotted as a 73 km miss (F-131).
        if r.method in _ASSESSMENT_METHODS:
            point["score"] = round(r.intercept_range_km)
        else:
            point["miss_km"] = round(r.intercept_range_km, 2)
        points.append(point)
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
        "intercept_data_mode": "",
    })


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_tle(state: object, sat_name: str) -> str | None:
    """Look up a satellite TLE from session state by object name."""
    for a in state.blue_assets:  # type: ignore[attr-defined]
        if a.stk_name == sat_name:
            return str(a.tle)
    for t in state.red_tracks:  # type: ignore[attr-defined]
        if t.stk_name == sat_name:
            return str(t.tle)
    return None


async def _refetch_tles(
    red_tle: str,
    blue_tle: str,
    data_mode: str,
    state: object,
) -> tuple[str, str]:
    """Re-fetch the red and blue TLEs from UDL using *data_mode*.

    Falls back silently to the supplied originals when UDL credentials are
    absent, the SATNO cannot be extracted from the TLE, or the fetch fails.
    """
    if not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]
        return red_tle, blue_tle

    from spectre.web.routes.udl import fetch_tle_for_satno

    async def _try_fetch(tle: str) -> str:
        satno = satno_from_tle(tle)
        if satno is None:
            return tle
        result = await fetch_tle_for_satno(
            satno,
            state.udl_username,  # type: ignore[attr-defined]
            state.udl_password,  # type: ignore[attr-defined]
            data_mode=data_mode,
            source=getattr(state, "udl_tle_source", ""),
        )
        return result[0] if result else tle

    new_red, new_blue = await asyncio.gather(_try_fetch(red_tle), _try_fetch(blue_tle))
    return new_red, new_blue


# ── Intercept solver dispatch ────────────────────────────────────────────────
#
# _run_intercept was a chain of twenty-three elif branches over one value and
# scored 38 against the Code Quality gate's cognitive complexity limit of 15.
# It is now two tables, in the same spirit as _METHOD_INSIGHT_BUILDERS above:
# the solvers that take nothing but the coast time, and the ones whose
# arguments have to be shaped from the panel's inputs first. Every entry makes
# the call its branch made, unchanged.

#: The hour the panel's coast time is read in. Named after the same constant in
#: ``spectre.web.format_units``, because a bare 3600 beside a revolution count
#: and a drift time in days reads as neither.
_SECONDS_PER_HOUR: float = 3600.0
_SECONDS_PER_DAY: float = 86400.0


def _hop_count(coast_s: float, default: int) -> int:
    """Whole hours of coast, read as a revolution or hop count.

    The phasing and hop solvers count revolutions rather than taking a
    duration, so the panel's coast time doubles as that count once it runs past
    an hour. Below that the solver's own default stands.
    """
    if coast_s > _SECONDS_PER_HOUR:
        return max(1, int(coast_s / _SECONDS_PER_HOUR))
    return default


def _hop_distance_km(target_km: float) -> float | None:
    """Hop spacing for the V-bar and H-bar solvers, or None to leave it to them.

    Zero is the operator leaving the standoff field empty, not a request to hop
    nowhere.
    """
    if target_km > 0:
        return target_km
    return None


def _geo_drift_days(coast_s: float) -> float | None:
    """Drift time in DAYS for the GEO relocation solver, or None to leave it to the solver.

    The panel's coast field doubles as the drift duration. It was divided by
    the seconds in an hour, so a 48 h coast reached the solver as a 48-day
    drift and the reported delta-V came out about 1/24 of the true cost
    (audit F-007).
    """
    if coast_s > _SECONDS_PER_HOUR:
        return coast_s / _SECONDS_PER_DAY
    return None


def _lambert_transfer(a: _InterceptArgs) -> InterceptSolution:
    """Solve the Lambert arc, which LAMBERT and PROXIMITY both fly."""
    return lambert_intercept(
        red_tle=a.red_tle, blue_tle=a.blue_tle,
        manoeuvre_start=a.start, tof_s=a.tof_s, coast_s=a.coast_s,
        target_distance_km=a.target_km,
    )


#: Methods whose solver takes the two TLEs, the manoeuvre start and the coast
#: time, and nothing else. RENDEZVOUS flies the Hohmann transfer, as it did in
#: the chain this table replaced. These entries hold the solver object itself,
#: bound at import, so rebinding the name on this module does not reach them;
#: the shaped table below resolves its solver on every call.
_COAST_ONLY_SOLVERS: dict[InterceptMethod, Callable[..., InterceptSolution]] = {
    InterceptMethod.HOHMANN: hohmann_intercept,
    InterceptMethod.RENDEZVOUS: hohmann_intercept,
    InterceptMethod.BIELLIPTIC: bielliptic_intercept,
    InterceptMethod.PLANE_CHANGE: plane_change_intercept,
    InterceptMethod.J2_DRIFT: j2_drift_intercept,
    InterceptMethod.MANOEUVRE_DETECT: manoeuvre_detect_intercept,
    InterceptMethod.INTENT_PREDICT: intent_predict_intercept,
    InterceptMethod.STABILITY: stability_intercept,
    InterceptMethod.FINGERPRINT: fingerprint_intercept,
    InterceptMethod.TERRAIN: terrain_intercept,
}

#: Methods whose solver arguments are shaped from the panel's inputs first:
#: a standoff floor, a revolution count, a budget. Each lambda is one branch of
#: the old chain, and only the method it is keyed on reaches it.
_SHAPED_SOLVERS: dict[InterceptMethod, Callable[[_InterceptArgs], InterceptSolution]] = {
    InterceptMethod.LAMBERT: _lambert_transfer,
    InterceptMethod.PROXIMITY: _lambert_transfer,
    # Phasing counts whole revolutions rather than taking a time of flight, so
    # the panel's intercept hours have no part in it.
    InterceptMethod.PHASING:
        lambda a: phasing_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start, n_revolutions=_hop_count(a.coast_s, 1),
        ),
    InterceptMethod.RBAR_HOP:
        lambda a: cw_radial_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            desired_separation_km=max(a.target_km, 5.0),
            time_s=a.tof_s,
            coast_s=a.coast_s,
        ),
    InterceptMethod.VBAR_HOP:
        lambda a: vbar_hop_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            n_hops=_hop_count(a.coast_s, 3),
            hop_distance_km=_hop_distance_km(a.target_km),
            coast_s=0.0,
        ),
    InterceptMethod.HBAR_HOP:
        lambda a: hbar_hop_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            n_hops=_hop_count(a.coast_s, 3),
            hop_distance_km=_hop_distance_km(a.target_km),
            coast_s=0.0,
        ),
    InterceptMethod.CW_DRIFT:
        lambda a: cw_drift_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            desired_drift_km=max(a.target_km, 10.0),
            time_s=a.tof_s,
            coast_s=a.coast_s,
        ),
    InterceptMethod.COLA:
        lambda a: cola_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            desired_miss_km=max(a.target_km, 1.0),
            time_before_tca_s=a.tof_s,
            coast_s=a.coast_s,
        ),
    InterceptMethod.GEO_DRIFT:
        lambda a: geo_drift_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            drift_time_days=_geo_drift_days(a.coast_s),
        ),
    InterceptMethod.NMC:
        lambda a: nmc_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            along_track_km=max(a.target_km, 2.0),
            coast_s=a.coast_s,
        ),
    InterceptMethod.DETECTABILITY:
        lambda a: detectability_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            tof_s=a.tof_s, coast_s=a.coast_s,
        ),
    InterceptMethod.EVASION:
        lambda a: evasion_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            desired_miss_km=max(a.target_km, 10.0),
            time_before_tca_s=a.tof_s,
            # The operator's ΔV budget. This was the coast time in hours read
            # as km/s, so a 6 h coast meant a 6 km/s budget (audit F-037).
            fuel_budget_km_s=to_km_s(a.max_dv_m_s),
            coast_s=0.0,
        ),
    InterceptMethod.INTERCEPT_ENVELOPE:
        lambda a: intercept_envelope_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start, tof_s=a.tof_s,
            coast_s=a.coast_s, max_delta_v_km_s=to_km_s(a.max_dv_m_s),
        ),
    InterceptMethod.FORMATION:
        lambda a: formation_intercept(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            desired_miss_km=max(a.target_km, 5.0),
            tof_s=a.tof_s, coast_s=a.coast_s,
        ),
    InterceptMethod.MIN_TIME:
        lambda a: min_time_intercept_wrapper(
            red_tle=a.red_tle, blue_tle=a.blue_tle,
            manoeuvre_start=a.start,
            max_delta_v=to_km_s(a.max_dv_m_s),  # astro takes km/s
            coast_s=a.coast_s,
        ),
}


def _run_intercept(
    method: InterceptMethod,
    red_tle: str,
    blue_tle: str,
    start: datetime,
    coast_s: float,
    tof_s: float,
    target_km: float,
    max_dv_m_s: float = DEFAULT_SWEEP_BUDGET_M_S,
) -> InterceptSolution:
    """Dispatch to the appropriate spectre.astro solver.

    *target_km* is a SEPARATION DISTANCE and *max_dv_m_s* is a VELOCITY BUDGET.
    They were previously the same argument for MIN_TIME, which took its delta-v
    budget from ``target_km``, so an operator asking for a 500 m standoff
    silently set the solver's budget to 0.5 km/s. This is the second site of
    that defect; the first was recorded in 0.5.13 for
    ``intercept_envelope_intercept``.
    """
    coast_only = _COAST_ONLY_SOLVERS.get(method)
    if coast_only is not None:
        return coast_only(
            red_tle=red_tle, blue_tle=blue_tle,
            manoeuvre_start=start, coast_s=coast_s,
        )
    shaped = _SHAPED_SOLVERS.get(method)
    if shaped is None:
        raise ValueError(f"Unsupported intercept method: {method}")
    return shaped(
        _InterceptArgs(red_tle, blue_tle, start, coast_s, tof_s, target_km, max_dv_m_s)
    )


def _solution_to_result(
    sol: InterceptSolution,
    red_name: str,
    blue_name: str,
    method: InterceptMethod,
) -> InterceptResult:
    """Convert an astro InterceptSolution to a domain InterceptResult.

    THIS IS THE UNIT BOUNDARY for the intercept engine. The astro layer works
    in km/s; everything from the domain layer outwards is m/s. ``from_km_s`` is
    applied here and nowhere downstream.
    """
    burns = [
        BurnResult(
            burn_number=b.burn_number,
            segment_name=f"Burn {b.burn_number}",
            burn_epoch=b.epoch,
            delta_v_m_s=from_km_s(b.delta_v_mag),
            dv_prograde=from_km_s(b.dv_prograde),
            dv_normal=from_km_s(b.dv_normal),
            dv_radial=from_km_s(b.dv_radial),
        )
        for b in sol.burns
    ]
    return InterceptResult(
        red_name=red_name,
        blue_name=blue_name,
        method=method,
        burns=burns,
        total_delta_v_m_s=from_km_s(sol.total_delta_v),
        arrival_epoch=sol.arrival_epoch,
        intercept_range_km=sol.miss_distance_km,
        notes=f"Computed via spectre.astro {sol.method} solver",
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
