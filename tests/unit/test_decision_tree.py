"""A multi-turn game tree of 1 to 3 turns (SPC-140).

Turn 2 starts where turn 1 left both orbits: red after its hypothesised burn, sample by sample, and blue after our
sized burn, both on RK45 with J2 and drag. Nothing in a tree is SGP4 after the scenario epoch, since no element set
exists for an orbit after a burn. Each node's figures run from its turn's start to the end of the span, as if no one
moves again, and carry their basis; a sequence's figures combine the nodes along it. A tree that does not fit the
branch cap, the cost cap or the budget says so and keeps the one-turn result; it is never cut short silently.
"""

from __future__ import annotations

import copy
import dataclasses
import re
from datetime import timedelta
from typing import Any

import numpy as np
import pytest

from spectre.astro.elset_approach import ELSET_PROPAGATOR
from spectre.astro.monte_carlo import SEPARATION_PROPAGATOR, burnt_arc, elset_state, rk45_arc
from spectre.astro.response_burn import RESPONSE_PROPAGATOR
from spectre.domain import decision, decision_tree
from spectre.domain.custody import Custody, CustodyStatus, Horizon, custody_over_horizon
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    BoundElset,
    EvaluationStoppedError,
    RunControl,
    Scenario,
    ScenarioResult,
    evaluate_scenario,
    needs_a_run,
)
from spectre.domain.decision_tree import (
    SENTENCES,
    TREE_BRANCH_REFUSED,
    TREE_BUDGET,
    TREE_BURN_OUTSIDE,
    TREE_LOOKUP_ROW,
    TREE_NODE_MEANS,
    TREE_PATH_MEANS,
    TREE_PROPAGATOR,
    TREE_RED_AGAIN,
    TREE_REFUSED_ROW,
    TREE_RESPONSE_AGAIN,
    TREE_UNBOUND,
    GameTree,
    PathStep,
    _require_tree_propagator,
    evaluate_tree,
    paired_minima,
    path_figures,
)
from spectre.domain.provenance import Basis
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, PLANE_CHANGE, REFERENCE_CASES, ReferenceCase
from tests.unit._i13 import i13_problems
from tests.unit.test_decision_sampled import _bound, _Fake


def _figures(result: ScenarioResult) -> list[list[tuple[float, float, float]]]:
    """Each cell's closest approach, delta-V and score, to compare a refused tree's result with one turn's."""
    return [
        [(c.closest_approach_km, c.delta_v_cost_km_s, c.composite_score) for c in row] for row in result.outcome_matrix
    ]


def _assert_one_turn_kept(scenario: Scenario, result: ScenarioResult, refusal: str) -> None:
    tree = result.tree
    assert tree is not None
    assert tree.refusal == refusal
    assert tree.lines == (refusal,)
    assert tree.roots == ()
    assert tree.complete_turns == 0
    assert refusal.endswith("This result is one turn.")
    assert _figures(result) == _figures(evaluate_scenario(scenario))


class TestTurnsRunFromOneToThree:
    @pytest.mark.parametrize("turns", [0, 4, -1])
    def test_turns_outside_one_to_three_are_refused(self, turns: int) -> None:
        """1."""
        with pytest.raises(ValueError, match="turns"):
            dataclasses.replace(_bound(), turns=turns)

    def test_the_default_is_one_turn_and_three_is_the_most(self) -> None:
        """1."""
        assert _bound().turns == 1
        assert decision.MAX_TURNS == 3
        assert dataclasses.replace(_bound(), turns=3).turns == 3

    def test_a_turn_count_that_is_not_a_whole_number_is_refused(self) -> None:
        """1: 2.5 turns, and True, which Python counts as 1."""
        with pytest.raises(ValueError, match="turns"):
            dataclasses.replace(_bound(), turns=2.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="turns"):
            dataclasses.replace(_bound(), turns=True)


class TestOneTurnIsUnchanged:
    def test_a_one_turn_result_carries_no_tree(self) -> None:
        """2."""
        result = evaluate_scenario(_bound(), sampler=_Fake())
        assert result.tree is None
        assert isinstance(result.scenario, Scenario)


class TestATreeNeedsBothSidesBound:
    @pytest.mark.parametrize("which", ["unbound", "red only", "blue out of date"])
    def test_an_unbound_or_unearned_tree_is_refused_and_keeps_one_turn(self, which: str) -> None:
        """3."""
        rows, responses = [cases.still()], [cases.hold(), cases.avoid()]
        if which == "unbound":
            scenario = cases.scenario(rows, responses, bind=None)
        elif which == "red only":
            scenario = cases.scenario(rows, responses, bind=decision.ScenarioBinding(red=cases.bound("red")))
        else:
            out_of_date = decision.ScenarioBinding(red=cases.bound("red"), blue=cases.bound("blue", age=30.0))
            scenario = cases.scenario(rows, responses, bind=out_of_date)
        _assert_one_turn_kept(scenario, evaluate_tree(scenario), TREE_UNBOUND)


class TestALookupRowRefusesTheTree:
    def test_a_manoeuvre_with_no_hypothesis_is_named(self) -> None:
        """4."""
        raise_ = AdversaryAction("A1", "Raise", ActionType.MANOEUVRE, 0.5, 0.7)
        scenario = cases.scenario([cases.still(), raise_], [cases.hold()])
        refusal = TREE_LOOKUP_ROW.format(row=2, name="Raise")
        _assert_one_turn_kept(scenario, evaluate_tree(scenario), refusal)

    def test_a_row_refused_before_it_runs_is_named(self) -> None:
        """4: 10 samples are fewer than the convergence check needs, so row 2's closest approach is refused."""
        scenario = cases.scenario([cases.still(), cases.evasive(n=10)], [cases.hold()], horizon_h=1.0)
        refusal = TREE_REFUSED_ROW.format(row=2, name="Evasive")
        _assert_one_turn_kept(scenario, evaluate_tree(scenario), refusal)


class TestEveryBurnFallsInsideItsOwnTurn:
    def test_a_response_executing_after_its_turn_ends_is_named(self) -> None:
        """16: a 3 h time to execute against 2 h turns."""
        scenario = cases.scenario([cases.still()], [cases.hold(), cases.avoid(hours=3.0)], horizon_h=4.0)
        refusal = TREE_BURN_OUTSIDE.format(what="Avoid's burn", h=3.0, turn_h=2.0)
        _assert_one_turn_kept(scenario, evaluate_tree(scenario), refusal)

    @pytest.mark.parametrize("offset_h", [2.5, 2.0])
    def test_a_red_burn_outside_its_turn_is_named(self, offset_h: float) -> None:
        """16: after the turn ends, or as it ends."""
        scenario = cases.scenario([cases.still(), cases.evasive(offset_h=offset_h)], [cases.hold()], horizon_h=4.0)
        refusal = TREE_BURN_OUTSIDE.format(what="Evasive's burn", h=offset_h, turn_h=2.0)
        result = evaluate_tree(scenario, sampler=_Fake())
        assert result.tree is not None
        assert result.tree.refusal == refusal
        assert result.tree.roots == ()

    def test_a_response_with_no_burn_may_take_longer_than_a_turn(self) -> None:
        """16: only a burn must fall inside its turn; a posture change taking 3 h burns nothing."""
        posture = dataclasses.replace(cases.hold("Posture"), action_type=ActionType.POSTURE_CHANGE, time_to_execute_hours=3.0)
        scenario = cases.scenario([cases.still()], [cases.hold(), posture], horizon_h=4.0)
        tree = evaluate_tree(scenario).tree
        assert tree is not None
        assert tree.refusal is None


# ── Built trees, each evaluated once ──

@pytest.fixture(scope="module")
def still_tree() -> ScenarioResult:
    """coplanar_leo, Hold course against Hold and Avoid with no target, two 3 h turns: nothing burns."""
    scenario = cases.scenario([cases.still()], [cases.hold(), cases.avoid(None)])
    return evaluate_tree(scenario)


@pytest.fixture(scope="module")
def sampled_tree() -> ScenarioResult:
    """plane_change, Hold course and a 50-sample Evasive burning 0.1 h in, against Hold and Avoid at 20 km
    executing 0.05 h in, over two 0.5 h turns."""
    rows = [cases.still(), cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1)]
    scenario = cases.scenario(rows, [cases.hold(), cases.avoid(20.0, hours=0.05)], horizon_h=1.0, bind=PLANE_CHANGE)
    return evaluate_tree(scenario)


def _tree(result: ScenarioResult) -> GameTree:
    tree = result.tree
    assert tree is not None
    assert tree.refusal is None, tree.refusal
    return tree


class TestTurnOneOfATreeIsTheMatrix:
    @pytest.mark.parametrize("which", ["still_tree", "sampled_tree"])
    def test_each_root_is_its_cell(self, which: str, request: pytest.FixtureRequest) -> None:
        """5: row by row, one root per cell, with the cell's figure unrounded, its basis and its delta-V."""
        result = request.getfixturevalue(which)
        roots = _tree(result).roots
        cells = [(i, j, c) for i, row in enumerate(result.outcome_matrix) for j, c in enumerate(row)]
        assert [(r.turn, r.action, r.response) for r in roots] == [(1, i, j) for i, j, _ in cells]
        for root, (_, _, cell) in zip(roots, cells, strict=True):
            if cell.ca_computed is not None:
                assert root.figures.closest_approach_km == cell.ca_computed.approach.miss_km
                assert root.figures.propagator == cell.ca_computed.propagator == RESPONSE_PROPAGATOR
            else:
                assert cell.ca_percentiles is not None
                assert root.figures.closest_approach_km == cell.ca_percentiles[5]
                assert root.figures.band == cell.ca_percentiles
                assert root.figures.propagator == SEPARATION_PROPAGATOR
            assert round(root.figures.closest_approach_km, 1) == cell.closest_approach_km
            assert root.figures.bases == cell.figure_bases
            assert round(root.figures.delta_v_km_s, 5) == cell.delta_v_cost_km_s
            assert root.path_closest_km == root.figures.closest_approach_km
            assert root.path_score == pytest.approx(cell.composite_score, abs=1e-6)


class TestNoTreeFigureIsSgp4:
    @pytest.mark.parametrize("which", ["still_tree", "sampled_tree"])
    def test_no_node_and_no_cell_is_sgp4(self, which: str, request: pytest.FixtureRequest) -> None:
        """6: the still row's cells too, though nothing burns, with the SGP4 figure shown beside them."""
        result = request.getfixturevalue(which)
        tree = _tree(result)
        assert all(n.figures.propagator != ELSET_PROPAGATOR for n in tree.nodes())
        cells = [c for row in result.outcome_matrix for c in row if c.ca_computed is not None]
        assert cells
        assert all(c.ca_computed is not None and c.ca_computed.propagator == RESPONSE_PROPAGATOR for c in cells)
        assert result.rk45_reference is not None
        sgp4, rk45 = result.rk45_reference
        assert sgp4.propagator == ELSET_PROPAGATOR
        assert rk45.propagator == RESPONSE_PROPAGATOR
        assert result.rk45_reference_line is not None

    def test_one_turn_with_nothing_burning_stays_on_sgp4(self) -> None:
        """6: the forcing is the tree's alone; the same scenario at one turn is unchanged."""
        scenario = cases.scenario([cases.still()], [cases.hold(), cases.avoid(None)], turns=1)
        result = evaluate_tree(scenario)
        assert result.tree is None
        assert {c.ca_computed.propagator for row in result.outcome_matrix for c in row if c.ca_computed} == {
            ELSET_PROPAGATOR,
        }

    def test_the_invariant_refuses_an_sgp4_figure_in_a_tree(self, still_tree: ScenarioResult) -> None:
        """6: built by hand, a tree with one SGP4 cell is refused."""
        tree = _tree(still_tree)
        cell = still_tree.outcome_matrix[0][0]
        assert cell.ca_computed is not None
        sgp4 = cell.ca_computed._replace(propagator=ELSET_PROPAGATOR)
        matrix = [[dataclasses.replace(cell, ca_computed=sgp4)]]
        with pytest.raises(ValueError, match="never SGP4"):
            _require_tree_propagator(tree, matrix)
        _require_tree_propagator(dataclasses.replace(tree, roots=()), matrix)   # no tree built, nothing to hold


class TestOneTurnThroughTheTreeIsUnchanged:
    @pytest.mark.parametrize("case", REFERENCE_CASES, ids=lambda c: c.name)
    def test_the_reference_cases_at_one_turn(self, case: ReferenceCase) -> None:
        """2: a still row against Hold and an Avoid with no target, bound to each reference pair."""
        scenario = cases.scenario(
            [cases.still()], [cases.hold(), cases.avoid(None)], turns=1, horizon_h=case.horizon_hours, bind=case,
        )
        tree, one = evaluate_tree(scenario), evaluate_scenario(scenario)
        assert tree.tree is None
        assert _figures(tree) == _figures(one)
        assert [c.ca_computed for row in tree.outcome_matrix for c in row] == [
            c.ca_computed for row in one.outcome_matrix for c in row
        ]

    def test_the_sixteen_cell_sampled_fake_at_one_turn(self) -> None:
        """2: tests/unit/test_decision_sampled.py's grid, its first row sampled by a fake."""
        tree, one = evaluate_tree(_bound(), sampler=_Fake()), evaluate_scenario(_bound(), sampler=_Fake())
        assert tree.tree is None
        assert _figures(tree) == _figures(one)
        assert tree.row_notes == one.row_notes


@pytest.fixture(scope="module")
def avoided() -> ScenarioResult:
    """7: coplanar_leo, Avoid burning 3.085 m/s at the epoch, two 3 h turns."""
    return evaluate_tree(cases.scenario([cases.still()], [cases.hold(), cases.avoid(20.0)]))


class TestTurnTwoStartsFromTurnOnesArcs:
    def test_the_childs_blue_starts_on_the_burnt_arc(self, avoided: ScenarioResult) -> None:
        """7: within 1e-9 km of turn 1's burnt RK45 arc, and more than 1 km from where SGP4 puts the element set."""
        cell = avoided.outcome_matrix[0][1]
        assert cell.ca_response is not None
        burn = cell.ca_response.sized.burn
        assert burn is not None
        assert cell.delta_v_cost_km_s == pytest.approx(0.003085, rel=0.01)
        blue0 = elset_state(COPLANAR_LEO.blue_tle, EPOCH)
        assert blue0 is not None
        coast = rk45_arc(blue0.state_eci_km, 6 * 3600.0, blue0.bstar)
        assert coast is not None
        burnt = burnt_arc(coast, burn, 6 * 3600.0, blue0.bstar)
        assert burnt is not None
        sgp4 = elset_state(COPLANAR_LEO.blue_tle, EPOCH + timedelta(hours=3))
        assert sgp4 is not None
        root = _tree(avoided).roots[1]
        for child in root.children:
            assert child.start.at_s == 3 * 3600.0
            np.testing.assert_allclose(child.start.blue, burnt(3 * 3600.0), atol=1e-9, rtol=0.0)
            assert np.linalg.norm(child.start.blue[:3] - sgp4.state_eci_km[:3]) > 1.0
            assert child.start.our_dv_km_s == pytest.approx(float(np.linalg.norm(burn.delta_v_ric_km_s)))

    def test_the_childs_red_starts_on_turn_ones_red_arc(self, avoided: ScenarioResult) -> None:
        """7: the still row's red, carried by RK45 from its SGP4 state at the epoch."""
        red0 = elset_state(COPLANAR_LEO.red_tle, EPOCH)
        assert red0 is not None
        arc = rk45_arc(red0.state_eci_km, 6 * 3600.0, red0.bstar)
        assert arc is not None
        for child in _tree(avoided).roots[0].children:
            np.testing.assert_allclose(child.start.red[0], arc(3 * 3600.0), atol=1e-9, rtol=0.0)
            assert child.start.red.shape == (1, 6)

    def test_a_hold_parents_child_starts_on_the_unburnt_arc(self, avoided: ScenarioResult) -> None:
        """7."""
        blue0 = elset_state(COPLANAR_LEO.blue_tle, EPOCH)
        assert blue0 is not None
        coast = rk45_arc(blue0.state_eci_km, 6 * 3600.0, blue0.bstar)
        assert coast is not None
        for child in _tree(avoided).roots[0].children:
            np.testing.assert_allclose(child.start.blue, coast(3 * 3600.0), atol=1e-9, rtol=0.0)
            assert child.start.our_dv_km_s == 0.0

    def test_a_target_is_sized_again_in_turn_two(self, avoided: ScenarioResult) -> None:
        """7: after Hold in turn 1 the pair still passes within 20 km, so Avoid burns in turn 2; after Avoid it
        does not need to."""
        roots = _tree(avoided).roots
        hold_then_avoid, avoid_then_avoid = roots[0].children[1], roots[1].children[1]
        assert hold_then_avoid.figures.delta_v_km_s > 0.0
        assert hold_then_avoid.figures.closest_approach_km >= 20.0 * 0.99
        assert hold_then_avoid.figures.bases.delta_v_cost_km_s.kind is Basis.COMPUTED
        assert avoid_then_avoid.figures.delta_v_km_s == 0.0
        assert avoid_then_avoid.path.delta_v_km_s == pytest.approx(roots[1].figures.delta_v_km_s)


class TestAPathsClosestApproachIsItsSmallestOverTurns:
    def test_a_computed_path_takes_the_smaller_of_its_slices(self, still_tree: ScenarioResult) -> None:
        """9: turn 1's slice to turn 2's start, then turn 2 to the span's end."""
        for root in _tree(still_tree).roots:
            for child in root.children:
                assert child.path_closest_km == min(root.figures.slice_min_km[0], child.figures.closest_approach_km)

    def test_a_sampled_path_is_p5_of_each_samples_own_minimum(self, sampled_tree: ScenarioResult) -> None:
        """9: P5 over samples of each sample's smaller minimum, sample k with sample k."""
        root = _tree(sampled_tree).roots[2]   # Evasive against Hold
        assert len(root.figures.slice_min_km) == 50
        for child in root.children:
            minima = paired_minima(np.array(root.figures.slice_min_km), np.array(child.figures.slice_min_km))
            assert child.path_closest_km == pytest.approx(float(np.percentile(minima, 5)))

    @pytest.mark.parametrize(("first", "second"), [(12.0, 30.0), (30.0, 12.0)])
    def test_either_order_gives_the_smaller(self, first: float, second: float) -> None:
        """9: slice minima of 12 km then 30 km, and 30 km then 12 km, both give 12 km."""
        assert paired_minima(np.array([first]), np.array([second])).tolist() == [12.0]


def _held() -> BoundElset:
    return dataclasses.replace(cases.bound("red"), custody=CustodyStatus(Custody.HELD, "Custody held."))


class TestPathFigures:
    def test_our_burns_add_up_and_custody_takes_the_earliest_red_burn(self) -> None:
        """10: hand-built steps; custody is custody_over_horizon given the earliest burn."""
        rows, responses = [cases.still(), cases.evasive()], [cases.hold(), cases.avoid(20.0)]
        scenario = cases.scenario(rows, responses, bind=decision.ScenarioBinding(red=_held(), blue=cases.bound("blue")))
        early, late = EPOCH + timedelta(hours=1), EPOCH + timedelta(hours=4)
        steps = [
            PathStep(rows[1], responses[1], 0.003, late),
            PathStep(rows[0], responses[0], 0.0),
            PathStep(rows[1], responses[1], 0.002, early),
        ]
        figures = path_figures(scenario, steps, 25.0, sampled=False)
        assert figures.delta_v_km_s == pytest.approx(0.005)
        over = custody_over_horizon(
            CustodyStatus(Custody.HELD, "Custody held."), elset_hours=0.0, limit_hours=24.0,
            horizon=Horizon(EPOCH, 6.0, early),
        )
        assert (figures.custody_maintained, figures.custody_gap_hours) == (over.maintained, over.lost_hours)
        assert figures.custody_gap_hours == pytest.approx(5.0)
        assert figures.custody_bases[0].kind is Basis.COMPUTED
        assert figures.time_to_execute_hours == 0.0
        assert figures.reversibility == 0.8
        standing = dataclasses.replace(responses[1], time_to_execute_hours=0.0, reversibility=0.8)
        expected = decision._score(scenario, standing, decision._Figures(False, 5.0, 25.0, 0.005))
        assert figures.score == pytest.approx(expected)
        assert figures.closest_approach_km == 25.0

    def test_time_to_execute_is_summed_and_capped_and_the_least_reversible_counts(self) -> None:
        """10."""
        rows = [cases.still()]
        slow = dataclasses.replace(cases.hold("Slow"), time_to_execute_hours=4.0, reversibility=0.3)
        scenario = cases.scenario(rows, [slow])
        steps = [PathStep(rows[0], slow, 0.0), PathStep(rows[0], cases.hold(), 0.0)] * 2
        figures = path_figures(scenario, steps, 50.0, sampled=False)
        assert figures.time_to_execute_hours == 6.0
        assert figures.reversibility == 0.3

    def test_without_custody_read_the_worst_turns_rule_of_thumb_stands(self) -> None:
        """10: a lookup, as one turn's is."""
        rows, responses = [cases.still(), cases.evasive()], [cases.hold()]
        scenario = cases.scenario(rows, responses)
        steps = [PathStep(rows[0], responses[0], 0.0), PathStep(rows[1], responses[0], 0.0)]
        figures = path_figures(scenario, steps, 9.0, sampled=False)
        assert figures.custody_maintained is False
        assert figures.custody_gap_hours == pytest.approx(6.0 * 0.7)
        assert figures.custody_bases[0].kind is Basis.LOOKUP


class _Clock:
    """A clock that reads 0 until told to jump."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestTheBudget:
    def test_a_budget_spent_after_turn_one_keeps_turn_one_and_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """14: the clock passes the run's 100 s budget once turn 1 is built; turn 2 never starts."""
        clock = _Clock()
        real = decision_tree.rk45_pair

        def then_late(*args: Any) -> Any:
            clock.now = 200.0
            return real(*args)

        monkeypatch.setattr(decision_tree, "rk45_pair", then_late)
        scenario = cases.scenario([cases.still()], [cases.hold(), cases.avoid(None)])
        result = evaluate_tree(scenario, run=RunControl(budget_s=100.0, stop=lambda: None, clock=clock))
        tree = result.tree
        assert tree is not None
        assert tree.complete_turns == 1
        refusal = TREE_BUDGET.format(turns=2, budget=100.0, k=2, done=2, total=6, last=1)
        assert tree.refusal == refusal
        assert tree.lines[-1] == refusal
        assert len(tree.roots) == 2
        assert all(root.children == () for root in tree.roots)

    def test_a_stop_mid_tree_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """15: as a stop in one turn does, with no result."""
        stopping = {"now": False}
        real = decision_tree.continue_series

        def then_stop(*args: Any, **kwargs: Any) -> Any:
            stopping["now"] = True
            return real(*args, **kwargs)

        monkeypatch.setattr(decision_tree, "continue_series", then_stop)
        rows = [cases.still(), cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1)]
        scenario = cases.scenario(rows, [cases.hold()], horizon_h=1.0, bind=PLANE_CHANGE)
        run = RunControl(budget_s=120.0, stop=lambda: "Superseded." if stopping["now"] else None)
        with pytest.raises(EvaluationStoppedError, match="Superseded"):
            evaluate_tree(scenario, run=run)


def _flat(result: ScenarioResult) -> list[tuple[Any, ...]]:
    return [
        (n.turn, n.action, n.response, n.figures.closest_approach_km, n.figures.slice_min_km, n.path_closest_km,
         n.path_score, n.start.seed, n.figures.tca_utc)
        for n in _tree(result).nodes()
    ]


class TestSameInputsSameTree:
    def test_the_same_evaluation_twice_gives_the_same_tree(self, sampled_tree: ScenarioResult) -> None:
        """17: seeds come from the row's seed, the turn and the path, never the clock or an object's identity."""
        again = evaluate_tree(copy.deepcopy(sampled_tree.scenario))
        assert _flat(again) == _flat(sampled_tree)
        assert len({n.start.seed for n in _tree(again).nodes() if n.turn == 2}) > 1


class TestABranchThatDoesNotConvergeWithholdsTheTree:
    @pytest.mark.parametrize(
        ("change", "why"),
        [
            ({"converged": False, "percentile_half_width_km": 3.25},
             "did not converge: its P5, P50 and P95 are known only to within 3.2 km"),
            ({"n_failed": 1}, "lost 1 of 50 samples, which failed to propagate"),
        ],
        ids=["unconverged", "failed"],
    )
    def test_a_bad_series_refuses_with_the_branch_named(
        self, change: dict[str, Any], why: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """18."""
        real = decision_tree.continue_series

        def spoilt(*args: Any, **kwargs: Any) -> Any:
            out = real(*args, **kwargs)
            return out._replace(series=(dataclasses.replace(out.series[0], **change), *out.series[1:]))

        monkeypatch.setattr(decision_tree, "continue_series", spoilt)
        rows = [cases.still(), cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1)]
        scenario = cases.scenario(rows, [cases.hold()], horizon_h=1.0, bind=PLANE_CHANGE)
        tree = evaluate_tree(scenario).tree
        assert tree is not None
        path = "Hold course against Hold in turn 1, then Evasive against Hold in turn 2"
        refusal = TREE_BRANCH_REFUSED.format(turns=2, path=path, why=why)
        assert tree.refusal == refusal
        assert tree.lines[-1] == refusal
        assert tree.complete_turns == 1
        assert all(root.children == () for root in tree.roots)


class TestEachNodeCarriesItsBasis:
    def test_every_later_node_names_its_turn_and_path(self, sampled_tree: ScenarioResult) -> None:
        """19."""
        later = [n for n in _tree(sampled_tree).nodes() if n.turn == 2]
        assert len(later) == 16
        for node in later:
            bases = node.figures.bases
            kind = bases.closest_approach_km.kind
            assert kind in (Basis.SAMPLED, Basis.COMPUTED)
            assert bases.time_to_closest_hours.kind is kind
            assert bases.closest_approach_km.note.startswith("Turn 2 of 2, ")
            assert " in turn 1, then " in bases.closest_approach_km.note
            assert bases.composite_score.kind is Basis.LOOKUP
            assert node.figures.propagator != ELSET_PROPAGATOR
            assert (node.figures.band is None) is (kind is Basis.COMPUTED)
        assert any(len(n.figures.slice_min_km) == 50 for n in later)

    def test_a_response_that_does_not_burn_spends_nothing_computed(self, sampled_tree: ScenarioResult) -> None:
        """19."""
        for node in _tree(sampled_tree).nodes():
            if node.turn == 2 and node.response == 0:
                assert node.figures.delta_v_km_s == 0.0
                assert node.figures.bases.delta_v_cost_km_s.kind is Basis.COMPUTED

    def test_the_sentences_name_the_tree(self, sampled_tree: ScenarioResult) -> None:
        """19: the header, the method and each red move again, in order."""
        tree = _tree(sampled_tree)
        assert tree.lines[0] == (
            "A 2-turn tree: 2 red moves and 2 responses each turn, 20 branches. Each turn is 0.5 h of the 1.0 h "
            "searched; turn 2 starts at 12:30 UTC."
        )
        assert tree.lines[1:4] == (TREE_PROPAGATOR, TREE_NODE_MEANS, TREE_PATH_MEANS)
        assert tree.lines[4] == TREE_RED_AGAIN.format(row=2, name="Evasive", offset=0.1)
        assert tree.lines[-1] == TREE_RESPONSE_AGAIN
        assert [w.span_s for w in tree.windows] == [3600.0, 1800.0]


class TestTreeSentencesPassTheHouseChecks:
    @pytest.mark.parametrize("sentence", SENTENCES)
    def test_each_sentence(self, sentence: str) -> None:
        """20: I13-clean, in m/s, and no long dashes or double dashes; a time's format is not a percentage."""
        assert i13_problems(re.sub(r"\{[^}]*\}", "0", sentence)) == []
        assert "km/s" not in sentence
        assert "—" not in sentence
        assert "–" not in sentence
        assert "--" not in sentence

    def test_a_three_turn_header_names_turn_three(self) -> None:
        """20."""
        scenario = cases.scenario([cases.still()], [cases.hold()], turns=3)
        tree = _tree(evaluate_tree(scenario))
        assert tree.lines[0].endswith("turn 2 starts at 14:00 UTC and turn 3 at 16:00 UTC.")
        assert tree.complete_turns == 3
        assert [n.turn for n in tree.nodes()] == [1, 2, 3]

    def test_turn_three_starts_where_turn_two_left_both_orbits(self) -> None:
        """7: three 2 h turns; turn 3 starts on turn 2's RK45 arcs, carried from turn 2's start."""
        scenario = cases.scenario([cases.still()], [cases.hold()], turns=3)
        (root,) = _tree(evaluate_tree(scenario)).roots
        (second,) = root.children
        (third,) = second.children
        blue0 = elset_state(COPLANAR_LEO.blue_tle, EPOCH)
        red0 = elset_state(COPLANAR_LEO.red_tle, EPOCH)
        assert blue0 is not None and red0 is not None
        blue = rk45_arc(second.start.blue, 4 * 3600.0, blue0.bstar)
        red = rk45_arc(second.start.red[0], 4 * 3600.0, red0.bstar)
        assert blue is not None and red is not None
        assert third.start.at_s == 4 * 3600.0
        np.testing.assert_array_equal(third.start.blue, blue(2 * 3600.0))
        np.testing.assert_array_equal(third.start.red[0], red(2 * 3600.0))


class TestATreeNeedsARun:
    def test_a_bound_tree_runs_as_a_job(self) -> None:
        """Even with nothing sampled or sized, a tree propagates many branches."""
        scenario = cases.scenario([cases.still()], [cases.hold()])
        assert needs_a_run(scenario)
        assert not needs_a_run(dataclasses.replace(scenario, turns=1))
        assert not needs_a_run(cases.scenario([cases.still()], [cases.hold()], bind=None))


class TestASequenceCarriesItsBasis:
    """A sequence's closest approach, delta-V and score each say what they rest on, as a node's figures do."""

    def test_a_sum_with_a_lookup_in_it_is_a_lookup_and_names_it(self) -> None:
        rows, responses = [cases.still()], [cases.hold(), cases.avoid(None)]
        scenario = cases.scenario(rows, responses)
        steps = [
            PathStep(rows[0], responses[1], 0.015, None, Basis.LOOKUP),
            PathStep(rows[0], responses[0], 0.0, None, Basis.COMPUTED),
            PathStep(rows[0], responses[1], 0.015, None, Basis.LOOKUP),
        ]
        bases = path_figures(scenario, steps, 10.0, sampled=False).bases
        assert bases.delta_v_km_s.kind is Basis.LOOKUP
        assert bases.delta_v_km_s.note == (
            "our burns along this sequence added up, each as its own turn states it; the delta-V for Avoid in turn 1 "
            "and Avoid in turn 3 is a lookup, not a sized burn, so the sum is a lookup"
        )
        assert bases.closest_approach_km.kind is Basis.COMPUTED
        assert bases.closest_approach_km.note.endswith(
            " No burn is sized for Avoid in turn 1 or Avoid in turn 3, so the blue asset is flown there without one.",
        )
        assert bases.score.kind is Basis.LOOKUP
        assert bases.score.note.startswith("the one-turn score on this sequence's figures: weighted sum of custody")

    def test_a_sum_of_computed_burns_is_computed(self) -> None:
        rows, responses = [cases.still()], [cases.hold(), cases.avoid(20.0)]
        scenario = cases.scenario(rows, responses)
        steps = [PathStep(rows[0], r, 0.003 * j, None, Basis.COMPUTED) for j, r in enumerate(responses)]
        bases = path_figures(scenario, steps, 25.0, sampled=True).bases
        assert bases.delta_v_km_s == decision.FigureBasis(
            Basis.COMPUTED, "our burns along this sequence added up, each as its own turn states it",
        )
        assert bases.closest_approach_km.kind is Basis.SAMPLED
        assert bases.closest_approach_km.note.startswith("P5 of each sample's own smallest separation along this ")
        assert "No burn is sized" not in bases.closest_approach_km.note
        assert bases.score.kind is Basis.LOOKUP

    def test_a_step_that_does_not_say_is_a_lookup(self) -> None:
        """Nothing claims more than it earned: a step built without its delta-V's basis counts as a lookup."""
        rows, responses = [cases.still()], [cases.hold()]
        steps = [PathStep(rows[0], responses[0], 0.0)]
        bases = path_figures(cases.scenario(rows, responses), steps, 9.0, sampled=False).bases
        assert bases.delta_v_km_s.kind is Basis.LOOKUP

    def test_each_node_in_a_tree_carries_its_sequences_bases(
        self, still_tree: ScenarioResult, sampled_tree: ScenarioResult,
    ) -> None:
        """The reviewer's case: Avoid with no target twice adds two lookups, so the sum is a lookup."""
        roots = _tree(still_tree).roots
        avoid_avoid, hold_hold = roots[1].children[1], roots[0].children[0]
        assert avoid_avoid.path.delta_v_km_s == pytest.approx(0.03)
        assert avoid_avoid.path.bases.delta_v_km_s.kind is Basis.LOOKUP
        assert "Avoid in turn 1 and Avoid in turn 2" in avoid_avoid.path.bases.delta_v_km_s.note
        assert "No burn is sized for Avoid in turn 1 or Avoid in turn 2" in avoid_avoid.path.bases.closest_approach_km.note
        assert hold_hold.path.bases.delta_v_km_s.kind is Basis.COMPUTED
        assert roots[0].path.bases.closest_approach_km.kind is Basis.COMPUTED
        for node in _tree(sampled_tree).nodes():
            kind = node.path.bases.closest_approach_km.kind
            assert kind is (Basis.SAMPLED if len(node.figures.slice_min_km) == 50 else Basis.COMPUTED)
            assert node.path.bases.delta_v_km_s.kind is Basis.COMPUTED
            assert node.path.bases.score.kind is Basis.LOOKUP
            for basis in node.path.bases:
                assert i13_problems(basis.note) == []
            assert "km/s" not in node.path.bases.delta_v_km_s.note
