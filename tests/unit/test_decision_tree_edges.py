"""What a game tree does when a branch cannot be had (SPC-140): it says which and why, and keeps the turns built.

Each failure is forced where the real orbits would not give it, by standing in for the one call that fails, so the
sentence the operator reads is pinned for every way a tree stops short.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, NoReturn

import numpy as np
import pytest

from spectre.astro.elset_approach import ElsetFailure
from spectre.astro.monte_carlo import Kept, MissStats, ReenteredError, SeparationSeries, SeparationWindow
from spectre.domain import decision, decision_tree
from spectre.domain.decision import ScenarioResult
from spectre.domain.decision_tree import (
    TREE_BRANCH_REFUSED,
    TREE_BUDGET_TURN_ONE,
    TREE_REFUSED_ROW,
    GameTree,
    evaluate_tree,
)
from spectre.domain.provenance import Basis
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import PLANE_CHANGE
from tests.unit.test_decision_sampled import _series


def _sampled(*responses: Any, n: int = 50) -> decision.Scenario:
    """plane_change, a 50-sample Evasive burning 0.1 h in, over two 0.5 h turns."""
    rows = [cases.evasive(PLANE_CHANGE, n=n, offset_h=0.1, row_id="A0")]
    return cases.scenario(rows, list(responses) or [cases.hold()], horizon_h=1.0, bind=PLANE_CHANGE)


def _still(*responses: Any) -> decision.Scenario:
    """coplanar_leo, Hold course, over two 3 h turns."""
    return cases.scenario([cases.still()], list(responses) or [cases.hold()])


def _assert_refused(result: ScenarioResult, refusal: str, *, complete: int) -> GameTree:
    tree = result.tree
    assert tree is not None
    assert tree.refusal == refusal
    assert tree.complete_turns == complete
    assert tree.lines[-1] == refusal
    assert all(root.children == () for root in tree.roots)
    return tree


def _branch(path: str, why: str) -> str:
    return TREE_BRANCH_REFUSED.format(turns=2, path=path, why=why)


def _none(*_: Any, **__: Any) -> None:
    return None


def _reenters(*_: Any, **__: Any) -> NoReturn:
    raise ReenteredError("below the floor")


class TestTurnOneLeavesNoOrbit:
    def test_a_sampled_row_refused_when_it_ran(self) -> None:
        """Its series did not converge, so its cells are lookups and the row leaves no orbit to carry on."""

        def unconverged(_h: Any, _b: Any, window: SeparationWindow, **_: Any) -> SeparationSeries:
            return _series(window, converged=False)

        result = evaluate_tree(_sampled(), sampler=unconverged)
        tree = _assert_refused(result, TREE_REFUSED_ROW.format(row=1, name="Evasive"), complete=0)
        assert tree.roots == ()
        assert tree.lines == (tree.refusal,)
        assert "hypothesis" not in TREE_REFUSED_ROW

    def test_a_sampled_row_the_budget_did_not_cover_says_the_budget_ran_out(self) -> None:
        """The clock ticks a second a read, so a 5.5 s budget runs out a few samples into turn 1's only row."""
        ticks = iter(range(1_000_000))
        run = decision.RunControl(budget_s=5.5, stop=lambda: None, clock=lambda: float(next(ticks)))
        result = evaluate_tree(_sampled(), run=run)
        (cell,) = result.outcome_matrix[0]
        assert cell.ca_refusal is not None
        assert cell.ca_refusal.startswith("Not sampled: this evaluation's 5.5 s budget ran out after ")
        tree = _assert_refused(result, TREE_BUDGET_TURN_ONE.format(budget=5.5, row=1, name="Evasive"), complete=0)
        assert tree.roots == ()

    def test_a_cell_refused_after_our_burn(self) -> None:
        """The series did not search the burnt blue asset, so that one cell is a lookup."""

        def unburnt(_h: Any, _b: Any, window: SeparationWindow, **_: Any) -> SeparationSeries:
            kept = Kept((1800.0,), np.zeros((50, 1, 6)), np.full(50, 1e-4), np.full((2, 50), 5.0), ((),) * 50)
            return dataclasses.replace(_series(window), kept=kept)

        result = evaluate_tree(_sampled(cases.hold(), cases.avoid(20.0, hours=0.05)), sampler=unburnt)
        why = "is refused in turn 1, as its cell says"
        _assert_refused(result, _branch("Evasive against Avoid in turn 1", why), complete=0)

    def test_red_with_no_nominal_arc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "nominal_red_arc", _none)
        result = evaluate_tree(_sampled())
        _assert_refused(result, _branch("Evasive against Hold in turn 1", "could not be propagated"), complete=0)

    def test_a_computed_row_sgp4_could_not_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision, "elset_closest_approach", lambda *_: ElsetFailure("red", "propagation"))
        result = evaluate_tree(_still())
        _assert_refused(result, TREE_REFUSED_ROW.format(row=1, name="Hold course"), complete=0)

    def test_a_computed_row_left_on_sgp4(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The budget ran out before the pair went on RK45, so its cells stay SGP4 and no tree is built on them."""
        monkeypatch.setattr(decision, "_size_computed", lambda *_: "Our burn is not sized: the budget ran out.")
        result = evaluate_tree(_still())
        _assert_refused(result, _branch("Hold course against Hold in turn 1", "could not be put on RK45 within the budget"), complete=0)

    def test_the_pair_would_not_go_on_rk45_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "rk45_pair", lambda *_: ElsetFailure("blue", "propagation"))
        result = evaluate_tree(_still())
        _assert_refused(result, _branch("Hold course against Hold in turn 1", "could not be propagated"), complete=0)

    def test_our_burnt_arc_reenters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "burnt_arc", _reenters)
        result = evaluate_tree(_still(cases.hold(), cases.avoid(20.0)))
        _assert_refused(result, _branch("Hold course against Avoid in turn 1", "could not be propagated"), complete=0)


class TestALaterTurnCannotBeHad:
    def test_reds_nominal_arc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "nominal_continued_arc", _none)
        result = evaluate_tree(_still())
        path = "Hold course against Hold in turn 1, then Hold course against Hold in turn 2"
        tree = _assert_refused(result, _branch(path, "could not be propagated"), complete=1)
        assert len(tree.roots) == 1

    def test_blues_coast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "rk45_arc", _reenters)
        result = evaluate_tree(_still())
        path = "Hold course against Hold in turn 1, then Hold course against Hold in turn 2"
        _assert_refused(result, _branch(path, "could not be propagated"), complete=1)

    def test_a_sequence_whose_p5_does_not_converge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each node converged, but the sequence's own minima did not."""
        monkeypatch.setattr(
            decision_tree, "_miss_stats", lambda *_: MissStats(5.0, 6.0, 7.0, 1.0, 2.5, 1.0, converged=False),
        )
        result = evaluate_tree(_sampled())
        path = "Evasive against Hold in turn 1, then Evasive against Hold in turn 2"
        why = "did not converge along the sequence: its P5 is known only to within 2.5 km"
        _assert_refused(result, _branch(path, why), complete=1)


class TestASizingRefusedInALaterTurn:
    def test_a_burn_after_the_closest_approach_keeps_the_lookup_and_says_why(self) -> None:
        """Avoid executes 2.9 h into each 3 h turn: in turn 1 that is before the pass at about 4.0 h, in turn 2 after."""
        result = evaluate_tree(_still(cases.hold(), cases.avoid(20.0, hours=2.9)))
        tree = result.tree
        assert tree is not None
        assert tree.refusal is None
        hold_then_avoid = tree.roots[0].children[1]
        basis = hold_then_avoid.figures.bases.delta_v_cost_km_s
        assert basis.kind is Basis.LOOKUP
        assert "Our burn is not sized" in basis.note
        assert "comes after the closest approach" in basis.note
        assert hold_then_avoid.figures.delta_v_km_s == pytest.approx(0.3 * 0.05)
        assert result.outcome_matrix[0][1].ca_response is not None


class TestThreeSampledTurns:
    def test_each_sample_is_carried_through_turn_two_into_turn_three(self) -> None:
        """plane_change over three 0.5 h turns, the Evasive row against Hold: one branch a turn, 50 samples each."""
        rows = [cases.evasive(PLANE_CHANGE, n=50, offset_h=0.05, row_id="A0")]
        scenario = cases.scenario(rows, [cases.hold()], turns=3, horizon_h=1.5, bind=PLANE_CHANGE)
        tree = evaluate_tree(scenario).tree
        assert tree is not None
        assert tree.refusal is None
        (root,) = tree.roots
        (second,) = root.children
        (third,) = second.children
        assert third.start.red.shape == (50, 6)
        assert third.start.at_s == 3600.0
        assert not np.allclose(third.start.red, second.start.red)
        assert third.figures.bases.closest_approach_km.kind is Basis.SAMPLED
        assert len(third.figures.slice_min_km) == 50
        assert third.path_closest_km <= second.path_closest_km + 1e-9
        assert math.isfinite(third.path_score)
