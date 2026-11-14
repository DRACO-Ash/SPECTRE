"""The game tree as the results page shows it (SPC-142).

Each node shows its own figures and its sequence's, each with the basis it rests on, in words as well as kind, and
the path of red moves and our responses it rests on. Delta-V reaches the page in m/s, converted here and only here.
A node on the plan the recommendation follows says so in words. The per-turn recommendation and the update after
turn 1 are the selection's lines, in two parts; the update's own basis is shown when there is one. A tree built in
part names the deepest turn built in full; a tree refused shows its refusal and no node.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.domain.decision import Scenario, ScenarioResult, Seen, SelectorStrategy
from spectre.domain.decision_figures import TcaUncertainty
from spectre.domain.decision_tree import TREE_DEEPEST, GameNode, GameTree, evaluate_tree
from spectre.domain.tree_selectors import NO_OBSERVATION, OBSERVED, OBSERVED_NO_PICK, follows_picks
from spectre.domain.turn_update import POSTERIOR_NOTE
from spectre.web.format_units import format_m_s, to_m_s
from spectre.web.tree_view import (
    FIGURE_LABELS,
    HEADING,
    HEADING_NOT_BUILT,
    PLAN_MARK,
    UPDATE_HEADING,
    UPDATE_HEADING_NO_PROBABILITY,
    NodeView,
    TreeView,
    _when,
    _when_note,
    custody_value,
    tree_view,
)
from tests.unit._tree_view_cases import sampled_result, still_result
from tests.unit.test_decision_tree_select import _still

_EV, _MINIMAX = SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMAX


def _view(result: ScenarioResult) -> TreeView:
    view = tree_view(result)
    assert view is not None
    return view


def _flat(nodes: tuple[NodeView, ...]) -> list[NodeView]:
    out: list[NodeView] = []
    for node in nodes:
        out += [node, *_flat(node.children)]
    return out


def _tree(result: ScenarioResult) -> GameTree:
    assert result.tree is not None
    return result.tree


def _paired(result: ScenarioResult) -> list[tuple[GameNode, NodeView]]:
    return list(zip(_tree(result).nodes(), _flat(_view(result).nodes), strict=True))


def _steps(scenario: Scenario, node: NodeView) -> list[tuple[int, int]]:
    return list(node.steps)


class TestNoTree:
    def test_one_turn_has_no_tree_to_show(self) -> None:
        result = evaluate_tree(dataclasses.replace(_still(), turns=1))
        assert tree_view(result) is None

    def test_a_refused_tree_shows_its_refusal_and_no_node(self) -> None:
        result = evaluate_tree(dataclasses.replace(_still(), binding=None))
        view = _view(result)
        assert view.lines == _tree(result).lines
        assert view.nodes == ()
        assert (view.recommendation, view.update, view.deepest, view.update_basis) == ((), (), None, None)
        assert view.turns == 2 and view.complete_turns == 0

    def test_a_refused_tree_is_not_headed_as_if_it_were_built(self) -> None:
        view = _view(evaluate_tree(dataclasses.replace(_still(), binding=None)))
        assert view.heading == HEADING_NOT_BUILT.format(turns=2) == "Game tree: 2 turns asked for, none built"

    def test_a_built_tree_is_headed_with_its_turns(self) -> None:
        assert _view(still_result()).heading == HEADING.format(turns=2) == "Game tree: 2 turns"

    def test_an_observation_stated_for_a_tree_with_no_pick_is_said_to_update_nothing(self) -> None:
        result = evaluate_tree(dataclasses.replace(_still(), binding=None, observed=Seen.BURN))
        view = _view(result)
        assert view.update == (OBSERVED_NO_PICK.format(seen="a burn"),)
        assert view.update_heading == UPDATE_HEADING


class TestTheNodes:
    def test_every_branch_is_a_node_in_the_trees_own_order(self) -> None:
        result = still_result()
        view = _view(result)
        assert len(view.nodes) == 4
        assert all(len(n.children) == 4 for n in view.nodes)
        assert len(_flat(view.nodes)) == 20
        for node, shown in _paired(result):
            assert shown.turn == node.turn

    def test_each_node_names_its_turn_its_moves_and_the_path_it_rests_on(self) -> None:
        view = _view(still_result())
        root = view.nodes[1]
        assert root.heading == "Turn 1 of 2: red Hold course, our Avoid"
        assert root.path == "Rests on: Hold course against Avoid in turn 1."
        child = root.children[3]
        assert child.heading == "Turn 2 of 2: red Posture, our Avoid"
        assert child.path == "Rests on: Hold course against Avoid in turn 1, then Posture against Avoid in turn 2."
        assert child.steps == ((0, 1), (1, 1))

    def test_each_figure_carries_its_basis_kind_and_rule(self) -> None:
        result = still_result()
        for node, shown in _paired(result):
            labels = [f.label for f in shown.figures]
            assert labels == list(FIGURE_LABELS)
            bases = node.figures.bases
            expected = [
                bases.closest_approach_km, bases.time_to_closest_hours, bases.delta_v_cost_km_s,
                node.path.bases.closest_approach_km, node.path.bases.delta_v_km_s, node.path.custody_bases[0],
                node.path.bases.score,
            ]
            for figure, basis in zip(shown.figures, expected, strict=True):
                assert figure.kind == basis.kind.value
                # The time's rule keeps all but the matrix's display, which this view replaces with its own.
                assert basis.note.removesuffix(" and shown to the minute") in figure.note

    def test_the_figures_are_written_once_at_their_precision(self) -> None:
        result = still_result()
        node = next(iter(_tree(result).nodes()))
        shown = _view(result).nodes[0]
        closest, when, burn, along, burns, custody, score = (f.value for f in shown.figures)
        assert closest == f"{node.figures.closest_approach_km:.1f} km"
        assert when.endswith("h after the scenario epoch, ± 6 min")
        assert burn == f"{format_m_s(to_m_s(node.figures.delta_v_km_s))} m/s"
        assert along == f"{node.path.closest_approach_km:.1f} km"
        assert burns == f"{format_m_s(to_m_s(node.path.delta_v_km_s))} m/s"
        assert custody == "held over the 6 h horizon"
        assert score == f"{node.path.score:.3f}, lower is better"
        assert shown.summary == (
            f"score {node.path.score:.3f} (lookup); closest approach along it {node.path.closest_approach_km:.1f} km "
            "(computed)"
        )

    def test_a_burn_is_shown_in_metres_per_second(self) -> None:
        avoid = _view(still_result()).nodes[1]
        assert avoid.figures[2].value == "15 m/s"
        assert all("km/s" not in f.value for n in _flat(_view(still_result()).nodes) for f in n.figures)

    def test_a_sampled_node_shows_its_band_and_how_well_it_is_known(self) -> None:
        result = sampled_result()
        evasive = [(n, v) for n, v in _paired(result) if n.turn == 1 and n.action == 1]
        assert evasive
        for node, shown in evasive:
            band = node.figures.band
            assert band is not None and node.figures.half_width_km is not None
            assert shown.figures[0].kind == "sampled"
            assert shown.figures[0].value == (
                f"{band[5]:.1f} km at P5; P50 {band[50]:.1f} km, P95 {band[95]:.1f} km; known to within "
                f"{node.figures.half_width_km:.2f} km"
            )

    @pytest.mark.parametrize(("gap", "degraded", "expected"), [
        (0.0, 0.0, "held over the 6 h horizon"),
        (5.0, 0.0, "lost for up to 5.0 h of the 6 h horizon"),
        (0.0, 6.0, "degraded, neither held nor lost, for 6.0 h of the 6 h horizon"),
        (5.0, 1.0, "degraded, neither held nor lost, for 1.0 h, then lost for up to 5.0 h of the 6 h horizon"),
        (5.996, 0.004, "degraded, neither held nor lost, for under 0.1 h, then lost for up to 6.0 h of the 6 h horizon"),
    ], ids=["held", "lost", "degraded", "degraded then lost", "degraded under a tenth of an hour"])
    def test_custody_is_shown_as_held_lost_or_degraded(self, gap: float, degraded: float, expected: str) -> None:
        """SPC-179: degraded is never shown as held or lost, and its hours are never called hours lost."""
        path = SimpleNamespace(custody_maintained=gap == 0.0 and degraded == 0.0, custody_gap_hours=gap,
                               custody_degraded_hours=degraded)
        assert custody_value(path, 6.0) == expected  # type: ignore[arg-type]

    def test_custody_lost_says_for_how_long(self) -> None:
        result = sampled_result()
        lost = [(n, v) for n, v in _paired(result) if not n.path.custody_maintained]
        assert lost
        for node, shown in lost:
            assert shown.figures[5].value == f"lost for up to {node.path.custody_gap_hours:.1f} h of the 1 h horizon"
            assert node.path.custody_bases[1].note in shown.figures[5].note


class TestThePlan:
    @pytest.mark.parametrize("strategy", list(SelectorStrategy))
    def test_a_node_on_the_plan_says_so_in_words(self, strategy: SelectorStrategy) -> None:
        result = still_result(strategy)
        selection = _tree(result).selection
        assert selection is not None
        marked = 0
        for _, shown in _paired(result):
            on = follows_picks(result.scenario, selection, _steps(result.scenario, shown))
            assert shown.on_plan is on
            assert shown.plan == (PLAN_MARK.format(rule=strategy.value.replace("_", " ")) if on else "")
            marked += on
        assert marked >= 2


class TestTheRecommendationAndTheUpdate:
    def test_the_recommendation_and_update_are_the_selections_two_parts(self) -> None:
        result = sampled_result(_EV, Seen.BURN)
        selection = _tree(result).selection
        assert selection is not None
        view = _view(result)
        assert view.recommendation == selection.recommendation
        assert view.update == selection.update
        assert OBSERVED.format(seen="a burn") in view.update
        assert view.update_basis is not None
        assert view.update_basis.kind == "lookup"
        assert view.update_basis.note == POSTERIOR_NOTE

    def test_with_nothing_stated_there_is_no_update_basis(self) -> None:
        view = _view(sampled_result(_EV))
        assert NO_OBSERVATION in view.update
        assert view.update_basis is None

    def test_a_stated_no_burn_shows_the_no_burn_update(self) -> None:
        view = _view(sampled_result(_EV, Seen.NO_BURN))
        assert OBSERVED.format(seen="no burn") in view.update
        assert view.update[-1].startswith("If turn 1 shows no burn:")
        assert not any(line.startswith("If turn 1 shows a burn") for line in view.update)

    def test_under_expected_value_the_block_is_the_update(self) -> None:
        assert _view(sampled_result(_EV)).update_heading == UPDATE_HEADING == "The update after turn 1"

    @pytest.mark.parametrize("strategy", [_MINIMAX, SelectorStrategy.MINIMIN])
    def test_under_a_rule_that_reads_no_probability_the_block_is_what_each_turn_lets_us_see(
        self, strategy: SelectorStrategy,
    ) -> None:
        view = _view(still_result(strategy))
        assert view.update_heading == UPDATE_HEADING_NO_PROBABILITY == "What each turn lets us see"

    def test_the_rule_is_named(self) -> None:
        assert _view(still_result(_MINIMAX)).rule == "minimax"
        assert _view(sampled_result(_EV)).rule == "expected value"


class TestATreeBuiltInPart:
    def test_it_names_the_deepest_turn_built_in_full(self) -> None:
        result = still_result()
        tree = _tree(result)
        roots = tuple(dataclasses.replace(r, children=()) for r in tree.roots)
        part = dataclasses.replace(result, tree=dataclasses.replace(tree, roots=roots, complete_turns=1))
        view = _view(part)
        assert view.deepest == TREE_DEEPEST.format(k=1, turns=2)
        assert all(n.children == () for n in view.nodes)


class TestTheTimeOfClosestApproach:
    """Written to no finer than it is known, with its uncertainty, or why there is none."""

    _EPOCH = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    _TCA = _EPOCH + timedelta(hours=1.2345)

    def test_with_no_uncertainty_recorded_it_says_so(self) -> None:
        assert _when(self._TCA, self._EPOCH, None) == "1.23 h after the scenario epoch; no uncertainty recorded"

    def test_at_an_edge_of_the_search_it_is_not_an_encounter(self) -> None:
        edge = TcaUncertainty(None, 1.0, 0.01, 7200.0, at_edge=True)
        assert _when(self._TCA, self._EPOCH, edge) == (
            "1.23 h after the scenario epoch; at the edge of the search, not an encounter"
        )

    def test_with_no_closing_speed_it_says_none_is_recorded(self) -> None:
        unknown = TcaUncertainty(None, 1.0, math.nan, 7200.0, at_edge=False)
        assert _when(self._TCA, self._EPOCH, unknown) == "1.23 h after the scenario epoch; no uncertainty recorded"

    def test_minutes_of_uncertainty_allow_tenths_of_an_hour_and_no_finer(self) -> None:
        known = TcaUncertainty(341.0, 1.9, 0.0055, 7200.0, at_edge=False)
        assert _when(self._TCA, self._EPOCH, known) == "1.2 h after the scenario epoch, ± 6 min"

    def test_every_nodes_time_is_written_no_finer_than_its_uncertainty(self) -> None:
        for result in (still_result(), sampled_result()):
            for node, shown in _paired(result):
                tca = node.figures.tca_uncertainty
                assert tca is not None
                h = (node.figures.tca_utc - result.scenario.epoch_utc).total_seconds() / 3600.0
                assert shown.figures[1].value.startswith(f"{tca.hours(h)} h after the scenario epoch")
        root = _view(still_result()).nodes[0]
        assert root.figures[1].value == "4.0 h after the scenario epoch, ± 6 min"

    def test_every_nodes_time_states_what_its_uncertainty_rests_on_and_how_it_is_shown(self) -> None:
        for result in (still_result(), sampled_result()):
            for node, shown in _paired(result):
                tca = node.figures.tca_uncertainty
                assert tca is not None
                note = shown.figures[1].note
                assert tca.title in note
                assert "shown to the minute" not in note
                assert "shown here in hours after the scenario epoch, no finer than its uncertainty allows" in note

    def test_a_time_with_no_uncertainty_recorded_says_so_in_its_note(self) -> None:
        assert _when_note("time of that closest approach, refined to 0.01 s and shown to the minute", None) == (
            "time of that closest approach, refined to 0.01 s; shown here in hours after the scenario epoch, no "
            "finer than its uncertainty allows. No uncertainty is recorded for this time."
        )

    def test_with_an_uncertainty_it_is_shown_at_its_scale(self) -> None:
        known = TcaUncertainty(4.0, 1.0, 0.25, 7200.0, at_edge=False)
        shown = _when(self._TCA, self._EPOCH, known)
        assert shown == f"{known.hours(1.2345)} h after the scenario epoch, ± 4 s"
        assert shown.startswith("1.23 h")
