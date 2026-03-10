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
    InterceptConfig,
    InterceptMethod,
    ManeuverOption,
    ManeuverSearchConfig,
)
from sipc.intercept_engine.lambert_planner import LambertPlanner
from sipc.intercept_engine.optimal_intercept import OptimalInterceptPlanner
from sipc.intercept_engine.proximity_intercept import ProximityInterceptPlanner
from sipc.intercept_engine.rendezvous_planner import RendezvousPlanner
from sipc.stk_adapter.mcs_builder import MCSBuilder
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


def _compress_tle_line(line: str) -> str:
    """Compress a non-standard (>69-char) TLE line to exactly 69 characters.

    UDL TLEs sometimes carry extra spaces in the international designator
    padding area (line 1, 0-indexed cols 10-16) or after the satellite number
    (line 2, col 8), producing 70-72-char lines.  The naïve ``[:69]`` fix
    removes the **checksum digit** (always the last character), causing STK to
    reject the TLE.  This function instead removes excess space characters from
    the known padding area near the start of each line so the checksum is
    preserved.

    Args:
        line: A single TLE line (stripped, no newline).

    Returns:
        A line of exactly 69 characters (padded if short, compressed if long).
    """
    n = len(line)
    if n == 69:
        return line
    if n < 69:
        return line.ljust(69)

    excess = n - 69
    chars = list(line)
    removed = 0

    # Scan backward from just before the checksum (last char), removing
    # space characters.  UDL extra spaces appear around the element-set
    # number area (cols 64-69) for line 1 and the inclination separator
    # area for line 2 — both near the end of the content, never in the
    # fixed-format fields that start the line.  Working backward preserves
    # the checksum digit (always the last character) automatically.
    i = len(chars) - 2  # start one position before the checksum
    while removed < excess and i >= 7:  # never touch the fixed header cols 1-8
        if chars[i] == " ":
            del chars[i]
            removed += 1
        else:
            i -= 1

    result = "".join(chars)
    if len(result) != 69:
        # Safety fallback: keep first 68 chars + checksum (last char).
        result = (result[:68] + result[-1]) if len(result) > 69 else result.ljust(69)
    return result


def _tle_checksum(line: str) -> int:
    """Compute the TLE line checksum over the first 68 characters.

    Per the TLE spec: sum all digit characters, add 1 for each ``'-'``,
    ignore everything else, then take the result modulo 10.

    Args:
        line: A TLE line of at least 68 characters.

    Returns:
        Integer 0–9 that should appear as the last character of the line.
    """
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def _normalize_tle_line1(line: str) -> str:
    """Normalise TLE line 1 sign characters to the format STK accepts.

    Uses exact column positions from the TLE specification
    (https://en.wikipedia.org/wiki/Two-line_element_set).
    All indices are 0-based on a standard 69-character line 1.

    Sign positions and normalisation rules:

    * idx 33 (col 34) — first derivative of mean motion sign:
        ``+`` → ``' '``  (STK expects space for positive)
    * idx 44 (col 45) — second derivative mantissa sign:
        ``+`` → ``' '``  (STK expects space for positive)
    * idx 50 (col 51) — second derivative exponent sign:
        ``' '`` or ``'+'`` → ``'-'``  (STK requires an explicit sign; UDL
        omits it for zero-valued fields, leaving a space that STK rejects)
    * idx 53 (col 54) — BSTAR drag term mantissa sign:
        ``+`` → ``' '``
    * idx 59 (col 60) — BSTAR drag term exponent sign:
        ``' '`` or ``'+'`` → ``'-'``

    After all substitutions the checksum digit (idx 68) is recalculated
    because converting ``' '`` or ``'+'`` to ``'-'`` at exponent positions
    changes the checksum value (``'-'`` contributes 1; spaces and ``'+'``
    contribute 0).
    """
    if not line.startswith("1 ") or len(line) < 61:
        return line

    chars = list(line)

    # Mantissa signs: '+' → ' '
    for idx in (33, 44, 53):
        if idx < len(chars) and chars[idx] == "+":
            chars[idx] = " "

    # Exponent signs: ' ' or '+' → '-'
    for idx in (50, 59):
        if idx < len(chars) and chars[idx] in (" ", "+"):
            chars[idx] = "-"

    # Recalculate the checksum — sign substitutions above may have changed it.
    if len(chars) == 69:
        chars[68] = str(_tle_checksum("".join(chars)))

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


class _EngineLogger:
    """Thin adapter so Python standard-library loggers satisfy the intercept engine's
    ``.log(msg, tag)`` interface."""

    def __init__(self, py_logger: logging.Logger) -> None:
        self._log = py_logger

    def log(self, msg: str, tag: str = "") -> None:
        self._log.debug("[%s] %s", tag, msg)


def _build_intercept_plan(
    method: InterceptMethod,
    config: ManeuverSearchConfig,
    eng_log: _EngineLogger,
) -> list[dict]:
    """Dispatch to the appropriate intercept engine and return its sequence plan."""
    if method == InterceptMethod.LAMBERT:
        return LambertPlanner(eng_log).generate_plan(config.coast_hours, config.intercept_hours)
    if method == InterceptMethod.RENDEZVOUS:
        return RendezvousPlanner(eng_log).generate_plan(config.coast_hours)
    if method == InterceptMethod.PROXIMITY:
        return ProximityInterceptPlanner(eng_log).generate_plan(
            config.coast_hours, config.target_distance_m
        )
    if method == InterceptMethod.OPTIMAL:
        return OptimalInterceptPlanner(eng_log).generate_plan(
            config.coast_hours,
            config.intercept_hours,
            config.number_of_burns,
            config.target_distance_m,
            config.minimize_delta_v,
        )
    raise ValueError(f"Unknown InterceptMethod: {method!r}")


def _set_initial_state_epoch(init_seg: Any, stk_time: str) -> None:
    """Set the epoch on an Astrogator Initial State segment.

    STK 13 exposes ``Epoch`` as an ``IAgDate`` sub-object; assigning directly
    raises "Property 'Insert.Epoch' can not be set."  Setting the sub-property
    ``Epoch.Value`` is the correct path.  This helper tries both forms so the
    code works across STK versions without silent failure.
    """
    try:
        init_seg.Epoch.Value = stk_time
        return
    except Exception:
        pass
    try:
        init_seg.Epoch = stk_time
    except Exception as exc:
        logger.debug(
            "_set_initial_state_epoch: could not set epoch %r (%s); "
            "Astrogator will use the default scenario epoch",
            stk_time, exc,
        )


class _InterceptConfigProxy:
    """Minimal duck-type shim so ``_extract_engine_result`` can accept
    an :class:`~sipc.domain.models.InterceptConfig` in place of a
    :class:`~sipc.domain.models.ManeuverSearchConfig`."""

    def __init__(self, cfg: InterceptConfig) -> None:
        self.red_sat = cfg.red_sat
        self.blue_sat = cfg.blue_sat


def _build_intercept_plan_from_config(
    config: InterceptConfig,
    eng_log: _EngineLogger,
) -> list[dict]:
    """Dispatch to the appropriate intercept engine using an :class:`~sipc.domain.models.InterceptConfig`."""
    if config.method == InterceptMethod.LAMBERT:
        return LambertPlanner(eng_log).generate_plan(config.coast_hours, config.intercept_hours)
    if config.method == InterceptMethod.RENDEZVOUS:
        return RendezvousPlanner(eng_log).generate_plan(config.coast_hours)
    if config.method == InterceptMethod.PROXIMITY:
        return ProximityInterceptPlanner(eng_log).generate_plan(
            config.coast_hours, config.target_distance_m
        )
    if config.method == InterceptMethod.OPTIMAL:
        return OptimalInterceptPlanner(eng_log).generate_plan(
            config.coast_hours,
            config.intercept_hours,
            config.number_of_burns,
            config.target_distance_m,
            config.minimize_delta_v,
        )
    raise ValueError(f"Unknown InterceptMethod: {config.method!r}")


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
            logger.info("New scenario created", extra={"scenario_name": name})
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
            extra={"sat_name": name, "folder": folder_name, "stk_path": stk_path},
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

        # Rewind to ensure all satellites have valid propagated states before
        # STK resolves the access geometry.
        try:
            self._root.Rewind()
        except Exception as _rw_exc:
            logger.debug("Rewind before compute_access failed (non-fatal): %s", _rw_exc)

        # GetAccessTo path format varies by STK/ODTK configuration.
        # The wildcard prefix `*/` expands to the scenario name and works in
        # Connect commands but is sometimes rejected in ODTK OM calls.
        # Also try reversed direction (obj_b → obj_a): access is symmetric
        # and ODTK may block GetAccessTo on delete-recreated satellites while
        # allowing it on original OM-created ones.
        _candidates: list[tuple[Any, str]] = []
        try:
            sat_b_obj = self._root.GetObjectFromPath(f"Satellite/{obj_b}")
            _candidates = [
                (sat_obj,   f"*/Satellite/{obj_b}"),
                (sat_obj,   f"Satellite/{obj_b}"),
                (sat_b_obj, f"*/Satellite/{obj_a}"),
                (sat_b_obj, f"Satellite/{obj_a}"),
            ]
        except Exception as _exc_b:
            logger.debug("Could not pre-fetch %r for reversed access: %s", obj_b, _exc_b)
            _candidates = [
                (sat_obj, f"*/Satellite/{obj_b}"),
                (sat_obj, f"Satellite/{obj_b}"),
            ]

        access = None
        _access_exc: Exception | None = None
        for _sat, _path in _candidates:
            try:
                access = _sat.GetAccessTo(_path)
                break
            except Exception as _exc:
                logger.debug("GetAccessTo(%r, %r) failed: %s", _sat, _path, _exc)
                _access_exc = _exc

        if access is None:
            # GetAccessTo is blocked by ODTK for all satellites.
            # Try fallbacks in order:
            #   1. Pre-computed STK Access object (created when user runs access
            #      computation in the GUI; lives at Satellite/<a>/Access/<b>)
            #   2. Pure-Python SGP4 (needs TLEs readable from propagator)
            #   3. STK Cartesian Position data providers
            #   4. Scenario time window (last resort)
            logger.warning(
                "compute_access: GetAccessTo blocked for %r -> %r "
                "(ODTK restriction); trying stk_object/sgp4/position fallbacks. "
                "Last error: %s",
                obj_a, obj_b, _access_exc,
            )
            try:
                return self._compute_access_via_stk_object(obj_a, obj_b)
            except StkCommandError as _obj_exc:
                logger.debug(
                    "compute_access: stk_object fallback unavailable for %r -> %r: %s",
                    obj_a, obj_b, _obj_exc,
                )
            try:
                return self._compute_access_via_sgp4(obj_a, obj_b)
            except StkCommandError as _sgp4_exc:
                logger.debug(
                    "compute_access: sgp4 fallback unavailable for %r -> %r: %s",
                    obj_a, obj_b, _sgp4_exc,
                )
            try:
                return self._compute_access_via_positions(obj_a, obj_b)
            except Exception as _pos_exc:
                logger.warning(
                    "compute_access: position data provider fallback failed for "
                    "%r -> %r (%s); using scenario time window",
                    obj_a, obj_b, _pos_exc,
                )
                sc_start, sc_stop = self.get_scenario_time()
                return [AccessInterval(start=sc_start, end=sc_stop, min_range_km=0.0)]

        try:
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

            # ── Intercept engine methods ──────────────────────────────────────
            for method in config.intercept_methods:
                result = self._solve_via_intercept_engine(config, method, red_obj)
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

    def apply_intercept_plan(self, config: InterceptConfig) -> ManeuverOption:
        """Calculate and apply a specific intercept trajectory.

        Builds an Astrogator targeting MCS from the intercept engine algorithm,
        runs Astrogator so the DC solves for the required ΔV, then encodes the
        solved trajectory as a fixed MCS so the satellite moves in STK.

        Args:
            config: Algorithm selection, satellite names, and timing parameters.

        Returns:
            :class:`~sipc.domain.models.ManeuverOption` with solved burn epoch,
            ΔV vector, intercept epoch, and miss distance.

        Raises:
            StkConnectionError: If not connected to STK.
            StkCommandError: If Astrogator fails to converge or the MCS cannot
                be built.
        """
        self._require_connection()

        if not self._astrogator_licensed():
            raise StkCommandError(
                "STK Astrogator module is not licensed — cannot calculate intercept."
            )

        _E_PROPAGATOR_ASTROGATOR = self._astrogator_enum_value()

        red_obj = self._root.GetObjectFromPath(f"Satellite/{config.red_sat}")

        # ── Phase 1: build targeting MCS and solve ────────────────────────────
        red_obj.SetPropagatorType(_E_PROPAGATOR_ASTROGATOR)
        prop = red_obj.Propagator
        mcs = prop.MainSequence
        mcs.RemoveAll()

        epoch = config.manoeuvre_start or self.get_scenario_epoch()
        init_seg = mcs.Insert(0, "Initial State", "-")
        _set_initial_state_epoch(init_seg, _to_stk_time(epoch))

        eng_log = _EngineLogger(logger)
        plan = _build_intercept_plan_from_config(config, eng_log)
        blue_path = f"*/Satellite/{config.blue_sat}"
        MCSBuilder().build(mcs, plan, blue_path, config.max_delta_v_km_s)

        try:
            prop.Propagate()
        except Exception as exc:
            raise StkCommandError(
                f"Astrogator failed to converge for {config.method.value} intercept "
                f"({config.red_sat} → {config.blue_sat}): {exc}"
            ) from exc

        # ── Phase 2: extract the solved result ───────────────────────────────
        # Re-use _extract_engine_result by building a minimal config proxy.
        proxy = _InterceptConfigProxy(config)
        option = self._extract_engine_result(mcs, proxy, config.method, epoch)
        if option is None:
            raise StkCommandError(
                f"Could not extract results from solved MCS [{config.method.value}]"
            )

        # ── Phase 3: rebuild as fixed MCS and propagate (satellite moves) ─────
        mcs.RemoveAll()
        self._build_fixed_mcs(mcs, option)
        try:
            prop.Propagate()
        except Exception as exc:
            raise StkCommandError(
                f"apply_intercept_plan: fixed MCS propagation failed for "
                f"{config.red_sat!r}: {exc}"
            ) from exc

        logger.info(
            "apply_intercept_plan: %s applied for %r → %r "
            "(dv=%.3f km/s, burn=%s, intercept=%s)",
            config.method.value, config.red_sat, config.blue_sat,
            option.delta_v_km_s,
            option.burn_epoch.strftime("%Y-%m-%d %H:%M UTC"),
            option.intercept_epoch.strftime("%Y-%m-%d %H:%M UTC"),
        )
        return option

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

        Tries six approaches in order, stopping at the first that succeeds:

        A. **Direct segment write (existing segs)** — if the satellite already has
           SGP4 segments, assign ``Line1``/``Line2`` directly.  No file I/O.
        B. **AddSegsFromLines** — call ``CommonTasks.AddSegsFromLines(name, l1, l2)``
           in-memory.  Bypasses the TLE file parser and any catalog-registration
           validation that blocks ``AddSegsFromFile`` for pre-existing satellites.
           Documented as removed from STK 13 stubs but reachable via dynamic
           COM dispatch.
        C. **Segments.AddNew + direct write** — ``Segments.AddNew(0)`` then assign
           ``Line1``/``Line2``.  ``IAgVeSGP4SegmentCollection`` may not expose
           ``AddNew`` — included as a speculative attempt.
        D. **AddSegsFromFile** — write a normalised 3-line TLE temp file and call
           ``CommonTasks.AddSegsFromFile`` via the STK Object Model.
        E. **Delete-and-Recreate** — if catalog registration blocks A–D, delete
           the satellite from the scenario, recreate it via the Object Model
           (``Children.New``), then retry ``AddSegsFromFile``.  OM-created
           satellites do not carry the catalog registration lock.
        F. **ImportFromFile** — STK Connect command (always blocked by ODTK;
           kept as a last-resort attempt before the fallback).
        G. **Existing-scenario fallback** — if A–F all fail but the satellite had
           a valid SGP4 propagator when this method was entered (snapshotted before
           any ``SetPropagatorType`` call), restore that pre-existing TLE and
           propagate.

        Args:
            sat_name: STK object name of the satellite.
            line1: TLE line 1 (raw, may be non-standard UDL format).
            line2: TLE line 2 (raw, may be non-standard UDL format).

        Raises:
            StkCommandError: If all four approaches fail.
        """
        # AgEVePropagatorType enum values in STK 13 (confirmed from gen_py stubs):
        #   ePropagatorHPOP=0  J2=1  J4=2  LOP=3  SGP4=4  SPICE=5  StkExternal=6
        _E_PROPAGATOR_SGP4 = 4
        errors: list[str] = []

        # NORAD catalog number from TLE line 1, columns 3–7 (1-indexed).
        satno = line1[2:7].strip()

        # Log non-standard lengths before compression for diagnostics.
        if len(line1) != 69 or len(line2) != 69:
            logger.warning(
                "_set_propagator_via_om: non-standard TLE line length for %r "
                "(line1=%d chars, line2=%d chars; expected 69 each) — "
                "will compress via _compress_tle_line. line1=%r  line2=%r",
                sat_name, len(line1), len(line2), line1, line2,
            )

        # Compress/pad both lines to exactly 69 chars BEFORE normalising so that
        # _normalize_tle_line1's fixed-index sign replacement targets the correct
        # columns.  Checksum is recalculated inside _normalize_tle_line1.
        line1_norm = _normalize_tle_line1(_compress_tle_line(line1))
        line2_fit = _compress_tle_line(line2)

        # Snapshot any pre-existing SGP4 propagator BEFORE calling
        # SetPropagatorType, which would wipe the segments.  This snapshot is
        # used as the Approach D fallback if all active import methods fail.
        existing_tle = self._snapshot_tle(sat_name)
        if existing_tle is not None:
            logger.debug(
                "_set_propagator_via_om: snapshotted existing SGP4 for %r "
                "(will use as fallback if import fails)",
                sat_name,
            )

        # ------------------------------------------------------------------
        # Approach A: direct segment Line1/Line2 property assignment
        # ------------------------------------------------------------------
        # Works when the satellite already has SGP4 segments (pre-loaded
        # scenario).  No TLE file is written; no parser is invoked.
        if existing_tle is not None:
            try:
                sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
                prop = sat_obj.Propagator
                seg = prop.Segments.Item(0)
                seg.Line1 = line1_norm
                seg.Line2 = line2_fit
                prop.Propagate()
                logger.info(
                    "set_propagator (direct segment write) succeeded for %r",
                    sat_name,
                )
                return
            except Exception as exc_a0:
                errors.append(f"DirectSegWrite: {exc_a0}")
                logger.debug(
                    "Direct segment write failed for %r: %s", sat_name, exc_a0
                )

        # ------------------------------------------------------------------
        # Approach B: CommonTasks.AddSegsFromLines (in-memory, no file I/O)
        # ------------------------------------------------------------------
        # AddSegsFromLines was documented as removed in STK 13 based on
        # incomplete gen_py stubs, but dynamic COM dispatch may still reach it
        # on the live server.  This bypasses both the TLE file parser AND any
        # catalog-registration validation that blocks AddSegsFromFile for
        # pre-existing (catalog-imported) satellites.
        try:
            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            sat_obj.SetPropagatorType(_E_PROPAGATOR_SGP4)
            propagator = sat_obj.Propagator
            propagator.CommonTasks.AddSegsFromLines(satno, line1_norm, line2_fit)
            propagator.Propagate()
            logger.info(
                "set_propagator (CommonTasks.AddSegsFromLines) succeeded for %r",
                sat_name,
            )
            return
        except Exception as exc_b:
            errors.append(f"AddSegsFromLines: {exc_b}")
            logger.debug(
                "[set_propagator] AddSegsFromLines failed for %r: %s", sat_name, exc_b
            )

        # ------------------------------------------------------------------
        # Approach C: SetPropagatorType + direct Segments.AddNew (no file I/O)
        # ------------------------------------------------------------------
        # IAgVeSGP4SegmentCollection does NOT expose RemoveAll or AddNew via
        # gen_py stubs, but the raw COM dispatch may differ — worth one attempt.
        try:
            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            sat_obj.SetPropagatorType(_E_PROPAGATOR_SGP4)
            propagator = sat_obj.Propagator
            segs = propagator.Segments
            seg = segs.AddNew(0)  # eSGP4SegTypeInitial
            seg.Line1 = line1_norm
            seg.Line2 = line2_fit
            propagator.Propagate()
            logger.info(
                "set_propagator (Segments.AddNew + direct write) succeeded for %r",
                sat_name,
            )
            return
        except Exception as exc_c:
            errors.append(f"AddNew: {exc_c}")
            logger.debug(
                "[set_propagator] Segments.AddNew failed for %r: %s", sat_name, exc_c
            )

        # ------------------------------------------------------------------
        # Approach D: CommonTasks.AddSegsFromFile via Object Model
        # ------------------------------------------------------------------
        # Write a normalised 3-line TLE temp file and call via the STK Object
        # Model — bypasses the blocked Connect command layer.  Logs the exact
        # file content (repr) at DEBUG level for diagnosis.
        #
        # Force a J2 → SGP4 propagator type cycle before loading the file.
        # Satellites left in a broken SGP4 state (0 segments, from a previous
        # failed import) need this reset so SetPropagatorType(SGP4) is not a
        # no-op and AddSegsFromFile gets a truly fresh propagator to write into.
        try:
            import os  # noqa: PLC0415
            import tempfile  # noqa: PLC0415

            sat_obj = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            _E_PROPAGATOR_J2 = 1
            sat_obj.SetPropagatorType(_E_PROPAGATOR_J2)   # cycle away from SGP4
            sat_obj.SetPropagatorType(_E_PROPAGATOR_SGP4)  # fresh SGP4 init
            propagator = sat_obj.Propagator
            logger.debug(
                "[set_propagator] propagator type=%s", type(propagator).__name__
            )

            # The name line MUST match the identifier passed to AddSegsFromFile
            # exactly.  Using sat_name (e.g. "B_SAT_33274") when the identifier
            # is the catalog number ("33274") causes a lookup miss and the same
            # "Failed to add the TLE" error.  Use satno for both.
            tle_content = f"{satno}\n{line1_norm}\n{line2_fit}\n"
            logger.debug(
                "[set_propagator] TLE file content for %r (repr): %r",
                sat_name, tle_content,
            )

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tle", delete=False, encoding="ascii",
                newline="\r\n",
            ) as fh:
                fh.write(tle_content)
                tle_path = fh.name

            logger.debug(
                "[set_propagator] TLE written to %r, calling AddSegsFromFile(%r, ...)",
                tle_path, satno,
            )
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
        except Exception as exc_c:
            errors.append(f"AddSegsFromFile: {exc_c}")
            logger.warning(
                "[set_propagator] AddSegsFromFile failed for %r: %s", sat_name, exc_c
            )

        # ------------------------------------------------------------------
        # Approach E: Delete-and-Recreate
        # ------------------------------------------------------------------
        # Catalog-imported satellites have an internal STK registration that
        # blocks AddSegsFromFile/AddSegsFromLines validation (HRESULT
        # -2147220989 "Failed to add the TLE").  OM-created satellites
        # (Children.New) do not have this lock — AddSegsFromFile works for
        # them reliably.  Solution: delete the catalog satellite, recreate
        # it via OM, then load the TLE via AddSegsFromFile.
        try:
            import os as _os  # noqa: PLC0415
            import tempfile as _tempfile  # noqa: PLC0415

            sat_obj_del = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            sat_obj_del.Unload()
            logger.info(
                "[set_propagator] Deleted catalog satellite %r; will recreate via OM",
                sat_name,
            )

            created = self._create_satellite_via_om(sat_name)
            if not created:
                raise RuntimeError(
                    f"Could not recreate {sat_name!r} via OM after delete"
                )

            sat_obj_new = self._root.GetObjectFromPath(f"Satellite/{sat_name}")
            sat_obj_new.SetPropagatorType(_E_PROPAGATOR_SGP4)
            propagator_new = sat_obj_new.Propagator

            tle_content_e = f"{satno}\n{line1_norm}\n{line2_fit}\n"
            with _tempfile.NamedTemporaryFile(
                mode="w", suffix=".tle", delete=False,
                encoding="ascii", newline="\r\n",
            ) as _fh:
                _fh.write(tle_content_e)
                tle_path_e = _fh.name

            try:
                propagator_new.CommonTasks.AddSegsFromFile(satno, tle_path_e)
                propagator_new.Propagate()
                logger.info(
                    "set_propagator (delete-recreate + AddSegsFromFile) succeeded for %r",
                    sat_name,
                )
                return
            finally:
                _os.unlink(tle_path_e)
        except Exception as exc_e:
            errors.append(f"DeleteRecreate: {exc_e}")
            logger.warning(
                "[set_propagator] Delete-recreate failed for %r: %s", sat_name, exc_e
            )

        # ------------------------------------------------------------------
        # Approach F: ExecuteCommand ImportFromFile (blocked by ODTK)
        # ------------------------------------------------------------------
        try:
            self._set_tle_via_file(sat_name, line1, line2)
            logger.info("set_propagator (ImportFromFile) succeeded for %r", sat_name)
            return
        except Exception as exc_d:
            errors.append(f"ImportFromFile: {exc_d}")
            logger.debug("set_propagator ImportFromFile failed for %r: %s", sat_name, exc_d)

        # ------------------------------------------------------------------
        # Approach G: existing-scenario fallback
        # ------------------------------------------------------------------
        # All active TLE import methods failed.  If the satellite had a valid
        # SGP4 propagator before this method was called (snapshotted above),
        # restore it and continue.  This lets operators pre-load satellites in
        # the STK scenario (e.g. via STK's Space-Track import) and have SIPC
        # use that data even when UDL TLEs cannot be imported.
        if existing_tle is not None:
            logger.warning(
                "set_propagator(%r): all active import methods failed; "
                "restoring pre-existing STK scenario TLE as fallback. "
                "Errors: %s",
                sat_name, " | ".join(errors),
            )
            try:
                self._restore_sgp4(sat_name, existing_tle)
                logger.warning(
                    "set_propagator(%r): using pre-existing STK scenario TLE "
                    "(UDL TLE could not be loaded — verify TLE format)",
                    sat_name,
                )
                return
            except Exception as exc_e:
                errors.append(f"RestoreExisting: {exc_e}")
                logger.warning(
                    "set_propagator(%r): existing-scenario restore also failed: %s",
                    sat_name, exc_e,
                )

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
        line1_norm_b = _normalize_tle_line1(_compress_tle_line(line1))
        line2_fit_b = _compress_tle_line(line2)
        tle_content = f"{satno_b}\n{line1_norm_b}\n{line2_fit_b}\n"
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

    def _compute_access_via_positions(
        self,
        obj_a: str,
        obj_b: str,
        step_s: float = 60.0,
    ) -> list[AccessInterval]:
        """Compute close-approach windows via STK Cartesian Position data providers.

        Used for ODTK-managed satellites whose SGP4 segments are not directly
        readable (``_snapshot_tle`` returns ``None``).  Queries each satellite's
        ``"Cartesian Position"`` data provider at *step_s*-second intervals,
        computes range at each step, and returns windows below the
        Earth-line-of-sight threshold (derived from orbital altitude).

        Args:
            obj_a: STK object name of the first satellite.
            obj_b: STK object name of the second satellite.
            step_s: Sampling interval in seconds (default 60 s).

        Raises:
            StkCommandError: If positions cannot be read from either satellite.
        """
        import math
        from datetime import timedelta

        sc_start, sc_stop = self.get_scenario_time()
        start_str = _to_stk_time(sc_start)
        stop_str  = _to_stk_time(sc_stop)

        sat_a = self._root.GetObjectFromPath(f"Satellite/{obj_a}")
        sat_b = self._root.GetObjectFromPath(f"Satellite/{obj_b}")

        # STK 13 data provider path + dataset names (try common variants).
        _POS_PROVIDERS = [
            "Cartesian Position",
            "J2000 Cartesian",
            "ICRF Cartesian",
            "ECI Cartesian",
            "Inertial Cartesian",
            "Fixed Cartesian",
            "ECEF Cartesian",
        ]
        _XYZ_SETS = [("x", "y", "z"), ("X", "Y", "Z")]

        def _enumerate_providers(sat_obj: Any, label: str) -> None:
            """Log all available data provider names for diagnostics."""
            try:
                dps = sat_obj.DataProviders
                names: list[str] = []
                for i in range(dps.Count):
                    try:
                        names.append(str(dps.Item(i).Name))
                    except Exception:
                        pass
                logger.warning(
                    "compute_access (positions): available DataProviders for %r: %s",
                    label, names,
                )
            except Exception as _e:
                logger.warning(
                    "compute_access (positions): could not enumerate DataProviders for %r: %s",
                    label, _e,
                )

        def _sample_positions(sat_obj: Any, label: str) -> list[tuple[float, float, float]]:
            # Build index of available providers via Item() enumeration —
            # GetDataPrvIntervalFromPath() does not work on satellite DataProviders
            # objects in this ODTK/STK 13 build even when the name is valid.
            dps = sat_obj.DataProviders
            provider_by_name: dict[str, Any] = {}
            for _i in range(dps.Count):
                try:
                    _dp = dps.Item(_i)
                    provider_by_name[str(_dp.Name)] = _dp
                except Exception:
                    pass

            for prov in _POS_PROVIDERS:
                dp = provider_by_name.get(prov)
                if dp is None:
                    logger.debug(
                        "compute_access (positions): provider %r not in index for %r",
                        prov, label,
                    )
                    continue
                try:
                    res = dp.Exec(start_str, stop_str, step_s)
                except Exception as _e:
                    logger.warning(
                        "compute_access (positions): Exec failed for provider %r on %r: %s",
                        prov, label, _e,
                    )
                    continue
                # Log available dataset names on the first successful Exec
                try:
                    ds_names = [
                        str(res.DataSets.Item(i).Name)
                        for i in range(res.DataSets.Count)
                    ]
                    logger.info(
                        "compute_access (positions): provider %r datasets for %r: %s",
                        prov, label, ds_names,
                    )
                except Exception:
                    pass
                for xn, yn, zn in _XYZ_SETS:
                    try:
                        xs = list(res.DataSets.GetDataSetByName(xn).GetValues())
                        ys = list(res.DataSets.GetDataSetByName(yn).GetValues())
                        zs = list(res.DataSets.GetDataSetByName(zn).GetValues())
                        logger.info(
                            "compute_access (positions): using provider %r "
                            "datasets (%r,%r,%r) for %r — %d samples",
                            prov, xn, yn, zn, label, len(xs),
                        )
                        return list(zip(xs, ys, zs))
                    except Exception as _e:
                        logger.debug(
                            "compute_access (positions): datasets (%r,%r,%r) "
                            "not found in provider %r for %r: %s",
                            xn, yn, zn, prov, label, _e,
                        )
            # Nothing worked — enumerate available providers at WARNING level.
            _enumerate_providers(sat_obj, label)
            raise StkCommandError(
                f"No readable Cartesian Position data provider for {label!r}"
            )

        pts_a = _sample_positions(sat_a, obj_a)
        pts_b = _sample_positions(sat_b, obj_b)

        n = min(len(pts_a), len(pts_b))
        if n == 0:
            raise StkCommandError(
                f"Empty position data for {obj_a!r} or {obj_b!r}"
            )

        # Estimate Earth-LOS threshold from mean orbital radius.
        # Average altitude from position magnitudes → horizon distance per sat.
        _R_EARTH_KM = 6371.0
        mean_r_a = sum(math.sqrt(x*x + y*y + z*z) for x, y, z in pts_a) / len(pts_a)
        mean_r_b = sum(math.sqrt(x*x + y*y + z*z) for x, y, z in pts_b) / len(pts_b)
        horizon_a = math.sqrt(max(mean_r_a**2 - _R_EARTH_KM**2, 0.0))
        horizon_b = math.sqrt(max(mean_r_b**2 - _R_EARTH_KM**2, 0.0))
        range_threshold_km = horizon_a + horizon_b
        logger.debug(
            "compute_access (positions): LOS threshold for %r/%r = %.0f km",
            obj_a, obj_b, range_threshold_km,
        )

        in_window = False
        window_start: datetime | None = None
        min_range = math.inf
        intervals: list[AccessInterval] = []

        for i in range(n):
            t = sc_start + timedelta(seconds=i * step_s)
            xa, ya, za = pts_a[i]
            xb, yb, zb = pts_b[i]
            dx, dy, dz = xa - xb, ya - yb, za - zb
            rng = math.sqrt(dx*dx + dy*dy + dz*dz)

            if rng <= range_threshold_km:
                if not in_window:
                    in_window = True
                    window_start = t
                    min_range = rng
                elif rng < min_range:
                    min_range = rng
            else:
                if in_window and window_start is not None:
                    intervals.append(AccessInterval(
                        start=window_start, end=t, min_range_km=min_range,
                    ))
                    in_window = False
                    min_range = math.inf

        if in_window and window_start is not None:
            intervals.append(AccessInterval(
                start=window_start, end=sc_stop, min_range_km=min_range,
            ))

        logger.info(
            "compute_access (positions): %d window(s) for %r -> %r "
            "(threshold %.0f km, step %.0f s)",
            len(intervals), obj_a, obj_b, range_threshold_km, step_s,
        )
        return intervals

    def _compute_access_via_stk_object(
        self,
        obj_a: str,
        obj_b: str,
    ) -> list[AccessInterval]:
        """Read access windows from a pre-computed STK Access child object.

        When a user computes access between two satellites via the STK GUI,
        STK creates an ``IAgAccess`` child object under the satellite at
        ``Satellite/<obj_a>/Access/<obj_b>``.  This method reads that object
        directly — bypassing ``GetAccessTo`` which ODTK blocks — and returns
        the already-computed (or re-computed) access windows.

        Tries both ``Satellite/<obj_a>/Access/<obj_b>`` and the reversed path
        since the user may have initiated the computation from either satellite.

        Args:
            obj_a: STK object name of the first satellite.
            obj_b: STK object name of the second satellite.

        Raises:
            StkCommandError: If no pre-computed Access object is found.
        """
        candidates = [
            f"Satellite/{obj_a}/Access/{obj_b}",
            f"Satellite/{obj_b}/Access/{obj_a}",
        ]

        for path in candidates:
            try:
                access_obj = self._root.GetObjectFromPath(path)
            except Exception as _e:
                logger.debug(
                    "_compute_access_via_stk_object: %r not found: %s", path, _e
                )
                continue

            # Re-compute to pick up any propagator updates; tolerate ODTK blocking.
            try:
                access_obj.ComputeAccess()
            except Exception as _ce:
                logger.debug(
                    "_compute_access_via_stk_object: ComputeAccess blocked for "
                    "%r (%s); reading existing results",
                    path, _ce,
                )

            try:
                time_periods = access_obj.AccessTimePeriods
                count = time_periods.Count
            except Exception as _e:
                logger.debug(
                    "_compute_access_via_stk_object: AccessTimePeriods "
                    "unavailable for %r: %s",
                    path, _e,
                )
                continue

            intervals: list[AccessInterval] = []
            for i in range(count):
                period = time_periods.Item(i)
                min_range = self._query_min_range_km(
                    access_obj, period.StartTime, period.StopTime
                )
                intervals.append(
                    AccessInterval(
                        start=_parse_stk_time(period.StartTime),
                        end=_parse_stk_time(period.StopTime),
                        min_range_km=min_range,
                    )
                )

            logger.info(
                "compute_access: used existing STK Access object %r — %d window(s)",
                path, len(intervals),
            )
            return intervals

        raise StkCommandError(
            f"No pre-computed Access object found for {obj_a!r} <-> {obj_b!r}"
        )

    def _compute_access_via_sgp4(
        self,
        obj_a: str,
        obj_b: str,
        step_s: float = 30.0,
    ) -> list[AccessInterval]:
        """Compute close-approach windows using pure-Python SGP4 propagation.

        Used when STK's ``GetAccessTo`` is blocked by ODTK.  Reads the current
        TLE from each satellite's SGP4 propagator (already loaded in STK),
        propagates both with the ``sgp4`` library at *step_s*-second intervals,
        and returns windows during which the pair has line-of-sight (range less
        than the sum of each satellite's Earth-horizon distance, derived from
        its mean motion).

        Args:
            obj_a: STK object name of the first satellite.
            obj_b: STK object name of the second satellite.
            step_s: Propagation time step in seconds (default 30 s).

        Returns:
            List of :class:`AccessInterval` in chronological order.

        Raises:
            StkCommandError: If TLEs cannot be read or sgp4 is not installed.
        """
        import math
        from datetime import timedelta

        try:
            from sgp4.api import Satrec, jday  # type: ignore[import]
        except ImportError as exc:
            raise StkCommandError(
                "sgp4 package not installed — cannot compute access without STK "
                "GetAccessTo.  Install with: pip install sgp4"
            ) from exc

        tle_a = self._snapshot_tle(obj_a)
        tle_b = self._snapshot_tle(obj_b)
        if tle_a is None or tle_b is None:
            missing = obj_a if tle_a is None else obj_b
            raise StkCommandError(
                f"Cannot compute access: no SGP4 TLE available for {missing!r}"
            )

        sat_a = Satrec.twoline2rv(tle_a[0], tle_a[1])
        sat_b = Satrec.twoline2rv(tle_b[0], tle_b[1])

        # Compute Earth line-of-sight threshold from mean motions.
        # For each satellite: horizon distance = sqrt(a² - R_earth²)
        # where a is semimajor axis derived from mean motion (TLE line 2, cols 52-63).
        # Range threshold = sum of both horizons (max range at which LOS exists).
        _R_EARTH_KM = 6371.0
        _MU = 398600.4418  # km³/s²
        _TWO_PI = 2.0 * math.pi

        def _horizon_km(line2: str) -> float:
            n_rev_day = float(line2[52:63])
            n_rad_s = n_rev_day * _TWO_PI / 86400.0
            a_km = (_MU / (n_rad_s ** 2)) ** (1.0 / 3.0)
            return math.sqrt(max(a_km ** 2 - _R_EARTH_KM ** 2, 0.0))

        range_threshold_km = _horizon_km(tle_a[1]) + _horizon_km(tle_b[1])
        logger.debug(
            "compute_access (sgp4): LOS threshold for %r/%r = %.0f km, step=%.0fs",
            obj_a, obj_b, range_threshold_km, step_s,
        )

        sc_start, sc_stop = self.get_scenario_time()
        total_s = (sc_stop - sc_start).total_seconds()
        n_steps = int(total_s / step_s) + 1

        in_window = False
        window_start: datetime | None = None
        min_range = math.inf
        intervals: list[AccessInterval] = []

        for i in range(n_steps):
            t = sc_start + timedelta(seconds=i * step_s)
            jd, fr = jday(
                t.year, t.month, t.day,
                t.hour, t.minute, t.second + t.microsecond * 1e-6,
            )
            e_a, r_a, _ = sat_a.sgp4(jd, fr)
            e_b, r_b, _ = sat_b.sgp4(jd, fr)

            if e_a != 0 or e_b != 0:
                continue  # propagation error at this epoch

            dx, dy, dz = r_a[0] - r_b[0], r_a[1] - r_b[1], r_a[2] - r_b[2]
            rng = math.sqrt(dx * dx + dy * dy + dz * dz)

            if rng <= range_threshold_km:
                if not in_window:
                    in_window = True
                    window_start = t
                    min_range = rng
                elif rng < min_range:
                    min_range = rng
            else:
                if in_window and window_start is not None:
                    intervals.append(AccessInterval(
                        start=window_start, end=t, min_range_km=min_range,
                    ))
                    in_window = False
                    min_range = math.inf

        if in_window and window_start is not None:
            intervals.append(AccessInterval(
                start=window_start, end=sc_stop, min_range_km=min_range,
            ))

        logger.info(
            "compute_access (sgp4): %d window(s) for %r -> %r "
            "(threshold %.0f km, step %.0f s)",
            len(intervals), obj_a, obj_b, range_threshold_km, step_s,
        )
        return intervals

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
            if not line1 or not line2:
                return None
            # Accept lines that begin with "1" or "2" (STK may omit the space
            # after the line number in some builds/catalog imports).
            if not (line1.startswith("1") and line2.startswith("2")):
                logger.debug(
                    "Could not snapshot TLE for %r: unexpected line format "
                    "line1=%r line2=%r",
                    sat_name, line1[:10], line2[:10],
                )
                return None
            return (line1, line2)
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
        line1_norm = _normalize_tle_line1(_compress_tle_line(line1))
        line2_fit = _compress_tle_line(line2)
        tle_content = f"{satno}\n{line1_norm}\n{line2_fit}\n"
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
            _set_initial_state_epoch(init_seg, _to_stk_time(config.search_window_start))

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

    def _solve_via_intercept_engine(
        self,
        config: ManeuverSearchConfig,
        method: InterceptMethod,
        red_obj: Any,
    ) -> ManeuverOption | None:
        """Build and run an Astrogator MCS using an intercept engine algorithm.

        Mirrors :meth:`_solve_maneuver` but uses the dict-plan architecture from
        the intercept engine package and :class:`~sipc.stk_adapter.mcs_builder.MCSBuilder`
        instead of the hardcoded burn-location approach.

        The caller (``compute_maneuver_options``) is responsible for snapshotting
        and restoring the red satellite's SGP4 propagator via ``_restore_sgp4``.

        Args:
            config: Search parameters.
            method: Which intercept engine algorithm to use.
            red_obj: STK COM object for the red satellite.

        Returns:
            A :class:`~sipc.domain.models.ManeuverOption` if the DC/Optimizer
            converges, ``None`` otherwise.
        """
        _E_PROPAGATOR_ASTROGATOR = self._astrogator_enum_value()

        try:
            red_obj.SetPropagatorType(_E_PROPAGATOR_ASTROGATOR)
            prop = red_obj.Propagator
            mcs = prop.MainSequence
            mcs.RemoveAll()

            # Seed the Initial State from the operator-supplied epoch (or scenario start).
            epoch = config.manoeuvre_start or self.get_scenario_epoch()
            init_seg = mcs.Insert(0, "Initial State", "-")  # 0 = _SEG_INITIAL_STATE
            _set_initial_state_epoch(init_seg, _to_stk_time(epoch))

            # Generate the sequence plan and build the MCS from it.
            eng_log = _EngineLogger(logger)
            plan = _build_intercept_plan(method, config, eng_log)
            blue_path = f"*/Satellite/{config.blue_sat}"
            MCSBuilder().build(mcs, plan, blue_path, config.max_delta_v_km_s)

            # Run Astrogator — DC or Optimizer executes inside STK.
            prop.Propagate()

            # Extract the solved maneuver result.
            return self._extract_engine_result(mcs, config, method, epoch)

        except Exception as exc:
            logger.debug(
                "Intercept engine solve failed [%s]: %s",
                method.value, exc,
            )
            return None

    def _extract_engine_result(
        self,
        mcs: Any,
        config: ManeuverSearchConfig,
        method: InterceptMethod,
        epoch: datetime,
    ) -> ManeuverOption | None:
        """Extract a :class:`~sipc.domain.models.ManeuverOption` from a solved MCS.

        Walks the Target Sequence to find the first burn segment and the last
        propagate segment after it.  Reads the solved ΔV vector and epochs from
        their ``FinalState`` objects.

        Args:
            mcs: The Astrogator ``MainSequence`` after ``Propagate()`` has run.
            config: Search parameters (red/blue satellite names, etc.).
            method: The intercept method that produced this MCS.
            epoch: The Initial State epoch used (fallback for missing values).

        Returns:
            Populated :class:`~sipc.domain.models.ManeuverOption`, or ``None``
            if the structure cannot be parsed.
        """
        import math  # noqa: PLC0415

        # Locate the Target Sequence (second item in the MCS after Initial State).
        target_seq = None
        for i in range(mcs.Count):
            seg = mcs.Item(i)
            try:
                _ = seg.Sequence  # Only Target Sequences expose .Sequence
                target_seq = seg
                break
            except Exception:
                pass

        if target_seq is None:
            logger.warning("_extract_engine_result: no Target Sequence found in MCS [%s]", method.value)
            return None

        inner_seq = target_seq.Sequence

        # Find the first burn segment and last propagate segment after it.
        burn_seg = None
        burn_seg_idx = -1
        for i in range(inner_seq.Count):
            seg = inner_seq.Item(i)
            name = str(getattr(seg, "Name", ""))
            if "Burn" in name or "burn" in name:
                burn_seg = seg
                burn_seg_idx = i
                break  # Use first burn for epoch/DV extraction

        if burn_seg is None:
            logger.warning("_extract_engine_result: no burn segment found in Target Sequence [%s]", method.value)
            return None

        # Last propagate segment AFTER the first burn (post-burn coast).
        last_prop_seg = None
        for i in range(burn_seg_idx + 1, inner_seq.Count):
            seg = inner_seq.Item(i)
            try:
                _ = seg.StoppingConditions  # Propagate segments expose this
                last_prop_seg = seg
            except Exception:
                pass

        # Read burn epoch.
        try:
            burn_epoch = _parse_stk_time(burn_seg.FinalState.Epoch)
        except Exception:
            burn_epoch = epoch

        # Read ΔV vector (VNC Cartesian components, km/s).
        dv_v = dv_n = dv_c = 0.0
        dv_total = 0.0
        try:
            atc = burn_seg.Maneuver.AttitudeControl
            vec = atc.DeltaV
            dv_v, dv_n, dv_c = float(vec.X), float(vec.Y), float(vec.Z)
            dv_total = math.sqrt(dv_v**2 + dv_n**2 + dv_c**2)
        except Exception as exc:
            logger.debug("_extract_engine_result: could not read DV from burn segment: %s", exc)

        # Read intercept epoch from final propagate (or burn if no post-coast).
        intercept_epoch = burn_epoch
        if last_prop_seg is not None:
            try:
                intercept_epoch = _parse_stk_time(last_prop_seg.FinalState.Epoch)
            except Exception:
                pass

        transfer_s = max((intercept_epoch - burn_epoch).total_seconds(), 0.0)

        # Read miss distance from the first Range result on the DC/Optimizer profile.
        miss_km = 0.0
        try:
            profile = target_seq.Profiles.Item(0)
            for i in range(profile.Results.Count):
                res = profile.Results.Item(i)
                if "Range" in str(getattr(res, "Name", "")):
                    miss_km = float(getattr(res, "CurrentValue", 0.0))
                    break
        except Exception as exc:
            logger.debug("_extract_engine_result: could not read miss distance: %s", exc)

        return ManeuverOption(
            red_name=config.red_sat,
            blue_name=config.blue_sat,
            burn_type=BurnType.IMPULSIVE,
            burn_location=BurnLocation.CUSTOM,
            burn_epoch=burn_epoch,
            delta_v_km_s=dv_total,
            dv_prograde=dv_v,
            dv_normal=dv_n,
            dv_radial=dv_c,
            intercept_epoch=intercept_epoch,
            transfer_duration_s=transfer_s,
            intercept_range_km=miss_km,
            notes=f"{method.value} intercept",
        )

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
        _set_initial_state_epoch(init_seg, _to_stk_time(option.burn_epoch))

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
