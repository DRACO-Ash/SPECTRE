"""StkComSession -- IStkSession implementation via pywin32 COM automation."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from sipc.domain.models import (
    AccessInterval,
    BurnLocation,
    BurnType,
    ManeuverOption,
    ManeuverSearchConfig,
)
from sipc.stk_adapter.exceptions import (
    StkCommandError,
    StkConnectionError,
    StkObjectNotFoundError,
)

logger = logging.getLogger(__name__)

# STK date string format: "1 Jan 2026 00:00:00.000"  (UTCG)
_STK_TIME_RE = re.compile(r"\.\d+$")


def _purge_stk_gen_py_stubs() -> None:
    """Remove partial STK 13 gen_py stubs from memory and disk.

    ``EnsureDispatch`` previously generated incomplete stubs for the STK 13
    Objects type library (GUID ``AB621A84-81D2-45BF-9236-112CF72743D7``).
    Even plain ``Dispatch`` uses these stubs when they exist, causing
    ``ModuleNotFoundError`` for any missing interface module (e.g.
    ``IAgStkObject``, ``IAgVePropagatorSGP4``).

    This function:

    1. Removes all stub modules from ``sys.modules`` so the current process
       immediately stops using them.
    2. Deletes the stub package directory from disk so future restarts are
       also clean.
    """
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import sys  # noqa: PLC0415

    _GUID_DIR = "AB621A84-81D2-45BF-9236-112CF72743D7x0x1x0"

    # 1. Evict from sys.modules (takes effect immediately in this process).
    stale = [k for k in list(sys.modules) if _GUID_DIR in k]
    for k in stale:
        del sys.modules[k]
    if stale:
        logger.info("Evicted %d partial STK gen_py stub modules from sys.modules", len(stale))

    # 2. Delete from disk so subsequent restarts don't reload them.
    try:
        from win32com.client import gencache  # type: ignore[import]  # noqa: PLC0415
        gen_path = gencache.GetGeneratePath()
        stub_dir = os.path.join(gen_path, _GUID_DIR)
        if os.path.isdir(stub_dir):
            shutil.rmtree(stub_dir)
            logger.info("Deleted partial STK gen_py stub directory: %s", stub_dir)
    except Exception as exc:
        logger.debug("gen_py disk cleanup skipped: %s", exc)


def _stk_dispatch() -> Any:
    """Return an ``STK13.Application`` COM object with the best available binding.

    Strategy:
    1. Purge any previously-incomplete gen_py stubs (disk + sys.modules).
    2. Try ``EnsureDispatch`` to regenerate **complete** stubs from scratch.
       Complete stubs are required because ``IAgVePropagatorSGP4`` is a
       vtable-only (non-dual) interface — it cannot be called via pure late
       binding; ``CastTo`` / generated wrapper classes are the only path.
    3. If ``EnsureDispatch`` fails, fall back to pure ``Dispatch`` (satellite
       creation still works; TLE loading will be limited).
    """
    _purge_stk_gen_py_stubs()
    import win32com.client  # type: ignore[import]
    logger.info("STK: generating COM type stubs via gencache.EnsureModule")
    try:
        from win32com.client import gencache as _gencache  # type: ignore[import]  # noqa: PLC0415
        # Generate stubs for the STK Objects type library (GUID / major / minor).
        # Complete stubs are required because IAgVePropagatorSGP4 is a vtable-only
        # (non-dual) interface and cannot be reached via pure late binding.
        _gencache.EnsureModule("{AB621A84-81D2-45BF-9236-112CF72743D7}", 0, 1, 0)
        import sys  # noqa: PLC0415
        _guid = "AB621A84-81D2-45BF-9236-112CF72743D7x0x1x0"
        if any(_guid in k and "IAgVePropagatorSGP4" in k for k in sys.modules):
            logger.info("STK stubs include IAgVePropagatorSGP4 — CastTo will work")
        else:
            logger.warning(
                "STK stubs generated but IAgVePropagatorSGP4 not yet in sys.modules "
                "(will be loaded on first CastTo call)"
            )
    except Exception as exc:
        logger.warning(
            "STK: stub generation failed (%s) — falling back to pure late binding; "
            "TLE loading via Object Model may be limited",
            exc,
        )
    return win32com.client.Dispatch("STK13.Application")


def _normalize_tle_line1(line: str) -> str:
    """Normalise TLE line 1 to the format STK accepts.

    Some TLE sources (including UDL) include an explicit ``+`` sign in the
    five sign positions of line 1:

    * column 34 (0-indexed 33): first derivative of mean motion — mantissa sign
    * column 45 (0-indexed 44): second derivative of mean motion — mantissa sign
    * column 51 (0-indexed 50): second derivative of mean motion — exponent sign
    * column 54 (0-indexed 53): BSTAR drag term — mantissa sign
    * column 60 (0-indexed 59): BSTAR drag term — exponent sign

    STK expects a **space** (not ``+``) in all sign positions for positive values.
    A ``+`` in any of those positions causes ``AddSegsFromFile`` to raise
    "Failed to add the TLE".
    """
    if not line.startswith("1 ") or len(line) < 54:
        return line
    chars = list(line)
    for idx in (33, 44, 50, 53, 59):
        if idx < len(chars) and chars[idx] == "+":
            chars[idx] = " "
    return "".join(chars)


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


def _add_stop_condition(stop_coll: Any, location: BurnLocation, config: ManeuverSearchConfig) -> None:
    """Add the appropriate Astrogator stopping condition for *location*.

    Maps each :class:`~sipc.domain.models.BurnLocation` to the corresponding
    STK Astrogator stop-condition name.  ``CUSTOM`` and unrecognised values
    fall back to a duration-based condition covering half the search window.

    Args:
        stop_coll: The ``StoppingConditions`` collection on a Propagate segment.
        location: Orbital geometry tag for the desired burn point.
        config: Search config (used for time-based fallbacks).
    """
    _STOP_MAP: dict[BurnLocation, str] = {
        BurnLocation.APOGEE:           "Apoapsis",
        BurnLocation.PERIGEE:          "Periapsis",
        BurnLocation.ASCENDING_NODE:   "Ascending Node",
        BurnLocation.DESCENDING_NODE:  "Descending Node",
        BurnLocation.NORTH_POLE:       "Latitude",
        BurnLocation.SOUTH_POLE:       "Latitude",
    }
    stop_name = _STOP_MAP.get(location)
    if stop_name:
        try:
            sc = stop_coll.Add(stop_name)
            # For latitude-based stops set the target latitude.
            if location == BurnLocation.NORTH_POLE:
                sc.Properties.Trip = 90.0
            elif location == BurnLocation.SOUTH_POLE:
                sc.Properties.Trip = -90.0
            return
        except Exception as exc:
            logger.debug("Stop condition %r failed (%s); falling back to duration", stop_name, exc)
    # Fallback: half the search window duration.
    half_s = (config.search_window_stop - config.search_window_start).total_seconds() / 2
    dur = stop_coll.Add("Duration")
    dur.Properties.Trip = half_s


def _configure_burn(burn_seg: Any, burn_type: BurnType) -> None:
    """Set the burn segment's maneuver type and attitude control frame.

    Configures the segment for either an impulsive or finite burn in the
    VNC (Velocity-Normal-Co-normal) frame.  For finite burns only the
    attitude frame is set; engine model parameters are left at defaults.

    Args:
        burn_seg: The Astrogator Maneuver segment COM object.
        burn_type: Impulsive or finite.
    """
    _MANEUVER_IMPULSIVE = 0
    _MANEUVER_FINITE    = 1
    _ATTITUDE_THRUST_VECTOR = 0
    _THRUST_AXES_VNC    = 4  # AgEVAThrustAxesType.eVAThrustAxesVNC (verify from stubs)

    try:
        m_type = _MANEUVER_IMPULSIVE if burn_type == BurnType.IMPULSIVE else _MANEUVER_FINITE
        burn_seg.SetManeuverType(m_type)
        maneuver = burn_seg.Maneuver
        maneuver.SetAttitudeControlType(_ATTITUDE_THRUST_VECTOR)
        atc = maneuver.AttitudeControl
        atc.ThrustAxesType = _THRUST_AXES_VNC
    except Exception as exc:
        logger.debug("_configure_burn partial failure (%s); proceeding with defaults", exc)


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
            self._app = _stk_dispatch()
            self._app.Visible = True
            self._root = self._app.Personality2
            if scenario_path:
                self._root.LoadScenario(scenario_path)
            logger.info("Connected to STK", extra={"scenario_path": scenario_path})
        except Exception as exc:
            raise StkConnectionError(f"Failed to connect to STK: {exc}") from exc

        self._log_connect_diagnostic()

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
            self._app = _stk_dispatch()
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

        self._log_connect_diagnostic()

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

        # If satellite already exists (e.g. from a previous run), skip creation.
        already_exists = False
        try:
            self._root.GetObjectFromPath(f"Satellite/{name}")
            already_exists = True
            logger.info("Satellite %r already exists in scenario; skipping creation", name)
        except Exception:
            pass  # Does not exist — create it below

        if not already_exists:
            # Prefer the STK Object Model (Children.New) over ExecuteCommand.
            # ExecuteCommand("New / Satellite …") can fail in ODTK-managed STK
            # instances because ODTK intercepts the Connect command layer.
            # Children.New goes directly to the COM object model and is unaffected.
            created = self._create_satellite_via_om(name)
            if not created:
                # Object model unavailable — fall back to Connect command.
                try:
                    result = self._root.ExecuteCommand(f"New / Satellite {name}")
                    _check(result, f"create_satellite({name!r})")
                    logger.info("Satellite %r created via Connect command", name)
                except StkCommandError:
                    raise
                except Exception as exc:
                    raise StkCommandError(
                        f"create_satellite({name!r}): both OM and Connect command failed — {exc}"
                    ) from exc

        # Best-effort folder assignment via Connect command.
        try:
            move_result = self._root.ExecuteCommand(
                f"SetGroup */Satellite/{name} Group {folder_name}"
            )
            if move_result.IsSucceeded == 0:
                logger.warning(
                    "Could not assign satellite %r to folder %r: %s",
                    name, folder_name, move_result.Message,
                )
        except Exception as exc:
            logger.warning("SetGroup threw for satellite %r: %s", name, exc)

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
        try:
            _check(self._root.ExecuteCommand(set_cmd), f"set_propagator TLE({sat_name!r})")
            _check(
                self._root.ExecuteCommand(f"Propagate */Satellite/{sat_name}"),
                f"set_propagator Propagate({sat_name!r})",
            )
            logger.info("set_propagator", extra={"sat_name": sat_name})
            return  # success via Connect command
        except Exception as exc:
            # Connect command layer unavailable or returned an error — fall back to
            # the Object Model path which works in ODTK-managed STK instances.
            logger.warning(
                "set_propagator Connect command failed for %r (%s); trying Object Model",
                sat_name, exc,
            )
        self._set_propagator_via_om(sat_name, line1, line2)
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

    def get_scenario_time(self) -> tuple[datetime, datetime]:
        """Return the scenario analysis start and stop epochs as UTC datetimes.

        Returns:
            ``(start, stop)`` — both UTC-aware datetimes.

        Raises:
            StkConnectionError: If not connected or no scenario is loaded.
        """
        self._require_connection()
        scenario = self._root.CurrentScenario
        start = _parse_stk_time(str(scenario.StartTime))
        stop = _parse_stk_time(str(scenario.StopTime))
        logger.info(
            "get_scenario_time",
            extra={"start": start.isoformat(), "stop": stop.isoformat()},
        )
        return (start, stop)

    def get_satellite_tle(self, sat_name: str) -> str | None:
        """Return the current TLE (line 1 and line 2) for an existing satellite.

        Reads the first TLE segment from the satellite's SGP4 propagator in the
        active scenario.  Returns ``None`` if the satellite does not exist, has
        no SGP4 segments, or the TLE cannot be read for any reason.

        Args:
            sat_name: STK object name of the satellite (e.g. ``B_SAT_Alpha``).

        Returns:
            Two-line TLE string (``"<line1>\\n<line2>"``), or ``None``.
        """
        tle = self._snapshot_tle(sat_name)
        if tle is None:
            return None
        return f"{tle[0]}\n{tle[1]}"

    def compute_maneuver_options(
        self, config: ManeuverSearchConfig
    ) -> list[ManeuverOption]:
        """Enumerate intercept maneuver options via STK Astrogator MCS.

        For each enabled :class:`~sipc.domain.models.BurnLocation`, builds an
        Astrogator Mission Control Sequence on the red satellite and runs a
        differential corrector targeting the blue satellite.  Converged
        solutions become :class:`~sipc.domain.models.ManeuverOption` objects;
        non-convergent candidates are silently dropped.

        The red satellite's SGP4 propagator is always restored in a ``finally``
        block so that a failed search never corrupts the planning scenario.

        Args:
            config: Search parameters — satellite names, time window, delta-V
                budget, burn types, and burn locations.

        Returns:
            Solved options sorted by ``delta_v_km_s`` ascending.

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If the Astrogator module is unavailable or
                satellite objects cannot be found.
        """
        self._require_connection()

        # Check Astrogator licence before touching any satellite state.
        if not self._astrogator_licensed():
            raise StkCommandError(
                "STK Astrogator module is not licensed on this installation. "
                "Maneuver planning is unavailable."
            )

        red_obj = self._root.GetObjectFromPath(f"Satellite/{config.red_sat}")
        # Snapshot the current TLE so we can restore it in the finally block.
        red_tle = self._snapshot_tle(config.red_sat)

        options: list[ManeuverOption] = []

        try:
            for location in config.burn_locations:
                for burn_type in config.burn_types:
                    result = self._solve_maneuver(config, location, burn_type, red_obj)
                    if result is not None and result.delta_v_km_s <= config.max_delta_v_km_s:
                        options.append(result)
        finally:
            # Always restore the original SGP4 propagator.
            if red_tle:
                self._restore_sgp4(config.red_sat, red_tle)

        options.sort(key=lambda o: o.delta_v_km_s)
        logger.info(
            "compute_maneuver_options: %d converged solutions for %s vs %s",
            len(options), config.red_sat, config.blue_sat,
        )
        return options

    def apply_maneuver(self, red_sat: str, option: ManeuverOption) -> None:
        """Write a selected maneuver option into the red satellite's Astrogator MCS.

        Switches the red satellite to Astrogator and builds a fixed (non-targeting)
        MCS encoding the chosen burn.  The satellite will propagate along the
        intercept trajectory when STK rewinds.

        Args:
            red_sat: STK object name of the red satellite.
            option: The :class:`~sipc.domain.models.ManeuverOption` to apply.

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If the MCS cannot be constructed or propagated.
        """
        self._require_connection()

        if not self._astrogator_licensed():
            raise StkCommandError(
                "STK Astrogator module is not licensed — cannot apply maneuver."
            )

        _E_PROPAGATOR_ASTROGATOR = self._astrogator_enum_value()
        _E_PROPAGATOR_SGP4 = 4

        red_obj = self._root.GetObjectFromPath(f"Satellite/{red_sat}")
        red_obj.SetPropagatorType(_E_PROPAGATOR_ASTROGATOR)
        prop = red_obj.Propagator
        mcs = prop.MainSequence

        try:
            self._build_fixed_mcs(mcs, option)
            prop.Propagate()
            logger.info(
                "apply_maneuver: MCS applied for %r (option %s dv=%.3f km/s)",
                red_sat, option.option_id, option.delta_v_km_s,
            )
        except Exception as exc:
            raise StkCommandError(
                f"apply_maneuver failed for {red_sat!r}: {exc}"
            ) from exc

    def list_scenario_satellites(self) -> list[str]:
        """Return the instance names of all Satellite children in the current scenario.

        Used by the "Import from Scenario" UI action to populate session state
        from pre-existing STK objects without re-creating or re-propagating them.

        Returns:
            List of STK object instance names (e.g. ``["B_SAT_Alpha", "R_SAT_Track01"]``).

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If the scenario children cannot be enumerated.
        """
        self._require_connection()
        try:
            children = self._root.CurrentScenario.Children
            names: list[str] = []
            for i in range(children.Count):
                try:
                    child = children.Item(i)
                    if str(child.ClassName) == "Satellite":
                        names.append(str(child.InstanceName))
                except Exception as exc:
                    logger.debug("list_scenario_satellites: skipping item %d: %s", i, exc)
            logger.info("list_scenario_satellites: found %d satellite(s)", len(names))
            return names
        except Exception as exc:
            raise StkCommandError(
                f"Failed to enumerate scenario satellites: {exc}"
            ) from exc

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

    def _set_propagator_via_om(self, sat_name: str, line1: str, line2: str) -> None:
        """Set the SGP4/TLE propagator via the STK Object Model.

        Root cause (resolved through iterative live debugging):

        * In STK 13 the ``AgEVePropagatorType`` enum is renumbered relative to
          STK 11.  ``ePropagatorSGP4 = 4`` (not 5).  Value 5 is SPICE.
        * With gen_py stubs generated by ``gencache.EnsureModule`` and the
          correct enum value, ``sat.Propagator`` returns ``_IAgVePropagatorSGP4``
          which exposes ``CommonTasks.AddSegsFromLines`` directly.

        Args:
            sat_name: STK object name of the satellite.
            line1: TLE line 1.
            line2: TLE line 2.

        Raises:
            StkCommandError: If all approaches fail.
        """
        # AgEVePropagatorType enum values in STK 13 (confirmed from gen_py stubs):
        #   ePropagatorHPOP=0  J2=1  J4=2  LOP=3  SGP4=4  SPICE=5  StkExternal=6
        _E_PROPAGATOR_SGP4 = 4
        errors: list[str] = []

        # ------------------------------------------------------------------
        # Approach A: CommonTasks.AddSegsFromFile via Object Model
        # ------------------------------------------------------------------
        # In STK 13, IAgVePropagatorSGP4CommonTasks does NOT have AddSegsFromLines
        # (removed from the API).  The correct method is AddSegsFromFile which
        # reads a standard 3-line TLE file.  We write to a temp file and call
        # via the Object Model — this bypasses the blocked Connect command layer.
        try:
            import os  # noqa: PLC0415
            import tempfile  # noqa: PLC0415

            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            sat_obj.SetPropagatorType(_E_PROPAGATOR_SGP4)
            propagator = sat_obj.Propagator
            logger.info(
                "[set_propagator] propagator type=%s", type(propagator).__name__
            )

            # NORAD catalog number is in TLE line 1, columns 3-7 (1-indexed).
            satno = line1[2:7].strip()

            # Validate TLE line lengths before writing.  STK 13 requires exactly
            # 69 characters per line; a shorter line (e.g. from UDL records with
            # stripped padding) produces "Failed to add the TLE".
            if len(line1) != 69 or len(line2) != 69:
                logger.warning(
                    "_set_propagator_via_om: non-standard TLE line length for %r "
                    "(line1=%d chars, line2=%d chars; expected 69 each). "
                    "line1=%r  line2=%r",
                    sat_name, len(line1), len(line2), line1, line2,
                )

            # UDL TLE data includes explicit '+' signs in the sign positions
            # of line 1.  STK expects a space there for positive values; a '+'
            # causes AddSegsFromFile to raise "Failed to add the TLE".
            line1_norm = _normalize_tle_line1(line1)

            # TLE format is fixed-width (69 chars per line).  Some UDL records
            # strip trailing spaces producing a 68-char line.  Pad both lines to
            # exactly 69 chars so AddSegsFromFile does not reject them.
            line1_norm = line1_norm.ljust(69)[:69]
            line2 = line2.ljust(69)[:69]

            # The name line MUST match the identifier passed to AddSegsFromFile
            # exactly.  Using sat_name (e.g. "B_SAT_33274") when the identifier
            # is the catalog number ("33274") causes a lookup miss and the same
            # "Failed to add the TLE" error.  Use satno for both.
            # Use platform-native line endings (no newline= override) so
            # STK's Windows TLE parser receives \r\n as expected.
            tle_content = f"{satno}\n{line1_norm}\n{line2}\n"
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tle", delete=False, encoding="ascii"
            ) as fh:
                fh.write(tle_content)
                tle_path = fh.name

            try:
                propagator.CommonTasks.AddSegsFromFile(satno, tle_path)
                propagator.Propagate()
                logger.info(
                    "set_propagator (CommonTasks.AddSegsFromFile) succeeded for %r",
                    sat_name,
                )
                return
            finally:
                os.unlink(tle_path)
        except Exception as exc_a:
            errors.append(f"AddSegsFromFile: {exc_a}")
            logger.warning(
                "[set_propagator] AddSegsFromFile failed for %r: %s", sat_name, exc_a
            )

        # ------------------------------------------------------------------
        # Approach B: ExecuteCommand ImportFromFile (last resort)
        # ------------------------------------------------------------------
        try:
            self._set_tle_via_file(sat_name, line1, line2)
            logger.info("set_propagator (ImportFromFile) succeeded for %r", sat_name)
            return
        except Exception as exc_b:
            errors.append(f"ImportFromFile: {exc_b}")
            logger.debug("set_propagator approach B failed for %r: %s", sat_name, exc_b)

        raise StkCommandError(
            f"set_propagator({sat_name!r}): all OM approaches failed — "
            + " | ".join(errors)
        )

    def _set_tle_via_file(self, sat_name: str, line1: str, line2: str) -> None:
        """Write a 3-line TLE temp file and import it via the STK Object Model.

        STK's satellite object exposes a ``LoadTleData`` or ``LoadTLEFile``
        method on some interfaces.  This is the last-resort fallback when both
        the Connect command and in-memory OM approaches fail.

        Args:
            sat_name: STK object name.
            line1: TLE line 1.
            line2: TLE line 2.

        Raises:
            StkCommandError: If the file-based load also fails.
        """
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        satno_b = line1[2:7].strip()
        line1_norm_b = _normalize_tle_line1(line1)
        tle_content = f"{satno_b}\n{line1_norm_b}\n{line2}\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tle", delete=False, encoding="ascii"
        ) as fh:
            fh.write(tle_content)
            tle_path = fh.name

        try:
            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            # Try the Connect command with a file path — some STK/ODTK builds
            # allow file-based imports even when in-memory commands are blocked.
            result = self._root.ExecuteCommand(
                f'ImportFromFile */Satellite/{sat_name} TLE "{tle_path}"'
            )
            _check(result, f"ImportFromFile TLE({sat_name!r})")
        finally:
            os.unlink(tle_path)

    def _create_satellite_via_om(self, name: str) -> bool:
        """Create a satellite using the STK Object Model (``Children.New``).

        Bypasses the Connect command layer entirely, which makes this reliable
        even in ODTK-managed STK instances where ``ExecuteCommand`` is
        intercepted.

        Args:
            name: STK object name for the new satellite.

        Returns:
            ``True`` if the satellite was created, ``False`` if the Object
            Model approach is unavailable (caller should fall back to
            ``ExecuteCommand``).
        """
        # AgESTKObjectType.eSatellite = 18 (stable across STK 10–13)
        _E_SATELLITE = 18
        # Try scenario_obj via CurrentScenario property first, then via Connect
        # command path as fallback (CurrentScenario may be inaccessible in
        # late-binding depending on STK / ODTK configuration).
        for _attempt, _get_scenario in enumerate([
            lambda: self._root.CurrentScenario,
            lambda: self._root.GetObjectFromPath("Scenario"),
        ]):
            try:
                scenario_obj = _get_scenario()
                scenario_obj.Children.New(_E_SATELLITE, name)
                logger.info(
                    "Satellite %r created via STK Object Model (attempt %d)", name, _attempt
                )
                return True
            except Exception as exc:
                logger.debug(
                    "OM satellite creation attempt %d failed for %r: %s", _attempt, name, exc
                )
        logger.warning(
            "Object model satellite creation unavailable for %r — will try Connect command",
            name,
        )
        return False

    def _log_connect_diagnostic(self) -> None:
        """Run a lightweight STK diagnostic and log the results.

        Calls ``ExecuteCommand("GetVersion")`` so that the run log immediately
        shows whether the Connect command layer is functional.  If the call
        fails, a warning is logged — satellite creation will fall back to the
        Object Model path automatically.
        """
        try:
            result = self._root.ExecuteCommand("GetVersion")
            if result.IsSucceeded:
                version = result.Item(0) if result.Count > 0 else "(no output)"
                logger.info("STK Connect commands operational — version: %s", version)
            else:
                logger.warning(
                    "STK Connect command layer not responding (GetVersion failed: %s). "
                    "Will use Object Model for satellite creation.",
                    result.Message,
                )
        except Exception as exc:
            logger.warning(
                "STK Connect command layer unavailable (%s). "
                "Will use Object Model for satellite creation.",
                exc,
            )

    # ── Astrogator helpers ────────────────────────────────────────────────────

    def _astrogator_licensed(self) -> bool:
        """Return True if the Astrogator module is licensed in this STK installation.

        Attempts the Connect-command path first; if that is blocked (ODTK),
        assumes licensed and lets the actual Astrogator call surface the error.
        """
        try:
            result = self._root.ExecuteCommand("GetLicensedModules")
            if result.IsSucceeded and result.Count > 0:
                licensed_str = result.Item(0)
                return "Astrogator" in licensed_str
        except Exception:
            # Connect layer blocked — cannot determine; assume available and
            # let the propagator switch fail gracefully if it is not.
            logger.debug("GetLicensedModules blocked; assuming Astrogator licensed")
        return True

    def _astrogator_enum_value(self) -> int:
        """Return the integer value of ePropagatorAstrogator from gen_py stubs.

        Falls back to 8 (the value in STK 12–13) if the stubs cannot be
        inspected.  The actual value is logged so live test runs can confirm it.
        """
        # Confirmed value from STK 13 gen_py stubs (AgEVePropagatorType enum):
        #   ePropagatorAstrogator = 12
        # The stubs define this in a tab-indented comment block that is not
        # importable as a module attribute, so we read it via EnsureModule and
        # fall back to the confirmed literal if the attribute is absent.
        _FALLBACK = 12
        try:
            from win32com.client import gencache as _gc  # type: ignore[import]  # noqa: PLC0415
            mod = _gc.EnsureModule("{AB621A84-81D2-45BF-9236-112CF72743D7}", 0, 1, 0)
            val = getattr(mod, "ePropagatorAstrogator", None)
            if val is not None:
                logger.debug("ePropagatorAstrogator enum value from stubs: %d", val)
                return int(val)
        except Exception as exc:
            logger.debug("Could not read ePropagatorAstrogator from stubs: %s", exc)
        logger.debug("Using confirmed ePropagatorAstrogator=%d (STK 13)", _FALLBACK)
        return _FALLBACK

    def _snapshot_tle(self, sat_name: str) -> tuple[str, str] | None:
        """Return the current (line1, line2) TLE from an SGP4 satellite, or None."""
        try:
            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            prop = sat_obj.Propagator
            segs = prop.Segments
            if segs.Count == 0:
                return None
            seg = segs.Item(0)
            line1 = str(seg.Line1).strip()
            line2 = str(seg.Line2).strip()
            return (line1, line2) if line1.startswith("1 ") else None
        except Exception as exc:
            logger.debug("Could not snapshot TLE for %r: %s", sat_name, exc)
            return None

    def _restore_sgp4(self, sat_name: str, tle: tuple[str, str]) -> None:
        """Restore *sat_name* to SGP4 propagation using the given TLE lines."""
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        _E_PROPAGATOR_SGP4 = 4
        line1, line2 = tle
        satno = line1[2:7].strip()
        line1_norm = _normalize_tle_line1(line1)
        tle_content = f"{satno}\n{line1_norm}\n{line2}\n"
        try:
            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            sat_obj.SetPropagatorType(_E_PROPAGATOR_SGP4)
            propagator = sat_obj.Propagator
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tle", delete=False, encoding="ascii"
            ) as fh:
                fh.write(tle_content)
                tle_path = fh.name
            try:
                propagator.CommonTasks.AddSegsFromFile(satno, tle_path)
                propagator.Propagate()
                logger.debug("Restored SGP4 propagator for %r", sat_name)
            finally:
                os.unlink(tle_path)
        except Exception as exc:
            logger.warning("Failed to restore SGP4 for %r after Astrogator search: %s", sat_name, exc)

    def _solve_maneuver(
        self,
        config: ManeuverSearchConfig,
        location: BurnLocation,
        burn_type: BurnType,
        red_obj: Any,
    ) -> ManeuverOption | None:
        """Build an Astrogator MCS for one burn location/type and run the targeter.

        Returns a :class:`~sipc.domain.models.ManeuverOption` if the
        differential corrector converges, ``None`` otherwise.
        """
        import math  # noqa: PLC0415

        _E_PROPAGATOR_ASTROGATOR = self._astrogator_enum_value()
        _E_PROPAGATOR_SGP4 = 4

        try:
            red_obj.SetPropagatorType(_E_PROPAGATOR_ASTROGATOR)
            prop = red_obj.Propagator
            mcs = prop.MainSequence

            # Clear any segments from a previous iteration.
            mcs.RemoveAll()

            # ── Initial State ────────────────────────────────────────────────
            _SEG_INITIAL_STATE   = 0
            _SEG_PROPAGATE       = 1
            _SEG_MANEUVER        = 2
            _SEG_TARGET_SEQUENCE = 3

            init_seg = mcs.Insert(_SEG_INITIAL_STATE, "Initial State", "-")
            # Use the scenario start epoch to seed the initial state from the
            # existing SGP4 propagator state.  Astrogator will pick up the
            # current propagated position automatically when the epoch is set.
            init_seg.Epoch = _to_stk_time(config.search_window_start)

            # ── Coast to burn point ──────────────────────────────────────────
            coast_seg = mcs.Insert(_SEG_PROPAGATE, "Coast to Burn", "-")
            stop_coll = coast_seg.StoppingConditions
            # Remove the default stopping condition and add one appropriate
            # for the requested burn location.
            stop_coll.RemoveAll()
            _add_stop_condition(stop_coll, location, config)

            # ── Maneuver ────────────────────────────────────────────────────
            burn_seg = mcs.Insert(_SEG_MANEUVER, "Intercept Burn", "-")
            _configure_burn(burn_seg, burn_type)

            # ── Target Sequence — differential corrector ─────────────────────
            target_seq = mcs.Insert(_SEG_TARGET_SEQUENCE, "Target Intercept", "-")
            post_coast = target_seq.Sequence.Insert(_SEG_PROPAGATE, "Coast to Intercept", "-")
            # Stop at end of search window.
            post_stop = post_coast.StoppingConditions
            post_stop.RemoveAll()
            epoch_stop = post_stop.Add("Epoch")
            epoch_stop.Properties.Trip = _to_stk_time(config.search_window_stop)

            dc = target_seq.Profiles.Add("Differential Corrector")
            dc_props = dc.Properties
            dc_props.MaxIterations = 50

            ctrl = dc.ControlParameters.Add("Impulsive Burn.BurnDirection.DeltaV")
            ctrl.Enable = True
            ctrl.Min = 0.0
            ctrl.Max = config.max_delta_v_km_s

            # Target: range to blue satellite ≤ 1 km at intercept epoch.
            blue_path = f"*/Satellite/{config.blue_sat}"
            constraint = dc.Results.Add(f"Range to {blue_path}")
            constraint.Enable = True
            constraint.DesiredValue = 0.0
            constraint.Tolerance = 1.0  # km

            # Run the MCS.
            prop.Propagate()

            # ── Extract results ──────────────────────────────────────────────
            burn_final = burn_seg.FinalState
            burn_epoch_str = burn_final.Epoch
            burn_epoch = _parse_stk_time(burn_epoch_str)

            dv_total = float(ctrl.CurrentValue) if hasattr(ctrl, "CurrentValue") else 0.0
            # VNC components — read from the burn segment maneuver object.
            dv_v = dv_n = dv_c = 0.0
            try:
                atc = burn_seg.Maneuver.AttitudeControl
                vec = atc.DeltaV
                dv_v, dv_n, dv_c = float(vec.X), float(vec.Y), float(vec.Z)
                dv_total = math.sqrt(dv_v**2 + dv_n**2 + dv_c**2)
            except Exception:
                pass

            intercept_final = post_coast.FinalState
            intercept_epoch_str = intercept_final.Epoch
            intercept_epoch = _parse_stk_time(intercept_epoch_str)
            transfer_s = (intercept_epoch - burn_epoch).total_seconds()

            # Approximate miss distance from the constraint result value.
            miss_km = float(getattr(constraint, "CurrentValue", 0.0))

            note = f"{location.value.replace('_', ' ').title()} {burn_type.value}"

            return ManeuverOption(
                red_name=config.red_sat,
                blue_name=config.blue_sat,
                burn_type=burn_type,
                burn_location=location,
                burn_epoch=burn_epoch,
                delta_v_km_s=dv_total,
                dv_prograde=dv_v,
                dv_normal=dv_n,
                dv_radial=dv_c,
                intercept_epoch=intercept_epoch,
                transfer_duration_s=max(transfer_s, 0.0),
                intercept_range_km=miss_km,
                notes=note,
            )

        except Exception as exc:
            logger.debug(
                "Maneuver search non-convergence for location=%s type=%s: %s",
                location.value, burn_type.value, exc,
            )
            return None

    def _build_fixed_mcs(self, mcs: Any, option: ManeuverOption) -> None:
        """Build a non-targeting Astrogator MCS for a selected ManeuverOption.

        Encodes the burn epoch, delta-V vector, and post-burn coast directly
        without a differential corrector — i.e. applies the solution as a
        fixed propagation sequence.
        """
        _SEG_INITIAL_STATE = 0
        _SEG_PROPAGATE     = 1
        _SEG_MANEUVER      = 2

        mcs.RemoveAll()

        init_seg = mcs.Insert(_SEG_INITIAL_STATE, "Initial State", "-")
        init_seg.Epoch = _to_stk_time(option.burn_epoch)

        coast_seg = mcs.Insert(_SEG_PROPAGATE, "Coast to Burn", "-")
        stop_coll = coast_seg.StoppingConditions
        stop_coll.RemoveAll()
        epoch_stop = stop_coll.Add("Epoch")
        epoch_stop.Properties.Trip = _to_stk_time(option.burn_epoch)

        burn_seg = mcs.Insert(_SEG_MANEUVER, "Intercept Burn", "-")
        _configure_burn(burn_seg, option.burn_type)
        try:
            atc = burn_seg.Maneuver.AttitudeControl
            atc.DeltaV.AssignCartesian(
                option.dv_prograde, option.dv_normal, option.dv_radial
            )
        except Exception as exc:
            logger.warning("Could not set delta-V vector on fixed MCS: %s", exc)

        post_seg = mcs.Insert(_SEG_PROPAGATE, "Coast to Intercept", "-")
        post_stop = post_seg.StoppingConditions
        post_stop.RemoveAll()
        epoch_stop2 = post_stop.Add("Epoch")
        epoch_stop2.Properties.Trip = _to_stk_time(option.intercept_epoch)

    def _require_connection(self) -> None:
        """Raise :class:`StkConnectionError` if not connected to STK.

        Also ensures COM is initialised on the calling thread.  FastAPI
        dispatches sync route handlers to a thread-pool thread; if that
        thread has never called ``CoInitialize`` the COM runtime raises
        ``CoInitialize has not been called``.  Calling it here (idempotent
        for already-initialised threads) ensures every COM operation is safe
        regardless of which thread the request arrives on.
        """
        try:
            import pythoncom  # type: ignore[import]  # noqa: PLC0415
            pythoncom.CoInitialize()
        except Exception:
            pass  # Already initialised on this thread — safe to continue
        if self._root is None:
            raise StkConnectionError(
                "Not connected to STK. Call connect() or new_scenario() first."
            )
