"""ManeuverPlanner — domain service for intercept option validation.

Validates search configuration before intercept calculations are run.
"""

from __future__ import annotations

import logging

from sipc.domain.models import ManeuverSearchConfig

logger = logging.getLogger(__name__)


class ManeuverPlannerError(Exception):
    """Raised when the maneuver search cannot proceed due to invalid inputs."""


def validate_search_config(config: ManeuverSearchConfig) -> None:
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
