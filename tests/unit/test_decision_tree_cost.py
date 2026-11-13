"""A game tree is checked against the branch cap and the cost cap before anything runs (SPC-140).

Branches are the sum over turns k of (rows x responses) to the k. The cost is the cap's own model, in sample-hours:
each arc integrated over what is left of the span with its set-up, each search past an arc's first at 0.3 of a
sample, and 2 arcs and 16 trials to size each burn, counting a repeated path once. Above either cap the tree is
refused, naming what fits, and the one-turn result stands. Since SPC-188 the cost cap is the tree's own,
MAX_TREE_SAMPLE_HOURS, set from trees measured under load (tests/unit/test_decision_tree_own_cap.py).
"""

from __future__ import annotations

import math
from typing import Any, NoReturn

import pytest

from spectre.domain import decision, decision_tree
from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    SET_UP_S_PER_SAMPLE,
    ActionType,
    Scenario,
    evaluate_scenario,
)
from spectre.domain.decision_tree import (
    MAX_TREE_BRANCHES,
    MAX_TREE_SAMPLE_HOURS,
    TREE_OVER_BRANCHES,
    TREE_OVER_CAP,
    branches,
    evaluate_tree,
    largest_tree,
    refused_before_run,
    tree_cost,
)
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import COPLANAR_LEO, PLANE_CHANGE
from tests.unit.test_decision_sampled import _Fake

_STILL = (ActionType.NO_ACTION, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE)


def _never(*_: Any, **__: Any) -> NoReturn:
    raise AssertionError("a later turn ran")


def _two_by_two(n: int, turns: int, turn_h: float, case: Any = COPLANAR_LEO, *, target: float | None = 20.0) -> Scenario:
    """Hold course and Evasive (burning 0.1 of a turn in), against Hold and Avoid: the measured trees."""
    rows = [cases.still(), cases.evasive(case, n=n, offset_h=0.1 * turn_h)]
    return cases.scenario(
        rows, [cases.hold(), cases.avoid(target, hours=0.1 * turn_h)], turns=turns, horizon_h=turns * turn_h, bind=case,
    )


class TestTheBranchCap:
    def test_branches_are_summed_over_turns(self) -> None:
        """11: 5 x 5 makes 25, 650 and 16,275 branches over 1, 2 and 3 turns."""
        assert [branches(5, 5, k) for k in (1, 2, 3)] == [25, 650, 16_275]
        assert MAX_TREE_BRANCHES == 1_000

    def test_a_tree_over_the_branch_cap_is_refused_naming_the_counts_and_what_fits(self) -> None:
        """11: five still rows and five responses, 3 turns."""
        rows = [cases.still(f"Still {i}", f"A{i}", _STILL[i % 3]) for i in range(5)]
        responses = [cases.hold(f"Hold {j}", f"F{j}") for j in range(5)]
        scenario = cases.scenario(rows, responses, turns=3)
        refusal = TREE_OVER_BRANCHES.format(
            turns=3, rows=5, responses=5, nodes=16_275, cap=MAX_TREE_BRANCHES, fits="At these sizes, 2 turns fit.",
        )
        assert "16,275 branches" in refusal
        result = evaluate_tree(scenario)
        assert result.tree is not None
        assert result.tree.refusal == refusal
        assert result.tree.roots == ()
        assert largest_tree(scenario) == 2


class TestTheCostCap:
    def test_a_tree_over_the_cap_is_refused_before_anything_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """12: plane_change with a 1,000-sample Evasive over two 3 h turns; the one-turn matrix stands."""
        monkeypatch.setattr(decision_tree, "continue_series", _never)
        scenario = _two_by_two(1000, 2, 3.0, PLANE_CHANGE, target=None)
        total = tree_cost(scenario)
        assert total > MAX_TREE_SAMPLE_HOURS
        refusal = TREE_OVER_CAP.format(
            turns=2, total=math.ceil(total), cap=MAX_TREE_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
            fits="No tree fits at these sizes: take fewer samples, rows or responses.",
        )
        fake = _Fake()
        result = evaluate_tree(scenario, sampler=fake)
        assert result.tree is not None
        assert result.tree.refusal == refusal
        assert result.tree.roots == ()
        assert len(fake.calls) == 1   # the one-turn row, with no turn boundary kept
        assert result.outcome_matrix[1][0].ca_percentiles is not None
        one = evaluate_scenario(scenario, sampler=_Fake())
        assert [c.composite_score for c in result.outcome_matrix[1]] == [c.composite_score for c in one.outcome_matrix[1]]

    def test_the_cost_is_known_before_anything_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """13: costing integrates nothing."""
        monkeypatch.setattr(decision_tree, "continue_series", _never)
        assert tree_cost(_two_by_two(100, 2, 2.0)) > 0.0


class TestTheCostModelAgainstTheMeasuredTrees:
    """13: the measured prototype trees, Hold course and Evasive against Hold and Avoid at 20 km."""

    @pytest.mark.parametrize(
        ("n", "turns", "turn_h", "case", "fits"),
        [
            (100, 2, 2.0, COPLANAR_LEO, True),     # 15.7 s idle
            (100, 3, 2.0, COPLANAR_LEO, True),     # 59.3 s idle; refused under the 120 s budget, fits 300 s
            (500, 2, 2.0, COPLANAR_LEO, True),     # 67.7 s idle; refused under the 120 s budget, fits 300 s
            (50, 2, 2.0, COPLANAR_LEO, True),      # 10.0 s idle
            (100, 2, 0.5, PLANE_CHANGE, True),     # 5.2 s idle
            (100, 3, 0.5, PLANE_CHANGE, True),     # 19.5 s idle
            # SPC-188, every core of the build container busy: the trees the tree's own cap is set from.
            (300, 2, 1.0, PLANE_CHANGE, True),     # 28.7 s loaded, measured with Avoid not burning
            (200, 2, 2.0, COPLANAR_LEO, True),     # 38.6 s loaded
            (500, 2, 1.0, PLANE_CHANGE, True),     # 50.2 s loaded, Avoid not burning: the slowest, 90.8 a second
            (300, 3, 0.5, PLANE_CHANGE, True),     # 76.5 s loaded, Avoid not burning
            (200, 3, 2.0, COPLANAR_LEO, True),     # over the shared cap of 0.37.0, under the tree's own
            (250, 3, 2.0, COPLANAR_LEO, False),    # over the tree's own cap
        ],
    )
    def test_each_measured_tree_fits_or_is_refused(self, n: int, turns: int, turn_h: float, case: Any, fits: bool) -> None:
        assert (tree_cost(_two_by_two(n, turns, turn_h, case)) <= MAX_TREE_SAMPLE_HOURS) is fits

    def test_the_largest_tree_that_fits(self) -> None:
        """At 200 samples 3 turns of coplanar_leo fit; at 250, 2 fit and 3 do not; at 1,500 no tree fits.
        plane_change's short turns fit 3. Under the shared cap of 0.37.0, 150 samples fitted 2 and 1,000 none."""
        assert largest_tree(_two_by_two(200, 3, 2.0)) == 3
        assert largest_tree(_two_by_two(250, 3, 2.0)) == 2
        assert largest_tree(_two_by_two(100, 3, 0.5, PLANE_CHANGE)) == 3
        assert largest_tree(_two_by_two(1500, 2, 2.0)) == 1

    def test_more_samples_or_turns_never_cost_less(self) -> None:
        costs = [tree_cost(_two_by_two(n, 2, 2.0)) for n in (50, 100, 200)]
        assert costs == sorted(costs)
        assert tree_cost(_two_by_two(100, 3, 2.0)) > tree_cost(_two_by_two(100, 2, 2.0))


def _one_row(turns: int, *responses: Any) -> Scenario:
    """plane_change, one 50-sample Evasive burning 0.05 h in, over 0.5 h turns: small enough to count by hand."""
    rows = [cases.evasive(PLANE_CHANGE, n=50, offset_h=0.05, row_id="A0")]
    return cases.scenario(
        rows, list(responses) or [cases.hold()], turns=turns, horizon_h=0.5 * turns, bind=PLANE_CHANGE,
    )


class TestTheCostModelTermByTerm:
    """12: the model as written, counted by hand on trees small enough to count: one red row of n samples. Each
    turn's red arcs, searches, slices, blue arcs and sizing are charged at what is left of the span with each
    sample's set-up, U; a search past an arc's first at 0.3 of it; a sizing at 2 arcs and 16 trials. An under-count
    would let through the cap a tree the budget cannot run."""

    def test_reds_arcs_are_counted_per_red_path(self) -> None:
        """A still row and a row of n samples: over 2 turns the red paths are SS, SM, MS and MM, 1 + 3n arcs; over
        3 turns, 1 + 7n."""
        assert decision_tree._red_arcs((0, 50), 2) == 1 + 3 * 50
        assert decision_tree._red_arcs((0, 50), 3) == 1 + 7 * 50
        assert decision_tree._red_arcs((50,), 3) == 50
        assert decision_tree._red_arcs((0,), 3) == 1

    def test_turn_one_costs_at_least_its_samples(self) -> None:
        scenario = _one_row(2)
        span_s = decision._searched_span_s(scenario)
        turn_one = decision._turn_one_cost_h(scenario)
        assert turn_one >= 50 * (span_s + SET_UP_S_PER_SAMPLE) / 3600.0
        assert tree_cost(scenario) > turn_one

    def test_turn_one_charges_the_computed_rows_on_rk45(self) -> None:
        """A still row alone, with nothing to sample or size: turn 1 still puts both orbits on RK45 over the span,
        2 arcs with set-up, and Avoid adds its 16 trials; the one-turn evaluation of the same rows costs nothing."""
        u = SET_UP_S_PER_SAMPLE
        holding = cases.scenario([cases.still()], [cases.hold()])
        span_s = decision._searched_span_s(holding)
        assert decision._turn_one_cost_h(holding) == pytest.approx(2 * (span_s + u) / 3600.0)
        burning = cases.scenario([cases.still()], [cases.hold(), cases.avoid(20.0)])
        assert decision._turn_one_cost_h(burning) == pytest.approx((2 + 16) * (span_s + u) / 3600.0)

    def test_two_turns_holding(self) -> None:
        """Turn 1 adds each sample's slice search and red's and blue's arcs again; turn 2 is n red arcs and one blue."""
        scenario = _one_row(2)
        n, u, f = 50, SET_UP_S_PER_SAMPLE, 0.3
        span_s = decision._searched_span_s(scenario)
        turn_s = span_s / 2
        later_s = n * f * (turn_s + u) + 2 * (span_s + u) + (n + 1) * (turn_s + u)
        assert tree_cost(scenario) == pytest.approx(decision._turn_one_cost_h(scenario) + later_s / 3600.0)

    def test_three_turns_holding(self) -> None:
        """Turn 2, not the last, adds each sample's slice search too."""
        scenario = _one_row(3)
        n, u, f = 50, SET_UP_S_PER_SAMPLE, 0.3
        span_s = decision._searched_span_s(scenario)
        turn_s = span_s / 3
        extra = n * f * (turn_s + u) + 2 * (span_s + u)
        second = (n + 1) * (2 * turn_s + u) + n * f * (turn_s + u)
        third = (n + 1) * (turn_s + u)
        expected = decision._turn_one_cost_h(scenario) + (extra + second + third) / 3600.0
        assert tree_cost(scenario) == pytest.approx(expected)

    def test_two_turns_with_a_burn_to_size(self) -> None:
        """Hold and Avoid: turn 1 searches each sample against both blues; turn 2 searches n arcs against 4 blues,
        3 past the first, and sizes Avoid from each of 2 parents at 2 arcs and 16 trials."""
        scenario = _one_row(2, cases.hold(), cases.avoid(20.0, hours=0.02))
        n, u, f = 50, SET_UP_S_PER_SAMPLE, 0.3
        span_s = decision._searched_span_s(scenario)
        turn_s = span_s / 2
        per = turn_s + u
        extra = 2 * n * f * per + 3 * (span_s + u)
        second = n * per + 3 * n * f * per + 4 * per + 2 * (2 + 16) * per
        assert tree_cost(scenario) == pytest.approx(decision._turn_one_cost_h(scenario) + (extra + second) / 3600.0)


class TestTheCapsBoundary:
    def test_a_tree_at_the_cap_fits_and_one_over_it_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scenario = cases.scenario([cases.still()], [cases.hold()])
        monkeypatch.setattr(decision_tree, "tree_cost", lambda _s: float(MAX_TREE_SAMPLE_HOURS))
        assert refused_before_run(scenario) is None
        monkeypatch.setattr(decision_tree, "tree_cost", lambda _s: MAX_TREE_SAMPLE_HOURS + 0.5)
        assert refused_before_run(scenario) == TREE_OVER_CAP.format(
            turns=2, total=math.ceil(MAX_TREE_SAMPLE_HOURS + 0.5), cap=MAX_TREE_SAMPLE_HOURS,
            budget=EVALUATION_BUDGET_S, fits="No tree fits at these sizes: take fewer samples, rows or responses.",
        )
        monkeypatch.setattr(decision_tree, "tree_cost", lambda _s: 1.5 * MAX_TREE_SAMPLE_HOURS)
        assert refused_before_run(scenario) is not None
