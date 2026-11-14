"""Real game trees for the view's tests (SPC-142), each built once.

The still tree is coplanar_leo, Hold course and Posture against Hold and Avoid with no target, two 3 h turns: 20
branches, all computed, in under a second. The sampled tree is plane_change, Hold course and Evasive (50 samples,
burning 0.1 h in) against Hold and Avoid sized to 20 km, over 1 h: Evasive's branches are sampled. Both have the
bound red track's custody read as held, so turn 1 shows a burn under Evasive and no burn under Hold course.
"""

from __future__ import annotations

import dataclasses
from functools import cache

from spectre.domain.decision import ScenarioResult, Seen, SelectorStrategy
from spectre.domain.decision_tree import evaluate_tree
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import PLANE_CHANGE
from tests.unit.test_decision_tree_select import _held, _still


@cache
def still_result(strategy: SelectorStrategy = SelectorStrategy.MINIMAX, observed: Seen | None = None) -> ScenarioResult:
    return evaluate_tree(dataclasses.replace(_still(), observed=observed), strategy)


@cache
def sampled_result(
    strategy: SelectorStrategy = SelectorStrategy.EXPECTED_VALUE, observed: Seen | None = None,
) -> ScenarioResult:
    rows = [cases.still(), cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1)]
    scenario = cases.scenario(rows, [cases.hold(), cases.avoid(20.0, hours=0.05)], horizon_h=1.0, bind=PLANE_CHANGE)
    return evaluate_tree(dataclasses.replace(_held(scenario), observed=observed), strategy)
