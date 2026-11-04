"""What a game tree carries from turn to turn, checked against arcs built here (SPC-140).

Each check rebuilds one figure the tree reports from the orbits themselves: a sample's burn that falls after its
turn ends, red's nominal arc carried into turn 3, a slice that stops at its turn's end, a later turn's time of
closest approach, and turn 1's slices against our burnt arc. A tree that took any of these from the wrong arc or
the wrong window would report a figure the orbits do not give.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import numpy as np
import pytest

from spectre.astro import monte_carlo as mc
from spectre.astro.elset_approach import elset_position_error_km
from spectre.astro.monte_carlo import (
    SeparationWindow,
    burnt_arc,
    elset_state,
    nominal_red_arc,
    rk45_arc,
    searched_approach,
)
from spectre.astro.response_burn import BurnRequest, Rk45Pair
from spectre.domain import decision_tree
from spectre.domain.decision import AdversaryAction, ScenarioResult
from spectre.domain.decision_tree import TREE_RED_AGAIN, GameTree, evaluate_tree
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH, PLANE_CHANGE

_Arc = Callable[[float], np.ndarray]


def _tree(result: ScenarioResult) -> GameTree:
    tree = result.tree
    assert tree is not None
    assert tree.refusal is None, tree.refusal
    return tree


def _turn_one_reds(hypothesis: mc.ManoeuvreHypothesis, span_s: float) -> list[_Arc]:
    """Each sample's red over the whole span as turn 1's series flies it: the unburnt arc, burnt as drawn."""
    draws = mc.generate_samples(hypothesis)
    burn_s = (hypothesis.epoch_utc - EPOCH).total_seconds()
    unburnt = mc._unburnt_arc(hypothesis, mc._earliest_s(burn_s + draws[:, 3]), span_s, burn_s)
    assert unburnt is not None
    window = SeparationWindow(EPOCH, span_s)
    reds = [mc._sample_red(draw, unburnt, burn_s, hypothesis.bstar_post, window) for draw in draws]
    assert all(red is not None for red in reds)
    return [red for red in reds if red is not None]


def _blue_coast(span_s: float) -> tuple[_Arc, float]:
    """plane_change's blue from its SGP4 state at the epoch by RK45 over *span_s*, and its B*."""
    blue0 = elset_state(PLANE_CHANGE.blue_tle, EPOCH)
    assert blue0 is not None
    coast = rk45_arc(blue0.state_eci_km, span_s, blue0.bstar)
    assert coast is not None
    return coast, blue0.bstar


def _hypothesis(row: AdversaryAction) -> mc.ManoeuvreHypothesis:
    assert row.hypothesis is not None
    return row.hypothesis.hypothesis


def _miss_km(red: _Arc, blue: _Arc, from_s: float, to_s: float) -> float:
    """The smallest separation of *red* and *blue* between *from_s* and *to_s*, both timed from the epoch."""
    window = SeparationWindow(EPOCH + timedelta(seconds=from_s), to_s - from_s)
    return searched_approach(lambda t: red(t + from_s), lambda t: blue(t + from_s), window).approach.miss_km


class TestALateBurnIsMadeInTheTurnAfter:
    def test_turn_twos_misses_follow_each_samples_own_arc(self) -> None:
        """plane_change's Evasive burning 0.98 h into each 1 h turn, 120 s 1-sigma: a third of its samples burn
        after turn 1 ends. With red holding course in turn 2, each sample's miss in turn 2 is the one its own turn-1
        arc gives over that half of the span, late burn and all."""
        rows = [cases.evasive(PLANE_CHANGE, n=50, offset_h=0.98, row_id="A0"), cases.still(row_id="A1")]
        scenario = cases.scenario(rows, [cases.hold()], horizon_h=2.0, bind=PLANE_CHANGE)
        tree = _tree(evaluate_tree(scenario))
        assert TREE_RED_AGAIN.format(row=1, name="Evasive", offset=0.98) in tree.lines
        assert TREE_RED_AGAIN.endswith(
            "a sample whose drawn time falls after its turn ends still burns then, in the turn after.",
        )
        hold_course = tree.roots[0].children[1]
        assert (hold_course.turn, hold_course.action) == (2, 1)
        hypothesis = rows[0].hypothesis
        assert hypothesis is not None
        reds = _turn_one_reds(hypothesis.hypothesis, 7200.0)
        late = 3528.0 + mc.generate_samples(hypothesis.hypothesis)[:, 3] > 3600.0
        assert int(late.sum()) >= 5
        blue, _ = _blue_coast(7200.0)
        expected = [_miss_km(red, blue, 3600.0, 7200.0) for red in reds]
        np.testing.assert_allclose(hold_course.figures.slice_min_km, expected, atol=0.01, rtol=0.0)


    def test_turn_three_is_handed_the_burns_turn_two_drew_past_its_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Three 1 h turns, Evasive burning 0.98 h into each: what turn 2's series kept still to come is what turn 3
        is given to make, sample by sample. The tree may stop at turn 3; what it was handed is the check."""
        calls: list[tuple[mc.ContinuedRed, mc.ContinuedSeries]] = []
        real = decision_tree.continue_series

        def spy(red: mc.ContinuedRed, *args: object, **kw: object) -> mc.ContinuedSeries:
            out = real(red, *args, **kw)  # type: ignore[arg-type]
            calls.append((red, out))
            return out

        monkeypatch.setattr(decision_tree, "continue_series", spy)
        rows = [cases.evasive(PLANE_CHANGE, n=50, offset_h=0.98, row_id="A0")]
        evaluate_tree(cases.scenario(rows, [cases.hold()], turns=3, horizon_h=3.0, bind=PLANE_CHANGE))
        (second, kept), (third, _) = calls
        assert kept.kept is not None
        assert sum(bool(p) for p in kept.kept.pending) >= 5
        assert len(third.pending) == 50
        for handed, held in zip(third.pending, kept.kept.pending, strict=True):
            assert [b.at_s for b in handed] == [b.at_s for b in held]
        assert second.pending != ()


@pytest.fixture(scope="module")
def sampled() -> tuple[list[AdversaryAction], ScenarioResult]:
    """plane_change, Hold course and a 50-sample Evasive burning 0.1 h in, against Hold and Avoid at 20 km
    executing 0.05 h in, over two 0.5 h turns."""
    rows = [cases.still(), cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1)]
    scenario = cases.scenario(rows, [cases.hold(), cases.avoid(20.0, hours=0.05)], horizon_h=1.0, bind=PLANE_CHANGE)
    return rows, evaluate_tree(scenario)


class TestTurnOnesSlicesAreAgainstOurBurntArc:
    def test_a_burnt_roots_slices_are_against_the_burnt_blue(
        self, sampled: tuple[list[AdversaryAction], ScenarioResult],
    ) -> None:
        """Evasive against Avoid: each sample's slice minimum to 0.5 h is against blue after our burn, which moves
        it by kilometres, and the sequence's closest approach is built on it."""
        rows, result = sampled
        root = _tree(result).roots[3]
        assert (root.action, root.response) == (1, 1)
        response = result.outcome_matrix[1][1].ca_response
        assert response is not None
        burn = response.sized.burn
        assert burn is not None
        coast, bstar = _blue_coast(3600.0)
        burnt = burnt_arc(coast, burn, 3600.0, bstar)
        assert burnt is not None
        reds = _turn_one_reds(_hypothesis(rows[1]), 3600.0)
        against_burnt = np.array([_miss_km(red, burnt, 0.0, 1800.0) for red in reds])
        against_coast = np.array([_miss_km(red, coast, 0.0, 1800.0) for red in reds])
        np.testing.assert_allclose(root.figures.slice_min_km, against_burnt, atol=1e-6, rtol=0.0)
        assert np.max(np.abs(against_burnt - against_coast)) > 1.0
        for child in root.children:
            minima = np.minimum(against_burnt, child.figures.slice_min_km)
            assert child.path_closest_km == pytest.approx(float(np.percentile(minima, 5)), abs=1e-6)


class TestALaterTurnsTimeOfClosestApproachIsInItsTurn:
    def test_every_later_nodes_closest_approach_falls_in_its_own_window(
        self, sampled: tuple[list[AdversaryAction], ScenarioResult],
    ) -> None:
        tree = _tree(sampled[1])
        later = [n for n in tree.nodes() if n.turn == 2]
        assert len(later) == 16
        window = tree.windows[1]
        for node in later:
            assert window.start_utc <= node.figures.tca_utc <= window.start_utc + timedelta(seconds=window.span_s)


class TestAComputedLaterTurnIsItsOwnArcs:
    def test_turn_twos_figures_are_its_arcs_over_its_own_window_and_slice(self) -> None:
        """coplanar_leo, Hold course against Hold, three 2 h turns: turn 2's closest approach, its time and its
        slice to 4 h are what its own arcs give from 2 h on, the pass at about 4.0 h falling past its slice."""
        scenario = cases.scenario([cases.still()], [cases.hold()], turns=3)
        (root,) = _tree(evaluate_tree(scenario)).roots
        (second,) = root.children
        red0, blue0 = elset_state(COPLANAR_LEO.red_tle, EPOCH), elset_state(COPLANAR_LEO.blue_tle, EPOCH)
        assert red0 is not None and blue0 is not None
        red = rk45_arc(second.start.red[0], 4 * 3600.0, red0.bstar)
        blue = rk45_arc(second.start.blue, 4 * 3600.0, blue0.bstar)
        assert red is not None and blue is not None
        start = EPOCH + timedelta(hours=2)
        rest = searched_approach(red, blue, SeparationWindow(start, 4 * 3600.0)).approach
        sliced = searched_approach(red, blue, SeparationWindow(start, 2 * 3600.0)).approach
        assert second.figures.closest_approach_km == rest.miss_km
        assert second.figures.tca_utc == rest.tca_utc(start)
        assert second.figures.slice_min_km == (sliced.miss_km,)
        assert sliced.at_window_edge
        assert sliced.miss_km > rest.miss_km + 0.05


def _hand_nominal(start: np.ndarray, bstar: float, hypothesis: mc.ManoeuvreHypothesis, burn_s: float, span_s: float) -> _Arc:
    """Red's nominal arc built here: coast to *burn_s*, add the stated delta-V along its RIC direction, fly on."""
    before = mc._dense_arc(start, 0.0, burn_s, bstar)
    assert before is not None
    at = before(burn_s).copy()
    ric = np.array([hypothesis.delta_v_radial, hypothesis.delta_v_in_track, hypothesis.delta_v_cross_track])
    at[3:] += mc._ric_to_eci_rotation(at[:3], at[3:]) @ (hypothesis.delta_v_magnitude_km_s * ric / np.linalg.norm(ric))
    after = mc._dense_arc(at, burn_s, span_s, hypothesis.bstar_post)
    assert after is not None
    return lambda t: before(t) if t < burn_s else after(t)


class TestOurBurnIsSizedAgainstRedsNominalEachTurn:
    def test_turn_two_and_three_size_against_reds_nominal_carried_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """plane_change's Evasive burning 0.05 h into each of three 0.5 h turns, against Avoid at 20 km: each later
        turn sizes our burn against red's nominal arc from where the turn before left it, built here."""
        calls: list[tuple[Rk45Pair, SeparationWindow, BurnRequest]] = []
        real = decision_tree.size_against

        def spy(pair: Rk45Pair, window: SeparationWindow, request: BurnRequest, **kw: object) -> object:
            calls.append((pair, window, request))
            return real(pair, window, request, **kw)  # type: ignore[arg-type]

        monkeypatch.setattr(decision_tree, "size_against", spy)
        rows = [cases.evasive(PLANE_CHANGE, n=50, offset_h=0.05, row_id="A0")]
        scenario = cases.scenario(
            rows, [cases.avoid(20.0, hours=0.02)], turns=3, horizon_h=1.5, bind=PLANE_CHANGE,
        )
        tree = evaluate_tree(scenario).tree
        assert tree is not None
        assert tree.complete_turns == 3, tree.refusal
        (root,) = tree.roots
        (second,) = root.children
        (third,) = second.children
        hypothesis = _hypothesis(rows[0])
        nominal = nominal_red_arc(hypothesis, SeparationWindow(EPOCH, 5400.0))
        assert nominal is not None
        np.testing.assert_allclose(second.start.red_nominal, nominal(1800.0), atol=1e-6, rtol=0.0)
        turn_two = _hand_nominal(second.start.red_nominal, second.start.red_nominal_bstar, hypothesis, 180.0, 3600.0)
        np.testing.assert_allclose(third.start.red_nominal, turn_two(1800.0), atol=1e-6, rtol=0.0)
        turn_three = _hand_nominal(third.start.red_nominal, third.start.red_nominal_bstar, hypothesis, 180.0, 1800.0)
        assert [w.start_utc for _, w, _ in calls] == [EPOCH + timedelta(hours=0.5), EPOCH + timedelta(hours=1.0)]
        for (pair, _, request), hand in zip(calls, (turn_two, turn_three), strict=True):
            assert request.at_s == pytest.approx(72.0)
            for t in (60.0, 179.0, 181.0, 900.0, 1700.0):
                np.testing.assert_allclose(pair.red(t)[:3], hand(t)[:3], atol=1e-6, rtol=0.0)


class TestALaterNodesTimeAndStart:
    """A later turn's node takes its TCA and its TCA's uncertainty from its own series in its own window, and starts
    with the red burns made before its turn, not its own. Over two 1 h turns plane_change's next crossing falls in
    turn 2, so its samples' TCAs differ; 100 samples converge there."""

    def test_each_later_node_reads_its_own_series_from_its_turns_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        made: list[tuple[mc.SeparationSeries, decision_tree.NodeFigures]] = []
        real = decision_tree._Tree._figures

        def spy(tree: decision_tree._Tree, steps: object, found: decision_tree._Found, *rest: object) -> decision_tree.NodeFigures:
            figures = real(tree, steps, found, *rest)  # type: ignore[arg-type]
            if found.series is not None:
                made.append((found.series, figures))
            return figures

        monkeypatch.setattr(decision_tree._Tree, "_figures", spy)
        rows = [cases.evasive(PLANE_CHANGE, n=100, offset_h=0.1, row_id="A0")]
        scenario = cases.scenario(rows, [cases.hold(), cases.avoid(20.0, hours=0.05)], horizon_h=2.0, bind=PLANE_CHANGE)
        start = _tree(evaluate_tree(scenario)).windows[1].start_utc
        assert len(made) == 4
        moved = 0
        for own, figures in made:
            index = own.earliest_at_or_below_p5_index
            assert index is not None
            moved += index != 0
            approach = own.approaches[index]
            assert figures.tca_utc == approach.tca_utc(start)
            uncertainty = figures.tca_uncertainty
            assert uncertainty is not None
            errors = [
                elset_position_error_km(tle, EPOCH, approach.tca_utc(start))
                for tle in (PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle)
            ]
            assert uncertainty.position_error_km == pytest.approx(float(np.hypot(*errors)), rel=1e-12)
        assert moved > 0
        assert all(len({a.tca_s for a in own.approaches}) > 1 for own, _ in made)

    def test_a_childs_start_holds_the_red_burns_before_its_turn(self) -> None:
        """Evasive in both turns of two 0.5 h turns: turn 2 starts after turn 1's burn and before its own."""
        rows = [cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1, row_id="A0")]
        scenario = cases.scenario(rows, [cases.hold()], horizon_h=1.0, bind=PLANE_CHANGE)
        tree = _tree(evaluate_tree(scenario))
        (root,) = tree.roots
        (child,) = root.children
        assert root.start.red_burns_utc == ()
        assert child.start.red_burns_utc == (EPOCH + timedelta(hours=0.1),)
