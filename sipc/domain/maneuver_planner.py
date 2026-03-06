"""ManeuverPlanner — domain service for Astrogator intercept option generation.

Validates search configuration, delegates computation to the STK adapter,
and returns a sorted list of candidate maneuver options for operator review.
"""

from __future__ import annotations

import logging

from sipc.domain.models import ManeuverOption, ManeuverSearchConfig
from sipc.stk_adapter.interface import IStkSession

logger = logging.getLogger(__name__)


class ManeuverPlannerError(Exception):
    """Raised when the maneuver search cannot proceed due to invalid inputs."""


class ManeuverPlanner:
    """Orchestrates Astrogator intercept option generation.

    Validates the search configuration, delegates the heavy lifting to the
    STK adapter, and returns results sorted by delta-V so the operator sees
    the cheapest solutions first.

    Args:
        session: An :class:`~sipc.stk_adapter.interface.IStkSession` implementation.
    """

    def __init__(self, session: IStkSession) -> None:
        self._session = session

    def compute_options(self, config: ManeuverSearchConfig) -> list[ManeuverOption]:
        """Run the maneuver search and return sorted intercept options.

        Args:
            config: Search parameters — satellite names, time window, delta-V
                budget, burn types, and burn locations.

        Returns:
            List of :class:`~sipc.domain.models.ManeuverOption` sorted by
            ``delta_v_km_s`` ascending.  Empty if no solutions converge.

        Raises:
            ManeuverPlannerError: If *config* fails validation.
            StkConnectionError: If not connected to STK.
            StkCommandError: If the Astrogator search fails fatally.
        """
        self._validate(config)

        logger.info(
            "ManeuverPlanner: starting search",
            extra={
                "red": config.red_sat,
                "blue": config.blue_sat,
                "window_start": config.search_window_start.isoformat(),
                "window_stop": config.search_window_stop.isoformat(),
                "max_dv": config.max_delta_v_km_s,
                "burn_types": [bt.value for bt in config.burn_types],
                "burn_locations": [bl.value for bl in config.burn_locations],
            },
        )

        options = self._session.compute_maneuver_options(config)
        options.sort(key=lambda o: o.delta_v_km_s)

        logger.info(
            "ManeuverPlanner: search complete",
            extra={"option_count": len(options), "red": config.red_sat},
        )
        return options

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate(self, config: ManeuverSearchConfig) -> None:
        """Raise :class:`ManeuverPlannerError` if *config* is invalid."""
        if not config.red_sat.strip():
            raise ManeuverPlannerError("red_sat must not be empty.")
        if not config.blue_sat.strip():
            raise ManeuverPlannerError("blue_sat must not be empty.")
        if config.red_sat == config.blue_sat:
            raise ManeuverPlannerError(
                f"red_sat and blue_sat must differ (both are {config.red_sat!r})."
            )
        if config.search_window_stop <= config.search_window_start:
            raise ManeuverPlannerError(
                "search_window_stop must be after search_window_start."
            )
        if config.max_delta_v_km_s <= 0:
            raise ManeuverPlannerError(
                f"max_delta_v_km_s must be positive (got {config.max_delta_v_km_s})."
            )
        if not config.burn_types:
            raise ManeuverPlannerError("At least one BurnType must be selected.")
        if not config.burn_locations:
            raise ManeuverPlannerError("At least one BurnLocation must be selected.")
