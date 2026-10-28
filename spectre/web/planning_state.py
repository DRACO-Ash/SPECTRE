"""Per-session in-memory planning state for SPECTRE web console.

In a single-node deployment this module holds run results and asset lists
in a plain dict keyed by sign-in (account id and session id).  Replace with a Redis-backed
store for multi-node cloud deployments.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from spectre.domain.models import (
    BlueAsset,
    InterceptResult,
    InterceptWindow,
    ManeuverOption,
    ManeuverSearchConfig,
    RedTrack,
    ThreatAssessment,
)
from spectre.web.models import SessionKey

logger = logging.getLogger(__name__)

# Maximum log entries retained per session before eviction (FIFO).
_MAX_LOG_ENTRIES = 200


@dataclass
class ElsetRefresh:
    """The refresh of every held element set made when UDL connects.

    *updated*, *failed* name each object ("red SY-12 02"); *current* counts
    the ones UDL had nothing newer for. *announced* is set once the page has
    been told the refresh finished, so it is told once.
    """

    started_at: datetime
    finished_at: datetime | None = None
    running: bool = True
    updated: list[str] = field(default_factory=list)
    current: int = 0
    failed: list[str] = field(default_factory=list)
    announced: bool = False


@dataclass
class SessionState:
    """Mutable state for one operator session.

    Attributes:
        blue_assets: List of friendly assets added in this session.
        red_tracks: List of threat tracks added in this session.
        results: Last set of :class:`InterceptWindow` results from ``/plan``.
        log_entries: The newest 200 log entries; older ones are evicted.
    """

    blue_assets: list[BlueAsset] = field(default_factory=list)
    red_tracks: list[RedTrack] = field(default_factory=list)
    results: list[InterceptWindow] = field(default_factory=list)
    log_entries: deque[str] = field(
        default_factory=lambda: deque(maxlen=_MAX_LOG_ENTRIES)
    )
    # UDL credentials — held in memory for this session only, never persisted.
    udl_username: str | None = None
    udl_password: str | None = None
    # UDL data classification: REAL | TEST | EXERCISE | SIMULATED.
    udl_data_mode: str = "REAL"
    # Scenario time window — set by the operator.
    scenario_start: datetime | None = None
    scenario_stop: datetime | None = None
    # Maneuver options from the last search run.
    maneuver_options: list[ManeuverOption] = field(default_factory=list)
    # The option the operator has selected for application.
    selected_maneuver: ManeuverOption | None = None
    # Config from the most recent maneuver search — used by /refresh.
    last_maneuver_config: ManeuverSearchConfig | None = None
    # Result from the last intercept engine calculation.
    last_intercept_result: InterceptResult | None = None
    # History of all intercept results this session (for trade-space plot).
    intercept_history: list[InterceptResult] = field(default_factory=list)
    # Threat sweep result.
    last_threat_assessment: ThreatAssessment | None = None
    # HRR TLE cache: SATNO → TLE (persists across sweeps).
    hrr_tle_cache: dict[str, str] = field(default_factory=dict)
    # Parallel data-mode cache: SATNO → UDL dataMode tag for the cached TLE.
    hrr_tle_data_mode: dict[str, str] = field(default_factory=dict)
    # Cached HRR satellite list from UDL.
    hrr_objects: list[dict[str, Any]] = field(default_factory=list)
    # TLE source filter — empty string means "UDL default" (no filter).
    udl_tle_source: str = ""
    # Available TLE sources discovered from UDL after login.
    udl_available_sources: list[str] = field(default_factory=list)
    # Manually added TLE targets for threat sweep: [{name, tle, confidence}]
    manual_sweep_tles: list[dict[str, Any]] = field(default_factory=list)
    # Multi-TLE cache for clustering: SATNO → [TLE strings] from all providers.
    # Populated by fetch-targets alongside hrr_tle_cache; consumed by the
    # clustering step at sweep time. A satno absent from this dict means only
    # one TLE was returned by UDL (nothing to cluster).
    hrr_tle_multiset: dict[str, list[str]] = field(default_factory=dict)
    # The element set refresh started at UDL connect, while it runs and after.
    elset_refresh: ElsetRefresh | None = None

    def __repr__(self) -> str:
        """Safe repr that never leaks the UDL password."""
        return (
            f"SessionState(username={self.udl_username!r}, "
            f"blue={len(self.blue_assets)}, red={len(self.red_tracks)}, "
            f"hrr_cache={len(self.hrr_tle_cache)})"
        )

    def tle_of(self, name: str) -> str | None:
        """The TLE of the blue asset or red track called *name*, if any.

        Three routes kept their own copy of this lookup (audit F-241).
        """
        for asset in self.blue_assets:
            if asset.stk_name == name:
                return asset.tle
        for track in self.red_tracks:
            if track.stk_name == name:
                return track.tle
        return None

    def append_log(self, message: str) -> None:
        """Append *message* to the session log, evicting the oldest past 200.

        The log used to be copied to an unbounded queue that nothing read, so
        every line a session wrote was retained (audit F-154).
        """
        self.log_entries.append(message)


# Module-level store: one sign-in → SessionState, with when it was created.
#
# Keyed by SessionKey (account id and the sign-in's random id), not the
# username. Keyed by name, the state outlived the account: a recreated
# namesake inherited the old holder's UDL password and results (audit F-148),
# and every concurrent sign-in of a user drove UDL with whichever password the
# last one entered (audit F-044).
_store: dict[SessionKey, tuple[float, SessionState]] = {}

# No token is accepted after this long (spectre.web.auth._SESSION_MAX_AGE), so
# state older than it can never be reached again and is dropped.
_STATE_MAX_AGE_S = 28_800


class _HasSessionKey(Protocol):
    session_key: SessionKey | None


def _key_of(owner: SessionKey | _HasSessionKey) -> SessionKey:
    if isinstance(owner, SessionKey):
        return owner
    if owner.session_key is None:
        raise RuntimeError("planning state requested for a request with no authenticated sign-in")
    return owner.session_key


def _prune(now: float) -> None:
    for key in [k for k, (created, _) in _store.items() if now - created > _STATE_MAX_AGE_S]:
        del _store[key]


def get_session_state(owner: SessionKey | _HasSessionKey) -> SessionState:
    """Return the :class:`SessionState` for this sign-in, creating it if absent.

    *owner* is the authenticated user from ``require_login``, which carries the
    sign-in's key, or a :class:`SessionKey` directly.

    New sessions are pre-populated with the default HRR object list, and with
    any element sets that came with it, so the threat sweep and the asset
    screen are usable immediately without a live UDL connection. An object
    list on its own is not enough: both capabilities need an element set per
    object, so seeding the list alone would populate a dropdown that then
    refuses to run.
    """
    key = _key_of(owner)
    now = time.monotonic()
    _prune(now)
    if key not in _store:
        state = SessionState()
        if _default_hrr_objects:
            state.hrr_objects = list(_default_hrr_objects)
        if _default_hrr_tles:
            state.hrr_tle_cache.update(_default_hrr_tles)
            state.hrr_tle_data_mode.update(_default_hrr_tle_modes)
        _store[key] = (now, state)
        logger.debug("Created new session state for account %d", key.user_id)
    return _store[key][1]


def has_session_state(key: SessionKey) -> bool:
    """Whether this sign-in still holds planning state."""
    return key in _store


def clear_session_state(owner: SessionKey | _HasSessionKey) -> None:
    """Remove and discard the state for one sign-in."""
    _store.pop(_key_of(owner), None)


def clear_account_state(user_id: int) -> None:
    """Discard the state of every sign-in of an account.

    Called when its sessions are revoked (logout, password change) and when it
    is deleted, so its UDL password goes with them.
    """
    for key in [k for k in _store if k.user_id == user_id]:
        del _store[key]


# ── App-level on-orbit catalog (shared across all operator sessions) ─────────
# Fetched in the background on first successful UDL login.
_onorbit_catalog: list[dict[str, Any]] = []
_catalog_status: str = "not_loaded"  # "not_loaded" | "loading" | "ready" | "error"


def get_onorbit_catalog() -> list[dict[str, Any]]:
    """Return the cached on-orbit catalog records."""
    return _onorbit_catalog


def get_catalog_status() -> str:
    """Return the current catalog load status string."""
    return _catalog_status


def set_onorbit_catalog(records: list[dict[str, Any]]) -> None:
    """Replace the catalog cache and mark status ready."""
    global _onorbit_catalog, _catalog_status
    _onorbit_catalog = records
    _catalog_status = "ready"
    logger.info("On-orbit catalog cached: %d objects", len(records))


def set_catalog_status(status: str) -> None:
    """Update the catalog load status."""
    global _catalog_status
    _catalog_status = status


# ── App-level HRR default (loaded from HRR_List.json at startup) ─────────────
# Pre-populates new operator sessions so the threat sweep works immediately,
# before the operator connects to UDL for a live refresh.
_default_hrr_objects: list[dict[str, Any]] = []


def set_default_hrr_objects(objects: list[dict[str, Any]]) -> None:
    """Store the parsed HRR list loaded from the local cache file at startup."""
    global _default_hrr_objects
    _default_hrr_objects = objects
    logger.info("Default HRR objects loaded: %d satellites", len(objects))


def get_default_hrr_objects() -> list[dict[str, Any]]:
    """Return the default HRR object list (loaded at startup)."""
    return _default_hrr_objects


#: Element sets that arrived with the default watchlist, keyed by satno, with
#: the provenance of each. Empty unless the loaded list carried them.
_default_hrr_tles: dict[str, str] = {}
_default_hrr_tle_modes: dict[str, str] = {}


def set_default_hrr_tles(tles: dict[str, str], modes: dict[str, str]) -> None:
    """Store element sets that came with the default watchlist."""
    # Boot-time default state, written once by the startup loader and read-only
    # for the rest of the process, exactly like the catalogue and HRR-object
    # setters above. This module IS the single-node store, as its docstring
    # says; wrapping one of the four module globals in a holder object would
    # leave the other three as they are and make this pair the odd case a
    # reader has to work out, which is a loss, not an improvement.
    global _default_hrr_tles, _default_hrr_tle_modes  # noqa: PLW0603
    _default_hrr_tles = dict(tles)
    _default_hrr_tle_modes = dict(modes)
    synthetic = sum(1 for m in modes.values() if m != "REAL")
    if tles:
        logger.info(
            "Default HRR element sets loaded: %d (%d not from live tracking)",
            len(tles), synthetic,
        )


def get_default_hrr_tles() -> tuple[dict[str, str], dict[str, str]]:
    """Return the default element sets and their provenance."""
    return _default_hrr_tles, _default_hrr_tle_modes
