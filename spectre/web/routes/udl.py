"""UDL (Unified Data Library) proxy routes for SPECTRE.

Provides session-scoped UDL authentication and TLE fetch endpoints.
Credentials are held in memory for the duration of the operator session
and are never written to disk or the database.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from math import inf
from typing import Annotated, Any, NamedTuple

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse

from spectre.astro.elset_check import check_elset, tle_epoch
from spectre.config.settings import UDL_BASE_URL
from spectre.web.auth import require_login
from spectre.web.deps import render
from spectre.web.elsets import (
    ElsetHistory,
    RefusedElset,
    log_refusal,
    log_skipped_by_type,
    refresh_held_elsets,
    refused,
)
from spectre.web.interaction_store import hold_conjunctions
from spectre.web.log_safety import log_safe
from spectre.web.models import SessionKey, User
from spectre.web.planning_state import (
    SessionState,
    get_catalog_status,
    get_onorbit_catalog,
    get_session_state,
    set_catalog_status,
    set_onorbit_catalog,
)
from spectre.web.rate_limit import udl_auth_rate_limit, udl_data_rate_limit, udl_sync_rate_limit
from spectre.web.udl_conjunction import CONJUNCTION_PATH, CONJUNCTION_SIDE_PARAMS, read_conjunctions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/udl")

_TLE_FIELDS_TEMPLATE = "partials/tle_fields.html"
_STATEVECTOR_FIELDS_TEMPLATE = "partials/statevector_fields.html"
_ELSET_REFRESH_TEMPLATE = "partials/elset_refresh_note.html"


def _parse_tle_epoch(line1: str) -> datetime | None:
    """Parse TLE line 1 epoch field (0-indexed cols 18-31, format YYDDD.FFFFFFFF) to UTC datetime.

    Returns None if the field cannot be parsed. The element-set acceptance check reads the epoch the same way, so
    one reading serves both (SPC-201).
    """
    return tle_epoch(line1)

_UDL_BASE = UDL_BASE_URL
# The element set archive and the current catalogue, each asked from several
# places, and the timestamp format UDL's epoch and createdAt filters take (UTC,
# microseconds). Each is one definition rather than repeated literals (python:S1192).
_ELSET_URL = f"{_UDL_BASE}/elset"
_ELSET_CURRENT_URL = f"{_UDL_BASE}/elset/current"
_UDL_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

# One wording for the one action an operator can take about it, used by every
# route that can be reached without credentials. It is also the literal whose
# three copies raised python:S1192 once the precheck helper moved the first one
# onto a changed line, so it has to stay a single definition.
_NOT_CONNECTED_MESSAGE = "Not connected to UDL — use the UDL panel to log in first."

# UDL spells the object name in camelCase or in upper case depending on which
# provider filed the record, so both spellings are read at every site. Naming
# the upper-case one keeps its three copies to a single literal (python:S1192).
_UDL_NAME_KEY_UPPER = "OBJECT_NAME"

# A failed UDL call shows the operator one of two fixed sentences and logs the
# detail. The exception text carries the request URL and query string, and a
# UDL error body can carry a server stack trace; neither belongs in the browser
# (CodeQL py/stack-trace-exposure, SPC-019). The sentence still names the call
# that failed and what to try, so the operator is not left guessing.
_DETAIL_IN_LOG = "the server log has the detail."


def _udl_unreachable(call: str) -> str:
    """The operator sentence for a UDL *call* that never got an answer."""
    return f"UDL unreachable during the {call}. Check the network path to UDL and try again; {_DETAIL_IN_LOG}"


def _udl_refused(call: str, status: int) -> str:
    """The operator sentence for a UDL *call* answered with an error *status*.

    A 5xx is UDL's own fault, so it must not send the operator to check
    access or a request that were both fine.
    """
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        advice = "That is a fault on the UDL side; try again later"
    else:
        advice = "Check your UDL access and the request, then try again"
    return f"UDL answered the {call} with HTTP {status}. {advice}; {_DETAIL_IN_LOG}"


async def fetch_tle_history_for_satno(
    satno: int,
    username: str,
    password: str,
    window_hours: float = 24.0,
    data_mode: str = "REAL",
    source: str = "",
) -> ElsetHistory:
    """Fetch all TLEs for a SATNO within a recent time window from UDL.

    Queries ``/elset`` (not ``/elset/current``) to retrieve every element set
    filed within *window_hours* of now.  Multiple providers contribute multiple
    records for the same object, giving the clustering step meaningful input.

    Returns a list of ``"line1\\nline2"`` strings — one per UDL record.
    Returns an empty list on failure so callers can fall back gracefully.
    A set the acceptance check refuses, its catalogue number included, is
    left out and kept on the list's ``refused`` so the caller can say so
    (SPC-201).

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
    params: dict[str, Any] = {
        "satNo":  satno,
        "epoch":  _epoch_after(window_hours),
    }
    if data_mode != "REAL":
        params["dataMode"] = data_mode
    if source:
        params["source"] = source

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _ELSET_URL,
                params=params,
                auth=(username, password),
                timeout=15.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_tle_history_for_satno(%s) failed: %s", log_safe(satno), log_safe(exc, limit=500))
        return ElsetHistory()

    records = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    sets: list[tuple[str, dict[str, Any]]] = []
    for rec in records:
        line1 = str(rec.get("line1") or rec.get("TLE_LINE1") or "").strip()
        line2 = str(rec.get("line2") or rec.get("TLE_LINE2") or "").strip()
        if line1 and line2:
            sets.append((f"{line1}\n{line2}", rec))
    # Every set feeds the clustering that chooses the cached one, so a set the acceptance check refuses, another
    # object's included, is dropped here, counted and its failures logged without its text (SPC-201). Each record
    # goes to the check with its set, so an SGP4-XP set or an uncorrelated track is refused by its own fields.
    tles = [tle for tle, _ in sets]
    checks = [check_elset(tle, satno, record=rec) for tle, rec in sets]
    log_skipped_by_type(f"SATNO {satno}", sets)
    history = ElsetHistory(
        (tle for tle, check in zip(tles, checks, strict=True) if check.accepted),
        [check for check in checks if not check.accepted],
    )
    if history.refused:
        logger.warning(
            "fetch_tle_history_for_satno(%s): %d element sets refused: %s",
            log_safe(satno), len(history.refused), log_safe([c.failures for c in history.refused], limit=1000),
        )

    logger.debug("fetch_tle_history_for_satno(%s): %d TLEs in %.0fh window", satno, len(history), window_hours)
    return history


#: How far back the archive is searched for the newest element set. A set
#: older than this is stale in every regime (TLE_FILTER's GEO and deep-space
#: limit, 72 hours, is the longest), so past it the current catalogue's answer
#: is as good as any.
_NEWEST_WINDOW_H = 72.0
#: The ISS archive window source discovery reads: every active provider files for it within a day.
_DISCOVERY_WINDOW_H = 24.0
#: The archive answer spans every provider over three days, so it is given
#: longer than the current catalogue's single set per provider.
_ARCHIVE_TIMEOUT_S = 20.0
_CURRENT_TIMEOUT_S = 15.0


def _epoch_after(hours: float) -> str:
    """A UDL epoch filter for element sets newer than *hours* before now."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    return f">{since.strftime(_UDL_TIME_FORMAT)}Z"


def _complete_records(records: list[Any]) -> list[dict[str, Any]]:
    """The records in a UDL elset answer that carry both element lines."""
    return [r for r in records if isinstance(r, dict) and _elset_line(r, 1) and _elset_line(r, 2)]


async def _newest_records(
    client: httpx.AsyncClient, satno: int, auth: tuple[str, str], data_mode: str, source: str,
) -> list[Any]:
    """The records a latest fetch chooses the newest set from. HTTP errors propagate.

    The archive over the last ``_NEWEST_WINDOW_H`` hours is asked first: it
    holds every provider's sets. ``/elset/current`` asked with no source was
    seen to answer for 18th SPCS alone, so a GEO object came back three days
    old while commercial providers had filed sets that day (charming-dirac
    0.6.5; the owner's observation, to be confirmed against live UDL). The
    current catalogue answers only when the archive holds no complete set in
    the window, and its answer comes back as UDL gave it, so a record missing
    a line can still be named as such. *source*, when the operator has chosen
    one, narrows both. dataMode is sent only when it is not REAL.
    """
    base: dict[str, Any] = {"satNo": satno}
    if data_mode != "REAL":
        base["dataMode"] = data_mode
    if source:
        base["source"] = source
    window = {**base, "epoch": _epoch_after(_NEWEST_WINDOW_H)}
    resp = await client.get(_ELSET_URL, params=window, auth=auth, timeout=_ARCHIVE_TIMEOUT_S)
    resp.raise_for_status()
    archived = _complete_records(_normalise_elset_records(resp.json()))
    if archived:
        return archived
    resp = await client.get(_ELSET_CURRENT_URL, params=base, auth=auth, timeout=_CURRENT_TIMEOUT_S)
    resp.raise_for_status()
    return _normalise_elset_records(resp.json())


class FetchedElset(NamedTuple):
    """One element set fetched from UDL, with its data mode and the provider that filed it."""

    tle: str
    data_mode: str
    source: str


async def fetch_tle_for_satno(
    satno: int, username: str, password: str,
    data_mode: str = "REAL",
    source: str = "",
) -> FetchedElset | RefusedElset | None:
    """The newest element set UDL holds for *satno*, from any provider, or from *source* when one is named.

    Returns the set with the record's ``dataMode`` (upper-cased) and the
    provider that filed it (its ``source``), so callers keep its provenance,
    or None on failure or when UDL holds no complete set. The archive over the
    last three days is asked first, then the current catalogue (see
    ``_newest_records``).

    The newest set must pass the acceptance check (SPC-201), and be for
    *satno*: when it does not, a RefusedElset comes back in its place, its
    failures logged without the set's text, and the caller stores nothing and
    says why. An older set, from the same provider or another, is not taken
    instead: the newest is what UDL holds now.
    """
    try:
        async with httpx.AsyncClient() as client:
            records = await _newest_records(client, satno, (username, password), data_mode, source)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_tle_for_satno(%s) failed: %s", log_safe(satno), log_safe(exc))
        return None

    # UDL answers in no order, and the archive holds several providers' sets,
    # so the newest complete record is chosen rather than the first.
    complete = _complete_records(records)
    if not complete:
        return None

    # Records tied at the newest epoch are none of them older, so the first the check accepts is taken; the order
    # UDL listed them in must not decide whether the fetch is refused. Only when every one is refused is it.
    newest = _tied_at_newest(complete, _select_latest_elset(complete))
    # An SGP4-XP set or an uncorrelated track is refused by the record's own fields, and named in the log by type.
    checked = [(rec, f"{_elset_line(rec, 1)}\n{_elset_line(rec, 2)}") for rec in newest]
    checks = [check_elset(tle, satno, record=rec) for rec, tle in checked]
    refused = [(tle, rec) for (rec, tle), check in zip(checked, checks, strict=True) if not check.accepted]
    if refused:
        log_skipped_by_type(f"SATNO {satno}", refused)
    for (rec, tle), check in zip(checked, checks, strict=True):
        if check.accepted:
            data_mode_tag = str(rec.get("dataMode") or data_mode or "REAL").strip().upper()
            return FetchedElset(tle, data_mode_tag, str(rec.get("source") or "").strip())
    log_refusal(checks[0].refusal(f"SATNO {satno}, as UDL answered it,"))
    return RefusedElset(satno, checks[0])


def _tied_at_newest(records: list[Any], chosen: Any) -> list[Any]:
    """*chosen* and every other record whose line 1 epoch equals it, in a stable order: provider, then set text."""
    epoch = _parse_tle_epoch(_elset_line(chosen, 1))
    tied = [r for r in records if r is chosen or (epoch is not None and _parse_tle_epoch(_elset_line(r, 1)) == epoch)]
    return sorted(tied, key=lambda r: (str(r.get("source") or ""), _elset_line(r, 1), _elset_line(r, 2)))


#: Background tasks started at UDL login. The loop holds only weak references
#: to tasks, so a discarded handle could be collected before the task finished
#: (audit F-143); these sets hold them until they are done.
_BACKGROUND: set[asyncio.Task[None]] = set()
_SESSION_TASKS: dict[SessionKey | None, set[asyncio.Task[None]]] = {}

#: The catalogue is pulled again once it is this old.
_CATALOG_TTL_S = 24 * 3600.0
class _CatalogClock:
    """When the catalogue last loaded (time.monotonic), or None."""

    loaded_at: float | None = None


_CATALOG_CLOCK = _CatalogClock()


def spawn_session_task(coro: Coroutine[Any, Any, None], owner: SessionKey | None) -> asyncio.Task[None]:
    """Start *coro* as a task UDL logout cancels, for other modules (the burn watch).

    Calls ``_spawn`` by name at call time, so tests that patch it still see it.
    """
    return _spawn(coro, owner)


def _spawn(coro: Coroutine[Any, Any, None], owner: SessionKey | None) -> asyncio.Task[None]:
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


def _cancel_session_tasks(owner: SessionKey | None) -> None:
    """Cancel the background tasks still using *owner*'s UDL password."""
    # cancel() only schedules the done callback that edits the set, so it is
    # safe to iterate directly.
    for task in _SESSION_TASKS.get(owner, ()):
        task.cancel()


async def _fetch_onorbit_background(username: str, password: str) -> None:
    """Fetch the UDL on-orbit catalog in the background and cache it app-wide.

    Called as an asyncio background task immediately after successful UDL login.
    Single-flight: a pull already loading is left to finish, so concurrent
    logins no longer each start the 60 s download, and a catalogue younger
    than _CATALOG_TTL_S is kept rather than never being refreshed (F-143).
    """
    status = get_catalog_status()
    if status == "loading":
        return
    loaded_at = _CATALOG_CLOCK.loaded_at
    fresh = loaded_at is not None and time.monotonic() - loaded_at < _CATALOG_TTL_S
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
        _CATALOG_CLOCK.loaded_at = time.monotonic()
        logger.info("Background: on-orbit catalog ready (%d objects)", len(get_onorbit_catalog()))
    except Exception as exc:   # noqa: BLE001 - a background task; any failure must reach the status flag
        set_catalog_status("error")
        logger.warning("Background: on-orbit catalog fetch failed: %s", log_safe(exc, limit=500))


def remember_sources(state: SessionState, sources: list[str]) -> None:
    """Add *sources* to the providers the TLE Source list offers, each once, in order; a blank one never."""
    named = {src.strip() for src in sources if src.strip()}
    state.udl_available_sources = sorted(set(state.udl_available_sources) | named)


async def _discover_tle_sources(username: str, password: str, state: SessionState) -> None:
    """Probe UDL for the TLE source providers this session can choose from.

    Reads the ISS's archive over the last day and adds every ``source`` on
    it to the list. ``/elset/current``, asked before, was seen to answer for
    18th SPCS alone when no source is given, so the list offered one provider.
    The ISS is a LEO object, so the providers the connect-time refresh sees on
    the held sets are added as it runs. Silent on failure: source discovery is
    best-effort, and a failed probe leaves the list alone.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _ELSET_URL,
                params={"satNo": 25544, "epoch": _epoch_after(_DISCOVERY_WINDOW_H)},
                auth=(username, password),
                timeout=15.0,
            )
        resp.raise_for_status()
        records = _normalise_elset_records(resp.json())
        remember_sources(state, [str(rec.get("source") or "") for rec in records if isinstance(rec, dict)])
        logger.info("UDL TLE sources discovered: %s", log_safe(state.udl_available_sources))
    except Exception as exc:   # noqa: BLE001 - a background task; a failure leaves the source list as it was
        logger.warning("_discover_tle_sources failed (non-critical): %s", log_safe(exc, limit=500))


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
    state = get_session_state(current_user)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _ELSET_CURRENT_URL,
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
            logger.warning(
                "UDL login probe %d for operator %s: %s",
                resp.status_code, log_safe(current_user.username), log_safe(body, limit=500),
            )
            return render(request,
                "partials/udl_status.html",
                {"udl_user": None, "error": _udl_refused("login check", resp.status_code)},
            )
    # No raise_for_status: every non-success status returned above, so the
    # HTTPStatusError branch it fed could never run (audit F-250).
    except httpx.TimeoutException:
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": "UDL connection timed out (10 s). Check network."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL login probe failed: %s", log_safe(exc, limit=500))
        return render(request,
            "partials/udl_status.html",
            {"udl_user": None, "error": _udl_unreachable("login check")},
        )

    state.udl_username = username
    state.udl_password = password
    # Discovery adds to the list, so a login on another account without a logout between must not inherit it.
    state.udl_available_sources = []
    state.append_log(f"[UDL] Connected as {username}")
    logger.info("UDL session opened for operator: %s", log_safe(current_user.username))

    # Kick off background tasks (no-op for catalog if already loaded). The
    # element set refresh replaces every held UDL or bootstrap set with UDL's
    # newest, so nothing on screen predates the connection.
    _spawn(_fetch_onorbit_background(username, password), current_user.session_key)
    _spawn(_discover_tle_sources(username, password, state), current_user.session_key)
    _spawn(refresh_held_elsets(state, username, password), current_user.session_key)

    return render(request,
        "partials/udl_status.html",
        {
            "udl_user": username,
            "error": None,
            "tle_source": state.udl_tle_source,
            "available": state.udl_available_sources,
            "elset_refresh_started": True,
        },
    )


@router.get("/elset-refresh", response_model=None)
async def elset_refresh_status(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
) -> HTMLResponse:
    """The connect-time element set refresh: running, finished, or not started.

    The note polls this while the refresh runs. The first response after it
    finishes is the one that announces it, so the red card is re-read once.
    """
    state = get_session_state(current_user)
    refresh = state.elset_refresh
    announce = refresh is not None and not refresh.running and not refresh.announced
    if announce and refresh is not None:
        refresh.announced = True
    return render(request, _ELSET_REFRESH_TEMPLATE, {"refresh": refresh, "announce": announce})


_VALID_DATA_MODES = {"REAL", "TEST", "EXERCISE", "SIMULATED"}

# A per-request data mode outside the four is refused rather than read as REAL:
# a mistyped mode must not pull live data into an exercise, or the reverse.
_UNKNOWN_DATA_MODE_MESSAGE = (
    "Data mode must be REAL, SIMULATED, EXERCISE or TEST; nothing was fetched. "
    "Choose one of those, or Session mode."
)


def _request_data_mode(state: SessionState, requested: str) -> str | None:
    """The data mode one UDL fetch uses: *requested*, or the session's when blank.

    A named mode applies to this request only and never changes the session
    mode (SPC-030). Returns None for anything outside the four UDL modes, which
    the caller refuses.
    """
    choice = requested.strip().upper()
    if not choice:
        return state.udl_data_mode or "REAL"
    if choice in _VALID_DATA_MODES:
        return choice
    logger.info("UDL fetch refused an unknown data mode %r", log_safe(requested))
    return None


@router.post("/data-mode", response_model=None)
async def set_data_mode(
    request: Request,
    data_mode: Annotated[str, Form()],
    current_user: User = Depends(require_login),
) -> HTMLResponse:
    """Set the UDL data classification mode for this session."""
    state = get_session_state(current_user)
    mode = data_mode.strip().upper()
    if mode not in _VALID_DATA_MODES:
        # Refused, never quietly set to REAL (SPC-024): an operator meaning
        # EXERCISE would otherwise land on live data with no word said.
        logger.info("Refused session data mode %s", log_safe(mode))
        return render(request, "partials/data_mode_status.html", {
            "udl_data_mode": state.udl_data_mode,
            "data_mode_error": ("Data mode must be REAL, SIMULATED, EXERCISE or TEST; "
                                f"the session mode is still {state.udl_data_mode}."),
        })
    state.udl_data_mode = mode
    state.append_log(f"[UDL] Data mode set to {mode}")
    logger.info("UDL data mode set to %s for operator %s", log_safe(mode), log_safe(current_user.username))
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
    state = get_session_state(current_user)
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
    state = get_session_state(current_user)
    state.udl_username = None
    state.udl_password = None
    state.elset_refresh = None
    # Discovery and the refresh add to the provider list rather than replace
    # it, so the next login, perhaps on another account, starts from empty.
    state.udl_available_sources = []
    # The login's background tasks hold the password; stop them too (F-143).
    _cancel_session_tasks(current_user.session_key)
    state.append_log("[UDL] Disconnected")
    logger.info("UDL session closed for operator: %s", log_safe(current_user.username))

    return render(request,
        "partials/udl_status.html",
        {"udl_user": None, "error": None},
    )


# ── TLE fetch proxy ────────────────────────────────────────────────────────


def _tle_precheck_error(state: SessionState, mode: str, data_mode: str | None) -> str | None:
    """Return the operator-facing reason a TLE fetch cannot proceed, or None.

    Credentials live only in session state, so a missing pair means the
    operator never logged in; epoch mode has nothing to measure an elset
    against until scenario time is set; a None *data_mode* is one
    _request_data_mode refused.
    """
    if not state.udl_username or not state.udl_password:
        return _NOT_CONNECTED_MESSAGE
    if data_mode is None:
        return _UNKNOWN_DATA_MODE_MESSAGE
    if mode == "epoch" and state.scenario_start is None:
        return "No scenario time set. Configure scenario time in the Scenario Configuration panel first."
    return None


def _epoch_request_params(state: SessionState, satno: int, data_mode: str) -> dict[str, Any]:
    """The /elset query for epoch mode: up to ten elsets at or before scenario start.

    dataMode is sent only when it is not REAL. The operator's source override
    does not apply: the epoch search reaches back past any one provider.
    """
    epoch_filter = state.scenario_start.strftime("%Y-%m-%dT%H:%M:%S.000000Z")  # type: ignore[union-attr]
    params: dict[str, Any] = {"satNo": satno, "epoch": f"<{epoch_filter}", "maxResults": 10}
    if data_mode != "REAL":
        params["dataMode"] = data_mode
    return params


async def _panel_records(client: httpx.AsyncClient, state: Any, satno: int, mode: str, dm: str) -> list[Any]:
    """The records the TLE panel's *mode* query answers with. HTTP errors propagate.

    Latest mode is the newest set from every provider, or the operator's
    chosen source, as every other latest fetch takes it (``_newest_records``).
    Both credentials are set once _tle_precheck_error has passed.
    """
    auth = (state.udl_username or "", state.udl_password or "")
    if mode != "epoch":
        return await _newest_records(client, satno, auth, dm, state.udl_tle_source)
    resp = await client.get(_ELSET_URL, params=_epoch_request_params(state, satno, dm), auth=auth, timeout=10.0)
    resp.raise_for_status()
    return _normalise_elset_records(resp.json())


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
    diagnosed from the epochs that were on offer, so both go in the log: the
    epoch as read, never the set's own text, since a set the acceptance check
    refuses must not reach the log in any part (SPC-201).
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
        for key in ("epoch", "EPOCH", "epochDate"):
            if key in sample:
                logger.info("  record[%r] = %s", key, log_safe(str(sample[key])[:80]))

    # Log every candidate's line 1 epoch, as read, for diagnostics.
    for i, candidate in enumerate(records):
        ep = _parse_tle_epoch(_elset_line(candidate, 1))
        logger.info(
            "  record[%d] parsed_epoch=%s  objectName=%s",
            i,
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

    UDL answers in no order, and the archive holds several providers' sets,
    so the newest is chosen here rather than taken on trust. A record missing
    a line cannot be used, so a complete one is preferred whenever any is.
    """
    candidates = [r for r in records if _elset_line(r, 1) and _elset_line(r, 2)] or records
    best_rec = candidates[0]
    best_epoch = _parse_tle_epoch(_elset_line(best_rec, 1))
    for candidate in candidates[1:]:
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


#: The red and blue forms each hold a copy of the TLE fields, so their ids
#: carry the side the fetch is swapping into.
_FIELDS_SIDES = {"red-tle-fields": "red", "blue-tle-fields": "blue"}


def _fields_side(request: Request) -> str:
    """The form side a TLE fetch fills, from its htmx target; "tle" when unknown."""
    return _FIELDS_SIDES.get(request.headers.get("HX-Target", ""), "tle")


async def _get_elsets(state: Any, satno: int, mode: str, dm: str) -> tuple[list[Any], str | None]:
    """The TLE fetch's UDL records: ``(records, None)``, or ``([], the sentence to show)``.

    Lifted out of ``fetch_tle`` whole, which sat at the complexity limit of
    15 (SPC-060). The detail of a failure goes to the log, never the page.
    """
    try:
        async with httpx.AsyncClient() as client:
            return await _panel_records(client, state, satno, mode, dm), None
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        # The remote response body cannot go into the record verbatim
        # (pythonsecurity:S5145), nor to the operator at all (SPC-019).
        logger.warning(
            "UDL returned %s for SATNO %s: %s",
            log_safe(exc.response.status_code), log_safe(satno), log_safe(body, limit=500),
        )
        return [], _udl_refused("TLE fetch", exc.response.status_code)
    except httpx.TimeoutException:
        return [], "UDL request timed out."
    except httpx.RequestError as exc:
        logger.warning("UDL TLE fetch failed for SATNO %s: %s", log_safe(satno), log_safe(exc))
        return [], _udl_unreachable("TLE fetch")


@router.get("/tle", response_model=None)
async def fetch_tle(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    mode: str = Query("latest", description="'latest' for current elset, 'epoch' for closest to scenario start"),
    name_override: Annotated[str, Query(description="Pre-populated name (e.g. from HRR watchlist commonName)")] = "",
    data_mode: Annotated[str, Query(description="UDL data mode for this fetch only; blank uses the session mode")] = "",
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_data_rate_limit),
) -> HTMLResponse:
    """Fetch a TLE for *satno* from UDL and return a pre-filled form partial.

    Two modes are supported:

    * ``latest``: the newest elset from any provider, or the chosen TLE Source: the
      archive over the last 72 hours first, then ``/elset/current`` (see ``_newest_records``).
    * ``epoch`` — fetches up to 10 elsets with epoch ≤ scenario start time, then selects
      the one whose epoch is closest to (but not after) the scenario start.  Requires
      scenario time to be set first.  A staleness warning is shown
      when the selected TLE is more than 7 days from the scenario start.

    *data_mode* names the UDL data mode for this request alone; blank uses the
    session mode, and the session mode is never changed by it.
    """
    state = get_session_state(current_user)

    _empty = {"name": "", "tle": "", "tle_epoch_str": None,
               "tle_age_days": None, "mode": mode, "error": None,
               "fields_side": _fields_side(request)}

    dm = _request_data_mode(state, data_mode)
    precheck_error = _tle_precheck_error(state, mode, dm)
    # dm is None only when precheck_error is set; named here so mypy sees it.
    if precheck_error is not None or dm is None:
        return render(request,
            _TLE_FIELDS_TEMPLATE,
            {**_empty, "error": precheck_error},
        )

    # ── Fetch from UDL ───────────────────────────────────────────────────────
    records, fetch_error = await _get_elsets(state, satno, mode, dm)
    if fetch_error is not None:
        return render(request, _TLE_FIELDS_TEMPLATE, {**_empty, "error": fetch_error})

    if not records:
        return render(request,
            _TLE_FIELDS_TEMPLATE,
            {**_empty, "error": f"No elset found for SATNO {satno}."},
        )

    # ── Select the best record ───────────────────────────────────────────────
    logger.info(
        "UDL returned %s elset record(s) for SATNO %s mode=%s dataMode=%s",
        log_safe(len(records)), log_safe(satno), log_safe(mode), log_safe(dm),
    )

    _log_elset_diagnostics(records)

    if mode == "epoch":
        # Pick the record whose TLE epoch is closest to (and ≤) scenario_start.
        rec = _select_elset_by_epoch(records, state.scenario_start)  # type: ignore[arg-type]
        if rec is None:
            return render(request,
                _TLE_FIELDS_TEMPLATE,
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
            _TLE_FIELDS_TEMPLATE,
            {**_empty, "error": f"UDL returned an elset for SATNO {satno} with no element lines."},
        )

    # The set fills the form only once it passes the acceptance check, as the set for the number asked (SPC-201).
    refusal = refused(f"{name} ({satno})", tle, satno=satno, record=rec)
    if refusal is not None:
        return render(request, _TLE_FIELDS_TEMPLATE, {**_empty, "error": refusal})

    # TLE epoch metadata for the partial
    tle_epoch_str, tle_age_days = _tle_epoch_metadata(line1, state.scenario_start)

    state.append_log(
        f"[UDL] Fetched TLE for SATNO {satno} ({name}) mode={mode}"
        + (f" epoch={tle_epoch_str}" if tle_epoch_str else "")
    )
    logger.info(
        "TLE fetched for SATNO %s (%s) mode=%s by operator %s",
        log_safe(satno), log_safe(name), log_safe(mode), log_safe(current_user.username),
    )

    return render(request,
        _TLE_FIELDS_TEMPLATE,
        {

            "name": name,
            "tle": tle,
            "tle_epoch_str": tle_epoch_str,
            "tle_age_days": tle_age_days,
            "mode": mode,
            # The record's own mode, else the one this fetch asked for: the
            # session mode is the wrong fallback once a request names its own.
            "elset_mode": str(rec.get("dataMode") or dm).strip().upper(),
            # The provider that filed it, so the add records where the set came from.
            "elset_source": str(rec.get("source") or "").strip(),
            "data_mode_override": bool(data_mode.strip()),
            "error": None,
            "fields_side": _empty["fields_side"],
        },
    )


# ── State vector fetch proxy ───────────────────────────────────────────────



# The query used to ask for any vector after 2020 with maxResults=1, which
# returns whichever record UDL sorts first, not the newest (audit F-248). The
# window is bounded and the newest record is picked here instead.
_SV_WINDOW_DAYS = 7
_SV_MAX_RESULTS = 100


def _sv_window_start() -> str:
    """The UDL epoch filter bound, :data:`_SV_WINDOW_DAYS` before now."""
    start = datetime.now(UTC) - timedelta(days=_SV_WINDOW_DAYS)
    return f"{start.strftime(_UDL_TIME_FORMAT)}Z"


def _newest_state_vector(data: object) -> dict[str, Any] | None:
    """The record with the latest epoch, from a list or a single-object payload."""
    records: list[Any] = []
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    dated = [r for r in records if isinstance(r, dict) and isinstance(r.get("epoch"), str)]
    if not dated:
        return None
    # ISO 8601 UTC strings of one shape sort in time order.
    return max(dated, key=lambda r: str(r["epoch"]))

@router.get("/statevector", response_model=None)
async def fetch_statevector(
    request: Request,
    satno: int = Query(..., description="NORAD satellite catalog number"),
    data_mode: Annotated[str, Query(description="UDL data mode for this fetch only; blank uses the session mode")] = "",
    current_user: User = Depends(require_login),
    _rl: None = Depends(udl_data_rate_limit),
) -> HTMLResponse:
    """Fetch the latest Cartesian state vector for *satno* from UDL.

    Returns position (km) and velocity (km s⁻¹) in the J2000 reference frame
    at the newest epoch in the last week (_SV_WINDOW_DAYS). Useful for initialising high-fidelity
    intercept geometry without propagating a TLE. *data_mode* names the UDL
    data mode for this request alone; blank uses the session mode.
    """
    state = get_session_state(current_user)

    if not state.udl_username or not state.udl_password:
        return render(request,
            _STATEVECTOR_FIELDS_TEMPLATE,
            {

                "sv": None,
                "error": _NOT_CONNECTED_MESSAGE,
            },
        )

    dm = _request_data_mode(state, data_mode)
    if dm is None:
        return render(request, _STATEVECTOR_FIELDS_TEMPLATE, {"sv": None, "error": _UNKNOWN_DATA_MODE_MESSAGE})
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_UDL_BASE}/statevector",
                params={"satNo": satno, "epoch": f">{_sv_window_start()}",
                        "dataMode": dm, "maxResults": _SV_MAX_RESULTS},
                auth=(state.udl_username, state.udl_password),
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        # It showed "UDL returned 503 for SATNO ..." with no advice and logged
        # no body, the one call SPC-019's two sentences had not reached.
        body = exc.response.text[:300].strip() or "(empty)"
        logger.warning(
            "UDL state vector fetch returned %s for SATNO %s: %s",
            log_safe(exc.response.status_code), log_safe(satno), log_safe(body, limit=500),
        )
        return render(request,
            _STATEVECTOR_FIELDS_TEMPLATE,
            {"sv": None, "error": _udl_refused("state vector fetch", exc.response.status_code)},
        )
    except httpx.TimeoutException:
        return render(request,
            _STATEVECTOR_FIELDS_TEMPLATE,
            {"sv": None, "error": "UDL request timed out."},
        )
    except httpx.RequestError as exc:
        logger.warning("UDL state vector fetch failed for SATNO %s: %s", log_safe(satno), log_safe(exc))
        return render(request,
            _STATEVECTOR_FIELDS_TEMPLATE,
            {"sv": None, "error": _udl_unreachable("state vector fetch")},
        )

    rec = _newest_state_vector(data)
    if rec is None:
        return render(request,
            _STATEVECTOR_FIELDS_TEMPLATE,
            {
                "sv": None,
                "error": f"No state vector found for SATNO {satno} in the last {_SV_WINDOW_DAYS} days.",
            },
        )
    # A vector with no stated frame cannot be placed: guessing J2000 for a
    # TEME or ECEF record puts the satellite kilometres away (audit F-248).
    if not rec.get("referenceFrame"):
        return render(request,
            _STATEVECTOR_FIELDS_TEMPLATE,
            {"sv": None, "error": f"UDL state vector for SATNO {satno} has no referenceFrame; refused."},
        )
    sv = {
        "name": str(rec.get("objectName") or rec.get(_UDL_NAME_KEY_UPPER, satno)).strip(),
        "epoch": rec.get("epoch", "—"),
        "x": rec.get("xpos"),
        "y": rec.get("ypos"),
        "z": rec.get("zpos"),
        "x_dot": rec.get("xvel"),
        "y_dot": rec.get("yvel"),
        "z_dot": rec.get("zvel"),
        "ref_frame": rec["referenceFrame"],
        "data_mode": str(rec.get("dataMode") or dm).strip().upper(),
    }

    state.append_log(
        f"[UDL] Fetched state vector for SATNO {satno} ({sv['name']}) epoch {sv['epoch']}"
    )
    logger.info(
        "State vector fetched for SATNO %s (%s) by operator %s",
        log_safe(satno),
        log_safe(sv["name"]),
        log_safe(current_user.username),
    )

    return render(request,
        _STATEVECTOR_FIELDS_TEMPLATE,
        {"sv": sv, "error": None, "data_mode_override": bool(data_mode.strip())},
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
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    # A createdAt with no offset is UTC by UDL convention. Left naive, max()
    # over a mixed list raised TypeError comparing it with aware values (F-255).
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)




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
        logger.warning("HRR fetch returned HTTP %s: %s", log_safe(exc.response.status_code), log_safe(body, limit=500))
        return [], [], 0, _udl_refused("HRR fetch", exc.response.status_code)
    except httpx.TimeoutException:
        return [], [], 0, "UDL request timed out."
    except httpx.RequestError as exc:
        logger.warning("HRR fetch failed: %s", log_safe(exc, limit=500))
        return [], [], 0, _udl_unreachable("HRR fetch")

    if not notifications:
        return [], [], 0, f"No HRR notifications found in the last {_HRR_MAX_LOOKBACK_DAYS} days."

    newest = max(notifications, key=_parse_created_at)
    hrr_blue, hrr_red = parse_hrr_notification(newest)
    return hrr_blue, hrr_red, days_used, None


def _hrr_elset_fields(sat: dict[str, Any], label: str) -> dict[str, str]:
    """Return the optional element-set fields for one HRR entry, or nothing.

    Both lines must be present to be usable: half a TLE is not a degraded
    TLE, it is an unparseable one. A set the acceptance check refuses is not
    carried: the entry holds the sentence saying so, naming the object as
    *label*, in its place (SPC-201).
    """
    line1 = str(sat.get("line1") or "").strip()
    line2 = str(sat.get("line2") or "").strip()
    if not (line1 and line2):
        return {}
    tle = f"{line1}\n{line2}"
    refusal = refused(label, tle)
    if refusal is not None:
        return {"tle_refusal": refusal}
    return {"tle": tle, "tle_data_mode": str(sat.get("tleDataMode") or "REAL").strip().upper()}


def elset_refusals(objects: list[dict[str, Any]]) -> list[str]:
    """The sentence for each HRR entry whose element set the acceptance check refused, in order."""
    return [str(o["tle_refusal"]) for o in objects if o.get("tle_refusal")]


def parse_hrr_notification(notification: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse a single HRR notification dict into (blue, red) normalised satellite lists.

    Shared by the live UDL fetch and the startup loader.

    An entry MAY carry an element set as ``line1``/``line2``. A real JCO
    notification does not, so the live path is unaffected; the bundled
    bootstrap list does, which is what lets a fresh instance run before anyone
    has connected to UDL. Where present it is carried through as ``tle`` with
    its ``tle_data_mode``, so the interface can mark where it came from, once
    it passes the acceptance check; a refused one is carried as the sentence
    ``tle_refusal`` instead (SPC-201).
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
        # Optional element set, carried through only when the source has one and it passes the check.
        entry.update(_hrr_elset_fields(sat, f"{name} ({satno})"))
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
    state = get_session_state(current_user)

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

    # Cache all HRR objects in session state for threat sweep use. A set the acceptance check refused was not
    # carried: the run log says so, naming the object (SPC-201).
    state.hrr_objects = hrr_blue + hrr_red
    for refusal in elset_refusals(state.hrr_objects):
        state.append_log(f"[HRR] {refusal}")

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


_MAX_CATALOGUE_RESULTS = 50


def _catalogue_matches(catalog: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    """Up to 50 objects whose name or catalogue number contains *q*."""
    q_lower = q.strip().lower()
    results: list[dict[str, Any]] = []
    for obj in catalog:
        name = str(obj.get("name") or obj.get("objectName") or "").lower()
        satno = str(obj.get("satNo") or obj.get("satno") or "")
        if q_lower not in name and q_lower not in satno:
            continue
        results.append({
            "satno": obj.get("satNo") or obj.get("satno") or "—",
            "name": obj.get("name") or obj.get("objectName") or "—",
            "obj_type": obj.get("objectType") or obj.get("type") or "—",
            "country": obj.get("country") or "—",
        })
        if len(results) >= _MAX_CATALOGUE_RESULTS:
            break
    return results


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
    state = get_session_state(current_user)
    if q.strip() and not (state.udl_username and state.udl_password):
        return HTMLResponse('<p class="error-msg">Log in to UDL to search the on-orbit catalogue.</p>')

    catalog = get_onorbit_catalog()
    status = get_catalog_status()

    results = _catalogue_matches(catalog, q) if q.strip() else []

    return render(request,
        "partials/catalog_results.html",
        {"results": results, "q": q,
         "status": status, "total": len(catalog)},
    )


# ── Conjunction lookup ─────────────────────────────────────────────────────


_CONJUNCTION_TEMPLATE = "partials/conjunction_results.html"
_CONJUNCTION_CALL = "conjunction lookup"
_MAX_SATNO_DIGITS = 9
_BAD_SATNO_MESSAGE = "Enter a NORAD catalogue number (digits only) to look up its conjunctions."


def _conjunction_satno(raw: str) -> int | None:
    """*raw* as a catalogue number, or None. ASCII digits only, so "1e3" and "²" are not one."""
    text = raw.strip()
    if not (text.isascii() and text.isdigit()) or len(text) > _MAX_SATNO_DIGITS or int(text) == 0:
        return None
    return int(text)


def _conjunction_precheck(state: SessionState, satno: int | None, data_mode: str | None) -> str | None:
    """The operator-facing reason a conjunction lookup cannot proceed, or None."""
    if not state.udl_username or not state.udl_password:
        return _NOT_CONNECTED_MESSAGE
    if satno is None:
        return _BAD_SATNO_MESSAGE
    if data_mode is None:
        return _UNKNOWN_DATA_MODE_MESSAGE
    return None


async def _get_conjunction_pages(
    auth: tuple[str, str], satno: int, dm: str,
) -> tuple[list[tuple[str, Any]], str | None]:
    """Ask UDL for the object as sat 1 and as sat 2: ``(replies, None)``, or ``([], the sentence to show)``.

    UDL filters on one side per query, so both are asked. Either failing
    fails the lookup: half a listing would read as no close approaches on the
    other side. The detail of a failure goes to the log, never the page.
    """
    pages: list[tuple[str, Any]] = []
    try:
        async with httpx.AsyncClient() as client:
            for side in CONJUNCTION_SIDE_PARAMS:
                resp = await client.get(
                    f"{_UDL_BASE}{CONJUNCTION_PATH}",
                    params={side: satno, "dataMode": dm},
                    auth=auth,
                    timeout=15.0,
                )
                resp.raise_for_status()
                try:
                    pages.append((side, resp.json()))
                except ValueError as exc:
                    logger.warning(
                        "UDL conjunction reply for SATNO %s was not JSON (%s): %s",
                        log_safe(satno), log_safe(exc), log_safe(resp.text[:300], limit=500),
                    )
                    return [], f"UDL answered the {_CONJUNCTION_CALL} with a body SPECTRE could not read; {_DETAIL_IN_LOG}"
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].strip() or "(empty)"
        logger.warning(
            "UDL conjunction lookup returned %s for SATNO %s: %s",
            log_safe(exc.response.status_code), log_safe(satno), log_safe(body, limit=500),
        )
        return [], _udl_refused(_CONJUNCTION_CALL, exc.response.status_code)
    except httpx.TimeoutException as exc:
        logger.warning("UDL conjunction lookup timed out for SATNO %s: %s", log_safe(satno), log_safe(exc))
        return [], f"UDL did not answer the {_CONJUNCTION_CALL} in time. Try again; {_DETAIL_IN_LOG}"
    except httpx.RequestError as exc:
        logger.warning("UDL conjunction lookup failed for SATNO %s: %s", log_safe(satno), log_safe(exc))
        return [], _udl_unreachable(_CONJUNCTION_CALL)
    return pages, None


@router.get("/conjunction", response_model=None)
async def udl_conjunction(
    request: Request,
    current_user: Annotated[User, Depends(require_login)],
    _rl: Annotated[None, Depends(udl_data_rate_limit)],
    satno: Annotated[str, Query(description="NORAD catalogue number")] = "",
    data_mode: Annotated[str, Query(description="UDL data mode for this lookup only; blank uses the session mode")] = "",
) -> HTMLResponse:
    """List the conjunctions UDL holds for *satno*, newest TCA first, at most 50 (SPC-031).

    The miss distance and probability of collision are UDL's figures as
    filed; SPECTRE computes neither. *data_mode* names the UDL data mode for
    this lookup alone; blank uses the session mode, which it never changes.
    """
    state = get_session_state(current_user)
    number = _conjunction_satno(satno)
    dm = _request_data_mode(state, data_mode)
    context: dict[str, Any] = {
        "satno": number, "rows": [], "usable": 0, "skipped": 0, "unrelated": 0, "lookup_mode": dm,
        "data_mode_override": bool(data_mode.strip()), "error": None,
    }
    error = _conjunction_precheck(state, number, dm)
    # number and dm are None only when error is set; named here so mypy sees it.
    if error is not None or number is None or dm is None:
        return render(request, _CONJUNCTION_TEMPLATE, {**context, "error": error})

    # Both credentials are set once the precheck has passed; the "or" is for mypy.
    auth = (state.udl_username or "", state.udl_password or "")
    pages, error = await _get_conjunction_pages(auth, number, dm)
    if error is not None:
        return render(request, _CONJUNCTION_TEMPLATE, {**context, "error": error})

    reading = read_conjunctions(pages, number, dm)
    # Held for Interactions (SPC-173): the sweep judges these and never fetches them itself.
    hold_conjunctions(state, number, reading, dm, datetime.now(UTC))
    state.append_log(f"[UDL] Conjunction lookup for SATNO {number}: {reading.usable} record(s)")
    logger.info(
        "Conjunction lookup for SATNO %s dataMode=%s by operator %s: %s usable, %s skipped, %s unrelated",
        log_safe(number), log_safe(dm), log_safe(current_user.username),
        log_safe(reading.usable), log_safe(reading.skipped), log_safe(reading.unrelated),
    )
    return render(request, _CONJUNCTION_TEMPLATE, {
        **context, "rows": reading.rows, "usable": reading.usable,
        "skipped": reading.skipped, "unrelated": reading.unrelated,
    })


#: Output field -> the UDL fields that may carry it, in order of preference.
_NOTSO_FIELDS: dict[str, tuple[str, str]] = {
    "message_id":  ("messageId", "id"),
    "issue_date":  ("issueDate", "date"),
    "start":       ("effectiveStart", "startTime"),
    "end":         ("effectiveEnd", "stopTime"),
    "type":        ("notificationType", "type"),
    "description": ("description", "remarks"),
    "raw":         ("rawMessage", "message"),
}


def _normalise_notso(rec: dict[str, Any]) -> dict[str, str]:
    """One UDL notification in a consistent shape, whichever field names it used."""
    return {out: str(rec.get(first) or rec.get(second) or "") for out, (first, second) in _NOTSO_FIELDS.items()}


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

    state = get_session_state(current_user)
    if not state.udl_username or not state.udl_password:
        return JSONResponse({"error": "No active UDL session"}, status_code=401)

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
        except ValueError:
            return JSONResponse([])

        records = data if isinstance(data, list) else [data]
        return JSONResponse([_normalise_notso(rec) for rec in records])

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 405, 501):
            return JSONResponse([])
        logger.warning("UDL NOTSO fetch error for %s: %s", log_safe(satno), log_safe(exc))
        return JSONResponse({"error": "UDL refused the NOTSO request; the server log has the detail."}, status_code=502)
    except (httpx.HTTPError, AttributeError) as exc:   # AttributeError: a record that is not an object
        logger.warning("UDL NOTSO fetch failed for %s: %s", log_safe(satno), log_safe(exc))
        return JSONResponse({"error": "UDL NOTSO fetch failed; the server log has the detail."}, status_code=502)


_NOTSO_PAGE = 500


def _notso_query(latest: datetime | None) -> dict[str, str | int]:
    """UDL query for TACREP_NOTSO records newer than the cache holds.

    An empty cache starts at 2024-01-01, to pull reasonable history without
    hitting UDL too hard; otherwise the newest record plus 1 microsecond, so
    the boundary record is not fetched again.
    """
    from datetime import timedelta

    since = latest + timedelta(microseconds=1) if latest is not None else datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "createdAt":  f">{since.strftime(_UDL_TIME_FORMAT)}Z",
        "dataMode":   "REAL",
        "msgType":    "TACREP_NOTSO",
        "source":     "JCO",
        "maxResults": _NOTSO_PAGE,
    }


def _notso_page_records(resp: Any, page: int) -> tuple[list[Any] | None, str | None]:
    """One page's records, or the reason paging stops here."""
    if resp.status_code in (404, 405, 501):
        return None, (
            f"UDL /notification endpoint returned HTTP {resp.status_code} — "
            "TACREP_NOTSO may not be available on this instance."
        )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("NOTSO sync page %d failed: %s", page, log_safe(exc, limit=500))
        return None, f"HTTP error on page {page}: {_udl_refused('NOTSO sync', resp.status_code)}"
    try:
        data = resp.json()
    # BLE001: any undecodable body ends paging with a reason, not a 500.
    except Exception:  # noqa: BLE001
        return None, f"Non-JSON response on page {page}"
    if isinstance(data, list):
        return data, None
    return ([data] if data else []), None


async def _pull_notso_pages(
    cache: Any, base_params: dict[str, str | int], auth: tuple[str, str],
) -> tuple[int, int, list[str]]:
    """Page through /notification into *cache*: (records added, pages, errors)."""
    total_added = 0
    page = 0
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                params: dict[str, str | int] = dict(base_params)
                if page > 0:
                    params["offset"] = page * _NOTSO_PAGE
                resp = await client.get(f"{_UDL_BASE}/notification", params=params, auth=auth)
                records, error = _notso_page_records(resp, page)
                if error:
                    errors.append(error)
                if not records:
                    break
                # A sync page rewrites the whole file; off the event loop (F-141).
                total_added += await asyncio.to_thread(cache.append, records)
                page += 1
                # Fewer than a full page means the end has been reached.
                if len(records) < _NOTSO_PAGE:
                    break
    # BLE001: a failed sync is reported with what it had added so far.
    except Exception as exc:  # noqa: BLE001
        errors.append(f"The NOTSO sync stopped before it finished. Try the sync again; {_DETAIL_IN_LOG}")
        logger.warning("notso_sync failed: %s", log_safe(exc, limit=500))
    return total_added, page, errors


def _notso_sync_status(total_added: int, errors: list[str], cache: Any) -> str:
    """The status callout: red when nothing was added and something failed."""
    if errors and total_added == 0:
        # Escaped, though the messages are fixed sentences now (SPC-019): one
        # that ever carries a value again must not become markup (F-249).
        error_html = "".join(f'<p style="margin:0.1rem 0">{html.escape(e)}</p>' for e in errors)
        return f'<div class="callout callout-red" style="font-size:0.72rem">{error_html}</div>'
    warn_html = "".join(
        f'<p style="margin:0.1rem 0; font-size:0.68rem; color:var(--text-dim)">⚠ {html.escape(e)}</p>'
        for e in errors
    )
    return (
        f'<div class="callout callout-green" style="font-size:0.72rem; padding:0.4rem 0.6rem">'
        f'<strong>+{total_added}</strong> new records added &mdash; '
        f'{cache.total_records()} total in cache. Last sync: {cache.last_sync_utc() or "—"}.'
        f'</div>{warn_html}'
    )


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
    ``notso_cache.json`` in the configured data directory.

    Always returns an HTML partial suitable for ``hx-swap="innerHTML"`` on the
    NOTSO sync status ``<div>``.
    """
    from fastapi.responses import HTMLResponse as _HTMLResponse

    from spectre.data.notso_cache import get_notso_cache

    state = get_session_state(current_user)
    if not state.udl_username or not state.udl_password:
        return _HTMLResponse(
            '<p class="error-msg" style="font-size:0.72rem">No active UDL session — connect first.</p>'
        )

    cache = get_notso_cache()
    params = _notso_query(cache.latest_created_at())
    total_added, page, errors = await _pull_notso_pages(
        cache, params, (state.udl_username, state.udl_password),
    )

    state.append_log(
        f"[NOTSO] Sync complete: +{total_added} new records "
        f"(total {cache.total_records()}, {page} page(s) fetched)"
    )
    return _HTMLResponse(_notso_sync_status(total_added, errors, cache))
