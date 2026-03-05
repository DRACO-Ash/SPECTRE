"""SIPC domain dataclasses — core entities used across all layers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

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
