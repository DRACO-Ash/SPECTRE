"""ScenarioViewModel — bridges domain models and the UI layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sipc.domain.models import BlueAsset, InterceptWindow, RedTrack, RunConfig

logger = logging.getLogger(__name__)


@dataclass
class ScenarioViewModel:
    """Observable state for the current scenario and planning run.

    The UI panels read from and write to this view-model. Changes here
    propagate to the domain layer when the user triggers a planning run.

    Attributes:
        blue_assets: Current list of blue (friendly) satellite assets.
        red_tracks: Current list of red (threat) satellite tracks.
        run_config: Provenance configuration for the active or next run.
        intercept_windows: Results from the most recent planning run.
    """

    blue_assets: list[BlueAsset] = field(default_factory=list)
    red_tracks: list[RedTrack] = field(default_factory=list)
    run_config: RunConfig | None = None
    intercept_windows: list[InterceptWindow] = field(default_factory=list)

    def add_blue_asset(self, asset: BlueAsset) -> None:
        """Add a blue asset, replacing any existing asset with the same name.

        Args:
            asset: The :class:`~sipc.domain.models.BlueAsset` to add.
        """
        self.blue_assets = [a for a in self.blue_assets if a.name != asset.name]
        self.blue_assets.append(asset)
        logger.debug("Added blue asset: %s", asset.stk_name)

    def add_red_track(self, track: RedTrack) -> None:
        """Add a red track, replacing any existing track with the same name.

        Args:
            track: The :class:`~sipc.domain.models.RedTrack` to add.
        """
        self.red_tracks = [t for t in self.red_tracks if t.name != track.name]
        self.red_tracks.append(track)
        logger.debug("Added red track: %s", track.stk_name)

    def clear_results(self) -> None:
        """Clear intercept window results from the previous run."""
        self.intercept_windows = []
