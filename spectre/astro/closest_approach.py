"""Closest approach inside a window, from any separation function (SPC-102).

Pure: no I/O, no logging and no element set parsing, so the Decision Engine
can call it without importing a propagator. The caller supplies the
separation in km as a function of seconds after the window start; SGP4, a
Monte Carlo trajectory or a test function all fit.

How a candidate becomes the answer:

* The window is sampled every *step_s* seconds from 0, with one sample at
  exactly *span_s*.
* A local minimum of the samples is the first sample of a run of equal values
  that is strictly below the sample before the run (or the run starts at
  t = 0) and no higher than the sample after it (or the run ends at span_s).
* Each candidate is refined by golden-section search over the sample before
  its run to the sample after it, clamped to the window. The refined point
  replaces the sample only when its separation is strictly smaller, so the
  miss and the TCA always come from the same instant.
* The smallest candidate wins; on an exact tie, the earliest TCA wins.

A separation that is NaN or infinite (a failed propagation) reads as
infinite, so it is never a minimum and never hides one beside it.

Finds every minimum only when the step is shorter than half the time between
minima; use a step no longer than a twentieth of the shorter period. A step
that skips an encounter cannot be detected here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Most samples one call may take. Bounds the cost, as events.py's
#: _MAX_SCAN_S bounds an event search (audit F-040).
MAX_SAMPLES: int = 100_000
#: The TCA is refined to this, in seconds (as scenario.py's access search).
TCA_TOLERANCE_S: float = 0.01
_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
#: A last interval shorter than this merges into the sample at span_s.
_GRID_SLACK_S: float = 1e-9


@dataclass(frozen=True)
class ClosestApproach:
    """The smallest separation found in a window, and when.

    ``at_window_edge`` is True when the winning point is the first or last
    grid sample itself, and ``tca_s`` is then exactly 0.0 or the window span.
    The objects are still closing at the end of the window, or already
    opening at its start: this is the smallest separation inside the window,
    not an encounter. An interior encounter with a larger miss is not
    reported when the edge value is smaller.
    """

    miss_km: float
    tca_s: float
    at_window_edge: bool

    def tca_utc(self, start: datetime) -> datetime:
        """The TCA as a time, given the window start."""
        return start + timedelta(seconds=self.tca_s)


def golden_minimum(
    f: Callable[[float], float], lo: float, hi: float, tolerance_s: float,
) -> tuple[float, float]:
    """Golden-section search for the minimum of *f* on [lo, hi].

    Returns (t, f(t)) at the midpoint of the final bracket, once it is no
    wider than *tolerance_s*, or once it can no longer shrink because its
    ends are a few units in the last place apart, so a tolerance finer than
    the float resolution of the times still returns. It uses comparisons
    only, so infinite values are safe; *f* must never return NaN.
    """
    a, b = lo, hi
    c, d = b - _GOLDEN * (b - a), a + _GOLDEN * (b - a)
    fc, fd = f(c), f(d)
    width = math.inf
    while tolerance_s < b - a < width:
        width = b - a
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - _GOLDEN * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + _GOLDEN * (b - a)
            fd = f(d)
    mid = (a + b) / 2.0
    return mid, f(mid)


def closest_approach(
    separation_km: Callable[[float], float],
    span_s: float,
    *,
    step_s: float = 60.0,
    tolerance_s: float = TCA_TOLERANCE_S,
) -> ClosestApproach:
    """The closest approach in the window [0, *span_s*] seconds.

    Raises ValueError, before *separation_km* is called, when *span_s*,
    *step_s* or *tolerance_s* is not finite and positive, or when the window
    needs more than MAX_SAMPLES samples; and when no sample is finite.
    """
    _require_positive("span_s", span_s)
    _require_positive("step_s", step_s)
    _require_positive("tolerance_s", tolerance_s)
    grid = _grid(span_s, step_s)

    def finite_separation(t: float) -> float:
        return _finite(separation_km(t))

    values = [finite_separation(t) for t in grid]
    if not any(math.isfinite(v) for v in values):
        raise ValueError("closest_approach: no finite separation in the window")
    miss, tca, index = min(
        (_refine(finite_separation, grid, values, run, tolerance_s) for run in _candidates(values)),
        key=lambda candidate: (candidate[0], candidate[1]),
    )
    return ClosestApproach(miss_km=miss, tca_s=tca, at_window_edge=index in (0, len(grid) - 1))


def _require_positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0.0):
        raise ValueError(f"closest_approach: {name} must be finite and > 0; got {value!r}")


def _grid(span_s: float, step_s: float) -> list[float]:
    """0, step_s, 2 step_s ... while short of span_s, then exactly span_s.

    Each time is k * step_s, never a running sum, and a last interval within
    _GRID_SLACK_S of the end merges into it, so the grid strictly increases
    and never passes span_s.
    """
    ratio = span_s / step_s
    if ratio > MAX_SAMPLES - 1:
        count = math.ceil(ratio) + 1 if math.isfinite(ratio) else ratio
        raise ValueError(
            f"closest_approach: {count:,} samples exceed the limit of {MAX_SAMPLES:,}; "
            "lengthen the step or shorten the window"
        )
    interior = (k * step_s for k in range(1, math.ceil(ratio) + 1))
    return [0.0, *(t for t in interior if t < span_s - _GRID_SLACK_S), span_s]


def _finite(value: float) -> float:
    """*value* as a float, with NaN and infinity read as infinity."""
    value = float(value)
    return value if math.isfinite(value) else math.inf


def _same(a: float, b: float) -> bool:
    """Exactly equal, for samples already passed through _finite (no NaN).

    A run of identical samples is one candidate; a tolerance here would merge
    distinct samples and change which one is the minimum.
    """
    return not (a < b or b < a)


def _candidates(values: list[float]) -> list[tuple[int, int]]:
    """(first, last) index of each run of equal samples that is a local minimum."""
    runs: list[tuple[int, int]] = []
    last_index = len(values) - 1
    first = 0
    while first <= last_index:
        last = first
        while last < last_index and _same(values[last + 1], values[first]):
            last += 1
        below_before = first == 0 or values[first] < values[first - 1]
        no_higher_after = last == last_index or values[first] <= values[last + 1]
        if below_before and no_higher_after:
            runs.append((first, last))
        first = last + 1
    return runs


def _refine(
    f: Callable[[float], float], grid: list[float], values: list[float],
    run: tuple[int, int], tolerance_s: float,
) -> tuple[float, float, int]:
    """(miss, tca, sample index) for one candidate run; index -1 for a refined point.

    The refined point replaces the run's first sample only when strictly
    smaller, so the miss and the TCA always come from the same instant.
    """
    first, last = run
    lo = grid[max(first - 1, 0)]
    hi = grid[min(last + 1, len(grid) - 1)]
    t, miss = golden_minimum(f, lo, hi, tolerance_s)
    if miss < values[first]:
        return miss, t, -1
    return values[first], grid[first], first
