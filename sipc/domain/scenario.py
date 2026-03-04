"""ScenarioPlanner — orchestrates intercept planning logic.

The planner operates entirely in domain terms. It depends on the
IStkSession Protocol (injected at construction) so that it can be
tested with FakeStkSession without a live STK installation.
"""

from __future__ import annotations

import logging

from sipc.domain.models import (
    AccessInterval,
    BlueAsset,
    InterceptWindow,
    RedTrack,
    RunConfig,
)
from sipc.stk_adapter.interface import IStkSession

logger = logging.getLogger(__name__)


class ScenarioPlanner:
    """High-level orchestrator for a single intercept planning run.

    Responsibilities:
    - Build or update the STK scenario via the session adapter.
    - Run access analysis for all blue-vs-red pairs.
    - Convert access intervals to candidate intercept windows.
    - Return results for display in the UI.

    Args:
        session: An :class:`~sipc.stk_adapter.interface.IStkSession` implementation.
        config: Run provenance metadata.
    """

    def __init__(self, session: IStkSession, config: RunConfig) -> None:
        self._session = session
        self._config = config

    def plan(
        self,
        blue_assets: list[BlueAsset],
        red_tracks: list[RedTrack],
    ) -> list[InterceptWindow]:
        """Execute a full planning run.

        Steps:
        1. Create or update satellite objects in STK.
        2. Compute access for every blue/red pair.
        3. Convert raw access intervals to :class:`InterceptWindow` objects.

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

        self._provision_assets(blue_assets, red_tracks)
        windows = self._compute_windows(blue_assets, red_tracks)

        logger.info(
            "Planning run complete",
            extra={"run_id": self._config.run_id, "window_count": len(windows)},
        )
        return windows

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _provision_assets(
        self, blue_assets: list[BlueAsset], red_tracks: list[RedTrack]
    ) -> None:
        """Create/update all satellite objects in the STK scenario."""
        from sipc.config.constants import STK_FOLDERS

        for asset in blue_assets:
            self._session.log_action(
                self._config.run_id,
                "create_blue_asset",
                {"name": asset.stk_name},
            )
            self._session.create_satellite(asset.stk_name, STK_FOLDERS[0])  # /Blue
            self._session.set_propagator(asset.stk_name, asset.tle)

        for track in red_tracks:
            self._session.log_action(
                self._config.run_id,
                "create_red_track",
                {"name": track.stk_name},
            )
            self._session.create_satellite(track.stk_name, STK_FOLDERS[1])  # /Red
            self._session.set_propagator(track.stk_name, track.tle)

    def _compute_windows(
        self,
        blue_assets: list[BlueAsset],
        red_tracks: list[RedTrack],
    ) -> list[InterceptWindow]:
        """Compute access and build intercept windows for all asset pairs."""
        windows: list[InterceptWindow] = []
        for asset in blue_assets:
            for track in red_tracks:
                intervals: list[AccessInterval] = self._session.compute_access(
                    asset.stk_name, track.stk_name
                )
                for interval in intervals:
                    windows.append(
                        InterceptWindow(
                            start=interval.start,
                            end=interval.end,
                            min_range_km=0.0,  # TODO: query geometry for min-range
                        )
                    )
        windows.sort(key=lambda w: w.start)
        return windows
