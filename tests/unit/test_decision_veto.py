"""A response the operator marks not permitted is never recommended (SPC-195, evaluation F-04, gate G4).

Evaluation probe P-06 found no field that could mark a response unacceptable, so a response that breaks a legal,
rules-of-engagement or safety constraint was recommended whenever it scored best. Each friendly response now carries
a veto, "Not permitted", with a reason. A vetoed response is removed before aggregation: no rule picks it, on the
matrix or on a game tree, a tie never brings it back, and it is never ranked first. It is still evaluated and shown,
so the operator sees what was excluded and why. With every response vetoed, nothing is recommended and the result
says why. These tests are the inverse of P-06: the vetoed response scores best and is still never recommended.
"""

from __future__ import annotations

import dataclasses

import pytest

from spectre.domain.decision import (
    MAX_VETO_REASON,
    ActionType,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
    permitted_responses,
    rank_responses,
)
from spectre.domain.decision_tree import evaluate_tree
from spectre.domain.rule_comparison import NONE_PERMITTED, compare_rules, matrix_picks, tree_turn_one_picks
from spectre.domain.tree_selectors import EXCLUDED, NO_PICK_VETOED_FIRST, TurnPick, select
from tests.unit._i13 import i13_problems
from tests.unit.test_decision_prior_interval import _both_applied, _prior, _result
from tests.unit.test_decision_rule_comparison import _BEFORE, _ONE_WAY, _scenario, _scored
from tests.unit.test_decision_tree_select import _still
from tests.unit.test_tree_selectors import _scenario as _tree_scenario
from tests.unit.test_tree_selectors import _tree, _two_turn_score

_MINIMAX, _MINIMIN, _EV = SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE
_RULES = (_MINIMAX, _MINIMIN, _EV)
_REASON = "Rules of engagement: no manoeuvre towards a third party's asset."


def _vetoed(response: FriendlyResponse, reason: str = _REASON) -> FriendlyResponse:
    return dataclasses.replace(response, vetoed=True, veto_reason=reason)


def _veto(scenario: Scenario, *places: int) -> Scenario:
    responses = [_vetoed(r) if j in places else r for j, r in enumerate(scenario.friendly_responses)]
    return dataclasses.replace(scenario, friendly_responses=responses)


def _forced(scenario: Scenario, scores: tuple[tuple[float, ...], ...], rule: SelectorStrategy) -> ScenarioResult:
    """*scenario* evaluated, its composite scores set to *scores*, and its pick under *rule* taken again."""
    result = evaluate_scenario(scenario, rule)
    matrix = [
        [dataclasses.replace(cell, composite_score=score) for cell, score in zip(row, row_scores, strict=True)]
        for row, row_scores in zip(result.outcome_matrix, scores, strict=True)
    ]
    return dataclasses.replace(
        result, outcome_matrix=matrix, robust_best_response=find_robust_response(scenario, matrix, rule),
        ranked_per_adversary=[rank_responses(scenario.friendly_responses, row) for row in matrix],
    )


class TestTheVetoOnAResponse:
    def test_a_response_is_permitted_unless_marked(self) -> None:
        response = FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0)
        assert (response.vetoed, response.veto_reason, response.not_permitted) == (False, "", None)

    def test_a_vetoed_response_says_so_with_its_reason_in_words(self) -> None:
        response = _vetoed(FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0))
        assert response.not_permitted == f"Not permitted: {_REASON}"

    @pytest.mark.parametrize("reason", ["", "   ", "\t\n"])
    def test_the_reason_is_required_when_the_response_is_vetoed(self, reason: str) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0, vetoed=True, veto_reason=reason)

    def test_the_reason_is_at_most_500_characters(self) -> None:
        assert MAX_VETO_REASON == 500
        longest = FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0, vetoed=True,
                                   veto_reason="x" * 500)
        assert len(longest.veto_reason) == 500
        with pytest.raises(ValueError, match="at most 500 characters; got 501"):
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0, vetoed=True, veto_reason="x" * 501)

    def test_a_reason_without_the_veto_is_refused(self) -> None:
        with pytest.raises(ValueError, match="only for a response not permitted"):
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0, veto_reason="no reason to give")

    def test_the_veto_is_a_truth_value(self) -> None:
        with pytest.raises(TypeError, match="vetoed"):
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0, vetoed=1,  # type: ignore[arg-type]
                             veto_reason=_REASON)

    def test_the_reason_is_text(self) -> None:
        with pytest.raises(TypeError, match="veto_reason"):
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0, vetoed=True,
                             veto_reason=None)  # type: ignore[arg-type]

    def test_the_permitted_responses_are_named_by_place(self) -> None:
        assert permitted_responses(_veto(_scenario(), 1)) == [0, 2]
        assert permitted_responses(_veto(_scenario(), 0, 1, 2)) == []


class TestTheInverseOfProbeP06OnTheMatrix:
    """R2 scores best in every row, so every rule picks it; marked not permitted, no rule does."""

    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_the_best_scoring_response_is_picked_until_it_is_vetoed(self, rule: SelectorStrategy) -> None:
        assert _scored(_ONE_WAY, rule).robust_best_response.id == "R2"
        result = _forced(_veto(_scenario(), 1), _ONE_WAY, rule)
        assert result.robust_best_response is not None
        assert result.robust_best_response.id != "R2"

    def test_no_rule_picks_it_side_by_side_and_the_headline_is_not_it(self) -> None:
        result = _forced(_veto(_scenario(), 1), _ONE_WAY, _MINIMAX)
        picks = matrix_picks(result)
        assert all(pick is not None and pick.id != "R2" for pick in picks.values())
        for primary in _RULES:
            compared = compare_rules(result, primary)
            assert compared.headline is not None and compared.headline.id != "R2"
            assert "Avoid (R2)" not in compared.line

    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_a_real_evaluation_never_recommends_its_own_best_once_vetoed(self, rule: SelectorStrategy) -> None:
        free = evaluate_scenario(_scenario(), rule)
        best = free.scenario.friendly_responses.index(free.robust_best_response)
        vetoed = evaluate_scenario(_veto(_scenario(), best), rule)
        assert vetoed.robust_best_response is not None
        assert vetoed.robust_best_response.id != free.robust_best_response.id

    def test_a_vetoed_response_is_still_evaluated_alike(self) -> None:
        free, vetoed = evaluate_scenario(_scenario()), evaluate_scenario(_veto(_scenario(), 1))
        assert [[c.composite_score for c in row] for row in vetoed.outcome_matrix] == [
            [c.composite_score for c in row] for row in free.outcome_matrix
        ]

    def test_it_is_never_ranked_first_and_is_listed_after_every_permitted_response(self) -> None:
        result = _forced(_veto(_scenario(), 1), _ONE_WAY, _MINIMAX)
        for ranked in result.ranked_per_adversary:
            assert [r.id for r, _ in ranked][-1] == "R2"
            assert ranked[0][0].id != "R2"
        assert [r.id for r, _ in rank_responses(result.scenario.friendly_responses, result.outcome_matrix[0])] == [
            "R1", "R3", "R2",
        ]

    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_a_tie_never_brings_a_vetoed_response_back(self, rule: SelectorStrategy) -> None:
        """R1 and R2 tie for best in every row; the first response wins a tie, but R1 is vetoed, so R2 is picked."""
        tied = ((0.2, 0.2, 0.9), (0.3, 0.3, 0.9))
        assert _forced(_scenario(), tied, rule).robust_best_response.id == "R1"
        assert _forced(_veto(_scenario(), 0), tied, rule).robust_best_response.id == "R2"

    def test_with_every_p_at_0_expected_value_names_no_response(self) -> None:
        """Every row at P 0 under the rule a record 0.28.0 or 0.29.0 wrote: expected value has no pick (SPC-200), so it
        can name no vetoed response either. Under the remainder rule the remainder carries the weight (SPC-203)."""
        scenario = _veto(_scenario(p=0.0, rule=_BEFORE), 0)
        assert find_robust_response(scenario, evaluate_scenario(scenario).outcome_matrix, _EV) is None

    def test_with_every_p_at_0_nothing_is_starred_and_the_star_line_says_why(self) -> None:
        compared = compare_rules(evaluate_scenario(_veto(_scenario(p=0.0, rule=_BEFORE), 0), _EV), _MINIMAX)
        assert compared.star_line == (
            "Nothing is starred: expected value, the rule chosen, has no pick, since every row has P 0."
        )

    def test_the_result_lists_each_vetoed_response_with_its_reason(self) -> None:
        result = evaluate_scenario(_veto(_scenario(), 1))
        assert result.veto_lines == (
            f"Avoid (R2) is marked not permitted, so no rule picks it; it is still evaluated and shown. Its reason: "
            f"{_REASON}",
        )
        assert evaluate_scenario(_scenario()).veto_lines == ()
        assert all(i13_problems(line) == [] for line in result.veto_lines)


class TestEveryResponseVetoed:
    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_no_rule_picks_anything(self, rule: SelectorStrategy) -> None:
        scenario = _veto(_scenario(), 0, 1, 2)
        result = evaluate_scenario(scenario, rule)
        assert result.robust_best_response is None
        assert find_robust_response(scenario, result.outcome_matrix, rule) is None
        assert set(matrix_picks(result).values()) == {None}

    def test_the_result_recommends_nothing_and_says_why(self) -> None:
        result = evaluate_scenario(_veto(_scenario(), 0, 1, 2))
        compared = compare_rules(result, _MINIMAX)
        assert compared.headline is None
        assert not compared.agree
        assert compared.line == NONE_PERMITTED
        assert compared.line == "No rule picks a response: every response is marked not permitted."
        assert compared.primary_line == (
            "This deployment's primary rule is minimax, the rule chosen: it has no pick, since every response is "
            "marked not permitted, so no recommendation is shown."
        )
        assert [pick.pick_text for pick in compared.picks] == [
            "no pick, since every response is marked not permitted",
        ] * 3
        assert compared.star_line == "Nothing is starred: every response is marked not permitted."

    def test_another_primary_rule_says_why_too(self) -> None:
        compared = compare_rules(evaluate_scenario(_veto(_scenario(), 0, 1, 2), _MINIMIN), _MINIMAX)
        assert compared.primary_line == (
            "This deployment's primary rule is minimax: it has no pick, since every response is marked not "
            "permitted. You chose minimin: it has no pick, since every response is marked not permitted. No "
            "recommendation is shown, since the primary rule has no pick."
        )

    def test_under_expected_value_with_an_unearned_p_minimax_is_said_to_pick_nothing(self) -> None:
        result = evaluate_scenario(_veto(_scenario(edited=False), 0, 1, 2), _EV)
        assert result.objective_guidance is not None
        assert result.objective_guidance.endswith(
            "Minimax, the cautious rule, needs no probability, but every response is marked not permitted, so it "
            "picks nothing."
        )

    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_the_trees_agreement_line_says_why_and_names_no_p_0(self, rule: SelectorStrategy) -> None:
        result = evaluate_tree(_veto(_still(), 0, 1), rule)
        compared = compare_rules(result, _MINIMAX)
        assert compared.tree_line == (
            "Over the 2 turns, no rule picks a response on turn 1: every response is marked not permitted."
        )
        assert compared.tree_agree is compared.agree is False
        assert compared.line == NONE_PERMITTED

    def test_with_a_notso_suggestion_applied_no_interval_is_read(self) -> None:
        result = _result([[0.9, 0.2], [0.1, 0.3]])
        vetoed = _veto(result.scenario, 0, 1)
        assert dataclasses.replace(result, scenario=vetoed, robust_best_response=None).interval_lines == ()

    def test_none_is_ranked_first(self) -> None:
        result = evaluate_scenario(_veto(_scenario(), 0, 1, 2))
        assert all(response.vetoed for ranked in result.ranked_per_adversary for response, _ in ranked)


class TestTheInverseOfProbeP06OnAHandBuiltTree:
    """Hold (0) costs nothing in turn 1, so it is picked in turn 1 under every rule; vetoed, no turn picks it."""

    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_no_turn_picks_a_vetoed_response(self, rule: SelectorStrategy) -> None:
        roots = _tree(2, 2, 2, _two_turn_score)
        free = select(_tree_scenario(), roots, 2, rule, matrix_pick=0)
        assert free.picks[0].pick == 0
        vetoed = select(_veto(_tree_scenario(), 0), roots, 2, rule, matrix_pick=1)
        assert vetoed.picks
        assert all(p.pick == 1 for p in vetoed.picks)
        assert all(p.values[0] is None for p in vetoed.picks)
        assert EXCLUDED.format(names="Hold") in vetoed.recommendation

    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_with_every_response_vetoed_the_tree_picks_nothing_and_says_why(self, rule: SelectorStrategy) -> None:
        selection = select(_veto(_tree_scenario(), 0, 1), _tree(2, 2, 2, _two_turn_score), 2, rule, matrix_pick=None)
        assert selection.picks == (TurnPick(1, (), None, (None, None)),)
        assert NO_PICK_VETOED_FIRST in selection.recommendation
        assert NO_PICK_VETOED_FIRST == "Turn 1: no pick, since every response is marked not permitted."


@pytest.fixture(scope="module")
def built() -> dict[tuple[SelectorStrategy, bool], ScenarioResult]:
    """_still's 2-turn tree under each rule, free and with Hold, the response every rule picks there, vetoed."""
    return {
        (rule, veto): evaluate_tree(_veto(_still(), 0) if veto else _still(), rule)
        for rule in _RULES for veto in (False, True)
    }


class TestTheInverseOfProbeP06OnABuiltTwoTurnTree:
    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r.value)
    def test_hold_is_picked_until_it_is_vetoed(
        self, built: dict[tuple[SelectorStrategy, bool], ScenarioResult], rule: SelectorStrategy,
    ) -> None:
        free = built[(rule, False)]
        assert free.tree is not None and free.tree.selection is not None and free.tree.complete_turns == 2
        assert free.tree.selection.picks[0].pick == 0
        assert free.robust_best_response is not None and free.robust_best_response.id == "F0"
        vetoed = built[(rule, True)]
        assert vetoed.tree is not None and vetoed.tree.selection is not None
        assert all(p.pick not in (0, None) for p in vetoed.tree.selection.picks)
        assert vetoed.robust_best_response is not None and vetoed.robust_best_response.id != "F0"

    def test_no_rules_turn_one_pick_is_the_vetoed_response(
        self, built: dict[tuple[SelectorStrategy, bool], ScenarioResult],
    ) -> None:
        for rule in _RULES:
            picks = tree_turn_one_picks(built[(rule, True)])
            assert list(picks) == list(_RULES)
            assert all(pick is not None and pick.id != "F0" for pick in picks.values())

    def test_its_figures_are_the_same_vetoed_or_not(
        self, built: dict[tuple[SelectorStrategy, bool], ScenarioResult],
    ) -> None:
        free, vetoed = built[(_MINIMAX, False)].tree, built[(_MINIMAX, True)].tree
        assert free is not None and vetoed is not None
        assert [n.path_score for n in vetoed.roots] == [n.path_score for n in free.roots]


def _vetoed_result(result: ScenarioResult, *places: int) -> ScenarioResult:
    """*result* with the responses at *places* marked not permitted and its pick taken again."""
    scenario = _veto(result.scenario, *places)
    pick = find_robust_response(scenario, result.outcome_matrix, result.robust_strategy)
    return dataclasses.replace(result, scenario=scenario, robust_best_response=pick)


class TestTheNotsoIntervalNamesNoVetoedResponse:
    """Expected value's pick across a NOTSO interval on P never moves to a response marked not permitted."""

    def test_a_vetoed_response_is_not_the_pick_it_changes_to_across_one_rows_interval(self) -> None:
        # Evade 0.06 + 0.9p against Watch 0.18 + 0.2p: Watch past p 0.171, until Watch is vetoed.
        (free,) = _result([[0.9, 0.2], [0.1, 0.3]]).interval_lines
        assert "above P 0.171 it recommends Watch" in free
        (line,) = _vetoed_result(_result([[0.9, 0.2], [0.1, 0.3]]), 1).interval_lines
        assert line == ("Row 1, Approach: expected value recommends Evade at every P across its NOTSO interval, "
                        "0.04 to 0.30, with the other rows held at their P and the remainder of P taking up the "
                        "difference.")

    def test_a_vetoed_response_is_not_the_pick_it_changes_to_with_rows_moved_together(self) -> None:
        # Moved together, rows 1 and 2 take expected value from Watch to Wait, until Wait is vetoed.
        free = _both_applied(_result([[0.96, 0.01, 0.78], [0.82, 0.89, 0.74]], other_p=0.13), _prior(), _prior())
        assert free.interval_lines[-1].endswith("it recommends Wait, with the remainder of P taking up the difference.")
        vetoed = _both_applied(
            _vetoed_result(_result([[0.96, 0.01, 0.78], [0.82, 0.89, 0.74]], other_p=0.13), 2), _prior(), _prior(),
        )
        assert vetoed.interval_lines[-1] == (
            "Moved together across their NOTSO intervals, rows 1 and 2's P keep expected value at Watch throughout, "
            "with the remainder of P taking up the difference."
        )
