"""The Monte Carlo "converged" flag tracks the precision of what it shows (audit F-103).

The flag compared the last 200 results with the whole: the mean to 1 % of
the semi-major axis (about 69 km in LEO, so it always passed) and the
standard deviation to 1 % (inside the sampling error of a 200-sample std,
so it almost always failed). Below 400 samples it was always "not
converged", and "the last 200" were in thread completion order, so the
same seed could give either answer.

It now asks whether the percentiles the panel shows are known to within a
stated tolerance: the bootstrap 95 % half-width of SMA P5, P50 and P95 is
at most 1 km. Results are aggregated in sample order.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from spectre.astro.monte_carlo import (
    CONVERGENCE_TOLERANCE_KM,
    check_convergence,
    percentile_half_width_km,
    run_monte_carlo,
)
from tests.unit.test_monte_carlo import _basic_hypothesis


def test_the_tolerance_is_stated() -> None:
    assert CONVERGENCE_TOLERANCE_KM == 1.0


def test_wide_scatter_in_few_samples_has_not_converged() -> None:
    values = np.random.default_rng(0).normal(6778.0, 50.0, 400)
    assert percentile_half_width_km(values.tolist()) > 5.0
    assert not check_convergence(values.tolist())


def test_tight_scatter_has_converged_whatever_the_count_against_400() -> None:
    values = np.random.default_rng(1).normal(6778.0, 1.0, 300)
    assert percentile_half_width_km(values.tolist()) < CONVERGENCE_TOLERANCE_KM
    assert check_convergence(values.tolist())


def test_too_few_samples_never_converge() -> None:
    assert not check_convergence([6778.0] * 20)


def test_the_same_seed_gives_the_same_answer_on_any_thread_count() -> None:
    hypothesis = _basic_hypothesis(n_samples=200)
    one = run_monte_carlo(hypothesis, prediction_horizon_hours=1.0, max_workers=1)
    four = run_monte_carlo(_basic_hypothesis(n_samples=200), prediction_horizon_hours=1.0, max_workers=4)
    assert one.converged == four.converged
    assert one.converged, "1 m/s of ΔV scatter in 200 samples pins SMA to well under 1 km"
    assert one.percentile_half_width_km == four.percentile_half_width_km
    keep = {"wall_time_seconds"}
    assert {k: v for k, v in dataclasses.asdict(one).items() if k not in keep} == \
        {k: v for k, v in dataclasses.asdict(four).items() if k not in keep}
