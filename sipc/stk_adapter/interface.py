"""IStkSession — structural Protocol defining the STK adapter contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sipc.domain.models import AccessInterval


@runtime_checkable
class IStkSession(Protocol):
    """Structural interface for an STK session.

    All implementations (COM-based, fake, future REST-based) must satisfy
    this Protocol. Consumers depend only on this interface, never on a
    concrete class, enabling full substitutability for unit testing.
    """

    def connect(self, scenario_path: str) -> None:
        """Attach to a running STK instance and optionally load an existing scenario.

        Args:
            scenario_path: Absolute path to the ``.sc`` scenario file, or an
                empty string to attach to an already-running STK instance.

        Raises:
            StkConnectionError: If STK is not reachable or the scenario fails to load.
        """
        ...

    def setup_scenario_folders(self, folders: list[str]) -> None:
        """Create the standard scenario folder structure.

        Called immediately after :meth:`new_scenario` to pre-create the
        canonical organisational folders (``/Blue``, ``/Red``, etc.).
        Implementations should tolerate folders that already exist.

        Args:
            folders: List of folder paths as defined in
                ``sipc.config.constants.STK_FOLDERS`` (e.g. ``["/Blue", "/Red", ...]``).
        """
        ...

    def new_scenario(self, name: str) -> None:
        """Create a brand-new blank scenario in STK.

        Any currently-open scenario is closed before the new one is created.

        Args:
            name: The scenario name (no path required; STK manages the file
                location until the operator saves it).

        Raises:
            StkConnectionError: If STK is not running or the scenario cannot
                be created.
        """
        ...

    def disconnect(self) -> None:
        """Release the STK COM connection and free resources."""
        ...

    def create_satellite(self, name: str, group: str) -> str:
        """Create a satellite object in the scenario.

        Args:
            name: STK object name (e.g. ``B_SAT_Alpha``).
            group: Scenario folder path (e.g. ``/Blue``).

        Returns:
            The full STK object path of the created satellite.

        Raises:
            StkCommandError: If the satellite cannot be created.
        """
        ...

    def set_propagator(self, sat_name: str, tle: str) -> None:
        """Assign a TLE propagator to an existing satellite.

        Args:
            sat_name: STK object name of the satellite.
            tle: Two-line element set as a two-line string (lines 1 & 2).

        Raises:
            StkObjectNotFoundError: If *sat_name* does not exist in the scenario.
            StkCommandError: If the propagator assignment fails.
        """
        ...

    def compute_access(self, obj_a: str, obj_b: str) -> list[AccessInterval]:
        """Compute access intervals between two STK objects.

        Args:
            obj_a: STK path of the first object.
            obj_b: STK path of the second object.

        Returns:
            List of :class:`~sipc.domain.models.AccessInterval` instances,
            ordered chronologically. Empty list if no access exists.

        Raises:
            StkObjectNotFoundError: If either object is not found.
            StkCommandError: If the access computation fails.
        """
        ...

    def set_scenario_time(self, start: datetime, stop: datetime) -> None:
        """Set the scenario analysis time window.

        Args:
            start: UTC-aware scenario start epoch.
            stop: UTC-aware scenario stop epoch.

        Raises:
            StkConnectionError: If not connected.
        """
        ...

    def get_scenario_epoch(self) -> datetime:
        """Return the scenario start epoch as a UTC-aware datetime.

        Returns:
            Scenario epoch in UTC.

        Raises:
            StkConnectionError: If no scenario is loaded.
        """
        ...

    def log_action(self, run_id: str, action: str, payload: dict[str, Any]) -> None:
        """Record a provenance-tagged adapter action.

        All STK calls should be logged via this method to maintain a full
        audit trail keyed by *run_id*.

        Args:
            run_id: Planning run identifier (e.g. ``RUN_20260304_001``).
            action: Short description of the action (e.g. ``create_satellite``).
            payload: Arbitrary key/value pairs describing the action parameters.
        """
        ...
