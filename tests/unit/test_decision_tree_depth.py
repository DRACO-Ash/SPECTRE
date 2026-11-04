"""The turn depth an operator asks for, refused before anything runs when the tree cannot fit (SPC-142).

The panel offers 1 to 3 turns. A depth whose branches pass the branch cap, or whose cost passes the cost cap, is
refused inline on Evaluate, naming the largest depth that would fit at the same sizes. A tree refused for another
reason first (a side unbound, a row with no orbit to carry on, a burn outside its turn) is not refused here: the
result then says why beside the one-turn matrix, as SPC-140 built it. A tree built in part names the deepest turn
built in full.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from spectre.domain.decision import EVALUATION_BUDGET_S, MAX_SAMPLE_HOURS, ActionType, Scenario
from spectre.domain.decision_tree import (
    MAX_TREE_BRANCHES,
    SENTENCES,
    TREE_DEEPEST,
    TREE_DEPTH_BRANCHES,
    TREE_DEPTH_COST,
    GameTree,
    branches,
    depth_refusal,
    largest_tree,
    refused_before_run,
    tree_cost,
)
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import PLANE_CHANGE
from tests.unit._i13 import i13_problems
from tests.unit.test_decision_tree_cost import _two_by_two

_ONLY_THE_MATRIX = (
    "The largest turn depth that fits at these sizes is 1, the outcome matrix alone: take fewer samples, rows or "
    "responses for a tree."
)
_STILL = (ActionType.NO_ACTION, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE)


def _wide(turns: int, *, bind: Any = cases.COPLANAR_LEO) -> Scenario:
    """Four still rows against three holds: 12, 156 and 1,884 branches over 1, 2 and 3 turns."""
    rows = [cases.still(f"Still {i}", f"A{i}", _STILL[i % 3]) for i in range(4)]
    responses = [cases.hold(f"Hold {j}", f"F{j}") for j in range(3)]
    return cases.scenario(rows, responses, turns=turns, bind=bind)


class TestADepthThatFits:
    def test_one_turn_is_never_refused(self) -> None:
        assert depth_refusal(_wide(1)) is None

    def test_a_tree_inside_both_caps_is_not_refused(self) -> None:
        scenario = _wide(2)
        assert branches(4, 3, 2) == 156
        assert tree_cost(scenario) <= MAX_SAMPLE_HOURS
        assert depth_refusal(scenario) is None


class TestTooManyBranches:
    def test_it_is_refused_naming_the_counts_and_the_largest_depth_that_fits(self) -> None:
        scenario = _wide(3)
        assert largest_tree(scenario) == 2
        expected = TREE_DEPTH_BRANCHES.format(
            turns=3, rows=4, responses=3, nodes=1_884, cap=MAX_TREE_BRANCHES,
            largest="The largest turn depth that fits at these sizes is 2.",
        )
        assert depth_refusal(scenario) == expected
        assert "1,884 branches" in expected
        assert expected.endswith("The largest turn depth that fits at these sizes is 2.")


class TestOverTheCostCap:
    def test_it_is_refused_naming_the_cost_and_that_only_the_matrix_fits(self) -> None:
        """plane_change with a 500-sample Evasive over two 3 h turns costs more than the cap; no tree fits."""
        scenario = _two_by_two(500, 2, 3.0, PLANE_CHANGE, target=None)
        total = tree_cost(scenario)
        assert total > MAX_SAMPLE_HOURS
        assert largest_tree(scenario) == 1
        refusal = depth_refusal(scenario)
        assert refusal == TREE_DEPTH_COST.format(
            turns=2, total=math.ceil(total), cap=MAX_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
            largest=_ONLY_THE_MATRIX,
        )
        assert refusal is not None
        assert refusal.endswith(_ONLY_THE_MATRIX)

    def test_three_turns_over_the_cap_name_two(self) -> None:
        scenario = _two_by_two(100, 3, 2.0)
        assert tree_cost(scenario) > MAX_SAMPLE_HOURS
        assert largest_tree(scenario) == 2
        refusal = depth_refusal(scenario)
        assert refusal is not None
        assert refusal.endswith("The largest turn depth that fits at these sizes is 2.")


class TestARefusalTheResultStates:
    def test_an_unbound_tree_is_left_to_the_result(self) -> None:
        """Unbound, the tree is refused for that first; the result says so beside one turn."""
        scenario = _wide(3, bind=None)
        assert refused_before_run(scenario) is not None
        assert depth_refusal(scenario) is None

    def test_a_burn_outside_its_turn_is_left_to_the_result(self) -> None:
        scenario = cases.scenario([cases.evasive(offset_h=2.5)], [cases.hold()], turns=3, horizon_h=6.0)
        refusal = refused_before_run(scenario)
        assert refusal is not None and "falls outside" in refusal
        assert depth_refusal(scenario) is None


class TestTheDeepestTurnBuiltInFull:
    @pytest.mark.parametrize(("complete", "turns"), [(1, 2), (1, 3), (2, 3)])
    def test_a_tree_built_in_part_names_it(self, complete: int, turns: int) -> None:
        tree = GameTree(turns, (), (), complete, "stopped", ("stopped",))
        assert tree.deepest == TREE_DEEPEST.format(k=complete, turns=turns)
        assert f"turn {complete} of {turns}" in tree.deepest

    @pytest.mark.parametrize(("complete", "turns"), [(2, 2), (3, 3), (0, 2)])
    def test_a_whole_tree_or_none_names_nothing(self, complete: int, turns: int) -> None:
        """A whole tree needs no such line; a tree with no turn built is its refusal alone."""
        assert GameTree(turns, (), (), complete, None, ()).deepest is None


@pytest.mark.parametrize("sentence", (TREE_DEPTH_BRANCHES, TREE_DEPTH_COST, TREE_DEEPEST))
def test_each_new_sentence_is_listed_and_passes_the_house_checks(sentence: str) -> None:
    assert sentence in SENTENCES
    assert i13_problems(sentence) == []
    for bad in ("—", "–", "--", "%"):
        assert bad not in sentence
