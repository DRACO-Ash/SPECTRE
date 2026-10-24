"""UDL (Unified Data Library) proxy routes for SPECTRE.

Provides session-scoped UDL authentication and TLE fetch endpoints.
Credentials are held in memory for the duration of the operator session
and are never written to disk or the database.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from math import inf
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.log_safety import log_safe
from spectre.web.models import User
from spectre.web.planning_state import (
    SessionState,
    get_catalog_status,
    get_onorbit_catalog,
    get_session_state,
    set_catalog_status,
    set_onorbit_catalog,
)
from spectre.web.rate_limit import udl_auth_rate_limit, udl_data_rate_limit, udl_sync_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/udl")


def _parse_tle_epoch(line1: str) -> datetime | None:
    """Parse TLE line 1 epoch field (0-indexed cols 18-31, format YYDDD.FFFFFFFF) to UTC datetime.

    Returns None if the field cannot be parsed.
    """
    try:
        epoch_str = line1[18:32].strip()
        year_2d = int(epoch_str[:2])
        day_frac = float(epoch_str[2:])
        year = 2000 + year_2d if year_2d < 57 else 1900 + year_2d
        day_int = int(day_frac)
        frac = day_frac - day_int
        return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day_int - 1 + frac)
    except (ValueError, IndexError):
        return None

_UDL_BASE = "https://unifieddatalibrary.com/udl"
# TLE line 1 carries the epoch in 0-indexed columns 18-31, so a line shorter
# than this cannot hold one and is logged whole rather than sliced to nothing.
_TLE_EPOCH_FIELD_END = 32

# One wording for the one action an operator can take about it, used by every
# route that can be reached without credentials. It is also the literal whose
# three copies raised python:S1192 once the precheck helper moved the first one
# onto a changed line, so it has to stay a single definition.
_NOT_CONNECTED_MESSAGE = "Not connected to UDL — use the UDL panel to log in first."

# UDL spells the object name in camelCase or in upper case depending on which
# provider filed the record, so both spellings are read at every site. Naming
# the upper-case one keeps its three copies to a single literal (python:S1192).
_UDL_NAME_KEY_UPPER = "OBJECT_NAME"


async def fetch_tle_history_for_satno(
    satno: int,
    username: str,
    password: str,
    window_hours: float = 24.0,
    data_mode: str = "REAL",
    source: str = "",
) -> list[str]:
    """Fetch all TLEs for a SATNO within a recent time window from UDL.

    Queries ``/elset`` (not ``/elset/current``) to retrieve every element set
    filed within *window_hours* of now.  Multiple providers contribute multiple
    records for the same object, giving the clustering step meaningful input.

    Returns a list of ``"line1\\nline2"`` strings — one per UDL record.
    Returns an empty list on failure so callers can fall back gracefully.

    Parameters
    ----------
    satno:
        NORAD catalogue number.
    username / password:
        UDL credentials.
    window_hours:
        How many hours back to search.  Default 24 h.
    data_mode:
        UDL data classification filter.
    source:
        Optional TLE source provider filter.
    """
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(hours=window_hours)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    params: dict[str, Any] = {
        "satNo":  satno,
        "epoch":  f">{since_str}",
    }
    if data_mode != "REAL":
        params["dataMode"] = data_mode
    if source:
        params["source"] = source

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/elset",
                params=params,
                auth=(username, password),
                timeout=15.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("fetch_tle_history_for_satno(%s) failed: %s", satno, exc)
        return []

    records = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    tles: list[str] = []
    for rec in records:
        line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
        line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
        if line1 and line2:
            tles.append(f"{line1}\n{line2}")

    logger.debug("fetch_tle_history_for_satno(%s): %d TLEs in %.0fh window", satno, len(tles), window_hours)
    return tles


async def fetch_tle_for_satno(
    satno: int, username: str, password: str,
    data_mode: str = "REAL",
    source: str = "",
) -> tuple[str, str] | None:
    """Fetch current TLE for a SATNO from UDL.

    Returns ``('line1\\nline2', 'DATA_MODE_TAG')`` or ``None`` on failure.
    The second element is the UDL ``dataMode`` field from the first returned record
    (normalised to upper-case), enabling callers to preserve data-provenance metadata.
    """
    try:
        async with httpx.AsyncClient() as client:
            params: dict[str, Any] = {"satNo": satno}
            if data_mode != "REAL":
                params["dataMode"] = data_mode
            if source:
                params["source"] = source
            resp = await client.get(
                f"{_UDL_BASE}/elset/current",
                params=params,
                auth=(username, password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("fetch_tle_for_satno(%s) failed: %s", satno, exc)
        return None

    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        records = []

    if not records:
        return None

    rec = records[0]
    line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
    line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
    if not line1 or not line2:
        return None
    data_mode_tag = str(rec.get("dataMode") or data_mode or "REAL").strip().upper()
    return (f"{line1}\n{line2}", data_mode_tag)


#: Background tasks started at UDL login. The loop holds only weak references
#: to tasks, so a discarded handle could be collected before the task finished
#: (audit F-143); these sets hold them until they are done.
_BACKGROUND: set[asyncio.Task[None]] = set()
_SESSION_TASKS: dict[str, set[asyncio.Task[None]]] = {}

#: The catalogue is pulled again once it is this old.
_CATALOG_TTL_S = 24 * 3600.0
_catalog_loaded_at: float | None = None


def _spawn(coro: Coroutine[Any, Any, None], owner: str) -> asyncio.Task[None]:
    """Start *coro* as a task held until it finishes, filed under *owner*."""
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    _SESSION_TASKS.setdefault(owner, set()).add(task)

    def _forget(t: asyncio.Task[None]) -> None:
        _BACKGROUND.discard(t)
        owned = _SESSION_TASKS.get(owner)
        if owned is not None:
            owned.discard(t)
            if not owned:
                _SESSION_TASKS.pop(owner, None)

    task.add_done_callback(_forget)
    return task


def _cancel_session_tasks(owner: str) -> None:
    """Cancel the background tasks still using *owner*'s UDL password."""
    for task in list(_SESSION_TASKS.get(owner, ())):
        task.cancel()


async def _fetch_onorbit_background(username: str, password: str) -> None:
    """Fetch the UDL on-orbit catalog in the background and cache it app-wide.

    Called as an asyncio background task immediately after successful UDL login.
    Single-flight: a pull already loading is left to finish, so concurrent
    logins no longer each start the 60 s download, and a catalogue younger
    than _CATALOG_TTL_S is kept rather than never being refreshed (F-143).
    """
    global _catalog_loaded_at
    status = get_catalog_status()
    if status == "loading":
        return
    fresh = _catalog_loaded_at is not None and time.monotonic() - _catalog_loaded_at < _CATALOG_TTL_S
    if status == "ready" and fresh:
        return
    set_catalog_status("loading")
    logger.info("Background: fetching on-orbit catalog from UDL")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/onorbit",
                auth=(username, password),
                timeout=60.0,
            )
        resp.raise_for_status()
        data = resp.json()
        set_onorbit_catalog(data if isinstance(data, list) else [])
        _catalog_loaded_at = time.monotonic()
        logger.info("Background: on-orbit catalog ready (%d objects)", len(get_onorbit_catalog()))
    except Exception as exc:
        set_catalog_status("error")
        logger.warning("Background: on-orbit catalog fetch failed: %s", exc)


async def _discover_tle_sources(username: str, password: str, state: SessionState) -> None:
    """Probe UDL to discover available TLE source providers for this session.

    Fetches ISS (SATNO 25544) with a wide window and collects unique ``source``
    field values from the returned records.  Results are stored on *state*.
    Silent on failure — source discovery is best-effort.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/elset/current",
                params={"satNo": 25544},
                auth=(username, password),
                timeout=15.0,
            )
        resp.raise_for_status()
        data = resp.json()
        records = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        sources = sorted({
            str(rec.get("source") or "").strip()
            for rec in records
            if rec.get("source") and str(rec.get("source")).strip()
        })
        state.udl_available_sources = sources
        logger.info("UDL TLE sources discovered: %s", log_safe(sources))
    except Exception as exc:
        logger.warning("_discover_tle_sources failed (non-critical): %s", exc)


# ── UDL session management ─────────────────────────────────────────────────


@router.post("/login", response_model=None)
async def udl_login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_auth_rate_limit),
) -> HTMLResponse:
    """Validate UDL credentials and store them in the operator session.

    Performs a lightweight probe request to UDL to confirm the credentials
    are accepted before storing them.
    """
    state = get_session_state(current_user.username)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/elset/current",
                params={"satNo": 25544},
                auth=(username, password),
                timeout=10.0,
            )
        if resp.status_code == 401:
            logger.warning("UDL login rejected for operator %s", log_safe(current_user.username))
            return render(request,
                "partials/udl_status.html",
                {"udl_user": None, "error": "Invalid UDL credentials (401)."},
            )
        if not resp.is_success:
            body = resp.text[:300].strip() or "(empty)"
            error = f"UDL probe returned HTTP {resp.status_code}: {body}"
            logger.warning(
                "UDL login probe %d for operator %s: %s",
                resp.status_code, log_safe(current_user.username), log_safe(body),
            )
            return render(request,
                "partials/udl_status.html",
                {"udl_user": None, "error": error},
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        error = f"UDL probe returned HTTP {exc.response.status_code}: {body}"
        logger.warning("UDL login probe HTTP error for operator %s: %s", log_safe(current_user.username), exc)
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": error},
        )
    except httpx.TimeoutException:
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": "UDL connection timed out (10 s). Check network."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL login probe failed: %s", exc)
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": f"UDL unreachable: {exc}"},
        )

    state.udl_username = username
    state.udl_password = password
    state.append_log(f"[UDL] Connected as {username}")
    logger.info("UDL session opened for operator: %s", log_safe(current_user.username))

    # Kick off background tasks (no-op for catalog if already loaded).
    _spawn(_fetch_onorbit_background(username, password), current_user.username)
    _spawn(_discover_tle_sources(username, password, state), current_user.username)

    return render(request,
        "partials/udl_status.html",
        {
            "udl_user": username,
            "error": None,
            "tle_source": state.udl_tle_source,
            "available": state.udl_available_sources,
        },
    )


_VALID_DATA_MODES = {"REAL", "TEST", "EXERCISE", "SIMULATED"}


@router.post("/data-mode", response_model=None)
async def set_data_mode(
    request: Request,
    data_mode: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Set the UDL data classification mode for this session."""
    state = get_session_state(current_user.username)
    mode = data_mode.strip().upper()
    if mode not in _VALID_DATA_MODES:
        mode = "REAL"
    state.udl_data_mode = mode
    state.append_log(f"[UDL] Data mode set to {mode}")
    logger.info("UDL data mode set to %s for operator %s", mode, log_safe(current_user.username))
    return render(request,
        "partials/data_mode_status.html",
        {"udl_data_mode": mode},
    )


@router.post("/tle-source", response_model=None)
async def set_tle_source(
    request: Request,
    tle_source: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Set the preferred TLE source provider for this session."""
    state = get_session_state(current_user.username)
    source = tle_source.strip()
    state.udl_tle_source = source
    if source:
        state.append_log(f"[UDL] TLE source set to {source}")
    else:
        state.append_log("[UDL] TLE source reset to UDL default")
    # %r is what keeps this line unforgeable: repr escapes a newline in an
    # unvalidated tle_source. Keep it. log_safe is identity for every real
    # source name, so the rendered text is unchanged either way.
    logger.info("TLE source set to %r for operator %s", log_safe(source), log_safe(current_user.username))
    return render(request,
        "partials/tle_source_status.html",
        {"tle_source": source, "available": state.udl_available_sources},
    )


@router.post("/logout", response_model=None)
async def udl_logout(
    request: Request,
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Clear UDL credentials from the operator session."""
    state = get_session_state(current_user.username)
    state.udl_username = None
    state.udl_password = None
    # The login's background tasks hold the password; stop them too (F-143).
    _cancel_session_tasks(current_user.username)
    state.append_log("[UDL] Disconnected")
    logger.info("UDL session closed for operator: %s", log_safe(current_user.username))

    return render(request,
        "partials/udl_status.html",
        {"udl_user": None, "error": None},
    )


# ── TLE fetch proxy ────────────────────────────────────────────────────────


def _tle_precheck_error(state: SessionState, mode: str) -> str | None:
    """Return the operator-facing reason a TLE fetch cannot proceed, or None.

    Credentials live only in session state, so a missing pair means the
    operator never logged in; epoch mode has nothing to measure an elset
    against until scenario time is set.
    """
    if not state.udl_username or not state.udl_password:
        return _NOT_CONNECTED_MESSAGE
    if mode == "epoch" and state.scenario_start is None:
        return "No scenario time set. Configure scenario time in the Scenario Configuration panel first."
    return None


def _elset_request_spec(
    state: SessionState,
    satno: int,
    mode: str,
    data_mode: str,
) -> tuple[str, dict[str, Any], float]:
    """Return the (url, params, timeout) for the elset query *mode* calls for.

    Epoch mode asks /elset for up to ten elsets at or before scenario start;
    latest mode asks /elset/current, which takes no epoch filter. dataMode is
    sent only when it is not REAL, and the operator's source override applies
    to the current-elset query alone.
    """
    if mode == "epoch":
        epoch_filter = state.scenario_start.strftime("%Y-%m-%dT%H:%M:%S.000000Z")  # type: ignore[union-attr]
        params: dict[str, Any] = {"satNo": satno, "epoch": f"<{epoch_filter}", "maxResults": 10}
        if data_mode != "REAL":
            params["dataMode"] = data_mode
        return f"{_UDL_BASE}/elset", params, 10.0

    latest_params: dict[str, Any] = {"satNo": satno}
    if data_mode != "REAL":
        latest_params["dataMode"] = data_mode
    if state.udl_tle_source:
        latest_params["source"] = state.udl_tle_source
    return f"{_UDL_BASE}/elset/current", latest_params, 15.0


def _normalise_elset_records(data: Any) -> list[Any]:
    """Return the UDL elset payload as a list of records.

    /elset/current answers with a bare object when a single elset matches and
    with a list when several do, so neither shape can be assumed.
    """
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return []


def _log_elset_diagnostics(records: list[Any]) -> None:
    """Log the record field names and every candidate's parsed line 1 epoch.

    Field names drift between UDL sources and a wrong pick is only ever
    diagnosed from the epochs that were on offer, so both go in the log.
    """
    # Everything logged here comes off the wire, the record's own field names
    # included, and a newline in any of it forges an audit entry
    # (pythonsecurity:S5145), so each value goes through log_safe.
    # Log the keys from the first record so we can verify field names.
    if records:
        sample = records[0]
        # A real UDL elset carries twenty-odd fields, so the default 120
        # character cap would truncate the very list this line exists to show.
        # The cap is a flood guard, not the control: control characters are
        # neutralised at any limit.
        logger.info("UDL elset record keys: %s", log_safe(list(sample.keys()), limit=2000))
        # Also check for any epoch-like top-level field
        for key in ("epoch", "EPOCH", "epochDate", "tle1", "TLE1"):
            if key in sample:
                logger.info("  record[%r] = %s", key, log_safe(str(sample[key])[:80]))

    # Log every candidate's TLE line1 epoch for diagnostics.
    for i, candidate in enumerate(records):
        l1_raw = _elset_line(candidate, 1)
        ep = _parse_tle_epoch(l1_raw)
        logger.info(
            "  record[%d] line1[18:32]=%r  parsed_epoch=%s  objectName=%s",
            i,
            log_safe(l1_raw[18:_TLE_EPOCH_FIELD_END] if len(l1_raw) > _TLE_EPOCH_FIELD_END else l1_raw),
            ep.isoformat() if ep else "None",
            log_safe(candidate.get("objectName") or candidate.get(_UDL_NAME_KEY_UPPER) or "?"),
        )


#: Every spelling of the two element lines a UDL record has been seen to use.
#: Diagnostics read "tle1" while extraction ignored it (audit F-140), so one
#: list now serves selection, extraction and diagnostics alike.
_LINE_KEYS = {
    1: ("line1", "TLE_LINE1", "tle1", "TLE1"),
    2: ("line2", "TLE_LINE2", "tle2", "TLE2"),
}


def _elset_line(rec: Any, n: int) -> str:
    """Line *n* (1 or 2) of a UDL record, under whichever spelling it carries."""
    return next((str(rec[k]).strip() for k in _LINE_KEYS[n] if rec.get(k)), "")


def _select_elset_by_epoch(records: list[Any], scenario_start: datetime) -> Any | None:
    """Return the record whose TLE epoch is closest to, and not after, *scenario_start*.

    An elset published after the scenario starts answers a question the
    operator did not ask, so those are skipped rather than ranked. Returns
    None when no candidate survives that filter.
    """
    best_rec = None
    best_delta = inf
    for candidate in records:
        ep = _parse_tle_epoch(_elset_line(candidate, 1))
        if ep is None or ep > scenario_start:
            continue
        delta = (scenario_start - ep).total_seconds()
        if delta < best_delta:
            best_delta = delta
            best_rec = candidate
    return best_rec


def _select_latest_elset(records: list[Any]) -> Any:
    """Return the record with the newest TLE epoch.

    /elset/current can answer with several records and does not order them,
    so the newest is chosen here rather than taken on trust.
    """
    best_rec = records[0]
    best_epoch = _parse_tle_epoch(_elset_line(best_rec, 1))
    for candidate in records[1:]:
        ep = _parse_tle_epoch(_elset_line(candidate, 1))
        if ep is not None and (best_epoch is None or ep > best_epoch):
            best_epoch = ep
            best_rec = candidate
    logger.info(
        "Latest mode selected record with epoch=%s",
        best_epoch.isoformat() if best_epoch else "None",
    )
    return best_rec


def _extract_tle_fields(rec: Any, name_override: str, satno: int) -> tuple[str, str, str]:
    """Return the (name, two-line TLE, line 1) carried by *rec*.

    UDL spells the fields in camelCase or upper case depending on source, so
    both are read before falling back to the catalogue number.
    """
    name = name_override.strip() or str(rec.get("objectName") or rec.get(_UDL_NAME_KEY_UPPER) or satno).strip()
    line1 = _elset_line(rec, 1)
    line2 = _elset_line(rec, 2)
    return name, f"{line1}\n{line2}", line1


def _tle_epoch_metadata(line1: str, scenario_start: datetime | None) -> tuple[str | None, float | None]:
    """Return the display epoch and the age in days of TLE *line1*.

    Either is None when it cannot be derived: an unparsable line 1, or no
    scenario time to measure the age against.
    """
    tle_epoch_dt = _parse_tle_epoch(line1)
    if tle_epoch_dt is None:
        return None, None
    tle_epoch_str = tle_epoch_dt.strftime("%Y-%m-%d %H:%M UTC")
    if scenario_start is None:
        return tle_epoch_str, None
    return tle_epoch_str, abs((scenario_start - tle_epoch_dt).total_seconds()) / 86400.0


@router.get("/tle", response_model=None)
async def fetch_tle(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    mode: str = Query("latest", description="'latest' for current elset, 'epoch' for closest to scenario start"),
    name_override: Annotated[str, Query(description="Pre-populated name (e.g. from HRR watchlist commonName)")] = "",
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_data_rate_limit),
) -> HTMLResponse:
    """Fetch a TLE for *satno* from UDL and return a pre-filled form partial.

    Two modes are supported:

    * ``latest`` — uses ``/elset/current`` to retrieve the most recent available elset.
    * ``epoch`` — fetches up to 10 elsets with epoch ≤ scenario start time, then selects
      the one whose epoch is closest to (but not after) the scenario start.  Requires
      scenario time to be set first.  A staleness warning is shown
      when the selected TLE is more than 7 days from the scenario start.
    """
    state = get_session_state(current_user.username)

    _empty = {"name": "", "tle": "", "tle_epoch_str": None,
               "tle_age_days": None, "mode": mode, "error": None}

    precheck_error = _tle_precheck_error(state, mode)
    if precheck_error is not None:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": precheck_error},
        )

    # ── Fetch from UDL ───────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient() as client:
            dm = state.udl_data_mode or "REAL"
            url, params, timeout = _elset_request_spec(state, satno, mode, dm)
            resp = await client.get(
                url,
                params=params,
                # Both credentials are non-None once _tle_precheck_error has
                # passed, but that narrowing now happens in the helper rather
                # than in this frame, so mypy cannot see it here.
                auth=(state.udl_username, state.udl_password),  # type: ignore[arg-type]
                timeout=timeout,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}: {body}"
        # The message embeds the remote response body, so it cannot be used as
        # the record verbatim (pythonsecurity:S5145).
        logger.warning("%s", log_safe(error))
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": error},
        )
    except httpx.TimeoutException:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL TLE fetch failed for SATNO %s: %s", satno, exc)
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": f"UDL unreachable: {exc}"},
        )

    # Normalise: /elset/current may return a single dict or a list
    records = _normalise_elset_records(data)

    if not records:
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": f"No elset found for SATNO {satno}."},
        )

    # ── Select the best record ───────────────────────────────────────────────
    logger.info(
        "UDL returned %d elset record(s) for SATNO %s mode=%s dataMode=%s",
        len(records), satno, log_safe(mode), dm,
    )

    _log_elset_diagnostics(records)

    if mode == "epoch":
        # Pick the record whose TLE epoch is closest to (and ≤) scenario_start.
        rec = _select_elset_by_epoch(records, state.scenario_start)  # type: ignore[arg-type]
        if rec is None:
            return render(request,
                "partials/tle_fields.html",
                {**_empty, "error": (
                    f"No elset found for SATNO {satno} with epoch ≤ "
                    f"{state.scenario_start.strftime('%Y-%m-%d %H:%M UTC')}."  # type: ignore[union-attr]
                )},
            )
    else:
        # For "latest" mode: pick the record with the newest TLE epoch.
        rec = _select_latest_elset(records)

    # ── Extract fields ───────────────────────────────────────────────────────
    name, tle, line1 = _extract_tle_fields(rec, name_override, satno)
    if not line1 or not _elset_line(rec, 2):
        # Rendered as success with a TLE of "\n" before (audit F-140).
        return render(request,
            "partials/tle_fields.html",
            {**_empty, "error": f"UDL returned an elset for SATNO {satno} with no element lines."},
        )

    # TLE epoch metadata for the partial
    tle_epoch_str, tle_age_days = _tle_epoch_metadata(line1, state.scenario_start)

    state.append_log(
        f"[UDL] Fetched TLE for SATNO {satno} ({name}) mode={mode}"
        + (f" epoch={tle_epoch_str}" if tle_epoch_str else "")
    )
    logger.info(
        "TLE fetched for SATNO %s (%s) mode=%s by operator %s",
        satno, log_safe(name), log_safe(mode), log_safe(current_user.username),
    )

    return render(request,
        "partials/tle_fields.html",
        {

            "name": name,
            "tle": tle,
            "tle_epoch_str": tle_epoch_str,
            "tle_age_days": tle_age_days,
            "mode": mode,
            "error": None,
        },
    )


# ── State vector fetch proxy ───────────────────────────────────────────────


@router.get("/statevector", response_model=None)
async def fetch_statevector(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_data_rate_limit),
) -> HTMLResponse:
    """Fetch the latest Cartesian state vector for *satno* from UDL.

    Returns position (km) and velocity (km s⁻¹) in the J2000 reference frame
    at the most recent available epoch. Useful for initialising high-fidelity
    intercept geometry without propagating a TLE.
    """
    state = get_session_state(current_user.username)

    if not state.udl_username or not state.udl_password:
        return render(request,
            "partials/statevector_fields.html",
            {
    
                "sv": None,
                "error": _NOT_CONNECTED_MESSAGE,
            },
        )

    dm = state.udl_data_mode or "REAL"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/statevector",
                params={"satNo": satno, "epoch": ">2020-01-01T00:00:00.000000Z",
                        "dataMode": dm, "maxResults": 1},
                auth=(state.udl_username, state.udl_password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        error = f"UDL returned {exc.response.status_code} for SATNO {satno}"
        logger.warning(error)
        return render(request,
            "partials/statevector_fields.html",
            {"sv": None, "error": error},
        )
    except httpx.TimeoutException:
        return render(request,
            "partials/statevector_fields.html",
            {"sv": None, "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL state vector fetch failed for SATNO %s: %s", satno, exc)
        return render(request,
            "partials/statevector_fields.html",
            {"sv": None, "error": f"UDL unreachable: {exc}"},
        )

    if not data:
        return render(request,
            "partials/statevector_fields.html",
            {
    
                "sv": None,
                "error": f"No state vector found for SATNO {satno}.",
            },
        )

    rec = data[0]
    sv = {
        "name": str(rec.get("objectName") or rec.get(_UDL_NAME_KEY_UPPER, satno)).strip(),
        "epoch": rec.get("epoch", "—"),
        "x": rec.get("xpos"),
        "y": rec.get("ypos"),
        "z": rec.get("zpos"),
        "x_dot": rec.get("xvel"),
        "y_dot": rec.get("yvel"),
        "z_dot": rec.get("zvel"),
        "ref_frame": rec.get("referenceFrame", "J2000"),
    }

    state.append_log(
        f"[UDL] Fetched state vector for SATNO {satno} ({sv['name']}) epoch {sv['epoch']}"
    )
    logger.info(
        "State vector fetched for SATNO %s (%s) by operator %s",
        satno,
        log_safe(sv["name"]),
        log_safe(current_user.username),
    )

    return render(request,
        "partials/statevector_fields.html",
        {"sv": sv, "error": None},
    )


# ── HRR Watchlist ──────────────────────────────────────────────────────────

_RED_COUNTRIES = {"CHN", "RUS", "IRN", "PRK"}


def _parse_created_at(rec: dict[str, Any]) -> datetime:
    """Parse the UDL notification createdAt field to a UTC datetime.

    Returns datetime.min (UTC) if the field is absent or unparseable so the
    record sorts to the bottom when picking the newest notification.
    """
    raw = str(rec.get("createdAt") or "").strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)




async def fetch_hrr_objects(
    username: str,
    password: str,
    data_mode: str = "REAL",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, str | None]:
    """Fetch HRR satellites from UDL and return (blue, red, lookback_days, error).

    Reusable by both the HRR panel route and the threat sweep.  On success the
    returned lists contain normalised dicts with keys: satno, name, country,
    rank, orbit_regime, created_at.  On failure, both lists are empty and *error*
    contains a human-readable message.
    """
    _HRR_MAX_LOOKBACK_DAYS = 3
    notifications: list[dict[str, Any]] = []
    days_used = 0

    try:
        async with httpx.AsyncClient() as client:
            for day in range(1, _HRR_MAX_LOOKBACK_DAYS + 1):
                resp = await client.get(
                    f"{_UDL_BASE}/notification",
                    params={
                        "createdAt": f">now-{day} days",
                        "dataMode": data_mode,
                        "msgType": "JCO-HRR-SATELLITES",
                        "source": "JCO",
                        "maxResults": 10000,
                    },
                    auth=(username, password),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list) and data:
                    notifications = data
                    days_used = day
                    break
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:200].strip() or "(empty)"
        return [], [], 0, f"HRR fetch returned HTTP {exc.response.status_code}: {body}"
    except httpx.TimeoutException:
        return [], [], 0, "UDL request timed out."
    except httpx.RequestError as exc:
        return [], [], 0, f"UDL unreachable: {exc}"

    if not notifications:
        return [], [], 0, f"No HRR notifications found in the last {_HRR_MAX_LOOKBACK_DAYS} days."

    newest = max(notifications, key=_parse_created_at)
    hrr_blue, hrr_red = parse_hrr_notification(newest)
    return hrr_blue, hrr_red, days_used, None


def _hrr_elset_fields(sat: dict[str, Any]) -> dict[str, str]:
    """Return the optional element-set fields for one HRR entry, or nothing.

    Both lines must be present to be usable: half a TLE is not a degraded
    TLE, it is an unparseable one.
    """
    line1 = str(sat.get("line1") or "").strip()
    line2 = str(sat.get("line2") or "").strip()
    if line1 and line2:
        return {
            "tle": f"{line1}\n{line2}",
            "tle_data_mode": str(sat.get("tleDataMode") or "REAL").strip().upper(),
        }
    return {}


def parse_hrr_notification(notification: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse a single HRR notification dict into (blue, red) normalised satellite lists.

    Shared by the live UDL fetch and the startup loader.

    An entry MAY carry an element set as ``line1``/``line2``. A real JCO
    notification does not, so the live path is unaffected; the bundled
    bootstrap list does, which is what lets a fresh instance run before anyone
    has connected to UDL. Where present it is carried through as ``tle`` with
    its ``tle_data_mode``, so the interface can mark where it came from.
    """
    msg_body: list[dict[str, Any]] = notification.get("msgBody") or []
    created_at = str(notification.get("createdAt") or "").strip()

    hrr_blue: list[dict[str, Any]] = []
    hrr_red: list[dict[str, Any]] = []

    for sat in msg_body:
        satno = str(sat.get("satNo") or sat.get("satno") or "").strip()
        name = str(sat.get("commonName") or sat.get("objectName") or satno or "—").strip()
        country = str(sat.get("country") or "").strip().upper()
        rank = sat.get("rank")
        orbit_regime = str(sat.get("orbitRegime") or "").strip()
        entry = {
            "satno": satno,
            "name": name,
            "country": country,
            "rank": rank,
            "orbit_regime": orbit_regime,
            "created_at": created_at,
        }
        # Optional element set, carried through only when the source has one.
        entry.update(_hrr_elset_fields(sat))
        if country in _RED_COUNTRIES:
            hrr_red.append(entry)
        else:
            hrr_blue.append(entry)

    return hrr_blue, hrr_red


@router.get("/hrr", response_model=None)
async def fetch_hrr(
    request: Request,
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_data_rate_limit),
) -> HTMLResponse:
    """Fetch the UDL High Rate Revisit (HRR) satellite list and return a panel partial."""
    state = get_session_state(current_user.username)

    _empty_err = {"hrr_blue": [], "hrr_red": [], "hrr_lookback": 0}

    if not state.udl_username or not state.udl_password:
        return render(request,
            "partials/hrr_panel.html",
            {**_empty_err, "error": _NOT_CONNECTED_MESSAGE},
        )

    dm = state.udl_data_mode or "REAL"
    hrr_blue, hrr_red, days_used, error = await fetch_hrr_objects(
        state.udl_username, state.udl_password, dm,
    )

    if error:
        logger.warning("HRR fetch error for operator %s: %s", log_safe(current_user.username), log_safe(error))
        return render(request,
            "partials/hrr_panel.html", {**_empty_err, "error": error},
        )

    # Cache all HRR objects in session state for threat sweep use.
    state.hrr_objects = hrr_blue + hrr_red

    state.append_log(
        f"[HRR] lookback={days_used}d — "
        f"{len(hrr_blue)} Blue, {len(hrr_red)} Red ({len(hrr_blue) + len(hrr_red)} sats)"
    )
    logger.info(
        "HRR fetched for operator %s: lookback=%dd %d blue + %d red",
        log_safe(current_user.username), days_used, len(hrr_blue), len(hrr_red),
    )

    return render(request,
        "partials/hrr_panel.html",
        {"hrr_blue": hrr_blue, "hrr_red": hrr_red,
         "hrr_lookback": days_used, "error": None},
    )


# ── On-orbit catalog search ────────────────────────────────────────────────


@router.get("/catalog/search", response_model=None)
async def search_catalog(
    request: Request,
    q: str = Query("", description="Search query — name substring or SATNO prefix"),
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Search the cached on-orbit catalog and return a results partial.

    Returns up to 50 matching objects.  When *q* is empty the partial shows
    the current catalog status (loading, ready, error) so the operator can
    see progress without searching.
    """
    # The catalogue was pulled with another operator's UDL credential. It is
    # searchable only by an operator holding a UDL session of their own
    # (audit F-142); the bare status line stays visible to everyone.
    state = get_session_state(current_user.username)
    if q.strip() and not (state.udl_username and state.udl_password):
        return HTMLResponse('<p class="error-msg">Log in to UDL to search the on-orbit catalogue.</p>')

    catalog = get_onorbit_catalog()
    status = get_catalog_status()

    results: list[dict[str, Any]] = []
    if q.strip():
        q_lower = q.strip().lower()
        for obj in catalog:
            name = str(obj.get("name") or obj.get("objectName") or "").lower()
            satno = str(obj.get("satNo") or obj.get("satno") or "")
            if q_lower in name or q_lower in satno:
                results.append({
                    "satno": obj.get("satNo") or obj.get("satno") or "—",
                    "name": obj.get("name") or obj.get("objectName") or "—",
                    "obj_type": obj.get("objectType") or obj.get("type") or "—",
                    "country": obj.get("country") or "—",
                })
                if len(results) >= 50:
                    break

    return render(request,
        "partials/catalog_results.html",
        {"results": results, "q": q,
         "status": status, "total": len(catalog)},
    )


@router.get("/notso", response_model=None)
async def udl_notso(
    satno: int,
    request: Request,
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_data_rate_limit),
) -> Any:
    """Attempt to fetch NOTSO records from UDL for a given SATNO.

    Returns a JSON array of NOTSORecord-like dicts on success, or an empty
    array with a 200 status when the endpoint is not available (404/405).
    This graceful degradation allows the UI to fall back to paste-textarea
    without treating a missing endpoint as a hard error.
    """
    from fastapi.responses import JSONResponse

    state = get_session_state(current_user.username)
    if not state.udl_username or not state.udl_password:
        return JSONResponse({"error": "No active UDL session"}, status_code=401)

    _UDL_BASE = "https://unifieddatalibrary.com/udl"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_UDL_BASE}/notification",
                params={"satNo": satno, "maxResults": 200},
                auth=(state.udl_username, state.udl_password),
            )
        if resp.status_code in (404, 405, 501):
            # Endpoint not available in this UDL instance — return empty list gracefully
            logger.info("UDL /notification endpoint not available (HTTP %d) — returning []", resp.status_code)
            return JSONResponse([])
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            return JSONResponse([])

        # Normalise to a consistent shape
        records = data if isinstance(data, list) else [data]
        normalised = []
        for rec in records:
            normalised.append({
                "message_id":   str(rec.get("messageId") or rec.get("id") or ""),
                "issue_date":   str(rec.get("issueDate") or rec.get("date") or ""),
                "start":        str(rec.get("effectiveStart") or rec.get("startTime") or ""),
                "end":          str(rec.get("effectiveEnd") or rec.get("stopTime") or ""),
                "type":         str(rec.get("notificationType") or rec.get("type") or ""),
                "description":  str(rec.get("description") or rec.get("remarks") or ""),
                "raw":          str(rec.get("rawMessage") or rec.get("message") or ""),
            })
        return JSONResponse(normalised)

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 405, 501):
            return JSONResponse([])
        logger.warning("UDL NOTSO fetch error for %d: %s", satno, exc)
        return JSONResponse({"error": str(exc)}, status_code=502)
    except Exception as exc:
        logger.warning("UDL NOTSO fetch failed for %d: %s", satno, exc)
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.post("/notso/sync", response_model=None)
async def udl_notso_sync(
    request: Request,
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_sync_rate_limit),
) -> Any:
    """Incrementally sync TACREP_NOTSO records from UDL into the local cache.

    Uses ``createdAt`` of the newest cached record as the lower bound for each
    pull.  Pages through the UDL ``/notification`` endpoint (500 records per
    page) until no more results are returned, then writes everything to
    ``spectre/data/notso_cache.json``.

    Always returns an HTML partial suitable for ``hx-swap="innerHTML"`` on the
    NOTSO sync status ``<div>``.
    """
    from fastapi.responses import HTMLResponse as _HTMLResponse

    from spectre.data.notso_cache import get_notso_cache

    state = get_session_state(current_user.username)
    if not state.udl_username or not state.udl_password:
        return _HTMLResponse(
            '<p class="error-msg" style="font-size:0.72rem">No active UDL session — connect first.</p>'
        )

    cache = get_notso_cache()
    latest = cache.latest_created_at()

    # Build the createdAt lower-bound filter.  If the cache is empty, default
    # to 2024-01-01 to pull reasonable history without hitting UDL too hard.
    if latest is not None:
        # Advance by 1 µs so we don't re-fetch the boundary record.
        from datetime import timedelta
        since = latest + timedelta(microseconds=1)
    else:
        from datetime import timedelta
        since = datetime(2024, 1, 1, tzinfo=UTC)

    since_str = since.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    base_params: dict[str, str | int] = {
        "createdAt":  f">{since_str}",
        "dataMode":   "REAL",
        "msgType":    "TACREP_NOTSO",
        "source":     "JCO",
        "maxResults": 500,
    }

    total_added = 0
    page = 0
    errors: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                params: dict[str, str | int] = dict(base_params)
                if page > 0:
                    params["offset"] = page * 500

                resp = await client.get(
                    f"{_UDL_BASE}/notification",
                    params=params,
                    auth=(state.udl_username, state.udl_password),
                )

                if resp.status_code in (404, 405, 501):
                    errors.append(
                        f"UDL /notification endpoint returned HTTP {resp.status_code} — "
                        "TACREP_NOTSO may not be available on this instance."
                    )
                    break

                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    errors.append(f"HTTP error on page {page}: {exc}")
                    break

                try:
                    data = resp.json()
                except Exception:
                    errors.append(f"Non-JSON response on page {page}")
                    break

                records = data if isinstance(data, list) else ([data] if data else [])
                if not records:
                    break  # No more pages

                added = cache.append(records)
                total_added += added
                page += 1

                # If we got fewer records than a full page, we've reached the end.
                if len(records) < 500:
                    break

    except Exception as exc:
        errors.append(f"Sync failed: {exc}")
        logger.warning("notso_sync failed: %s", exc)

    state.append_log(
        f"[NOTSO] Sync complete: +{total_added} new records "
        f"(total {cache.total_records()}, {page} page(s) fetched)"
    )

    # Build status HTML
    if errors and total_added == 0:
        error_html = "".join(f'<p style="margin:0.1rem 0">{e}</p>' for e in errors)
        return _HTMLResponse(
            f'<div class="callout callout-red" style="font-size:0.72rem">{error_html}</div>'
        )

    warn_html = ""
    if errors:
        warn_html = "".join(
            f'<p style="margin:0.1rem 0; font-size:0.68rem; color:var(--text-dim)">⚠ {e}</p>'
            for e in errors
        )

    last_sync = cache.last_sync_utc() or "—"
    total = cache.total_records()
    return _HTMLResponse(
        f'<div class="callout callout-green" style="font-size:0.72rem; padding:0.4rem 0.6rem">'
        f'<strong>+{total_added}</strong> new records added &mdash; '
        f'{total} total in cache. Last sync: {last_sync}.'
        f'</div>{warn_html}'
    )
