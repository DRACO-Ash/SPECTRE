"""A built game tree carries its rule's picks over it (SPC-141), for the view to show (SPC-142).

The selection is the strategy's picks over the turns built in full, with what each turn shows and, under expected
value only, the update after turn 1. A tree refused before anything runs has none. No row's P is touched.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import pytest

from spectre.domain import decision_tree
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import ActionType, RunControl, Scenario, ScenarioBinding, SelectorStrategy
from spectre.domain.decision_tree import evaluate_tree
from spectre.domain.tree_selectors import PARTIAL, select
from spectre.domain.turn_update import Seen
from tests.unit import _decision_tree_cases as cases


def _held(scenario: Scenario) -> Scenario:
    binding = scenario.binding
    assert binding is not None and binding.red is not None
    red = dataclasses.replace(binding.red, custody=CustodyStatus(Custody.HELD, "Custody held."))
    return dataclasses.replace(scenario, binding=ScenarioBinding(red=red, blue=binding.blue))


def _still() -> Scenario:
    """coplanar_leo, Hold course and Posture change against Hold and Avoid with no target, two 3 h turns."""
    rows = [cases.still(), cases.still("Posture", "A1", ActionType.POSTURE_CHANGE)]
    return _held(cases.scenario(rows, [cases.hold(), cases.avoid(None)]))


class TestTheTreeCarriesItsPicks:
    @pytest.mark.parametrize("strategy", list(SelectorStrategy))
    def test_a_built_tree_carries_its_rules_picks(self, strategy: SelectorStrategy) -> None:
        scenario = _still()
        before = copy.deepcopy(scenario.adversary_actions)
        result = evaluate_tree(scenario, strategy)
        tree = result.tree
        assert tree is not None
        assert tree.refusal is None, tree.refusal
        selection = tree.selection
        assert selection is not None
        matrix = scenario.friendly_responses.index(result.robust_best_response)
        assert selection == select(scenario, tree.roots, 2, strategy, matrix_pick=matrix)
        assert selection.strategy is strategy
        assert selection.picks[0].turn == 1
        assert selection.likelihood == (Seen.NO_BURN, Seen.NO_BURN)
        assert (selection.posteriors != ()) is (strategy is SelectorStrategy.EXPECTED_VALUE)
        assert scenario.adversary_actions == before

    def test_a_tree_refused_before_it_runs_has_no_picks(self) -> None:
        scenario = dataclasses.replace(_still(), binding=None)
        tree = evaluate_tree(scenario).tree
        assert tree is not None
        assert tree.refusal is not None
        assert tree.selection is None

    def test_a_tree_stopped_after_turn_one_picks_over_turn_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The clock passes the budget once turn 1 is built, so the picks stop there and say so."""
        clock = {"now": 0.0}
        real = decision_tree.rk45_pair

        def then_late(*args: Any) -> Any:
            clock["now"] = 200.0
            return real(*args)

        monkeypatch.setattr(decision_tree, "rk45_pair", then_late)
        run = RunControl(budget_s=100.0, stop=lambda: None, clock=lambda: clock["now"])
        tree = evaluate_tree(_still(), run=run).tree
        assert tree is not None
        assert tree.complete_turns == 1
        assert tree.selection is not None
        assert tree.selection.turns == 1
        assert PARTIAL.format(k=1, turns=2) in tree.selection.lines

    def test_a_tree_refused_in_turn_one_has_no_picks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "rk45_pair", lambda *_: decision_tree.ElsetFailure("blue", "propagation"))
        tree = evaluate_tree(_still()).tree
        assert tree is not None
        assert tree.complete_turns == 0
        assert tree.selection is None
