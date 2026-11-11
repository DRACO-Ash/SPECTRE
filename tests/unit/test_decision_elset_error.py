"""The Decision Engine reads element-set error in every closest approach it propagates (SPC-202, evaluation F-11).

A sampled cell's samples each draw both objects' element-set error along track, at each set's age at the scenario
epoch, from spectre/astro/along_track.py's model (the threat sweep's rule of thumb, tuned, not sourced), so its band,
P5, convergence and score are of the moved objects. A computed cell keeps its SGP4 miss as the figure, with a band
beside it: the miss less and plus both sets' error at the closest approach in quadrature, the TCA's own uncertainty
figure (SPC-118). Its score reads the lower edge, the closer case, which the operator reads to answer "can it reach
one of mine": Claude's choice.

The pair is co-orbital, as in tests/unit/test_elset_error_in_the_miss.py: red 20 km ahead of blue on one orbit, with
no burn and no spread, so the sampled spread is the element-set error alone.
"""

from __future__ import annotations

import dataclasses
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from spectre.astro.along_track import position_error_km
from spectre.astro.elset_approach import elset_position_error_km
from spectre.astro.monte_carlo import ElsetError, SeparationWindow, run_separation_series
from spectre.astro.propagator import TLEOrbit
from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    HypothesisSource,
    MissRule,
    OutcomeMetrics,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    evaluate_scenario,
)
from spectre.domain.decision_envelope import DEEP_SPACE_GEO, DEEP_SPACE_GEO_ELSET, envelope_lines
from spectre.domain.decision_figures import ELSET_MODEL, ElsetErrorAt, ResponseBurnSpec, tca_histogram, tca_uncertainty
from spectre.domain.decision_inputs import (
    VERSION,
    VERSIONS,
    InputsRefusedError,
    canonical_json,
    read_inputs,
    sha256_of,
    store_inputs,
)
from spectre.domain.decision_replay import LEGACY_POINT, said_first
from spectre.domain.rule_comparison import matrix_picks
from spectre.web.decision_record import replay_record, stored_of
from spectre.web.models import DecisionRecord
from tests.unit._decision_reference import EPOCH, GEO_DRIFT_IN
from tests.unit.test_decision_response import _avoid, _computed_scenario, _hold
from tests.unit.test_decision_sampled import _page
from tests.unit.test_elset_error_in_the_miss import _BLUE_TLE, _RED_TLE, _blue, _still

_HOUR = timedelta(hours=1)


def _bound(side: str, tle: str, age_h: float) -> BoundElset:
    """An element set bound *age_h* old at EPOCH, against a 72 h limit so a two-day-old LEO set still earns time."""
    return BoundElset(
        side=side,  # type: ignore[arg-type]
        name=side.upper(), stk_name=side.upper(), satno=90002 if side == "red" else 90001, tle=tle, data_mode="REAL",
        epoch=EPOCH - age_h * _HOUR, age_hours=age_h, limit_hours=72.0,
    )


def _pair_scenario(red_age_h: float = 0.0, *, n: int = 1000, rule: MissRule | None = None) -> Scenario:
    """Red still, sampled (row 1), and the same pair computed with no burn (row 2), two responses, 0.5 h."""
    rows = [
        AdversaryAction("A0", "Still, sampled", ActionType.MANOEUVRE, 0.5, 0.7,
                        hypothesis=AdversaryHypothesis(_still(n), HypothesisSource.ENTERED)),
        AdversaryAction("A1", "No action", ActionType.NO_ACTION, 0.5, 0.7),
    ]
    responses = [FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
                 FriendlyResponse("F1", "Retask", ActionType.SENSOR_RETASK, 0.2, 0.8, 1.0)]
    binding = ScenarioBinding(red=_bound("red", _RED_TLE, red_age_h), blue=_bound("blue", _BLUE_TLE, 0.0))
    extra = {} if rule is None else {"miss_rule": rule}
    return Scenario(name="Pair", epoch_utc=EPOCH, adversary_actions=rows, friendly_responses=responses,
                    horizon_hours=0.5, binding=binding, **extra)


def _sigma(age_h: float) -> float:
    return position_error_km(age_h / 24.0, "LEO")


@pytest.fixture(scope="module")
def fresh() -> ScenarioResult:
    return evaluate_scenario(_pair_scenario(0.0))


@pytest.fixture(scope="module")
def aged() -> ScenarioResult:
    return evaluate_scenario(_pair_scenario(48.0))


def _sampled(result: ScenarioResult) -> OutcomeMetrics:
    return result.outcome_matrix[0][0]


def _computed(result: ScenarioResult) -> OutcomeMetrics:
    return result.outcome_matrix[1][0]


class TestTheSampledBandWidensWithAge:
    def test_a_fresh_set_draws_the_models_error_at_epoch(self, fresh: ScenarioResult) -> None:
        assert _sampled(fresh).ca_std_km == pytest.approx(math.hypot(_sigma(0.0), _sigma(0.0)), rel=0.12)

    def test_a_two_day_old_set_widens_it_at_the_models_rate(self, aged: ScenarioResult) -> None:
        """Red two days old: 1 km plus 2 km a day is 5 km, so the spread is sqrt(5^2 + 1^2) km, not sqrt(2) km."""
        assert _sigma(48.0) == pytest.approx(5.0)
        assert _sampled(aged).ca_std_km == pytest.approx(math.hypot(5.0, 1.0), rel=0.12)

    def test_the_band_widens_by_the_ratio_the_model_gives(self, fresh: ScenarioResult, aged: ScenarioResult) -> None:
        def width(result: ScenarioResult) -> float:
            p = _sampled(result).ca_percentiles
            assert p is not None
            return p[95] - p[5]

        assert width(aged) / width(fresh) == pytest.approx(math.hypot(5.0, 1.0) / math.hypot(1.0, 1.0), rel=0.2)

    def test_the_cell_names_each_sides_error_and_age(self, aged: ScenarioResult) -> None:
        drawn = _sampled(aged).ca_elset_error
        assert drawn is not None
        assert (drawn.red_km, drawn.blue_km, drawn.red_age_h, drawn.blue_age_h) == pytest.approx((5.0, 1.0, 48.0, 0.0))
        assert drawn.at == EPOCH

    def test_p5_and_the_score_read_the_widened_misses(self, aged: ScenarioResult) -> None:
        """The cell's band is the series run with each side's model error, and its score reads that P5."""
        scenario = aged.scenario
        hypothesis = scenario.adversary_actions[0].hypothesis
        assert hypothesis is not None
        series = run_separation_series(hypothesis.hypothesis, _blue(), SeparationWindow(EPOCH, 1800.0),  # type: ignore[arg-type]
                                       elset_error=ElsetError(5.0, 1.0))
        cell = _sampled(aged)
        assert cell.ca_percentiles == series.percentiles
        figures = decision.cell_figures(cell)
        assert figures.closest_approach_km == series.miss_km_p5
        assert cell.composite_score == round(decision._score(scenario, scenario.friendly_responses[0], figures), 6)


class TestTheComputedBand:
    def test_the_miss_stays_the_figure(self, aged: ScenarioResult) -> None:
        cell = _computed(aged)
        assert cell.ca_computed is not None
        assert cell.closest_approach_km == round(cell.ca_computed.approach.miss_km, 1)

    def test_the_band_is_the_miss_less_and_plus_both_errors_in_quadrature_at_the_tca(self, aged: ScenarioResult) -> None:
        cell = _computed(aged)
        found = cell.ca_computed
        assert found is not None
        tca = found.approach.tca_utc(found.window.start_utc)
        binding = aged.scenario.binding
        assert binding is not None and binding.red is not None and binding.blue is not None
        errors = [elset_position_error_km(s.tle, s.epoch, tca) for s in (binding.red, binding.blue)]  # type: ignore[arg-type]
        combined = math.hypot(*errors)
        assert cell.ca_elset_band == pytest.approx((found.approach.miss_km - combined, found.approach.miss_km + combined))
        drawn = cell.ca_elset_error
        assert drawn is not None
        assert drawn.at == tca
        assert drawn.combined_km == pytest.approx(combined)
        assert cell.tca_uncertainty is not None
        assert drawn.combined_km == pytest.approx(cell.tca_uncertainty.position_error_km)

    def test_the_score_reads_the_lower_edge(self, aged: ScenarioResult) -> None:
        cell = _computed(aged)
        band = cell.ca_elset_band
        assert band is not None
        figures = decision.cell_figures(cell)
        assert figures.closest_approach_km == band[0]
        assert cell.composite_score == round(decision._score(aged.scenario, aged.scenario.friendly_responses[0], figures), 6)

    def test_a_lower_edge_below_zero_scores_as_zero(self) -> None:
        assert decision.lower_edge_km(1.0, 3.0) == 0.0
        assert decision.lower_edge_km(5.0, 3.0) == 2.0

    def test_the_cell_says_the_band_and_what_the_score_reads(self, aged: ScenarioResult) -> None:
        cell = _computed(aged)
        band = cell.ca_elset_band
        assert band is not None
        line = cell.ca_elset_line
        assert line is not None
        assert f"{band[0]:.1f} km to {band[1]:.1f} km" in line
        assert f"the score reads {band[0]:.1f} km" in line
        assert "tuned, not sourced" in line

    def test_the_page_shows_the_band_beside_the_miss(self, aged: ScenarioResult) -> None:
        line = _computed(aged).ca_elset_line
        assert line is not None
        assert _page(aged).count(line) == len(aged.scenario.friendly_responses)


class TestRepeatable:
    def test_the_same_scenario_gives_the_same_figures(self, aged: ScenarioResult) -> None:
        again = evaluate_scenario(_pair_scenario(48.0))
        assert [[c.composite_score for c in row] for row in again.outcome_matrix] == [
            [c.composite_score for c in row] for row in aged.outcome_matrix
        ]
        assert _sampled(again).ca_percentiles == _sampled(aged).ca_percentiles


@pytest.fixture(scope="module")
def point() -> ScenarioResult:
    return evaluate_scenario(_pair_scenario(48.0, rule=MissRule.POINT))


class TestTheRuleBefore:
    """A scenario read from a record 0.28.0 to 0.31.0 wrote is evaluated as it was then: no element-set error."""

    def test_a_new_scenario_reads_the_error(self) -> None:
        assert _pair_scenario().miss_rule is MissRule.ELSET_ERROR

    def test_the_sampled_band_has_no_element_set_spread(self, point: ScenarioResult) -> None:
        cell = _sampled(point)
        assert cell.ca_elset_error is None
        assert cell.ca_std_km == pytest.approx(0.0, abs=0.01)

    def test_the_computed_score_reads_the_point_miss(self, point: ScenarioResult) -> None:
        cell = _computed(point)
        assert cell.ca_elset_band is None and cell.ca_elset_line is None
        assert cell.ca_computed is not None
        assert decision.cell_figures(cell).closest_approach_km == cell.ca_computed.approach.miss_km

    def test_its_sentences_are_the_ones_shown_then(self, point: ScenarioResult) -> None:
        assert "element-set error is not in it" in _computed(point).figure_bases.closest_approach_km.note
        assert "own errors are not sampled" in _sampled(point).figure_bases.closest_approach_km.note


class TestEveryBasisSentenceIsTrue:
    def test_no_sentence_says_the_error_is_left_out(self, aged: ScenarioResult) -> None:
        text = _page(aged)
        assert "element-set error is not in it" not in text
        assert "own errors are not sampled" not in text
        assert "Not in this spread: element-set error" not in text

    def test_the_sampled_basis_names_the_draws_model_source_and_ages(self, aged: ScenarioResult) -> None:
        note = _sampled(aged).figure_bases.closest_approach_km.note
        for words in ("element-set error along track", "5.0 km", "48.0 h", "1.0 km", "0.0 h", "tuned, not sourced",
                      "spectre/astro/along_track.py"):
            assert words in note

    def test_the_computed_basis_names_the_band_model_source_and_ages(self, aged: ScenarioResult) -> None:
        cell = _computed(aged)
        drawn = cell.ca_elset_error
        assert drawn is not None
        note = cell.figure_bases.closest_approach_km.note
        for words in ("in quadrature", f"{drawn.red_age_h:.1f} h", f"{drawn.blue_age_h:.1f} h", "tuned, not sourced",
                      "lower edge"):
            assert words in note

    def test_the_results_caveats_name_it(self, aged: ScenarioResult) -> None:
        assert aged.computed_caveat is not None and "lower edge" in aged.computed_caveat
        assert aged.sampled_caveat is not None and "element-set error along track" in aged.sampled_caveat


def test_the_ages_are_read_from_each_sets_epoch() -> None:
    """The age is the moment less the set's epoch, as the TCA's uncertainty reads it (SPC-118)."""
    binding = _pair_scenario(48.0).binding
    assert binding is not None
    at = decision.elset_error_at(binding, EPOCH)
    assert (at.red_age_h, at.blue_age_h) == (48.0, 0.0)
    assert isinstance(at.at, datetime)


# ── Records 0.28.0 to 0.31.0 wrote: replayed under the rule they were evaluated by ──

#: Two decision records exactly as SPECTRE 0.31.0 wrote them, schema version 3, written by that release's own
#: new_record at adeb112 before SPC-202 was built: a matrix with one sampled row and three computed rows under
#: minimax, and a two-turn tree with a sampled row under expected value.
_V3 = Path(__file__).with_name("_decision_records_0_31_0.json")
_V2 = Path(__file__).with_name("_decision_records_0_29_0.json")
_V1 = Path(__file__).with_name("_decision_records_0_28_0.json")


def _records(path: Path) -> dict[str, DecisionRecord]:
    found = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: DecisionRecord(**{**columns, "id": n, "created_at": datetime.fromisoformat(columns["created_at"])})
        for n, (name, columns) in enumerate(sorted(found.items()), start=1)
    }


_EVERY_OLD = [(path, name) for path in (_V1, _V2, _V3) for name in sorted(json.loads(path.read_text("utf-8")))]
_IDS = [f"{path.stem[-5:]}-{name}" for path, name in _EVERY_OLD]


class TestARecordOf0280To0310ReplaysAsItWasEvaluated:
    def test_the_0310_records_were_written_by_0310(self) -> None:
        for row in _records(_V3).values():
            assert row.code_version == "0.31.0"
            assert json.loads(row.inputs or "")["version"] == 3

    @pytest.mark.parametrize(("path", "name"), _EVERY_OLD, ids=_IDS)
    def test_it_reads_under_the_rule_before(self, path: Path, name: str) -> None:
        assert stored_of(_records(path)[name]).scenario.miss_rule is MissRule.POINT

    @pytest.mark.parametrize(("path", "name"), _EVERY_OLD, ids=_IDS)
    def test_it_replays_exactly_and_says_how(self, path: Path, name: str) -> None:
        done = replay_record(_records(path)[name])
        assert done.matches, done.lines
        assert LEGACY_POINT in done.preamble

    def test_under_this_codes_rule_its_scores_would_differ(self) -> None:
        """Replayed under the rule it was evaluated by it matches; evaluated with element-set error, its computed and
        sampled scores move, which the replay would otherwise report as differences."""
        stored = stored_of(_records(_V3)["sampled_and_computed"])
        now = evaluate_scenario(dataclasses.replace(stored.scenario, miss_rule=MissRule.ELSET_ERROR), stored.rule)
        assert [tuple(c.composite_score for c in row) for row in now.outcome_matrix] != list(stored.scores)

    def test_the_replay_command_says_so_before_it_evaluates(self) -> None:
        assert LEGACY_POINT in said_first(stored_of(_records(_V3)["tree"]), "0.32.0")
        fresh = read_inputs(*store_inputs(evaluate_scenario(_pair_scenario(0.0, n=60))))
        assert LEGACY_POINT not in said_first(fresh, "0.32.0")

    def test_its_scenario_hashes_as_0310_hashed_it(self) -> None:
        row = _records(_V3)["sampled_and_computed"]
        stored = stored_of(row)
        result = evaluate_scenario(stored.scenario, stored.rule)
        assert result.provenance is not None
        assert result.provenance.inputs[0].sha256 == json.loads(row.input_hashes)[0]["sha256"]


class TestTheStoredInputsHoldTheRule:
    def test_this_code_writes_version_4_and_reads_every_earlier_one(self) -> None:
        assert (VERSION, VERSIONS) == (4, (1, 2, 3, 4))
        document = json.loads(store_inputs(evaluate_scenario(_pair_scenario(0.0, n=60)))[0])
        assert document["version"] == 4
        assert document["scenario"]["miss_rule"] == MissRule.ELSET_ERROR.value

    def test_it_reads_back_the_rule(self) -> None:
        stored = read_inputs(*store_inputs(evaluate_scenario(_pair_scenario(0.0, n=60))))
        assert stored.scenario.miss_rule is MissRule.ELSET_ERROR

    def test_a_result_under_the_rule_before_is_never_stored_again(self, point: ScenarioResult) -> None:
        with pytest.raises(ValueError, match="never stored again"):
            store_inputs(point)

    def test_a_version_4_document_under_the_rule_before_is_refused(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(_pair_scenario(0.0, n=60)))[0])
        document["scenario"]["miss_rule"] = MissRule.POINT.value
        text = canonical_json(document)
        with pytest.raises(InputsRefusedError, match=r"refused at scenario\.miss_rule: version 4 holds"):
            read_inputs(text, sha256_of(text))

    def test_a_version_3_document_holding_the_rule_is_refused(self) -> None:
        """Version 3 never held it: a field it never held is unknown there."""
        document = json.loads(store_inputs(evaluate_scenario(_pair_scenario(0.0, n=60)))[0])
        text = canonical_json({**document, "version": 3})
        with pytest.raises(InputsRefusedError, match="unknown field miss_rule"):
            read_inputs(text, sha256_of(text))


# ── Our burn, and the invariant ──

@pytest.fixture(scope="module")
def burns() -> tuple[ScenarioResult, ScenarioResult]:
    """coplanar_leo computed with our burn sized, so every computed cell is RK45: under each rule."""
    scenario = _computed_scenario(_hold(), _avoid(), still=2)
    return evaluate_scenario(scenario), evaluate_scenario(dataclasses.replace(scenario, miss_rule=MissRule.POINT))


def _combined(cell: OutcomeMetrics) -> float:
    assert cell.ca_elset_error is not None
    return cell.ca_elset_error.combined_km


class TestWithOurBurn:
    def test_the_rk45_cells_carry_the_band_and_score_its_lower_edge(self, burns: tuple[ScenarioResult, ...]) -> None:
        now, _ = burns
        cell = now.outcome_matrix[0][1]
        found, band = cell.ca_computed, cell.ca_elset_band
        assert found is not None and band is not None and cell.ca_response is not None
        assert decision.cell_figures(cell).closest_approach_km == band[0]
        assert band[0] == pytest.approx(found.approach.miss_km - _combined(cell))
        first = now.outcome_matrix[0][0].ca_elset_error
        assert first is not None
        assert now.row_uncertainty[0] == decision._ROW_RK45_ELSET.format(elset=decision._ROW_ELSET.format(**first.words()))
        assert now.computed_caveat == decision.COMPUTED_CAVEAT_WITH_BURNS_ELSET.format(
            ages=decision.ELSET_AGES.format(ra=0.0, ba=0.0))

    def test_under_the_rule_before_they_say_what_they_said(self, burns: tuple[ScenarioResult, ...]) -> None:
        _, before = burns
        assert before.computed_caveat == decision.COMPUTED_CAVEAT_WITH_BURNS
        assert before.row_uncertainty[0] == decision._ROW_RK45
        assert before.outcome_matrix[0][1].ca_elset_error is None


def test_a_lookup_cell_never_holds_element_set_error() -> None:
    lookup = evaluate_scenario(dataclasses.replace(_pair_scenario(rule=MissRule.POINT), binding=None))
    cell = lookup.outcome_matrix[1][0]
    error = ElsetErrorAt(EPOCH, 0.0, 0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="ca_elset_error is set only on a computed or sampled closest approach"):
        dataclasses.replace(cell, ca_elset_error=error)


# ── Review of SPC-202: each side's regime, the stated sigma, every sentence's ages, the TCA and the picks ──

def _mixed(red_tle: str, blue_tle: str) -> ScenarioBinding:
    return ScenarioBinding(red=_bound("red", red_tle, 48.0), blue=_bound("blue", blue_tle, 48.0))


class TestEachSideReadsItsOwnRegime:
    """Red a LEO set and blue a GEO set, both two days old: red's error is 1 km plus 2 km a day, 5 km, and blue's
    2 km plus 1 km a day, 4 km. Each side's error is read from its own set, at its own regime's rate."""

    def test_the_error_at_any_moment(self) -> None:
        binding = _mixed(_RED_TLE, GEO_DRIFT_IN.blue_tle)
        now = decision.elset_error_at(binding, EPOCH)
        assert (now.red_km, now.blue_km) == pytest.approx((5.0, 4.0))
        later = decision.elset_error_at(binding, EPOCH + 24 * _HOUR)
        assert (later.red_km, later.blue_km) == pytest.approx((7.0, 5.0))

    def test_and_the_other_way_round(self) -> None:
        now = decision.elset_error_at(_mixed(GEO_DRIFT_IN.red_tle, _BLUE_TLE), EPOCH)
        assert (now.red_km, now.blue_km) == pytest.approx((4.0, 5.0))

    def test_what_every_sample_draws(self) -> None:
        scenario = dataclasses.replace(_pair_scenario(), binding=_mixed(_RED_TLE, GEO_DRIFT_IN.blue_tle))
        assert decision.sample_error(scenario) == ElsetError(red_km=5.0, blue_km=4.0)


class TestTheComputedBandSaysItIsOneSigma:
    """A computed band is the miss less and plus 1 sigma; a sampled cell scores on P5, about 1.645 sigma where the
    error dominates, so the two are scored at different confidence levels, and the cell says which it is."""

    def test_the_line_and_the_basis_say_1_sigma(self, aged: ScenarioResult) -> None:
        cell = _computed(aged)
        assert cell.ca_elset_line is not None and "1 sigma" in cell.ca_elset_line
        assert "1 sigma" in cell.figure_bases.closest_approach_km.note


def _unnamed(sentence: str | None, red_h: float, blue_h: float) -> list[str]:
    """What *sentence* leaves out of the error's model with its figures and source, and both sets' ages: [] for none."""
    wanted = [ELSET_MODEL, f"{red_h:.1f} h old", f"{blue_h:.1f} h old"]
    return wanted if sentence is None else [words for words in wanted if words not in sentence]


class TestEverySentenceNamesTheModelSourceAndAges:
    """Each sentence that once said element-set error is not in a figure names, under SPC-202's rule, the error
    included, its model, its source and the ages read: at the scenario epoch where it is drawn, at the closest
    approach where it is beside a computed miss."""

    def test_the_bands_hover(self, aged: ScenarioResult) -> None:
        assert _unnamed(_sampled(aged).ca_distribution, 48.0, 0.0) == []

    def test_a_computed_rows_uncertainty_sentence(self, aged: ScenarioResult) -> None:
        drawn = _computed(aged).ca_elset_error
        assert drawn is not None
        assert _unnamed(aged.row_uncertainty[1], drawn.red_age_h, drawn.blue_age_h) == []

    def test_a_computed_row_with_our_burn(self, burns: tuple[ScenarioResult, ...]) -> None:
        now, _ = burns
        drawn = now.outcome_matrix[0][0].ca_elset_error
        assert drawn is not None
        assert _unnamed(now.row_uncertainty[0], drawn.red_age_h, drawn.blue_age_h) == []
        assert _unnamed(now.computed_caveat, 0.0, 0.0) == []

    def test_the_results_caveats_and_converged_means(self, aged: ScenarioResult) -> None:
        for sentence in (aged.computed_caveat, aged.sampled_caveat, aged.converged_means):
            assert _unnamed(sentence, 48.0, 0.0) == [], sentence

    def test_the_rule_before_keeps_its_sentences(self, point: ScenarioResult) -> None:
        assert point.converged_means == decision.CONVERGED_MEANS
        assert point.computed_caveat == decision.COMPUTED_CAVEAT
        assert point.row_uncertainty[1] == decision._ROW_COMPUTED


class TestASampledTcaCountsTheErrorOnce:
    """Every sample draws both sets' error at the scenario epoch, so the samples' TCAs spread by it already. The ± on
    a sampled TCA, and the histogram's bins, hold only what the samples do not draw: the error's growth from the
    scenario epoch to the TCA, both sets in quadrature. A computed TCA holds the whole error, as before."""

    @staticmethod
    def _growth(scenario: Scenario, at: datetime) -> float:
        binding = scenario.binding
        assert binding is not None
        then, now = decision.elset_error_at(binding, EPOCH), decision.elset_error_at(binding, at)
        return math.sqrt((now.red_km ** 2 - then.red_km ** 2) + (now.blue_km ** 2 - then.blue_km ** 2))

    def test_the_sampled_tca_holds_the_growth_alone(self, aged: ScenarioResult) -> None:
        cell = _sampled(aged)
        found, tca = cell.ca_sampled_tca, cell.tca_uncertainty
        assert found is not None and tca is not None
        expected = self._growth(aged.scenario, found.tca_utc)
        assert tca.position_error_km == pytest.approx(expected)
        assert tca.position_error_km < 0.5 < _sampled(aged).ca_elset_error.combined_km  # type: ignore[union-attr]
        assert tca.undrawn

    def test_the_growth_is_each_sets_error_then_less_at_the_epoch_in_quadrature(self) -> None:
        """Red LEO 48 h old and blue LEO fresh: 12 h on, red's error grows from 5 km to 6 km and blue's from 1 km to
        2 km, so what no sample draws is sqrt(36 - 25 + 4 - 1) = sqrt(14) km."""
        binding = _pair_scenario(48.0).binding
        assert binding is not None
        assert decision._undrawn_error_km(binding, EPOCH, EPOCH + 12 * _HOUR) == pytest.approx(math.sqrt(14.0))
        assert decision._undrawn_error_km(binding, EPOCH, EPOCH) == 0.0

    def test_its_hover_and_the_histogram_say_what_they_hold(self) -> None:
        tca = tca_uncertainty(0.5, 0.25, 1800.0, at_edge=False, undrawn=True)
        assert tca.sigma_s == pytest.approx(2.0)
        assert "the samples do not draw" in tca.title and ELSET_MODEL in tca.title
        assert "the samples do not draw" not in tca_uncertainty(0.5, 0.25, 1800.0, at_edge=False).title
        slow = tca_uncertainty(0.5, 1e-7, 1800.0, at_edge=False, undrawn=True)
        assert slow.too_slow and "the samples do not draw" in slow.title
        histogram = tca_histogram([0.1, 0.2], [2.0, 2.0], n_closing=0, n_opening=0, undrawn=True)
        assert histogram is not None and "the samples do not draw" in histogram.caption
        plain = tca_histogram([0.1, 0.2], [2.0, 2.0], n_closing=0, n_opening=0)
        assert plain is not None and "the samples do not draw" not in plain.caption

    def test_the_rule_before_holds_the_whole_error(self, point: ScenarioResult) -> None:
        tca = _sampled(point).tca_uncertainty
        assert tca is not None and not tca.undrawn
        found = _sampled(point).ca_sampled_tca
        assert found is not None
        binding = point.scenario.binding
        assert binding is not None
        assert tca.position_error_km == pytest.approx(decision.elset_error_at(binding, found.tca_utc).combined_km)

    def test_a_computed_tca_holds_the_whole_error(self, aged: ScenarioResult) -> None:
        tca = _computed(aged).tca_uncertainty
        assert tca is not None and not tca.undrawn


#: coplanar_leo computed, Hold against Avoid with our burn sized to 15 km: the closest-approach weight 0.7, the other
#: four 0.075 each.
_FLIP_WEIGHTS = {"w_closest_approach": 0.7, "w_custody": 0.075, "w_dv_cost": 0.075, "w_time_to_exec": 0.075,
                 "w_reversibility": 0.075}


@pytest.fixture(scope="module")
def flip() -> tuple[ScenarioResult, ScenarioResult]:
    scenario = dataclasses.replace(_computed_scenario(_hold(), _avoid(ResponseBurnSpec(target_km=15.0))), **_FLIP_WEIGHTS)
    return evaluate_scenario(scenario), evaluate_scenario(dataclasses.replace(scenario, miss_rule=MissRule.POINT))


class TestAPickChangesWhereOurBurnIsSized:
    """Hold's miss, 10.0055 km, is just outside the 10 km keep-out; its band's lower edge is inside it, where the
    closest-approach term is already the full penalty, so Hold's score moves by under 0.0001. Avoid's burn is sized to
    put the miss itself at 15 km, so its lower edge is 15 km less its own error and only Avoid's score rises. Every
    rule picked Avoid under the rule before; every rule picks Hold under this one. Scores are costs: lower is better."""

    def test_every_rule_picked_avoid_before(self, flip: tuple[ScenarioResult, ...]) -> None:
        _, before = flip
        assert {rule.value: f.name for rule, f in matrix_picks(before).items() if f is not None} == {
            "minimax": "Avoid", "minimin": "Avoid", "expected_value": "Avoid"}
        assert [c.composite_score for c in before.outcome_matrix[0]] == pytest.approx([0.699953, 0.694479], abs=1e-6)

    def test_every_rule_picks_hold_now(self, flip: tuple[ScenarioResult, ...]) -> None:
        now, _ = flip
        assert {rule.value: f.name for rule, f in matrix_picks(now).items() if f is not None} == {
            "minimax": "Hold", "minimin": "Hold", "expected_value": "Hold"}
        assert [c.composite_score for c in now.outcome_matrix[0]] == pytest.approx([0.7, 0.704518], abs=1e-6)

    def test_why(self, flip: tuple[ScenarioResult, ...]) -> None:
        now, before = flip
        hold, avoid = now.outcome_matrix[0]
        keep = now.scenario.keep_out_km
        assert before.outcome_matrix[0][0].ca_computed is not None
        assert before.outcome_matrix[0][0].ca_computed.approach.miss_km > keep > decision.cell_figures(hold).closest_approach_km
        band = avoid.ca_elset_band
        assert avoid.ca_computed is not None and band is not None
        assert avoid.ca_computed.approach.miss_km == pytest.approx(15.0, abs=0.2)
        assert decision.cell_figures(avoid).closest_approach_km == band[0] < 15.0 - 1.0


class TestTheEnvelopeFlagSaysWhatTheModelNowFeeds:
    """The element-set error model is a rule of thumb, and since SPC-202 it sets every sample's draw, every computed
    band and the score that reads them, not only a set's age and its TCA's uncertainty, so a flagged set says so."""

    def test_a_geo_pair(self) -> None:
        binding = ScenarioBinding(red=_bound("red", GEO_DRIFT_IN.red_tle, 0.0), blue=_bound("blue", GEO_DRIFT_IN.blue_tle, 0.0))
        scenario = dataclasses.replace(_pair_scenario(), binding=binding)
        lines = envelope_lines(scenario)
        assert len(lines) == 2
        for line in lines:
            assert "drawn in every sample" in line and "beside every computed miss" in line and "score" in line
        assert lines[0] == DEEP_SPACE_GEO_ELSET.format(side="red", name="RED", period=TLEOrbit(GEO_DRIFT_IN.red_tle).period_minutes,
                                                       limit=72.0)

    def test_under_the_rule_before_it_says_what_it_said(self) -> None:
        binding = ScenarioBinding(red=_bound("red", GEO_DRIFT_IN.red_tle, 0.0), blue=_bound("blue", GEO_DRIFT_IN.blue_tle, 0.0))
        scenario = dataclasses.replace(_pair_scenario(rule=MissRule.POINT), binding=binding)
        assert envelope_lines(scenario)[0] == DEEP_SPACE_GEO.format(
            side="red", name="RED", period=TLEOrbit(GEO_DRIFT_IN.red_tle).period_minutes, limit=72.0)
