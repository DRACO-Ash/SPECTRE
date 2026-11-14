"""A game tree carries each sample's element-set error from turn to turn (SPC-202, evaluation F-11).

Turn 1 is the matrix, whose sampled cells draw both objects' element-set error and whose computed cells carry a band.
A later turn starts each sample where its last turn left it: red's draw is in the state it carries, and blue's is a
time along its own orbit the sample keeps, so each blue is read that much later or earlier. A sampled turn after a
computed one draws both objects' error at its start. A computed node shows its miss and scores its sequence on the
miss less both sets' error at its closest approach in quadrature, never less than the error at any closest approach
before it, since the error grows with age.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime
from typing import cast

import numpy as np
import pytest

from spectre.astro.along_track import position_error_km
from spectre.astro.monte_carlo import (
    ContinuedRed,
    ElsetError,
    SeparationWindow,
    continue_series,
    elset_offsets_km,
    elset_state,
    rk45_arc,
    run_separation_series,
    shift_pad_s,
)
from spectre.domain import decision, decision_tree
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    FriendlyResponse,
    HypothesisSource,
    MissRule,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    cell_figures,
)
from spectre.domain.decision_tree import GameNode, evaluate_tree
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_elset_error import _bound
from tests.unit.test_elset_error_in_the_miss import _AHEAD_KM, _BLUE_TLE, _RED_TLE, _blue, _still

_WINDOW = SeparationWindow(EPOCH, 1800.0)


class TestALaterTurnReadsEachSamplesBlueWhereItsDrawPutIt:
    def test_each_sample_searches_blue_moved_by_its_own_shift(self) -> None:
        """Three samples from red's one state, blue read 0 s, 1 s and -1 s on: the miss closes and opens by blue's
        speed times the shift."""
        red, blue = elset_state(_RED_TLE, EPOCH), elset_state(_BLUE_TLE, EPOCH)
        assert red is not None and blue is not None
        shifts = np.array([0.0, 1.0, -1.0])
        arc = rk45_arc(blue.state_eci_km, _WINDOW.span_s, blue.bstar, shift_pad_s(shifts))
        assert arc is not None
        states = np.repeat(red.state_eci_km[None, :], 3, axis=0)
        out = continue_series(
            ContinuedRed(states, np.full(3, red.bstar), blue_shift_s=shifts), [arc], _WINDOW,
        )
        speed = float(np.linalg.norm(blue.state_eci_km[3:]))
        misses = [a.miss_km for a in out.series[0].approaches]
        assert misses == pytest.approx([_AHEAD_KM, _AHEAD_KM - speed, _AHEAD_KM + speed], abs=0.05)

    def test_a_series_keeps_each_samples_blue_shift_for_the_next_turn(self) -> None:
        error = ElsetError(1.0, 2.0)
        series = run_separation_series(_still(4), _blue(), _WINDOW, keep_at_s=(900.0,), elset_error=error)  # type: ignore[arg-type]
        assert series.kept is not None and series.kept.blue_shift_s is not None
        blue = elset_state(_BLUE_TLE, EPOCH)
        assert blue is not None
        speed = float(np.linalg.norm(blue.state_eci_km[3:]))
        expected = elset_offsets_km(error, 42, 4)[:, 1] / speed
        assert series.kept.blue_shift_s.tolist() == pytest.approx(expected.tolist())

    def test_with_no_shift_nothing_moves(self) -> None:
        assert shift_pad_s(None) == 0.0
        assert shift_pad_s(np.zeros(3)) == 0.0


def _tree_scenario(*, sampled_first: bool) -> Scenario:
    """Two turns over 0.5 h: red still and sampled, and red doing nothing; hold or retask."""
    still = AdversaryHypothesis(_still(400), HypothesisSource.ENTERED)
    rows = [AdversaryAction("A0", "Still, sampled", ActionType.MANOEUVRE, 0.5, 0.7, hypothesis=still),
            AdversaryAction("A1", "No action", ActionType.NO_ACTION, 0.5, 0.7)]
    if not sampled_first:
        rows.reverse()
    responses = [FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
                 FriendlyResponse("F1", "Retask", ActionType.SENSOR_RETASK, 0.2, 0.8, 1.0)]
    binding = ScenarioBinding(red=_bound("red", _RED_TLE, 24.0), blue=_bound("blue", _BLUE_TLE, 0.0))
    return Scenario(name="Tree", epoch_utc=EPOCH, adversary_actions=rows, friendly_responses=responses,
                    horizon_hours=0.5, binding=binding, turns=2)


@pytest.fixture(scope="module")
def tree() -> ScenarioResult:
    return evaluate_tree(_tree_scenario(sampled_first=True))


def _nodes(result: ScenarioResult) -> list[GameNode]:
    assert result.tree is not None and result.tree.refusal is None, None if result.tree is None else result.tree.refusal
    return list(result.tree.nodes())


class TestTheTree:
    def test_each_root_scores_as_its_cell(self, tree: ScenarioResult) -> None:
        roots = [n for n in _nodes(tree) if n.turn == 1]
        cells = [c for row in tree.outcome_matrix for c in row]
        for root, cell in zip(roots, cells, strict=True):
            assert root.path_score == pytest.approx(cell.composite_score, abs=1e-6)
            assert root.path.score == pytest.approx(cell.composite_score, abs=1e-6)
            assert cell_figures(cell).closest_approach_km <= root.path_closest_km

    def test_a_later_sampled_node_says_what_it_draws(self, tree: ScenarioResult) -> None:
        later = [n for n in _nodes(tree) if n.turn == 2 and n.figures.band is not None]
        assert later
        for node in later:
            note = node.figures.bases.closest_approach_km.note
            assert "element-set error along track" in note and "not sampled" not in note
            assert "element-set error along track" in node.path.bases.closest_approach_km.note

    def test_a_later_sampled_node_spreads_by_the_error(self, tree: ScenarioResult) -> None:
        """Red is still in every turn, so the spread of a later sampled node is the element-set error alone."""
        node = next(n for n in _nodes(tree) if n.turn == 2 and n.figures.band is not None and n.action == 0)
        band = node.figures.band
        assert band is not None
        assert band[95] - band[5] > 2.0

    def test_a_computed_sequence_scores_on_its_miss_less_the_error(self, tree: ScenarioResult) -> None:
        computed = [n for n in _nodes(tree) if n.turn == 2 and n.figures.band is None]
        assert computed
        for node in computed:
            assert "less this error" in node.figures.bases.closest_approach_km.note
            assert "less the element-set error" in node.path.bases.closest_approach_km.note


@pytest.fixture(scope="module")
def after_computed() -> ScenarioResult:
    return evaluate_tree(_tree_scenario(sampled_first=False))


class TestASampledTurnAfterAComputedOne:
    def test_it_draws_both_errors_at_its_start(self, after_computed: ScenarioResult) -> None:
        """The computed root leaves red one state; its sampled child starts each sample from that state moved along
        track by its own draw."""
        node = next(n for n in _nodes(after_computed) if n.turn == 2 and n.action == 1 and n.figures.band is not None)
        starts = node.start.red
        assert starts.shape[0] > 1
        assert len({tuple(np.round(s, 9)) for s in starts}) == starts.shape[0]
        band = node.figures.band
        assert band is not None
        assert band[95] - band[5] > 1.0

    def test_a_start_that_cannot_be_moved_refuses_the_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "moved_states", lambda *_: None)
        result = evaluate_tree(_tree_scenario(sampled_first=False))
        assert result.tree is not None and result.tree.refusal is not None
        assert "could not be propagated" in result.tree.refusal


# ── Review of SPC-202: a later computed node's score figure, the ages it reads, and a third turn's carry ──

def _age_h(result: ScenarioResult, side: str, at: datetime) -> float:
    binding = result.scenario.binding
    assert binding is not None
    elset = binding.red if side == "red" else binding.blue
    assert elset is not None and elset.epoch is not None
    return (at - elset.epoch).total_seconds() / 3600.0


@pytest.fixture(scope="module")
def tree_point() -> ScenarioResult:
    return evaluate_tree(dataclasses.replace(_tree_scenario(sampled_first=True), miss_rule=MissRule.POINT))


class TestALaterComputedNodeReadsTheErrorAtItsOwnClosestApproach:
    """Red's set is 24 h old at the scenario epoch and blue's fresh, both LEO. A later computed node's closest
    approach is some minutes into its turn, so red's set is older there than at the epoch: the node reads the error
    at its own TCA, red's 1 km plus 2 km a day of that age and blue's likewise, in quadrature."""

    def _later_computed(self, result: ScenarioResult) -> list[GameNode]:
        nodes = [n for n in _nodes(result) if n.turn == 2 and n.figures.band is None]
        assert nodes
        return nodes

    def test_its_basis_names_each_sets_age_at_its_closest_approach(self, tree: ScenarioResult) -> None:
        for node in self._later_computed(tree):
            tca = node.figures.tca_utc
            red_h, blue_h = _age_h(tree, "red", tca), _age_h(tree, "blue", tca)
            assert red_h > 24.05   # the TCA is after the epoch, so an age at the epoch would read 24.0
            note = node.figures.bases.closest_approach_km.note
            assert f"({red_h:.1f} h old then)" in note and f"({blue_h:.1f} h old)" in note
            assert f"{red_h:.1f} h old" in node.path.bases.closest_approach_km.note

    def test_its_sequence_scores_on_the_closest_approach_less_that_error(
        self, tree: ScenarioResult, tree_point: ScenarioResult,
    ) -> None:
        """The other four terms are the same under both rules, so the score under this one is the score under the
        rule before with the closest-approach term read at the closest approach less the error."""
        before = dict(zip(_nodes(tree), _nodes(tree_point), strict=True))   # the same tree, node for node
        scenario = tree.scenario
        w, keep = scenario.w_closest_approach, scenario.keep_out_km
        for node in self._later_computed(tree):
            then = before[node]
            assert (then.turn, then.action, then.response) == (node.turn, node.action, node.response)
            tca = node.figures.tca_utc
            red_km = position_error_km(_age_h(tree, "red", tca) / 24.0, "LEO")
            blue_km = position_error_km(_age_h(tree, "blue", tca) / 24.0, "LEO")
            closest = node.path_closest_km
            assert then.path_closest_km == pytest.approx(closest)
            expected = (then.path_score - w * decision._norm_ca(closest, keep)
                        + w * decision._norm_ca(closest - math.hypot(red_km, blue_km), keep))
            assert node.path_score == pytest.approx(expected, abs=1e-9)
            assert node.path_score > then.path_score


def _three_turns() -> Scenario:
    return dataclasses.replace(_tree_scenario(sampled_first=True), turns=3)


class TestAThirdTurnKeepsEachSamplesBlueShift:
    """Blue's draw is a time along its own orbit each sample keeps from turn to turn: the sampled root hands it to
    turn 2, and turn 2's series hands it to turn 3, each sample's the same as its first draw. Where a sampled turn
    follows a computed one it draws afresh on its own seed, and that draw is carried on in turn."""

    def test_every_turn_after_the_first_reads_blue_at_the_first_draws_shift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[float, np.ndarray | None]] = []
        real = decision_tree.continue_series

        def spy(red: ContinuedRed, *args: object, **kwargs: object) -> object:
            window = args[1]
            assert isinstance(window, SeparationWindow)
            seen.append(((window.start_utc - EPOCH).total_seconds(), red.blue_shift_s))
            return real(red, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(decision_tree, "continue_series", spy)
        result = evaluate_tree(_three_turns())
        assert result.tree is not None and result.tree.refusal is None, None if result.tree is None else result.tree.refusal
        hypothesis = result.scenario.adversary_actions[0].hypothesis
        assert hypothesis is not None
        blue = elset_state(_BLUE_TLE, EPOCH)
        assert blue is not None
        speed = float(np.linalg.norm(blue.state_eci_km[3:]))
        first = elset_offsets_km(ElsetError(3.0, 1.0), hypothesis.hypothesis.random_seed, 400)[:, 1] / speed
        turn_s = 1800.0 / 3
        assert {round(at) for at, _ in seen} == {round(turn_s), round(2 * turn_s)}
        assert all(shifts is not None for _, shifts in seen)

        def from_the_root(t: float) -> int:
            return sum(np.allclose(cast("np.ndarray", s), first, rtol=0.0, atol=1e-12) for at, s in seen if round(at) == round(t))

        assert from_the_root(turn_s) == 2        # the sampled root's two moves in turn 2
        assert from_the_root(2 * turn_s) == 4    # and each of their two moves in turn 3
