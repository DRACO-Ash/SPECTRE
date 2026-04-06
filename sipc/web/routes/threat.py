"""Threat sweep routes — batch intercept feasibility assessment.

Given one red satellite, computes intercept solutions against operator-
selected targets (blue assets + HRR objects filtered by side and rank)
at multiple manoeuvre epochs (now, apogee, perigee, ascending node,
descending node).  Results are ranked by minimum delta-V.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from sipc.astro.constants import regimes_compatible
from sipc.astro.events import EventType, find_orbital_events
from sipc.astro.maneuvers import (
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
from sipc.astro.propagator import TLEOrbit, regime_from_tle, state_to_keplerian
from sipc.data.intel import get_intel, satno_from_tle
from sipc.domain.models import (
    ThreatAssessment,
    ThreatSweepEntry,
    ThreatTarget,
)
from sipc.web.auth import require_login
from sipc.web.deps import render
from sipc.web.models import User
from sipc.web.planning_state import get_session_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/threat")

_RED_COUNTRIES = {"CHN", "RUS", "IRN", "PRK"}


@router.get("/red-orbit-info", response_model=None)
async def red_orbit_info(
    request: Request,
    red_sat: str = Query("", description="Red satellite name"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Compute orbital parameters for a red satellite and return a compact info card."""
    state = get_session_state(current_user.username)

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

        from sipc.web.routes.udl import _parse_tle_epoch

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
            "lon_deg": lon_deg,
            "inc_deg": inc_deg,
            "period_min": period_min,
            "alt_km": alt_km,
            "ecc": ecc,
            "a_km": a_km,
            "pair": pair,
        })
    except Exception as exc:
        logger.warning("red_orbit_info failed for %s: %s", red_sat, exc)
        return HTMLResponse(
            f'<p class="error-msg" style="font-size:0.75rem">Orbit info unavailable: {exc}</p>'
        )


def _interceptor_regime(state: object, red_sat_name: str) -> str | None:
    """Return the canonical orbit regime for a red track, or None if not found."""
    from sipc.astro.constants import classify_orbit_regime
    from sipc.astro.propagator import TLEOrbit

    for track in state.red_tracks:  # type: ignore[attr-defined]
        if track.stk_name != red_sat_name:
            continue
        try:
            orbit = TLEOrbit(track.tle)
            t = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            rv = orbit.propagate(t)
            kep = state_to_keplerian(rv[0], rv[1])
            return classify_orbit_regime(kep["semi_major_axis"], kep["eccentricity"])
        except Exception:
            return None
    return None


def _hrr_group_counts(
    state: object,
    regime: str | None = None,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (blue_hrr, red_hrr) where each is [(rank, count), …] sorted by rank.

    If *regime* is provided, only objects whose normalised ``orbit_regime``
    matches are counted — allowing the dropdown to be filtered to objects that
    are actually reachable by the selected interceptor.
    """
    from collections import Counter

    from sipc.astro.constants import normalise_regime

    blue_ctr: Counter[int] = Counter()
    red_ctr: Counter[int] = Counter()
    for obj in state.hrr_objects:  # type: ignore[attr-defined]
        rank = obj.get("rank")
        if rank is None:
            rank = 0   # treat unranked objects as rank 0 rather than dropping them
        if regime is not None:
            obj_regime = normalise_regime(str(obj.get("orbit_regime") or ""))
            if obj_regime != regime:
                continue
        country = str(obj.get("country") or "").strip().upper()
        if country in _RED_COUNTRIES:
            red_ctr[rank] += 1
        else:
            blue_ctr[rank] += 1
    return sorted(blue_ctr.items()), sorted(red_ctr.items())


def _objects_for_group(
    state: object, side: str, rank: int, regime: str | None = None,
) -> list[dict]:
    """Return HRR objects matching *side* ('blue'|'red'), *rank*, and optionally *regime*."""
    from sipc.astro.constants import normalise_regime

    results: list[dict] = []
    for obj in state.hrr_objects:  # type: ignore[attr-defined]
        obj_rank = obj.get("rank")
        if obj_rank is None:
            obj_rank = 0
        if obj_rank != rank:
            continue
        if regime is not None:
            obj_regime = normalise_regime(str(obj.get("orbit_regime") or ""))
            if obj_regime != regime:
                continue
        country = str(obj.get("country") or "").strip().upper()
        is_red = country in _RED_COUNTRIES
        if (side == "red" and is_red) or (side == "blue" and not is_red):
            results.append(obj)
    return results


@router.post("/add-manual-tle", response_model=None)
async def add_manual_tle(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Add a manually provided TLE to the session's manual sweep target list."""
    state = get_session_state(current_user.username)
    form = await request.form()
    name = str(form.get("manual_name") or "").strip()
    tle = str(form.get("manual_tle") or "").strip()
    confidence = str(form.get("manual_confidence") or "MEDIUM").strip().upper()

    if not name:
        return render(request, "partials/sweep_manual_tles.html", {
            "manual_tles": state.manual_sweep_tles,
            "error": "Target name is required.",
        })
    if not tle:
        return render(request, "partials/sweep_manual_tles.html", {
            "manual_tles": state.manual_sweep_tles,
            "error": "TLE is required.",
        })

    # Validate TLE by attempting to parse it.
    try:
        TLEOrbit(tle)
    except Exception as exc:
        return render(request, "partials/sweep_manual_tles.html", {
            "manual_tles": state.manual_sweep_tles,
            "error": f"Invalid TLE: {exc}",
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
    state = get_session_state(current_user.username)
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
    state = get_session_state(current_user.username)
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


@router.post("/fetch-targets", response_model=None)
async def fetch_targets(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Pre-fetch TLEs for a selected HRR target group (side:rank)."""
    state = get_session_state(current_user.username)
    form = await request.form()
    tgt_group = str(form.get("tgt_group") or "").strip()

    if not tgt_group:
        return HTMLResponse("")

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

    from sipc.web.routes.udl import fetch_tle_for_satno, fetch_tle_history_for_satno
    from sipc.config.constants import TLE_CLUSTERING

    # Clear the multi-TLE cache so this fetch starts clean; prevents stale TLEs
    # from a prior group selection contaminating clustering for the new group.
    state.hrr_tle_multiset.clear()

    sem = asyncio.Semaphore(10)
    fetched = 0
    failed = 0
    _window_hours: float = float(TLE_CLUSTERING.get("fetch_window_hours", 24))

    async def _fetch_one(satno_str: str) -> None:
        nonlocal fetched, failed
        if satno_str in state.hrr_tle_cache:
            fetched += 1
            return
        async with sem:
            _result = await fetch_tle_for_satno(
                int(satno_str), state.udl_username, state.udl_password,
                data_mode=state.udl_data_mode or "REAL",
                source=state.udl_tle_source,
            )
            if _result:
                tle, dm = _result
                state.hrr_tle_cache[satno_str] = tle
                state.hrr_tle_data_mode[satno_str] = dm
                fetched += 1
                # Also fetch multi-provider history for clustering.
                history = await fetch_tle_history_for_satno(
                    int(satno_str), state.udl_username, state.udl_password,
                    window_hours=_window_hours,
                    data_mode=state.udl_data_mode or "REAL",
                    source=state.udl_tle_source,
                )
                if len(history) > 1:
                    state.hrr_tle_multiset[satno_str] = history
            else:
                failed += 1

    satnos = [str(o.get("satno") or "").strip() for o in objects]
    satnos = [s for s in satnos if s]
    await asyncio.gather(*[_fetch_one(s) for s in satnos])

    total = len(satnos)
    state.append_log(
        f"[THREAT] Pre-fetched {side.title()} HRR Rank {rank}: "
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

    raw_objects: list[dict]
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


def _find_tle(state: object, sat_name: str) -> str | None:
    """Look up a satellite TLE from session state by object name."""
    for a in state.blue_assets:  # type: ignore[attr-defined]
        if a.stk_name == sat_name:
            return a.tle
    for t in state.red_tracks:  # type: ignore[attr-defined]
        if t.stk_name == sat_name:
            return t.tle
    return None


def _compute_epochs(red_tle: str, now: datetime) -> list[tuple[str, datetime]]:
    """Compute the sweep epochs for the red satellite."""
    epochs: list[tuple[str, datetime]] = [("now", now)]

    events = find_orbital_events(red_tle, now, now + timedelta(hours=24), max_per_type=1)
    for ev in events:
        loc = _EVENT_TO_LOCATION.get(ev.event_type)
        if loc:
            epochs.append((loc, ev.epoch))

    return epochs


def _sol_to_entry(
    sol: InterceptSolution,
    target: ThreatTarget,
    epoch: datetime,
    location: str,
    method_name: str,
) -> ThreatSweepEntry:
    """Convert an InterceptSolution to a ThreatSweepEntry."""
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
        delta_v_km_s=abs(sol.total_delta_v),
        tof_hours=tof_hours,
        dv_prograde=dv_pro,
        dv_normal=dv_nor,
        dv_radial=dv_rad,
        method=method_name,
    )


def _sweep_all_methods(
    red_tle: str,
    target_tle: str,
    target: ThreatTarget,
    epochs: list[tuple[str, datetime]],
    max_dv: float,
) -> list[ThreatSweepEntry]:
    """Run all applicable transfer methods for one target across all epochs."""
    entries: list[ThreatSweepEntry] = []

    for location, epoch in epochs:
        # Hohmann
        try:
            sol = hohmann_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, coast_s=0.0,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "hohmann"))
        except Exception:
            pass

        # Lambert (6-hour TOF)
        try:
            sol = lambert_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, tof_s=21600.0, coast_s=0.0,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "lambert"))
        except Exception:
            pass

        # Bi-elliptic
        try:
            sol = bielliptic_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, coast_s=0.0,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "bielliptic"))
        except Exception:
            pass

        # Phasing (1 revolution)
        try:
            sol = phasing_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, n_revolutions=1,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "phasing"))
        except Exception:
            pass

        # Plane change
        try:
            sol = plane_change_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, coast_s=0.0,
            )
            if abs(sol.total_delta_v) <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "plane_change"))
        except Exception:
            pass

        # Min-time
        try:
            sol = min_time_intercept_wrapper(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, max_delta_v=max_dv,
                coast_s=0.0,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "min_time"))
        except Exception:
            pass

        # V-bar hop (3-hop sequence, auto-derived distance)
        try:
            sol = vbar_hop_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, n_hops=3,
                coast_s=0.0,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "vbar_hop"))
        except Exception:
            pass

        # H-bar hop (3-hop sequence, auto-derived distance)
        try:
            sol = hbar_hop_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=epoch, n_hops=3,
                coast_s=0.0,
            )
            if sol.total_delta_v <= max_dv:
                entries.append(_sol_to_entry(sol, target, epoch, location, "hbar_hop"))
        except Exception:
            pass

    return entries


def _compute_worst_coa(entries: list[ThreatSweepEntry]) -> dict | None:
    """Identify and describe the most dangerous course of action from sweep entries.

    The "most dangerous" entry is the one with the lowest ΔV — it is the most
    easily achievable intercept and therefore represents the highest immediate
    threat to the target set.

    Returns a Jinja-safe dict, or ``None`` if *entries* is empty.
    """
    if not entries:
        return None

    import math

    # entries are already sorted by dv ascending — lowest = most achievable = most dangerous
    worst = entries[0]
    dv = worst.delta_v_km_s

    # Threat level: lower ΔV means more achievable, therefore higher threat
    if dv < 0.2:
        threat_level = "CRITICAL"
        threat_color = "#ef4444"
        threat_bg = "rgba(239,68,68,0.06)"
    elif dv < 0.5:
        threat_level = "HIGH"
        threat_color = "#f59e0b"
        threat_bg = "rgba(245,158,11,0.06)"
    elif dv < 1.0:
        threat_level = "MEDIUM"
        threat_color = "#3b8beb"
        threat_bg = "rgba(59,139,235,0.06)"
    else:
        threat_level = "LOW"
        threat_color = "#22c55e"
        threat_bg = "rgba(34,197,94,0.06)"

    _sweep_intents: dict[str, str] = {
        "hohmann":      "Orbital Transfer — Energy Change",
        "lambert":      "Close-Proximity Operation",
        "bielliptic":   "Orbital Transfer — Energy Change",
        "phasing":      "Phasing Rendezvous",
        "plane_change": "Plane Change — Orbit Alignment",
        "min_time":     "Minimum-Time Intercept",
        "vbar_hop":     "V-Bar Hop — Along-Track Approach",
        "hbar_hop":     "H-Bar Hop — Orbit-Normal Approach",
    }
    intent_label = _sweep_intents.get(worst.method, "Intercept Manoeuvre")

    # Burn direction breakdown
    pro = worst.dv_prograde
    nor = worst.dv_normal
    rad = worst.dv_radial
    total_vec = math.sqrt(pro ** 2 + nor ** 2 + rad ** 2)
    if total_vec > 1e-12:
        pro_pct = round(abs(pro) / total_vec * 100.0, 1)
        nor_pct = round(abs(nor) / total_vec * 100.0, 1)
        rad_pct = round(abs(rad) / total_vec * 100.0, 1)
        threshold = 0.7 * total_vec
        if abs(pro) >= threshold:
            direction = "Prograde" if pro >= 0 else "Retrograde"
        elif abs(nor) >= threshold:
            direction = "Normal" if nor >= 0 else "Anti-normal"
        elif abs(rad) >= threshold:
            direction = "Radial" if rad >= 0 else "Anti-radial"
        else:
            direction = "Combined"
    else:
        pro_pct = nor_pct = rad_pct = 0.0
        direction = "Unknown"

    # Time-of-flight label
    tof_s = worst.tof_hours * 3600.0
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

    dv_budget_pct = round(min(100.0, dv / 3.0 * 100.0), 1)

    summary = (
        f"Most achievable intercept: {worst.method.upper()} transfer to "
        f"{worst.target.target_name} burning at {worst.burn_location} "
        f"requires only {dv:.4f} km/s \u0394V with {tof_label} time of flight. "
        f"Dominant burn axis: {direction}. "
        f"Adversary capability assessment — intercept is {threat_level.lower()} threat."
    )

    return {
        "target_name": worst.target.target_name,
        "target_satno": worst.target.target_satno or "",
        "method": worst.method,
        "intent_label": intent_label,
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


def _group_entries(entries: list[ThreatSweepEntry]) -> list[dict]:
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

    groups: list[dict] = []
    for _name, items in buckets.items():
        items.sort(key=lambda t: t[1].delta_v_km_s)
        best = items[0][1]
        groups.append({
            "target": best.target,
            "best_dv": best.delta_v_km_s,
            "best_method": best.method,
            "best_location": best.burn_location,
            "best_tof": best.tof_hours,
            "profile_count": len(items),
            "children": [{"flat_idx": idx, "entry": e} for idx, e in items],
            "osint": get_intel(best.target.target_satno or None),  # key stays 'osint' — threat_sweep.html reads group.osint
        })

    groups.sort(key=lambda g: g["best_dv"])
    return groups


@router.post("/sweep", response_model=None)
async def threat_sweep(
    request: Request,
    red_sat: Annotated[str, Form()],
    max_dv: Annotated[float, Form(ge=0.0, le=100.0)] = 3.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Run a threat sweep for a red satellite against the selected target group."""
    t0 = time.monotonic()
    state = get_session_state(current_user.username)
    now = datetime.now(tz=UTC)
    errors: list[str] = []

    # Parse target group selection (e.g. "blue:1", "red:3", "all").
    form = await request.form()
    tgt_group = str(form.get("tgt_group") or "").strip()

    # Read optional manual red TLE override.
    manual_red_tle_raw = str(form.get("manual_red_tle") or "").strip()
    manual_red_confidence = str(form.get("manual_red_confidence") or "MEDIUM").strip().upper()
    manual_red_tle: str | None = None
    if manual_red_tle_raw:
        try:
            TLEOrbit(manual_red_tle_raw)  # validate
            manual_red_tle = manual_red_tle_raw
        except Exception as exc:
            errors.append(f"Manual red TLE invalid ({exc}) — using registered TLE instead.")

    if not tgt_group or tgt_group == "none":
        side, rank = "none", None
        group_label = "Manual only"
    elif tgt_group == "all":
        side, rank = "all", None
        group_label = "All HRR"
    elif ":" in tgt_group:
        side, rank_str = tgt_group.split(":", 1)
        try:
            rank = int(rank_str)
        except ValueError:
            return render(request, "partials/threat_sweep.html", {
                "assessment": None,
                "error": f"Invalid target group rank: {rank_str}",
            })
        group_label = f"{side.title()} HRR Rank {rank}"
    else:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": f"Invalid target group: {tgt_group}",
        })

    # Find red TLE — manual override takes precedence over the registered track.
    if manual_red_tle:
        red_tle = manual_red_tle
    else:
        red_tle = _find_tle(state, red_sat.strip())
    if not red_tle:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": f"No TLE found for red satellite: {red_sat}",
        })

    # Build HRR target list, excluding the interceptor itself.
    red_satno = str(satno_from_tle(red_tle)) if red_tle else None
    if side == "none":
        targets = []
    else:
        targets = _build_target_list(state, side, rank, exclude_satno=red_satno)

    # Build manual targets from session state.
    _manual_tle_by_name: dict[str, str] = {}
    for _m in state.manual_sweep_tles:
        _mname = _m["name"]
        _mtle = _m["tle"]
        _mconf = _m.get("confidence", "")
        _msatno = str(satno_from_tle(_mtle)) if _mtle else ""
        targets.append(ThreatTarget(
            target_name=_mname,
            target_satno=_msatno,
            target_source="manual",
            hrr_rank=None,
            confidence=_mconf,
        ))
        _manual_tle_by_name[_mname] = _mtle

    if not targets:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": "No targets available — select an HRR group or add manual TLEs.",
        })

    # Hard cap: prevent runaway compute on unexpectedly large groups.
    _MAX_SWEEP_TARGETS = 100
    if len(targets) > _MAX_SWEEP_TARGETS:
        targets = targets[:_MAX_SWEEP_TARGETS]
        errors.append(f"Target list truncated to {_MAX_SWEEP_TARGETS} (cap exceeded).")

    # Any targets without a cached TLE get a last-chance fetch now.
    missing = [t for t in targets if t.target_satno and t.target_satno not in state.hrr_tle_cache]
    if missing and state.udl_username and state.udl_password:
        from sipc.web.routes.udl import fetch_tle_for_satno

        sem = asyncio.Semaphore(10)

        async def _fetch_one(t: ThreatTarget) -> None:
            async with sem:
                _result = await fetch_tle_for_satno(
                    int(t.target_satno), state.udl_username, state.udl_password,
                    data_mode=state.udl_data_mode or "REAL",
                    source=state.udl_tle_source,
                )
                if _result:
                    tle, dm = _result
                    state.hrr_tle_cache[t.target_satno] = tle
                    state.hrr_tle_data_mode[t.target_satno] = dm
                else:
                    errors.append(f"TLE fetch failed for {t.target_name} ({t.target_satno})")

        await asyncio.gather(*[_fetch_one(t) for t in missing])

    # Cluster multi-provider TLEs and reduce to best representative per object.
    from sipc.astro.tle_preprocessing import cluster_and_reduce_tle_cache
    from sipc.config.constants import TLE_CLUSTERING

    clustering_summary = None
    if state.hrr_tle_multiset:
        try:
            reduced, clustering_summary = cluster_and_reduce_tle_cache(
                state.hrr_tle_multiset,
                state.hrr_tle_cache,
                TLE_CLUSTERING,
            )
            state.hrr_tle_cache.update(reduced)
        except Exception as _cl_exc:
            logger.warning("TLE clustering step failed: %s — proceeding without reduction", _cl_exc)

    # Compute epochs for red satellite.
    epochs = _compute_epochs(red_tle, now)

    # Count total targets (HRR + manual).
    hrr_count = len(targets)

    # Classify red satellite's regime once — used to skip incompatible targets.
    try:
        red_regime = regime_from_tle(red_tle)
    except Exception:
        red_regime = "LEO"  # assume LEO on parse failure; sweep proceeds

    # Run sweep in executor.
    loop = asyncio.get_running_loop()

    def _run_sweep() -> tuple[list[ThreatSweepEntry], list[str]]:
        all_entries: list[ThreatSweepEntry] = []
        sweep_errors: list[str] = []
        for target in targets:
            if target.target_source == "manual":
                tle = _manual_tle_by_name.get(target.target_name)
            else:
                tle = state.hrr_tle_cache.get(target.target_satno)
            if not tle:
                sweep_errors.append(f"No TLE for {target.target_name} — skipped")
                continue
            # Skip targets in incompatible orbit regimes.
            try:
                tgt_regime = regime_from_tle(tle)
            except Exception:
                tgt_regime = red_regime  # assume compatible if TLE can't be parsed
            if not regimes_compatible(red_regime, tgt_regime):
                sweep_errors.append(
                    f"{target.target_name}: skipped — "
                    f"{red_regime} red vs {tgt_regime} target (regime mismatch)"
                )
                continue
            target_entries = _sweep_all_methods(red_tle, tle, target, epochs, max_dv)
            if not target_entries:
                sweep_errors.append(
                    f"{target.target_name}: all methods/epochs exceeded {max_dv} km/s or solver failed"
                )
            all_entries.extend(target_entries)
        return all_entries, sweep_errors

    entries, sweep_errors = await loop.run_in_executor(None, _run_sweep)
    errors.extend(sweep_errors)

    # Sort by delta-V ascending.
    entries.sort(key=lambda e: e.delta_v_km_s)

    elapsed = time.monotonic() - t0

    assessment = ThreatAssessment(
        red_name=red_sat.strip(),
        sweep_epoch=now,
        entries=entries,
        target_count=len(targets),
        elapsed_s=round(elapsed, 2),
        errors=errors,
    )

    # Group entries by target for the collapsed-row UI.
    grouped = _group_entries(entries)
    # Attach UDL dataMode provenance to each group for the display-time filter.
    for g in grouped:
        if g["target"].target_source == "manual":
            g["data_mode"] = "MANUAL"
        else:
            satno = g["target"].target_satno
            g["data_mode"] = state.hrr_tle_data_mode.get(satno, "REAL") if satno else "REAL"

    # Identify the most dangerous course of action.
    worst_coa = _compute_worst_coa(entries)

    state.last_threat_assessment = assessment
    state.append_log(
        f"[THREAT] Sweep complete: {red_sat} vs {len(targets)} "
        f"{group_label} targets, "
        f"{len(entries)} solutions, {elapsed:.1f}s"
    )
    logger.info(
        "threat_sweep: %s vs %d targets (%s), %d solutions, %.1fs by %s",
        red_sat, len(targets), group_label, len(entries), elapsed,
        current_user.username,
    )

    return render(request, "partials/threat_sweep.html", {
        "assessment": assessment,
        "grouped": grouped,
        "hrr_count": hrr_count,
        "worst_coa": worst_coa,
        "red_satno": red_satno or "",
        "manual_red_confidence": manual_red_confidence if manual_red_tle else None,
        "clustering_summary": clustering_summary,
        "error": None,
    })


@router.post("/refine", response_model=None)
async def refine_entry(
    request: Request,
    entry_index: Annotated[int, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Refine a single threat sweep entry with Lambert solver."""
    state = get_session_state(current_user.username)

    if not state.last_threat_assessment or entry_index >= len(state.last_threat_assessment.entries):
        return render(request, "partials/threat_sweep_row.html", {
            "entry": None, "index": entry_index, "error": "Invalid entry",
        })

    entry = state.last_threat_assessment.entries[entry_index]

    # Find TLEs.
    red_tle = _find_tle(state, state.last_threat_assessment.red_name)
    if entry.target.target_source == "blue":
        target_tle = _find_tle(state, entry.target.target_name)
    else:
        target_tle = state.hrr_tle_cache.get(entry.target.target_satno)

    if not red_tle or not target_tle:
        return render(request, "partials/threat_sweep_row.html", {
            "entry": entry, "index": entry_index, "error": "TLE not found",
        })

    def _refine() -> ThreatSweepEntry:
        tof_s = max(entry.tof_hours * 3600.0, 3600.0)
        try:
            sol = lambert_intercept(
                red_tle=red_tle, blue_tle=target_tle,
                manoeuvre_start=entry.burn_epoch, tof_s=tof_s, coast_s=0.0,
            )
        except Exception:
            return entry
        return _sol_to_entry(sol, entry.target, entry.burn_epoch,
                             entry.burn_location, "lambert")

    loop = asyncio.get_running_loop()
    refined = await loop.run_in_executor(None, _refine)

    state.last_threat_assessment.entries[entry_index] = refined
    state.append_log(
        f"[THREAT] Refined #{entry_index + 1}: {refined.target.target_name} "
        f"Lambert dV={refined.delta_v_km_s:.4f} km/s"
    )

    return render(request, "partials/threat_sweep_row.html", {
        "entry": refined, "index": entry_index, "error": None,
    })
