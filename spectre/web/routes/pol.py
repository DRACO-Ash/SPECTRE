"""Historical Pattern of Life (PoL) routes for SPECTRE.

Fetches historical TLEs from UDL, runs the PoL analysis engine, and returns
rendered partials for the Historical PoL hero tab.
"""

from __future__ import annotations

import contextlib
import html
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NamedTuple

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from spectre.astro.dv_estimation import _SNR_HIGH, _SNR_LOW
from spectre.astro.pattern_of_life import _parse_tle_epoch as tle_epoch
from spectre.astro.pattern_of_life import analyse_pattern_of_life, parse_tle_history_counted
from spectre.astro.tle_filter import filter_tle_history
from spectre.config.settings import UDL_BASE_URL
from spectre.data.intel import get_intel
from spectre.domain.custody import CustodyStatus, assess_custody
from spectre.domain.manoeuvre_calibration import per_event_station_keeping_m_s
from spectre.domain.normality import BurnNormality, burns_from_views, judge_burn
from spectre.domain.pol_assessment import PolAssessment, assess_pattern_of_life
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.elsets import limit_hours_for_regime
from spectre.web.format_units import to_m_s
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import get_session_state
from spectre.web.rate_limit import pol_compute_rate_limit, udl_auth_rate_limit, udl_data_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pol")

_UDL_BASE = UDL_BASE_URL

# Maximum TLEs to fetch from UDL historical endpoint.
_UDL_MAX_RESULTS = 5000

# The PoL hero tab's own template. Every route that answers with the whole
# panel - the panel itself and each of pol_analyse's failure exits - has to
# name the same one, or a failed analysis returns a fragment the tab cannot
# swap in.
_POL_PANEL_TEMPLATE = "partials/pol_panel.html"

# Returned by every drill-down that is asked about a SATNO the session has no
# analysis for. Held here so the three exits stay byte-identical: the operator
# reaching this from a stale tab should not be able to tell which one answered.
# Both forms run in the shared default executor, so one operator's request is
# every operator's wait (audit F-145). Thirty days is the longest horizon a
# single TLE fit can say anything about. The CSV cap, about 10,000
# observations, sits under Starlette's own 1 MiB form-field limit so the
# operator reads why rather than a bare 400.
MAX_HORIZON_H = 720.0
_MIN_HORIZON_H = 1.0
MAX_PHOTOMETRY_CSV_CHARS = 524_288

_NO_ANALYSIS_HTML = (
    '<p class="error-msg">No PoL analysis for this SATNO. Run Pattern of Life first.</p>'
)


# ── UDL helper ────────────────────────────────────────────────────────────────

def _first(rec: dict[str, Any], *keys: str) -> str:
    """The first truthy value among *keys*, as stripped text; empty if none."""
    for key in keys:
        if rec.get(key):
            return str(rec[key]).strip()
    return ""


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
    except ValueError:
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
        l1 = _first(rec, "line1", "TLE_LINE1", "tle1")
        l2 = _first(rec, "line2", "TLE_LINE2", "tle2")
        if l1.startswith("1 ") and l2.startswith("2 "):
            lines += [l1, l2]
            metadata[l1] = (_first(rec, "dataMode", "data_mode"), _first(rec, "source"))
            rms_raw = rec.get("rmsResidual") or rec.get("rms_residual") or rec.get("rms")
            rms_metadata[l1] = float(rms_raw) if rms_raw is not None else None
            # Capture satellite name from first valid record that has one
            sat_name = sat_name or _first(rec, "satName", "objectName", "OBJECT_NAME", "name")

    logger.info("PoL UDL: parsed %d TLE pairs from %d records", len(lines) // 2, len(records))
    return "\n".join(lines), metadata, rms_metadata, sat_name


async def _fetch_udl_history(
    satno: int, username: str, password: str, data_mode: str, source: str = "",
) -> tuple[str, dict[str, tuple[str, str]], dict[str, float | None], str]:
    """Fetch historical TLEs from UDL elset endpoint (2015 → now, max 5 000).

    Returns ``(tle_text, metadata, rms_metadata, sat_name)``.
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
    """Return the PoL panel — credential form + results placeholder.

    ``pol_panel.html`` includes ``pol_results.html`` whenever an analysis is in
    session state, so this route has to supply that template's whole context
    too. It did not, and the result was a hard 500 on every reload of the panel
    once the operator had run an analysis: the include fired, the first name it
    read was undefined, and StrictUndefined raised.

    That is the correct behaviour from StrictUndefined. The alternative, Jinja's
    silent default, would have rendered the panel with every figure blank and
    nothing to say why.
    """
    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)
    context: dict[str, object] = {
        "has_udl": bool(state.udl_username),
        "pol": pol,
        "error": None,
    }
    if pol is not None:
        context.update(_pol_view(pol, reserve_reset_for(state, pol.satno)))
        context.setdefault("source", "UDL")
        context.setdefault("pair", get_intel(pol.satno))
    return render(request, _POL_PANEL_TEMPLATE, context)


def _panel_error(request: Request, state: Any, message: str) -> HTMLResponse:
    """The whole PoL panel, re-rendered with one error message and no analysis.

    Every failure exit from an analysis answers with the panel template rather
    than a results fragment, because the hero tab swaps the panel whole: a bare
    fragment would leave the operator with a tab that cannot be run again. The
    context is built in one place so the exits cannot drift apart - an exit
    that dropped ``has_udl`` would hide the credentials form on the one screen
    the operator needs it on.
    """
    return render(request, _POL_PANEL_TEMPLATE, {
        "has_udl": bool(state.udl_username),
        "pol": None,
        "error": message,
    })


async def _fetch_merged_history(
    satno: int, username: str, password: str, data_mode: str, source: str = "",
) -> tuple[str, str, dict[str, tuple[str, str]], dict[str, float | None], str]:
    """Archive and current UDL elsets for one object, merged into one block.

    Returns ``(archive_text, merged_text, metadata, rms_metadata, name)``. The
    archive text comes back alongside the merged block because the caller
    reports the size of the archive fetch, not of the merge.

    ``/elset`` caps at ``_UDL_MAX_RESULTS``, so a long-lived object runs out of
    archive before it reaches the present. The current elset is therefore
    fetched separately and layered on top of the archive.

    An empty *data_mode* is normalised to REAL, which is what the session path
    did at both of its call sites before they moved in here.
    """
    mode = data_mode or "REAL"
    archive_text, meta, rms_meta, archive_name = await _fetch_udl_history(
        satno, username, password, mode, source=source,
    )
    latest_text, latest_meta, latest_rms, latest_name = await _fetch_udl_latest(
        satno, username, password, mode, source=source,
    )
    name = latest_name or archive_name or str(satno)
    # Latest entries override archive ones: the newer provenance is the one the
    # operator is shown.
    merged_meta = {**meta, **latest_meta}
    merged_rms = {**rms_meta, **latest_rms}
    merged_text = archive_text + ("\n" if archive_text else "") + latest_text
    return archive_text, merged_text, merged_meta, merged_rms, name


def _archive_end_if_capped(archive_text: str) -> datetime | None:
    """The newest archived epoch when the archive pull hit its record cap.

    One request returns at most _UDL_MAX_RESULTS sets with no paging, and the
    current set is appended after it, so a capped archive leaves a gap that
    used to pass without a word (audit F-144). None when under the cap.
    """
    line1s = [ln.strip() for ln in archive_text.splitlines() if ln.strip().startswith("1 ")]
    if len(line1s) < _UDL_MAX_RESULTS:
        return None
    epochs = []
    for ln in line1s:
        # A line 1 too damaged to date is skipped; parsing drops it anyway.
        with contextlib.suppress(ValueError, IndexError):
            epochs.append(tle_epoch(ln))
    return max(epochs, default=None)


def _cadence_filtered(
    records: list[Any], apply_filter: bool, satno: int,
) -> tuple[list[Any], list[Any]]:
    """The element history, cadence-filtered if the operator asked for it.

    Returns ``(records, quality_flags)``. The unfiltered case hands the records
    straight back with no flags, so the caller carries one shape into the
    analysis rather than a branch around the filter.
    """
    if not apply_filter:
        return records, []
    raw_count = len(records)
    filtered, quality_flags = filter_tle_history(records)
    logger.info(
        "PoL cadence filter: %s → %s records, %s flags for %s",
        log_safe(raw_count), log_safe(len(filtered)), log_safe(len(quality_flags)), log_safe(satno),
    )
    return filtered, quality_flags


def _filter_note(apply_filter: bool, quality_flags: list[Any]) -> str:
    """The cadence-filter suffix for the session log line.

    An unfiltered run says nothing rather than reporting zero flags: zero flags
    from a filter that never ran reads as a clean history, and the operator
    would have no way to tell the two apart in the log.
    """
    if not apply_filter:
        return ""
    return f" [cadence-filtered, {len(quality_flags)} flags]"


class _MergedHistory(NamedTuple):
    """What :func:`_fetch_merged_history` returns, named."""

    archive_text: str
    merged_text: str
    metadata: dict[str, tuple[str, str]]
    rms_metadata: dict[str, float | None]
    name: str


def _analyse_merged(
    history: _MergedHistory, satno: int, threshold_km_s: float, apply_filter: bool,
) -> tuple[Any, list[Any]] | None:
    """Parse a merged UDL history and run Pattern of Life over it.

    Returns ``(analysis, quality_flags)``, or ``None`` when nothing parsed.
    One copy for the panel and for the history held for the sweep (SPC-001).
    """
    records, dropped = parse_tle_history_counted(
        history.merged_text, satno=satno,
        metadata=history.metadata, rms_metadata=history.rms_metadata,
    )
    if not records:
        return None
    records, quality_flags = _cadence_filtered(records, apply_filter, satno)
    pol = analyse_pattern_of_life(
        records,
        satno=satno,
        name=history.name,
        dv_threshold=threshold_km_s,
        quality_flags=quality_flags,
    )
    pol.malformed_element_sets = dropped.malformed
    pol.duplicate_epoch_sets = dropped.duplicate_epoch
    pol.bad_provenance_sets = dropped.bad_provenance
    pol.other_object_sets = dropped.other_object
    pol.history_truncated_at = _archive_end_if_capped(history.archive_text)
    return pol, quality_flags


# ── The history held for other panels (SPC-001) ──────────────────────────────

#: How long a held history answers before it is fetched again. A burn shows in
#: the next element set, hours after it happens, so a history much older than
#: this can miss the very burn the operator is asking about.
HELD_HISTORY_MAX_AGE = timedelta(minutes=30)
#: The threshold the panel offers by default, so the sweep and an untouched
#: panel see the same burns.
_HELD_DV_THRESHOLD_KM_S = 0.002
#: Histories held per sign-in. Each holds up to 5,000 element sets; the
#: oldest goes first.
_MAX_HELD_HISTORIES = 20


@dataclass(frozen=True)
class HeldHistory:
    """One object's element-set history as analysed, or why there is none."""

    satno: int
    fetched_at: datetime
    pol: Any | None = None
    problem: str = ""


def _hold(state: Any, held: HeldHistory) -> HeldHistory:
    histories = state.elset_histories
    histories.pop(held.satno, None)
    histories[held.satno] = held
    while len(histories) > _MAX_HELD_HISTORIES:
        histories.pop(next(iter(histories)))
    return held


async def held_history(state: Any, satno: int, now: datetime) -> HeldHistory:
    """The object's analysed element-set history, fetched from UDL if not held.

    The sweep, the is-this-normal verdict and custody all read this one copy,
    so no panel fetches the same history again. Never raises: a failure comes
    back as a ``problem`` the panel shows in place of a verdict, with the
    detail in the log, never the browser. Failures are not held, so the next
    request tries again.
    """
    held = state.elset_histories.get(satno)
    if held is not None and now - held.fetched_at < HELD_HISTORY_MAX_AGE:
        return held  # type: ignore[no-any-return]
    if not state.udl_username or not state.udl_password:
        return HeldHistory(satno, now, problem="UDL is not connected, so no element-set history is held.")
    pol, problem = await _fetch_and_analyse(state, satno)
    if pol is None:
        return HeldHistory(satno, now, problem=problem)
    return _hold(state, HeldHistory(satno, now, pol=pol))


async def _fetch_and_analyse(state: Any, satno: int) -> tuple[Any | None, str]:
    """The analysed history from UDL, or ``None`` and the problem to show."""
    try:
        fetched = _MergedHistory(*await _fetch_merged_history(
            satno, state.udl_username, state.udl_password,
            state.udl_data_mode, source=state.udl_tle_source,
        ))
    except Exception as exc:  # noqa: BLE001 - any UDL failure becomes a stated problem
        logger.warning("Held history: UDL fetch failed for %s: %s", log_safe(satno), log_safe(exc))
        return None, "The element-set history could not be fetched from UDL."
    if not fetched.merged_text.strip():
        return None, "UDL returned no element sets for this object."
    try:
        analysed = await run_in_threadpool(
            _analyse_merged, fetched, satno, _HELD_DV_THRESHOLD_KM_S, False,
        )
    except Exception:  # a failed analysis becomes a stated problem, logged in full
        logger.exception("Held history: analysis failed for %s", log_safe(satno))
        return None, "The element-set history could not be analysed."
    if analysed is None:
        return None, "No usable element sets were in the UDL history."
    return analysed[0], ""


def history_evidence(
    pol: Any, reserve_reset: datetime | None = None,
) -> tuple[PolAssessment, BurnNormality | None]:
    """The history's interpretation, and the verdict on its latest burn.

    One assessment for both, so the sweep reads its capability evidence and
    its is-this-normal verdict from the same reading of the history.
    """
    assessment = assess_pattern_of_life(pol, reserve_reset)
    latest = max(_burn_normality(pol, assessment.manoeuvres), key=lambda n: n.burn.epoch, default=None)
    return assessment, latest


@router.post("/analyse", response_class=HTMLResponse)
async def pol_analyse(
    request: Request,
    satno: Annotated[int, Form()],
    current_user: Annotated[User, Depends(require_login)],
    _rl: Annotated[None, Depends(udl_data_rate_limit)],
    pol_source: Annotated[str, Form()] = "udl",
    udl_user: Annotated[str, Form()] = "",
    udl_pass: Annotated[str, Form()] = "",
    dv_threshold_ms: Annotated[float, Form()] = 2.0,
    cadence_filter: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Fetch historical TLEs from UDL and run PoL analysis.

    Held to the UDL data limit, and to the five-per-minute credential limit
    of /udl/login when the form carries credentials: without either it was
    an unthrottled credential oracle (audit F-045).
    """
    state = get_session_state(current_user)

    # ── UDL direct credentials ────────────────────────────────────────────────
    if pol_source == "udl_direct":
        await udl_auth_rate_limit(current_user)
        if not udl_user.strip() or not udl_pass:
            return _panel_error(request, state, "Enter UDL username and password.")
        try:
            # The password goes as typed: a leading or trailing space is part
            # of it, and stripping sent a different credential (audit F-251).
            archive_text, merged_text, merged_meta, merged_rms, name = await _fetch_merged_history(
                satno, udl_user.strip(), udl_pass, "REAL",
                source=state.udl_tle_source,
            )
            logger.info("PoL: %s chars from UDL (direct) for %s", log_safe(len(archive_text)), log_safe(satno))
        except Exception as exc:   # noqa: BLE001 - a multi-step UDL fetch; any failure is reported to the operator
            logger.warning("PoL: UDL direct failed: %s", exc)
            return _panel_error(request, state, f"UDL fetch failed: {exc}")

    # ── UDL session credentials ───────────────────────────────────────────────
    else:  # pol_source == "udl"
        if not state.udl_username or not state.udl_password:
            return _panel_error(
                request, state,
                "No active UDL session. Connect UDL first, or choose 'UDL (credentials)'.",
            )
        try:
            archive_text, merged_text, merged_meta, merged_rms, name = await _fetch_merged_history(
                satno, state.udl_username, state.udl_password,
                state.udl_data_mode,
                source=state.udl_tle_source,
            )
            logger.info("PoL: %s chars from UDL (session) for %s", log_safe(len(archive_text)), log_safe(satno))
        except Exception as exc:   # noqa: BLE001 - a multi-step UDL fetch; any failure is reported to the operator
            logger.warning("PoL: UDL session failed: %s", exc)
            return _panel_error(request, state, f"UDL fetch failed: {exc}")

    if not merged_text.strip():
        return _panel_error(
            request, state,
            f"No TLE data returned from UDL for SATNO {satno}. "
            "Check the SATNO and credentials, and verify the object exists in the catalogue.",
        )

    # ── Parse + analyse ───────────────────────────────────────────────────────
    try:
        apply_filter = bool(cadence_filter)
        threshold_km_s = dv_threshold_ms / 1000.0
        analysed = _analyse_merged(
            _MergedHistory(archive_text, merged_text, merged_meta, merged_rms, name),
            satno, threshold_km_s, apply_filter,
        )
        if analysed is None:
            return _panel_error(
                request, state,
                f"No valid TLEs parsed from UDL response for SATNO {satno}.",
            )
        pol, quality_flags = analysed
        state.last_pol_analysis = pol  # type: ignore[attr-defined]
        filter_note = _filter_note(apply_filter, quality_flags)
        state.append_log(
            f"[POL] Analysed {satno}: {pol.tle_count} TLEs, "
            f"{len(pol.manoeuvres)} manoeuvres, status={pol.pol_status} [UDL]{filter_note}"
        )
    except Exception as exc:
        logger.exception("PoL analysis failed for %s", log_safe(satno))
        return _panel_error(request, state, f"Analysis error: {exc}")

    return render(request, "partials/pol_results.html", {
        "pol": pol,
        "source": "UDL",
        "pair": get_intel(satno),
        **_pol_view(pol, reserve_reset_for(state, satno)),
    })


def _all_detections(pol: object) -> list[Any]:
    """Confirmed manoeuvres and unconfirmed candidates together.

    The two-tier split exists so that unconfirmed detections stay out of the
    cumulative ΔV and the propellant budget. It is NOT a filter on what
    external evidence may be compared against. A NOTSO is an operator's own
    declaration that a burn happened, so correlating it against the confirmed
    list alone reports a declared manoeuvre as a phantom whenever our own
    detection of it fell to candidate confidence — and a NOTSO matching a
    candidate is corroboration of that candidate, which is the single
    strongest thing that could be said about it.
    """
    return list(getattr(pol, "manoeuvres", []) or []) + list(
        getattr(pol, "candidate_manoeuvres", []) or []
    )


def reserve_reset_for(state: object, satno: int) -> datetime | None:
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


def _burn_normality(pol: object, views: list[Any]) -> list[BurnNormality]:
    """Each confirmed burn judged against the object's own earlier burns (SPC-009).

    In the order of *views*, so the manoeuvre table can pair them row by row.
    The history starts at the first element set held, not the first burn, so
    a long quiet stretch still counts as time the object was watched.
    """
    burns = burns_from_views(views)
    if not burns:
        return []
    records = getattr(pol, "records", None) or []
    start = records[0].epoch if records else min(b.epoch for b in burns)
    return [judge_burn(b, burns, start) for b in burns]


def _pol_custody(pol: Any, latest_burn: BurnNormality | None, now: datetime) -> CustodyStatus | None:
    """Custody of the analysed object at *now* (SPC-018), or ``None`` with no element sets."""
    records = getattr(pol, "records", None) or []
    if not records:
        return None
    hours = max((now - records[-1].epoch).total_seconds() / 3600.0, 0.0)
    return assess_custody(
        elset_hours=hours,
        limit_hours=limit_hours_for_regime(str(getattr(pol, "regime", "") or "")),
        elset_count=int(getattr(pol, "tle_count", len(records))),
        history_days=float(getattr(pol, "span_days", 0.0) or 0.0),
        normality=latest_burn.verdict if latest_burn else None,
        history_problem="",
        truncated_at=getattr(pol, "history_truncated_at", None),
    )


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
    normality = _burn_normality(pol, assessment.manoeuvres)
    latest_burn = max(normality, key=lambda n: n.burn.epoch, default=None)

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
        "manoeuvre_rows": [{"m": v.manoeuvre, "v": v, "delta_v_m_s": v.delta_v_m_s, "normal": n}
                           for v, n in zip(assessment.manoeuvres, normality, strict=True)],
        "latest_burn": latest_burn,
        "custody": _pol_custody(pol, latest_burn, datetime.now(tz=UTC)),
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
        "malformed_element_sets": getattr(pol, "malformed_element_sets", 0),
        "duplicate_epoch_sets": getattr(pol, "duplicate_epoch_sets", 0),
        "bad_provenance_sets":  getattr(pol, "bad_provenance_sets", 0),
        "other_object_sets":    getattr(pol, "other_object_sets", 0),
        "breakdowns_truncated": getattr(pol, "breakdowns_truncated", 0),
        "confirmed":            len(getattr(pol, "manoeuvres", [])),
        "candidates":           len(getattr(pol, "candidate_manoeuvres", [])),
        "noise_floor_m_s":      to_m_s(noise.floor_km_s) if noise else None,
        "noise_median_m_s":     to_m_s(noise.median_km_s) if noise else None,
        "noise_mad_m_s":        to_m_s(noise.mad_km_s) if noise else None,
        "noise_samples":        noise.samples if noise else 0,
        "noise_method":         noise.method if noise else "",
        "noise_floor_measured": noise.floor_is_measured if noise else False,
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
        # The colour bands are the module\'s own SNR cut-offs; the template
        # hard-coded 10 and 5 (audit F-226).
        "snr_high":             _SNR_HIGH,
        "snr_low":              _SNR_LOW,
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
        "noise_method":         "",
        "noise_floor_measured": False,
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
        # The colour bands are the module\'s own SNR cut-offs; the template
        # hard-coded 10 and 5 (audit F-226).
        "snr_high":             _SNR_HIGH,
        "snr_low":              _SNR_LOW,
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
        "noise_method":     bd.noise.method if bd.noise else "",
        "noise_floor_measured": bd.noise.floor_is_measured if bd.noise else False,
    })
    return view


@router.post("/reserve-reset", response_class=HTMLResponse)
async def pol_reserve_reset(
    request: Request,
    satno: Annotated[int, Form()],
    # Annotated dependencies carry no default, so this has to precede
    # reset_date. FastAPI binds route arguments by name, so the order is
    # invisible to callers.
    current_user: Annotated[User, Depends(require_login)],
    reset_date: Annotated[str, Form()] = "",
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
    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)
    if pol is None or pol.satno != satno:
        return HTMLResponse(_NO_ANALYSIS_HTML)

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
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """The full working behind one manoeuvre's ΔV figure.

    Both element sets side by side with their provenance, every term in the
    decomposition with the numbers that produced it, all three estimators, and
    why the result was or was not believed.
    """
    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)

    if pol is None or pol.satno != satno:
        return HTMLResponse(_NO_ANALYSIS_HTML)

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
    assessment = assess_pattern_of_life(pol, reserve_reset_for(state, satno))
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
# PLR0913, PLR0917: FastAPI form parameters.
async def pol_monte_carlo(  # noqa: PLR0913, PLR0917
    request: Request,
    satno: Annotated[int, Form()],
    manoeuvre_epoch: Annotated[str, Form()],
    current_user: Annotated[User, Depends(require_login)],
    _rl: Annotated[None, Depends(pol_compute_rate_limit)],
    manoeuvre_type: Annotated[str, Form()] = "orbit_raise",
    n_samples: Annotated[int, Form()] = 500,
    horizon_h: Annotated[float, Form()] = 48.0,
) -> HTMLResponse:
    """Run Monte Carlo simulation for a specific detected manoeuvre."""
    import asyncio

    from spectre.astro.monte_carlo import (
        MANOEUVRE_ARCHETYPES,
        hypothesis_from_tle_record,
        run_monte_carlo,
    )

    # "not (a <= x <= b)" also refuses NaN, which every comparison fails.
    if not (_MIN_HORIZON_H <= horizon_h <= MAX_HORIZON_H):
        return HTMLResponse(
            f'<p class="error-msg">Horizon must be between {_MIN_HORIZON_H:.0f} and {MAX_HORIZON_H:.0f} hours.</p>'
        )

    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)

    if pol is None or pol.satno != satno:
        return HTMLResponse(_NO_ANALYSIS_HTML)

    # Find the manoeuvre matching the requested epoch
    target_epoch_str = manoeuvre_epoch[:19]  # trim to seconds
    matching = [
        m for m in _all_detections(pol)
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
    except Exception:
        logger.exception("Monte Carlo failed for %s", log_safe(satno))
        return HTMLResponse('<p class="error-msg">Monte Carlo failed; the server log has the detail.</p>')

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
    state = get_session_state(current_user)
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
    state = get_session_state(current_user)
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


def _notsos_from_cache_records(raw_records: list[dict[str, Any]], satno: int) -> list[Any]:
    """Cached NOTSO dicts as ``NOTSORecord`` objects, for one satellite.

    The cache holds raw dicts, so they go back through the same text parser the
    pasted-text path uses. One grammar, one set of results, whichever source
    the operator correlated from. A JCO record can name several objects, so
    its text is built for the satellite under analysis (audit F-046).
    """
    from spectre.astro.notso import parse_notso_text
    from spectre.data.notso_cache import message_text

    notsos: list[Any] = []
    for rec in raw_records:
        notsos.extend(parse_notso_text(message_text(rec, satno)))
    return notsos


def _analysis_window(pol: Any) -> tuple[datetime | None, datetime | None]:
    """First and last epoch the analysis covers.

    The element history is the authority on the span; the manoeuvre list is the
    fallback for an analysis whose records were not retained. Both ends come
    from the same source, because a window with one end from each would report
    a behaviour profile over a span that was never observed.
    """
    if pol.records:
        return pol.records[0].epoch, pol.records[-1].epoch
    if pol.manoeuvres:
        return pol.manoeuvres[0].epoch, pol.manoeuvres[-1].epoch
    return None, None


def _correlation_rows(correlations: list[Any]) -> list[dict[str, object]]:
    """One display row per correlation, each carrying its own m/s figures.

    Converted here, not in the template, on the same terms as :func:`_pol_view`.
    """
    return [
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
    ]


def _load_notsos(state: Any, pol: Any, notso_text: str) -> tuple[list[Any], list[str], str] | HTMLResponse:
    """The NOTSOs to correlate, the rejected messages and where they came from.

    Pasted text needs no UDL session; the local cache holds UDL data fetched
    with another operator's credential, so it does (audit F-142). Returns the
    refusal to show instead when there is nothing usable.
    """
    from spectre.astro.notso import parse_notso_text_with_rejects
    from spectre.data.notso_cache import get_notso_cache

    if notso_text:
        notsos, rejects = parse_notso_text_with_rejects(notso_text)
        if not notsos:
            return HTMLResponse(
                '<p class="error-msg">No NOTSO records could be parsed. '
                'Check the message format (SATNO, effective window, and type fields are required).</p>'
            )
        return notsos, rejects, "pasted text"
    if not (state.udl_username and state.udl_password):
        return HTMLResponse(
            '<p class="error-msg">Log in to UDL to correlate against the NOTSO cache, '
            'or paste NOTSO messages.</p>'
        )
    raw_records = get_notso_cache().get_for_satno(pol.satno)
    if not raw_records:
        return HTMLResponse(
            '<p class="error-msg">No NOTSOs in local cache for SATNO '
            f'{pol.satno}. Run a cache sync first, or paste NOTSO messages manually.</p>'
        )
    # Each cache record carries a msgText field (the full notification text),
    # or the text is reconstructed from its fields.
    notsos = _notsos_from_cache_records(raw_records, pol.satno)
    if not notsos:
        return HTMLResponse(
            f'<p class="error-msg">Cache has {len(raw_records)} record(s) for SATNO '
            f'{pol.satno} but none could be parsed. Try pasting the text manually.</p>'
        )
    return notsos, [], f"local cache ({len(raw_records)} records)"


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
        correlate_notsos_with_manoeuvres,
        extract_behaviour_profile,
    )

    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)

    if pol is None:
        return HTMLResponse(
            '<p class="error-msg">Run Pattern of Life analysis first before correlating NOTSOs.</p>'
        )

    form = await request.form()
    notso_text = str(form.get("notso_text") or "").strip()

    loaded = _load_notsos(state, pol, notso_text)
    if isinstance(loaded, HTMLResponse):
        return loaded
    notsos, rejects, source_label = loaded

    try:
        # A NOTSO follows human analysis and is deliberately withheld for
        # small routine burns, so the routine per-burn ceiling for this
        # object's regime is the line below which no notice is expected.
        reportable_m_s, _ = per_event_station_keeping_m_s(
            str(getattr(pol, "regime", "") or ""),
        )
        # notso.py is an astro module and works in km/s; the calibration is
        # m/s. This is the conversion, in that direction, and it is the only
        # one on this path.
        reportable_km_s = reportable_m_s / 1000.0
        correlations = correlate_notsos_with_manoeuvres(
            notsos, _all_detections(pol), pol.satno
        )

        start, end = _analysis_window(pol)
        profile = (
            extract_behaviour_profile(
                pol.satno, correlations, start, end,
                reportable_threshold_km_s=reportable_km_s,
            )
            if (start and end) else None
        )

        state.append_log(
            f"[NOTSO] Correlated {len(notsos)} NOTSOs ({source_label}) for {pol.satno}: "
            f"{sum(1 for c in correlations if c.correlation_type == 'matched')} matched, "
            f"{sum(1 for c in correlations if c.correlation_type == 'notso_only')} NOTSO-only, "
            f"{sum(1 for c in correlations if c.correlation_type == 'manoeuvre_only')} manoeuvre-only"
        )
    except Exception:
        logger.exception("NOTSO correlation failed for %d", pol.satno)
        return HTMLResponse('<p class="error-msg">NOTSO correlation failed; the server log has the detail.</p>')

    return render(request, "partials/notso_results.html", {
        # Rows carry their own m/s figures so the template does no arithmetic.
        "correlation_rows": _correlation_rows(correlations),
        "correlations": correlations,
        "profile": profile,
        "pol": pol,
        "source_label": source_label,
        "notso_parsed": len(notsos),
        "notso_rejects": rejects,
    })


# ── Photometry routes ─────────────────────────────────────────────────────────

@router.get("/photometry-panel", response_class=HTMLResponse)
async def pol_photometry_panel(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Return the photometry analysis input panel."""
    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)
    return render(request, "partials/photometry_panel.html", {
        "pol": pol,
    })


@router.post("/photometry-analyse", response_class=HTMLResponse)
async def pol_photometry_analyse(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    _rl: Annotated[None, Depends(pol_compute_rate_limit)],
    csv_text: Annotated[str, Form()] = "",
    recent_window_days: Annotated[float, Form()] = 30.0,
    baseline_window_days: Annotated[float, Form()] = 90.0,
    extinction_coeff: Annotated[float, Form()] = 0.12,
) -> HTMLResponse:
    """Parse photometry CSV and run change-detection analysis."""
    from spectre.astro.photometry import assess_photometry, parse_photometry_csv

    state = get_session_state(current_user)
    pol = getattr(state, "last_pol_analysis", None)

    if not csv_text.strip():
        return HTMLResponse('<p class="error-msg">Paste a CSV with at least epoch_utc and apparent_magnitude columns.</p>')
    if len(csv_text) > MAX_PHOTOMETRY_CSV_CHARS:
        return HTMLResponse(
            f'<p class="error-msg">CSV too large: {len(csv_text):,} characters, '
            f'limit {MAX_PHOTOMETRY_CSV_CHARS:,}. Trim it to the windows being compared.</p>'
        )

    try:
        # Off the event loop: parsing and the fit are pure CPU.
        observations = await run_in_threadpool(parse_photometry_csv, csv_text)
        if len(observations) < 5:
            return HTMLResponse(
                f'<p class="error-msg">Need at least 5 valid observations, got {len(observations)}.</p>'
            )

        # Photometry corroborates in the same way a NOTSO does: a brightness
        # change beside a candidate detection is evidence for it.
        manoeuvres = _all_detections(pol) if pol else []
        result = await run_in_threadpool(
            assess_photometry,
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
    except Exception:
        logger.exception("Photometry analysis failed")
        return HTMLResponse('<p class="error-msg">Photometry analysis failed; the server log has the detail.</p>')

    return render(request, "partials/photometry_results.html", {
        "result": result,
        "n_observations": len(observations),
        "pol": pol,
    })
