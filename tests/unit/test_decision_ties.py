"""A tie is detected within a stated tolerance and every tied response is shown (SPC-206, evaluation F-13).

The evaluation found that a tie went to the response entered first and was not shown: two responses equal under the
rule were reported as one recommendation chosen by typing order (probe P-05: X or Y by entry order). Its closing
evidence is P-05's tie case showing both. P-05 is reproduced here from the evaluation's own description, two
responses X and Y that score the same under the rule, entered in either order: both are shown, under every rule, on
the matrix and over a game tree, and the recommendation says it is a tie rather than naming one.

The tolerance is TIE_TOLERANCE, half a unit in the sixth decimal place the engine rounds every composite score to,
listed in the lookup register. The pick find_robust_response returns is unchanged, the first tied response, so a
record's pick columns and their replay stay exactly as before; the tie is said beside it.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import (
    TIE_LINE,
    TIE_TOLERANCE,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeMetrics,
    ProbabilityRule,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
    tie_line,
    tied_responses,
    tied_with,
)
from spectre.domain.decision_tree import GameTree
from spectre.domain.rule_comparison import compare_rules, tree_turn_one_picks, tree_turn_one_ties
from spectre.domain.tree_selectors import (
    MATRIX_DIFFERS,
    PICK_TIED_FIRST,
    PICK_TIED_LATER,
    follows_picks,
    select,
)
from spectre.domain.turn_update import Seen
from tests.unit.test_tree_selectors import Node, _scenario, _tree, _two_turn_score

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_MINIMAX, _EV, _MINIMIN = SelectorStrategy.MINIMAX, SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMIN
_RULES = (_MINIMAX, _MINIMIN, _EV)


def _response(name: str, cost: float = 0.3) -> FriendlyResponse:
    return FriendlyResponse(name, name, ActionType.MANOEUVRE, cost, 0.8, 6.0)


def _p05(*order: str) -> Scenario:
    """P-05: two adversary rows and responses X and Y with the same inputs, so every score of X is Y's, entered in
    *order*, with a costlier Z beside them that never ties."""
    rows = [
        AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.6, 0.7),
        AdversaryAction("A2", "Hold course", ActionType.NO_ACTION, 0.4, 0.7),
    ]
    responses = [_response(name, 0.9 if name == "Z" else 0.3) for name in order]
    return Scenario(name="P-05", epoch_utc=datetime(2026, 11, 5, tzinfo=UTC), adversary_actions=rows,
                    friendly_responses=responses)


def _names(responses: tuple[FriendlyResponse, ...]) -> list[str]:
    return [r.name for r in responses]


def _metrics(score: float) -> OutcomeMetrics:
    return OutcomeMetrics(
        custody_maintained=True, custody_gap_hours=0.0, closest_approach_km=1000.0,
        time_to_closest_hours=1.0, delta_v_cost_km_s=0.0, composite_score=score,
    )


def _render(result: ScenarioResult, primary: SelectorStrategy) -> str:
    from spectre.web.app import templates as _app_templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(_app_templates.env.filters)
    template = env.get_template("partials/decision_results.html")
    html = template.render(result=result, rules=compare_rules(result, primary))
    return " ".join(html.split())


class TestP05ShowsBoth:
    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    @pytest.mark.parametrize("order", [("X", "Y", "Z"), ("Y", "X", "Z")], ids=["X first", "Y first"])
    def test_both_tied_responses_are_shown_whichever_was_entered_first(self, rule: SelectorStrategy,
                                                                       order: tuple[str, ...]) -> None:
        result = evaluate_scenario(_p05(*order), rule)
        scores = [[cell.composite_score for cell in row] for row in result.outcome_matrix]
        assert all(row[0] == row[1] != row[2] for row in scores)
        assert _names(result.tied_responses) == list(order[:2])
        assert _names(tied_responses(result.scenario, result.outcome_matrix, rule)) == list(order[:2])

    @pytest.mark.parametrize("order", [("X", "Y", "Z"), ("Y", "X", "Z")], ids=["X first", "Y first"])
    def test_the_recommendation_says_it_is_a_tie(self, order: tuple[str, ...]) -> None:
        result = evaluate_scenario(_p05(*order))
        first, second = order[:2]
        expected = TIE_LINE.format(rule="minimax", names=f"{first} ({first}) and {second} ({second})",
                                   tolerance=TIE_TOLERANCE)
        assert result.tie_line == expected
        compared = compare_rules(result, _MINIMAX)
        assert _names(compared.headline_tied) == [first, second]
        assert compared.tie_line == expected
        assert [p.pick_text for p in compared.picks] == [f"a tie between {first} ({first}) and {second} ({second})"] * 3

    def test_the_page_names_both_in_the_headline_and_stars_both(self) -> None:
        html = _render(evaluate_scenario(_p05("X", "Y", "Z")), _MINIMAX)
        headline = re.search(r'<div class="headline-pick"[^>]*>([^<]*)</div>', html)
        assert headline is not None and headline.group(1).strip() == "Tie: X and Y"
        assert 'class="tie-line"' in html
        assert "A tie under minimax: X (X) and Y (Y) score within 5e-07 of each other" in html
        assert html.count("★</span>") == 2   # X's and Y's matrix headings, not Z's
        assert "★ and the blue highlights mark X (X) and Y (Y), tied," in html

    def test_the_rules_agree_on_the_tie(self) -> None:
        compared = compare_rules(evaluate_scenario(_p05("X", "Y", "Z")), _MINIMAX)
        assert compared.agree is True
        assert compared.line == "All three rules agree: each picks a tie between X (X) and Y (Y)."

    def test_the_pick_a_record_holds_is_unchanged_so_its_replay_is_too(self) -> None:
        """find_robust_response still returns the first tied response, as every release before did."""
        for order in (("X", "Y", "Z"), ("Y", "X", "Z")):
            result = evaluate_scenario(_p05(*order))
            for rule in _RULES:
                pick = find_robust_response(result.scenario, result.outcome_matrix, rule)
                assert pick is not None and pick.name == order[0]


class TestTheTolerance:
    def _two(self, a: float, b: float) -> tuple[Scenario, list[list[OutcomeMetrics]]]:
        scenario = _p05("X", "Y")
        return scenario, [[_metrics(a), _metrics(b)], [_metrics(a), _metrics(b)]]

    def test_it_is_half_a_unit_in_the_sixth_place_scores_are_rounded_to(self) -> None:
        assert TIE_TOLERANCE == 5e-7

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_values_within_it_tie(self, rule: SelectorStrategy) -> None:
        scenario, matrix = self._two(0.4, 0.4 + 4e-7)
        assert _names(tied_responses(scenario, matrix, rule)) == ["X", "Y"]

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_one_unit_in_the_sixth_place_apart_is_no_tie(self, rule: SelectorStrategy) -> None:
        scenario, matrix = self._two(0.400001, 0.4)
        assert _names(tied_responses(scenario, matrix, rule)) == ["Y"]
        assert tie_line(rule, tied_responses(scenario, matrix, rule)) is None

    def test_a_response_not_permitted_never_joins_a_tie(self) -> None:
        scenario, matrix = self._two(0.4, 0.4)
        vetoed = dataclasses.replace(scenario, friendly_responses=[
            scenario.friendly_responses[0],
            dataclasses.replace(scenario.friendly_responses[1], vetoed=True, veto_reason="Breaks the ROE."),
        ])
        assert _names(tied_responses(vetoed, matrix, _MINIMAX)) == ["X"]

    def test_under_expected_value_with_no_weight_there_is_no_tie(self) -> None:
        """Every row at P 0 under the rule a 0.28.0 or 0.29.0 record is replayed by: no pick, so no tie (SPC-200)."""
        scenario, matrix = self._two(0.4, 0.4)
        before = dataclasses.replace(
            scenario, probability_rule=ProbabilityRule.SHARES,
            adversary_actions=[dataclasses.replace(a, probability=0.0) for a in scenario.adversary_actions],
        )
        assert find_robust_response(before, matrix, _EV) is None
        assert tied_responses(before, matrix, _EV) == ()
        assert _names(tied_responses(before, matrix, _MINIMAX)) == ["X", "Y"]

    def test_with_no_pick_there_is_no_tie(self) -> None:
        scenario, matrix = self._two(0.4, 0.4)
        every = dataclasses.replace(scenario, friendly_responses=[
            dataclasses.replace(r, vetoed=True, veto_reason="Breaks the ROE.") for r in scenario.friendly_responses
        ])
        assert tied_responses(every, matrix, _MINIMAX) == ()
        assert tie_line(_MINIMAX, ()) is None


#: test_tree_selectors' turn-2 costs, but after a burn in turn 1 Hold and Avoid cost the same in turn 2.
_TIED_SECOND = {(0, 0, 0): 0.2, (0, 0, 1): 0.3, (0, 1, 0): 0.9, (0, 1, 1): 0.5,
                (1, 0, 0): 0.1, (1, 0, 1): 0.1, (1, 1, 0): 0.3, (1, 1, 1): 0.3}


def _tied_tree(*, turn_one: bool) -> tuple[Node, ...]:
    """The two-turn hand tree of test_tree_selectors with _TIED_SECOND. Under minimax, after a burn Hold and Avoid
    tie in turn 2 (each worst 0.3), and after none Avoid is picked (0.5 against 0.9); turn 1 then weighs 0.5 holding
    against 0.6 avoiding, or, with *turn_one*, Avoid costing nothing in turn 1, 0.5 against 0.5, a tie."""
    def score(path: tuple[tuple[int, int], ...]) -> float:
        (a1, r1), *rest = path
        first = 0.0 if turn_one else 0.1 * r1
        return first + sum(_TIED_SECOND[(a1, a2, r2)] for a2, r2 in rest)

    return _tree(2, 2, 2, score)


class TestATieOverAGameTree:
    def test_a_tie_in_turn_one_names_both_and_the_plan_follows_each(self) -> None:
        scenario = _scenario()
        selection = select(scenario, _tied_tree(turn_one=True), 2, _MINIMAX, matrix_pick=0)
        first = selection.picks[0]
        assert (first.pick, first.tied) == (0, (1,))
        assert first.values == pytest.approx((0.5, 0.5))
        assert PICK_TIED_FIRST.format(names="Hold and Avoid", tolerance=TIE_TOLERANCE) in selection.recommendation
        assert {p.after for p in selection.picks if p.turn == 2} == {
            ((0, Seen.NO_BURN),), ((0, Seen.BURN),), ((1, Seen.NO_BURN),), ((1, Seen.BURN),),
        }
        assert follows_picks(scenario, selection, ((0, 0), (0, 1)))
        assert follows_picks(scenario, selection, ((0, 1), (0, 1)))
        assert not follows_picks(scenario, selection, ((0, 1), (0, 0)))

    def test_a_tie_in_a_later_turn_names_both(self) -> None:
        scenario = _scenario()
        selection = select(scenario, _tied_tree(turn_one=False), 2, _MINIMAX, matrix_pick=0)
        first = selection.picks[0]
        assert (first.pick, first.tied) == (0, ())
        line = PICK_TIED_LATER.format(k=2, history="turn 1 shows a burn after Hold", names="Hold and Avoid",
                                      tolerance=TIE_TOLERANCE)
        assert line in selection.recommendation
        burnt = [p for p in selection.picks if p.after == ((0, Seen.BURN),)]
        assert [(p.pick, p.tied) for p in burnt] == [(0, (1,))]
        assert follows_picks(scenario, selection, ((1, 0), (1, 0)))
        assert follows_picks(scenario, selection, ((1, 0), (1, 1)))

    def test_no_tie_leaves_the_lines_as_they_were(self) -> None:
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)
        assert all(p.tied == () for p in selection.picks)
        assert "Turn 1: Hold." in selection.recommendation


# ── Review of 0.38.0: entered order, the lowest pick, the tolerance's edges, and the matrix line ──

def _one_turn_result(leaves: dict[tuple[int, int], float]) -> ScenarioResult:
    """A lookup result for rows A1 (P 0.25) and A2 (P 0.75) against Hold (F0) and Avoid (F1), carrying a hand-built
    one-turn tree whose leaf for (red's move, our response) is *leaves*; two turns asked, one built."""
    scenario = Scenario(
        name="Hand", epoch_utc=datetime(2026, 11, 5, tzinfo=UTC),
        adversary_actions=[AdversaryAction("A1", "Hold course", ActionType.NO_ACTION, 0.25, 0.7),
                           AdversaryAction("A2", "Approach", ActionType.MANOEUVRE, 0.75, 0.7)],
        friendly_responses=[FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
                            FriendlyResponse("F1", "Avoid", ActionType.MANOEUVRE, 0.3, 0.8, 1.0)],
        turns=2,
    )
    result = evaluate_scenario(scenario)
    roots = tuple(Node(a, r, score) for (a, r), score in leaves.items())
    selection = select(result.scenario, roots, 1, _MINIMAX, matrix_pick=0)
    tree = GameTree(2, (), roots, 1, None, (), selection)  # type: ignore[arg-type]
    return dataclasses.replace(result, tree=tree)


#: The reviewer's case: Hold 0.3 and 0.5000004, Avoid 0.3000004 and 0.5. Minimax and expected value pick Avoid,
#: minimin Hold, each tied with the other within the tolerance.
_REVIEW_LEAVES = {(0, 0): 0.3, (1, 0): 0.5000004, (0, 1): 0.3000004, (1, 1): 0.5}


class TestATreeTieIsInEnteredOrder:
    def test_every_rule_names_the_same_tie_in_entered_order_and_agrees(self) -> None:
        result = _one_turn_result(_REVIEW_LEAVES)
        ties = tree_turn_one_ties(result)
        assert {rule: _names(tied) for rule, tied in ties.items()} == {rule: ["Hold", "Avoid"] for rule in _RULES}
        compared = compare_rules(result, _MINIMAX)
        assert compared.tree_agree is True
        assert compared.tree_line == (
            "Over the 2 turns, built in full to turn 1 only, all three rules agree on turn 1: each picks a tie between "
            "Hold (F0) and Avoid (F1)."
        )

    def test_each_rule_keeps_its_own_lowest_pick(self) -> None:
        picks = tree_turn_one_picks(_one_turn_result(_REVIEW_LEAVES))
        assert {rule: p.name for rule, p in picks.items() if p is not None} == {
            _MINIMAX: "Avoid", _EV: "Avoid", _MINIMIN: "Hold",
        }

    def test_the_turn_line_names_the_tie_in_entered_order(self) -> None:
        tree = _one_turn_result(_REVIEW_LEAVES).tree
        assert tree is not None and tree.selection is not None
        first = tree.selection.picks[0]
        assert (first.pick, first.choices) == (1, (0, 1))
        line = PICK_TIED_FIRST.format(names="Hold and Avoid", tolerance=TIE_TOLERANCE)
        assert line in tree.selection.recommendation


class TestTheRecordKeepsTheLowestScore:
    def test_a_later_entered_response_scoring_lower_is_the_pick_and_the_tie_is_in_entered_order(self) -> None:
        scenario, matrix = TestTheTolerance()._two(0.4000004, 0.4)
        for rule in _RULES:
            pick = find_robust_response(scenario, matrix, rule)
            assert pick is not None and pick.name == "Y"
            assert _names(tied_responses(scenario, matrix, rule)) == ["X", "Y"]

    def test_the_wording_says_the_lowest_score_not_the_first_entered(self) -> None:
        doc = inspect.getdoc(ScenarioResult.tied_responses) or ""
        assert "lowest" in doc and "first of them" not in doc
        root = Path(__file__).resolve().parents[2]
        guide = " ".join((root / "docs" / "generate_guide.py").read_text("utf-8").split())
        phases = " ".join((root / "docs" / "decision_engine_phases.md").read_text("utf-8").split())
        for text in (guide, phases):
            assert "pick is still the first entered" not in text
            assert "still returns the first tied response" not in text
            assert "the response with the lowest score, as 0.37.0 did" in text


class TestTheToleranceEdges:
    @pytest.mark.parametrize("base", [0.3, 0.7, 0.1, 0.9, 1.7])
    def test_at_exactly_the_tolerance_it_is_a_tie_whatever_the_value(self, base: float) -> None:
        assert tied_with([base, base + TIE_TOLERANCE]) == (0, 1)
        assert tied_with([base + TIE_TOLERANCE, base]) == (0, 1)

    @pytest.mark.parametrize("base", [0.3, 0.7, 0.1, 0.9, 1.7])
    def test_just_past_the_tolerance_it_is_not(self, base: float) -> None:
        assert tied_with([base, base + 6e-7]) == (0,)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_a_score_that_is_not_finite_never_ties(self, bad: float) -> None:
        assert tied_with([bad, 0.4, 0.4]) == (1, 2)
        assert tied_with([bad, bad]) == ()

    def test_a_pick_never_loses_its_tie_set(self) -> None:
        """A value that is not finite never ties: the tie set holds the pick alone, never none. A matrix holding a NaN
        score is refused before any rule picks on it since SPC-221 (evaluation F-32), where 0.41.0 picked by order."""
        from spectre.domain.decision import NonFiniteScoreError, ties_of
        scenario, matrix = TestTheTolerance()._two(math.nan, 0.4)
        with pytest.raises(NonFiniteScoreError):
            find_robust_response(scenario, matrix, _MINIMAX)
        with pytest.raises(NonFiniteScoreError):
            tied_responses(scenario, matrix, _MINIMAX)
        assert ties_of([math.nan, 0.4], 0) == (0,)
        assert ties_of([0.4, 0.4], None) == ()
        assert ties_of([0.4, 0.4], 1) == (0, 1)


class TestTheMatrixLine:
    def test_a_tree_tie_that_holds_the_matrix_pick_does_not_differ_from_it(self) -> None:
        selection = select(_scenario(), _tied_tree(turn_one=True), 2, _MINIMAX, matrix_pick=1)
        assert (selection.picks[0].pick, selection.picks[0].tied) == (0, (1,))
        assert [line for line in selection.recommendation if line.startswith("Over the 2 turns")] == []

    def test_with_no_tie_a_different_matrix_pick_is_said(self) -> None:
        selection = select(_scenario(), _tied_tree(turn_one=False), 2, _MINIMAX, matrix_pick=1)
        line = MATRIX_DIFFERS.format(turns=2, rule="minimax", tree="Hold", matrix="Avoid")
        assert line in selection.recommendation
