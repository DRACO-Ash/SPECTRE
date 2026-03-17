"""Per-session in-memory planning state for SIPC web console.

In a single-node deployment this module holds run results and asset lists
in a plain dict keyed by session username.  Replace with a Redis-backed
store for multi-node cloud deployments.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from sipc.domain.models import (
    BlueAsset,
    InterceptResult,
    InterceptWindow,
    ManeuverOption,
    ManeuverSearchConfig,
    RedTrack,
    ThreatAssessment,
)

logger = logging.getLogger(__name__)

# Maximum log entries retained per session before eviction (FIFO).
_MAX_LOG_ENTRIES = 200


@dataclass
class SessionState:
    """Mutable state for one operator session.

    Attributes:
        blue_assets: List of friendly assets added in this session.
        red_tracks: List of threat tracks added in this session.
        results: Last set of :class:`InterceptWindow` results from ``/plan``.
        log_queue: Async queue of log-line strings for SSE streaming.
        log_entries: Fixed-size deque of recent log entries (polling fallback).
            Oldest entries are evicted automatically when the deque is full.
    """

    blue_assets: list[BlueAsset] = field(default_factory=list)
    red_tracks: list[RedTrack] = field(default_factory=list)
    results: list[InterceptWindow] = field(default_factory=list)
    log_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
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
    # Cached HRR satellite list from UDL.
    hrr_objects: list[dict] = field(default_factory=list)

    def append_log(self, message: str) -> None:
        """Append *message* to the session log.

        The underlying :class:`collections.deque` automatically evicts the
        oldest entry when the log is full — no manual size check required.
        """
        self.log_entries.append(message)
        try:
            self.log_queue.put_nowait(message)
        except asyncio.QueueFull:
            pass


# Module-level store: username → SessionState.
_store: dict[str, SessionState] = {}


def get_session_state(username: str) -> SessionState:
    """Return the :class:`SessionState` for *username*, creating it if absent."""
    if username not in _store:
        _store[username] = SessionState()
        logger.debug("Created new session state for user: %s", username)
    return _store[username]


def clear_session_state(username: str) -> None:
    """Remove and discard the state for *username* (e.g. on logout)."""
    _store.pop(username, None)


# ── App-level on-orbit catalog (shared across all operator sessions) ─────────
# Fetched in the background on first successful UDL login.
_onorbit_catalog: list[dict] = []
_catalog_status: str = "not_loaded"  # "not_loaded" | "loading" | "ready" | "error"


def get_onorbit_catalog() -> list[dict]:
    """Return the cached on-orbit catalog records."""
    return _onorbit_catalog


def get_catalog_status() -> str:
    """Return the current catalog load status string."""
    return _catalog_status


def set_onorbit_catalog(records: list[dict]) -> None:
    """Replace the catalog cache and mark status ready."""
    global _onorbit_catalog, _catalog_status
    _onorbit_catalog = records
    _catalog_status = "ready"
    logger.info("On-orbit catalog cached: %d objects", len(records))


def set_catalog_status(status: str) -> None:
    """Update the catalog load status."""
    global _catalog_status
    _catalog_status = status
