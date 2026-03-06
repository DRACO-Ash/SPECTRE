"""FakeStkSession — in-memory IStkSession implementation for unit testing."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sipc.domain.models import (
    AccessInterval,
    BurnLocation,
    BurnType,
    ManeuverOption,
    ManeuverSearchConfig,
)

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
        self.range_km: float = 100.0
        self.scenario_start: datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        self.scenario_stop: datetime = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)
        # Maneuver options returned by compute_maneuver_options().
        # Tests may replace this with a custom list.
        self.maneuver_options: list[ManeuverOption] = []
        # Tracks the last option passed to apply_maneuver().
        self.applied_maneuver: ManeuverOption | None = None

    # ── IStkSession interface ─────────────────────────────────────────────────

    def connect(self, scenario_path: str) -> None:
        """Record connection; no actual COM call is made."""
        self.connected = True
        self.scenario_path = scenario_path
        logger.debug("FakeStkSession.connect", extra={"scenario_path": scenario_path})

    def setup_scenario_folders(self, folders: list[str]) -> None:
        """Record folder setup; no-op for the fake session."""
        logger.debug("FakeStkSession.setup_scenario_folders", extra={"folders": folders})

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
        """Return pre-configured access intervals with ``range_km`` applied to each."""
        logger.debug(
            "FakeStkSession.compute_access", extra={"obj_a": obj_a, "obj_b": obj_b}
        )
        return [
            AccessInterval(
                start=iv.start,
                end=iv.end,
                min_range_km=self.range_km,
            )
            for iv in self.access_intervals
        ]

    def set_scenario_time(self, start: datetime, stop: datetime) -> None:
        """Store scenario time window in memory."""
        self.scenario_start = start
        self.scenario_stop = stop
        logger.debug(
            "FakeStkSession.set_scenario_time",
            extra={"start": start.isoformat(), "stop": stop.isoformat()},
        )

    def get_scenario_epoch(self) -> datetime:
        """Return the configured epoch (default: 2026-01-01T00:00:00Z)."""
        return self.epoch

    def compute_maneuver_options(
        self, config: ManeuverSearchConfig
    ) -> list[ManeuverOption]:
        """Return pre-configured maneuver options, sorted by delta_v_km_s.

        Tests can configure ``self.maneuver_options`` to control what is returned.
        If the list is empty, a single deterministic stub option is synthesised
        using the first enabled burn location from *config* so that tests that
        only care about non-empty results always get one.
        """
        from datetime import timedelta  # noqa: PLC0415

        logger.debug(
            "FakeStkSession.compute_maneuver_options",
            extra={"red": config.red_sat, "blue": config.blue_sat},
        )
        if self.maneuver_options:
            return sorted(self.maneuver_options, key=lambda o: o.delta_v_km_s)

        # Synthesise one deterministic option so callers always get a result.
        location = (
            config.burn_locations[0]
            if config.burn_locations
            else BurnLocation.APOGEE
        )
        burn_type = (
            config.burn_types[0]
            if config.burn_types
            else BurnType.IMPULSIVE
        )
        burn_epoch = config.search_window_start + timedelta(hours=1)
        return [
            ManeuverOption(
                red_name=config.red_sat,
                blue_name=config.blue_sat,
                burn_type=burn_type,
                burn_location=location,
                burn_epoch=burn_epoch,
                delta_v_km_s=0.250,
                dv_prograde=0.250,
                dv_normal=0.0,
                dv_radial=0.0,
                intercept_epoch=burn_epoch + timedelta(minutes=47),
                transfer_duration_s=47 * 60,
                intercept_range_km=0.5,
                notes=f"Stub: {location.value} {burn_type.value}",
            )
        ]

    def apply_maneuver(self, red_sat: str, option: ManeuverOption) -> None:
        """Record the applied maneuver option for test assertion."""
        self.applied_maneuver = option
        logger.debug(
            "FakeStkSession.apply_maneuver",
            extra={"red_sat": red_sat, "option_id": option.option_id},
        )

    def log_action(self, run_id: str, action: str, payload: dict[str, Any]) -> None:
        """Append action to the in-memory log."""
        self.actions_log.append((run_id, action, payload))
        logger.debug(
            "FakeStkSession.log_action",
            extra={"run_id": run_id, "action": action},
        )
