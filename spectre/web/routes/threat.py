"""Threat sweep routes — batch intercept feasibility assessment.

Given one red satellite, computes intercept solutions against operator-
selected targets (blue assets + HRR objects filtered by side and rank)
at multiple manoeuvre epochs (now, apogee, perigee, ascending node,
descending node).  Results are ranked by minimum delta-V.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

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
from spectre.astro.propagator import TLEOrbit, regime_from_tle, state_to_keplerian
from spectre.data.intel import get_intel, satno_from_tle
from spectre.domain.manoeuvre_calibration import (
    DEFAULT_SWEEP_BUDGET_M_S,
    classify_posture,
    from_km_s,
    kind_for_method,
)
from spectre.domain.models import (
    ThreatActor,
    ThreatAssessment,
    ThreatSweepEntry,
    ThreatTarget,
)
from spectre.domain.threat_assessment import (
    AccessEvidence,
    ActorVerdict,
    CapabilityEvidence,
    assess_threat,
    rank_actors,
    warning_time_rank,
)
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.format_units import format_tof_label
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import get_session_state

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
            "lon_deg": lon_deg,
            "inc_deg": inc_deg,
            "period_min": period_min,
            "alt_km": alt_km,
            "ecc": ecc,
            "a_km": a_km,
            "pair": pair,
        })
    except Exception as exc:
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

    from spectre.astro.constants import normalise_regime

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
) -> list[dict[str, Any]]:
    """Return HRR objects matching *side* ('blue'|'red'), *rank*, and optionally *regime*."""
    from spectre.astro.constants import normalise_regime

    results: list[dict[str, Any]] = []
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
    state = get_session_state(current_user.username)
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


def _find_tle(state: object, sat_name: str) -> str | None:
    """Look up a satellite TLE from session state by object name."""
    for a in state.blue_assets:  # type: ignore[attr-defined]
        if a.stk_name == sat_name:
            return str(a.tle)
    for t in state.red_tracks:  # type: ignore[attr-defined]
        if t.stk_name == sat_name:
            return str(t.tle)
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
    )


# Verdict colours. MINIMAL is new: it is the band an object lands in when the
# geometry is permissive but the object cannot fly it, which previously had no
# way of being expressed at all.
#: A burn vector shorter than this is numerically zero, so its direction is
#: undefined and the component percentages below would divide by noise.
_ZERO_VECTOR_M_S: float = 1e-12

#: A component carrying at least this share of the burn magnitude names the
#: axis on its own; below it the burn is reported as "Combined".
_DOMINANT_AXIS_FRACTION: float = 0.7

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
                kwargs["max_delta_v"] = budget / 1000.0  # m/s -> km/s for astro
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
                    notes.setdefault(name, f"exceeds the {budget:g} m/s budget")
            # BLE001: one refusal is recorded and the sweep continues.
            except Exception as exc:  # noqa: BLE001
                notes.setdefault(name, _refusal_reason(exc))

    return entries


def _red_capability(red_satno: str | None) -> CapabilityEvidence:
    """Assemble what is known about the red object's ability to act.

    Reads the assessed intelligence record, which is already loaded and was
    already being joined for display. Behavioural evidence (propellant budget,
    anomaly score, manoeuvre count) comes from pattern-of-life analysis, which
    needs an element-set history rather than the single current TLE the sweep
    holds; those fields stay None here and the verdict reports them as missing
    rather than assuming either way.
    """
    if not red_satno:
        return CapabilityEvidence()
    record = get_intel(red_satno)
    if not record:
        return CapabilityEvidence()
    return CapabilityEvidence(
        intel_threat_level=record.get("threat_level"),
        operational_status=record.get("status"),
    )


def _dominant_axis(pro: float, nor: float, rad: float, threshold: float) -> str:
    """Name the axis carrying the burn, or "Combined" when none dominates.

    The ladder is tested prograde, then normal, then radial, and the first
    component at or above *threshold* wins. That order is the reported one and
    matters when two components are both above it.
    """
    if abs(pro) >= threshold:
        return "Prograde" if pro >= 0 else "Retrograde"
    if abs(nor) >= threshold:
        return "Normal" if nor >= 0 else "Anti-normal"
    if abs(rad) >= threshold:
        return "Radial" if rad >= 0 else "Anti-radial"
    return "Combined"


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
            _dominant_axis(pro, nor, rad, _DOMINANT_AXIS_FRACTION * total_vec),
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
    if not entries:
        return None

    # The entry that leaves the least warning time among the feasible ones.
    worst = min(
        entries,
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
        items.sort(key=lambda t: (t[1].tof_hours, t[1].delta_v_m_s))
        best = items[0][1]
        groups.append({
            "target": best.target,
            "best_dv": best.delta_v_m_s,
            "best_posture": best.posture_label,
            "best_method": best.method,
            "best_location": best.burn_location,
            "best_tof": best.tof_hours,
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
    refusals: dict[str, str],
) -> tuple[ActorVerdict | None, list[ThreatSweepEntry]]:
    """Assess one candidate actor against the asset.

    Epochs come from the ACTOR's element set, because the actor is the object
    that would burn. That is why the cost scales with the number of candidates
    rather than being computed once.
    """
    actor_regime = actor.regime or _regime_of_tle(actor_tle)
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
        refusals=refusals,
    )
    for entry in entries:
        entry.actor = actor
    if not entries:
        return (None, [])

    best = min(
        entries,
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
        satno = str(satno_from_tle(tle)) if tle else ""
        targets.append(ThreatTarget(
            target_name=name,
            target_satno=satno,
            target_source="manual",
            hrr_rank=None,
            confidence=confidence,
        ))
        manual_tle_by_name[name] = tle
    return manual_tle_by_name


async def _fetch_missing_target_tles(
    state: object, targets: list[ThreatTarget], errors: list[str],
) -> None:
    """Last-chance fetch for targets with no element set, or only a synthetic one.

    A no-op without UDL credentials, which is the normal case on a fresh
    instance running from the bundled bootstrap watchlist. A failed fetch is
    recorded against the target rather than dropped.
    """
    missing = [
        t for t in targets
        if t.target_satno and _needs_live_tle(state, t.target_satno)
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

    await asyncio.gather(*[_fetch_one(t) for t in missing])


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
        logger.warning("TLE clustering step failed: %s — proceeding without reduction", _cl_exc)
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
) -> tuple[list[ThreatSweepEntry], list[str], dict[str, str]]:
    """Fan every target out across every method and epoch.

    Synchronous on purpose: the handler hands this to an executor thread.
    Lifted out of that handler whole, where being nested inside it added the
    handler's nesting to every branch here on top of its own.

    Returns ``(entries, errors, method_refusals)``. A target that is skipped
    is recorded with the reason rather than dropped, because a short result
    and a safe one read identically on the screen.
    """
    all_entries: list[ThreatSweepEntry] = []
    sweep_errors: list[str] = []
    method_refusals: dict[str, str] = {}
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
        # BLE001: one bad element set, not the whole sweep.
        except Exception:  # noqa: BLE001
            tgt_regime = red_regime  # assume compatible if TLE can't be parsed
        if not regimes_compatible(red_regime, tgt_regime):
            sweep_errors.append(
                f"{target.target_name}: skipped — "
                f"{red_regime} red vs {tgt_regime} target (regime mismatch)"
            )
            continue
        target_entries = _sweep_all_methods(
            _SweepRequest(
                red_tle=red_tle, target_tle=tle, target=target,
                max_dv_m_s=max_dv_m_s, regime=red_regime,
            ),
            epochs,
            refusals=method_refusals,
        )
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


@router.post("/sweep", response_model=None)
async def threat_sweep(
    request: Request,
    red_sat: Annotated[str, Form()],
    max_dv_m_s: Annotated[float, Form(ge=0.0, le=100000.0)] = DEFAULT_SWEEP_BUDGET_M_S,
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
    manual_red_tle: str | None = _validate_manual_red_tle(manual_red_tle_raw, errors)

    parsed = _parse_target_group(tgt_group)
    if parsed.error:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": parsed.error,
        })
    side, rank, group_label = parsed.side, parsed.rank, parsed.group_label

    # Find red TLE — manual override takes precedence over the registered track.
    red_tle: str | None = manual_red_tle or _find_tle(state, red_sat.strip())
    if not red_tle:
        return render(request, "partials/threat_sweep.html", {
            "assessment": None,
            "error": f"No TLE found for red satellite: {red_sat}",
        })

    # Build HRR target list, excluding the interceptor itself.
    red_satno = str(satno_from_tle(red_tle)) if red_tle else None
    targets = (
        [] if side == "none"
        else _build_target_list(state, side, rank, exclude_satno=red_satno)
    )

    # Build manual targets from session state.
    _manual_tle_by_name = _append_manual_targets(state, targets)

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
    await _fetch_missing_target_tles(state, targets, errors)

    # Cluster multi-provider TLEs and reduce to best representative per object.
    clustering_summary = _reduce_tle_clusters(state)

    # What is known about the RED object's ability to act.
    #
    # Capability is a property of the threatening object, not of the things it
    # might reach, and red is a single object, so this is one lookup rather
    # than one per target. The sweep previously looked up intelligence for the
    # TARGET and used it for display only, while the verdict consulted nothing.
    red_capability = _red_capability(red_satno)

    # Compute epochs for red satellite.
    epochs = _compute_epochs(red_tle, now)

    # Count total targets (HRR + manual).
    hrr_count = len(targets)

    # Classify red satellite's regime once — used to skip incompatible targets.
    try:
        red_regime = regime_from_tle(red_tle)
    # BLE001: a malformed element set must not kill the sweep.
    except Exception:  # noqa: BLE001
        red_regime = "LEO"  # assume LEO on parse failure; sweep proceeds

    # Run sweep in executor.
    loop = asyncio.get_running_loop()
    entries, sweep_errors, method_refusals = await loop.run_in_executor(
        None,
        lambda: _run_target_sweep(
            state, targets, _manual_tle_by_name, red_tle, red_regime, epochs, max_dv_m_s,
        ),
    )
    errors.extend(sweep_errors)

    # Rank on warning time among the feasible intercepts. Delta-V keeps its
    # role as the feasibility filter it already was, but it is not the ranking:
    # an intercept arriving in 35 minutes is a harder problem than a cheaper
    # one arriving in 40 hours, and sorting on cost called the second worse.
    entries.sort(key=lambda e: warning_time_rank(e.delta_v_m_s, e.tof_hours, max_dv_m_s))

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
    red_mode = "MANUAL" if manual_red_tle else state.hrr_tle_data_mode.get(red_satno or "", "REAL")
    provenance = _provenance_warnings(
        [(f"red {red_sat.strip()}", red_mode)]
        + [(f"target {g['target'].target_name}", g["data_mode"]) for g in grouped],
    )

    # Identify the most dangerous course of action.
    worst_coa = _compute_worst_coa(entries, red_capability, max_dv_m_s)

    state.last_threat_assessment = assessment
    state.append_log(
        f"[THREAT] Sweep complete: {red_sat} vs {len(targets)} "
        f"{group_label} targets, "
        f"{len(entries)} solutions, {elapsed:.1f}s"
    )
    logger.info(
        "threat_sweep: %s vs %d targets (%s), %d solutions, %.1fs by %s",
        log_safe(red_sat), len(targets), log_safe(group_label), len(entries), elapsed,
        log_safe(current_user.username),
    )

    return render(request, "partials/threat_sweep.html", {
        "assessment": assessment,
        "grouped": grouped,
        "hrr_count": hrr_count,
        "worst_coa": worst_coa,
        # Methods that produced nothing, and why. Previously discarded, which
        # hid the fastest approaches: refusals cluster on the aggressive end.
        "method_refusals": sorted(method_refusals.items()),
        "red_satno": red_satno or "",
        "manual_red_confidence": manual_red_confidence if manual_red_tle else None,
        "clustering_summary": clustering_summary,
        "provenance_warnings": provenance,
        "error": None,
    })






async def _refresh_actor_tles(state: object, actors: list[ThreatActor]) -> None:
    """Fetch live element sets for actors that have none, or only synthetic.

    A no-op without UDL credentials, which is the normal case on a fresh
    instance running from the bundled bootstrap watchlist.
    """
    missing = [a for a in actors if _needs_live_tle(state, a.actor_satno)]
    if not missing or not state.udl_username or not state.udl_password:  # type: ignore[attr-defined]
        return

    from spectre.web.routes.udl import fetch_tle_for_satno

    sem = asyncio.Semaphore(10)
    user: str = state.udl_username  # type: ignore[attr-defined]
    password: str = state.udl_password  # type: ignore[attr-defined]

    async def _fetch_one(actor: ThreatActor) -> None:
        async with sem:
            got = await fetch_tle_for_satno(
                int(actor.actor_satno), user, password,
                data_mode=state.udl_data_mode or "REAL",  # type: ignore[attr-defined]
                source=state.udl_tle_source,  # type: ignore[attr-defined]
            )
            if got:
                tle, mode = got
                state.hrr_tle_cache[actor.actor_satno] = tle  # type: ignore[attr-defined]
                state.hrr_tle_data_mode[actor.actor_satno] = mode  # type: ignore[attr-defined]

    await asyncio.gather(*[_fetch_one(a) for a in missing])



class _ScreenRun(NamedTuple):
    """Everything one pass over the candidate actors produced."""

    verdicts: list[ActorVerdict]
    entries: list[ThreatSweepEntry]
    refusals: dict[str, str]
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
    refusals: dict[str, str] = {}
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
        rows.sort(key=lambda e: (e.tof_hours, e.delta_v_m_s))
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
    state = get_session_state(current_user.username)
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
    state = get_session_state(current_user.username)
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
    await _refresh_actor_tles(state, actors)

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
    )
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
        "method_refusals": sorted(method_refusals.items()),
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
    state = get_session_state(current_user.username)
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
    red_tle = assessment.red_tle or _find_tle(state, assessment.red_name)
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
