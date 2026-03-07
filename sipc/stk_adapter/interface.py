"""IStkSession — structural Protocol defining the STK adapter contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sipc.domain.models import AccessInterval, ManeuverOption, ManeuverSearchConfig


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

    def compute_maneuver_options(
        self, config: ManeuverSearchConfig
    ) -> list[ManeuverOption]:
        """Enumerate viable intercept maneuver options via Astrogator MCS.

        For each enabled :class:`~sipc.domain.models.BurnLocation` in *config*,
        builds an Astrogator Mission Control Sequence on the red satellite and
        runs a differential corrector targeting the blue satellite.  Converged
        solutions are returned as :class:`~sipc.domain.models.ManeuverOption`
        instances; non-convergent candidates are silently dropped.

        The red satellite's propagator is always restored to SGP4 after the
        search completes, regardless of success or failure.

        Args:
            config: Search parameters including satellite names, time window,
                delta-V budget, burn types, and burn locations.

        Returns:
            List of :class:`~sipc.domain.models.ManeuverOption`, sorted by
            ``delta_v_km_s`` ascending.  May be empty if no solutions converge
            within the given constraints.

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If the Astrogator module is unavailable or the
                satellite objects cannot be found.
        """
        ...

    def apply_maneuver(self, red_sat: str, option: ManeuverOption) -> None:
        """Write a selected maneuver option into the red satellite's Astrogator MCS.

        Replaces the red satellite's current propagator with an Astrogator
        sequence encoding the selected burn.  After this call the satellite
        will propagate along the intercept trajectory when STK rewinds.

        Args:
            red_sat: STK object name of the red satellite.
            option: The :class:`~sipc.domain.models.ManeuverOption` to apply.

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If the MCS cannot be constructed or propagated.
        """
        ...

    def list_scenario_satellites(self) -> list[str]:
        """Return the STK instance names of all Satellite objects in the current scenario.

        Useful for importing pre-existing satellites (loaded directly in STK or
        left over from a previous SIPC session) into the operator's session state
        without re-creating or re-propagating them.

        Returns:
            List of STK object instance names, e.g. ``["B_SAT_Alpha", "R_SAT_Track01"]``.
            Empty if no satellites exist or no scenario is loaded.

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If the children cannot be enumerated.
        """
        ...

    def get_satellite_tle(self, sat_name: str) -> str | None:
        """Return the current TLE (line 1 and line 2) for an existing satellite.

        Reads the TLE directly from the satellite's SGP4 propagator in the STK
        scenario.  Used when importing pre-existing satellites so that their TLE
        is available in session state without requiring a fresh UDL fetch.

        Args:
            sat_name: STK object name of the satellite (e.g. ``B_SAT_Alpha``).

        Returns:
            Two-line TLE string (``"<line1>\\n<line2>"``), or ``None`` if the
            satellite does not exist, has no SGP4 segments, or the TLE cannot
            be read.
        """
        ...

    def get_scenario_time(self) -> tuple[datetime, datetime]:
        """Return the scenario analysis start and stop epochs as UTC datetimes.

        Returns:
            ``(start, stop)`` — both UTC-aware datetimes.

        Raises:
            StkConnectionError: If not connected to STK or no scenario is loaded.
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
