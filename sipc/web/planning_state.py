"""Per-session in-memory planning state for SIPC web console.

In a single-node deployment this module holds run results and asset lists
in a plain dict keyed by session username.  Replace with a Redis-backed
store for multi-node cloud deployments.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from typing import Any

from sipc.domain.models import BlueAsset, InterceptWindow, RedTrack

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
        log_entries: Recent log entries (for polling fallback).
    """

    blue_assets: list[BlueAsset] = field(default_factory=list)
    red_tracks: list[RedTrack] = field(default_factory=list)
    results: list[InterceptWindow] = field(default_factory=list)
    log_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    log_entries: list[str] = field(default_factory=list)
    # UDL credentials — held in memory for this session only, never persisted.
    udl_username: str | None = None
    udl_password: str | None = None
    # Live STK session — None means planning runs use FakeStkSession.
    stk_session: Any | None = None
    stk_scenario: str = ""

    def append_log(self, message: str) -> None:
        """Append *message* to the session log, evicting oldest if needed."""
        if len(self.log_entries) >= _MAX_LOG_ENTRIES:
            self.log_entries.pop(0)
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
