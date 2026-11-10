"""Every rule's pick, side by side, and the deployment's primary rule (SPC-194, evaluation F-03, gate G3).

One rule was chosen per evaluation on the panel and could be changed after a result was seen, and the result showed
that rule's pick alone: no side-by-side result, no disagreement flag. Every result now carries the picks of all
three rules on the same matrix, each with its rule's one-line meaning, a line saying whether they agree and, where
they do not, which picks differ; for a game tree, each rule's turn-1 pick over the tree already built. The headline
recommendation is the deployment's primary rule's pick, so no rule chosen after the fact can hide it.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from spectre.domain.decision import (
    EXPECTED_VALUE_UNEARNED,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from spectre.domain.decision_tree import GameTree
from spectre.domain.rule_comparison import (
    AGREE,
    MEANINGS,
    PICKS_BASIS,
    RULE_WORDS,
    RULES,
    compare_rules,
    expected_value_caveat,
    matrix_picks,
    tree_turn_one_picks,
)
from spectre.domain.tree_selectors import select
from tests.unit._i13 import i13_problems
from tests.unit.test_tree_selectors import _scenario as _tree_scenario
from tests.unit.test_tree_selectors import _tree, _two_turn_score

_EPOCH = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
_MINIMAX, _MINIMIN, _EV = SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE
#: Rows by responses. Minimax picks R2 (worst cases 0.9, 0.5, 0.55), minimin R1 (best cases 0.1, 0.5, 0.35) and
#: expected value at P 0.5 each R3 (means 0.5, 0.5, 0.45): three different picks.
_THREE_WAYS = ((0.9, 0.5, 0.55), (0.1, 0.5, 0.35))
#: Minimax and expected value pick R2 (worst 0.9, 0.5, 0.95; means 0.5, 0.45, 0.6); minimin picks R1 (best 0.1).
_TWO_AND_ONE = ((0.9, 0.5, 0.95), (0.1, 0.4, 0.25))
#: R2 is best in every row, so every rule picks it.
_ONE_WAY = ((0.9, 0.2, 0.95), (0.6, 0.1, 0.65))


def _scenario(*, edited: bool = True, p: float = 0.5) -> Scenario:
    return Scenario(
        name="Approach on BLUE-1", epoch_utc=_EPOCH,
        adversary_actions=[
            AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, p, 0.7, probability_edited=edited),
            AdversaryAction("A2", "Hold course", ActionType.NO_ACTION, p, 0.7, probability_edited=edited),
        ],
        friendly_responses=[
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
            FriendlyResponse("R2", "Avoid", ActionType.MANOEUVRE, 0.3, 0.8, 2.0),
            FriendlyResponse("R3", "Retask", ActionType.SENSOR_RETASK, 0.1, 0.9, 1.0),
        ],
        horizon_hours=24.0,
    )


def _scored(scores: tuple[tuple[float, ...], ...], rule: SelectorStrategy = _MINIMAX, *, edited: bool = True,
            p: float = 0.5) -> ScenarioResult:
    """A real result with its matrix's composite scores set to *scores* and its pick under *rule* taken again."""
    result = evaluate_scenario(_scenario(edited=edited, p=p), rule)
    matrix = [
        [dataclasses.replace(cell, composite_score=score) for cell, score in zip(row, row_scores, strict=True)]
        for row, row_scores in zip(result.outcome_matrix, scores, strict=True)
    ]
    pick = find_robust_response(result.scenario, matrix, rule)
    return dataclasses.replace(result, outcome_matrix=matrix, robust_best_response=pick)


class TestThreePicksSideBySide:
    def test_every_rule_is_listed_in_order_with_its_meaning(self) -> None:
        compared = compare_rules(_scored(_THREE_WAYS), _MINIMAX)
        assert [pick.rule for pick in compared.picks] == [_MINIMAX, _MINIMIN, _EV]
        assert [pick.words for pick in compared.picks] == ["minimax", "minimin", "expected value"]
        assert [pick.meaning for pick in compared.picks] == [MEANINGS[rule] for rule in RULES]
        assert all(MEANINGS[rule].endswith(".") and len(MEANINGS[rule]) < 120 for rule in RULES)

    def test_each_pick_is_find_robust_responses_own_on_the_same_matrix(self) -> None:
        result = _scored(_THREE_WAYS)
        compared = compare_rules(result, _MINIMAX)
        for pick in compared.picks:
            assert pick.response is find_robust_response(result.scenario, result.outcome_matrix, pick.rule)
        assert [pick.response.id for pick in compared.picks] == ["R2", "R1", "R3"]
        assert matrix_picks(result) == {pick.rule: pick.response for pick in compared.picks}

    def test_the_picks_say_what_they_rest_on(self) -> None:
        assert compare_rules(_scored(_THREE_WAYS), _MINIMAX).basis == PICKS_BASIS
        assert "lookup" in PICKS_BASIS

    def test_reading_them_changes_no_figure_and_no_pick(self) -> None:
        result = _scored(_THREE_WAYS, _MINIMIN)
        before = [[cell.composite_score for cell in row] for row in result.outcome_matrix]
        compare_rules(result, _MINIMAX)
        assert [[cell.composite_score for cell in row] for row in result.outcome_matrix] == before
        assert (result.robust_strategy, result.robust_best_response.id) == (_MINIMIN, "R1")


class TestWhetherTheRulesAgree:
    def test_three_different_picks_are_named_each_by_its_rule(self) -> None:
        compared = compare_rules(_scored(_THREE_WAYS), _MINIMAX)
        assert not compared.agree
        assert compared.line == (
            "The rules disagree: minimax picks Avoid (R2); minimin picks Hold (R1); expected value picks Retask (R3)."
        )

    def test_two_that_agree_are_named_together_and_the_odd_one_apart(self) -> None:
        compared = compare_rules(_scored(_TWO_AND_ONE), _MINIMAX)
        assert not compared.agree
        assert compared.line == "The rules disagree: minimax and expected value pick Avoid (R2); minimin picks Hold (R1)."

    def test_agreement_is_said_in_words(self) -> None:
        compared = compare_rules(_scored(_ONE_WAY), _MINIMAX)
        assert compared.agree
        assert compared.line == AGREE.format(pick="Avoid (R2)")
        assert compared.line == "All three rules agree: each picks Avoid (R2)."

    def test_no_line_breaks_i13(self) -> None:
        for scores in (_THREE_WAYS, _TWO_AND_ONE, _ONE_WAY):
            compared = compare_rules(_scored(scores), _EV)
            for line in (compared.line, compared.primary_line, compared.star_line, compared.basis, *MEANINGS.values()):
                assert i13_problems(line) == [], line


class TestExpectedValuesUnearnedProbability:
    def test_its_guidance_stays_beside_its_pick_whatever_rule_ran(self) -> None:
        result = _scored(_THREE_WAYS, _MINIMAX, edited=False)
        compared = compare_rules(result, _MINIMAX)
        caveat = expected_value_caveat(result)
        assert caveat is not None and caveat.startswith(EXPECTED_VALUE_UNEARNED)
        assert compared.caveat == caveat
        assert caveat == dataclasses.replace(result, robust_strategy=_EV).objective_guidance

    def test_it_says_what_minimax_picks_not_what_it_recommends(self) -> None:
        """Beside a headline that may be another rule's pick, minimax's is a pick, not the recommendation."""
        caveat = compare_rules(_scored(_THREE_WAYS, _MINIMIN, edited=False), _MINIMIN).caveat
        assert caveat is not None
        assert caveat.endswith("Minimax, the cautious rule, needs no probability: it picks Avoid.")
        assert "recommends" not in caveat

    def test_an_earned_probability_carries_none(self) -> None:
        assert compare_rules(_scored(_THREE_WAYS), _MINIMAX).caveat is None

    def test_under_expected_value_the_results_own_guidance_is_unchanged(self) -> None:
        result = _scored(_THREE_WAYS, _EV, edited=False)
        compare_rules(result, _MINIMAX)
        assert result.objective_guidance is not None
        assert result.objective_guidance.startswith(EXPECTED_VALUE_UNEARNED)


class TestThePrimaryRule:
    def test_the_headline_is_the_primary_rules_pick_whatever_rule_was_chosen(self) -> None:
        result = _scored(_THREE_WAYS, _MINIMIN)
        compared = compare_rules(result, _MINIMAX)
        assert (compared.primary, compared.chosen) == (_MINIMAX, _MINIMIN)
        assert compared.differs
        assert compared.headline.id == "R2"
        assert result.robust_best_response.id == "R1"

    def test_a_chosen_rule_other_than_the_primary_shows_both_picks(self) -> None:
        compared = compare_rules(_scored(_THREE_WAYS, _EV), _MINIMAX)
        assert compared.primary_line == (
            "This deployment's primary rule is minimax: it picks Avoid (R2). You chose expected value: it picks "
            "Retask (R3). The recommendation shown is the primary rule's pick."
        )

    def test_the_primary_rule_chosen_says_so(self) -> None:
        compared = compare_rules(_scored(_THREE_WAYS, _EV), _EV)
        assert not compared.differs
        assert compared.headline.id == "R3"
        assert compared.primary_line == (
            "This deployment's primary rule is expected value, the rule chosen: the recommendation is its pick, "
            "Retask (R3)."
        )

    def test_the_star_is_said_to_mark_the_rule_chosen_beside_the_primary(self) -> None:
        compared = compare_rules(_scored(_THREE_WAYS, _MINIMIN), _MINIMAX)
        assert compared.star_line == (
            "\u2605 and the blue highlights mark Hold (R1), the pick of minimin, the rule chosen; the recommendation "
            "above is Avoid (R2), the pick of minimax, the deployment's primary rule."
        )

    def test_the_star_on_the_primary_rule_chosen_says_so(self) -> None:
        compared = compare_rules(_scored(_THREE_WAYS, _MINIMAX), _MINIMAX)
        assert compared.star_line == (
            "\u2605 and the blue highlights mark Avoid (R2), the pick of minimax, the primary rule and the rule chosen."
        )

    def test_rule_words_are_the_records_words(self) -> None:
        assert RULE_WORDS == {_MINIMAX: "minimax", _MINIMIN: "minimin", _EV: "expected value"}


def _tree_result(rule: SelectorStrategy = _MINIMAX, *, p: tuple[float, float] = (0.25, 0.75)) -> ScenarioResult:
    """A two-turn result over the hand-built tree of test_tree_selectors, its selection under *rule*."""
    scenario = _tree_scenario(p=p)
    result = evaluate_scenario(scenario, rule)
    roots = _tree(2, 2, 2, _two_turn_score)
    selection = select(scenario, roots, 2, rule, matrix_pick=0)
    return dataclasses.replace(result, tree=GameTree(2, (), roots, 2, None, (), selection))  # type: ignore[arg-type]


class TestEachRulesTurnOnePickOnTheTree:
    def test_each_is_selects_own_over_the_tree_already_built(self) -> None:
        result = _tree_result()
        assert result.tree is not None
        picks = tree_turn_one_picks(result)
        assert list(picks) == list(RULES)
        for rule, response in picks.items():
            own = select(result.scenario, result.tree.roots, 2, rule, matrix_pick=0).picks[0].pick
            assert own is not None
            assert response is result.scenario.friendly_responses[own]

    def test_the_rule_that_ran_gives_the_trees_own_pick(self) -> None:
        for rule in RULES:
            result = _tree_result(rule)
            assert result.tree is not None and result.tree.selection is not None
            first = result.tree.selection.picks[0].pick
            assert first is not None
            assert tree_turn_one_picks(result)[rule] is result.scenario.friendly_responses[first]

    def test_they_are_listed_with_their_own_agreement_line(self) -> None:
        result = _tree_result()
        compared = compare_rules(result, _MINIMAX)
        words = {rule: pick.name for rule, pick in compared.tree_picks if pick is not None}
        assert set(words) == set(RULES)
        assert compared.tree_line is not None
        assert compared.tree_line.startswith("Over the 2 turns, ")
        names = {pick.name for _, pick in compared.tree_picks if pick is not None}
        if len(names) == 1:
            assert compared.tree_line == f"Over the 2 turns, all three rules agree on turn 1: each picks {_label(result, names)}."
        else:
            assert "disagree on turn 1" in compared.tree_line

    def test_a_rule_with_no_pick_says_why(self) -> None:
        """Every row at P 0 leaves expected value no weight to pick on; minimax and minimin still pick."""
        result = _tree_result(p=(0.0, 0.0))
        picks = tree_turn_one_picks(result)
        assert picks[_EV] is None
        assert picks[_MINIMAX] is not None and picks[_MINIMIN] is not None
        line = compare_rules(result, _MINIMAX).tree_line
        assert line is not None
        assert "expected value has no pick, since every row has P 0" in line
        assert "disagree" in line

    def test_a_tree_built_in_part_says_so_and_counts_the_turns_asked(self) -> None:
        """The budget stopped the tree after turn 1 of 2: its line names both, never "the 1 turns"."""
        result = _tree_result()
        assert result.tree is not None
        partial = dataclasses.replace(
            result.tree, complete_turns=1,
            selection=select(result.scenario, result.tree.roots, 1, _MINIMAX, matrix_pick=0),
        )
        line = compare_rules(dataclasses.replace(result, tree=partial), _MINIMAX).tree_line
        assert line is not None
        assert line.startswith("Over the 2 turns, built in full to turn 1 only, ")
        assert "1 turns" not in line

    def test_whether_the_rules_agree_on_the_tree_is_said_apart(self) -> None:
        agreeing = compare_rules(_tree_result(), _MINIMAX)
        assert agreeing.tree_agree is (agreeing.tree_line is not None and "all three rules agree" in agreeing.tree_line)
        split = compare_rules(_tree_result(p=(0.0, 0.0)), _MINIMAX)
        assert split.tree_agree is False
        assert compare_rules(_scored(_THREE_WAYS), _MINIMAX).tree_agree is None

    def test_one_turn_and_a_tree_with_no_selection_list_none(self) -> None:
        one = _scored(_THREE_WAYS)
        assert tree_turn_one_picks(one) == {}
        assert compare_rules(one, _MINIMAX).tree_line is None
        refused = dataclasses.replace(one, tree=GameTree(2, (), (), 0, "No tree.", ("No tree.",)))
        assert tree_turn_one_picks(refused) == {}
        assert compare_rules(refused, _MINIMAX).tree_picks == ()


def _label(result: ScenarioResult, names: set[str]) -> str:
    (name,) = names
    (response,) = [r for r in result.scenario.friendly_responses if r.name == name]
    return f"{response.name} ({response.id})"


@pytest.mark.parametrize("rule", list(SelectorStrategy))
def test_every_selector_strategy_has_words_and_a_meaning(rule: SelectorStrategy) -> None:
    assert rule in RULE_WORDS and rule in MEANINGS and rule in RULES


class TestEveryRowAtPZero:
    """With every row at P 0, expected value has no weight to pick on: it has no pick, on the matrix as on the tree,
    and nothing counts it as agreeing with another rule."""

    def test_expected_value_has_no_pick_on_the_matrix(self) -> None:
        result = _scored(_ONE_WAY, p=0.0)
        assert matrix_picks(result)[_EV] is None
        compared = compare_rules(result, _MINIMAX)
        (ev,) = [pick for pick in compared.picks if pick.rule is _EV]
        assert ev.response is None
        assert ev.pick_text == "no pick, since every row has P 0"
        assert [pick.pick_text for pick in compared.picks[:2]] == ["Avoid (R2)", "Avoid (R2)"]
        assert not compared.agree
        assert compared.line == (
            "The rules disagree: minimax and minimin pick Avoid (R2); expected value has no pick, since every row has "
            "P 0."
        )

    def test_a_row_above_p_zero_gives_it_a_pick(self) -> None:
        result = _scored(_ONE_WAY, p=0.0)
        rows = [dataclasses.replace(result.scenario.adversary_actions[0], probability=0.1),
                result.scenario.adversary_actions[1]]
        weighted = dataclasses.replace(result, scenario=dataclasses.replace(result.scenario, adversary_actions=rows))
        ev = matrix_picks(weighted)[_EV]
        assert ev is find_robust_response(weighted.scenario, weighted.outcome_matrix, _EV)
        assert ev.id == "R2"

    def test_a_primary_rule_with_no_pick_shows_no_recommendation(self) -> None:
        compared = compare_rules(_scored(_ONE_WAY, _EV, p=0.0), _EV)
        assert compared.headline is None
        assert compared.primary_line == (
            "This deployment's primary rule is expected value, the rule chosen: it has no pick, since every row has "
            "P 0, so no recommendation is shown."
        )
        other = compare_rules(_scored(_ONE_WAY, _MINIMAX, p=0.0), _EV)
        assert other.headline is None
        assert other.primary_line == (
            "This deployment's primary rule is expected value: it has no pick, since every row has P 0. You chose "
            "minimax: it picks Avoid (R2). No recommendation is shown, since the primary rule has no pick."
        )
        assert other.star_line == (
            "\u2605 and the blue highlights mark Avoid (R2), the pick of minimax, the rule chosen; the deployment's "
            "primary rule, expected value, has no pick, since every row has P 0, so no recommendation is shown above."
        )

    def test_a_chosen_rule_with_no_pick_says_so_beside_the_primary(self) -> None:
        compared = compare_rules(_scored(_ONE_WAY, _EV, p=0.0), _MINIMAX)
        assert compared.headline is not None and compared.headline.id == "R2"
        assert compared.primary_line == (
            "This deployment's primary rule is minimax: it picks Avoid (R2). You chose expected value: it has no pick, "
            "since every row has P 0. The recommendation shown is the primary rule's pick."
        )
        assert compared.star_line == (
            "\u2605 and the blue highlights mark Hold (R1) only as the first response: expected value, the rule chosen, "
            "has no pick, since every row has P 0."
        )
