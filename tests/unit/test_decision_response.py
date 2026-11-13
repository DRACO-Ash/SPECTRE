"""A manoeuvre response with a target separation has its burn sized and applied to the blue asset (SPC-121).

Our response's delta-V was the response's cost times 0.05 km/s, a lookup, and every response in a row had the same
closest approach. Given a target separation, a manoeuvre response's burn is now sized by propagation
(spectre/astro/response_burn.py) at the response's time to execute after the scenario epoch, applied to the blue
asset, and scored on what it buys: the closest approach after it against the one before it, with the delta-V it
spends. A row's cells finally differ by response.

One figure never mixes propagators. SGP4 cannot take a burn, so once any response in a scenario is sized, every
computed figure in the result is RK45 with J2 and drag for both orbits, from their SGP4 states at the scenario
epoch, and the SGP4 figure with no burn is shown beside it with the measured difference. A sampled row sizes our
burn once on the hypothesis's nominal burn and applies it in every sample, paired by sample.

The computed fixtures are the coplanar_leo reference element sets (tests/unit/_decision_reference.py): 10.006 km
at about 14,484 s with no burn; 3.085 m/s retrograde in-track at the epoch reaches 20 km.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import timedelta
from typing import Any

import numpy as np
import pytest

from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import ELSET_PROPAGATOR, ElsetApproach, elset_closest_approach
from spectre.astro.monte_carlo import (
    BlueBurn,
    BurnSeries,
    ManoeuvreHypothesis,
    MissStats,
    SeparationSeries,
    SeparationWindow,
)
from spectre.astro.response_burn import RESPONSE_PROPAGATOR, BurnAxis, SizedBurn
from spectre.domain import decision
from spectre.domain.decision import (
    BINDING_NOTE,
    EVALUATION_BUDGET_S,
    MAX_SAMPLE_HOURS,
    SET_UP_S_PER_SAMPLE,
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    EvaluationStoppedError,
    FriendlyResponse,
    OutcomeMetrics,
    RunControl,
    SamplingProgress,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    evaluate_scenario,
    longest_horizon_h,
    needs_a_run,
    pre_manoeuvre_state,
)
from spectre.domain.decision_figures import ResponseBurnSpec, ResponseFigure
from spectre.domain.provenance import Basis
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, PLANE_CHANGE
from tests.unit.test_decision_sampled import _elset, _evasive, _Fake, _page, _series, _steady

_TARGET = ResponseBurnSpec(target_km=20.0)
_HOLD, _AVOID = 0, 1


def _leo(side: str) -> BoundElset:
    tle = COPLANAR_LEO.red_tle if side == "red" else COPLANAR_LEO.blue_tle
    return BoundElset(
        side=side, name=f"{side.upper()}_LEO", stk_name=f"{side.upper()}_LEO",  # type: ignore[arg-type]
        satno=90002 if side == "red" else 90001, tle=tle, data_mode="REAL", epoch=EPOCH, age_hours=0.0,
        limit_hours=24.0,
    )


def _avoid(spec: ResponseBurnSpec | None = _TARGET, *, hours: float = 0.0, name: str = "Avoid") -> FriendlyResponse:
    return FriendlyResponse("F1", name, ActionType.MANOEUVRE, 0.3, 0.8, hours, burn=spec)


def _hold() -> FriendlyResponse:
    return FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0)


def _computed_scenario(*responses: FriendlyResponse, still: int = 1) -> Scenario:
    actions = [AdversaryAction("A0", "Drift", ActionType.NO_ACTION, 0.5, 0.7)]
    if still > 1:
        actions.append(AdversaryAction("A1", "Retask", ActionType.SENSOR_RETASK, 0.5, 0.7))
    return Scenario(
        name="Avoid", epoch_utc=EPOCH, adversary_actions=actions,
        friendly_responses=list(responses) or [_hold(), _avoid()], horizon_hours=COPLANAR_LEO.horizon_hours,
        binding=ScenarioBinding(red=_leo("red"), blue=_leo("blue")),
    )


@pytest.fixture(scope="module")
def leo() -> ScenarioResult:
    return evaluate_scenario(_computed_scenario(_hold(), _avoid(), still=2))


def _cell(result: ScenarioResult, row: int = 0, col: int = _AVOID) -> OutcomeMetrics:
    return result.outcome_matrix[row][col]


class TestAComputedRowAppliesOurBurn:
    def test_a_manoeuvre_response_with_a_target_has_computed_delta_v(self, leo: ScenarioResult) -> None:
        """27: 3.085 m/s, where the lookup took 0.3 x 50 = 15 m/s."""
        cell = _cell(leo)
        assert cell.delta_v_cost_km_s == pytest.approx(0.003085, rel=0.01)
        assert cell.figure_bases.delta_v_cost_km_s.kind is Basis.COMPUTED
        assert cell.closest_approach_km >= 20.0
        assert cell.ca_response is not None and cell.ca_response.sized.burn is not None
        assert cell.delta_v_cost_km_s == round(float(np.linalg.norm(cell.ca_response.sized.burn.delta_v_ric_km_s)), 5)

    def test_a_rows_cells_differ_by_response(self, leo: ScenarioResult) -> None:
        """28."""
        hold, avoid = leo.outcome_matrix[0]
        assert hold.closest_approach_km == 10.0
        assert avoid.closest_approach_km >= 20.0
        assert hold.figure_bases.delta_v_cost_km_s.kind is Basis.COMPUTED and hold.delta_v_cost_km_s == 0.0   # SPC-125

    def test_every_computed_cell_names_rk45_once_any_response_burns(self, leo: ScenarioResult) -> None:
        """29: the Hold cells too, so no row is ranked across two propagators."""
        cells = [cell for row in leo.outcome_matrix for cell in row]
        assert len(cells) == 4
        assert {cell.ca_computed.propagator for cell in cells if cell.ca_computed is not None} == {RESPONSE_PROPAGATOR}
        assert all(cell.ca_computed is not None for cell in cells)
        assert _cell(leo, 1, _AVOID).ca_computed == _cell(leo).ca_computed

    def test_the_reference_line_gives_both_propagators_and_their_difference(self, leo: ScenarioResult) -> None:
        """30."""
        sgp4 = elset_closest_approach(COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle, SeparationWindow(EPOCH, 21600.0))
        assert isinstance(sgp4, ElsetApproach)
        rk45 = _cell(leo, 0, _HOLD).ca_computed
        assert rk45 is not None
        assert leo.rk45_reference == (sgp4, rk45)
        dm = abs(rk45.approach.miss_km - sgp4.approach.miss_km)
        dt = abs(rk45.approach.tca_s - sgp4.approach.tca_s)
        line = leo.rk45_reference_line
        assert line is not None
        assert line.startswith(
            "Our burn cannot be applied to an element set, so in this result every closest approach is propagated by "
            "RK45 with J2 and exponential drag for both orbits, from their SGP4 states at the scenario epoch. With no "
            f"burn, SGP4 puts the closest approach at {sgp4.approach.miss_km:.3f} km at "
        )
        assert line.endswith(f": {dm:.3f} km and {dt:.0f} s apart, which is the propagators, not any burn.")
        assert line in _page(leo)

    def test_buys_is_rk45_after_minus_rk45_before_and_before_is_the_hold_cell(self, leo: ScenarioResult) -> None:
        """32."""
        figure = _cell(leo).ca_response
        hold = _cell(leo, 0, _HOLD).ca_computed
        assert figure is not None and hold is not None
        assert figure.sized.before == hold
        assert figure.buys_km == figure.sized.after.approach.miss_km - hold.approach.miss_km
        assert figure.line.startswith("Our burn: 3.0") or figure.line.startswith("Our burn: 3.1")
        assert "in-track (retrograde) at 2026-10-17 12:00 UTC, 0.0 h after the scenario epoch. It buys +" in figure.line
        assert figure.line.endswith("both by RK45 for both orbits.")
        assert figure.line in _page(leo)

    def test_the_delta_v_note_names_how_the_burn_was_found(self, leo: ScenarioResult) -> None:
        """33."""
        note = _cell(leo).figure_bases.delta_v_cost_km_s.note
        assert note.startswith("our burn: 3.")
        for part in (
            "at 2026-10-17 12:00 UTC, the response's time to execute after the scenario epoch (entered)",
            "in-track, the manoeuvre library's cheapest for a 4.0 h lead (Clohessy-Wiltshire)",
            "its sense the one that opens the closest approach more when flown",
            "puts the closest approach at 20 km or more within the 50 m/s budget",
            "searched by RK45 with J2 and exponential drag for both orbits",
            "halving to within 1 %, so a smaller burn on this axis may also reach the target",
        ):
            assert part in note, part

    def test_the_computed_line_says_after_our_burn(self, leo: ScenarioResult) -> None:
        line = _cell(leo).ca_computed_line
        assert line is not None and line.endswith("; RK45, after our burn.")
        hold_line = _cell(leo, 0, _HOLD).ca_computed_line
        assert hold_line is not None and hold_line.endswith("; RK45, no burn.")

    def test_the_caveat_says_a_response_with_a_target_differs(self, leo: ScenarioResult) -> None:
        assert leo.computed_caveat == decision.COMPUTED_CAVEAT_WITH_BURNS_ELSET.format(
            ages="red's set 0.0 h old and blue's 0.0 h old")   # both coplanar_leo sets at the scenario epoch
        assert "A response with a target separation applies our burn to the blue asset" in leo.computed_caveat
        assert "Our burn is sized on the miss itself, not the band, so a response whose burn is sized scores its own" in leo.computed_caveat


class TestWhatIsNotSized:
    def test_no_target_gives_a_lookup_note_ending_with_the_target_sentence(self) -> None:
        """34."""
        result = evaluate_scenario(_computed_scenario(_hold(), _avoid(None)))
        cell = _cell(result)
        assert cell.figure_bases.delta_v_cost_km_s.kind is Basis.LOOKUP
        assert cell.figure_bases.delta_v_cost_km_s.note.endswith("Enter a target separation to size this burn.")
        assert cell.ca_computed is not None and cell.ca_computed.propagator == ELSET_PROPAGATOR

    def test_a_burn_after_the_span_is_refused(self) -> None:
        """35: 7 h to execute against a 6 h horizon: delta-V a lookup, closest approach computed with no burn."""
        result = evaluate_scenario(_computed_scenario(_hold(), _avoid(hours=7.0)))
        cell = _cell(result)
        assert cell.ca_response is None
        assert cell.figure_bases.delta_v_cost_km_s.kind is Basis.LOOKUP
        assert cell.delta_v_cost_km_s == 0.015
        assert cell.ca_computed is not None
        assert cell.closest_approach_km == _cell(result, 0, _HOLD).closest_approach_km
        assert cell.response_refusal == (
            "Our burn is not sized: at 2026-10-17 19:00 UTC it comes after the 6.0 h searched, so it cannot change "
            "the closest approach in it. This cell's delta-V is a lookup."
        )
        assert cell.response_refusal in cell.figure_bases.delta_v_cost_km_s.note

    def test_a_burn_after_the_tca_is_refused(self) -> None:
        result = evaluate_scenario(_computed_scenario(_hold(), _avoid(hours=5.0)))
        refusal = _cell(result).response_refusal
        assert refusal is not None and refusal.startswith(
            "Our burn is not sized: at 2026-10-17 17:00 UTC, the response's time to execute after the scenario epoch, "
            "it comes after the closest approach at 2026-10-17 16:0",
        )

    def test_a_target_already_met_spends_nothing(self) -> None:
        result = evaluate_scenario(_computed_scenario(_hold(), _avoid(ResponseBurnSpec(5.0))))
        cell = _cell(result)
        assert cell.delta_v_cost_km_s == 0.0 and cell.figure_bases.delta_v_cost_km_s.kind is Basis.COMPUTED
        assert cell.ca_response is not None and cell.ca_response.line == (
            "No burn needed: the closest approach without one, 10.0 km, is already at or beyond the 5 km target, so "
            "this response spends nothing."
        )

    @pytest.mark.parametrize(
        "spec",
        [ResponseBurnSpec(0.0), ResponseBurnSpec(math.nan), ResponseBurnSpec(20.0, budget_km_s=0.0),
         ResponseBurnSpec(20.0, budget_km_s=math.inf)],
    )
    def test_a_burn_needs_a_finite_target_and_budget_above_zero(self, spec: ResponseBurnSpec) -> None:
        with pytest.raises(ValueError, match="FriendlyResponse.burn"):
            _avoid(spec)

    def test_only_a_manoeuvre_response_burns(self) -> None:
        with pytest.raises(ValueError, match="manoeuvre"):
            FriendlyResponse("F2", "Retask", ActionType.SENSOR_RETASK, 0.1, 0.9, 1.0, burn=_TARGET)


class TestTheInvariants:
    def _metrics(self, **changes: Any) -> OutcomeMetrics:
        leo = evaluate_scenario(_computed_scenario(_hold(), _avoid()))
        return dataclasses.replace(_cell(leo), **changes)

    def test_a_response_with_an_sgp4_figure_is_refused(self) -> None:
        """31."""
        cell = self._metrics()
        assert cell.ca_computed is not None
        sgp4 = cell.ca_computed._replace(propagator=ELSET_PROPAGATOR)
        with pytest.raises(ValueError, match="RK45"):
            dataclasses.replace(cell, ca_computed=sgp4)

    def test_a_response_needs_a_computed_delta_v(self) -> None:
        cell = self._metrics()
        bases = dataclasses.replace(cell.figure_bases, delta_v_cost_km_s=decision.LOOKUP_BASES.delta_v_cost_km_s)
        with pytest.raises(ValueError, match="ca_response"):
            dataclasses.replace(cell, figure_bases=bases)

    def test_the_delta_v_shown_is_the_burn(self) -> None:
        with pytest.raises(ValueError, match="delta_v_cost_km_s"):
            self._metrics(delta_v_cost_km_s=0.015)

    def test_one_propagator_per_matrix(self, leo: ScenarioResult) -> None:
        sgp4_cell = dataclasses.replace(
            _cell(leo, 0, _HOLD), ca_computed=_cell(leo, 0, _HOLD).ca_computed._replace(propagator=ELSET_PROPAGATOR),  # type: ignore[union-attr]
        )
        with pytest.raises(ValueError, match="one propagator"):
            decision._require_one_propagator([[sgp4_cell, _cell(leo)]])


# ── A sampled row ──

def _evasive_quarter(n: int) -> AdversaryHypothesis:
    """Evasive from red's state 0.25 h into the window, as m5.py measured it."""
    at = pre_manoeuvre_state(PLANE_CHANGE.red_tle, EPOCH + timedelta(hours=0.25))
    assert at is not None
    return AdversaryHypothesis.from_archetype("evasive", at, n_samples=n)


def _sampled_scenario(*responses: FriendlyResponse, n: int = 100, real: bool = False) -> Scenario:
    hypothesis = _evasive_quarter(n) if real else _evasive(n)
    return Scenario(
        name="Evade", epoch_utc=EPOCH,
        # P 1: the one action, certain, so no remainder row is computed beside the sampled row (SPC-203).
        adversary_actions=[AdversaryAction("A0", "Evade", ActionType.MANOEUVRE, 1.0, 0.7, hypothesis=hypothesis)],
        friendly_responses=list(responses), horizon_hours=1.0,
        binding=ScenarioBinding(red=_elset("red"), blue=_elset("blue")),
    )


def _sized_stub(burn: BlueBurn | None, before_km: float = 9.65) -> SizedBurn:
    found = ElsetApproach(ClosestApproach(before_km, 1410.0, False), 0.394, SeparationWindow(EPOCH, 3600.0),
                          RESPONSE_PROPAGATOR)
    return SizedBurn("1", burn, found, found, BurnAxis.RADIAL, True, 1410.0, 1, True, 11)


class _WithBurns(_Fake):
    """The fake series, with each burn's series at P5 *p5* and its convergence as given."""

    def __init__(self, p5: float = 19.93, *, converged: bool = True) -> None:
        super().__init__()
        self.p5, self.converged = p5, converged
        self.burns: tuple[BlueBurn, ...] | None = None

    def __call__(self, hypothesis: ManoeuvreHypothesis, blue: Any, window: SeparationWindow, *,
                 blue_burns: tuple[BlueBurn, ...] = (), **_: Any) -> SeparationSeries:
        self.burns = blue_burns
        series = _series(window)
        shifted = tuple(dataclasses.replace(a, miss_km=a.miss_km + 16.93) for a in series.approaches)
        stats = MissStats(self.p5, self.p5 + 5.0, self.p5 + 17.0, 5.0, 0.4 if self.converged else 3.0, 1.0,
                          self.converged)
        after = tuple(BurnSeries(burn, shifted, (), 0, stats) for burn in blue_burns)
        return dataclasses.replace(series, after_burns=after)


class TestASampledRow:
    def test_a_real_sampled_run_applies_our_burn_in_every_sample(self) -> None:
        """36: plane_change Evasive 0.25 h in, 100 samples: 5.47 m/s inward, sized on the nominal burn. Before SPC-202,
        9.45 km at P5 before and 19.94 km after, 16 of 100 under the 20 km target; with each sample drawing both
        objects' element-set error, 1.0 km each at epoch, 7.27 km before and 17.87 km after, 52 of 100 under it
        (re-derived by evaluating this scenario under each rule): the burn is sized on the nominal, not the band."""
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid(), real=True))
        hold, avoid = result.outcome_matrix[0]
        assert hold.ca_percentiles is not None and avoid.ca_percentiles is not None
        assert avoid.ca_percentiles[5] == pytest.approx(17.87, abs=0.05)
        assert avoid.ca_response is not None
        assert avoid.ca_response.buys_km == pytest.approx(10.6, abs=0.6)
        assert avoid.ca_response.buys_km == avoid.ca_percentiles[5] - hold.ca_percentiles[5]
        assert avoid.figure_bases.delta_v_cost_km_s.kind is Basis.COMPUTED
        # The integrator's own error ends the note (SPC-214).
        assert ("and our burn is applied to the blue asset in every sample; RK45 runs up to 1.0 h here, from the "
                "window's start to its end; integrator error, not in the spread: "
                in avoid.figure_bases.closest_approach_km.note)
        assert avoid.ca_response.line.startswith("Our burn: ")
        assert "sized on the hypothesis's nominal burn to put its closest approach at 20 km. Across samples it buys +" \
            in avoid.ca_response.line
        counted = avoid.ca_response.sampled_under_target
        assert counted is not None and counted[1] == 100 and counted[0] >= 5   # P5 under 20 km: at least 5 of 100
        assert avoid.ca_response.line.endswith(f" {counted[0]} of 100 samples still came closer than the target.")
        assert avoid.ca_response.line in _page(result)

    def test_the_sampler_is_given_each_sized_burn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        burn = BlueBurn(0.0, (0.00547, 0.0, 0.0))
        monkeypatch.setattr(decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(burn),))
        fake = _WithBurns()
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=fake)
        assert fake.burns == (burn,)
        assert result.outcome_matrix[0][_AVOID].delta_v_cost_km_s == 0.00547

    def test_a_sampled_cell_under_its_target_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """37: P5 after 19.93 km against a 20 km target."""
        monkeypatch.setattr(
            decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))),),
        )
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns(19.93))
        figure = result.outcome_matrix[0][_AVOID].ca_response
        assert figure is not None
        assert figure.line.endswith(
            " P5 after our burn is 19.9 km, under the 20 km target: 3 of 50 samples still came closer than the target."
        )

    def test_an_unconverged_after_burn_band_refuses_only_that_cell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """38."""
        monkeypatch.setattr(
            decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))),),
        )
        result = evaluate_scenario(_sampled_scenario(_hold(), _avoid()), sampler=_WithBurns(converged=False))
        hold, avoid = result.outcome_matrix[0]
        assert hold.ca_percentiles is not None
        assert avoid.ca_percentiles is None and avoid.ca_response is None
        assert avoid.ca_refusal is not None and avoid.ca_refusal.startswith("Not sampled after our burn: P5, P50")
        assert avoid.figure_bases.delta_v_cost_km_s.kind is Basis.LOOKUP


class TestTheCost:
    def _five(self, horizon: float, burns: int) -> Scenario:
        responses = [
            FriendlyResponse(f"F{k}", f"Avoid {k}", ActionType.MANOEUVRE, 0.3, 0.8, 0.0,
                             burn=_TARGET if k < burns else None)
            for k in range(5)
        ]
        return Scenario(
            name="Cap", epoch_utc=EPOCH,
            # P 1: the one action, certain, so no remainder row of no adversary action is costed beside it (SPC-203).
            adversary_actions=[AdversaryAction("A0", "Evade", ActionType.MANOEUVRE, 1.0, 0.7, hypothesis=_steady(500))],
            friendly_responses=responses, horizon_hours=horizon,
            binding=ScenarioBinding(red=_elset("red"), blue=_elset("blue")),
        )

    def test_the_cap_counts_burns(self) -> None:
        """39: 500 samples over 9 h fit with no burn and not with five; with five, 8.8 h is the longest that fits."""
        assert longest_horizon_h(500, burns=5) < 9.0 <= longest_horizon_h(500)
        assert needs_a_run(self._five(9.0, 0))
        scenario = self._five(9.0, 5)
        assert not needs_a_run(scenario)
        refusal = evaluate_scenario(scenario, sampler=_Fake()).outcome_matrix[0][0].ca_refusal
        assert refusal is not None and "with 5 of our burns to size" in refusal
        assert f"the longest horizon that fits is {longest_horizon_h(500, burns=5)} h" in refusal
        assert f"{MAX_SAMPLE_HOURS:,.0f}" in refusal

    @pytest.mark.parametrize("burns", [0, 1, 5])
    def test_the_longest_horizon_counts_burns(self, burns: int) -> None:
        """40: each burn adds 0.3 of a search per sample, 16 sizing trials and blue's burnt arc to every row."""
        m = 500 * (1.0 + 0.3 * burns) + 16 * burns
        hours = (MAX_SAMPLE_HOURS - m * SET_UP_S_PER_SAMPLE / 3600.0) / (m + 2 + burns)
        assert longest_horizon_h(500, burns=burns) == pytest.approx(math.floor(hours * 10) / 10)
        assert longest_horizon_h(500, burns=5) < longest_horizon_h(500, burns=1) < longest_horizon_h(500)

    def test_computed_rows_with_a_burning_response_need_a_run(self) -> None:
        """41."""
        assert needs_a_run(_computed_scenario(_hold(), _avoid()))
        assert not needs_a_run(_computed_scenario(_hold(), _avoid(None)))


class TestTheBudget:
    def test_sizing_ticks_the_budget(self) -> None:
        """42: a stop after the first trial ends the evaluation."""
        seen: list[SamplingProgress] = []

        def stop() -> str | None:
            return "you cancelled it" if seen else None

        run = RunControl(budget_s=EVALUATION_BUDGET_S, stop=stop, progress=seen.append, clock=lambda: 0.0)
        with pytest.raises(EvaluationStoppedError, match="cancelled"):
            evaluate_scenario(_computed_scenario(_hold(), _avoid()), run=run)
        assert len(seen) == 1
        assert seen[0].stage == "sizing" and seen[0].label == "Avoid"
        assert (seen[0].done, seen[0].total) == (1, 16)

    def test_a_spent_budget_refuses_the_burn_by_name(self) -> None:
        ticks = iter(range(1000))
        past = 2 * EVALUATION_BUDGET_S   # each reading of the clock is past the budget after the first
        run = RunControl(budget_s=EVALUATION_BUDGET_S, stop=lambda: None, clock=lambda: past * next(ticks))
        result = evaluate_scenario(_computed_scenario(_hold(), _avoid()), run=run)
        cell = _cell(result)
        assert cell.ca_response is None
        assert cell.response_refusal is not None and f"{EVALUATION_BUDGET_S:g} s budget ran out" in cell.response_refusal


class TestWhatTheResultSays:
    def test_the_score_note_gives_both_deltas(self, leo: ScenarioResult) -> None:
        """44; SPC-191: the move is the closest-approach term before the burn less the one after it, each worked here
        as 1 at or inside the 10 km keep-out and ln(50,000 / miss) / ln 5,000 beyond it, and the delta-V's share is
        0.20 x ln(1 + dv) / ln 1,001 for dv in m/s."""
        figure = _cell(leo).ca_response
        assert figure is not None
        w = leo.scenario
        before, after = figure.misses_km
        assert after - before == figure.buys_km

        def term(miss_km: float) -> float:
            return 1.0 if miss_km <= 10.0 else math.log(50_000.0 / miss_km) / math.log(5_000.0)

        ca = w.w_closest_approach * abs(term(before) - term(after))
        dv_m_s = _cell(leo).delta_v_cost_km_s * 1000
        dv = w.w_dv_cost * math.log(1.0 + dv_m_s) / math.log(1_001.0)
        assert ca > w.w_closest_approach * abs(figure.buys_km) / 50_000.0   # more than the linear scale gave it
        assert leo.burn_score_note == (
            "The score values closest approach in orders of magnitude from the 10 km keep-out distance to 50,000 km, "
            f"and our delta-V in orders of magnitude up to 1,000 m/s, so the {figure.buys_km:.1f} km our burn buys "
            f"against Drift moves its score by {ca:.4f} while its {dv_m_s:.2f} m/s adds {dv:.4f}: read what a burn "
            "buys from its cell as well as from the ranking."
        )

    def test_the_binding_note_says_when_our_delta_v_is_computed(self) -> None:
        """45; SPC-125: a response that does not burn spends 0 m/s against the no-burn orbit, not a lookup."""
        assert BINDING_NOTE.endswith(
            "Our delta-V is computed for a manoeuvre response given a target separation, and is 0 m/s for a response "
            "that does not burn wherever the closest approach is computed or sampled; a manoeuvre response with no "
            "target keeps the lookup."
        )
        assert "our burn is sized only for a manoeuvre response given a target separation" in decision.HYPOTHESIS_NOTE

    def test_no_gap_is_measured_when_every_figure_is_rk45(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """45: computed rows on RK45 beside a sampled row compare like with like."""

        def gap(*_: Any) -> float:
            raise AssertionError("a gap was measured")

        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", gap)
        sampled = _sampled_scenario(_hold(), _avoid(), n=50)
        scenario = dataclasses.replace(sampled, adversary_actions=[
            dataclasses.replace(sampled.adversary_actions[0], probability=0.5),
            AdversaryAction("A1", "Drift", ActionType.NO_ACTION, 0.5, 0.7),
        ])
        monkeypatch.setattr(
            decision, "hypothesis_response_plan", lambda *_a, **_k: (_sized_stub(BlueBurn(0.0, (0.00547, 0.0, 0.0))),),
        )
        result = evaluate_scenario(scenario, sampler=_WithBurns())
        assert result.n_computed_cells == 2 and result.n_sampled_cells == 2
        assert result.propagator_gap_km is None and result.propagator_line is None

    def test_the_page_says_how_many_cells_burn(self, leo: ScenarioResult) -> None:
        assert "our burn sized in 2 cells" in _page(leo)

    def test_figures_without_burns_keep_their_basis(self) -> None:
        figure = ResponseFigure(_sized_stub(None), EPOCH + timedelta(hours=1.0), 5.0, 0.05)
        assert figure.buys_km == 0.0
