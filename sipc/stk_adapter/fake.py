"""FakeStkSession — in-memory IStkSession implementation for unit testing."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sipc.domain.models import AccessInterval

logger = logging.getLogger(__name__)


class FakeStkSession:
    """In-memory double for :class:`~sipc.stk_adapter.interface.IStkSession`.

    Satisfies the IStkSession Protocol without any COM dependencies.
    Stores state in plain Python dicts for easy assertion in tests.

    Attributes:
        connected: Whether ``connect()`` has been called without ``disconnect()``.
        scenario_path: Path passed to the last ``connect()`` call.
        satellites: Mapping of STK name → group for created satellites.
        propagators: Mapping of STK name → TLE string.
        actions_log: Ordered list of ``(run_id, action, payload)`` tuples.
        access_intervals: Pre-configured intervals returned by ``compute_access()``.
        epoch: The scenario epoch returned by ``get_scenario_epoch()``.
    """

    def __init__(self) -> None:
        self.connected: bool = False
        self.scenario_path: str = ""
        self.satellites: dict[str, str] = {}
        self.propagators: dict[str, str] = {}
        self.actions_log: list[tuple[str, str, dict[str, Any]]] = []
        self.access_intervals: list[AccessInterval] = []
        self.epoch: datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    # ── IStkSession interface ─────────────────────────────────────────────────

    def connect(self, scenario_path: str) -> None:
        """Record connection; no actual COM call is made."""
        self.connected = True
        self.scenario_path = scenario_path
        logger.debug("FakeStkSession.connect", extra={"scenario_path": scenario_path})

    def new_scenario(self, name: str) -> None:
        """Record new-scenario creation; resets satellite/propagator state."""
        self.connected = True
        self.scenario_path = ""
        self.satellites.clear()
        self.propagators.clear()
        self.actions_log.clear()
        logger.debug("FakeStkSession.new_scenario", extra={"name": name})

    def disconnect(self) -> None:
        """Record disconnection."""
        self.connected = False
        logger.debug("FakeStkSession.disconnect")

    def create_satellite(self, name: str, group: str) -> str:
        """Store satellite in memory and return its STK path."""
        stk_path = f"{group}/{name}"
        self.satellites[name] = group
        logger.debug("FakeStkSession.create_satellite", extra={"name": name, "group": group})
        return stk_path

    def set_propagator(self, sat_name: str, tle: str) -> None:
        """Store TLE assignment in memory."""
        self.propagators[sat_name] = tle
        logger.debug("FakeStkSession.set_propagator", extra={"sat_name": sat_name})

    def compute_access(self, obj_a: str, obj_b: str) -> list[AccessInterval]:
        """Return pre-configured access intervals (default: empty list)."""
        logger.debug(
            "FakeStkSession.compute_access", extra={"obj_a": obj_a, "obj_b": obj_b}
        )
        return list(self.access_intervals)

    def get_scenario_epoch(self) -> datetime:
        """Return the configured epoch (default: 2026-01-01T00:00:00Z)."""
        return self.epoch

    def log_action(self, run_id: str, action: str, payload: dict[str, Any]) -> None:
        """Append action to the in-memory log."""
        self.actions_log.append((run_id, action, payload))
        logger.debug(
            "FakeStkSession.log_action",
            extra={"run_id": run_id, "action": action},
        )
