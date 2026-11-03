"""Each time of closest approach carries an uncertainty (SPC-118).

A slow approach turns a small position error into a large error in time: 0.044 km moved the GEO reference TCA by
1,951 s between propagators. The TCA's uncertainty is the element sets' position error at the TCA, both objects
combined in quadrature (spectre/astro/along_track.py's model), over the closing speed, with all of the error
taken along the approach, so it errs wide. There is none when the closing speed is rounding noise, when it would
be wider than the span searched, or when the smallest separation is at an edge of the search.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta

import pytest

from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import elset_position_error_km
from spectre.astro.monte_carlo import ManoeuvreHypothesis, SeparationWindow, elset_state, run_separation_series
from spectre.domain import decision
from spectre.domain.decision import ScenarioBinding, ScenarioResult, evaluate_scenario
from spectre.domain.decision_figures import TCA_AT_EDGE, TcaUncertainty, tca_uncertainty
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit.test_decision_computed import _NO_ACTION, _cells, _computed, _geo
from tests.unit.test_decision_sampled import _bound, _Fake, _page, _series


@pytest.fixture(scope="module")
def geo() -> ScenarioResult:
    return _computed(binding=ScenarioBinding(red=_geo("red"), blue=_geo("blue")), horizon_hours=48.0)


class TestAComputedCell:
    def test_a_computed_geo_cell_carries_its_tca_uncertainty(self, geo: ScenarioResult) -> None:
        """8: 4.662 km over 1.094 m/s, about 1.2 h."""
        tca = _cells(geo, _NO_ACTION)[0].tca_uncertainty
        assert tca is not None
        assert tca.position_error_km == pytest.approx(4.662, abs=0.001)
        assert tca.closing_speed_km_s * 1000.0 == pytest.approx(1.094, abs=0.001)
        assert tca.sigma_s == pytest.approx(4259.5, abs=1.0)

    def test_the_line_prints_at_its_scale(self, geo: ScenarioResult) -> None:
        """9: GEO to the tenth of an hour, with whole hours after the epoch; the plane change to the second."""
        geo_line = _cells(geo, _NO_ACTION)[0].ca_computed_line
        assert geo_line == (
            "Computed: 30.0 km at 2026-10-18 19:07 UTC ± 1.2 h, 31 h after the scenario epoch; SGP4, no burn."
        )
        pc_line = _cells(_computed(), _NO_ACTION)[0].ca_computed_line
        assert pc_line == (
            "Computed: 10.4 km at 2026-10-17 12:24 UTC ± 4 s, 0.39 h after the scenario epoch; SGP4, no burn."
        )
        assert pc_line in _page(_computed())

    def test_the_hover_says_what_it_rests_on(self, geo: ScenarioResult) -> None:
        tca = _cells(geo, _NO_ACTION)[0].tca_uncertainty
        assert tca is not None
        assert tca.title == (
            "TCA known to ± 1.2 h: element-set error of 4.7 km at the TCA, both objects combined in quadrature (the "
            "sweep's 1 km at epoch plus 2 km a day in LEO, 2 km plus 1 km a day at GEO), over a closing speed of "
            "1.1 m/s. All of the error is taken along the approach, so it errs wide; our burn's execution error is "
            "not in it."
        )

    def test_an_edge_minimum_carries_no_uncertainty(self) -> None:
        """11: over 24 h GEO drift-in is still closing at the end of the search."""
        result = _computed(binding=ScenarioBinding(red=_geo("red"), blue=_geo("blue")), horizon_hours=24.0)
        tca = _cells(result, _NO_ACTION)[0].tca_uncertainty
        assert tca is not None
        assert tca.sigma_s is None
        assert tca.title == TCA_AT_EDGE == (
            "No TCA uncertainty: the smallest separation is at the edge of the search, not an encounter."
        )

    def test_a_lookup_cell_carries_none(self) -> None:
        cell = _cells(_computed(), 0)[0]
        assert cell.tca_uncertainty is None


class TestTheFigure:
    def test_an_uncertainty_wider_than_the_span_says_so(self) -> None:
        """14: 1.5 km at 1 mm/s is 1,500 s, wider than a 1,000 s search."""
        tca = tca_uncertainty(1.5, 1e-6, 1000.0, at_edge=False)
        assert tca.sigma_s is None
        assert tca.title == (
            "TCA not known to better than the 0.3 h searched: the objects close at 0.00 m/s, too slowly to fix the "
            "time from a 1.5 km position error."
        )
        assert tca.pm == "± more than the 0.3 h searched"
        assert tca.hours(0.3919) == "0"

    def test_a_tca_too_slow_to_fix_reads_no_finer_than_its_span(self) -> None:
        """A 4.7 km error at 0.02 m/s over a 48 h search: the time is printed to the hour, with the span as its ±."""
        tca = tca_uncertainty(4.7, 0.00002, 172800.0, at_edge=False)
        assert tca.sigma_s is None
        assert tca.pm == "± more than the 48.0 h searched"
        assert tca.hours(31.4237) == "31"

    def test_a_tca_with_no_uncertainty_for_another_reason_keeps_two_decimals(self) -> None:
        """At an edge, or with no recorded speed, the time is the search's own, not a slow approach's."""
        assert tca_uncertainty(4.7, 0.00002, 172800.0, at_edge=True).hours(31.4237) == "31.42"
        assert tca_uncertainty(4.7, math.nan, 172800.0, at_edge=False).hours(31.4237) == "31.42"
        assert tca_uncertainty(4.7, math.nan, 172800.0, at_edge=False).pm == ""

    @pytest.mark.parametrize(
        ("sigma", "pm", "hours"),
        [(0.4, "± under 1 s", "0.39"), (3.7, "± 4 s", "0.39"), (59.0, "± 59 s", "0.39"),
         (179.0, "± 3 min", "0.39"), (180.0, "± 3 min", "0.4"), (420.0, "± 7 min", "0.4"),
         (1799.0, "± 30 min", "0.4"), (1800.0, "± 30 min", "0"), (4259.5, "± 1.2 h", "0")],
    )
    def test_the_ladder(self, sigma: float, pm: str, hours: str) -> None:
        tca = TcaUncertainty(sigma, 1.0, 1.0 / sigma, 1e9, at_edge=False)
        assert tca.pm == pm
        assert tca.hours(0.3919) == hours

    def test_the_element_set_error_grows_with_age(self) -> None:
        tle = PLANE_CHANGE.red_tle
        assert elset_position_error_km(tle, EPOCH, EPOCH) == pytest.approx(1.0)
        assert elset_position_error_km(tle, EPOCH, EPOCH + timedelta(days=1.5)) == pytest.approx(4.0)


class TestASampledCell:
    def test_it_uses_the_speed_of_the_sample_that_sets_its_tca(self) -> None:
        """12: the earliest sample at or below P5 is the second, 2.5 km at 1,200 s; it closes at 0.5 km/s."""

        class _WithSpeeds(_Fake):
            def __call__(self, hypothesis: ManoeuvreHypothesis, blue: object, window: SeparationWindow) -> object:
                series = _series(window)
                speeds = tuple(0.5 if k == 1 else 0.01 for k in range(len(series.approaches)))
                return dataclasses.replace(series, closing_speeds_km_s=speeds)

        result = evaluate_scenario(_bound(), sampler=_WithSpeeds())
        cell = result.outcome_matrix[0][0]
        assert cell.tca_uncertainty is not None
        assert cell.tca_uncertainty.closing_speed_km_s == 0.5
        assert cell.tca_uncertainty.sigma_s == pytest.approx(cell.tca_uncertainty.position_error_km / 0.5)
        assert cell.ca_sampled_tca_line == (
            "Earliest TCA at or below P5: 2026-10-17 12:20 UTC ± 3 s, 0.33 h after the scenario epoch. Across "
            "samples the TCA runs from 0.57 h (P5) to 0.83 h (P95)."
        )
        assert cell.ca_sampled_tca_line in _page(result)

    def test_a_series_without_speeds_has_no_uncertainty(self) -> None:
        cell = evaluate_scenario(_bound(), sampler=_Fake()).outcome_matrix[0][0]
        assert cell.tca_uncertainty is not None
        assert cell.tca_uncertainty.sigma_s is None
        assert math.isnan(cell.tca_uncertainty.closing_speed_km_s)

    def test_the_series_records_each_samples_closing_speed(self) -> None:
        """13: the plane change's nominal sample crosses at 394.0 m/s."""
        blue, red = elset_state(PLANE_CHANGE.blue_tle, EPOCH), elset_state(PLANE_CHANGE.red_tle, EPOCH)
        assert blue is not None and red is not None
        hypothesis = ManoeuvreHypothesis(
            epoch_utc=EPOCH, delta_v_magnitude_km_s=0.0, delta_v_radial=0.0, delta_v_in_track=0.0,
            delta_v_cross_track=0.0, pre_manoeuvre_state_eci_km=red.state_eci_km,
            delta_v_magnitude_1sigma_km_s=0.0, delta_v_pointing_1sigma_deg=0.0, epoch_1sigma_seconds=0.0,
            bstar_post=0.0, bstar_1sigma=0.0, n_samples=1,
        )
        series = run_separation_series(hypothesis, blue, SeparationWindow(EPOCH, 3600.0))
        assert len(series.closing_speeds_km_s) == len(series.approaches) == 1
        assert series.closing_speeds_km_s[0] * 1000.0 == pytest.approx(394.0, abs=0.5)
        assert series.earliest_at_or_below_p5_index == 0

    def test_the_speeds_run_parallel_to_the_approaches(self) -> None:
        series = _series(SeparationWindow(EPOCH, 3600.0))
        with pytest.raises(ValueError, match="closing speed"):
            dataclasses.replace(series, closing_speeds_km_s=(0.1,))


def test_the_helper_combines_both_sides_in_quadrature() -> None:
    binding = ScenarioBinding(red=_geo("red"), blue=_geo("blue"))
    approach = ClosestApproach(30.0, 86400.0, at_window_edge=False)
    tca = decision._tca_uncertainty(binding, EPOCH, approach, 0.001, 172800.0)
    assert tca.position_error_km == pytest.approx(math.hypot(3.0, 3.0))
    assert tca.sigma_s == pytest.approx(math.hypot(3.0, 3.0) / 0.001)
