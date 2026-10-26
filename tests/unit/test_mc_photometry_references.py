"""Monte Carlo and photometry checked against independent references (audit F-109).

These suites tested shape, ordering and bounds; nothing pinned the physics or
the statistics to a reference, so five numerical defects passed them. The
Welch test against scipy for large samples (test_photometry_statistics), the
drag term against an independent decay (test_monte_carlo_drag) and the
hypothesis builder (test_monte_carlo_direction) are pinned elsewhere. This
module adds the rest:

● the J2 equations of motion against the secular node rate
  -3/2 n J2 (R/p)^2 cos i (Vallado eq. 9-41);
● the regularised incomplete beta against scipy.special.betainc;
● the Welch p-value against scipy on small samples, and a table value;
● the all-diverged path of the Monte Carlo run.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import special, stats
from scipy.integrate import solve_ivp

from spectre.astro import monte_carlo
from spectre.astro.constants import J2_EARTH, MU_EARTH, R_EARTH
from spectre.astro.photometry import _regularised_incomplete_beta, _t_test_two_sample
from tests.unit.test_monte_carlo import _basic_hypothesis


def _node_deg(state: np.ndarray) -> float:
    h = np.cross(state[:3], state[3:])
    return math.degrees(math.atan2(h[0], -h[1]))


def test_the_j2_equations_regress_the_node_at_the_secular_rate() -> None:
    # 900 km circular, 51.6 degrees: above the drag cut-off, so J2 alone.
    a, inc = R_EARTH + 900.0, math.radians(51.6)
    v = math.sqrt(MU_EARTH / a)
    state = np.array([a, 0.0, 0.0, 0.0, v * math.cos(inc), v * math.sin(inc)])
    period = 2 * math.pi * math.sqrt(a**3 / MU_EARTH)
    span = 48 * 3600.0
    first = np.linspace(0.0, period, 200)
    last = np.linspace(span - period, span, 200)
    sol = solve_ivp(monte_carlo._j2_drag_ode, (0.0, span), state, method="DOP853", rtol=1e-10, atol=1e-12,
                    t_eval=np.concatenate([first, last]), args=(0.0, 0.0))
    nodes = np.unwrap(np.radians([_node_deg(sol.y[:, k]) for k in range(sol.y.shape[1])]))
    # Orbit-averaged nodes, so the short-period J2 terms cancel.
    drift = math.degrees(nodes[200:].mean() - nodes[:200].mean()) / ((span - period) / 86400.0)

    n = math.sqrt(MU_EARTH / a**3)
    analytic = math.degrees(-1.5 * n * J2_EARTH * (R_EARTH / a) ** 2 * math.cos(inc)) * 86400.0
    assert drift == pytest.approx(analytic, rel=0.01)


@pytest.mark.parametrize(("x", "a", "b"), [
    (0.1, 0.5, 0.5), (0.5, 2.0, 3.0), (0.9, 5.0, 1.5), (0.3, 10.0, 10.0), (0.75, 0.5, 20.0), (0.02, 3.0, 0.5),
])
def test_the_incomplete_beta_matches_scipy(x: float, a: float, b: float) -> None:
    # The continued fraction stops at 3e-7 a term; the result holds to 1e-9.
    assert _regularised_incomplete_beta(x, a, b) == pytest.approx(float(special.betainc(a, b, x)), abs=1e-9)


@pytest.mark.parametrize("seed", range(6))
def test_welch_matches_scipy_on_small_samples(seed: int) -> None:
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0, 0.1, 6 + seed)
    b = rng.normal(0.05, 0.2, 5 + 2 * seed)
    t, p = _t_test_two_sample(list(a), list(b))
    expected = stats.ttest_ind(a, b, equal_var=False)
    assert abs(t) == pytest.approx(abs(float(expected.statistic)), rel=1e-9)
    assert p == pytest.approx(float(expected.pvalue), abs=1e-5)


def test_the_t_table_value_two_tailed() -> None:
    # Student's t, 10 degrees of freedom: t = 2.228 sits at p = 0.05, two-tailed.
    # Two equal groups of 6 with equal variance give Welch df = 10 exactly.
    base = np.array([-1.0, -0.6, -0.2, 0.2, 0.6, 1.0])
    s = float(np.std(base, ddof=1))
    shift = 2.228 * s * math.sqrt(2.0 / 6.0)
    _, p = _t_test_two_sample(list(base), list(base + shift))
    assert p == pytest.approx(0.05, abs=1e-4)


def test_a_run_where_every_sample_diverges_reports_the_starting_orbit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monte_carlo, "propagate_single_sample", lambda *_a, **_k: None)
    hypothesis = _basic_hypothesis(n_samples=20)
    result = monte_carlo.run_monte_carlo(hypothesis, prediction_horizon_hours=1.0, max_workers=1)
    sma0 = monte_carlo._state_to_keplerian(hypothesis.pre_manoeuvre_state_eci_km[:3],
                                            hypothesis.pre_manoeuvre_state_eci_km[3:])[0]
    assert result.n_samples_converged == 0
    assert result.converged is False
    assert result.sma_km_p5 == result.sma_km_p95 == pytest.approx(sma0)
    assert result.sma_km_std == 0.0
