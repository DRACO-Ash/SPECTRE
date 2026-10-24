"""ScenarioPlanner — orchestrates intercept planning logic.

Uses spectre.astro for orbital propagation and access computation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta

from spectre.astro.propagator import TLE_ERRORS, TLEOrbit
from spectre.domain.models import (
    BlueAsset,
    InterceptWindow,
    RedTrack,
    RunConfig,
)

logger = logging.getLogger(__name__)

# Range threshold (km) — pairs closer than this are reported as windows.
_ACCESS_RANGE_KM = 500.0
# Propagation step for access search.
_STEP_S = 60.0


class ScenarioPlanner:
    """High-level orchestrator for a single intercept planning run.

    Propagates all blue/red TLEs via SGP4 and identifies time windows
    where the range between any blue-red pair falls below a threshold.

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

        Propagates each blue-vs-red pair over the scenario window and
        returns :class:`InterceptWindow` entries where range < threshold.
        """
        logger.info(
            "Starting planning run",
            extra={
                "run_id": self._config.run_id,
                "blue_count": len(blue_assets),
                "red_count": len(red_tracks),
            },
        )

        windows: list[InterceptWindow] = []
        start = self._config.timestamp
        stop = start + timedelta(hours=24)

        for blue in blue_assets:
            for red in red_tracks:
                try:
                    b_orb = TLEOrbit(blue.tle)
                    r_orb = TLEOrbit(red.tle)
                except TLE_ERRORS:
                    logger.warning(
                        "Skipping %s vs %s — invalid TLE", blue.name, red.name
                    )
                    continue
                windows += _pair_windows(blue, red, _ranges(b_orb, r_orb, start, stop), stop)

        windows.sort(key=lambda w: w.start)
        logger.info(
            "Planning run complete",
            extra={"run_id": self._config.run_id, "window_count": len(windows)},
        )
        return windows


def _ranges(
    b_orb: TLEOrbit, r_orb: TLEOrbit, start: datetime, stop: datetime,
) -> Iterator[tuple[datetime, float]]:
    """Blue-red range in km at each step, skipping steps SGP4 cannot reach."""
    import numpy as np

    t = start
    while t <= stop:
        try:
            rng = float(np.linalg.norm(b_orb.propagate(t).r - r_orb.propagate(t).r))
        except TLE_ERRORS:
            pass
        else:
            yield t, rng
        t += timedelta(seconds=_STEP_S)


def _pair_windows(
    blue: BlueAsset, red: RedTrack,
    ranges: Iterable[tuple[datetime, float]], stop: datetime,
) -> list[InterceptWindow]:
    """Spans where the range stays under the threshold; one still open ends at *stop*."""
    windows: list[InterceptWindow] = []
    win_start: datetime | None = None
    min_range = float("inf")
    for t, rng in ranges:
        if rng < _ACCESS_RANGE_KM:
            if win_start is None:
                win_start, min_range = t, rng
            else:
                min_range = min(min_range, rng)
        elif win_start is not None:
            windows.append(InterceptWindow(
                start=win_start, end=t, min_range_km=min_range,
                blue_name=blue.name, red_name=red.name,
            ))
            win_start = None
    if win_start is not None:
        windows.append(InterceptWindow(
            start=win_start, end=stop, min_range_km=min_range,
            blue_name=blue.name, red_name=red.name,
        ))
    return windows
