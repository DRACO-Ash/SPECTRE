"""ScenarioPlanner — orchestrates intercept planning logic.

Uses spectre.astro for orbital propagation and access computation.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from datetime import datetime, timedelta

import numpy as np

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
# Step bounds for the access search. The step adapts to the geometry: a fixed
# 60 s skipped encounters closing at 15 km/s, which are inside 500 km for
# under a minute (audit F-115).
_MAX_STEP_S = 60.0
_MIN_STEP_S = 1.0
# Samples per crossing of the threshold sphere while inside it.
_SAMPLES_PER_CHORD = 8
# Closest approach is refined to this, in seconds.
_TCA_TOLERANCE_S = 0.01
_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0


class ScenarioPlanner:
    """High-level orchestrator for a single intercept planning run.

    Propagates all blue/red TLEs via SGP4 and identifies time windows
    where the range between any blue-red pair falls below a threshold,
    each with its closest approach refined between samples.

    Args:
        config: Run provenance metadata, and the search horizon.
    """

    def __init__(self, config: RunConfig) -> None:
        self._config = config

    def plan(
        self,
        blue_assets: list[BlueAsset],
        red_tracks: list[RedTrack],
    ) -> list[InterceptWindow]:
        """Execute a full planning run.

        Propagates each blue-vs-red pair over the configured horizon and
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
        stop = start + timedelta(hours=self._config.horizon_hours)

        for blue in blue_assets:
            for red in red_tracks:
                try:
                    pair = _Pair(TLEOrbit(blue.tle), TLEOrbit(red.tle))
                except TLE_ERRORS:
                    logger.warning(
                        "Skipping %s vs %s — invalid TLE", blue.name, red.name
                    )
                    continue
                windows += _pair_windows(blue, red, pair, _samples(pair, start, stop), stop)

        windows.sort(key=lambda w: w.start)
        logger.info(
            "Planning run complete",
            extra={"run_id": self._config.run_id, "window_count": len(windows)},
        )
        return windows


class _Pair:
    """A blue and a red orbit, measured against each other."""

    def __init__(self, blue: TLEOrbit, red: TLEOrbit) -> None:
        self._blue = blue
        self._red = red

    def range_and_speed(self, t: datetime) -> tuple[float, float] | None:
        """Range (km) and relative speed (km/s) at *t*, or ``None`` where SGP4 fails."""
        try:
            b, r = self._blue.propagate(t), self._red.propagate(t)
        except TLE_ERRORS:
            return None
        return float(np.linalg.norm(b.r - r.r)), float(np.linalg.norm(b.v - r.v))

    def range_km(self, t: datetime) -> float:
        """Range at *t*; infinite where SGP4 fails, so a search steps away from it."""
        measured = self.range_and_speed(t)
        return math.inf if measured is None else measured[0]


def _next_step_s(range_km: float, speed_km_s: float) -> float:
    """How far the next sample may be without stepping over an encounter.

    Outside the threshold, range cannot fall faster than the relative speed,
    so the gap divided by that speed is safe. Inside, the step keeps several
    samples on the shortest chord the speed allows.
    """
    if speed_km_s <= 0.0:
        return _MAX_STEP_S
    gap = range_km - _ACCESS_RANGE_KM
    step = gap / speed_km_s if gap > 0.0 else _ACCESS_RANGE_KM / (_SAMPLES_PER_CHORD * speed_km_s)
    return min(_MAX_STEP_S, max(_MIN_STEP_S, step))


def _samples(pair: _Pair, start: datetime, stop: datetime) -> list[tuple[datetime, float | None]]:
    """(time, range) across the horizon; ``None`` where propagation failed."""
    out: list[tuple[datetime, float | None]] = []
    t = start
    while t <= stop:
        measured = pair.range_and_speed(t)
        out.append((t, None if measured is None else measured[0]))
        step = _MAX_STEP_S if measured is None else _next_step_s(*measured)
        t += timedelta(seconds=step)
    return out


def _closest(pair: _Pair, lo: datetime, hi: datetime) -> tuple[datetime, float]:
    """Golden-section search for the closest approach between *lo* and *hi*."""
    a, b = 0.0, (hi - lo).total_seconds()
    c, d = b - _GOLDEN * (b - a), a + _GOLDEN * (b - a)
    fc = pair.range_km(lo + timedelta(seconds=c))
    fd = pair.range_km(lo + timedelta(seconds=d))
    while b - a > _TCA_TOLERANCE_S:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - _GOLDEN * (b - a)
            fc = pair.range_km(lo + timedelta(seconds=c))
        else:
            a, c, fc = c, d, fd
            d = a + _GOLDEN * (b - a)
            fd = pair.range_km(lo + timedelta(seconds=d))
    mid = (a + b) / 2.0
    return lo + timedelta(seconds=mid), pair.range_km(lo + timedelta(seconds=mid))


def _runs(samples: list[tuple[datetime, float | None]]) -> Iterator[tuple[int, int]]:
    """Index spans [i, j) of consecutive samples inside the threshold."""
    i = 0
    while i < len(samples):
        rng = samples[i][1]
        if rng is None or rng >= _ACCESS_RANGE_KM:
            i += 1
            continue
        j = i
        while j < len(samples) and (r := samples[j][1]) is not None and r < _ACCESS_RANGE_KM:
            j += 1
        yield i, j
        i = j


def _pair_windows(
    blue: BlueAsset, red: RedTrack, pair: _Pair,
    samples: list[tuple[datetime, float | None]], stop: datetime,
) -> list[InterceptWindow]:
    """Spans where the range stays under the threshold, each with its refined minimum.

    A window ends at the first sample outside it, at a sample SGP4 could not
    reach (it used to carry on regardless), or at *stop*.
    """
    windows: list[InterceptWindow] = []
    for i, j in _runs(samples):
        end = samples[j][0] if j < len(samples) else stop
        k = min(range(i, j), key=lambda n: samples[n][1] or math.inf)
        lo = samples[k - 1][0] if k > 0 else samples[k][0]
        hi = samples[k + 1][0] if k + 1 < len(samples) else samples[k][0]
        sampled = samples[k][1] or math.inf
        refined = _closest(pair, lo, hi)[1] if hi > lo else sampled
        windows.append(InterceptWindow(
            start=samples[i][0], end=end, min_range_km=min(sampled, refined),
            blue_name=blue.name, red_name=red.name,
        ))
    return windows
