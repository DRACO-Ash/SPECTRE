"""StkComSession -- IStkSession implementation via pywin32 COM automation."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sipc.domain.models import AccessInterval
from sipc.stk_adapter.exceptions import (
    StkCommandError,
    StkConnectionError,
    StkObjectNotFoundError,
)

logger = logging.getLogger(__name__)

# STK date string format: "1 Jan 2026 00:00:00.000"  (UTCG)
_STK_TIME_RE = re.compile(r"\.\d+$")


def _parse_stk_time(stk_time: str) -> datetime:
    """Parse an STK UTCG time string to a UTC-aware :class:`datetime`.

    Handles the default STK format ``d Mmm yyyy HH:mm:ss.sss`` as well as
    ISO 8601 strings (in case the scenario unit preferences are overridden).
    """
    s = stk_time.strip()
    try:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    except ValueError:
        pass
    # Strip fractional seconds then parse STK default format
    s_clean = _STK_TIME_RE.sub("", s)
    return datetime.strptime(s_clean, "%d %b %Y %H:%M:%S").replace(tzinfo=UTC)


def _to_stk_time(dt: datetime) -> str:
    """Format a UTC-aware datetime as an STK UTCG time string.

    Produces the format STK expects for ``SetTimePeriod`` and similar calls:
    ``"d Mon YYYY HH:MM:SS.000"``  (e.g. ``"5 Mar 2026 12:00:00.000"``).
    """
    return f"{dt.day} {dt.strftime('%b %Y %H:%M:%S')}.000"


def _check(result: Any, context: str) -> None:
    """Raise :class:`StkCommandError` if an ExecuteCommand result failed."""
    if result.IsSucceeded == 0:
        raise StkCommandError(f"{context}: {result.Message}")


class StkComSession:
    """Live STK session implemented via the STK 13 Object Model (COM).

    This class is the production adapter. It is deliberately kept thin --
    all business logic lives in the domain layer. Each public method:

    1. Validates preconditions (e.g. connected).
    2. Translates domain objects to STK Connect commands or COM calls.
    3. Logs the action via ``log_action`` for provenance.
    4. Translates COM results to domain objects.

    COM imports are deferred to ``connect()`` / ``new_scenario()`` so that
    the module can be *imported* on non-Windows machines (CI) without errors.

    Attributes:
        _app: The ``STK.Application`` COM object, or ``None`` if not connected.
        _root: The ``IAgStkObjectRoot`` interface, or ``None`` if not connected.
    """

    def __init__(self) -> None:
        self._app: Any = None
        self._root: Any = None

    # -------------------------------------------------------------------------
    # IStkSession interface
    # -------------------------------------------------------------------------

    def connect(self, scenario_path: str) -> None:
        """Attach to a running STK instance and optionally load an existing scenario.

        Args:
            scenario_path: Absolute path to a ``.sc`` scenario file.
                Pass an empty string to attach to an already-open scenario.

        Raises:
            StkConnectionError: If STK is not running or the scenario fails to load.
        """
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client  # type: ignore[import]

            pythoncom.CoInitialize()
            self._app = win32com.client.Dispatch("STK13.Application")
            self._app.Visible = True
            self._root = self._app.Personality2
            if scenario_path:
                self._root.LoadScenario(scenario_path)
            logger.info("Connected to STK", extra={"scenario_path": scenario_path})
        except Exception as exc:
            raise StkConnectionError(f"Failed to connect to STK: {exc}") from exc

    def setup_scenario_folders(self, folders: list[str]) -> None:
        """Create the standard scenario folder structure in STK.

        Safe to call on an existing scenario -- folders that already exist are
        silently skipped.  Called automatically by :meth:`new_scenario` but
        can also be called after :meth:`connect` to ensure folders are present
        in a pre-existing scenario.

        Args:
            folders: List of folder paths as defined in
                ``sipc.config.constants.STK_FOLDERS``
                (e.g. ``["/Blue", "/Red", ...]``).
        """
        self._require_connection()
        for path in folders:
            self._ensure_folder(path.lstrip("/"))

    def new_scenario(self, name: str) -> None:
        """Create a new blank STK scenario, closing any currently-open one.

        After creating the scenario, the standard folder structure is set up
        automatically via :meth:`setup_scenario_folders`.

        Args:
            name: The scenario name (no path required; STK manages the file
                location until the operator saves it).

        Raises:
            StkConnectionError: If STK is not running or the scenario cannot
                be created.
        """
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client  # type: ignore[import]

            pythoncom.CoInitialize()
            self._app = win32com.client.Dispatch("STK13.Application")
            self._app.Visible = True
            self._root = self._app.Personality2

            # Close any currently-open scenario before creating a new one.
            # STK only supports one scenario at a time.
            try:
                self._root.CloseScenario()
                logger.info("Closed existing scenario before creating new one")
            except Exception:
                pass  # No scenario open — safe to proceed

            self._root.NewScenario(name)
            logger.info("New scenario created", extra={"name": name})
        except Exception as exc:
            raise StkConnectionError(f"Failed to create new STK scenario: {exc}") from exc

        from sipc.config.constants import STK_FOLDERS  # noqa: PLC0415

        self.setup_scenario_folders(STK_FOLDERS)

    def disconnect(self) -> None:
        """Release COM references."""
        self._root = None
        self._app = None
        logger.info("Disconnected from STK")

    def create_satellite(self, name: str, group: str) -> str:
        """Create a satellite object in the STK scenario inside the correct folder.

        Steps:

        1. Ensure the target folder exists (creates it if absent).
        2. Create the satellite object at scenario root.
        3. Move it into the folder via the ``SetGroup`` Connect command.

        The folder assignment in step 3 is best-effort: if ``SetGroup`` is
        not available (older STK build or different syntax), a warning is logged
        but the satellite still exists with the correct name and TLE at scenario
        root so the planning run is not blocked.

        Args:
            name: STK object name (e.g. ``B_SAT_Alpha``).
            group: Scenario folder path (e.g. ``/Blue``).

        Returns:
            The STK object path of the new satellite (``Satellite/<name>``).

        Raises:
            StkConnectionError: If not connected.
            StkCommandError: If satellite creation fails.
        """
        self._require_connection()
        folder_name = group.lstrip("/")
        self._ensure_folder(folder_name)

        # If the satellite already exists (e.g. from a previous run), skip creation.
        try:
            self._root.GetObjectFromPath(f"Satellite/{name}")
            logger.info("Satellite %r already exists in scenario; skipping New command", name)
        except Exception:
            try:
                result = self._root.ExecuteCommand(f"New / Satellite {name}")
                _check(result, f"create_satellite({name!r})")
            except StkCommandError:
                raise
            except Exception as exc:
                raise StkCommandError(
                    f"create_satellite({name!r}): STK raised COM exception — {exc}"
                ) from exc

        # Move into the folder. STK Connect command: SetGroup */Satellite/<name> Group <folder>
        move_result = self._root.ExecuteCommand(
            f"SetGroup */Satellite/{name} Group {folder_name}"
        )
        if move_result.IsSucceeded == 0:
            logger.warning(
                "Could not assign satellite %r to folder %r: %s",
                name,
                folder_name,
                move_result.Message,
            )

        stk_path = f"Satellite/{name}"
        logger.info(
            "create_satellite",
            extra={"name": name, "folder": folder_name, "path": stk_path},
        )
        return stk_path

    def set_propagator(self, sat_name: str, tle: str) -> None:
        """Load a TLE into an existing satellite and propagate.

        Uses the STK Connect command::

            SetState */Satellite/<name> TLE "<name>" "<line1>" "<line2>"

        followed by ``Propagate */Satellite/<name>`` to run the SGP4
        propagator across the scenario time window.

        Args:
            sat_name: STK object name of the satellite.
            tle: Two-line element set as a two-line string (lines 1 & 2,
                newline-separated).

        Raises:
            StkConnectionError: If not connected.
            StkCommandError: If the TLE or propagation command fails.
        """
        self._require_connection()
        lines = [ln.strip() for ln in tle.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            raise StkCommandError(
                f"Invalid TLE for {sat_name!r}: expected 2 lines, got {len(lines)}"
            )
        line1, line2 = lines[0], lines[1]

        set_cmd = (
            f'SetState */Satellite/{sat_name} TLE '
            f'"{sat_name}" "{line1}" "{line2}"'
        )
        _check(self._root.ExecuteCommand(set_cmd), f"set_propagator TLE({sat_name!r})")
        _check(
            self._root.ExecuteCommand(f"Propagate */Satellite/{sat_name}"),
            f"set_propagator Propagate({sat_name!r})",
        )
        logger.info("set_propagator", extra={"sat_name": sat_name})

    def compute_access(self, obj_a: str, obj_b: str) -> list[AccessInterval]:
        """Compute access intervals between two satellite objects.

        Fetches each object by name from the scenario root (``Satellite/<name>``),
        computes access, and converts the STK time strings to UTC-aware datetimes.

        Args:
            obj_a: STK object name of the first satellite (e.g. ``B_SAT_Alpha``).
            obj_b: STK object name of the second satellite (e.g. ``R_SAT_Track01``).

        Returns:
            List of :class:`~sipc.domain.models.AccessInterval` in chronological order.

        Raises:
            StkConnectionError: If not connected.
            StkObjectNotFoundError: If either satellite is not in the scenario.
            StkCommandError: If access computation fails.
        """
        self._require_connection()
        try:
            sat_obj = self._root.GetObjectFromPath(f"Satellite/{obj_a}")
        except Exception as exc:
            raise StkObjectNotFoundError(
                f"Satellite not found in scenario: {obj_a!r}"
            ) from exc

        try:
            access = sat_obj.GetAccessTo(f"*/Satellite/{obj_b}")
            access.ComputeAccess()
            time_periods = access.AccessTimePeriods
        except Exception as exc:
            raise StkCommandError(
                f"Access computation failed ({obj_a} -> {obj_b}): {exc}"
            ) from exc

        intervals: list[AccessInterval] = []
        for i in range(time_periods.Count):
            period = time_periods.Item(i)
            min_range = self._query_min_range_km(
                access, period.StartTime, period.StopTime
            )
            intervals.append(
                AccessInterval(
                    start=_parse_stk_time(period.StartTime),
                    end=_parse_stk_time(period.StopTime),
                    min_range_km=min_range,
                )
            )

        logger.info(
            "compute_access",
            extra={"obj_a": obj_a, "obj_b": obj_b, "interval_count": len(intervals)},
        )
        return intervals

    def set_scenario_time(self, start: datetime, stop: datetime) -> None:
        """Set the scenario analysis time window and rewind to the start epoch.

        Args:
            start: UTC-aware scenario start epoch.
            stop: UTC-aware scenario stop epoch.

        Raises:
            StkConnectionError: If not connected.
        """
        self._require_connection()
        scenario = self._root.CurrentScenario
        scenario.SetTimePeriod(_to_stk_time(start), _to_stk_time(stop))
        self._root.Rewind()
        logger.info(
            "set_scenario_time",
            extra={"start": start.isoformat(), "stop": stop.isoformat()},
        )

    def get_scenario_epoch(self) -> datetime:
        """Return the scenario start epoch as a UTC-aware datetime.

        Raises:
            StkConnectionError: If not connected.
        """
        self._require_connection()
        start_str: str = self._root.CurrentScenario.StartTime
        epoch = _parse_stk_time(start_str)
        logger.info("get_scenario_epoch", extra={"epoch": epoch.isoformat()})
        return epoch

    def log_action(self, run_id: str, action: str, payload: dict[str, Any]) -> None:
        """Log a provenance-tagged STK adapter action.

        Args:
            run_id: Planning run identifier.
            action: Short action description.
            payload: Arbitrary key/value action parameters.
        """
        logger.info(
            "stk_action",
            extra={"run_id": run_id, "action": action, "payload": payload},
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _query_min_range_km(
        self, access: Any, start_time: str, stop_time: str, step_s: float = 30.0
    ) -> float:
        """Return the minimum range (km) between two objects over an access interval.

        Queries the STK ``Range`` data provider on the already-computed access
        object using a fixed time step.  On any failure the method returns
        ``0.0`` and logs a warning so that a data-provider error never aborts
        a planning run.

        Args:
            access: The STK access COM object (``IAgSatelliteAccess``).
            start_time: STK-format start time string for the interval.
            stop_time: STK-format stop time string for the interval.
            step_s: Sampling step in seconds (default 30 s).

        Returns:
            Minimum range in km, or ``0.0`` if unavailable.
        """
        try:
            dp = access.DataProviders.GetDataPrvIntervalFromPath("Range")
            result = dp.Exec(start_time, stop_time, step_s)
            values = list(result.DataSets.GetDataSetByName("Range").GetValues())
            return float(min(values)) if values else 0.0
        except Exception as exc:
            logger.warning(
                "Range data provider query failed; min_range_km will be 0: %s", exc
            )
            return 0.0

    def _ensure_folder(self, folder_name: str) -> None:
        """Create a scenario-level folder if it does not already exist.

        STK returns an error when a folder already exists; that specific error
        is silently ignored.  Any other failure is logged as a warning.

        Args:
            folder_name: Folder name without leading slash (e.g. ``Blue``).
        """
        try:
            result = self._root.ExecuteCommand(f"New / Folder {folder_name}")
            if result.IsSucceeded == 0:
                msg = result.Message.lower()
                if "already" not in msg and "exist" not in msg:
                    logger.warning(
                        "Could not create STK folder %r: %s", folder_name, result.Message
                    )
        except Exception as exc:
            # Some STK builds throw instead of returning IsSucceeded==0 for
            # "already exists" — treat all COM exceptions here as non-fatal.
            logger.warning("STK folder %r COM exception (likely already exists): %s", folder_name, exc)

    def _require_connection(self) -> None:
        """Raise :class:`StkConnectionError` if not connected to STK."""
        if self._root is None:
            raise StkConnectionError(
                "Not connected to STK. Call connect() or new_scenario() first."
            )
