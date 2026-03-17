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

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from fastapi import Query

from sipc.astro.events import EventType, find_orbital_events
from sipc.astro.maneuvers import (
    InterceptSolution,
    hohmann_intercept,
    lambert_intercept,
    bielliptic_intercept,
    phasing_intercept,
    plane_change_intercept,
    min_time_intercept_wrapper,
)
from sipc.astro.propagator import TLEOrbit, state_to_keplerian
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
        from sipc.astro.constants import R_EARTH
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

        return render(request, "partials/red_orbit_info.html", {
            "name": track.name,
            "epoch_str": epoch_str,
            "lon_deg": lon_deg,
            "inc_deg": inc_deg,
            "period_min": period_min,
            "alt_km": alt_km,
            "ecc": ecc,
            "a_km": a_km,
        })
    except Exception as exc:
        logger.warning("red_orbit_info failed for %s: %s", red_sat, exc)
        return HTMLResponse(
            f'<p class="error-msg" style="font-size:0.75rem">Orbit info unavailable: {exc}</p>'
        )


def _hrr_group_counts(state: object) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (blue_hrr, red_hrr) where each is [(rank, count), …] sorted by rank."""
    from collections import Counter

    blue_ctr: Counter[int] = Counter()
    red_ctr: Counter[int] = Counter()
    for obj in state.hrr_objects:  # type: ignore[attr-defined]
        rank = obj.get("rank")
        if rank is None:
            continue
        country = str(obj.get("country") or "").strip().upper()
        if country in _RED_COUNTRIES:
            red_ctr[rank] += 1
        else:
            blue_ctr[rank] += 1
    return sorted(blue_ctr.items()), sorted(red_ctr.items())


def _objects_for_group(
    state: object, side: str, rank: int,
) -> list[dict]:
    """Return HRR objects matching *side* ('blue'|'red') and *rank*."""
    results: list[dict] = []
    for obj in state.hrr_objects:  # type: ignore[attr-defined]
        if obj.get("rank") != rank:
            continue
        country = str(obj.get("country") or "").strip().upper()
        is_red = country in _RED_COUNTRIES
        if (side == "red" and is_red) or (side == "blue" and not is_red):
            results.append(obj)
    return results


@router.get("/target-config", response_model=None)
async def target_config(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the sweep target dropdown with HRR group counts."""
    state = get_session_state(current_user.username)
    blue_hrr, red_hrr = _hrr_group_counts(state)
    return render(request, "partials/sweep_target_config.html", {
        "has_udl": bool(state.udl_username),
        "has_hrr": bool(state.hrr_objects),
        "blue_hrr": blue_hrr,
        "red_hrr": red_hrr,
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

    if not tgt_group or ":" not in tgt_group:
        return HTMLResponse("")

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
            "error": f"No {side.title()} HRR Rank {rank} objects found.",
            "fetched": None, "total": 0, "failed": 0,
        })

    if not state.udl_username or not state.udl_password:
        return render(request, "partials/sweep_fetch_status.html", {
            "error": "Not connected to UDL — cannot fetch TLEs.",
            "fetched": None, "total": 0, "failed": 0,
        })

    from sipc.web.routes.udl import fetch_tle_for_satno

    sem = asyncio.Semaphore(10)
    fetched = 0
    failed = 0

    async def _fetch_one(satno_str: str) -> None:
        nonlocal fetched, failed
        if satno_str in state.hrr_tle_cache:
            fetched += 1
            return
        async with sem:
            tle = await fetch_tle_for_satno(
                int(satno_str), state.udl_username, state.udl_password,
                data_mode=state.udl_data_mode or "REAL",
            )
            if tle:
                state.hrr_tle_cache[satno_str] = tle
                fetched += 1
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
    rank: int,
) -> list[ThreatTarget]:
    """Build a target list from HRR objects matching *side* and *rank*.

    Parameters:
        side: ``'blue'`` or ``'red'`` — the HRR side to include.
        rank: HRR rank level (0–5).
    """
    targets: list[ThreatTarget] = []

    for obj in _objects_for_group(state, side, rank):
        satno = str(obj.get("satno") or "").strip()
        name = str(obj.get("name") or satno or "HRR-?").strip()
        targets.append(ThreatTarget(
            target_name=name,
            target_satno=satno,
            target_source="hrr",
            hrr_rank=rank,
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

    return entries


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
        })

    groups.sort(key=lambda g: g["best_dv"])
    return groups


@router.post("/sweep", response_model=None)
async def threat_sweep(
    request: Request,
    red_sat: Annotated[str, Form()],
    max_dv: Annotated[float, Form()] = 3.0,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Run a threat sweep for a red satellite against the selected target group."""
    t0 = time.monotonic()
    state = get_session_state(current_user.username)
    now = datetime.now(tz=UTC)
    errors: list[str] = []

    # Parse target group selection (e.g. "blue:1", "red:3").
    form = await request.form()
    tgt_group = str(form.get("tgt_group") or "").strip()

    if not tgt_group or ":" not in tgt_group:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": "Select a target group from the dropdown before sweeping.",
        })

    side, rank_str = tgt_group.split(":", 1)
    try:
        rank = int(rank_str)
    except ValueError:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": f"Invalid target group rank: {rank_str}",
        })

    # Find red TLE.
    red_tle = _find_tle(state, red_sat.strip())
    if not red_tle:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": f"No TLE found for red satellite: {red_sat}",
        })

    # Build target list from the selected HRR group.
    targets = _build_target_list(state, side, rank)
    if not targets:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": f"No {side.title()} HRR Rank {rank} objects found.",
        })

    # Any targets without a cached TLE get a last-chance fetch now.
    missing = [t for t in targets if t.target_satno and t.target_satno not in state.hrr_tle_cache]
    if missing and state.udl_username and state.udl_password:
        from sipc.web.routes.udl import fetch_tle_for_satno

        sem = asyncio.Semaphore(10)

        async def _fetch_one(t: ThreatTarget) -> None:
            async with sem:
                tle = await fetch_tle_for_satno(
                    int(t.target_satno), state.udl_username, state.udl_password,
                    data_mode=state.udl_data_mode or "REAL",
                )
                if tle:
                    state.hrr_tle_cache[t.target_satno] = tle
                else:
                    errors.append(f"TLE fetch failed for {t.target_name} ({t.target_satno})")

        await asyncio.gather(*[_fetch_one(t) for t in missing])

    # Compute epochs for red satellite.
    epochs = _compute_epochs(red_tle, now)

    # All targets are HRR — TLEs come from the cache.
    hrr_count = len(targets)

    # Run sweep in executor.
    loop = asyncio.get_running_loop()

    def _run_sweep() -> tuple[list[ThreatSweepEntry], list[str]]:
        all_entries: list[ThreatSweepEntry] = []
        sweep_errors: list[str] = []
        for target in targets:
            tle = state.hrr_tle_cache.get(target.target_satno)
            if not tle:
                sweep_errors.append(f"No TLE for {target.target_name} — skipped")
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

    state.last_threat_assessment = assessment
    state.append_log(
        f"[THREAT] Sweep complete: {red_sat} vs {len(targets)} "
        f"{side.title()} HRR Rank {rank} targets, "
        f"{len(entries)} solutions, {elapsed:.1f}s"
    )
    logger.info(
        "threat_sweep: %s vs %d targets (%s HRR %d), %d solutions, %.1fs by %s",
        red_sat, len(targets), side, rank, len(entries), elapsed,
        current_user.username,
    )

    return render(request, "partials/threat_sweep.html", {
        "assessment": assessment,
        "grouped": grouped,
        "hrr_count": hrr_count,
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
