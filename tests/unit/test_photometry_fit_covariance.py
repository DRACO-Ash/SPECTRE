"""The photometric fit's covariance is res_var x (X^T X)^-1, checked against numpy.

Audit F-102: the fit stored res_var / diag(X^T X), which is not a covariance;
over tens of degrees of phase the columns 1, x, x^2 are strongly correlated
and that understates the coefficient variances by orders of magnitude.
"""

from __future__ import annotations

import numpy as np

from spectre.astro.photometry import _fit_least_squares_quadratic


def test_the_fit_covariance_is_the_inverse_normal_matrix() -> None:
    rng = np.random.default_rng(3)
    phases = np.linspace(20.0, 80.0, 40)
    mags = 5.0 + 0.02 * phases + 1e-4 * phases**2 + rng.normal(0.0, 0.05, phases.size)
    *coeffs, cov = _fit_least_squares_quadratic(list(phases), list(mags))

    x = np.column_stack([np.ones_like(phases), phases, phases**2])
    residuals = mags - x @ np.array(coeffs)
    expected = residuals @ residuals / (phases.size - 3) * np.linalg.inv(x.T @ x)
    assert np.allclose(np.array(cov), expected, rtol=1e-6, atol=0.0)
