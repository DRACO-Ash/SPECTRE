"""A sampled evaluation runs under one wall-time budget, can be stopped, and reports its progress (SPC-113).

The route runs a sampled evaluation as a session job the page polls, so the
operator's request no longer waits for it. The job hands evaluate_scenario a
RunControl: a budget in seconds, a stop that names why the evaluation is no
longer wanted, a progress callback and a clock. The sampler ticks once per
sample; each tick reports progress, raises EvaluationStoppedError when stop
speaks, and refuses the row, naming the budget, once the budget is spent.
Rows after a spent budget are refused without starting.

Every test injects a fake sampler and a fake clock, so none depends on the
wall clock or runs a propagator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from spectre.astro.monte_carlo import BlueTrack, ManoeuvreHypothesis, SeparationSeries, SeparationWindow, Tick
from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    EvaluationStoppedError,
    RunControl,
    SamplingProgress,
    evaluate_scenario,
    needs_a_run,
)
from tests.unit.test_decision_sampled import _LOOKUPS, _bound, _cells, _evasive, _scenario, _series, _steady

_PART = (
    "Not sampled: this evaluation's {budget} s budget ran out after {k} of {n} samples of this hypothesis, and a "
    "P5 from part of them would not be earned. Take fewer samples or a shorter horizon." + _LOOKUPS
)
_NONE = (
    "Not sampled: this evaluation's {budget} s budget ran out before this hypothesis started. Take fewer samples "
    "or a shorter horizon." + _LOOKUPS
)


class _Clock:
    """A fake monotonic clock: 0 at the first reading, then *step* seconds later at each one after."""

    def __init__(self, step: float) -> None:
        self.step, self.readings = step, 0

    def __call__(self) -> float:
        now = self.step * self.readings
        self.readings += 1
        return now


class _Ticking:
    """A sampler that ticks once per sample for its 50 samples, then returns the fake series."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(
        self, _h: ManoeuvreHypothesis, _b: BlueTrack, window: SeparationWindow, /, *, tick: Tick | None = None,
        **_: Any,
    ) -> SeparationSeries:
        self.calls += 1
        for k in range(1, 51):
            if tick is not None:
                tick(k, 50)
        return _series(window)


def _run(
    clock: _Clock, *, budget_s: float = EVALUATION_BUDGET_S, stop: Callable[[], str | None] = lambda: None,
    progress: Callable[[SamplingProgress], None] | None = None,
) -> RunControl:
    if progress is None:
        return RunControl(budget_s=budget_s, stop=stop, clock=clock)
    return RunControl(budget_s=budget_s, stop=stop, progress=progress, clock=clock)


def _refusals(result: Any, row: int) -> set[str | None]:
    return {cell.ca_refusal for cell in _cells(result, row)}


#: The product's budget as the refusal names it, and the samples done within it at 10 s a sample, fewer than 50.
_BUDGET = f"{EVALUATION_BUDGET_S:g}"
_DONE_AT_10_S = int(EVALUATION_BUDGET_S // 10.0)


def test_a_row_that_runs_past_the_budget_names_the_samples_done_within_it() -> None:
    """B3: at 10 s a sample, the one after EVALUATION_BUDGET_S / 10 finishes past the budget, so that many were
    done when the budget ran out (30 of 50 at 300 s)."""
    assert _DONE_AT_10_S < 50
    sampler = _Ticking()
    result = evaluate_scenario(_bound(), sampler=sampler, run=_run(_Clock(10.0)))
    assert sampler.calls == 1
    assert _refusals(result, 0) == {_PART.format(budget=_BUDGET, k=_DONE_AT_10_S, n=50)}
    assert all(cell.ca_percentiles is None for cell in _cells(result, 0))


def test_rows_after_a_spent_budget_are_refused_without_starting() -> None:
    """B4."""
    sampler = _Ticking()
    result = evaluate_scenario(_bound({0: _evasive(), 1: _evasive()}), sampler=sampler, run=_run(_Clock(10.0)))
    assert sampler.calls == 1
    assert _refusals(result, 0) == {_PART.format(budget=_BUDGET, k=_DONE_AT_10_S, n=50)}
    assert _refusals(result, 1) == {_NONE.format(budget=_BUDGET)}


def test_a_first_row_inside_the_budget_is_sampled_and_a_second_past_it_refused() -> None:
    """B5: 1 s a reading and an 80 s budget: row 1's 50 ticks end at 50 s, row 2 starts at 51 s and its 30th sample ends at 81 s."""
    sampler = _Ticking()
    result = evaluate_scenario(
        _bound({0: _evasive(), 1: _evasive()}), sampler=sampler, run=_run(_Clock(1.0), budget_s=80.0),
    )
    assert sampler.calls == 2
    assert _refusals(result, 0) == {None}
    assert all(cell.ca_percentiles is not None for cell in _cells(result, 0))
    assert _refusals(result, 1) == {_PART.format(budget=80, k=29, n=50)}


def test_a_row_whose_last_sample_ends_past_the_budget_keeps_its_complete_series() -> None:
    """Every sample is done, so nothing is refused for it; the next row is refused before it starts.

    Budget 49.5 s at 1 s a reading: row 1's 50th tick reads 50 s, row 2's start reads 51 s.
    """
    sampler = _Ticking()
    result = evaluate_scenario(
        _bound({0: _evasive(), 1: _evasive()}), sampler=sampler, run=_run(_Clock(1.0), budget_s=49.5),
    )
    assert sampler.calls == 1
    assert _refusals(result, 0) == {None}
    assert _refusals(result, 1) == {_NONE.format(budget="49.5")}


def test_a_row_starting_exactly_at_the_budget_starts() -> None:
    """Spent means past the budget: row 2's start reads 51 s against a 51 s budget, so it starts; its first tick reads
    52 s with no sample finished within the budget."""
    sampler = _Ticking()
    result = evaluate_scenario(
        _bound({0: _evasive(), 1: _evasive()}), sampler=sampler, run=_run(_Clock(1.0), budget_s=51.0),
    )
    assert sampler.calls == 2
    assert _refusals(result, 1) == {_PART.format(budget=51, k=0, n=50)}


def test_a_sample_finishing_exactly_at_the_budget_is_within_it() -> None:
    """The 25th sample ends at 25 s, exactly the budget, so the row goes on; the 26th ends past it, so 25 were done."""
    result = evaluate_scenario(_bound(), sampler=_Ticking(), run=_run(_Clock(1.0), budget_s=25.0))
    assert _refusals(result, 0) == {_PART.format(budget=25, k=25, n=50)}


def test_a_stop_that_speaks_ends_the_evaluation_with_its_reason() -> None:
    """B6: no result, and the reason is the stop's own fixed sentence."""
    ticks: list[int] = []

    def stop() -> str | None:
        ticks.append(1)
        return "you cancelled it" if len(ticks) == 4 else None

    sampler = _Ticking()
    with pytest.raises(EvaluationStoppedError) as stopped:
        evaluate_scenario(_bound({0: _evasive(), 1: _evasive()}), sampler=sampler, run=_run(_Clock(0.0), stop=stop))
    assert stopped.value.reason == "you cancelled it"
    assert str(stopped.value) == "you cancelled it"
    assert sampler.calls == 1 and len(ticks) == 4


def test_progress_is_reported_once_per_sample() -> None:
    """B7: row and rows count the rows that run, done and total the samples of the row, elapsed from the budget."""
    seen: list[SamplingProgress] = []
    evaluate_scenario(
        _bound({0: _evasive(), 2: _evasive()}), sampler=_Ticking(), run=_run(_Clock(0.5), progress=seen.append),
    )
    assert len(seen) == 100
    assert seen[0] == SamplingProgress(row=1, rows=2, done=1, total=50, elapsed_s=0.5)
    assert seen[49] == SamplingProgress(row=1, rows=2, done=50, total=50, elapsed_s=25.0)
    assert seen[50] == SamplingProgress(row=2, rows=2, done=1, total=50, elapsed_s=26.0)
    assert seen[-1] == SamplingProgress(row=2, rows=2, done=50, total=50, elapsed_s=50.5)


def test_without_a_run_control_the_sampler_is_called_without_a_tick() -> None:
    """Without a RunControl no tick is passed: three positional arguments and the element-set error every bound row
    draws (SPC-202), nothing else."""
    calls: list[tuple[Any, ...]] = []

    def three(*args: Any, **kwargs: Any) -> SeparationSeries:
        calls.append((args, kwargs))
        return _series(args[2])

    evaluate_scenario(_bound(), sampler=three)
    assert len(calls) == 1 and len(calls[0][0]) == 3 and set(calls[0][1]) == {"elset_error"}


def test_a_run_control_without_a_ready_row_never_reads_its_clock() -> None:
    """A lookup scenario needs no budget: the clock starts only when the first row does."""
    clock = _Clock(10.0)
    evaluate_scenario(_scenario(), run=_run(clock))
    assert clock.readings == 0


class TestNeedsARun:
    """B10: whether an evaluation would sample anything, known before anything runs."""

    def test_a_lookup_scenario_needs_no_run(self) -> None:
        assert needs_a_run(_scenario()) is False

    def test_a_row_refused_before_running_needs_no_run(self) -> None:
        assert needs_a_run(_bound({0: _evasive(49)})) is False

    def test_a_scenario_over_the_cap_needs_no_run(self) -> None:
        assert needs_a_run(_bound({0: _steady(500), 1: _steady(500)}, horizon_hours=11.9)) is False

    def test_an_unbound_hypothesis_needs_no_run(self) -> None:
        assert needs_a_run(_scenario({0: _evasive()})) is False

    def test_a_ready_row_needs_a_run(self) -> None:
        assert needs_a_run(_bound()) is True
