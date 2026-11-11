"""The remainder of P carries weight wherever it is weighed, and is said wherever it is counted (SPC-203).

tests/unit/test_decision_p_remainder.py shows the remainder row is added, labelled and refused where it should be.
These show its weight reaches each place that reads it, with cells chosen so the remainder's own scores move the
answer: a test that gave the remainder the same score under every response, or a column's worst case from another
row, could not tell a rule that weighs it from one that does not. Each expected value, pick and crossing below is
derived by hand from the cells written here, never pasted from an output. They also pin how the engine says the
remainder counts: in the tree's size and cost, in the tolerance either side of 1, in the NOTSO interval line at a
sum of 1, in the share beside each P, and in the tree's branch headings.
"""

from __future__ import annotations

import dataclasses
import html
import itertools
import re
from typing import Any

import pytest

from spectre.domain.decision import (
    P_SUM_TOLERANCE,
    REMAINDER_BESIDE_NO_ACTION,
    REMAINDER_NAME,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeMetrics,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
    needs_a_run,
    p_sum_problem,
    with_remainder,
)
from spectre.domain.decision_tree import (
    MAX_TREE_BRANCHES,
    TREE_DEPTH_BRANCHES,
    TREE_OVER_BRANCHES,
    depth_refusal,
    evaluate_tree,
    largest_tree,
    refused_before_run,
    tree_cost,
)
from spectre.domain.tree_selectors import select
from spectre.domain.turn_update import seen_after
from spectre.web.tree_view import tree_view
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_figure_basis import _render, _text
from tests.unit.test_decision_prior_interval import _metrics
from tests.unit.test_decision_prior_interval import _result as interval_result
from tests.unit.test_decision_tree_select import _still
from tests.unit.test_tree_selectors import Node, _tree
from tests.unit.test_tree_selectors import _scenario as selector_scenario

EV, MINIMAX, MINIMIN = SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN
_STILL = (ActionType.NO_ACTION, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE)
#: The sentence that says the remainder counts as one of red's moves, for an operator who listed three rows.
_COUNTED_3 = (
    "Red's moves count the remainder of P, the engine's no-action row, beside your 3 rows: rows whose P sum to 1 "
    "leave no remainder, and one red move fewer."
)


def _responses() -> list[FriendlyResponse]:
    return [FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
            FriendlyResponse("F1", "Avoid", ActionType.MANOEUVRE, 0.1, 0.8, 2.0)]


def _row(p: float, kind: ActionType = ActionType.MANOEUVRE, row_id: str = "A1", name: str = "Approach") -> AdversaryAction:
    return AdversaryAction(row_id, name, kind, p, 0.5)


def _scenario(*rows: AdversaryAction) -> Scenario:
    return Scenario(name="P", epoch_utc=EPOCH, adversary_actions=list(rows), friendly_responses=_responses())


def _matrix(scores: list[list[float]]) -> list[list[OutcomeMetrics]]:
    return [[_metrics(s) for s in row] for row in scores]


def _with_remainder_scored(result: ScenarioResult, remainder: list[float]) -> ScenarioResult:
    """*result* with its remainder row scored *remainder*, one score per response, and its pick taken again."""
    matrix = [*result.outcome_matrix[:-1], [_metrics(s) for s in remainder]]
    return ScenarioResult(
        scenario=result.scenario, outcome_matrix=matrix, ranked_per_adversary=[], computation_time_s=0.0,
        robust_best_response=find_robust_response(result.scenario, matrix, EV), robust_strategy=EV,
    )


class TestEveryRuleWeighsTheRemaindersOwnCells:
    """One row, Approach, at P 0.5, the remainder at 0.5. Approach scores Hold 0.2 and Avoid 0.3; the remainder
    scores Hold 0.6 and Avoid 0.1. With the remainder: minimax's worst cases are 0.6 and 0.3, so Avoid; minimin's
    best 0.2 and 0.1, so Avoid; expected value's 0.5 x 0.2 + 0.5 x 0.6 = 0.4 and 0.5 x 0.3 + 0.5 x 0.1 = 0.2, so
    Avoid. On Approach alone every rule would pick Hold, 0.2 against 0.3: the remainder's cells move each rule."""

    _CELLS = [[0.2, 0.3], [0.6, 0.1]]

    @pytest.mark.parametrize("rule", [MINIMAX, MINIMIN, EV], ids=lambda r: r.value)
    def test_each_rule_picks_avoid_because_of_the_remainder(self, rule: SelectorStrategy) -> None:
        scenario = with_remainder(_scenario(_row(0.5)))
        assert [a.probability for a in scenario.adversary_actions] == [0.5, 0.5]
        assert scenario.adversary_actions[-1].remainder
        pick = find_robust_response(scenario, _matrix(self._CELLS), rule)
        assert pick is not None and pick.name == "Avoid"

    @pytest.mark.parametrize("rule", [MINIMAX, MINIMIN, EV], ids=lambda r: r.value)
    def test_on_the_operators_row_alone_each_rule_would_pick_hold(self, rule: SelectorStrategy) -> None:
        alone = _scenario(_row(1.0))
        pick = find_robust_response(alone, _matrix(self._CELLS[:1]), rule)
        assert pick is not None and pick.name == "Hold"


class TestTheNotsoIntervalWeighsTheRemaindersOwnCells:
    """Row 1, Approach, carries the NOTSO suggestion, P 0.13 in 0.04 to 0.30; row 2 is at 0.5, and the remainder
    takes 1 less both. Approach scores Evade 0.9 and Watch 0.2; row 2 Evade 0.1 and Watch 0.3; the remainder Evade 0.0
    and Watch 0.5. With row 1 at p: Evade 0.9p + 0.05 + 0.0 (0.5 - p) = 0.05 + 0.9p; Watch 0.2p + 0.15 + 0.5 (0.5 - p)
    = 0.4 - 0.3p. They are equal at p = 0.35 / 1.2 = 0.2917, inside the interval and under the cap of 0.5, so Evade
    at 0.13 and Watch above 0.292. Were the remainder not to take up the move, or its scores left out of the
    crossing, Evade would hold across the whole interval."""

    def _result(self) -> ScenarioResult:
        return _with_remainder_scored(interval_result([[0.9, 0.2], [0.1, 0.3]], other_p=0.5), [0.0, 0.5])

    def test_the_pick_changes_where_the_remainders_cells_say(self) -> None:
        (line,) = self._result().interval_lines
        assert line == (
            "Row 1, Approach: expected value recommends Evade at P 0.13, but not across its NOTSO interval, 0.04 to "
            "0.30: above P 0.292 it recommends Watch, with the other rows held at their P and the remainder of P "
            "taking up the difference."
        )

    @pytest.mark.parametrize(("p", "pick"), [(0.13, "Evade"), (0.29, "Evade"), (0.295, "Watch"), (0.30, "Watch")])
    def test_the_hand_lines_agree_either_side_of_the_crossing(self, p: float, pick: str) -> None:
        evade, watch = 0.05 + 0.9 * p, 0.4 - 0.3 * p
        assert ("Evade" if evade < watch else "Watch") == pick


class TestTheTreeWeighsTheRemainder:
    """Hold course at P 0.1 and Evasive at 0.4, custody held, so turn 1 shows whether red burnt; the remainder,
    no adversary action, carries 0.5. Each turn costs, by red's move, Hold 0.0 or Avoid 0.25 against no burn, and
    Hold 0.5 or Avoid 0.2 against Evasive; a sequence's score is its turns' costs added. Expected value's root value
    is checked against every policy that picks by what it has seen, each red path weighed by the P written here."""

    _P = (0.1, 0.4, 0.5)
    _COST = ((0.0, 0.25), (0.5, 0.2), (0.0, 0.25))

    def _scenario(self, turns: int) -> Scenario:
        base = selector_scenario(turns=turns)
        rows = [dataclasses.replace(a, probability=p) for a, p in zip(base.adversary_actions, self._P[:2], strict=True)]
        return with_remainder(dataclasses.replace(base, adversary_actions=rows))

    def _score(self, path: tuple[tuple[int, int], ...]) -> float:
        return sum(self._COST[a][r] for a, r in path)

    def test_one_turn_weighs_the_remainder_by_its_p(self) -> None:
        """Hold 0.4 x 0.5 = 0.2; Avoid 0.1 x 0.25 + 0.4 x 0.2 + 0.5 x 0.25 = 0.23: Hold. Without the remainder's
        weight the rows' shares would be 0.2 and 0.8: Hold 0.4, Avoid 0.21, so Avoid."""
        scenario = self._scenario(1)
        assert scenario.adversary_actions[-1].remainder
        roots = _tree(3, 2, 1, self._score)
        first = select(scenario, roots, 1, EV, matrix_pick=0).picks[0]
        assert first.values == pytest.approx((0.2, 0.23))
        assert first.pick == 0

    def test_two_turns_find_the_best_policy_with_the_remainder_weighed(self) -> None:
        scenario = self._scenario(2)
        turn_s = 3 * 3600.0
        roots = _tree(3, 2, 2, self._score)
        shows = sorted({seen_after(scenario, (a,), turn_s) for a in range(3)})
        means = []
        for r1, second in itertools.product(range(2), itertools.product(range(2), repeat=len(shows))):
            r2 = dict(zip(shows, second, strict=True))
            means.append(sum(
                self._P[a1] * self._P[a2] * self._score(((a1, r1), (a2, r2[seen_after(scenario, (a1,), turn_s)])))
                for a1, a2 in itertools.product(range(3), repeat=2)
            ))
        first = select(scenario, roots, 2, EV, matrix_pick=0).picks[0]
        assert first.pick is not None
        assert first.values[first.pick] == pytest.approx(min(means))

    def test_the_hand_built_tree_is_three_red_moves(self) -> None:
        roots = _tree(3, 2, 1, self._score)
        assert isinstance(roots[0], Node)
        assert {node.action for node in roots} == {0, 1, 2}


class TestTheJudgementInputsLeaveOutTheRemainder:
    def test_the_result_the_page_reads_lists_no_remainder_row(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1)))
        assert result.scenario.adversary_actions[-1].remainder
        sentences = " ".join(line.sentence for line in result.judgement_lines)
        assert "Approach" in sentences
        assert REMAINDER_NAME not in sentences

    def test_the_remainders_p_rests_on_the_weakest_basis_whichever_row_holds_it(self) -> None:
        """A row at the panel's default P, a lookup, listed first, beside one at the operator's own, a judgement:
        the remainder is marked judgement, the weaker, not the first row's."""
        rows = [AdversaryAction("A1", "Quiet", ActionType.NO_ACTION, 0.5, 0.4, probability_edited=False),
                AdversaryAction("A2", "Approach", ActionType.MANOEUVRE, 0.4, 0.8)]
        bases = evaluate_scenario(_scenario(*rows)).row_input_bases
        assert (bases[0].probability.kind.value, bases[1].probability.kind.value) == ("lookup", "judgement")
        assert bases[2].probability.kind.value == "judgement"


class TestWhyTheRemainderStandsApart:
    def test_beside_an_operators_no_action_row_its_source_says_why(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.3), _row(0.2, ActionType.NO_ACTION, "A2", "Stay")))
        assert result.row_sources[-1].endswith(REMAINDER_BESIDE_NO_ACTION)
        assert "this row is the chance that none of them happens" in REMAINDER_BESIDE_NO_ACTION

    def test_with_no_such_row_it_does_not(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.3)))
        assert REMAINDER_BESIDE_NO_ACTION not in result.row_sources[-1]


def _three_still(p: float, turns: int = 3) -> Scenario:
    """Three still rows, each at P *p*, against three holds, bound to coplanar_leo."""
    rows = [cases.still(f"Still {i}", f"A{i}", _STILL[i]) for i in range(3)]
    scenario = cases.scenario(rows, [cases.hold(f"Hold {j}", f"F{j}") for j in range(3)], turns=turns)
    return dataclasses.replace(
        scenario, adversary_actions=[dataclasses.replace(a, probability=p) for a in scenario.adversary_actions],
    )


class TestTheTreeCountsTheRemainderAndSaysSo:
    """Three rows at P 0.3 leave a remainder of 0.1, a fourth red move: 4 moves and 3 responses make 12, 156 and
    1,884 branches over 1, 2 and 3 turns, past the 1,000 cap at 3. At P 1/3 each they sum to 1: 3 moves make 9, 90
    and 819 branches, so 3 turns fit."""

    def test_the_panels_refusal_counts_it_and_names_it(self) -> None:
        expected = TREE_DEPTH_BRANCHES.format(
            turns=3, rows=4, responses=3, nodes=1_884, cap=MAX_TREE_BRANCHES,
            largest="The largest turn depth that fits at these sizes is 2.",
        )
        assert depth_refusal(_three_still(0.3)) == f"{expected} {_COUNTED_3}"
        assert depth_refusal(_three_still(1 / 3)) is None

    def test_the_largest_depth_counts_it(self) -> None:
        assert (largest_tree(_three_still(0.3)), largest_tree(_three_still(1 / 3))) == (2, 3)

    def test_the_cost_counts_it(self) -> None:
        below, at_one = _three_still(0.3), _three_still(1 / 3)
        assert tree_cost(below) == tree_cost(with_remainder(below))
        assert tree_cost(below) > tree_cost(at_one)

    def test_the_refusal_before_a_run_counts_it_and_names_it(self) -> None:
        expected = TREE_OVER_BRANCHES.format(
            turns=3, rows=4, responses=3, nodes=1_884, cap=MAX_TREE_BRANCHES, fits="At these sizes, 2 turns fit.",
        )
        assert refused_before_run(_three_still(0.3)) == f"{expected} {_COUNTED_3}"
        assert refused_before_run(_three_still(1 / 3)) is None

    def test_whether_a_run_is_needed_counts_it(self) -> None:
        """A lookup manoeuvre row runs nothing; at P 0.5 the remainder, a no-action row bound to both orbits, is
        computed, so Avoid's burn is sized against it."""
        def one(p: float) -> Scenario:
            scenario = cases.scenario([_row(1.0)], [cases.hold(), cases.avoid(20.0)], turns=1)
            return dataclasses.replace(
                scenario, adversary_actions=[dataclasses.replace(scenario.adversary_actions[0], probability=p)],
            )

        assert (needs_a_run(one(1.0)), needs_a_run(one(0.5))) == (False, True)

    def test_the_built_trees_header_is_followed_by_the_line_that_names_it(self) -> None:
        rows = [dataclasses.replace(a, probability=p) for a, p in zip(_still().adversary_actions, (0.2, 0.3),
                                                                       strict=True)]
        tree = evaluate_tree(dataclasses.replace(_still(), adversary_actions=rows), EV).tree
        assert tree is not None and tree.refusal is None
        assert ": 3 red moves and 2 responses each turn" in tree.lines[0]
        assert tree.lines[1] == (
            "Red's moves count the remainder of P, the engine's no-action row, beside your 2 rows: rows whose P sum "
            "to 1 leave no remainder, and one red move fewer."
        )

    def test_at_a_sum_of_1_nothing_is_said(self) -> None:
        tree = evaluate_tree(_still(), EV).tree
        assert tree is not None
        assert not any("remainder" in line for line in tree.lines)


class TestTheToleranceEitherSideOf1:
    def test_a_remainder_within_the_tolerance_adds_no_row(self) -> None:
        scenario = _scenario(_row(1.0 - P_SUM_TOLERANCE / 2))
        assert with_remainder(scenario) is scenario

    def test_a_remainder_just_past_the_tolerance_adds_its_row(self) -> None:
        rows = with_remainder(_scenario(_row(1.0 - 2 * P_SUM_TOLERANCE))).adversary_actions
        assert rows[-1].remainder
        assert rows[-1].probability == pytest.approx(2 * P_SUM_TOLERANCE, rel=1e-6)

    def test_the_panel_takes_a_sum_within_the_tolerance_above_as_the_scenario_does(self) -> None:
        rows = [_row(0.5), _row(0.5 + P_SUM_TOLERANCE / 2, ActionType.SENSOR_RETASK, "A2", "Retask")]
        assert p_sum_problem(rows) is None
        assert _scenario(*rows).adversary_actions == rows

    def test_the_panel_refuses_just_past_it_as_the_scenario_does(self) -> None:
        rows = [_row(0.5), _row(0.5 + 2 * P_SUM_TOLERANCE, ActionType.SENSOR_RETASK, "A2", "Retask")]
        problem = p_sum_problem(rows)
        assert problem is not None and "above 1" in problem
        with pytest.raises(ValueError, match="above 1"):
            _scenario(*rows)


class TestTheIntervalAtASumOf1SaysWhatIsTrue:
    def test_one_row_says_a_lower_p_would_be_weighed_by_a_remainder_this_evaluation_did_not_evaluate(self) -> None:
        (line,) = interval_result([[0.9, 0.2], [0.1, 0.3]], other_p=0.87).interval_lines
        assert line == (
            "Row 1, Approach: expected value's pick is not checked across its NOTSO interval, 0.04 to 0.30: your "
            "rows' P sum to 1, so a higher P for this row would sum above 1, which is refused, and a lower one would "
            "leave a remainder of P, whose row this evaluation did not evaluate, since your rows left none. With your "
            "rows' P summing below 1 the remainder row is evaluated, and this interval is checked."
        )
        assert "no row to weigh it" not in line


class TestTheShareReadsAsItsP:
    """The share beside each P is P itself, so it is written as the P beside it is; the remainder's, 1 less the
    rows' sum, is written to the ninth decimal at most, both as P and as share."""

    def _page(self, *ps: float) -> str:
        kinds = (ActionType.MANOEUVRE, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE, ActionType.NO_ACTION)
        rows = [_row(p, kinds[i], f"A{i}", f"Row {i}") for i, p in enumerate(ps)]
        return html.unescape(_text(_render(evaluate_scenario(_scenario(*rows)))))

    def test_a_p_of_0_reads_the_same_as_its_share(self) -> None:
        assert "P=0.0 (judgement) · Share=0.0 (judgement)" in self._page(0.0)

    def test_a_p_held_within_the_tolerance_reads_the_same_as_its_share(self) -> None:
        text = self._page(0.25, 0.25, 0.25, 0.2500000001)
        assert "P=0.2500000001 (judgement) · Share=0.2500000001 (judgement)" in text

    def test_the_remainders_p_and_share_read_alike(self) -> None:
        text = self._page(0.1, 0.2)
        assert "P=0.7 (judgement) · Share=0.7 (judgement) · Conf: none" in text
        result = evaluate_scenario(_scenario(_row(0.1), _row(0.2, ActionType.SENSOR_RETASK, "A2", "Retask")))
        assert result.row_share_texts == result.row_p_texts == ("0.1", "0.2", "0.7")


class TestTheRemainderIsLabelledInEachPlace:
    _LABEL = "No adversary action (remainder of P): the engine's remainder, not your row"

    def _html(self) -> str:
        return _render(evaluate_scenario(_scenario(_row(0.1))))

    def test_in_the_matrix(self) -> None:
        cell = re.search(r'<div class="remainder-row"[^>]*>(.*?)</div>', self._html(), re.DOTALL)
        assert cell is not None
        assert html.unescape(cell.group(1)).strip() == self._LABEL

    def test_in_the_rankings(self) -> None:
        heading = re.search(r'<div class="remainder-ranking"[^>]*>(.*?)</div>', self._html(), re.DOTALL)
        assert heading is not None
        assert " ".join(html.unescape(heading.group(1)).split()) == self._LABEL


def _tree_result() -> Any:
    rows = [dataclasses.replace(a, probability=p) for a, p in zip(_still().adversary_actions, (0.2, 0.3), strict=True)]
    return evaluate_tree(dataclasses.replace(_still(), adversary_actions=rows), EV)


class TestTheTreeBranchHeadings:
    def test_a_remainder_branch_is_headed_plainly_and_labelled_beside_it(self) -> None:
        view = tree_view(_tree_result())
        assert view is not None
        nodes = [node for root in view.nodes for node in (root, *root.children)]
        remainder = [n for n in nodes if REMAINDER_NAME in n.heading]
        assert remainder
        for node in remainder:
            assert re.fullmatch(rf"Turn \d of 2: red {re.escape(REMAINDER_NAME)}, our \w+", node.heading)
            assert node.remainder == "(red's move here is the engine's remainder, not your row)"
        assert all(n.remainder == "" for n in nodes if REMAINDER_NAME not in n.heading)
