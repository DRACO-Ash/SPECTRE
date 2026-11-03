"""A sampled closest approach converges when its percentiles are known well enough for what the operator does (SPC-117).

The operator reads P5 to answer "can it reach one of mine", a question of
magnitude. The 1 km absolute tolerance refused most burns already made, the
"something moved" case, where the misses are hundreds of km and a half-width
of a few km changes no answer. The tolerance is now 1 km, or 5 % of P5 where
that is larger: below 20 km, every close approach the operator would act on
is held exactly as tightly as before, and the score moves by at most
w_ca x half-width / 50,000.

Measured at seed 42 (the archetypes' default), the reference element sets in
tests/unit/_decision_reference.py, the burn 0.25 h into the window unless
stated, the venv at cd44cb5:

* coplanar_leo Orbit Raise, 100 samples over 1 h: P5 153.25 km, half-width
  1.758 km against a tolerance of 7.66 km. Refused at 1 km; converged now.
* geo_drift_in Intercept, 100 samples over 6 h: P5 7.16 km, half-width
  3.939 km against 1 km. Genuinely unknown, and still refused.
* plane_change Orbit Raise burning 2 h before a 1 h window, 100 samples: P5
  855.86 km, half-width 11.338 km against 42.79 km; every sample is closest
  at the window start, already opening.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from datetime import timedelta

import pytest

from spectre.astro.monte_carlo import (
    CONVERGENCE_TOLERANCE_KM,
    MISS_TOLERANCE_FRACTION,
    SeparationSeries,
    SeparationWindow,
    check_convergence,
    elset_state,
    miss_tolerance_km,
    run_separation_series,
)
from spectre.domain.decision import (
    CONVERGED_MEANS,
    AdversaryHypothesis,
    BoundElset,
    PreManoeuvreState,
    ScenarioBinding,
    evaluate_scenario,
)
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE, ReferenceCase
from tests.unit.test_decision_sampled import _LOOKUPS, _bound, _cells, _Fake, _page, _scenario


def _series(case: ReferenceCase, archetype: str, n: int, hours: float) -> SeparationSeries:
    """*archetype* burning 0.25 h into a window of *hours* from EPOCH, from red's state there, at seed 42."""
    burn = EPOCH + timedelta(hours=0.25)
    red, blue = elset_state(case.red_tle, burn), elset_state(case.blue_tle, EPOCH)
    assert red is not None and blue is not None
    carried = AdversaryHypothesis.from_archetype(archetype, PreManoeuvreState(burn, tuple(red.state_eci_km)), n_samples=n)
    assert carried.hypothesis.random_seed == 42
    return run_separation_series(carried.hypothesis, blue, SeparationWindow(EPOCH, hours * 3600.0))


class TestTheTolerance:
    @pytest.mark.parametrize(
        ("p5_km", "tolerance_km"),
        [(10.0, 1.0), (20.0, 1.0), (100.0, 5.0), (855.86, 42.793), (0.0, 1.0), (math.nan, 1.0), (math.inf, 1.0)],
    )
    def test_it_is_1_km_or_5_percent_of_p5_where_that_is_larger(self, p5_km: float, tolerance_km: float) -> None:
        """C1: a P5 that is not finite gives the floor, never a tolerance that admits anything."""
        assert miss_tolerance_km(p5_km) == pytest.approx(tolerance_km)
        assert MISS_TOLERANCE_FRACTION == 0.05
        assert CONVERGENCE_TOLERANCE_KM == 1.0

    def test_the_series_states_the_tolerance_it_was_held_to(self) -> None:
        """A series with no tolerance given is held to the 1 km floor, as before SPC-117."""
        fields = SeparationSeries.__dataclass_fields__
        assert fields["tolerance_km"].default == CONVERGENCE_TOLERANCE_KM
        assert list(fields).index("tolerance_km") == list(fields).index("propagator") - 1


class TestOnTheMeasuredCases:
    def test_coplanar_orbit_raise_converges_on_the_relative_tolerance(self) -> None:
        """C2: half-width 1.76 km against 7.66 km, 5 % of a 153.25 km P5; at 1 km it was refused."""
        series = _series(COPLANAR_LEO, "orbit_raise", 100, 1.0)
        assert series.miss_km_p5 == pytest.approx(153.25, abs=0.05)
        assert series.percentile_half_width_km == pytest.approx(1.758, abs=0.01)
        assert series.tolerance_km == pytest.approx(0.05 * series.miss_km_p5)
        assert series.percentile_half_width_km > CONVERGENCE_TOLERANCE_KM
        assert series.converged is True

    def test_geo_intercept_stays_refused(self) -> None:
        """C3, a regression pin that passed before SPC-117 by design: 3.94 km against the 1 km floor."""
        series = _series(GEO_DRIFT_IN, "intercept_approach", 100, 6.0)
        assert series.miss_km_p5 == pytest.approx(7.16, abs=0.05)
        assert series.percentile_half_width_km == pytest.approx(3.939, abs=0.01)
        assert series.tolerance_km == CONVERGENCE_TOLERANCE_KM
        assert series.converged is False

    def test_a_burn_two_hours_before_the_window_is_sampled_and_says_it_was_already_opening(self) -> None:
        """C7: the "something moved" case. Orbit Raise burned 2 h before a 1 h window, red fitted at the burn.

        P5 855.86 km known to within 11.34 km, against 42.79 km. Every sample is closest at the window's first
        instant, so the cell says P5 is the separation then, not an encounter.
        """
        start = EPOCH + timedelta(hours=2)
        red_then = elset_state(PLANE_CHANGE.red_tle, EPOCH)
        assert red_then is not None
        carried = AdversaryHypothesis.from_archetype(
            "orbit_raise", PreManoeuvreState(EPOCH, tuple(red_then.state_eci_km)), n_samples=100,
        )

        def bound(side: str, tle: str) -> BoundElset:
            return BoundElset(
                side=side, name=side, stk_name=side.upper(), satno=None, tle=tle, data_mode="REAL",  # type: ignore[arg-type]
                epoch=EPOCH, age_hours=2.0, limit_hours=24.0,
            )

        scenario = _scenario({0: carried}, binding=ScenarioBinding(
            red=bound("red", PLANE_CHANGE.red_tle), blue=bound("blue", PLANE_CHANGE.blue_tle),
        ))
        scenario.epoch_utc = start
        cell = _cells(evaluate_scenario(scenario), 0)[0]
        assert cell.ca_refusal is None
        assert cell.ca_percentiles is not None
        assert cell.ca_percentiles[5] == pytest.approx(855.86, abs=0.1)
        assert cell.ca_half_width_km == pytest.approx(11.34, abs=0.05)
        assert str(cell.ca_caveat).endswith(
            " In 100 of 100 samples the objects were already opening when the window began, so the closest approach "
            "was before it."
        )


class TestWhatThePageSays:
    def test_the_unconverged_refusal_names_the_tolerance_it_missed(self) -> None:
        """C4: P5 100 km gives a 5 km tolerance; a 6.2 km half-width misses it."""
        fake = _Fake(half_width=6.2, converged=False)

        def wide(*args: object) -> SeparationSeries:
            series = fake(*args)  # type: ignore[arg-type]
            return dataclasses.replace(
                series, miss_km_p5=100.0, miss_km_p50=120.0, miss_km_p95=150.0, tolerance_km=5.0,
            )

        cell = _cells(evaluate_scenario(_bound(), sampler=wide), 0)[0]
        assert cell.ca_refusal == (
            "Not sampled: P5, P50 and P95 are known only to within 6.2 km, wider than the 5.0 km this miss needs (1 km, "
            "or 5 % of P5 where that is larger). Take more samples, with a shorter horizon if that goes over the "
            "4,800 sample-hour cap." + _LOOKUPS
        )

    def test_converged_means_is_on_the_sampled_page(self) -> None:
        """C5."""
        assert CONVERGED_MEANS == (
            "Converged means P5, P50 and P95 are each known to within 1 km, or to within 5 % of P5 where that is "
            "larger (95 % bootstrap): more samples would move them by less than that. Whether a move that size "
            "matters depends on how close is too close for your asset, which this page is not told. It says nothing "
            "about element-set error or the hypothesis being wrong."
        )
        assert "reach" not in CONVERGED_MEANS
        sampled = evaluate_scenario(_bound(), sampler=_Fake())
        assert sampled.converged_means == CONVERGED_MEANS
        assert CONVERGED_MEANS in _page(sampled)
        plain = evaluate_scenario(_scenario())
        assert plain.converged_means is None
        assert "Converged means" not in _page(plain)

    def test_the_band_carries_its_half_width(self) -> None:
        """C6."""
        cell = _cells(evaluate_scenario(_bound(), sampler=_Fake()), 0)[0]
        assert cell.ca_band == (
            "Sampled: P5 3.0 km to P95 20.0 km, median 8.0 km, each known to within 0.4 km, 50 samples."
        )

    def test_the_monte_carlo_engine_keeps_its_own_1_km_check(self) -> None:
        """run_monte_carlo's SMA percentiles are not the miss the operator reads, so their check stays absolute."""
        assert inspect.signature(check_convergence).parameters["tolerance_km"].default == 1.0
