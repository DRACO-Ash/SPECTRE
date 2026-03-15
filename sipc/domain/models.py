"""SIPC domain dataclasses — core entities used across all layers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from sipc.config.constants import BLUE_PREFIX, RED_PREFIX


@dataclass
class BlueAsset:
    """A friendly (blue) satellite asset.

    Attributes:
        name: Human-readable short name (e.g. ``Alpha``).
        tle: Two-line element string (lines 1 & 2, newline-separated).
        stk_name: Auto-derived object name (``B_SAT_<name>``).
    """

    name: str
    tle: str
    stk_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.stk_name = f"{BLUE_PREFIX}{self.name}"


@dataclass
class RedTrack:
    """A threat (red) satellite track.

    Attributes:
        name: Human-readable track identifier (e.g. ``Track01``).
        tle: Two-line element string (lines 1 & 2, newline-separated).
        stk_name: Auto-derived object name (``R_SAT_<name>``).
    """

    name: str
    tle: str
    stk_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.stk_name = f"{RED_PREFIX}{self.name}"


@dataclass
class AccessInterval:
    """A time window during which two objects have mutual access (line of sight).

    Attributes:
        start: UTC-aware start of the access window.
        end: UTC-aware end of the access window.
        min_range_km: Minimum range between the two objects during this window (km).
            Zero indicates the value was not computed or is unavailable.
    """

    start: datetime
    end: datetime
    min_range_km: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """Duration of this access interval in seconds."""
        return (self.end - self.start).total_seconds()


@dataclass
class InterceptWindow:
    """A candidate intercept window derived from access analysis.

    Attributes:
        start: UTC-aware start of the intercept opportunity.
        end: UTC-aware end of the intercept opportunity.
        min_range_km: Minimum range between interceptor and target during this window (km).
        blue_name: Human-readable name of the blue (friendly) asset.
        red_name: Human-readable name of the red (threat) track.
    """

    start: datetime
    end: datetime
    min_range_km: float
    blue_name: str
    red_name: str


class InterceptMethod(Enum):
    """Algorithm used by the intercept engine.

    ``LAMBERT``      — pre-burn coast → burn → post-burn coast (R=0).
    ``HOHMANN``      — two-burn circular coplanar transfer.
    ``BIELLIPTIC``   — three-burn transfer via intermediate apoapsis.
    ``RENDEZVOUS``   — coast → burn (match position + velocity).
    ``PROXIMITY``    — coast → burn (minimise range to target_distance_m).
    """

    LAMBERT     = "lambert"
    HOHMANN     = "hohmann"
    BIELLIPTIC  = "bielliptic"
    RENDEZVOUS  = "rendezvous"
    PROXIMITY   = "proximity"


class BurnType(Enum):
    """Type of propulsive maneuver.

    ``IMPULSIVE`` treats the burn as an instantaneous velocity change (ΔV).
    ``FINITE`` models a continuous-thrust burn over a defined duration.
    """

    IMPULSIVE = "impulsive"
    FINITE = "finite"


class BurnLocation(Enum):
    """Orbital geometry position at which a maneuver is executed.

    Each value maps to a well-defined point in the red satellite's orbit,
    used to constrain the burn epoch search.
    """

    APOGEE = "apogee"
    """Highest point in the orbit — most efficient for perigee raise."""

    PERIGEE = "perigee"
    """Lowest point in the orbit — most efficient for apogee raise."""

    ASCENDING_NODE = "ascending_node"
    """Equatorial crossing going north — most efficient for plane changes."""

    DESCENDING_NODE = "descending_node"
    """Equatorial crossing going south — alternative plane-change point."""

    NORTH_POLE = "north_pole"
    """Maximum northern latitude pass."""

    SOUTH_POLE = "south_pole"
    """Maximum southern latitude pass."""

    CUSTOM = "custom"
    """User-specified true anomaly or epoch."""


@dataclass
class ManeuverOption:
    """One solved intercept trajectory from a manoeuvre search.

    Represents a single candidate maneuver that places the red satellite
    on an intercept trajectory with the blue target.  All delta-V components
    are expressed in the VNC (Velocity-Normal-Co-normal) frame.

    Attributes:
        option_id: Unique identifier; auto-generated UUID if not supplied.
        red_name: Object name of the red (threat) satellite.
        blue_name: Object name of the blue (friendly) target satellite.
        burn_type: Impulsive or finite burn.
        burn_location: Orbital geometry tag for the burn point.
        burn_epoch: UTC datetime at which the burn is executed.
        delta_v_km_s: Total delta-V magnitude in km/s.
        dv_prograde: VNC prograde (along-track) component in km/s.
        dv_normal: VNC normal (orbit-normal) component in km/s.
        dv_radial: VNC radial (cross-track) component in km/s.
        intercept_epoch: UTC datetime when the intercept occurs.
        transfer_duration_s: Coast time from burn to intercept in seconds.
        intercept_range_km: Miss distance at intercept in km.
        notes: Human-readable label, e.g. ``"Hohmann via apogee raise"``.
    """

    red_name: str
    blue_name: str
    burn_type: BurnType
    burn_location: BurnLocation
    burn_epoch: datetime
    delta_v_km_s: float
    dv_prograde: float
    dv_normal: float
    dv_radial: float
    intercept_epoch: datetime
    transfer_duration_s: float
    intercept_range_km: float
    notes: str = ""
    option_id: str = field(default_factory=lambda: f"MNV_{uuid.uuid4().hex[:10].upper()}")


@dataclass
class ManeuverSearchConfig:
    """Parameters controlling an intercept option search.

    Attributes:
        red_sat: Object name of the red satellite (interceptor).
        blue_sat: Object name of the blue satellite (target).
        search_window_start: UTC start of the maneuver search window.
        search_window_stop: UTC end of the maneuver search window.
        max_delta_v_km_s: Solutions requiring more than this ΔV are discarded.
        burn_types: Which burn types to include in the search.
        burn_locations: Which orbital positions to evaluate for the burn.
    """

    red_sat: str
    blue_sat: str
    search_window_start: datetime
    search_window_stop: datetime
    max_delta_v_km_s: float = 3.0
    burn_types: list[BurnType] = field(
        default_factory=lambda: [BurnType.IMPULSIVE, BurnType.FINITE]
    )
    burn_locations: list[BurnLocation] = field(
        default_factory=lambda: list(BurnLocation)
    )

    # ── Intercept engine fields ───────────────────────────────────────────────
    # Ignored when intercept_methods is empty (backward-compatible default).
    intercept_methods: list[InterceptMethod] = field(default_factory=list)
    manoeuvre_start: datetime | None = None
    """Initial State epoch for the aggressor satellite.  If ``None``, the
    scenario start epoch is used."""
    coast_hours: float = 1.0
    """Pre-burn coast duration in hours (all intercept engine methods)."""
    intercept_hours: float = 6.0
    """Post-burn time-of-flight in hours (Lambert and Optimal methods)."""
    number_of_burns: int = 1
    """Number of burn segments (Optimal only)."""
    target_distance_m: float = 0.0
    """Desired miss distance in metres (Proximity and Optimal methods)."""
    minimize_delta_v: bool = True
    """Optimizer cost function — minimize total ΔV (Optimal only)."""


@dataclass
class InterceptConfig:
    """Parameters for a direct intercept engine calculation.

    Unlike :class:`ManeuverSearchConfig`, this does not scan burn locations.
    It directly encodes a specific trajectory structure (algorithm + timing)
    and solves for the ΔV that satisfies it.

    Attributes:
        red_sat: Object name of the aggressor satellite.
        blue_sat: Object name of the target satellite.
        method: Which intercept engine algorithm to use.
        manoeuvre_start: UTC epoch for the initial state. If ``None``, the
            scenario start epoch is used.
        coast_hours: Pre-burn coast duration in hours.
        intercept_hours: Post-burn time-of-flight in hours (Lambert).
        number_of_burns: Number of burn segments (reserved for future use).
        target_distance_m: Desired miss distance in metres (Proximity).
        minimize_delta_v: Minimise total ΔV (reserved for future use).
        max_delta_v_km_s: ΔV budget constraint.
    """

    red_sat: str
    blue_sat: str
    method: InterceptMethod
    manoeuvre_start: datetime | None = None
    coast_hours: float = 1.0
    intercept_hours: float = 6.0
    number_of_burns: int = 1
    target_distance_m: float = 0.0
    minimize_delta_v: bool = True
    max_delta_v_km_s: float = 3.0


@dataclass
class OrbitalEvent:
    """A future orbital geometry event for a satellite.

    Used by the Intercept Engine UI to offer clickable manoeuvre start times
    at apogee, perigee, ascending node, or descending node.
    """

    event_type: BurnLocation
    epoch: datetime
    label: str = ""


@dataclass
class BurnResult:
    """One solved burn within a multi-burn intercept solution."""

    burn_number: int
    segment_name: str
    burn_epoch: datetime
    delta_v_km_s: float
    dv_prograde: float = 0.0
    dv_normal: float = 0.0
    dv_radial: float = 0.0


@dataclass
class InterceptResult:
    """Complete result of an intercept engine solve, supporting multi-burn.

    Attributes:
        burns: Per-burn breakdown (epoch, ΔV components for each manoeuvre).
        total_delta_v_km_s: Sum of all burn magnitudes.
        arrival_epoch: UTC time when the red satellite reaches its final position.
        intercept_range_km: Miss distance at arrival in km.
    """

    red_name: str
    blue_name: str
    method: InterceptMethod
    burns: list[BurnResult] = field(default_factory=list)
    total_delta_v_km_s: float = 0.0
    arrival_epoch: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    intercept_range_km: float = 0.0
    notes: str = ""
    option_id: str = field(default_factory=lambda: f"INT_{uuid.uuid4().hex[:10].upper()}")


@dataclass
class RunConfig:
    """Provenance metadata for a single planning run.

    Attributes:
        operator: Operator username or callsign initiating the run.
        source: Data source tag for the inputs (e.g. ``SPADOC``, ``MANUAL``).
        timestamp: UTC-aware datetime when the run was created.
        run_id: Unique run identifier; auto-generated as ``RUN_<uuid>`` if not supplied.
    """

    operator: str
    source: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC)
    )
    run_id: str = field(default_factory=lambda: f"RUN_{uuid.uuid4().hex[:12].upper()}")
