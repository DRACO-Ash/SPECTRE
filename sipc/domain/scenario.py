"""ScenarioPlanner — orchestrates intercept planning logic.

Uses sipc.astro for orbital propagation and access computation.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sipc.astro.propagator import TLEOrbit
from sipc.domain.models import (
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
        import numpy as np

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
                except Exception:
                    logger.warning(
                        "Skipping %s vs %s — invalid TLE", blue.name, red.name
                    )
                    continue

                t = start
                in_window = False
                win_start = start
                min_range = float("inf")

                while t <= stop:
                    try:
                        sv_b = b_orb.propagate(t)
                        sv_r = r_orb.propagate(t)
                        rng = float(np.linalg.norm(sv_b.r - sv_r.r))
                    except Exception:
                        t += timedelta(seconds=_STEP_S)
                        continue

                    if rng < _ACCESS_RANGE_KM:
                        if not in_window:
                            in_window = True
                            win_start = t
                            min_range = rng
                        else:
                            min_range = min(min_range, rng)
                    elif in_window:
                        windows.append(InterceptWindow(
                            start=win_start, end=t,
                            min_range_km=min_range,
                            blue_name=blue.name, red_name=red.name,
                        ))
                        in_window = False
                        min_range = float("inf")

                    t += timedelta(seconds=_STEP_S)

                if in_window:
                    windows.append(InterceptWindow(
                        start=win_start, end=stop,
                        min_range_km=min_range,
                        blue_name=blue.name, red_name=red.name,
                    ))

        windows.sort(key=lambda w: w.start)
        logger.info(
            "Planning run complete",
            extra={"run_id": self._config.run_id, "window_count": len(windows)},
        )
        return windows
