"""The next-manoeuvre band is a small-sample prediction interval, timed on burns.

Audit F-094. The "± X d (2σ)" band was twice the sample deviation from as
few as three intervals, which implies about 95% coverage; with three intervals
the Student t factor is 4.30, not 2, and a band for the NEXT interval also
carries the uncertainty of the mean, sqrt(1 + 1/n). The intervals were also
measured between after-element-set epochs, which can lag a burn by the whole
gap, rather than between the burns.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta

import pytest
from scipy import stats

from spectre.astro.pattern_of_life import _MIN_INTERVALS_FOR_PREDICTION, _next_manoeuvre
from tests.unit.test_pol_status_ladder import _BURN, _manoeuvre


def _burns_at(days: list[float], lag_days: float = 0.0) -> list:
    """Manoeuvres burning at *days*, their after-sets *lag_days* later."""
    out = []
    for d in days:
        m = dataclasses.replace(_manoeuvre(0.01), epoch=_BURN + timedelta(days=d + lag_days))
        out.append(m)
    return out


def test_the_band_is_the_t_prediction_interval() -> None:
    # Intervals 10, 12, 14 days: mean 12, sample deviation 2.
    mnvs = _burns_at([0, 10, 22, 36])
    est, unc = _next_manoeuvre(mnvs, burn_time=lambda m: m.epoch)
    n = 3
    expected = stats.t.ppf(0.975, n - 1) * 2.0 * math.sqrt(1 + 1 / n)
    assert unc == pytest.approx(round(expected, 1))
    assert est == (_BURN + timedelta(days=48)).strftime("%Y-%m-%d %H:%M UTC")


def test_too_few_intervals_give_no_prediction() -> None:
    mnvs = _burns_at([0, 10, 22][: _MIN_INTERVALS_FOR_PREDICTION])
    assert _next_manoeuvre(mnvs, burn_time=lambda m: m.epoch) == (None, None)


def test_the_intervals_run_between_burns_not_after_sets() -> None:
    # Burns every 10 days, but the after-sets land 0, 3, 0, 3 days late.
    mnvs = [dataclasses.replace(m, epoch=m.epoch + timedelta(days=3 * (i % 2)))
            for i, m in enumerate(_burns_at([0, 10, 20, 30]))]
    burn = {id(m): _BURN + timedelta(days=10 * i) for i, m in enumerate(mnvs)}
    est, unc = _next_manoeuvre(mnvs, burn_time=lambda m: burn[id(m)])
    assert unc == 0.0
    assert est == (_BURN + timedelta(days=40)).strftime("%Y-%m-%d %H:%M UTC")
