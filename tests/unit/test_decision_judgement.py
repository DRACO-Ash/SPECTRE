"""Operator judgements tagged as judgements, and the code version on the results page (SPC-196, evaluation F-05).

Every figure was tagged computed, sampled or lookup, but the values the operator enters (each response's cost,
reversibility and time to execute, each row's P and Conf, the scoring weights, the keep-out distance) carried no
tag, so an operator could not tell physics from opinion in the inputs to a recommendation. A fourth basis,
judgement, is the weakest of the four: a judgement is not evidence, so it never lends a figure more standing than a
lookup. The results list every input the operator entered that enters a score or a pick, each tagged in words, and
state the code version that computed them.
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import json
import re
from datetime import UTC, datetime

import pytest

import spectre
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    Seen,
    evaluate_scenario,
    outcome_bases,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.decision_inputs import canonical_json, store_inputs
from spectre.domain.decision_judgement import (
    CODE_VERSION_UNRECORDED,
    JUDGEMENT_HEAD,
    judgement_lines,
)
from spectre.domain.provenance import Basis, FigureBasis, weakest
from spectre.domain.threat_understanding import Support, Understanding, _grade
from tests.unit._decision_tree_cases import evasive
from tests.unit.test_decision_figure_basis import _FIGURES, _render, _tags, _text
from tests.unit.test_decision_inputs import _assert_refused, _entered, _result, _tree, _with_priors
from tests.unit.test_threat_understanding import _item

_EPOCH = datetime(2026, 4, 10, tzinfo=UTC)


def _scenario(**kw: object) -> Scenario:
    rows = [
        AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.4, 0.8),
        AdversaryAction("A2", "Quiet", ActionType.NO_ACTION, 0.5, 0.4, probability_edited=False),
    ]
    responses = [
        FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
        FriendlyResponse("R2", "Avoid", ActionType.MANOEUVRE, 0.3, 0.5, 6.0,
                         burn=ResponseBurnSpec(target_km=20.0, budget_km_s=0.04)),
    ]
    fields: dict[str, object] = {"name": "t", "epoch_utc": _EPOCH, "adversary_actions": rows,
                                 "friendly_responses": responses, "keep_out_km": 12.5}
    fields.update(kw)
    return Scenario(**fields)  # type: ignore[arg-type]


def _sentences(
    scenario: Scenario, row_custody: tuple[str | None, ...] = (), row_sampled: tuple[bool, ...] = (),
) -> str:
    return " ".join(line.sentence for line in judgement_lines(scenario, row_custody, row_sampled))


def _notes(scenario: Scenario) -> dict[str, str]:
    """Each listed input's note by "subject: name", as its mark's title shows it."""
    return {f"{line.subject}: {i.name}": i.basis.note for line in judgement_lines(scenario, ()) for i in line.inputs}


def _section(html: str) -> str:
    match = re.search(r'<div[^>]*class="judgement-inputs".*?</div>', html, re.DOTALL)
    assert match is not None, "no Judgement inputs section"
    return match.group(0)


class TestTheJudgementBasis:
    def test_there_are_four_bases_declared_weakest_first(self) -> None:
        assert [b.value for b in Basis] == ["judgement", "lookup", "sampled", "computed"]

    def test_a_judgement_is_weaker_than_a_lookup_in_either_order(self) -> None:
        assert weakest(Basis.LOOKUP, Basis.JUDGEMENT) is Basis.JUDGEMENT
        assert weakest(Basis.JUDGEMENT, Basis.LOOKUP) is Basis.JUDGEMENT
        assert weakest(Basis.JUDGEMENT) is Basis.JUDGEMENT

    @pytest.mark.parametrize("other", list(Basis))
    def test_a_judgement_never_lends_a_figure_more_standing_than_lookup(self, other: Basis) -> None:
        assert weakest(other, Basis.JUDGEMENT) is Basis.JUDGEMENT
        assert weakest(Basis.COMPUTED, Basis.SAMPLED, other, Basis.JUDGEMENT) is Basis.JUDGEMENT

    def test_a_judgement_is_never_threat_evidence(self) -> None:
        with pytest.raises(ValueError, match="a judgement is not evidence"):
            _item(basis=Basis.JUDGEMENT)

    @pytest.mark.parametrize("controlled", [True, False])
    def test_threat_rigour_reads_a_judgement_as_no_better_than_a_lookup(self, controlled: bool) -> None:
        """Rigour is graded by the weakest basis; a judgement is weaker than a lookup, so it grades LOW, never as
        though it were computed (the rule written for a lookup covers it)."""
        grade, why = _grade(None, Support("operator view", Basis.JUDGEMENT, controlled))
        assert grade is Understanding.LOW
        assert why == "the ceiling rests on a judgement (operator view)"

    def test_a_cell_figure_resting_on_a_judgement_pulls_the_score_down_to_it(self) -> None:
        notes = {name: FigureBasis(Basis.COMPUTED, "n") for name in _FIGURES}
        bases = outcome_bases(**{**notes, "closest_approach_km": FigureBasis(Basis.JUDGEMENT, "n")})
        assert bases.composite_score.kind is Basis.JUDGEMENT

    def test_the_score_stays_a_lookup_beside_the_judgements_it_reads(self) -> None:
        result = evaluate_scenario(_scenario())
        assert result.judgement_lines
        for row in result.outcome_matrix:
            for cell in row:
                assert cell.figure_bases.composite_score.kind is Basis.LOOKUP
        assert JUDGEMENT_HEAD.startswith(
            "Judgement inputs: the values on the panel when you evaluated, set by you or kept as the panel started "
            "them, each marked with its basis.")
        assert JUDGEMENT_HEAD.endswith(
            "a figure's mark names the evidence and rules it rests on, taking these inputs as given, so no mark rises "
            "on one, and the score stays a lookup.")

    def test_a_stored_notso_suggestion_is_never_read_back_as_a_judgement(self) -> None:
        document = json.loads(store_inputs(_result(_with_priors()))[0])
        document["scenario"]["adversary_actions"][0]["accepted_prior"]["basis"]["kind"] = "judgement"
        text = canonical_json(document)
        _assert_refused(text, hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "scenario.adversary_actions[0].accepted_prior.basis.kind",
                        "a NOTSO suggestion is a lookup, never a judgement")


class TestEveryJudgementInputIsTagged:
    def test_the_weights_keep_out_distance_horizon_and_turns(self) -> None:
        text = _sentences(_scenario(w_custody=0.3, w_closest_approach=0.3, horizon_hours=36.5))
        assert ("Weights: custody 0.3 (judgement), closest approach 0.3 (judgement), our delta-V 0.2 (judgement), "
                "time to execute 0.1 (judgement), reversibility 0.1 (judgement).") in text
        assert "Keep-out distance: 12.5 km (judgement)." in text
        assert "Horizon: 36.5 h (judgement)." in text
        assert "Turns: 1 (judgement). One turn: the outcome matrix alone, no game tree." in text

    def test_more_turns_say_a_tree_may_pick(self) -> None:
        text = _sentences(_tree(None))
        assert ("Turns: 2 (judgement). Above one turn, a game tree is built where both sides are bound and current, "
                "and its pick heads the results.") in text

    def test_each_responses_type_cost_reversibility_time_to_execute_and_burn(self) -> None:
        text = _sentences(_scenario())
        assert ("Hold (R1): type no action (judgement), cost 0 (judgement), reversibility 1 (judgement), time to "
                "execute 0 h (judgement).") in text
        assert ("Avoid (R2): type manoeuvre (judgement), cost 0.3 (judgement), reversibility 0.5 (judgement), time "
                "to execute 6 h (judgement), target separation 20 km (judgement), delta-V budget 40 m/s "
                "(judgement), burn axis cheapest (judgement).") in text
        assert "The target, budget and axis size its burn where both sides are bound." in text

    @pytest.mark.parametrize(("action_type", "reads"), [
        (ActionType.MANOEUVRE, "cost raises its closest approach and sets its delta-V where those are lookups."),
        (ActionType.POSTURE_CHANGE, "cost raises its closest approach where that is a lookup."),
        (ActionType.SENSOR_RETASK, "its cost moves no figure."),
        (ActionType.NO_ACTION, "its cost moves no figure."),
    ])
    def test_each_response_says_what_its_cost_moves(self, action_type: ActionType, reads: str) -> None:
        """The lookup model raises closest approach by cost for a manoeuvre or posture change, and spends delta-V by
        it for a manoeuvre only; a still response's cost moves nothing."""
        response = FriendlyResponse("R9", "Check", action_type, 0.4, 0.5, 1.0)
        line = judgement_lines(_scenario(friendly_responses=[response]), ())[4]
        assert line.sentence.endswith(
            "Its type selects how the lookup model reads it; reversibility and time to execute enter each of its "
            f"scores; {reads}")

    def test_each_rows_type_p_conf_and_custody_gap_share(self) -> None:
        text = _sentences(_scenario())
        assert ("Approach (A1): type manoeuvre (judgement), P 0.4 (judgement), Conf 0.8 (judgement), custody gap "
                "share 0.7 (judgement). Its type selects its lookup closest approach and custody rule; P weights it "
                "under expected value; Conf moves no figure. The gap share sets its custody gap by rule of thumb "
                "against a response that neither manoeuvres nor retasks a sensor.") in text

    def test_a_p_never_edited_is_the_panels_default_a_lookup(self) -> None:
        text = _sentences(_scenario())
        assert "Quiet (A2): type no action (judgement), P 0.5 (lookup), Conf 0.4 (judgement)." in text

    def test_a_custody_gap_share_no_figure_reads_is_not_listed(self) -> None:
        """Read custody replaces the rule of thumb, so the share enters nothing (SPC-123); a still row has none."""
        text = _sentences(_scenario(), ("Custody read from the bound red track.", None))
        assert "Approach (A1): type manoeuvre (judgement), P 0.4 (judgement), Conf 0.8 (judgement)." in text
        assert "custody gap share" not in text

    @pytest.mark.parametrize("kind", [ActionType.MANOEUVRE, ActionType.SENSOR_RETASK])
    def test_a_custody_gap_share_is_not_listed_when_every_response_holds_custody(self, kind: ActionType) -> None:
        """The rule of thumb loses custody only against a response that neither manoeuvres nor retasks a sensor; with
        none such, the share sets nothing, so it is not listed as entering a figure."""
        responses = [FriendlyResponse("R1", "Act", kind, 0.3, 0.5, 2.0)]
        assert "custody gap share" not in _sentences(_scenario(friendly_responses=responses))

    def test_an_applied_notso_suggestion_is_a_lookup_not_a_judgement(self) -> None:
        scenario = _with_priors()
        text = _sentences(scenario)
        prior = scenario.adversary_actions[0].accepted_prior
        assert prior is not None
        assert f"P {prior.probability:g} (lookup), Conf {prior.confidence:g} (lookup)" in text
        conf_only = scenario.adversary_actions[1]
        assert f"P {conf_only.probability:g} (lookup), Conf {conf_only.confidence:g} (judgement)" in text

    def test_an_entered_hypothesis_is_a_judgement_of_what_red_might_do(self) -> None:
        text = _sentences(_entered())
        assert ("Entered (A1): manoeuvre hypothesis entered (judgement), samples 40 (judgement). What red might do, "
                "not what it did.") in text
        assert ("Spread (A2): manoeuvre hypothesis entered (judgement), delta-V spread 0.7 m/s (judgement), samples "
                "30 (judgement). What red might do, not what it did.") in text

    def test_a_detected_burn_is_what_red_did_not_a_judgement(self) -> None:
        text = _sentences(_entered())
        assert ("Detected (A3): detected burn (computed), samples 10 (judgement). What red did, read from its "
                "element-set history, not a judgement.") in text
        assert "Detected (A3): manoeuvre hypothesis" not in text

    def test_an_archetype_is_your_choice_and_its_delta_v_a_lookup(self) -> None:
        scenario = _scenario(adversary_actions=[evasive(n=50)])
        text = _sentences(scenario)
        assert ("Evasive (A1): archetype Evasive Manoeuvre (judgement), its delta-V 2 m/s (lookup), samples 50 "
                "(judgement). What red might do, not what it did.") in text
        assert "MANOEUVRE_ARCHETYPES" in _notes(scenario)["Evasive (A1): its delta-V"]

    def test_a_hypothesis_says_sampled_only_when_its_row_was(self) -> None:
        scenario = _entered()
        assert "Nothing was sampled from it on this evaluation" in _sentences(scenario, (), (False, False, False))
        sampled = _sentences(scenario, (), (True, False, False))
        assert ("Entered (A1): manoeuvre hypothesis entered (judgement), samples 40 (judgement). What red might do, "
                "not what it did. Its row's closest approach is sampled from it.") in sampled
        assert "its figures are sampled from it" not in sampled

    def test_an_evaluation_that_samples_nothing_never_says_it_did(self) -> None:
        """Under 50 samples a row is not sampled: every figure is a lookup and the list says nothing was sampled."""
        result = evaluate_scenario(_entered())
        assert all(c.figure_bases.closest_approach_km.kind is not Basis.SAMPLED
                   for row in result.outcome_matrix for c in row)
        text = " ".join(line.sentence for line in result.judgement_lines)
        assert "is sampled from it" not in text
        assert text.count("Nothing was sampled from it on this evaluation") == 3

    def test_a_stated_turn_1_observation_is_a_judgement_where_a_tree_reads_it(self) -> None:
        assert "Turn 1: shows a burn (judgement)." in _sentences(_tree(Seen.BURN))
        assert "Turn 1:" not in _sentences(_tree(None))
        assert "Turn 1:" not in _sentences(dataclasses.replace(_tree(Seen.BURN), turns=1))

    def test_a_value_kept_at_its_start_says_so_and_names_where_the_panel_starts_it(self) -> None:
        """The form records no edit of these, so each is the operator's, set or kept: the note says which values a
        new panel starts at, and never that the operator typed it."""
        notes = _notes(_scenario())
        assert notes["Weights: custody"].startswith("your judgement, set or kept on the panel; a new panel starts it "
                                                    "at 0.35")
        assert "a new panel starts it at 10 km" in notes["Keep-out distance: "]
        assert "a new panel starts it at 72 h" in notes["Horizon: "]
        assert "a new row starts it at 0.7" in notes["Approach (A1): Conf"]
        assert "a new row starts it at 0.3" in notes["Avoid (R2): cost"]
        assert "a new row starts it at 0.8" in notes["Avoid (R2): reversibility"]
        assert "a new row starts it at 6 h" in notes["Avoid (R2): time to execute"]
        assert "left blank, the default 50 m/s" in notes["Avoid (R2): delta-V budget"]
        assert all("entered on the panel" not in note for note in notes.values())


class TestThePageTagsThem:
    def test_the_results_list_the_judgement_inputs_in_words(self) -> None:
        result = evaluate_scenario(_scenario())
        section = _section(_render(result))
        text = html.unescape(_text(section))
        assert text.startswith(JUDGEMENT_HEAD)
        for line in result.judgement_lines:
            assert line.sentence in text
        marks = re.findall(r'class="figure-basis" data-basis="(\w+)"', section)
        assert marks == [i.basis.kind.value for line in result.judgement_lines for i in line.inputs]
        assert marks.count("judgement") >= 18

    def test_the_headline_responses_inputs_are_tagged(self) -> None:
        result = evaluate_scenario(_scenario())
        text = _text(_render(result))
        pick = result.robust_best_response
        kind = pick.action_type.value.replace("_", " ").title()
        assert (f"Type: {kind} (judgement) · Cost: {pick.cost} (judgement) · Reversibility: {pick.reversibility} "
                f"(judgement) · Time to execute: {pick.time_to_execute_hours}h (judgement)") in text

    def test_each_rows_p_and_conf_in_the_matrix_carry_their_basis(self) -> None:
        text = _text(_render(evaluate_scenario(_scenario())))
        assert ("Manoeuvre (judgement) · P=0.4 (judgement) · Share=0.4 (judgement) · Conf=0.8 (judgement) · "
                "Gap=0.7 (judgement)") in text
        assert "No Action (judgement) · P=0.5 (lookup) · Share=0.5 (lookup) · Conf=0.4 (judgement)" in text

    def test_the_remainder_row_is_the_engines_and_rests_on_the_weakest_of_the_rows_p(self) -> None:
        """Rows at P 0.4, the operator's judgement, and 0.5, the panel's default, leave 0.1 (SPC-203)."""
        text = html.unescape(_text(_render(evaluate_scenario(_scenario()))))
        assert "No adversary action (remainder of P): the engine's remainder, not your row" in text
        assert "No Action (lookup) · P=0.1 (judgement) · Share=0.1 (judgement) · Conf: none" in text
        assert "No adversary action (remainder of P) (remainder)" not in _sentences(_scenario()), "not a panel input"

    def test_every_existing_figure_mark_is_unchanged(self) -> None:
        html = _render(evaluate_scenario(_scenario()))
        for figure in ("composite_score", "closest_approach_km", "custody_maintained"):
            tags = _tags(html, figure)
            assert tags and all('data-basis="lookup"' in t for t in tags)

    def test_the_code_version_is_on_screen_in_words(self) -> None:
        result = evaluate_scenario(_scenario())
        assert result.provenance is not None
        text = _text(_render(result))
        assert (f"Code version {spectre.__version__}: the version SPECTRE reports for the code that computed this "
                "result, from its provenance.") in text
        assert "release that computed" not in text

    def test_a_result_without_provenance_says_its_code_version_is_not_recorded(self) -> None:
        result: ScenarioResult = dataclasses.replace(evaluate_scenario(_scenario()), provenance=None)
        assert CODE_VERSION_UNRECORDED in _text(_render(result))
