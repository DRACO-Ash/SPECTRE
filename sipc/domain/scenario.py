"""ScenarioPlanner — orchestrates intercept planning logic.

Uses sipc.astro for orbital propagation and access computation.
"""

from __future__ import annotations

import logging

from sipc.domain.models import (
    BlueAsset,
    InterceptWindow,
    RedTrack,
    RunConfig,
)

logger = logging.getLogger(__name__)


class ScenarioPlanner:
    """High-level orchestrator for a single intercept planning run.

    Responsibilities:
    - Propagate satellite TLEs using sipc.astro.
    - Compute access windows for all blue-vs-red pairs.
    - Return results for display in the UI.

    Args:
        config: Run provenance metadata.
    """

    def __init__(self, config: RunConfig) -> None:
        self._config = config

    def plan(
        self,
        blue_assets: list[BlueAsset],
        red_tracks: list[RedTrack],
    ) -> list[InterceptWindow]:
        """Execute a full planning run.

        Args:
            blue_assets: List of friendly assets to evaluate.
            red_tracks: List of threat tracks to evaluate against.

        Returns:
            Candidate :class:`InterceptWindow` list, ordered by start time.
        """
        logger.info(
            "Starting planning run",
            extra={
                "run_id": self._config.run_id,
                "blue_count": len(blue_assets),
                "red_count": len(red_tracks),
            },
        )

        # TODO: Implement access computation using sipc.astro propagation.
        # For now return empty — the intercept engine handles the real work.
        windows: list[InterceptWindow] = []

        logger.info(
            "Planning run complete",
            extra={"run_id": self._config.run_id, "window_count": len(windows)},
        )
        return windows
