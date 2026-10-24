"""Photometry Welch test checked against scipy.

Audit F-101: the Welch-Satterthwaite guard compared a dimensional quantity
(mag^4) with an absolute 1e-15, so precise or large samples collapsed to one
degree of freedom, a Cauchy tail: sigma 0.05 mag with 3,000 per group gives
a denominator near 2.3e-16.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from spectre.astro.photometry import _t_test_two_sample


def test_welch_p_value_matches_scipy_for_large_precise_samples() -> None:
    rng = np.random.default_rng(7)
    a = rng.normal(0.0, 0.05, 3000)
    b = rng.normal(0.004, 0.05, 3000)
    _, p = _t_test_two_sample(list(a), list(b))
    expected = stats.ttest_ind(a, b, equal_var=False).pvalue
    assert p == pytest.approx(expected, abs=1e-4)
