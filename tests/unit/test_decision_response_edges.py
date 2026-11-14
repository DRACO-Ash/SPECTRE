"""What our burn says when it cannot be sized or applied, and the checks that keep it honest (SPC-121).

The companion of test_decision_response.py: every refusal names why in the cell and leaves our delta-V a lookup,
and every invariant refuses a cell that would claim more than it earned. Fakes stand in for the propagator where
the rule is the domain's, not the physics.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from spectre.astro import response_burn
from spectre.astro.elset_approach import ElsetFailure
from spectre.astro.monte_carlo import (
    BlueBurn,
    BurnSeries,
    ManoeuvreHypothesis,
    MissStats,
    ReenteredError,
    SeparationWindow,
)
from spectre.astro.response_burn import (
    RESPONSE_PROPAGATOR,
    BurnAxis,
    BurnRefusal,
    BurnRequest,
    Rk45Plan,
    SizedBurn,
    elset_response_plan,
    hypothesis_response_plan,
)
from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeMetrics,
    RunControl,
    Scenario,
    ScenarioBinding,
    evaluate_scenario,
    needs_a_run,
)
from spectre.domain.decision_figures import ResponseBurnSpec, ResponseFigure
from spectre.domain.provenance import Basis, FigureBasis
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, GEO_DRIFT_IN, PLANE_CHANGE
from tests.unit.test_decision_computed import _geo
from tests.unit.test_decision_response import (
    _AVOID,
    _HOLD,
    _avoid,
    _cell,
    _computed_scenario,
    _hold,
    _sampled_scenario,
    _sized_stub,
    _WithBurns,
)
from tests.unit.test_decision_sampled import _elset, _evasive, _never, _series, _steady

_LOOKUP_DV = " This cell's delta-V is a lookup."


def _stub_plan(monkeypatch: pytest.MonkeyPatch, result: SizedBurn | BurnRefusal | None) -> None:
    sized = None if result is None else (result,)
    monkeypatch.setattr(decision, "hypothesis_response_plan", lambda *_a, **_k: sized)


class TestTheSpecIsChecked:
    def test_a_burn_must_be_a_spec(self) -> None:
        with pytest.raises(TypeError, match="ResponseBurnSpec"):
            FriendlyResponse("F1", "Avoid", ActionType.MANOEUVRE, 0.3, 0.8, 0.0, burn=20.0)  # type: ignore[arg-type]

    def test_its_axis_must_be_listed(self) -> None:
        with pytest.raises(ValueError, match="axis"):
            _avoid(ResponseBurnSpec(20.0, axis="sideways"))  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def burnt() -> OutcomeMetrics:
    return _cell(evaluate_scenario(_computed_scenario(_hold(), _avoid())))


class TestTheInvariants:
    def test_a_burn_never_rests_on_a_lookup_closest_approach(self, burnt: OutcomeMetrics) -> None:
        bases = dataclasses.replace(
            burnt.figure_bases, closest_approach_km=FigureBasis(Basis.LOOKUP, "n"),
            time_to_closest_hours=FigureBasis(Basis.LOOKUP, "n"),
        )
        with pytest.raises(ValueError, match="never a lookup"):
            dataclasses.replace(burnt, figure_bases=bases, ca_computed=None, tca_uncertainty=None)

    def test_a_lookup_cell_carries_no_tca_uncertainty(self, burnt: OutcomeMetrics) -> None:
        lookup = evaluate_scenario(dataclasses.replace(_computed_scenario(_hold()), binding=None)).outcome_matrix[0][0]
        with pytest.raises(ValueError, match="tca_uncertainty"):
            dataclasses.replace(lookup, tca_uncertainty=burnt.tca_uncertainty)

    def test_a_computed_cell_carries_no_sampled_tca(self, burnt: OutcomeMetrics) -> None:
        sampled_tca = decision.SampledTca(EPOCH, 0.1, 0.1, 0.2)
        with pytest.raises(ValueError, match="ca_sampled_tca"):
            dataclasses.replace(burnt, ca_sampled_tca=sampled_tca)
        assert burnt.ca_sampled_tca_line is None
        assert burnt.tca_title is not None and burnt.tca_title.startswith("TCA known to ± ")


class TestComputedRefusals:
    def test_a_failed_rk45_pair_refuses_every_burn_and_keeps_sgp4(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision, "elset_response_plan", lambda *_a, **_k: ElsetFailure("red", "propagation"))
        result = evaluate_scenario(_computed_scenario(_hold(), _avoid()))
        cell = _cell(result)
        assert cell.ca_computed is not None and cell.ca_computed.propagator != RESPONSE_PROPAGATOR
        assert cell.response_refusal == (
            "Our burn is not sized: the blue asset's arc after it could not be propagated." + _LOOKUP_DV
        )
        assert result.rk45_reference is None and result.rk45_reference_line is None

    def test_a_reentering_burn_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        refused = Rk45Plan(_sized_stub(None).before, (BurnRefusal("1", "reentered", 2),))
        monkeypatch.setattr(decision, "elset_response_plan", lambda *_a, **_k: refused)
        cell = _cell(evaluate_scenario(_computed_scenario(_hold(), _avoid())))
        assert cell.response_refusal == (
            "Our burn is not sized: the blue asset's arc after it could not be propagated, since it re-entered below "
            "100 km." + _LOOKUP_DV
        )

    @staticmethod
    def _five_burns() -> list[FriendlyResponse]:
        return [_hold(), *(
            FriendlyResponse(f"F{k}", f"Avoid {k}", ActionType.MANOEUVRE, 0.3, 0.8, 0.0, burn=ResponseBurnSpec(100.0))
            for k in range(1, 6)
        )]

    def test_geo_over_72_h_with_five_burns_fits_the_cap(self) -> None:
        """Risk 5: (2 + 16 x 5) x 72.15 = 5,916.3 sample-hours. Refused under the 120 s budget's 4,800, it fits
        the 300 s budget's cap (the owner's ruling of 2026-11-05, SPC-178), so its burns are sized in a job."""
        scenario = Scenario(
            name="GEO", epoch_utc=EPOCH,
            adversary_actions=[AdversaryAction("A0", "Drift", ActionType.NO_ACTION, 0.5, 0.7)],
            friendly_responses=self._five_burns(), horizon_hours=72.0,
            binding=ScenarioBinding(red=_geo("red"), blue=_geo("blue")),
        )
        assert decision._turn_one_cost_h(scenario) == pytest.approx(5916.3)
        assert decision._turn_one_cost_h(scenario) <= decision.MAX_SAMPLE_HOURS
        assert needs_a_run(scenario)

    def test_burns_to_size_beside_a_sampled_row_over_the_cap_are_refused_on_it(self) -> None:
        """A computed row and a sampled row of 500 over 9 h, with five burns: the sampled row's floor is
        500 x 9.15 + 5 x (150 x 9.15 + 16 x 9.15 + 9) = 12,214.5, charged twice for the second seed its convergence
        is checked on (SPC-224), 24,429, and the computed rows' sizing (2 + 80) x 9.15 = 750.3 more, so 25,180. The
        computed cells keep their SGP4 figure and our delta-V stays a lookup."""
        scenario = Scenario(
            name="Mixed", epoch_utc=EPOCH,
            adversary_actions=[
                AdversaryAction("A0", "Drift", ActionType.NO_ACTION, 0.5, 0.7),
                AdversaryAction("A1", "Evade", ActionType.MANOEUVRE, 0.5, 0.7, hypothesis=_steady(500)),
            ],
            friendly_responses=self._five_burns(), horizon_hours=9.0,
            binding=ScenarioBinding(red=_elset("red"), blue=_elset("blue")),
        )
        assert not needs_a_run(scenario)
        result = evaluate_scenario(scenario, sampler=_never)
        refusal = result.outcome_matrix[0][1].response_refusal
        assert refusal is not None and refusal.startswith(
            "Our burn is not sized: sizing it with the rest of this evaluation needs at least 25,180 sample-hours, "
            f"above the {decision.MAX_SAMPLE_HOURS:,.0f} one evaluation may run within its "
            f"{decision.EVALUATION_BUDGET_S:.0f} s budget. At these sample counts the longest horizon that fits is "
            "4.2 h."
        )
        assert refusal.endswith(_LOOKUP_DV)
        assert result.outcome_matrix[0][1].ca_computed is not None
        assert result.outcome_matrix[0][1].ca_computed.propagator != RESPONSE_PROPAGATOR

    def test_an_unbound_burn_is_a_lookup_with_nothing_sized(self) -> None:
        scenario = dataclasses.replace(_computed_scenario(_hold(), _avoid()), binding=None)
        assert not needs_a_run(scenario)
        cell = _cell(evaluate_scenario(scenario))
        assert cell.ca_response is None and cell.delta_v_cost_km_s == 0.015
        assert cell.response_refusal == (
            "No burn is shown for the 20 km target: it is sized against this cell's closest approach computed or "
            "sampled, and here that is a lookup." + _LOOKUP_DV
        )

    def test_a_budget_spent_before_the_computed_burns_refuses_them(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A sampled row spends the budget; the computed rows' burns do not start."""

        def sampler(_h: ManoeuvreHypothesis, _b: Any, window: SeparationWindow, /, **_kw: Any) -> Any:
            return _series(window)

        times = iter([0.0, 500.0, 500.0, 500.0])
        run = RunControl(budget_s=120.0, stop=lambda: None, clock=lambda: next(times))
        scenario = _sampled_scenario(_hold(), _avoid(), n=50)
        scenario.adversary_actions.append(AdversaryAction("A1", "Drift", ActionType.NO_ACTION, 0.5, 0.7))
        _stub_plan(monkeypatch, BurnRefusal("1", "after_window", 0))
        result = evaluate_scenario(scenario, sampler=sampler, run=run)
        refusal = result.outcome_matrix[1][_AVOID].response_refusal
        assert refusal == "Our burn is not sized: this evaluation's 120 s budget ran out before it was." + _LOOKUP_DV


class TestSampledRefusals:
    def test_a_failed_nominal_arc_refuses_the_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, None)
        cell = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns()).outcome_matrix[0][_AVOID]
        assert cell.ca_percentiles is not None and cell.ca_response is None
        assert cell.response_refusal is not None and cell.response_refusal.startswith("Our burn is not sized: the blue")

    def test_a_burn_after_the_tca_is_refused_in_a_sampled_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, BurnRefusal("1", "after_tca", 0, 1200.0))
        cell = evaluate_scenario(
            _sampled_scenario(_hold(), _avoid(hours=0.5)), sampler=_WithBurns(),
        ).outcome_matrix[0][_AVOID]
        assert cell.response_refusal == (
            "Our burn is not sized: at 2026-10-17 12:30 UTC, the response's time to execute after the scenario epoch, "
            "it comes after the closest approach at 2026-10-17 12:20 UTC (RK45, red with the hypothesis's nominal "
            "burn), so it cannot open it. Shorten the time to execute." + _LOOKUP_DV
        )
        assert cell.figure_bases.delta_v_cost_km_s.kind is Basis.LOOKUP

    def test_a_target_met_without_a_burn_spends_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, _sized_stub(None, before_km=25.0))
        cell = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns()).outcome_matrix[0][_AVOID]
        assert cell.ca_response is not None and cell.delta_v_cost_km_s == 0.0
        assert cell.ca_response.line == (
            "No burn needed: the closest approach without one, 25.0 km, is already at or beyond the 20 km target, so "
            "this response spends nothing. P5 across samples is 3.0 km, under the 20 km target: 36 of 50 samples came "
            "closer than the target."
        )

    def test_a_failed_after_burn_sample_refuses_that_cell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, _sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))))

        class _Failing(_WithBurns):
            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                series = super().__call__(*args, **kwargs)
                after = tuple(b._replace(n_failed=2) for b in series.after_burns)
                return dataclasses.replace(series, after_burns=after)

        cell = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_Failing()).outcome_matrix[0][_AVOID]
        assert cell.ca_refusal is not None and cell.ca_refusal.startswith(
            "Not sampled after our burn: 2 of 50 samples failed to propagate against the burnt blue asset",
        )

    def test_a_budget_spent_while_sizing_refuses_the_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def sizing(*_a: Any, tick: Any = None, **_k: Any) -> Any:
            tick("1", 1, 16)
            return (_sized_stub(None),)

        monkeypatch.setattr(decision, "hypothesis_response_plan", sizing)
        times = iter([0.0, 500.0, 500.0])
        run = RunControl(budget_s=120.0, stop=lambda: None, clock=lambda: next(times))
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns(), run=run)
        assert result.outcome_matrix[0][_HOLD].ca_refusal == (
            "Not sampled: this evaluation's 120 s budget ran out while our burn was sized for this row. Take fewer "
            "samples or a shorter horizon. This cell's closest approach is a lookup."
        )


class TestTheLines:
    def test_a_short_burn_says_it_falls_short(self) -> None:
        plan = elset_response_plan(
            COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, SeparationWindow(EPOCH, COPLANAR_LEO.horizon_s),
            (BurnRequest("1", 0.0, 500.0, 0.001, BurnAxis.CHEAPEST),),
        )
        assert isinstance(plan, Rk45Plan)
        sized = plan.responses[0]
        assert isinstance(sized, SizedBurn)
        figure = ResponseFigure(sized, EPOCH, 500.0, 0.001)
        assert figure.line.startswith("Our burn: the whole 1 m/s budget, in-track (")
        assert figure.line.endswith(" UTC, reaches " + f"{sized.after.approach.miss_km:.1f}" + " km, short of the 500 km target.")
        assert "its size the whole 1 m/s budget, since no burn within it was found" in figure.note

    def test_a_minimum_at_the_window_end_says_the_target_holds_only_to_it(self) -> None:
        window = SeparationWindow(EPOCH, GEO_DRIFT_IN.horizon_s, GEO_DRIFT_IN.step_s)
        plan = elset_response_plan(
            GEO_DRIFT_IN.red_tle, GEO_DRIFT_IN.blue_tle, window, (BurnRequest("1", 0.0, 150.0, 0.05, BurnAxis.IN_TRACK),),
        )
        assert isinstance(plan, Rk45Plan) and isinstance(plan.responses[0], SizedBurn)
        figure = ResponseFigure(plan.responses[0], EPOCH, 150.0, 0.05)
        assert figure.line.endswith(
            " The objects are still closing when the search ends, so the target holds only to 2026-10-19 12:00 UTC."
        )
        assert "in-track, entered by the operator" in figure.note

    def test_each_axis_names_its_senses(self) -> None:
        for axis, words in ((BurnAxis.CROSS_TRACK, "positive normal"), (BurnAxis.RADIAL, "outward")):
            sized = _sized_stub(BlueBurn(0.0, (0.001, 0.0, 0.0)))._replace(axis=axis, sense=1)
            assert f"({words})" in ResponseFigure(sized, EPOCH, 5.0, 0.05).line


class TestTheAstroRefusals:
    def test_an_unpropagated_element_set_fails_the_pair(self) -> None:
        plan = elset_response_plan("not an element set", COPLANAR_LEO.blue_tle, SeparationWindow(EPOCH, 3600.0), ())
        assert plan == ElsetFailure("red", "propagation")

    def test_a_failed_arc_fails_the_pair(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def reenters(*_: Any) -> Any:
            raise ReenteredError("down")

        monkeypatch.setattr(response_burn, "rk45_arc", reenters)
        plan = elset_response_plan(COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, SeparationWindow(EPOCH, 3600.0), ())
        assert plan == ElsetFailure("red", "propagation")

    def test_a_failed_nominal_arc_gives_no_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(response_burn, "nominal_red_arc", lambda *_: None)
        blue = response_burn.elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert blue is not None
        hypothesis = _evasive().hypothesis
        assert hypothesis_response_plan(hypothesis, blue, SeparationWindow(EPOCH, 3600.0), ()) is None

    def test_a_burnt_arc_whose_solve_fails_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(response_burn, "burnt_arc", lambda *_: None)
        plan = elset_response_plan(
            COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, SeparationWindow(EPOCH, COPLANAR_LEO.horizon_s),
            (BurnRequest("1", 0.0, 20.0, 0.05, BurnAxis.CHEAPEST),),
        )
        assert isinstance(plan, Rk45Plan)
        assert plan.responses == (BurnRefusal("1", "propagation", 1),)


def test_the_burn_series_pairs_by_sample() -> None:
    """The fake's burn series shifts every sample by 16.93 km, so P5 after minus P5 before is what it buys."""
    window = SeparationWindow(EPOCH, 3600.0)
    series = _series(window)
    after = BurnSeries(
        BlueBurn(0.0, (0.0, 0.0, 0.0)), tuple(dataclasses.replace(a, miss_km=a.miss_km + 1.0) for a in series.approaches),
        (), 0, MissStats(4.0, 9.0, 21.0, 5.0, 0.4, 1.0, True),
    )
    burnt = decision._burnt_series(series, after)
    assert burnt.miss_km_p5 == 4.0 and burnt.after_burns == () and burnt.converged
    assert np.allclose([a.miss_km for a in burnt.approaches], [a.miss_km + 1.0 for a in series.approaches])
