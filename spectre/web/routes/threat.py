"""Threat sweep routes — batch intercept feasibility assessment.

Given one red satellite, computes intercept solutions against operator-
selected targets (blue assets + HRR objects filtered by side and rank)
at multiple manoeuvre epochs (now, apogee, perigee, ascending node,
descending node).  Results are ranked by minimum delta-V.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from spectre.astro.along_track import position_error_km, shift_along_track
from spectre.astro.constants import normalise_regime, regimes_compatible
from spectre.astro.events import EventType, find_orbital_events
from spectre.astro.maneuvers import (
    InterceptSolution,
    bielliptic_intercept,
    hbar_hop_intercept,
    hohmann_intercept,
    lambert_intercept,
    min_time_intercept_wrapper,
    phasing_intercept,
    plane_change_intercept,
    vbar_hop_intercept,
)
from spectre.astro.phase_angle import phase_angle_deg
from spectre.astro.propagator import TLE_ERRORS, TLEOrbit, regime_from_tle, state_to_keplerian
from spectre.data.intel import get_intel, satno_from_tle
from spectre.domain.custody import Custody, CustodyStatus, age_text, assess_custody
from spectre.domain.decide_by import (
    DEFAULT_RESPONSE_H,
    DecideBy,
    decide_by,
    earliest_arrival,
    parse_response_hours,
    withheld,
)
from spectre.domain.manoeuvre_calibration import (
    DEFAULT_SWEEP_BUDGET_M_S,
    classify_posture,
    from_km_s,
    kind_for_method,
    to_km_s,
)
from spectre.domain.models import (
    ThreatActor,
    ThreatAssessment,
    ThreatSweepEntry,
    ThreatTarget,
)
from spectre.domain.normality import BurnNormality
from spectre.domain.pol_assessment import PolAssessment
from spectre.domain.threat_assessment import (
    AccessEvidence,
    ActorVerdict,
    CapabilityEvidence,
    arrives_at_target,
    assess_threat,
    rank_actors,
    warning_time_rank,
)
from spectre.domain.warning_change import (
    BurnLine,
    Status,
    WarningChange,
    burns_in_window,
    compare,
    footer,
    headline,
    least_warning_by_target,
    newest_unconfirmed,
    worst_change,
)
from spectre.web.auth import require_login
from spectre.web.burn_view import DOMINANT_AXIS_FRACTION, dominant_axis
from spectre.web.burn_watch import CHECK_EVERY, BurnWatch, start_watch, watch_view
from spectre.web.deps import render
from spectre.web.elsets import elset_age, limit_hours_for_regime
from spectre.web.format_units import format_tof_label
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import get_session_state
from spectre.web.routes.pol import HeldHistory, burn_verdicts, held_history, history_evidence, reserve_reset_for
from spectre.web.routes.udl import spawn_session_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/threat")

_THREAT_SWEEP_TEMPLATE = "partials/threat_sweep.html"
_BURN_WATCH_TEMPLATE = "partials/burn_watch_note.html"

_RED_COUNTRIES = {"CHN", "RUS", "IRN", "PRK"}

#: Sweeps that may run at once across every operator. Each holds a default
#: executor thread for its whole length, so unbounded sweeps starved every
#: other feature that uses the executor (audit F-235).
_SWEEP_SLOTS = asyncio.Semaphore(2)


@router.get("/red-orbit-info", response_model=None)
async def red_orbit_info(
    request: Request,
    red_sat: str = Query("", description="Red satellite name"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Compute orbital parameters for a red satellite and return a compact info card."""
    state = get_session_state(current_user)

    if not red_sat:
        return HTMLResponse("")

    # Find the red track by stk_name.
    track = None
    for rt in state.red_tracks:
        if rt.stk_name == red_sat:
            track = rt
            break

    if track is None:
        return HTMLResponse("")

    try:
        import math

        from spectre.web.routes.udl import _parse_tle_epoch

        orbit = TLEOrbit(track.tle)

        # Parse TLE epoch.
        lines = [ln.strip() for ln in track.tle.strip().splitlines() if ln.strip()]
        tle_epoch = _parse_tle_epoch(lines[0]) if lines else None
        epoch = tle_epoch or datetime.now(tz=UTC)

        kep = orbit.keplerian_at(epoch)
        sv = orbit.propagate(epoch)

        period_min = kep.period_s / 60.0
        inc_deg = kep.inc
        alt_km = sv.altitude_km
        ecc = kep.ecc
        a_km = kep.a

        # Sub-satellite longitude (approximate from TEME position + GMST).
        from sgp4.api import jday
        jd, fr = jday(epoch.year, epoch.month, epoch.day,
                       epoch.hour, epoch.minute, epoch.second + epoch.microsecond / 1e6)
        # Greenwich Mean Sidereal Time (radians).
        t_ut1 = (jd + fr - 2451545.0) / 36525.0
        gmst_rad = (67310.54841 + (876600 * 3600 + 8640184.812866) * t_ut1
                     + 0.093104 * t_ut1**2 - 6.2e-6 * t_ut1**3)
        gmst_rad = math.radians((gmst_rad % 86400) / 240.0)
        lon_deg = math.degrees(math.atan2(sv.r[1], sv.r[0])) - math.degrees(gmst_rad)
        # Normalise to [-180, 180].
        lon_deg = ((lon_deg + 180) % 360) - 180

        epoch_str = epoch.strftime("%Y-%m-%d %H:%M UTC") if tle_epoch else "—"

        satno = satno_from_tle(track.tle)
        pair = get_intel(satno)

        return render(request, "partials/red_orbit_info.html", {
            "name": track.name,
            "epoch_str": epoch_str,
            "age": elset_age(track.tle, datetime.now(tz=UTC)),
            "data_mode": track.data_mode,
            "lon_deg": lon_deg,
            "inc_deg": inc_deg,
            "period_min": period_min,
            "alt_km": alt_km,
            "ecc": ecc,
            "a_km": a_km,
            "pair": pair,
        })
    except TLE_ERRORS as exc:
        # red_sat is a query parameter and the exception text is built from an
        # operator-supplied element set, so both can carry a newline and forge
        # an audit record (pythonsecurity:S5145).
        logger.warning(
            "red_orbit_info failed for %s: %s", log_safe(red_sat), log_safe(exc)
        )
        # The reason stays in the log, not in the markup. This response bypasses
        # Jinja, so an interpolated exception reaches the browser unescaped,
        # which is the reflected-value defect found at operator.py:296.
        return HTMLResponse(
            '<p class="error-msg" style="font-size:0.75rem">Orbit info unavailable for this track.</p>'
        )


def _interceptor_regime(state: object, red_sat_name: str) -> str | None:
    """Return the canonical orbit regime for a red track, or None if not found."""
    from spectre.astro.constants import classify_orbit_regime
    from spectre.astro.propagator import TLEOrbit

    for track in state.red_tracks:  # type: ignore[attr-defined]
        if track.stk_name != red_sat_name:
            continue
        try:
            orbit = TLEOrbit(track.tle)
            t = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            sv = orbit.propagate(t)
            kep = state_to_keplerian(sv)
            return classify_orbit_regime(kep.a, kep.ecc)
        except TLE_ERRORS:
            return None
    return None


def _hrr_rank(obj: dict[str, Any]) -> int:
    """An HRR object's rank; unranked objects count as rank 0 rather than being dropped."""
    rank = obj.get("rank")
    return 0 if rank is None else rank


def _hrr_side(obj: dict[str, Any]) -> str:
    """'red' for an object of a red country, else 'blue'."""
    country = str(obj.get("country") or "").strip().upper()
    return "red" if country in _RED_COUNTRIES else "blue"


def _hrr_in_regime(obj: dict[str, Any], regime: str | None) -> bool:
    """Whether *obj* is in *regime*; every object is when no regime is given."""
    from spectre.astro.constants import normalise_regime

    return regime is None or normalise_regime(str(obj.get("orbit_regime") or "")) == regime


def _hrr_group_counts(
    state: object,
    regime: str | None = None,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (blue_hrr, red_hrr) where each is [(rank, count), …] sorted by rank.

    If *regime* is provided, only objects whose normalised ``orbit_regime``
    matches are counted — allowing the dropdown to be filtered to objects that
    are actually reachable by the selected interceptor.

    The side, rank and regime rules are the helpers above, shared with
    :func:`_objects_for_group`, which kept its own copy (audit F-136).
    """
    from collections import Counter

    counts: dict[str, Counter[int]] = {"blue": Counter(), "red": Counter()}
    for obj in state.hrr_objects:  # type: ignore[attr-defined]
        if _hrr_in_regime(obj, regime):
            counts[_hrr_side(obj)][_hrr_rank(obj)] += 1
    return sorted(counts["blue"].items()), sorted(counts["red"].items())


def _objects_for_group(
    state: object, side: str, rank: int, regime: str | None = None,
) -> list[dict[str, Any]]:
    """Return HRR objects matching *side* ('blue'|'red'), *rank*, and optionally *regime*."""
    return [
        obj for obj in state.hrr_objects  # type: ignore[attr-defined]
        if _hrr_rank(obj) == rank and _hrr_side(obj) == side and _hrr_in_regime(obj, regime)
    ]


#: Bounds on the manual target list (F-134). It lives in the process-global
#: session state, survives session expiry and rides into every sweep.
_MAX_MANUAL_TARGETS = 50
_MAX_MANUAL_NAME = 64
_MAX_MANUAL_TLE = 300  # a name line and two 69-column lines, with room to spare
_CONFIDENCES = ("CONFIRMED", "HIGH", "MEDIUM", "LOW", "UNCONFIRMED")


def _manual_target_error(existing: list[dict[str, str]], name: str, tle: str, confidence: str) -> str | None:
    """Why a manual target cannot be added, or None when it can."""
    problems = (
        (not name, "Target name is required."),
        (len(name) > _MAX_MANUAL_NAME, f"Target name must be at most {_MAX_MANUAL_NAME} characters."),
        (not tle, "TLE is required."),
        (len(tle) > _MAX_MANUAL_TLE, f"TLE is too long: at most {_MAX_MANUAL_TLE} characters."),
        (confidence not in _CONFIDENCES, f"Confidence must be one of {', '.join(_CONFIDENCES)}."),
        (
            len(existing) >= _MAX_MANUAL_TARGETS and all(e["name"] != name for e in existing),
            f"A sweep takes at most {_MAX_MANUAL_TARGETS} manual targets; remove one first.",
        ),
    )
    first = next((message for failed, message in problems if failed), None)
    if first:
        return first
    try:
        TLEOrbit(tle)
    # BLE001: any parse failure is the operator's to see, with its reason.
    except Exception as exc:  # noqa: BLE001
        return f"Invalid TLE: {exc}"
    return None


@router.post("/add-manual-tle", response_model=None)
async def add_manual_tle(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a manually provided TLE to the session's manual sweep target list."""
    state = get_session_state(current_user)
    form = await request.form()
    name = str(form.get("manual_name") or "").strip()
    tle = str(form.get("manual_tle") or "").strip()
    confidence = str(form.get("manual_confidence") or "MEDIUM").strip().upper()

    error = _manual_target_error(state.manual_sweep_tles, name, tle, confidence)
    if error:
        return render(request, "partials/sweep_manual_tles.html", {
            "manual_tles": state.manual_sweep_tles,
            "error": error,
        })

    # Replace existing entry with same name, otherwise append.
    state.manual_sweep_tles = [e for e in state.manual_sweep_tles if e["name"] != name]
    state.manual_sweep_tles.append({"name": name, "tle": tle, "confidence": confidence})
    state.append_log(f"[THREAT] Manual TLE added: {name} ({confidence})")

    return render(request, "partials/sweep_manual_tles.html", {
        "manual_tles": state.manual_sweep_tles,
        "error": None,
    })


@router.post("/remove-manual-tle", response_model=None)
async def remove_manual_tle(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Remove a manual TLE entry from the session."""
    state = get_session_state(current_user)
    form = await request.form()
    name = str(form.get("manual_name") or "").strip()
    state.manual_sweep_tles = [e for e in state.manual_sweep_tles if e["name"] != name]
    return render(request, "partials/sweep_manual_tles.html", {
        "manual_tles": state.manual_sweep_tles,
        "error": None,
    })


@router.get("/target-config", response_model=None)
async def target_config(
    request: Request,
    red_sat: str = Query("", description="Selected interceptor stk_name — used to filter by regime"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the sweep target dropdown filtered to the interceptor's orbital regime."""
    state = get_session_state(current_user)
    regime = _interceptor_regime(state, red_sat) if red_sat else None
    blue_hrr, red_hrr = _hrr_group_counts(state, regime=regime)
    return render(request, "partials/sweep_target_config.html", {
        "has_udl": bool(state.udl_username),
        "has_hrr": bool(state.hrr_objects),
        "blue_hrr": blue_hrr,
        "red_hrr": red_hrr,
        "interceptor_regime": regime,
        "interceptor_name": red_sat,
        "manual_tles": state.manual_sweep_tles,
    })


async def _prefetch_group_tle(
    state: object, satno_str: str, sem: asyncio.Semaphore, window_hours: float,
) -> bool:
    """Bring one HRR object's element set up to date, history included.

    Lifted whole out of ``fetch_targets``, where it was a closure counting
    into two ``nonlocal`` tallies three levels deep. True means the object
    ends the call holding a usable element set, which is what the status
    panel counts as fetched: one that already held a REAL one counts without
    a call being made.

    The credential check is kept even though the caller has already made it.
    Session state is shared, and dropping a guard because it looks redundant
    is how a concurrent disconnect turns into a request for an empty password.
    """
    from spectre.web.routes.udl import fetch_tle_for_satno, fetch_tle_history_for_satno

    if not _needs_live_tle(state, satno_str):
        return True
    if not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]
        return False
    async with sem:
        result = await fetch_tle_for_satno(
            int(satno_str), state.udl_username, state.udl_password,  # type: ignore[attr-defined]
            data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]
            source=state.udl_tle_source,  # type: ignore[attr-defined]
        )
        if not result:
            return False
        tle, dm = result
        state.hrr_tle_cache[satno_str] = tle  # type: ignore[attr-defined]
        state.hrr_tle_data_mode[satno_str] = dm  # type: ignore[attr-defined]
        # Also fetch multi-provider history for clustering.
        history = await fetch_tle_history_for_satno(
            int(satno_str), state.udl_username, state.udl_password,  # type: ignore[attr-defined]
            window_hours=window_hours,
            data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]
            source=state.udl_tle_source,  # type: ignore[attr-defined]
        )
        if len(history) > 1:
            state.hrr_tle_multiset[satno_str] = history  # type: ignore[attr-defined]
    return True


@router.post("/fetch-targets", response_model=None)
async def fetch_targets(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Pre-fetch TLEs for a selected HRR target group (side:rank)."""
    state = get_session_state(current_user)
    form = await request.form()
    tgt_group = str(form.get("tgt_group") or "").strip()

    if not tgt_group:
        return HTMLResponse("")

    # Bound before the branch. Only the else: suite below assigns them, but the
    # log line at the end of this function reads both, so the "all" path raised
    # UnboundLocalError and returned HTTP 500 after every TLE had been fetched.
    side = ""
    rank: int | None = None

    if tgt_group == "all":
        objects = list(state.hrr_objects)
    elif ":" not in tgt_group:
        return HTMLResponse("")
    else:
        side, rank_str = tgt_group.split(":", 1)
        try:
            rank = int(rank_str)
        except ValueError:
            return render(request, "partials/sweep_fetch_status.html", {
                "error": f"Invalid rank: {rank_str}", "fetched": None, "total": 0, "failed": 0,
            })
        objects = _objects_for_group(state, side, rank)

    if not objects:
        return render(request, "partials/sweep_fetch_status.html", {
            "error": "No HRR objects found for selected group.",
            "fetched": None, "total": 0, "failed": 0,
        })

    if not state.udl_username or not state.udl_password:
        return render(request, "partials/sweep_fetch_status.html", {
            "error": "Not connected to UDL — cannot fetch TLEs.",
            "fetched": None, "total": 0, "failed": 0,
        })

    from spectre.config.constants import TLE_CLUSTERING

    # Clear the multi-TLE cache so this fetch starts clean; prevents stale TLEs
    # from a prior group selection contaminating clustering for the new group.
    state.hrr_tle_multiset.clear()

    sem = asyncio.Semaphore(10)
    _window_hours: float = float(TLE_CLUSTERING.get("fetch_window_hours", 24))

    satnos = [str(o.get("satno") or "").strip() for o in objects]
    satnos = [s for s in satnos if s]
    # Exactly one of fetched/failed was counted per object before, so the two
    # tallies still add up to the total.
    outcomes = await asyncio.gather(*[
        _prefetch_group_tle(state, s, sem, _window_hours) for s in satnos
    ])
    fetched = sum(1 for ok in outcomes if ok)
    failed = len(outcomes) - fetched

    total = len(satnos)
    group_label = f"{side.title()} HRR Rank {rank}" if rank is not None else "all HRR objects"
    state.append_log(
        f"[THREAT] Pre-fetched {group_label}: "
        f"{fetched}/{total} TLEs ({failed} failed)"
    )

    return render(request, "partials/sweep_fetch_status.html", {
        "error": None, "fetched": fetched, "total": total, "failed": failed,
    })


# Map astro EventType → sweep location label.
_EVENT_TO_LOCATION = {
    EventType.APOGEE: "apogee",
    EventType.PERIGEE: "perigee",
    EventType.ASCENDING_NODE: "asc_node",
    EventType.DESCENDING_NODE: "desc_node",
}



def _needs_live_tle(state: object, satno: str) -> bool:
    """True when *satno* has no element set, or only a synthetic one.

    The bundled bootstrap watchlist seeds the cache so the sweep and the screen
    run before anyone connects to UDL. Those element sets are SYNTHETIC. A
    plain "is it cached" check would treat them as satisfied and never replace
    them, so connecting to UDL would change nothing and the operator would
    keep reading generated orbits believing they were tracked.
    """
    if satno not in state.hrr_tle_cache:  # type: ignore[attr-defined]
        return True
    mode = state.hrr_tle_data_mode.get(satno, "REAL")  # type: ignore[attr-defined]
    return str(mode) != "REAL"


def _build_target_list(
    state: object,
    side: str,
    rank: int | None,
    exclude_satno: str | None = None,
) -> list[ThreatTarget]:
    """Build a target list from HRR objects matching *side* and *rank*.

    Parameters:
        side: ``'blue'``, ``'red'``, or ``'all'`` — HRR side to include.
        rank: HRR rank level (0–5), or ``None`` when *side* is ``'all'``.
        exclude_satno: SATNO string to omit (the interceptor itself).
    """
    targets: list[ThreatTarget] = []

    raw_objects: list[dict[str, Any]]
    if side == "all":
        raw_objects = list(state.hrr_objects)  # type: ignore[attr-defined]
    else:
        raw_objects = _objects_for_group(state, side, rank or 0)

    for obj in raw_objects:
        satno = str(obj.get("satno") or "").strip()
        if exclude_satno and satno == exclude_satno:
            continue
        name = str(obj.get("name") or satno or "HRR-?").strip()
        obj_rank = obj.get("rank")
        targets.append(ThreatTarget(
            target_name=name,
            target_satno=satno,
            target_source="hrr",
            hrr_rank=obj_rank,
        ))

    return targets


# Apogee, perigee and the nodes are named only where they mean something (red
# team finding 3). Speed at perigee exceeds speed at apogee by about twice the
# eccentricity, so below 0.005 the difference is under 1 per cent; on a
# station-kept GEO object (e = 0.00016) the two apsides are 13 km apart on a
# 42,164 km orbit. A station-kept GEO object also holds its inclination to a
# few hundredths of a degree, where the equatorial nodes move with the noise
# in the element set. Below either bar the epoch is a time sample across the
# next day, and is labelled as one. Both bars are tuned, not sourced.
_APSIDES_NAMED_FROM_ECC: float = 0.005
_NODES_NAMED_FROM_INC_DEG: float = 0.5
_APSIDES = frozenset({"apogee", "perigee"})
_NODES = frozenset({"asc_node", "desc_node"})


def _shape_of(tle: str) -> tuple[float, float]:
    """Eccentricity and inclination (degrees) of *tle*."""
    sat = TLEOrbit(tle)._sat  # noqa: SLF001 - the parsed record already held, not a second parse
    return float(sat.ecco), math.degrees(float(sat.inclo))


def _sample_label(epoch: datetime, now: datetime) -> str:
    return f"now +{(epoch - now).total_seconds() / 3600.0:.1f} h"


def _compute_epochs(red_tle: str, now: datetime) -> list[tuple[str, datetime]]:
    """Compute the sweep epochs for the red satellite.

    Each is labelled by the event it was found at only where that event means
    something for this orbit; otherwise by its time after now.
    """
    epochs: list[tuple[str, datetime]] = [("now", now)]
    ecc, inc_deg = _shape_of(red_tle)

    events = find_orbital_events(red_tle, now, now + timedelta(hours=24), max_per_type=1)
    for ev in events:
        loc = _EVENT_TO_LOCATION.get(ev.event_type)
        if not loc:
            continue
        unnamed = (loc in _APSIDES and ecc < _APSIDES_NAMED_FROM_ECC) or (
            loc in _NODES and inc_deg < _NODES_NAMED_FROM_INC_DEG)
        epochs.append((_sample_label(ev.epoch, now) if unnamed else loc, ev.epoch))

    return epochs


def _epoch_note(red_tle: str) -> str:
    """Why some burn times carry no apsis or node name, or empty when all do."""
    ecc, inc_deg = _shape_of(red_tle)
    unnamed = []
    if ecc < _APSIDES_NAMED_FROM_ECC:
        unnamed.append(f"its eccentricity ({ecc:.4f}) is too small for apogee and perigee to differ meaningfully")
    if inc_deg < _NODES_NAMED_FROM_INC_DEG:
        unnamed.append(f"its inclination ({inc_deg:.2f}\u00b0) is too small for its nodes to be well defined")
    if not unnamed:
        return ""
    return (
        "Burn times are samples across the next day, not chosen points on the orbit: "
        + " and ".join(unnamed) + ". The phase angle to the target is what differs between them."
    )


def _swept_target_tle(state: object, target: ThreatTarget) -> str | None:
    """The element set a swept target was flown with, blue assets included."""
    return _target_tle(state, target) or state.tle_of(target.target_name)  # type: ignore[attr-defined]


def _phase_label(red_tle: str, target_tle: str | None, epoch: datetime) -> str:
    """Where the target sits relative to the interceptor at the burn (SPC-004)."""
    if not target_tle:
        return ""
    try:
        red = TLEOrbit(red_tle).propagate(epoch)
        target = TLEOrbit(target_tle).propagate(epoch)
        angle = phase_angle_deg(red.r, red.v, target.r)
    except TLE_ERRORS as exc:  # ValueError among them, which phase_angle_deg raises
        logger.info("Phase angle not computed: %s", log_safe(exc))
        return ""
    side = "ahead of" if angle >= 0 else "behind"
    return f"{abs(angle):.1f}\u00b0 {side} the interceptor"


# PLR0913, PLR0917: one parameter per column of the row it builds.
def _sol_to_entry(  # noqa: PLR0913, PLR0917
    sol: InterceptSolution,
    target: ThreatTarget,
    epoch: datetime,
    location: str,
    method_name: str,
    regime: str = "",
) -> ThreatSweepEntry:
    """Convert an InterceptSolution to a ThreatSweepEntry.

    THIS IS THE UNIT BOUNDARY for the sweep. ``InterceptSolution`` carries km/s
    because the astro package works in km and km/s (MU_EARTH is in km^3/s^2 and
    SGP4 returns km). ``ThreatSweepEntry`` carries m/s because that is what the
    operator reads and what the manoeuvre calibration is expressed in.

    ``from_km_s`` is applied here and nowhere downstream. A second conversion
    anywhere below this line puts a value out by a factor of a million.
    """
    tof_hours = 0.0
    dv_pro = 0.0
    dv_nor = 0.0
    dv_rad = 0.0
    if sol.burns:
        tof_s = (sol.arrival_epoch - sol.burns[0].epoch).total_seconds()
        tof_hours = tof_s / 3600.0
        for b in sol.burns:
            dv_pro += b.dv_prograde
            dv_nor += b.dv_normal
            dv_rad += b.dv_radial
    return ThreatSweepEntry(
        target=target,
        burn_epoch=epoch,
        burn_location=location,
        delta_v_m_s=from_km_s(abs(sol.total_delta_v)),
        tof_hours=tof_hours,
        dv_prograde=from_km_s(dv_pro),
        dv_normal=from_km_s(dv_nor),
        dv_radial=from_km_s(dv_rad),
        method=method_name,
        regime=regime,
        posture_label=classify_posture(
            from_km_s(abs(sol.total_delta_v)), regime, kind_for_method(method_name),
        ).posture_label,
        arrives=arrives_at_target(method_name),
    )


# Verdict colours. MINIMAL is new: it is the band an object lands in when the
# geometry is permissive but the object cannot fly it, which previously had no
# way of being expressed at all.
#: A burn vector shorter than this is numerically zero, so its direction is
#: undefined and the component percentages below would divide by noise.
_ZERO_VECTOR_M_S: float = 1e-12


#: (text colour, panel wash) per band, as design tokens rather than hex.
#: Raw hex here did not move when the operator picked Steel (Light), so every
#: band failed WCAG AA as text on the light surfaces. The values now live in
#: spectre/web/static/spectre-theme.css, which restates them per theme; the
#: badge fill that carries white text is the .spectre-band-* class there.
_BAND_COLOURS: dict[str, tuple[str, str]] = {
    "CRITICAL": ("var(--spectre-status-critical)", "rgba(var(--spectre-status-critical-rgb), 0.06)"),
    "HIGH":     ("var(--spectre-status-high)",     "rgba(var(--spectre-status-high-rgb), 0.06)"),
    "MEDIUM":   ("var(--spectre-status-medium)",   "rgba(var(--spectre-status-medium-rgb), 0.06)"),
    "LOW":      ("var(--spectre-status-low)",      "rgba(var(--spectre-status-low-rgb), 0.06)"),
    "MINIMAL":  ("var(--spectre-status-minimal)",  "rgba(var(--spectre-status-minimal-rgb), 0.06)"),
}


_SENTENCE_END = re.compile(r"\.(?:\s|$)")


def _refusal_reason(exc: BaseException) -> str:
    """Turn a solver refusal into a sentence worth showing.

    A refusal is information: "this geometry is degenerate" tells the analyst
    something real. An empty result tells them nothing, and looks identical to
    a method that was never tried.
    """
    text = str(exc).strip()
    if not text:
        return f"refused ({type(exc).__name__})"
    # A full stop ends a sentence only before whitespace or the end. Splitting
    # on every "." cut solver figures short: "transfer angle 179.9876 deg"
    # was shown as "transfer angle 179" (audit F-058).
    first_sentence = _SENTENCE_END.split(text, maxsplit=1)[0].split(";")[0].strip()
    return first_sentence[:160] if first_sentence else text[:160]


@dataclass(frozen=True)
class _SweepRequest:
    """Everything one target's fan-out needs, as one value.

    The fan-out previously took seven positional parameters and repeated the
    same nine-line block eight times, once per solver. The duplication was not
    cosmetic: the per-method budget check, the refusal recording and the entry
    construction all had to be kept in step by hand across eight copies, and a
    units change had to be applied correctly to every one of them.
    """

    red_tle: str
    target_tle: str
    target: ThreatTarget
    max_dv_m_s: float
    regime: str


#: The eight methods, as (name, solver, extra keyword arguments).
#:
#: ``manoeuvre_start`` is supplied per epoch. ``max_delta_v`` for min_time is
#: filled in at call time because it depends on the operator's budget.
_SWEEP_METHODS: tuple[tuple[str, Any, dict[str, Any]], ...] = (
    ("hohmann", hohmann_intercept, {"coast_s": 0.0}),
    ("lambert", lambert_intercept, {"tof_s": 21600.0, "coast_s": 0.0}),
    ("bielliptic", bielliptic_intercept, {"coast_s": 0.0}),
    ("phasing", phasing_intercept, {"n_revolutions": 1}),
    ("plane_change", plane_change_intercept, {"coast_s": 0.0}),
    ("min_time", min_time_intercept_wrapper, {"coast_s": 0.0}),
    ("vbar_hop", vbar_hop_intercept, {"n_hops": 3, "coast_s": 0.0}),
    ("hbar_hop", hbar_hop_intercept, {"n_hops": 3, "coast_s": 0.0}),
)


def _sweep_all_methods(
    request: _SweepRequest,
    epochs: list[tuple[str, datetime]],
    refusals: dict[str, str] | None = None,
) -> list[ThreatSweepEntry]:
    """Run every applicable transfer method for one target across all epochs.

    *refusals* collects, per method, why it produced nothing. Every method used
    to be wrapped in a bare ``except Exception: pass``, so the analyst could not
    tell "tried and not viable" from "threw", and could not see that a method
    had been attempted at all.

    That asymmetry mattered in the dangerous direction. The cheapest options are
    the ones most likely to be refused: a degenerate Lambert geometry is the
    near-180-degree GEO phasing case, and a phasing orbit too aggressive to fly
    is the short-notice one. Refusals cluster on the fast end, so dropping them
    silently biased the sweep towards under-reporting the quickest approaches.
    """
    entries: list[ThreatSweepEntry] = []
    notes: dict[str, str] = refusals if refusals is not None else {}
    budget = request.max_dv_m_s

    for location, epoch in epochs:
        for name, solver, extra in _SWEEP_METHODS:
            kwargs = dict(extra)
            if name == "min_time":
                kwargs["max_delta_v"] = to_km_s(budget)  # astro takes km/s
            try:
                sol = solver(
                    red_tle=request.red_tle,
                    blue_tle=request.target_tle,
                    manoeuvre_start=epoch,
                    **kwargs,
                )
                # plane_change can report a signed figure; cost is a magnitude.
                cost_m_s = from_km_s(abs(sol.total_delta_v))
                if cost_m_s <= budget:
                    entries.append(_sol_to_entry(
                        sol, request.target, epoch, location, name, request.regime,
                    ))
                else:
                    notes.setdefault(name, f"at {location}: exceeds the {budget:g} m/s budget")
            # BLE001: one refusal is recorded and the sweep continues.
            except Exception as exc:  # noqa: BLE001
                notes.setdefault(name, f"at {location}: {_refusal_reason(exc)}")

    # A method that solved at any epoch did produce a solution for this
    # target; listing it as refused contradicted the table beside it (F-125).
    for solved in {e.method for e in entries}:
        notes.pop(solved, None)
    return entries


def _red_capability(
    red_satno: str | None, history: PolAssessment | None = None, span_days: float | None = None,
) -> CapabilityEvidence:
    """Assemble what is known about the red object's ability to act.

    The assessed intelligence record, and, when the object's element-set
    history is held, what its behaviour shows: propellant used, discretionary
    reserve left, the behavioural anomaly score and the burns observed
    (SPC-002). Without a history those stay None and the verdict lists them
    as missing rather than assuming either way.
    """
    record = get_intel(red_satno) if red_satno else None
    base = CapabilityEvidence(
        intel_threat_level=record.get("threat_level"),
        operational_status=record.get("status"),
    ) if record else CapabilityEvidence()
    if history is None:
        return base
    propellant = history.propellant
    return replace(
        base,
        propellant_used_pct=propellant.propellant_used_pct,
        discretionary_remaining_m_s=propellant.discretionary_remaining_m_s,
        discretionary_max_m_s=propellant.discretionary_max_m_s,
        anomaly_score=history.anomaly.overall if history.anomaly else None,
        manoeuvres_observed=len(history.manoeuvres),
        history_span_days=span_days,
    )


def _burn_direction_breakdown(
    pro: float, nor: float, rad: float,
) -> tuple[float, float, float, str]:
    """Split a burn into per-axis percentages and name its dominant axis.

    Lifted out of ``_compute_worst_coa`` whole. The comparison stays written
    as "greater than zero" rather than inverted into a guard clause: a NaN
    component must fall to the "Unknown" branch exactly as it did before, and
    an inverted test would send it down the dividing path instead.

    Returns ``(pro_pct, nor_pct, rad_pct, direction)``.
    """
    import math

    total_vec = math.sqrt(pro ** 2 + nor ** 2 + rad ** 2)
    if total_vec > _ZERO_VECTOR_M_S:
        return (
            round(abs(pro) / total_vec * 100.0, 1),
            round(abs(nor) / total_vec * 100.0, 1),
            round(abs(rad) / total_vec * 100.0, 1),
            dominant_axis(pro, nor, rad, DOMINANT_AXIS_FRACTION * total_vec),
        )
    return (0.0, 0.0, 0.0, "Unknown")


def _compute_worst_coa(
    entries: list[ThreatSweepEntry],
    capability: CapabilityEvidence | None = None,
    max_dv_m_s: float = DEFAULT_SWEEP_BUDGET_M_S,
) -> dict[str, Any] | None:
    """Identify and describe the most dangerous course of action from sweep entries.

    "Most dangerous" now means the one that leaves the least warning time among
    the intercepts that can actually be flown, not simply the cheapest. Warning
    time is what a defender spends: an intercept costing 450 m/s arriving in
    35 minutes is a far harder problem than one costing 120 m/s over 40 hours,
    and ranking on delta-V alone called the second the greater threat.

    *capability* carries what is known about the red object's ability to act.
    Without it the verdict is geometry alone, which is what this function used
    to be while calling itself an adversary capability assessment.

    Returns a Jinja-safe dict, or ``None`` if *entries* is empty.
    """
    # Only a solution that reaches the target leaves a warning time to rank.
    arriving = [e for e in entries if e.arrives]
    if not arriving:
        return None

    # The entry that leaves the least warning time among the feasible ones.
    worst = min(
        arriving,
        key=lambda e: warning_time_rank(e.delta_v_m_s, e.tof_hours, max_dv_m_s),
    )
    dv = worst.delta_v_m_s

    assessment = assess_threat(
        AccessEvidence(
            best_delta_v_m_s=dv,
            time_to_arrival_hours=worst.tof_hours,
            method=worst.method,
            regime=worst.regime,
        ),
        capability or CapabilityEvidence(),
    )
    threat_level = assessment.verdict_label
    threat_color, threat_bg = _BAND_COLOURS.get(
        threat_level,
        ("var(--spectre-status-unknown)", "rgba(var(--spectre-status-unknown-rgb), 0.06)"),
    )

    # Burn direction breakdown
    pro_pct, nor_pct, rad_pct, direction = _burn_direction_breakdown(
        worst.dv_prograde, worst.dv_normal, worst.dv_radial,
    )

    tof_label = format_tof_label(worst.tof_hours)

    dv_budget_pct = round(min(100.0, dv / max_dv_m_s * 100.0), 1) if max_dv_m_s > 0 else 0.0

    # Metres per second, whole numbers. Measured against TLE uncertainty a
    # co-orbital GEO intercept is good to about 1 m/s at a realistic
    # few-kilometre position error, so decimals here would be noise presented
    # as precision. Published figures are written the same way: the SJ-21 tow
    # of Beidou-2 G2 is "about 60 m/s".
    summary = (
        f"Least warning: {worst.method.upper()} transfer to "
        f"{worst.target.target_name} arriving in {tof_label}, costing "
        f"{dv:.0f} m/s \u0394V, burning at {worst.burn_location}. "
        f"Dominant burn axis: {direction}. {assessment.rationale}"
    )

    return {
        # The two findings, kept separately visible. One word carrying both is
        # how the geometric verdict came to contradict the intelligence panel
        # beside it.
        "access_level": assessment.access_label,
        "capability_level": assessment.capability_label,
        "assessment_confidence": assessment.confidence,
        "assessment_rationale": assessment.rationale,
        "inputs_used": assessment.inputs_used,
        "inputs_missing": assessment.inputs_missing,
        "warning_time_hours": round(assessment.warning_time_hours, 2),
        "budget_m_s": max_dv_m_s,
        "posture_label": assessment.posture_label,
        "posture_rationale": assessment.posture_rationale,
        "posture_basis": assessment.posture_basis,
        "undeliverable_reason": assessment.undeliverable_reason,
        "target_name": worst.target.target_name,
        "target_satno": worst.target.target_satno or "",
        "method": worst.method,
        "dv": round(dv, 4),
        "tof_label": tof_label,
        "tof_hours": round(worst.tof_hours, 2),
        "burn_location": worst.burn_location,
        "burn_epoch": worst.burn_epoch.strftime("%Y-%m-%d %H:%M UTC"),
        "threat_level": threat_level,
        "threat_color": threat_color,
        "threat_bg": threat_bg,
        "direction": direction,
        "pro_pct": pro_pct,
        "nor_pct": nor_pct,
        "rad_pct": rad_pct,
        "dv_budget_pct": dv_budget_pct,
        "summary": summary,
    }


def _group_entries(entries: list[ThreatSweepEntry]) -> list[dict[str, Any]]:
    """Group flat entries by target name for the collapsed-row UI.

    Returns a list of dicts sorted by best (lowest) delta-V, each containing:
      target, best_dv, best_method, profile_count, children (list of
      {flat_idx, entry} dicts sorted by delta-V).
    """
    from collections import OrderedDict

    buckets: OrderedDict[str, list[tuple[int, ThreatSweepEntry]]] = OrderedDict()
    for flat_idx, entry in enumerate(entries):
        key = entry.target.target_name
        buckets.setdefault(key, []).append((flat_idx, entry))

    groups: list[dict[str, Any]] = []
    for items in buckets.values():
        items.sort(key=lambda t: (not t[1].arrives, t[1].tof_hours, t[1].delta_v_m_s))
        best = items[0][1]
        groups.append({
            "target": best.target,
            "best_dv": best.delta_v_m_s,
            "best_posture": best.posture_label,
            "best_method": best.method,
            "best_location": best.burn_location,
            "best_tof": best.tof_hours,
            "best_arrives": best.arrives,
            "profile_count": len(items),
            "children": [{"flat_idx": idx, "entry": e} for idx, e in items],
            "osint": get_intel(best.target.target_satno or None),  # key stays 'osint' — threat_sweep.html reads group.osint
        })

    # Ranked on warning time, matching the headline. Sorting these on cost while
    # the banner above ranked on time made the two disagree about which target
    # mattered most, on the same screen.
    groups.sort(key=lambda g: (g["best_tof"], g["best_dv"]))
    return groups



# ─────────────────────────────────────────────────────────────────────────────
# Blue asset screening: one asset, every candidate actor
# ─────────────────────────────────────────────────────────────────────────────
#
# The sweep asks "what can this object reach". Screening asks "who threatens
# this asset, and which of them matters", which is a different question: the
# analyst is being told which object to brief.
#
# It is also the first time the composite verdict does any discriminating. In
# the red-out sweep capability is one constant across every entry, because
# there is one red object. Here it varies per actor, and it is the field that
# separates the two objects worth briefing from the eighteen that are not.
#
# Measured cost: 53.8 ms per actor, of which 81 per cent is the 24-hour event
# scan at 30-second steps. 25 actors is about 1.35 s and 50 about 2.7 s, which
# is why no feasibility pre-screen was built: it would be an optimisation with
# nothing to optimise, and a place for a defect to hide.

#: Hard cap on candidate actors, from the measurement above. 60 actors is
#: roughly 3.2 s, which is still interactive. Truncation is always reported.
_MAX_SCREEN_ACTORS: int = 60


def _resolve_hrr_tle(state: object, satno: str) -> str | None:
    """Look up an HRR object's element set from the session cache.

    ``_find_tle`` searches the operator's own blue assets and red tracks, which
    is the right lookup for the red-out sweep. Screening works entirely from
    the HRR watchlist, where both the asset and every candidate actor live in
    ``hrr_tle_cache`` keyed by satno, so neither end is reachable through it.
    """
    if not satno:
        return None
    cached = state.hrr_tle_cache.get(str(satno).strip())  # type: ignore[attr-defined]
    return str(cached) if cached else None


def _regime_of_tle(tle: str) -> str:
    """Canonical regime for an element set, or "" when it cannot be read."""
    try:
        return regime_from_tle(tle)
    # BLE001: a malformed element set must not kill the screen.
    except Exception:  # noqa: BLE001
        return ""


def _build_actor_list(state: object, asset_regime: str) -> list[ThreatActor]:
    """Candidate threat actors for an asset in *asset_regime*.

    Red HRR objects whose regime could physically reach the asset's. The filter
    is ``regimes_compatible`` rather than equality on purpose: a GTO or HEO
    object crosses both the LEO and GEO belts, so excluding it would be a false
    negative on exactly the case worth catching.
    """
    actors: list[ThreatActor] = []
    for obj in state.hrr_objects:  # type: ignore[attr-defined]
        country = str(obj.get("country") or "").strip().upper()
        if country not in _RED_COUNTRIES:
            continue
        satno = str(obj.get("satno") or "").strip()
        if not satno:
            continue
        obj_regime = normalise_regime(str(obj.get("orbit_regime") or ""))
        if asset_regime and obj_regime and not regimes_compatible(asset_regime, obj_regime):
            continue
        actors.append(ThreatActor(
            actor_name=str(obj.get("name") or satno).strip(),
            actor_satno=satno,
            country=country,
            hrr_rank=obj.get("rank"),
            regime=obj_regime,
        ))
    return actors


# PLR0913, PLR0917: the inputs of one actor's assessment.
def _screen_one_actor(  # noqa: PLR0913, PLR0917
    actor: ThreatActor,
    actor_tle: str,
    asset_tle: str,
    asset: ThreatTarget,
    now: datetime,
    budget_m_s: float,
    refusals: list[tuple[str, str, str]],
) -> tuple[ActorVerdict | None, list[ThreatSweepEntry]]:
    """Assess one candidate actor against the asset.

    Epochs come from the ACTOR's element set, because the actor is the object
    that would burn. That is why the cost scales with the number of candidates
    rather than being computed once.
    """
    actor_regime = actor.regime or _regime_of_tle(actor_tle)
    notes: dict[str, str] = {}
    epochs = _compute_epochs(actor_tle, now)
    entries = _sweep_all_methods(
        _SweepRequest(
            red_tle=actor_tle,
            target_tle=asset_tle,
            target=asset,
            max_dv_m_s=budget_m_s,
            regime=actor_regime,
        ),
        epochs,
        refusals=notes,
    )
    refusals.extend((actor.actor_name, method, reason) for method, reason in sorted(notes.items()))
    for entry in entries:
        entry.actor = actor
    if not entries:
        return (None, [])

    arriving = [e for e in entries if e.arrives]
    if not arriving:
        return (None, entries)
    best = min(
        arriving,
        key=lambda e: warning_time_rank(e.delta_v_m_s, e.tof_hours, budget_m_s),
    )
    assessment = assess_threat(
        AccessEvidence(
            best_delta_v_m_s=best.delta_v_m_s,
            time_to_arrival_hours=best.tof_hours,
            method=best.method,
            regime=actor_regime,
        ),
        _red_capability(actor.actor_satno),
    )
    verdict = ActorVerdict(
        actor_name=actor.actor_name,
        actor_satno=actor.actor_satno,
        assessment=assessment,
        warning_hours=best.tof_hours,
        delta_v_m_s=best.delta_v_m_s,
        method=best.method,
        country=actor.country,
    )
    return (verdict, entries)

class _TargetGroup(NamedTuple):
    """A parsed ``tgt_group`` form value, or the reason it could not be read.

    Lifted out of the sweep handler, which carried 122 statements across 22
    branches. Input parsing and its error paths are a third of that and have
    nothing to do with running a sweep, so they are easier to read and to test
    on their own.
    """

    side: str = ""
    rank: int | None = None
    group_label: str = ""
    error: str = ""


def _parse_target_group(tgt_group: str) -> _TargetGroup:
    """Read the operator's target-group selection.

    Accepts "none" or empty (manual targets only), "all", or "side:rank".
    """
    if not tgt_group or tgt_group == "none":
        return _TargetGroup(side="none", rank=None, group_label="Manual only")
    if tgt_group == "all":
        return _TargetGroup(side="all", rank=None, group_label="All HRR")
    if ":" not in tgt_group:
        return _TargetGroup(error=f"Invalid target group: {tgt_group}")
    side, rank_str = tgt_group.split(":", 1)
    try:
        rank = int(rank_str)
    except ValueError:
        return _TargetGroup(error=f"Invalid target group rank: {rank_str}")
    return _TargetGroup(
        side=side, rank=rank, group_label=f"{side.title()} HRR Rank {rank}",
    )


def _validate_manual_red_tle(raw: str, errors: list[str]) -> str | None:
    """Accept a pasted red element set, or record why it was rejected.

    A rejected override is reported and the registered track is used instead,
    so a typo in the paste box never quietly becomes a sweep of a different
    object than the operator named.
    """
    if not raw:
        return None
    try:
        TLEOrbit(raw)  # validate
    # BLE001: operator input, reported not raised.
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Manual red TLE invalid ({exc}) — using registered TLE instead.")
        return None
    return raw


def _append_manual_targets(
    state: object, targets: list[ThreatTarget],
) -> dict[str, str]:
    """Append the session's manual sweep targets and return their element sets.

    The returned mapping is keyed by target NAME, not by satellite number: a
    pasted element set may carry no number the catalogue recognises, and the
    name is the only handle the sweep has on it.
    """
    manual_tle_by_name: dict[str, str] = {}
    for manual in state.manual_sweep_tles:  # type: ignore[attr-defined]
        name = manual["name"]
        tle = manual["tle"]
        confidence = manual.get("confidence", "")
        # satno_from_tle answers None for a number it cannot read (Alpha-5,
        # for one); str() made that "None", which then looked fetchable.
        number = satno_from_tle(tle) if tle else None
        satno = str(number) if number is not None else ""
        targets.append(ThreatTarget(
            target_name=name,
            target_satno=satno,
            target_source="manual",
            hrr_rank=None,
            confidence=confidence,
        ))
        manual_tle_by_name[name] = tle
    return manual_tle_by_name


#: Hard cap on one sweep, against runaway compute on a large group.
_MAX_SWEEP_TARGETS = 100


def _cap_targets(
    state: object,
    targets: list[ThreatTarget],
    manual_tle_by_name: dict[str, str],
    red_regime: str,
    errors: list[str],
) -> list[ThreatTarget]:
    """Order, filter and cap the sweep's targets, naming whatever is left out.

    Manual targets lead, because the operator pasted them on purpose; they
    used to come last, so the cap dropped them first and silently (F-126).
    A target whose cached element set is in an incompatible regime is
    skipped here rather than after the cap, so it no longer takes a slot.
    """
    ordered = [t for t in targets if t.target_source == "manual"]
    ordered += [t for t in targets if t.target_source != "manual"]
    kept: list[ThreatTarget] = []
    for target in ordered:
        tle = (
            manual_tle_by_name.get(target.target_name) if target.target_source == "manual"
            else state.hrr_tle_cache.get(target.target_satno)  # type: ignore[attr-defined]
        )
        regime = _regime_of_tle(tle) if tle else ""
        if regime and not regimes_compatible(red_regime, regime):
            errors.append(
                f"{target.target_name}: skipped — {red_regime} red vs {regime} target (regime mismatch)"
            )
            continue
        kept.append(target)
    if len(kept) > _MAX_SWEEP_TARGETS:
        dropped = ", ".join(t.target_name for t in kept[_MAX_SWEEP_TARGETS:])
        errors.append(f"Target list capped at {_MAX_SWEEP_TARGETS}; not swept: {dropped}.")
        kept = kept[:_MAX_SWEEP_TARGETS]
    return kept


async def _fetch_missing_target_tles(
    state: object, targets: list[ThreatTarget], errors: list[str],
) -> None:
    """Last-chance fetch for targets with no element set, or only a synthetic one.

    A no-op without UDL credentials, which is the normal case on a fresh
    instance running from the bundled bootstrap watchlist. A failed fetch is
    recorded against the target rather than dropped.
    """
    # A manual target flies the operator's pasted set, looked up by name, so
    # a fetch could only overwrite a cache entry nothing reads.
    missing = [
        t for t in targets
        if t.target_source != "manual" and t.target_satno and _needs_live_tle(state, t.target_satno)
    ]
    if not missing or not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]
        return

    from spectre.web.routes.udl import fetch_tle_for_satno

    sem = asyncio.Semaphore(10)
    udl_user: str = state.udl_username  # type: ignore[attr-defined]
    udl_pass: str = state.udl_password  # type: ignore[attr-defined]

    async def _fetch_one(t: ThreatTarget) -> None:
        async with sem:
            _result = await fetch_tle_for_satno(
                int(t.target_satno), udl_user, udl_pass,
                data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]
                source=state.udl_tle_source,  # type: ignore[attr-defined]
            )
            if _result:
                tle, dm = _result
                state.hrr_tle_cache[t.target_satno] = tle  # type: ignore[attr-defined]
                state.hrr_tle_data_mode[t.target_satno] = dm  # type: ignore[attr-defined]
            else:
                errors.append(f"TLE fetch failed for {t.target_name} ({t.target_satno})")

    # return_exceptions: one target's failure is recorded, not a 500 for all.
    outcomes = await asyncio.gather(*[_fetch_one(t) for t in missing], return_exceptions=True)
    errors.extend(
        f"TLE fetch failed for {t.target_name} ({t.target_satno}): {_refusal_reason(outcome)}"
        for t, outcome in zip(missing, outcomes, strict=True)
        if isinstance(outcome, BaseException)
    )


def _reduce_tle_clusters(state: object) -> Any | None:
    """Reduce multi-provider element sets to one representative per object.

    Returns the clustering summary for display, or None when there was
    nothing to cluster. The cache update stays inside the try: a summary
    computed before a failed update is still the summary that was computed,
    and reporting None there would understate what the sweep actually ran on.
    """
    # Imported before the guard, as they were when this sat inline in the
    # handler: the sweep resolved these names on every request, whether or
    # not there was anything to cluster.
    from spectre.astro.tle_preprocessing import cluster_and_reduce_tle_cache
    from spectre.config.constants import TLE_CLUSTERING

    if not state.hrr_tle_multiset:  # type: ignore[attr-defined]
        return None

    clustering_summary = None
    try:
        reduced, clustering_summary = cluster_and_reduce_tle_cache(
            state.hrr_tle_multiset,  # type: ignore[attr-defined]
            state.hrr_tle_cache,  # type: ignore[attr-defined]
            TLE_CLUSTERING,
        )
        state.hrr_tle_cache.update(reduced)  # type: ignore[attr-defined]
    # BLE001: clustering is an optimisation, never a gate.
    except Exception as _cl_exc:  # noqa: BLE001
        logger.warning(
            "TLE clustering step failed: %s, proceeding without reduction", log_safe(_cl_exc),
        )
    return clustering_summary


# PLR0913, PLR0917: the inputs of one pass over the sweep's target list.
def _run_target_sweep(  # noqa: PLR0913, PLR0917
    state: object,
    targets: list[ThreatTarget],
    manual_tle_by_name: dict[str, str],
    red_tle: str,
    red_regime: str,
    epochs: list[tuple[str, datetime]],
    max_dv_m_s: float,
) -> tuple[list[ThreatSweepEntry], list[str], list[tuple[str, str, str]]]:
    """Fan every target out across every method and epoch.

    Synchronous on purpose: the handler hands this to an executor thread.
    Lifted out of that handler whole, where being nested inside it added the
    handler's nesting to every branch here on top of its own.

    Returns ``(entries, errors, method_refusals)``, the last as
    (target, method, reason) for each method that solved nowhere for that
    target. A target that is skipped
    is recorded with the reason rather than dropped, because a short result
    and a safe one read identically on the screen.
    """
    all_entries: list[ThreatSweepEntry] = []
    sweep_errors: list[str] = []
    method_refusals: list[tuple[str, str, str]] = []
    for target in targets:
        if target.target_source == "manual":
            tle = manual_tle_by_name.get(target.target_name)
        else:
            tle = state.hrr_tle_cache.get(target.target_satno)  # type: ignore[attr-defined]
        if not tle:
            sweep_errors.append(f"No TLE for {target.target_name} — skipped")
            continue
        # Skip targets in incompatible orbit regimes.
        try:
            tgt_regime = regime_from_tle(tle)
        except TLE_ERRORS:
            # Swept on the assumption it is compatible, and said so; the
            # assumption was silent (audit F-234).
            sweep_errors.append(
                f"{target.target_name}: its TLE could not be propagated to classify its orbit; "
                "swept assuming the same regime as red"
            )
            tgt_regime = red_regime
        if not regimes_compatible(red_regime, tgt_regime):
            sweep_errors.append(
                f"{target.target_name}: skipped — "
                f"{red_regime} red vs {tgt_regime} target (regime mismatch)"
            )
            continue
        notes: dict[str, str] = {}
        target_entries = _sweep_all_methods(
            _SweepRequest(
                red_tle=red_tle, target_tle=tle, target=target,
                max_dv_m_s=max_dv_m_s, regime=red_regime,
            ),
            epochs,
            refusals=notes,
        )
        method_refusals.extend((target.target_name, m, why) for m, why in sorted(notes.items()))
        if not target_entries:
            sweep_errors.append(
                f"{target.target_name}: all methods/epochs exceeded {max_dv_m_s:g} m/s or solver failed"
            )
        all_entries.extend(target_entries)
    return all_entries, sweep_errors, method_refusals


def _attach_data_mode(state: object, grouped: list[dict[str, Any]]) -> None:
    """Record each group's element-set provenance for the display-time filter.

    Manual targets are marked MANUAL. Everything else reports the UDL dataMode
    its element set arrived with, so an operator can see at a glance which rows
    rest on tracked orbits and which on generated ones.
    """
    for g in grouped:
        if g["target"].target_source == "manual":
            g["data_mode"] = "MANUAL"
            continue
        satno = g["target"].target_satno
        g["data_mode"] = state.hrr_tle_data_mode.get(satno, "REAL") if satno else "REAL"  # type: ignore[attr-defined]


_DECLARED_MODES = frozenset({"REAL", "MANUAL"})


def _red_track_mode(state: object, red_sat: str, red_satno: str | None) -> str:
    """The provenance of the red track's own element set.

    A track records where its set came from. The sweep used to look the red
    object up in the target cache instead, so a hand-entered red set read as
    REAL whenever the same object was also an HRR target.
    """
    for track in state.red_tracks:  # type: ignore[attr-defined]
        if track.stk_name == red_sat:
            return str(track.data_mode)
    return str(state.hrr_tle_data_mode.get(red_satno or "", "REAL"))  # type: ignore[attr-defined]


def _elset_ages(state: object, red_tle: str, grouped: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """The interceptor's element set age and the swept targets', stale ones named."""
    targets = []
    for group in grouped:
        tle = _target_tle(state, group["target"])
        age = elset_age(tle, now) if tle else None
        if age is not None:
            targets.append((group["target"].target_name, age))
    return {
        "red": elset_age(red_tle, now),
        "newest": min(targets, key=lambda t: t[1].hours)[1] if targets else None,
        "oldest": max(targets, key=lambda t: t[1].hours)[1] if targets else None,
        "stale": [name for name, age in targets if age.stale],
        "count": len(targets),
    }


def _provenance_warnings(subjects: list[tuple[str, str]]) -> list[str]:
    """Name what in a result rests on element sets that are not live tracking.

    *subjects* are (label, UDL dataMode) pairs. REAL is live tracking and
    MANUAL is the operator's own entry, already labelled where it was typed,
    so neither is raised. Every other mode gets one line naming its subjects.
    """
    by_mode: dict[str, list[str]] = {}
    for label, mode in subjects:
        if mode not in _DECLARED_MODES:
            by_mode.setdefault(mode, []).append(label)
    return [f"{mode}: {', '.join(labels)}" for mode, labels in sorted(by_mode.items())]


# ── The red object's own history (SPC-001, SPC-009) ─────────────────────────

#: How long the sweep waits for the red object's history once its own work is
#: done. A first fetch of a long-lived object can take longer; it carries on
#: in the background and is held for the next sweep.
_HISTORY_WAIT_S: float = 20.0
# Fetches still running after a sweep answered. Held here so the event loop
# keeps a reference to each until it finishes.
_HISTORY_TASKS: set[asyncio.Task[HeldHistory]] = set()


def _start_red_history(state: object, red_satno: str | None, now: datetime) -> asyncio.Task[HeldHistory] | None:
    """Start fetching the red object's history, to run alongside the sweep."""
    if not red_satno:
        return None
    task = asyncio.create_task(held_history(state, int(red_satno), now))
    _HISTORY_TASKS.add(task)
    task.add_done_callback(_HISTORY_TASKS.discard)
    return task


class _RedHistory(NamedTuple):
    """What the red object's history said, or why it said nothing."""

    pol: Any | None
    assessment: PolAssessment | None
    normality: BurnNormality | None
    problem: str
    fetched_at: datetime | None


async def _settle_red_history(
    state: object, task: asyncio.Task[HeldHistory] | None, red_satno: str | None,
) -> _RedHistory:
    """Wait a bounded time for the red object's history, then interpret it."""
    if task is None or red_satno is None:
        return _RedHistory(None, None, None, "The interceptor has no catalogue number to fetch a history for.", None)
    try:
        held = await asyncio.wait_for(asyncio.shield(task), timeout=_HISTORY_WAIT_S)
    except TimeoutError:
        return _RedHistory(
            None, None, None, "Its element-set history is still loading from UDL; the next sweep will use it.", None,
        )
    if held.pol is None:
        return _RedHistory(None, None, None, held.problem, held.fetched_at)
    loop = asyncio.get_running_loop()
    reset = reserve_reset_for(state, int(red_satno))
    assessment, normality = await loop.run_in_executor(None, history_evidence, held.pol, reset)
    return _RedHistory(held.pol, assessment, normality, "", held.fetched_at)


def _red_custody(red_tle: str, history: _RedHistory, now: datetime) -> CustodyStatus:
    """Whether the interceptor is in custody: its orbit's age and its history (SPC-018)."""
    age = elset_age(red_tle, now)
    pol = history.pol
    return assess_custody(
        elset_hours=age.hours if age else None,
        limit_hours=age.limit_hours if age else 0.0,
        elset_count=pol.tle_count if pol else 0,
        history_days=pol.span_days if pol else 0.0,
        normality=history.normality.verdict if history.normality else None,
        history_problem=history.problem,
        truncated_at=pol.history_truncated_at if pol else None,
    )


def _behaviour_label(history: _RedHistory) -> str:
    """What the worst case card says about behaviour, in place of the solver's name.

    It said "Close-Proximity Operation" whenever Lambert won the delta-V
    comparison: the solver's name in different words, read as an inference
    about the adversary (red team finding 4). Behaviour comes from the
    object's own history now, or the card says it is not judged (SPC-003).
    """
    if history.normality is not None:
        return f"Behaviour: {history.normality.verdict.value} for this object"
    if history.pol is not None:
        return "Behaviour: no confirmed burns in its history"
    return "Behaviour not judged: no element-set history"


def _red_capability_from(red_satno: str | None, history: _RedHistory) -> CapabilityEvidence:
    """The capability evidence, with the behaviour the held history shows."""
    return _red_capability(red_satno, history.assessment, history.pol.span_days if history.pol else None)


def _worst_coa_in_context(
    state: object, entries: list[ThreatSweepEntry], capability: CapabilityEvidence,
    max_dv_m_s: float, red: tuple[_RedHistory, str],
) -> dict[str, Any] | None:
    """The worst course of action, with its behaviour label and phase angle.

    *red* is the interceptor's history and element set. *entries* is sorted
    on the same warning-time key the worst case is chosen by, so its first
    entry is the worst.
    """
    worst = _compute_worst_coa(entries, capability, max_dv_m_s)
    if worst is None:
        return None
    history, red_tle = red
    worst["behaviour_label"] = _behaviour_label(history)
    worst["phase_label"] = _phase_label(
        red_tle, _swept_target_tle(state, entries[0].target), entries[0].burn_epoch,
    )
    return worst


def _red_history_view(history: _RedHistory, custody: CustodyStatus) -> dict[str, Any]:
    """The sweep's custody and is-this-normal section."""
    problem = history.problem
    if not problem and history.normality is None:
        problem = "No confirmed burns in its element-set history."
    return {
        "custody": custody,
        "normality": history.normality,
        "problem": problem,
        "elsets": history.pol.tle_count if history.pol else 0,
        "span_days": history.pol.span_days if history.pol else 0.0,
        "fetched_at": history.fetched_at,
    }


# ── What the burn changed (SPC-006, SPC-007) ─────────────────────────────────
#
# The operator's second question: how long have I got, and how did that burn
# change it? Warning before and after is flown, not remembered: the orbit just
# before the burn and the orbit the sweep flew, against the same targets and
# their same element sets, at the same moment. So the change needs no earlier
# sweep, and the after figure is the worst case card's own.


def _utc_now() -> datetime:
    """The sweep's clock, a seam so tests can stand at a chosen moment."""
    return datetime.now(tz=UTC)


class _FrozenTargets(NamedTuple):
    """The swept targets' element sets, copied once after clustering.

    Every run of one sweep flies these, so a set refreshed mid-sweep cannot
    make the before and after figures fly different targets. It stands in for
    the session state in ``_run_target_sweep``, which reads only this cache.
    """

    hrr_tle_cache: dict[str, str]


class _SweepBasis(NamedTuple):
    """What every run of one sweep holds constant."""

    targets: list[ThreatTarget]
    manual_tle_by_name: dict[str, str]
    frozen: _FrozenTargets
    red_regime: str
    max_dv_m_s: float
    blue_satnos: frozenset[str]
    now: datetime


def _sweep_basis(  # noqa: PLR0913 - one argument per thing the runs hold constant, all named at the call
    state: object, targets: list[ThreatTarget], *, manual: dict[str, str], red_regime: str,
    max_dv_m_s: float, now: datetime,
) -> _SweepBasis:
    """Freeze the swept targets' element sets and the rest of what every run holds constant."""
    cache = state.hrr_tle_cache  # type: ignore[attr-defined]
    hrr_objects = state.hrr_objects  # type: ignore[attr-defined]
    return _SweepBasis(
        targets=list(targets),
        manual_tle_by_name=dict(manual),
        frozen=_FrozenTargets({t.target_satno: cache[t.target_satno] for t in targets if t.target_satno in cache}),
        red_regime=red_regime,
        max_dv_m_s=max_dv_m_s,
        blue_satnos=frozenset(str(o.get("satno") or "").strip() for o in hrr_objects if _hrr_side(o) == "blue"),
        now=now,
    )


async def _fly(
    basis: _SweepBasis, red_tle: str,
) -> tuple[list[ThreatSweepEntry], list[str], list[tuple[str, str, str]]]:
    """Fly one red orbit against the frozen targets: the sweep, the before run and the watch.

    Epochs and the sweep run off the event loop, the sweep a bounded number at
    once across all operators: each holds an executor thread for its whole
    length (audit F-235).
    """
    loop = asyncio.get_running_loop()
    epochs = await loop.run_in_executor(None, _compute_epochs, red_tle, basis.now)
    async with _SWEEP_SLOTS:
        return await loop.run_in_executor(
            None,
            lambda: _run_target_sweep(
                basis.frozen, basis.targets, basis.manual_tle_by_name, red_tle,
                basis.red_regime, epochs, basis.max_dv_m_s,
            ),
        )


def _when(moment: datetime) -> str:
    """A moment as the operator reads it: "03:12 UTC on 2 Nov"."""
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


def _hours_ago(now: datetime, moment: datetime) -> str:
    return format_tof_label(max((now - moment).total_seconds(), 0.0) / 3600.0)


_DETECTION_NOTE = (
    "A burn counts once 2 independent estimators agree on it at 10 times its own element-set scatter; "
    "screening starts at 2 m/s, so small burns can go unseen."
)


class _ChangeContext(NamedTuple):
    """The facts the change is worded from, beyond the two runs."""

    red_name: str
    red_satno: str | None
    red_epoch: datetime | None
    history: _RedHistory
    prior: ThreatAssessment | None


def _custody_refusal(history: _RedHistory, custody: CustodyStatus) -> WarningChange | None:
    """No figures without a history, or with custody lost."""
    if history.pol is None:
        return WarningChange(Status.CANNOT_SAY, f"What the burn changed: cannot say. {history.problem}")
    if custody.state is Custody.LOST:
        return WarningChange(
            Status.NOT_COMPUTED,
            "What the burn changed is not shown: custody is lost, so any figure would rest on an out-of-date orbit.",
        )
    return None


def _no_burn(pol: Any, now: datetime, limit_hours: float) -> WarningChange:
    """The window held no confirmed burn: say what was looked at, never "nothing moved"."""
    newest = pol.records[-1].epoch if pol.records else now
    confirmed = sorted(pol.manoeuvres, key=lambda m: m.burn_epoch)
    last = (f"Its last confirmed burn was {_hours_ago(now, confirmed[-1].burn_epoch)} ago."
            if confirmed else "It has no confirmed burn in its history.")
    window_start = now - timedelta(hours=limit_hours)
    return WarningChange(
        Status.NO_BURN,
        f"No confirmed burn in its element sets from {_when(window_start)} to its newest, {_when(newest)}: "
        f"the last {limit_hours:.0f} h, its element-set age limit. There is no burn to compare. {last}",
    )


def _burn_selection(
    history: _RedHistory, red_epoch: datetime | None, custody: CustodyStatus, basis: _SweepBasis,
) -> WarningChange | list[Any]:
    """The burns to compare across, or the sentence saying why there are none to compare."""
    refusal = _custody_refusal(history, custody)
    if refusal is not None:
        return refusal
    pol: Any = history.pol  # a history is held: _custody_refusal answered for none
    limit = limit_hours_for_regime(basis.red_regime)
    burns = sorted(burns_in_window(pol.manoeuvres, basis.now, limit), key=lambda m: m.burn_window[0])
    if not burns:
        return _no_burn(pol, basis.now, limit)
    latest = burns[-1]
    if red_epoch is not None and red_epoch < latest.burn_window[1]:
        return WarningChange(
            Status.NOT_COMPUTED,
            f"The sweep above flies its element set of {_when(red_epoch)}, from before its burn at "
            f"{_when(latest.burn_epoch)}, so its figures do not include the burn and the change is not computed. "
            f"UDL holds a set from after it ({_when(latest.tle_after.epoch)}); reconnect to UDL to refresh "
            "held element sets (sets entered by hand are not refreshed), then sweep again.",
        )
    before = burns[0].tle_before
    before_age = (basis.now - before.epoch).total_seconds() / 3600.0
    if before_age > limit:
        return WarningChange(
            Status.NOT_COMPUTED,
            f"That burn's warning change is not computed: its last element set before the burn is "
            f"{age_text(before_age)} old against a {limit:.0f} h limit, too old to fly to now.",
        )
    return burns


def _burn_line(m: Any, red_name: str, verdicts: dict[datetime, Any], now: datetime) -> BurnLine:
    """One burn in the window, with its own is-this-normal verdict."""
    start, end = m.burn_window
    when = (f"{red_name} burned at {_when(m.burn_epoch)}, {_hours_ago(now, m.burn_epoch)} ago."
            if start == end else f"{red_name} burned between {_when(start)} and {_when(end)}.")
    verdict = verdicts.get(m.burn_epoch)
    caveat = (f"Caveat: the element sets either side of that burn were {m.gap_days:.0f} days apart, "
              "so the before orbit may already include other burns.") if m.long_gap else ""
    return BurnLine(when, f"Is this normal? {verdict.sentence}" if verdict else "", caveat)


def _basis_line(basis: _SweepBasis, before: Any, red_epoch: datetime | None) -> str:
    """What the figures rest on, in small text under the section."""
    after = f"(epoch {_when(red_epoch)})" if red_epoch else ""
    return (
        f"Computed at {basis.now:%H:%M} UTC. Before: its last element set before the burn "
        f"(epoch {_when(before.epoch)}), flown as if it had not burned. After: the element set this sweep "
        f"flew {after}. Both against the same {len(basis.targets)} targets and their same element sets, the same "
        f"{len(_SWEEP_METHODS)} transfer methods and the {basis.max_dv_m_s:g} m/s budget. Each orbit is offered "
        "its own burn times (now, and its apsides and nodes over the next 24 hours), so part of a change can be "
        "timing rather than reach. Warning time runs from the moment it burns to arrival, for its fastest "
        "intercept, as on the worst case. A change within 15 minutes reads as unchanged; that tolerance is "
        f"tuned, not sourced. {_DETECTION_NOTE}"
    )


def _last_shown(prior: ThreatAssessment | None, red_satno: str | None, first_burn: Any, top: Any) -> str:
    """The figure the operator last saw before the burn, cited and never used as "before"."""
    if prior is None or top is None or not prior.red_tle or not red_satno:
        return ""
    prior_number = satno_from_tle(prior.red_tle)
    prior_age = elset_age(prior.red_tle, first_burn.burn_window[0])
    if str(prior_number) != red_satno or prior_age is None or prior_age.epoch > first_burn.burn_window[0]:
        return ""
    shown = least_warning_by_target(prior.entries, float("inf")).get(top.name)
    if shown is None:
        return ""
    return (f"Last shown before the burn: {format_tof_label(shown)} on {top.name}, "
            f"in your sweep at {prior.sweep_epoch:%H:%M} UTC.")


def _change_notes(context: _ChangeContext, burns: list[Any], top: Any, now: datetime) -> tuple[str, ...]:
    """The lines shown only when they apply."""
    pol: Any = context.history.pol
    notes = [_last_shown(context.prior, context.red_satno, burns[0], top)]
    newer = newest_unconfirmed(pol.candidate_manoeuvres, burns[-1].tle_after.epoch)
    if newer is not None:
        notes.append(f"An unconfirmed detection at {_when(newer.burn_epoch)} is newer and is not counted, "
                     "because it is not confirmed.")
    notes.append(_notso_cue(context.red_name, context.red_satno, burns[-1].tle_after.epoch, now))
    return tuple(n for n in notes if n)


def _build_change(
    basis: _SweepBasis, burns: list[Any], before: list[ThreatSweepEntry], after: list[ThreatSweepEntry],
    context: _ChangeContext,
) -> WarningChange:
    """The rows, the headline, each burn's line, the notes and the basis."""
    rows = compare(
        [(t.target_name, t.target_source == "blue" or t.target_satno in basis.blue_satnos) for t in basis.targets],
        least_warning_by_target(before, basis.max_dv_m_s),
        least_warning_by_target(after, basis.max_dv_m_s),
    )
    changed = tuple(r for r in rows if r.change.name != "UNCHANGED")
    top = next((r for r in rows if r.change.name in ("CUT", "NEWLY_IN_REACH")), None)
    verdicts = burn_verdicts(context.history.pol, context.history.assessment) if context.history.assessment else {}
    return WarningChange(
        status=Status.FIGURES,
        headline=headline(rows, len(burns), basis.max_dv_m_s, format_tof_label),
        rows=tuple(rows),
        footer=footer(rows),
        burns=tuple(_burn_line(m, context.red_name, verdicts, basis.now) for m in burns),
        notes=_change_notes(context, burns, top, basis.now),
        basis=_basis_line(basis, burns[0].tle_before, context.red_epoch),
        worst=worst_change(rows),
        changed=changed,
    )


async def _warning_change(
    basis: _SweepBasis, red: tuple[str, str | None, str], history: _RedHistory,
    entries: list[ThreatSweepEntry], context: tuple[CustodyStatus, ThreatAssessment | None],
) -> WarningChange:
    """What the burn changed: the one call the sweep makes for it.

    *red* is the interceptor's name, catalogue number and the element set the
    sweep flew; *entries* are the sweep's own, so the after figure is the one
    the worst case card shows. *context* is its custody and the operator's
    previous sweep, cited when it flew the orbit from before the burn.
    """
    red_name, red_satno, red_tle = red
    custody, prior = context
    age = elset_age(red_tle, basis.now)
    red_epoch = age.epoch if age else None
    selection = _burn_selection(history, red_epoch, custody, basis)
    if isinstance(selection, WarningChange):
        return selection
    before, _, _ = await _fly(basis, selection[0].tle_before.tle)
    return _build_change(
        basis, selection, before, entries, _ChangeContext(red_name, red_satno, red_epoch, history, prior),
    )


def _notso_cue(red_name: str, red_satno: str | None, latest_after: datetime | None, now: datetime) -> str:
    """A manoeuvre NOTSO newer than any confirmed burn: named, never turned into a figure.

    Read from the cache the operator syncs; nothing is pulled from UDL here.
    """
    if not red_satno:
        return ""
    from spectre.data.notso_cache import event_class, get_notso_cache, is_manoeuvre_notice, notice_time

    cache = get_notso_cache()
    newer: list[tuple[datetime, dict[str, Any]]] = []
    for rec in cache.get_for_satno(red_satno):
        when = notice_time(rec)
        if is_manoeuvre_notice(rec) and when is not None and when <= now and (
                latest_after is None or when > latest_after):
            newer.append((when, rec))
    if not newer:
        return ""
    when, rec = max(newer, key=lambda pair: pair[0])
    synced = cache.last_sync_utc() or "never"
    return (f"NOTSO at {_when(when)} reports a {event_class(rec)} by {red_name}. No element set since shows "
            "a confirmed burn yet, so its effect on your warning cannot be computed. "
            f"NOTSO cache last synced {synced}.")


async def _watch_change(
    state: object, watch: BurnWatch, found: tuple[Any, PolAssessment, list[Any]], now: datetime,
) -> WarningChange:
    """What the burns the watch found changed, flown from the newest held orbit at check time.

    The same selection and wording as the sweep. After is the history's newest
    element set, refused as custody lost past its regime's limit, and the
    targets' element sets are frozen afresh from the session at this moment.
    """
    pol, assessment, burns = found
    basis = _sweep_basis(state, watch.targets, manual=watch.manual_tle_by_name, red_regime=watch.red_regime,
                         max_dv_m_s=watch.max_dv_m_s, now=now)
    red_tle = pol.records[-1].tle
    verdicts = burn_verdicts(pol, assessment)
    latest = verdicts.get(max(burns, key=lambda m: m.burn_epoch).burn_epoch)
    history = _RedHistory(pol, assessment, latest, "", now)
    custody = _red_custody(red_tle, history, now)
    age = elset_age(red_tle, now)
    red_epoch = age.epoch if age else None
    selection = _burn_selection(history, red_epoch, custody, basis)
    if isinstance(selection, WarningChange):
        return selection
    after, _, _ = await _fly(basis, red_tle)
    before, _, _ = await _fly(basis, selection[0].tle_before.tle)
    context = _ChangeContext(watch.red_name, str(watch.red_satno), red_epoch, history, None)
    return _build_change(basis, selection, before, after, context)


def _watch_after_sweep(  # noqa: PLR0913 - one argument per thing the watch starts from, all named at the call
    state: object, user: User, basis: _SweepBasis, red: tuple[str, str | None], *,
    history: _RedHistory, history_task: asyncio.Task[HeldHistory] | None,
) -> None:
    """Start, or replace, the burn watch on the object just swept (SPC-006).

    Only with UDL connected and a catalogue number to ask UDL about. The burns
    the history already held are accounted for, because the sweep has just
    shown them; with the history still loading, none is, so the first check
    announces any burn in the window.
    """
    red_name, red_satno = red
    if not red_satno or not state.udl_username or user.session_key is None:  # type: ignore[attr-defined]
        return
    pol = history.pol
    confirmed = pol.manoeuvres if pol is not None else []
    watch = BurnWatch(
        red_name=red_name, red_satno=int(red_satno), red_regime=basis.red_regime,
        targets=list(basis.targets), manual_tle_by_name=dict(basis.manual_tle_by_name),
        max_dv_m_s=basis.max_dv_m_s,
        accounted_until=max((m.tle_after.epoch for m in confirmed), default=None) if pol is not None else None,
        started_at=basis.now, next_check_at=basis.now + CHECK_EVERY,
        newest_epoch=pol.records[-1].epoch if pol is not None and pol.records else None,
    )
    if pol is None:
        watch.next_check_at = basis.now
    start_watch(state, user.session_key, watch, first_history=history_task,  # type: ignore[arg-type]
                compute=_watch_change, spawn=spawn_session_task)


@router.get("/burn-watch", response_model=None)
async def burn_watch_note(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """The burn watch note: watching, an alert, or why it is not watching. Makes no UDL call."""
    state = get_session_state(current_user)
    return render(request, _BURN_WATCH_TEMPLATE, watch_view(state, current_user.session_key, _utc_now()))


def _band_runs(worst: ThreatSweepEntry, red_tle: str, target_tle: str, errors_km: tuple[float, float],
               max_dv_m_s: float) -> list[tuple[float, float]]:
    """The worst case re-solved with each orbit moved ahead and behind along track: ``(m/s, hours)`` each."""
    method = next((m for m in _SWEEP_METHODS if m[0] == worst.method), None)
    if method is None:
        return []
    name, solver, extra = method
    kwargs = dict(extra)
    if name == "min_time":
        kwargs["max_delta_v"] = to_km_s(max_dv_m_s)  # astro takes km/s
    red_km, target_km = errors_km
    values: list[tuple[float, float]] = []
    for red_sign, target_sign in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        try:
            sol = solver(red_tle=shift_along_track(red_tle, red_sign * red_km),
                         blue_tle=shift_along_track(target_tle, target_sign * target_km),
                         manoeuvre_start=worst.burn_epoch, **kwargs)
        # BLE001: a solver refusing a shifted geometry narrows the band; it is not a sweep failure.
        except Exception as exc:  # noqa: BLE001
            logger.debug("Band re-solve refused for %s: %s", log_safe(worst.method), log_safe(exc))
            continue
        tof_h = (sol.arrival_epoch - sol.burns[0].epoch).total_seconds() / 3600.0 if sol.burns else 0.0
        values.append((from_km_s(abs(sol.total_delta_v)), tof_h))
    return values


#: Re-solves needed before a spread says anything: one alone has nothing to differ from.
_MIN_BAND_RUNS: int = 2


def _dv_band(state: object, entries: list[ThreatSweepEntry], red_tle: str, basis: _SweepBasis) -> dict[str, str]:
    """The worst case's delta-V band from element-set age (SPC-005, red team finding 6), or nothing.

    A sensitivity, not a confidence interval: how far the figure moves when
    each orbit sits where its element set's age says it could be. Needs at
    least two re-solves to say anything.
    """
    if not entries:
        return {}
    worst = entries[0]
    target_tle = _swept_target_tle(state, worst.target)
    if not target_tle:
        return {}
    ages = [elset_age(tle, basis.now) for tle in (red_tle, target_tle)]
    red_km, target_km = (position_error_km(a.days if a else 0.0, basis.red_regime) for a in ages)
    values = _band_runs(worst, red_tle, target_tle, (red_km, target_km), basis.max_dv_m_s)
    if len(values) < _MIN_BAND_RUNS:
        return {}
    dv_spread = max(abs(dv - worst.delta_v_m_s) for dv, _ in values)
    tof_minutes = max(abs(tof - worst.tof_hours) for _, tof in values) * 60.0
    red_age, target_age = (age_text(a.hours) if a else "unknown" for a in ages)
    how = (f"re-solved with the interceptor's orbit moved {red_km:.0f} km and the target's {target_km:.0f} km along "
           f"track, ahead and behind, the error assumed for element sets {red_age} and {target_age} old (1 km plus "
           "2 km a day of age in LEO and MEO, 2 km plus 1 km a day at GEO; tuned, not sourced). A sensitivity, not a "
           "confidence interval.")
    if worst.method == "min_time":
        # The minimum-time solver spends the whole budget by construction, so
        # its delta-V cannot move; its flight time, the warning, is what does.
        return {
            "dv_band": "(the budget)",
            "dv_band_basis": (f"This intercept spends the whole budget by construction, so its delta-V does not "
                              f"move; its flight time moves by \u00b1 {tof_minutes:.0f} min when {how}"),
        }
    band = f"\u00b1 {dv_spread:.1f}" if dv_spread < 1.0 else f"\u00b1 {dv_spread:.0f}"
    return {
        "dv_band": band,
        "dv_band_basis": (f"Delta-V band {band} m/s, and flight time \u00b1 {tof_minutes:.0f} min: the figure {how}"),
    }


def _with_band(worst_coa: dict[str, Any] | None, band: dict[str, str]) -> dict[str, Any] | None:
    if worst_coa is not None:
        worst_coa.update(band)
    return worst_coa


def _sweep_decide_by(
    state: object, entries: list[ThreatSweepEntry], custody: CustodyStatus, worst_coa: dict[str, Any] | None,
    basis: _SweepBasis,
) -> DecideBy:
    """Decide-by for this sweep (SPC-008), or why it is withheld.

    Withheld where custody is lost, because the arrival would rest on an
    out-of-date orbit, and where the interceptor is assessed unable to fly the
    intercept, because a deadline for something it cannot do would alarm.
    """
    if custody.state is Custody.LOST:
        return withheld("custody is lost, so the soonest arrival would rest on an out-of-date orbit")
    if worst_coa is not None and worst_coa.get("capability_level") == "MINIMAL":
        return withheld("the interceptor is assessed unable to fly the intercept (capability MINIMAL)")
    set_hours = state.response_time_h  # type: ignore[attr-defined]
    hours = DEFAULT_RESPONSE_H if set_hours is None else float(set_hours)
    return decide_by(earliest_arrival(entries, basis.max_dv_m_s), hours, set_hours is None, basis.now, basis.max_dv_m_s)


def _take_response_time(state: object, raw: str, errors: list[str]) -> None:
    """Hold the response time the sweep form carries; blank keeps the last one set."""
    hours, problem = parse_response_hours(raw)
    if problem:
        errors.append(f"{problem} Decide-by uses the response time already set.")
    elif hours is not None:
        state.response_time_h = hours  # type: ignore[attr-defined]


@router.post("/sweep", response_model=None)
async def threat_sweep(
    request: Request,
    red_sat: Annotated[str, Form()],
    max_dv_m_s: Annotated[float, Form(ge=0.0, le=100000.0)] = DEFAULT_SWEEP_BUDGET_M_S,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Run a threat sweep for a red satellite against the selected target group."""
    t0 = time.monotonic()
    state = get_session_state(current_user)
    now = _utc_now()
    errors: list[str] = []
    # The operator's previous sweep, cited if it flew this object's pre-burn orbit.
    prior = state.last_threat_assessment

    # Parse target group selection (e.g. "blue:1", "red:3", "all").
    form = await request.form()
    tgt_group = str(form.get("tgt_group") or "").strip()

    # Read optional manual red TLE override.
    manual_red_tle_raw = str(form.get("manual_red_tle") or "").strip()
    manual_red_confidence = str(form.get("manual_red_confidence") or "MEDIUM").strip().upper()
    manual_red_tle: str | None = _validate_manual_red_tle(manual_red_tle_raw, errors)
    _take_response_time(state, str(form.get("response_time_h") or ""), errors)

    parsed = _parse_target_group(tgt_group)
    if parsed.error:
        return render(request, _THREAT_SWEEP_TEMPLATE, {
            "assessment": None,
            "error": parsed.error,
        })
    side, rank, group_label = parsed.side, parsed.rank, parsed.group_label

    # Find red TLE — manual override takes precedence over the registered track.
    red_tle: str | None = manual_red_tle or state.tle_of(red_sat.strip())
    if not red_tle:
        return render(request, _THREAT_SWEEP_TEMPLATE, {
            "assessment": None,
            "error": f"No TLE found for red satellite: {red_sat}",
        })

    # Build HRR target list, excluding the interceptor itself.
    red_number = satno_from_tle(red_tle) if red_tle else None
    red_satno = str(red_number) if red_number is not None else None
    targets = (
        [] if side == "none"
        else _build_target_list(state, side, rank, exclude_satno=red_satno)
    )

    # Build manual targets from session state.
    _manual_tle_by_name = _append_manual_targets(state, targets)

    if not targets:
        return render(request, _THREAT_SWEEP_TEMPLATE, {
            "assessment": None,
            "error": "No targets available — select an HRR group or add manual TLEs.",
        })

    # Classify red satellite's regime once — used to skip incompatible targets.
    # A red TLE SGP4 cannot propagate cannot be swept; it was assumed to be
    # LEO and the sweep went ahead on that silent guess (audit F-234).
    try:
        red_regime = regime_from_tle(red_tle)
    except TLE_ERRORS as exc:
        return render(request, _THREAT_SWEEP_TEMPLATE, {
            "assessment": None,
            "error": f"The red TLE could not be propagated to classify its orbit: {exc}",
        })

    targets = _cap_targets(state, targets, _manual_tle_by_name, red_regime, errors)

    # Its own history comes from UDL while the sweep computes.
    history_task = _start_red_history(state, red_satno, now)

    # Any targets without a cached TLE get a last-chance fetch now.
    await _fetch_missing_target_tles(state, targets, errors)

    loop = asyncio.get_running_loop()
    # Cluster multi-provider TLEs and reduce to best representative per object,
    # off the event loop like the sweep itself (audit F-235).
    clustering_summary = await loop.run_in_executor(None, _reduce_tle_clusters, state)

    # Count total targets (HRR + manual).
    hrr_count = len(targets)

    # The targets' element sets are frozen here, after the last-chance fetch
    # and clustering, so the sweep and the before-burn run fly the same ones.
    basis = _sweep_basis(state, targets, manual=_manual_tle_by_name, red_regime=red_regime,
                         max_dv_m_s=max_dv_m_s, now=now)
    entries, sweep_errors, method_refusals = await _fly(basis, red_tle)
    errors.extend(sweep_errors)

    # Rank on warning time among the feasible intercepts. Delta-V keeps its
    # role as the feasibility filter it already was, but it is not the ranking:
    # an intercept arriving in 35 minutes is a harder problem than a cheaper
    # one arriving in 40 hours, and sorting on cost called the second worse.
    entries.sort(key=lambda e: warning_time_rank(e.delta_v_m_s, e.tof_hours, max_dv_m_s, e.arrives))

    elapsed = time.monotonic() - t0

    assessment = ThreatAssessment(
        red_name=red_sat.strip(),
        sweep_epoch=now,
        entries=entries,
        target_count=len(targets),
        elapsed_s=round(elapsed, 2),
        errors=errors,
        red_tle=red_tle,
    )

    # Group entries by target for the collapsed-row UI.
    grouped = _group_entries(entries)
    # Attach UDL dataMode provenance to each group for the display-time filter.
    _attach_data_mode(state, grouped)
    red_mode = "MANUAL" if manual_red_tle else _red_track_mode(state, red_sat.strip(), red_satno)
    provenance = _provenance_warnings(
        [(f"red {red_sat.strip()}", red_mode)]
        + [(f"target {g['target'].target_name}", g["data_mode"]) for g in grouped],
    )

    # What is known about the RED object's ability to act: its assessed record
    # and, when its history arrived, its behaviour (SPC-002). Capability is a
    # property of the threatening object, not of the things it might reach.
    history = await _settle_red_history(state, history_task, red_satno)
    red_capability = _red_capability_from(red_satno, history)

    # Identify the most dangerous course of action.
    worst_coa = _worst_coa_in_context(state, entries, red_capability, max_dv_m_s, (history, red_tle))
    custody = _red_custody(red_tle, history, now)
    red_history = _red_history_view(history, custody)
    # What the burn changed, from the orbit before it and the one just flown.
    warning_change = await _warning_change(
        basis, (red_sat.strip(), red_satno, red_tle), history, entries, (custody, prior),
    )
    _watch_after_sweep(state, current_user, basis, (red_sat.strip(), red_satno),
                       history=history, history_task=history_task)
    decide = _sweep_decide_by(state, entries, custody, worst_coa, basis)
    worst_coa = _with_band(worst_coa, await loop.run_in_executor(None, _dv_band, state, entries, red_tle, basis))

    state.last_threat_assessment = assessment
    state.append_log(
        f"[THREAT] Sweep complete: {red_sat} vs {len(targets)} "
        f"{group_label} targets, "
        f"{len(entries)} solutions, {elapsed:.1f}s"
    )
    logger.info(
        "threat_sweep: %s vs %s targets (%s), %s solutions, %ss by %s",
        log_safe(red_sat), log_safe(len(targets)), log_safe(group_label),
        log_safe(len(entries)), log_safe(format(elapsed, ".1f")),
        log_safe(current_user.username),
    )

    return render(request, _THREAT_SWEEP_TEMPLATE, {
        "assessment": assessment,
        "grouped": grouped,
        "hrr_count": hrr_count,
        "worst_coa": worst_coa,
        # Methods that produced nothing, and why. Previously discarded, which
        # hid the fastest approaches: refusals cluster on the aggressive end.
        "method_refusals": method_refusals,
        "red_satno": red_satno or "",
        "manual_red_confidence": manual_red_confidence if manual_red_tle else None,
        "clustering_summary": clustering_summary,
        "provenance_warnings": provenance,
        "elset_ages": _elset_ages(state, red_tle, grouped, now),
        "red_history": red_history,
        "warning_change": warning_change,
        "decide_by": decide,
        **watch_view(state, current_user.session_key, now),
        "epoch_note": _epoch_note(red_tle),
        "error": None,
    })






async def _refresh_actor_tles(state: object, actors: list[ThreatActor]) -> list[str]:
    """Fetch live element sets for actors that have none, or only synthetic.

    A no-op without UDL credentials, which is the normal case on a fresh
    instance running from the bundled bootstrap watchlist. Returns one note
    per actor whose fetch failed: it is then screened on the set already
    held, and the operator is told so (F-135), as the sweep does.
    """
    missing = [a for a in actors if _needs_live_tle(state, a.actor_satno)]
    if not missing or not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]
        return []

    from spectre.web.routes.udl import fetch_tle_for_satno

    sem = asyncio.Semaphore(10)
    user: str = state.udl_username  # type: ignore[attr-defined]
    password: str = state.udl_password  # type: ignore[attr-defined]

    async def _fetch_one(actor: ThreatActor) -> bool:
        async with sem:
            got = await fetch_tle_for_satno(
                int(actor.actor_satno), user, password,
                data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]
                source=state.udl_tle_source,  # type: ignore[attr-defined]
            )
            if not got:
                return False
            tle, mode = got
            state.hrr_tle_cache[actor.actor_satno] = tle  # type: ignore[attr-defined]
            state.hrr_tle_data_mode[actor.actor_satno] = mode  # type: ignore[attr-defined]
            return True

    outcomes = await asyncio.gather(*[_fetch_one(a) for a in missing], return_exceptions=True)
    held = "screened on the set already held"
    return [
        f"{a.actor_name} ({a.actor_satno}): live element set not fetched"
        + (f" ({_refusal_reason(outcome)}); {held}" if isinstance(outcome, BaseException) else f"; {held}")
        for a, outcome in zip(missing, outcomes, strict=True)
        if outcome is not True
    ]



class _ScreenRun(NamedTuple):
    """Everything one pass over the candidate actors produced."""

    verdicts: list[ActorVerdict]
    entries: list[ThreatSweepEntry]
    refusals: list[tuple[str, str, str]]
    notes: list[str]


# PLR0913, PLR0917: the inputs of one screening pass.
def _screen_all_actors(  # noqa: PLR0913, PLR0917
    state: object,
    actors: list[ThreatActor],
    asset_tle: str,
    asset: ThreatTarget,
    now: datetime,
    budget_m_s: float,
) -> _ScreenRun:
    """Assess every candidate actor against the asset.

    An actor that cannot be assessed is recorded with the reason rather than
    dropped, because a shorter list and a safer asset look identical.
    """
    verdicts: list[ActorVerdict] = []
    entries: list[ThreatSweepEntry] = []
    refusals: list[tuple[str, str, str]] = []
    notes: list[str] = []

    for actor in actors:
        actor_tle = _resolve_hrr_tle(state, actor.actor_satno)
        if not actor_tle:
            notes.append(f"{actor.actor_name} ({actor.actor_satno}): no element set")
            continue
        verdict, actor_entries = _screen_one_actor(
            actor, actor_tle, asset_tle, asset, now, budget_m_s, refusals,
        )
        entries.extend(actor_entries)
        if verdict is None:
            notes.append(
                f"{actor.actor_name} ({actor.actor_satno}): no method within "
                f"{budget_m_s:g} m/s"
            )
            continue
        verdicts.append(verdict)

    return _ScreenRun(verdicts=verdicts, entries=entries, refusals=refusals, notes=notes)


def _profiles_by_actor(
    entries: list[ThreatSweepEntry],
) -> dict[str, list[ThreatSweepEntry]]:
    """Group entries so each ranked row opens to the profiles behind it.

    Soonest first, so an analyst can see WHICH epoch and method produced the
    warning time rather than being asked to take the headline on trust.
    """
    grouped: dict[str, list[ThreatSweepEntry]] = {}
    for entry in entries:
        if entry.actor is None:
            continue
        grouped.setdefault(entry.actor.actor_satno, []).append(entry)
    for rows in grouped.values():
        rows.sort(key=lambda e: (not e.arrives, e.tof_hours, e.delta_v_m_s))
    return grouped


class _Candidates(NamedTuple):
    """The actors to screen, how many were considered, or why there are none."""

    actors: list[ThreatActor] = []
    red_population: int = 0
    notes: list[str] = []
    error: str = ""


def _select_candidates(state: object, asset_regime: str) -> _Candidates:
    """Choose which red objects to screen against this asset.

    Every empty outcome carries a different sentence. An operator reading
    "no candidates" has to be able to tell a missing watchlist from a
    watchlist whose red objects are all in the wrong regime, because one is a
    setup problem and the other is a finding.
    """
    if not state.hrr_objects:  # type: ignore[attr-defined]
        return _Candidates(error=(
            "No HRR watchlist loaded, so there are no candidate actors to "
            "screen against. Fetch the HRR list from the UDL panel first."
        ))

    hrr_objects = state.hrr_objects  # type: ignore[attr-defined]
    red_population = sum(
        1 for o in hrr_objects
        if str(o.get("country") or "").strip().upper() in _RED_COUNTRIES
    )
    actors = _build_actor_list(state, asset_regime)
    if not actors:
        return _Candidates(error=(
            f"No red HRR objects are in a regime compatible with "
            f"{asset_regime or 'this asset'}. {red_population} red object(s) "
            "were considered and all were excluded by regime."
        ))

    notes: list[str] = []
    if len(actors) > _MAX_SCREEN_ACTORS:
        notes.append(
            f"Candidate list truncated to {_MAX_SCREEN_ACTORS} of {len(actors)} "
            "(compute cap). Ranking covers the truncated set only."
        )
        actors = actors[:_MAX_SCREEN_ACTORS]

    return _Candidates(actors=actors, red_population=red_population, notes=notes)


class _ResolvedAsset(NamedTuple):
    """The asset to screen, or why it could not be resolved.

    Pulled out of the handler because resolving which object the operator
    means, and where its element set comes from, is a separate job from
    screening it. Every failure here is a sentence the operator can act on.
    """

    tle: str = ""
    satno: str = ""
    name: str = ""
    error: str = ""


def _resolve_asset(
    state: object, asset_satno: str, manual_tle: str,
) -> _ResolvedAsset:
    """Resolve the blue asset from a watchlist selection or a pasted TLE."""
    if manual_tle:
        try:
            TLEOrbit(manual_tle)
        # BLE001: operator input, reported not raised.
        except Exception as exc:  # noqa: BLE001
            return _ResolvedAsset(error=f"Manual asset TLE invalid: {exc}")
        satno = str(satno_from_tle(manual_tle) or asset_satno)
        return _ResolvedAsset(
            tle=manual_tle,
            satno=satno,
            name=f"Manual asset [{satno}]" if satno else "Manual asset",
        )

    if not asset_satno:
        return _ResolvedAsset(error="Select a blue asset to screen, or paste its TLE.")

    tle = _resolve_hrr_tle(state, asset_satno)
    if not tle:
        return _ResolvedAsset(error=(
            f"No element set cached for asset {asset_satno}. Fetch the HRR "
            "watchlist TLEs from the UDL panel, or paste the asset's TLE."
        ))

    name = next(
        (
            str(o.get("name") or asset_satno).strip()
            for o in state.hrr_objects  # type: ignore[attr-defined]
            if str(o.get("satno") or "").strip() == asset_satno
        ),
        asset_satno,
    )
    return _ResolvedAsset(tle=tle, satno=asset_satno, name=name)


@router.get("/screen-config", response_model=None)
async def screen_config(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """Return the blue asset selector for the screening panel."""
    state = get_session_state(current_user)
    assets = [
        {
            "satno": str(o.get("satno") or "").strip(),
            "name": str(o.get("name") or o.get("satno") or "—").strip(),
            "country": str(o.get("country") or "").strip().upper(),
            "regime": normalise_regime(str(o.get("orbit_regime") or "")),
            "rank": o.get("rank"),
        }
        for o in state.hrr_objects
        if str(o.get("country") or "").strip().upper() not in _RED_COUNTRIES
        and str(o.get("satno") or "").strip()
    ]
    assets.sort(key=lambda a: (a["rank"] if a["rank"] is not None else 99, a["name"]))
    red_total = sum(
        1 for o in state.hrr_objects
        if str(o.get("country") or "").strip().upper() in _RED_COUNTRIES
    )
    # Provenance. Element sets that did not come from live tracking must be
    # declared where the operator chooses an asset, not only in a server log.
    modes = {state.hrr_tle_data_mode.get(str(a["satno"]), "REAL") for a in assets}
    return render(request, "partials/screen_config.html", {
        "has_udl": bool(state.udl_username),
        "has_hrr": bool(state.hrr_objects),
        "assets": assets,
        "red_total": red_total,
        "synthetic_elements": bool(modes - {"REAL"}),
    })


@router.post("/screen", response_model=None)
async def threat_screen(
    request: Request,
    # Annotated carries no default, so it must precede the defaulted form
    # fields. FastAPI binds these by name, so the order is not observable.
    current_user: Annotated[User, Depends(require_login)],
    asset_satno: Annotated[str, Form()] = "",
    max_dv_m_s: Annotated[float, Form(ge=0.0, le=100000.0)] = DEFAULT_SWEEP_BUDGET_M_S,
) -> HTMLResponse:
    """Screen ONE blue asset against every candidate red actor in reach.

    The inverse of ``/sweep``: instead of one red object against many targets,
    this is many candidate actors against one asset, ranked so the analyst is
    told which object to brief.
    """
    t0 = time.monotonic()
    state = get_session_state(current_user)
    now = datetime.now(tz=UTC)
    errors: list[str] = []

    def _fail(message: str) -> HTMLResponse:
        """Every empty result carries a reason. Silence reads as safety."""
        return render(request, "partials/threat_screen.html", {
            "screening": None, "error": message,
        })

    form = await request.form()
    manual_asset_tle = str(form.get("manual_asset_tle") or "").strip()
    asset_satno = str(asset_satno or form.get("asset_satno") or "").strip()

    resolved = _resolve_asset(state, asset_satno, manual_asset_tle)
    if resolved.error:
        return _fail(resolved.error)
    asset_tle = resolved.tle
    asset_satno = resolved.satno
    asset_name = resolved.name
    asset_regime = _regime_of_tle(asset_tle)
    asset = ThreatTarget(
        target_name=asset_name,
        target_satno=asset_satno,
        target_source="hrr" if not manual_asset_tle else "manual",
        hrr_rank=None,
    )

    # ── Enumerate candidate actors ───────────────────────────────────────────
    candidates = _select_candidates(state, asset_regime)
    if candidates.error:
        return _fail(candidates.error)
    actors = candidates.actors
    screened_from = candidates.red_population
    errors.extend(candidates.notes)

    # ── Fetch any missing or synthetic actor element sets ────────────────────
    refresh_notes = await _refresh_actor_tles(state, actors)

    # ── Screen, off the event loop ───────────────────────────────────────────
    loop = asyncio.get_running_loop()
    run = await loop.run_in_executor(
        None,
        lambda: _screen_all_actors(state, actors, asset_tle, asset, now, max_dv_m_s),
    )
    errors.extend(run.notes)

    screening = rank_actors(run.verdicts)
    # Read after _refresh_actor_tles, which replaces synthetic sets when it can.
    asset_mode = "MANUAL" if manual_asset_tle else state.hrr_tle_data_mode.get(asset_satno, "REAL")
    actor_modes = {
        v.actor_satno: state.hrr_tle_data_mode.get(v.actor_satno, "REAL")
        for v in run.verdicts
    }
    provenance = _provenance_warnings(
        [(f"asset {asset_name}", asset_mode)]
        + [(f"actor {v.actor_name}", actor_modes[v.actor_satno]) for v in run.verdicts],
    ) + refresh_notes
    profiles_by_actor = _profiles_by_actor(run.entries)
    entries = run.entries
    method_refusals = run.refusals
    elapsed = time.monotonic() - t0

    state.append_log(
        f"[SCREEN] {asset_name}: {len(actors)} candidate actor(s), "
        f"{len(run.verdicts)} within {max_dv_m_s:g} m/s, {elapsed:.1f}s "
        f"(operator {current_user.username})"
    )

    return render(request, "partials/threat_screen.html", {
        "screening": screening,
        "asset_name": asset_name,
        "asset_satno": asset_satno,
        "asset_regime": asset_regime or "unknown",
        "actors_considered": len(actors),
        "actors_reachable": len(run.verdicts),
        "red_population": screened_from,
        "budget_m_s": max_dv_m_s,
        "elapsed_s": round(elapsed, 2),
        "entry_count": len(entries),
        "method_refusals": method_refusals,
        "profiles_by_actor": profiles_by_actor,
        "errors": errors,
        "error": None,
        "band_colours": _BAND_COLOURS,
        "actor_modes": actor_modes,
        "provenance_warnings": provenance,
    })

def _target_tle(state: object, target: ThreatTarget) -> str | None:
    """The element set a swept target was flown with.

    A manual target's set lives in the manual list, keyed by name; looking it
    up in the HRR cache by number found nothing (found by the F-042 tests).
    """
    if target.target_source == "manual":
        return next(
            (m["tle"] for m in state.manual_sweep_tles if m["name"] == target.target_name),  # type: ignore[attr-defined]
            None,
        )
    return state.hrr_tle_cache.get(target.target_satno)  # type: ignore[attr-defined, no-any-return]


@router.post("/refine", response_model=None)
async def refine_entry(
    request: Request,
    entry_index: Annotated[int, Form(ge=0)],
    group_idx: Annotated[int, Form(ge=0)] = 0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Refine a single threat sweep entry with Lambert solver.

    ``group_idx`` arrives with ``entry_index`` from the row being replaced.
    The fragment swaps in over one child row of threat_sweep.html, whose
    column headings are a repeated in-tbody header row with ids of the form
    ``tsw-child-<group>-N``; the refined cells bind to those with ``headers=``
    and so have to name the same group. It is not recomputed here on purpose:
    ``_group_entries`` ranks the groups on best time-of-flight and delta-v,
    which is exactly what a refine changes, so a grouping derived after the
    fact can disagree with the table the row is still sitting in.
    """
    state = get_session_state(current_user)
    # Held for the whole request. The session state is shared by every tab
    # of this account, so a sweep finishing elsewhere during the await below
    # replaces last_threat_assessment, and writing through the state then
    # spliced this entry into the newer sweep or raised IndexError (F-128).
    assessment = state.last_threat_assessment

    def _row(entry: ThreatSweepEntry | None, error: str | None, refine_error: str | None = None) -> HTMLResponse:
        return render(request, "partials/threat_sweep_row.html", {
            "entry": entry, "index": entry_index, "group_idx": group_idx,
            "red_name": assessment.red_name if assessment else "",
            "error": error, "refine_error": refine_error,
        })

    if not assessment or entry_index >= len(assessment.entries):
        return _row(None, "Invalid entry")

    entry = assessment.entries[entry_index]
    # The sweep's own red element set, so a manual override flies here too
    # (F-127). Older assessments carry none and fall back to the lookup.
    red_tle = assessment.red_tle or state.tle_of(assessment.red_name)
    target_tle = _target_tle(state, entry.target)
    if not red_tle or not target_tle:
        return _row(entry, "TLE not found")

    def _refine() -> ThreatSweepEntry | str:
        tof_s = max(entry.tof_hours * 3600.0, 3600.0)
        try:
            sol = lambert_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=entry.burn_epoch, tof_s=tof_s, coast_s=0.0,
            )
        # BLE001: any solver refusal is reported to the operator, not raised.
        except Exception as exc:  # noqa: BLE001
            return _refusal_reason(exc)
        return _sol_to_entry(sol, entry.target, entry.burn_epoch,
                             entry.burn_location, "lambert", entry.regime)

    loop = asyncio.get_running_loop()
    refined = await loop.run_in_executor(None, _refine)

    if isinstance(refined, str):
        # A refusal used to return the Hohmann entry unchanged and log it as
        # a Lambert result: no reason on screen, a false record in the log.
        state.append_log(f"[THREAT] Refine #{entry_index + 1} refused: {refined}")
        return _row(entry, None, f"Lambert refine refused: {refined}")
    if state.last_threat_assessment is not assessment:
        return _row(entry, None, "A newer sweep replaced this one while refining; run the refine again there.")

    assessment.entries[entry_index] = refined
    state.append_log(
        f"[THREAT] Refined #{entry_index + 1}: {refined.target.target_name} "
        f"Lambert dV={refined.delta_v_m_s:.0f} m/s"
    )
    return _row(refined, None)
