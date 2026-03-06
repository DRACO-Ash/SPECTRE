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
        stk_name: Auto-derived STK object name (``B_SAT_<name>``).
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
        stk_name: Auto-derived STK object name (``R_SAT_<name>``).
    """

    name: str
    tle: str
    stk_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.stk_name = f"{RED_PREFIX}{self.name}"


@dataclass
class AccessInterval:
    """A time window during which two STK objects have mutual access (line of sight).

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
    used by the Astrogator MCS to constrain the burn epoch search.
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
    """One solved intercept trajectory from the Astrogator search.

    Represents a single candidate maneuver that places the red satellite
    on an intercept trajectory with the blue target.  All delta-V components
    are expressed in the VNC (Velocity-Normal-Co-normal) frame.

    Attributes:
        option_id: Unique identifier; auto-generated UUID if not supplied.
        red_name: STK object name of the red (threat) satellite.
        blue_name: STK object name of the blue (friendly) target satellite.
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
    """Parameters controlling the Astrogator intercept option search.

    Attributes:
        red_sat: STK object name of the red satellite (interceptor).
        blue_sat: STK object name of the blue satellite (target).
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
