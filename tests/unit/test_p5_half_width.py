"""P5 is labelled with its own half-width; convergence is named as the widest of three (SPC-213, evaluation F-26).

The sampled basis note read "P5 of n sampled misses, known to within h km", where h was the widest of the P5, P50
and P95 bootstrap half-widths, the figure convergence is judged on. With a long upper tail that overstates how
closely P5 is known many times over (18 to 45 times in the evaluation's probe P-11). The note now gives P5 its own
half-width, from the same bootstrap resamples, and names the convergence figure apart, as the widest of the three.
Convergence, and so every refusal and every figure, is unchanged.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from spectre.astro import monte_carlo
from spectre.astro.monte_carlo import SeparationSeries, SeparationWindow
from spectre.domain import decision

#: 45 misses packed between 3 and 3.45 km and a tail of 5 from 50 to 450 km: P5 is tight, P95 is not.
_SKEWED = [3.0 + 0.01 * k for k in range(45)] + [50.0 + 100.0 * k for k in range(5)]
_SEED = 42


def _series(misses: list[float]) -> SeparationSeries:
    """A series over *misses* with the statistics the engine works out from them."""
    window = SeparationWindow(start_utc=datetime(2026, 10, 17, 12, tzinfo=UTC), span_s=3600.0)
    stats = monte_carlo._miss_stats(misses, _SEED)
    return SeparationSeries(
        window=window, approaches=(), n_samples_run=len(misses), n_failed=0, n_reentered=0,
        miss_km_p5=stats.p5, miss_km_p50=stats.p50, miss_km_p95=stats.p95, miss_km_std=stats.std,
        percentile_half_width_km=stats.half_width_km, converged=stats.converged, random_seed=_SEED,
        integration_s=0.0, wall_time_seconds=0.0, tolerance_km=stats.tolerance_km,
        p5_half_width_km=stats.p5_half_width_km,
    )


class TestEachPercentileHasItsOwnHalfWidth:
    def test_the_widest_is_unchanged(self) -> None:
        """The convergence figure is the same draw's widest, so no refusal and no figure moves."""
        widths = monte_carlo.percentile_half_widths_km(_SKEWED, seed=_SEED)
        assert len(widths) == 3
        assert max(widths) == monte_carlo.percentile_half_width_km(_SKEWED, seed=_SEED)

    def test_p5_is_known_far_more_closely_than_the_widest_here(self) -> None:
        p5, p50, p95 = monte_carlo.percentile_half_widths_km(_SKEWED, seed=_SEED)
        assert p5 < 0.1
        assert p95 > 10.0
        assert p50 < p95

    def test_below_fifty_samples_none_is_known(self) -> None:
        assert monte_carlo.percentile_half_widths_km([1.0] * 49) == (math.inf, math.inf, math.inf)

    def test_the_miss_statistics_carry_p5s_own(self) -> None:
        stats = monte_carlo._miss_stats(_SKEWED, _SEED)
        p5, _, p95 = monte_carlo.percentile_half_widths_km(_SKEWED, seed=_SEED)
        assert stats.p5_half_width_km == p5
        assert stats.half_width_km == p95
        assert not stats.converged, "convergence still reads the widest"


class TestTheSampledNote:
    def test_p5_is_labelled_with_its_own_half_width_not_the_widest(self) -> None:
        series = _series(_SKEWED)
        assert series.p5_half_width_km < series.percentile_half_width_km / 100.0
        note = decision._sampled_bases(series, 1.0).closest_approach_km.note
        assert note.startswith(
            f"P5 of 0 sampled misses, known to within {series.p5_half_width_km:.2f} km (95 % bootstrap): 1 in 20 "
            "samples came closer. Convergence is judged on the widest of the P5, P50 and P95 half-widths, "
            f"{series.percentile_half_width_km:.2f} km. "
        )

    def test_a_series_after_our_burn_carries_p5s_own_too(self) -> None:
        stats = monte_carlo._miss_stats(_SKEWED, _SEED)
        after = monte_carlo.BurnSeries(
            burn=monte_carlo.BlueBurn(at_s=0.0, delta_v_ric_km_s=(0.0, 0.0, 0.0)), approaches=(),
            closing_speeds_km_s=(), n_failed=0, stats=stats,
        )
        burnt = decision._burnt_series(_series([5.0] * 50), after)
        assert (burnt.p5_half_width_km, burnt.percentile_half_width_km) == (stats.p5_half_width_km,
                                                                          stats.half_width_km)

    def test_the_engines_own_series_carries_p5s_own(self) -> None:
        """Through _series_of, as every separation series is built."""
        window = SeparationWindow(start_utc=datetime(2026, 10, 17, 12, tzinfo=UTC), span_s=3600.0)
        outcomes = [
            monte_carlo.Sampled(monte_carlo.ClosestApproach(m, 10.0, False), 0.1) for m in _SKEWED
        ]
        series = monte_carlo._series_of(window, outcomes, monte_carlo._Ran(seed=_SEED, started=0.0), integration_s=0.0)
        p5, _, p95 = monte_carlo.percentile_half_widths_km(_SKEWED, seed=_SEED)
        assert (series.p5_half_width_km, series.percentile_half_width_km) == (p5, p95)


class TestANonFiniteMissStillPropagates:
    """V0.40 review: the widest was np.max, which carries a NaN wherever it falls; Python's max() keeps whatever comes
    first, so a NaN half-width that was not P5's read as the next widest and could pass convergence."""

    _WITH_INF = [1.0 + 0.01 * k for k in range(59)] + [math.inf]

    def test_a_nan_half_width_that_is_not_first_makes_the_widest_nan(self) -> None:
        p5, p50, p95 = monte_carlo.percentile_half_widths_km(self._WITH_INF, seed=_SEED)
        assert math.isfinite(p5) and math.isfinite(p50) and math.isnan(p95)
        assert math.isnan(monte_carlo.percentile_half_width_km(self._WITH_INF, seed=_SEED))

    def test_such_a_series_has_not_converged(self) -> None:
        stats = monte_carlo._miss_stats(self._WITH_INF, _SEED)
        assert math.isnan(stats.half_width_km)
        assert stats.converged is False
        assert math.isfinite(stats.p5_half_width_km)
