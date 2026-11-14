"""The closest-approach helper, on separation functions with exact answers (SPC-102).

Each test pins one rule of spectre.astro.closest_approach: inputs are refused
before anything is sampled, the grid ends exactly at the window end and never
passes it, a failed propagation is never a minimum, every local minimum is
refined, the miss and the TCA come from one instant, ties take the earliest,
a flat series costs one refinement, and a minimum at the window edge is
flagged rather than reported as an encounter.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.closest_approach import (
    _GRID_SLACK_S,
    MAX_SAMPLES,
    ClosestApproach,
    closest_approach,
    golden_minimum,
)

EPOCH = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _must_not_be_called(t: float) -> float:
    raise AssertionError(f"separation sampled at {t} before the inputs were checked")


class _Recorder:
    """A separation function that keeps every time it is asked for."""

    def __init__(self, f: Callable[[float], float]) -> None:
        self._f = f
        self.times: list[float] = []

    def __call__(self, t: float) -> float:
        self.times.append(t)
        return self._f(t)


@pytest.mark.parametrize("name", ["span_s", "step_s", "tolerance_s"])
@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_inputs_must_be_finite_and_positive(name: str, bad: float) -> None:
    kwargs = {"span_s": 600.0, "step_s": 60.0, "tolerance_s": 0.01, name: bad}
    with pytest.raises(ValueError, match=f"closest_approach: {name} must be finite and > 0"):
        closest_approach(_must_not_be_called, kwargs["span_s"], step_s=kwargs["step_s"],
                         tolerance_s=kwargs["tolerance_s"])


def test_the_sample_count_is_bounded() -> None:
    with pytest.raises(ValueError, match=r"10,000,001 samples exceed the limit of 100,000"):
        closest_approach(_must_not_be_called, 1e7, step_s=1.0)


@pytest.mark.parametrize("step_s", [1.0, 0.5])
def test_the_sample_limit_is_exact(step_s: float) -> None:
    # MAX_SAMPLES intervals need one sample more than the limit; one interval
    # fewer fills it exactly.
    with pytest.raises(ValueError, match=r"100,001 samples exceed the limit of 100,000"):
        closest_approach(_must_not_be_called, MAX_SAMPLES * step_s, step_s=step_s)
    stub = _Recorder(lambda t: 7.0)
    result = closest_approach(stub, (MAX_SAMPLES - 1) * step_s, step_s=step_s)
    assert result.miss_km == 7.0
    # The grid is the first MAX_SAMPLES calls, and the last of them is the window end.
    assert stub.times[MAX_SAMPLES - 1] == (MAX_SAMPLES - 1) * step_s
    assert stub.times[MAX_SAMPLES - 2] == (MAX_SAMPLES - 2) * step_s


def test_the_last_sample_is_at_the_window_end() -> None:
    result = closest_approach(lambda t: 150.0 - t, 150.0, step_s=60.0)
    assert result.tca_s == 150.0
    assert result.at_window_edge is True
    assert result.miss_km == 0.0


def test_the_grid_never_passes_the_window_end() -> None:
    stub = _Recorder(lambda t: t)
    closest_approach(stub, 0.7, step_s=0.1)
    grid = stub.times[:8]
    assert all(0.0 <= t <= 0.7 for t in stub.times), [t for t in stub.times if not 0.0 <= t <= 0.7]
    assert grid[-1] == 0.7
    assert all(b > a for a, b in zip(grid, grid[1:], strict=False))
    assert stub.times[8] < grid[-1], "refinement starts after exactly eight grid samples"


def test_a_last_interval_inside_the_slack_merges_into_the_window_end() -> None:
    # 6 x 0.1 lands a hair below a span of 0.6 + 1e-12, so without the slack
    # the grid would hold two samples 1e-12 apart at the end.
    span_s = 0.6 + 1e-12
    stub = _Recorder(lambda t: t)
    closest_approach(stub, span_s, step_s=0.1)
    # The minimum is at t = 0, so every refinement time lies strictly inside (0, 0.1).
    grid = [t for t in stub.times if not 0.0 < t < 0.1]
    assert len(grid) == 7, grid
    assert grid[-1] == span_s
    assert all(t < span_s - _GRID_SLACK_S for t in grid[:-1]), grid


def test_a_failed_propagation_is_never_a_minimum() -> None:
    def separation(t: float) -> float:
        if t == 240.0:
            return math.nan
        if t == 420.0:
            return math.inf
        return abs(t - 300.0) + 5.0

    result = closest_approach(separation, 600.0, step_s=60.0)
    assert result.miss_km == pytest.approx(5.0, abs=1e-6)
    assert result.tca_s == pytest.approx(300.0, abs=0.01)
    assert result.at_window_edge is False


def test_a_failed_propagation_inside_a_refinement_bracket_is_never_a_minimum() -> None:
    # The NaN band sits between grid samples, on the side of the true
    # minimum, where only the golden-section probes can land.
    def separation(t: float) -> float:
        if 305.0 < t < 320.0:
            return math.nan
        return abs(t - 290.0) + 5.0

    result = closest_approach(separation, 600.0, step_s=60.0)
    assert result.miss_km == pytest.approx(5.0, abs=0.01)
    assert result.tca_s == pytest.approx(290.0, abs=0.01)
    assert result.at_window_edge is False


def test_no_finite_separation_is_refused() -> None:
    with pytest.raises(ValueError, match="closest_approach: no finite separation in the window"):
        closest_approach(lambda t: math.nan, 600.0, step_s=60.0)


def test_every_local_minimum_is_refined() -> None:
    # The smallest sample is 10 at 100 s; the sharp dip at 530 s reads 12 on
    # the samples either side of it, so only a refinement of every local
    # minimum finds it.
    result = closest_approach(
        lambda t: min(10.0 + 0.001 * (t - 100.0) ** 2, 2.0 + abs(t - 530.0)), 1000.0, step_s=20.0,
    )
    assert result.miss_km == pytest.approx(2.0, abs=0.01)
    assert result.tca_s == pytest.approx(530.0, abs=0.01)


def test_the_refined_point_replaces_the_sample_only_when_smaller() -> None:
    def separation(t: float) -> float:
        if t == 300.0:
            return 1.0
        if 240.0 < t < 360.0:
            return 2.0
        return 3.0 + abs(t - 300.0) / 100.0

    result = closest_approach(separation, 600.0, step_s=60.0)
    assert result.miss_km == 1.0
    assert result.tca_s == 300.0
    assert result.at_window_edge is False


def test_ties_take_the_earliest() -> None:
    def separation(t: float) -> float:
        d = min(abs(t - 500.0), abs(t - 1500.0), abs(t - 2500.0))
        return 4.0 + max(0.0, d - 50.0) / 100.0

    result = closest_approach(separation, 3000.0, step_s=60.0)
    assert result.miss_km == 4.0
    assert result.tca_s == 480.0


def test_a_flat_series_is_one_candidate() -> None:
    stub = _Recorder(lambda t: 7.0)
    result = closest_approach(stub, 6000.0, step_s=60.0)
    assert result.miss_km == 7.0
    # 101 grid samples, then one golden-section search across the whole window.
    assert len(stub.times) <= 101 + 40, len(stub.times)


@pytest.mark.parametrize(
    ("separation", "tca_s", "at_edge"),
    [
        (lambda t: 1000.0 - t, 600.0, True),
        (lambda t: 10.0 + t, 0.0, True),
        (lambda t: abs(t - 290.0) + 3.0, 290.0, False),
        (lambda t: abs(t - 310.0) + 3.0, 310.0, False),
    ],
    ids=["closing-at-the-end", "opening-at-the-start", "interior-left-of-its-sample", "interior-right-of-its-sample"],
)
def test_an_edge_minimum_is_flagged_not_reported_as_an_encounter(
    separation: Callable[[float], float], tca_s: float, at_edge: bool,
) -> None:
    result = closest_approach(separation, 600.0, step_s=60.0)
    assert result.at_window_edge is at_edge
    if at_edge:
        assert result.tca_s == tca_s
    else:
        assert result.tca_s == pytest.approx(tca_s, abs=0.01)


def test_golden_minimum_finds_a_parabola_vertex() -> None:
    t, value = golden_minimum(lambda s: (s - 37.25) ** 2 + 4.0, 0.0, 100.0, 0.01)
    assert t == pytest.approx(37.25, abs=0.01)
    assert value == pytest.approx(4.0, abs=1e-4)


class _Budget:
    """A separation function that fails the test after *limit* calls, rather than hang."""

    def __init__(self, f: Callable[[float], float], limit: int) -> None:
        self._f = f
        self._left = limit

    def __call__(self, t: float) -> float:
        self._left -= 1
        if self._left < 0:
            raise AssertionError("the search did not stop: its bracket can no longer shrink")
        return self._f(t)


@pytest.mark.parametrize("tolerance_s", [1e-11, 1e-300])
def test_a_tolerance_below_the_float_resolution_still_returns(tolerance_s: float) -> None:
    # Near 1.7e5 s one unit in the last place is about 2.9e-11 s, so the bracket
    # stops shrinking long before it is this narrow.
    separation = _Budget(lambda t: abs(t - 170000.3), 10_000)
    result = closest_approach(separation, 172800.0, step_s=60.0, tolerance_s=tolerance_s)
    assert result.tca_s == pytest.approx(170000.3, abs=1e-6)
    t, value = golden_minimum(_Budget(lambda s: abs(s - 37.25), 1_000), 0.0, 100.0, tolerance_s)
    assert t == pytest.approx(37.25, abs=1e-9)
    assert value == pytest.approx(0.0, abs=1e-9)


def test_tca_utc_adds_seconds_to_the_start() -> None:
    assert ClosestApproach(1.0, 90.5, False).tca_utc(EPOCH) == EPOCH + timedelta(seconds=90.5)
