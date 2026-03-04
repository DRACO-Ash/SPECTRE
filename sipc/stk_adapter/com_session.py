"""StkComSession — IStkSession implementation via pywin32 COM automation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sipc.domain.models import AccessInterval
from sipc.stk_adapter.exceptions import StkConnectionError

logger = logging.getLogger(__name__)


class StkComSession:
    """Live STK session implemented via the STK 13 Object Model (COM).

    This class is the production adapter. It is deliberately kept thin —
    all business logic lives in the domain layer. Each public method:

    1. Validates preconditions (e.g. connected).
    2. Translates domain objects → STK Connect commands or COM calls.
    3. Logs the action via ``log_action`` for provenance.
    4. Translates COM results → domain objects.

    COM imports are deferred to ``connect()`` so that the module can be
    *imported* on non-Windows machines (CI) without import errors.

    Attributes:
        _app: The ``STK.Application`` COM object, or ``None`` if not connected.
        _root: The ``IAgStkObjectRoot`` interface, or ``None`` if not connected.
    """

    def __init__(self) -> None:
        self._app: Any = None
        self._root: Any = None

    # ── IStkSession interface ─────────────────────────────────────────────────

    def connect(self, scenario_path: str) -> None:
        """Attach to a running STK instance and optionally load a scenario.

        Args:
            scenario_path: Absolute path to a ``.sc`` scenario file.
                Pass an empty string to attach to an already-open scenario.

        Raises:
            StkConnectionError: If STK is not running or the scenario fails to load.
        """
        try:
            import win32com.client  # type: ignore[import]

            self._app = win32com.client.Dispatch("STK13.Application")
            self._app.Visible = True
            self._root = self._app.Personality2
            if scenario_path:
                self._root.LoadScenario(scenario_path)
            logger.info("Connected to STK", extra={"scenario_path": scenario_path})
        except Exception as exc:
            raise StkConnectionError(f"Failed to connect to STK: {exc}") from exc

    def disconnect(self) -> None:
        """Release COM references."""
        self._root = None
        self._app = None
        logger.info("Disconnected from STK")

    def create_satellite(self, name: str, group: str) -> str:
        """Create a satellite in the STK scenario.

        Args:
            name: STK object name.
            group: Scenario folder (e.g. ``/Blue``).

        Returns:
            STK object path of the new satellite.

        Raises:
            StkConnectionError: If not connected.
        """
        self._require_connection()
        # TODO: implement via IAgStkObjectRoot.Children.New(eSatellite, name)
        #       and move to the correct group folder.
        stk_path = f"{group}/{name}"
        logger.info("create_satellite (stub)", extra={"name": name, "group": group})
        return stk_path

    def set_propagator(self, sat_name: str, tle: str) -> None:
        """Assign a TLE propagator to a satellite.

        Args:
            sat_name: STK object name.
            tle: Two-line element string.

        Raises:
            StkConnectionError: If not connected.
        """
        self._require_connection()
        # TODO: implement via satellite.SetPropagatorType(ePropagatorStkExternal)
        #       and load TLE lines.
        logger.info("set_propagator (stub)", extra={"sat_name": sat_name})

    def compute_access(self, obj_a: str, obj_b: str) -> list[AccessInterval]:
        """Compute access intervals between two STK objects.

        Args:
            obj_a: STK path of object A.
            obj_b: STK path of object B.

        Returns:
            List of :class:`~sipc.domain.models.AccessInterval` in chronological order.

        Raises:
            StkConnectionError: If not connected.
        """
        self._require_connection()
        # TODO: implement via IAgStkObject.GetAccessTo(obj_b).ComputeAccess()
        logger.info(
            "compute_access (stub)", extra={"obj_a": obj_a, "obj_b": obj_b}
        )
        return []

    def get_scenario_epoch(self) -> datetime:
        """Return the scenario start epoch as UTC-aware datetime.

        Raises:
            StkConnectionError: If not connected.
        """
        self._require_connection()
        # TODO: parse self._root.CurrentScenario.StartTime
        logger.info("get_scenario_epoch (stub)")
        return datetime(2026, 1, 1, tzinfo=timezone.utc)

    def log_action(self, run_id: str, action: str, payload: dict[str, Any]) -> None:
        """Log a provenance-tagged STK action.

        Args:
            run_id: Planning run identifier.
            action: Short action description.
            payload: Arbitrary key/value action parameters.
        """
        logger.info(
            "stk_action",
            extra={"run_id": run_id, "action": action, "payload": payload},
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _require_connection(self) -> None:
        """Raise StkConnectionError if not connected."""
        if self._root is None:
            raise StkConnectionError(
                "Not connected to STK. Call connect() before issuing commands."
            )
