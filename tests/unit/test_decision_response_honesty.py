"""Our burn's cell never reads as more than it earned (SPC-121 and SPC-118, review of 0.16.0).

A sampled burn that spends the whole budget and still falls short says so; a P5 under the target says how many
samples came closer, not "1 in 20"; a target entered where nothing can be sized says it was not used; a refusal
after the closest approach names the closest approach it was decided on; the job page counts hypotheses, not
sizing; and the job page names a response without a name by its id.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import ELSET_PROPAGATOR, ElsetApproach
from spectre.astro.monte_carlo import BlueBurn, SeparationWindow
from spectre.astro.response_burn import BurnRefusal, Rk45Plan
from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    RunControl,
    SamplingProgress,
    Scenario,
    ScenarioBinding,
    evaluate_scenario,
)
from spectre.domain.decision_figures import ResponseBurnSpec, ResponseFigure
from spectre.domain.provenance import Basis
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH
from tests.unit.test_decision_response import (
    _AVOID,
    _HOLD,
    _avoid,
    _cell,
    _computed_scenario,
    _hold,
    _leo,
    _sampled_scenario,
    _sized_stub,
    _WithBurns,
)
from tests.unit.test_decision_sampled import _Fake, _series

_LOOKUP_DV = " This cell's delta-V is a lookup."
_UNUSED = (
    "No burn is shown for the 20 km target: it is sized against this cell's closest approach computed or sampled, "
    "and here that is a lookup." + _LOOKUP_DV
)
_SHIFT_KM = 16.93   # _WithBurns moves every sample this far out after our burn


def _stub_plan(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    monkeypatch.setattr(decision, "hypothesis_response_plan", lambda *_a, **_k: (result,))


def _under(target: float, shift: float = 0.0) -> int:
    """How many of the fake series' 50 samples, moved out by *shift*, come closer than *target*."""
    return sum(a.miss_km + shift < target for a in _series(SeparationWindow(EPOCH, 3600.0)).approaches)


class TestASampledBurnShortOfTheTarget:
    def test_it_says_the_whole_budget_falls_short_on_the_nominal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sized = _sized_stub(BlueBurn(0.0, (0.002, 0.0, 0.0)))._replace(reached=False)
        _stub_plan(monkeypatch, sized)
        spec = ResponseBurnSpec(20.0, budget_km_s=0.002)
        cell = evaluate_scenario(
            _sampled_scenario(_hold(), _avoid(spec)), sampler=_WithBurns(),
        ).outcome_matrix[0][_AVOID]
        k = _under(20.0, _SHIFT_KM)
        assert cell.ca_response_line == (
            "Our burn: the whole 2 m/s budget, radial (outward) at 2026-10-17 12:00 UTC, falls short of the 20 km "
            f"target on the hypothesis's nominal burn, reaching {sized.after.approach.miss_km:.1f} km. Across samples "
            "it buys +16.9 km at P5: 3.0 km before it, 19.9 km after it. P5 after our burn is 19.9 km, under the 20 "
            f"km target: {k} of 50 samples still came closer than the target."
        )
        assert "sized on the hypothesis's nominal burn to put" not in cell.ca_response_line


class TestAP5UnderTheTargetCountsTheSamples:
    def test_after_a_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, _sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))))
        cell = evaluate_scenario(
            _sampled_scenario(_hold(), _avoid()), sampler=_WithBurns(p5=19.93),
        ).outcome_matrix[0][_AVOID]
        k = _under(20.0, _SHIFT_KM)
        assert 0 < k < 50
        assert cell.ca_response_line is not None and cell.ca_response_line.endswith(
            f" P5 after our burn is 19.9 km, under the 20 km target: {k} of 50 samples still came closer than the "
            "target."
        )
        assert "1 in 20" not in cell.ca_response_line

    def test_with_no_burn_needed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, _sized_stub(None, before_km=25.0))
        cell = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns()).outcome_matrix[0][_AVOID]
        assert cell.ca_response_line is not None and cell.ca_response_line.endswith(
            f" P5 across samples is 3.0 km, under the 20 km target: {_under(20.0)} of 50 samples came closer than the "
            "target."
        )

    def test_a_figure_built_without_counts_says_at_least_1_in_20(self) -> None:
        figure = ResponseFigure(
            _sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))), EPOCH, 20.0, 0.05, sampled_before_p5_km=3.0,
            sampled_after_p5_km=19.0,
        )
        assert figure.line.endswith(
            " P5 after our burn is 19.0 km, under the 20 km target: at least 1 in 20 samples still came closer than "
            "the target."
        )


class TestTheDeltaVNote:
    def test_a_burn_short_of_the_target_does_not_say_a_smaller_one_may_reach_it(self) -> None:
        sized = _sized_stub(BlueBurn(0.0, (0.002, 0.0, 0.0)))._replace(reached=False)
        note = ResponseFigure(sized, EPOCH, 20.0, 0.002).note
        assert "may also reach the target" not in note
        assert note.endswith(
            "its size the whole 2 m/s budget, since no burn within it was found to put the closest approach at 20 km, "
            "searched by RK45 with J2 and exponential drag for both orbits, doubling from the manoeuvre library's "
            "size to the whole budget"
        )

    def test_a_burn_that_reaches_it_does(self) -> None:
        note = ResponseFigure(_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))), EPOCH, 20.0, 0.05).note
        assert note.endswith(
            "halving to within 1 %, so a smaller burn on this axis may also reach the target"
        )


class TestATargetThatCannotBeUsedSaysSo:
    def test_unbound(self) -> None:
        cell = _cell(evaluate_scenario(dataclasses.replace(_computed_scenario(_hold(), _avoid()), binding=None)))
        assert cell.ca_response_line == _UNUSED
        assert cell.figure_bases.delta_v_cost_km_s.kind is Basis.LOOKUP
        assert cell.figure_bases.delta_v_cost_km_s.note.endswith(_UNUSED)

    def test_a_manoeuvre_with_no_hypothesis(self) -> None:
        scenario = Scenario(
            name="x", epoch_utc=EPOCH, adversary_actions=[AdversaryAction("A0", "Move", ActionType.MANOEUVRE, 0.5, 0.7)],
            friendly_responses=[_hold(), _avoid()], horizon_hours=COPLANAR_LEO.horizon_hours,
            binding=ScenarioBinding(red=_leo("red"), blue=_leo("blue")),
        )
        cell = _cell(evaluate_scenario(scenario))
        assert cell.ca_refusal is not None and cell.ca_response_line == _UNUSED

    def test_a_refused_sampled_row(self) -> None:
        cell = evaluate_scenario(_sampled_scenario(_hold(), _avoid(), n=10), sampler=_Fake()).outcome_matrix[0][_AVOID]
        assert cell.ca_refusal is not None and cell.ca_response_line == _UNUSED

    def test_a_response_with_no_target_says_nothing(self) -> None:
        cell = _cell(evaluate_scenario(dataclasses.replace(_computed_scenario(_hold(), _avoid(None)), binding=None)))
        assert cell.ca_response_line is None


class TestARefusalAfterTheTcaNamesTheTcaItWasDecidedOn:
    def test_in_a_sampled_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, BurnRefusal("1", "after_tca", 0, 1500.0))
        cell = evaluate_scenario(
            _sampled_scenario(_hold(), _avoid(hours=0.5)), sampler=_WithBurns(),
        ).outcome_matrix[0][_AVOID]
        assert cell.response_refusal == (
            "Our burn is not sized: at 2026-10-17 12:30 UTC, the response's time to execute after the scenario epoch, "
            "it comes after the closest approach at 2026-10-17 12:25 UTC (RK45, red with the hypothesis's nominal "
            "burn), so it cannot open it. Shorten the time to execute." + _LOOKUP_DV
        )

    def test_in_a_computed_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = _sized_stub(None).before
        refused = Rk45Plan(before, (BurnRefusal("1", "after_tca", 0, 3000.0),))
        monkeypatch.setattr(decision, "elset_response_plan", lambda *_a, **_k: refused)
        cell = _cell(evaluate_scenario(_computed_scenario(_hold(), _avoid(hours=1.0))))
        assert cell.response_refusal == (
            "Our burn is not sized: at 2026-10-17 13:00 UTC, the response's time to execute after the scenario epoch, "
            "it comes after the closest approach at 2026-10-17 12:50 UTC (RK45 for both orbits, no burn), so it "
            "cannot open it. Shorten the time to execute." + _LOOKUP_DV
        )


class _Ticking(_WithBurns):
    """The fake series with our burns, ticking once as a real series ticks per sample."""

    def __call__(self, *args: Any, tick: Any = None, **kwargs: Any) -> Any:
        if tick is not None:
            tick(1, 50)
        return super().__call__(*args, **kwargs)


class TestTheJobPage:
    @pytest.fixture
    def seen(self, monkeypatch: pytest.MonkeyPatch) -> list[SamplingProgress]:
        """One sampled hypothesis and one computed row, each sizing a burn for a response with no name."""

        def sampled(*_a: Any, tick: Any = None, **_k: Any) -> Any:
            tick("1", 1, 16)
            return (_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))),)

        def computed(*_a: Any, tick: Any = None, **_k: Any) -> Any:
            tick("1", 1, 16)
            return Rk45Plan(_sized_stub(None).before, (BurnRefusal("1", "after_window", 0),))

        monkeypatch.setattr(decision, "hypothesis_response_plan", sampled)
        monkeypatch.setattr(decision, "elset_response_plan", computed)
        scenario = _sampled_scenario(_hold(), _avoid(name=" "), n=50)
        scenario.adversary_actions.append(AdversaryAction("A1", "Drift", ActionType.NO_ACTION, 0.5, 0.7))
        progress: list[SamplingProgress] = []
        run = RunControl(budget_s=120.0, stop=lambda: None, progress=progress.append, clock=lambda: 0.0)
        evaluate_scenario(scenario, sampler=_Ticking(), run=run)
        return progress

    def test_it_counts_hypotheses_not_sizing(self, seen: list[SamplingProgress]) -> None:
        sampling = [p for p in seen if p.stage == "sampling"]
        assert sampling and {(p.row, p.rows) for p in sampling} == {(1, 1)}
        assert sum(p.stage == "sizing" for p in seen) == 2

    def test_a_response_with_no_name_is_named_by_its_id(self, seen: list[SamplingProgress]) -> None:
        assert {p.label for p in seen if p.stage == "sizing"} == {"response F1"}


class TestTheChecksHold:
    def test_a_result_mixing_propagators_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Hold cell left on SGP4 beside an RK45 burn would rank one row across two propagators."""
        built = decision._computed_response_cell

        def mixed(*args: Any) -> Any:
            cell = built(*args)
            if args[-1] != _HOLD:
                return cell
            found = cell.ca_computed
            return dataclasses.replace(cell, ca_computed=found._replace(propagator=ELSET_PROPAGATOR))

        monkeypatch.setattr(decision, "_computed_response_cell", mixed)
        with pytest.raises(ValueError, match="share one propagator"):
            evaluate_scenario(_computed_scenario(_hold(), _avoid()))

    def test_one_failed_sample_after_our_burn_refuses_the_cell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_plan(monkeypatch, _sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))))

        class _OneFailed(_WithBurns):
            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                series = super().__call__(*args, **kwargs)
                after = tuple(b._replace(n_failed=1) for b in series.after_burns)
                return dataclasses.replace(series, after_burns=after)

        cell = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_OneFailed()).outcome_matrix[0][_AVOID]
        assert cell.ca_refusal is not None and cell.ca_refusal.startswith(
            "Not sampled after our burn: 1 of 50 samples failed to propagate against the burnt blue asset",
        )


def test_the_stub_approach_is_an_rk45_figure() -> None:
    """The stubs above stand for RK45 figures, as the sizing returns."""
    found = _sized_stub(None).before
    assert isinstance(found, ElsetApproach) and isinstance(found.approach, ClosestApproach)
    assert found.propagator != ELSET_PROPAGATOR
