"""The best branch under each response, marked in words apart from the plan (SPC-189, design D14).

Until 0.38.0 a branch was marked only when every response on it was the rule's pick for what the turns before it
showed: the plan the recommendation follows. A branch reached through a response the rule would not choose carried
no mark, so the operator who weighed another response saw no recommended way on from it. The owner ruled on
2026-11-05 to mark the best branch under each response, including responses the rule would not pick. The selector
already picks in every information set, so the mark is read from those picks: a branch is the best continuation
under a response the rule does not pick when every response after it is the rule's pick for what the turns before
showed. It is said in words of its own, never the plan's, and carries no star.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import SelectorStrategy
from spectre.domain.tree_selectors import TreeSelection, continuation, follows_picks, select
from spectre.domain.turn_update import Seen
from spectre.web.tree_view import CONTINUATION_MARK, PLAN_MARK, NodeView, tree_view
from tests.unit._tree_view_cases import still_result
from tests.unit.test_tree_selectors import _scenario, _tree, _two_turn_score

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_MINIMAX = SelectorStrategy.MINIMAX


def _hand() -> TreeSelection:
    """test_tree_selectors' two-turn hand tree under minimax, custody held. Turn 1 picks Hold (0.5 against 0.6).
    After Hold: Avoid if turn 1 shows no burn (0.5 against 0.9), Hold after a burn (0.3 against 0.6). After Avoid,
    which the rule does not pick, every sequence costs 0.1 more, so the picks there are the same: Avoid after no
    burn, Hold after a burn."""
    return select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)


class TestTheSelectorPicksUnderEveryResponse:
    def test_every_information_set_keeps_its_pick(self) -> None:
        selection = _hand()
        every = {p.after: p.pick for p in selection.every}
        assert every == {
            (): 0,
            ((0, Seen.NO_BURN),): 1, ((0, Seen.BURN),): 0,
            ((1, Seen.NO_BURN),): 1, ((1, Seen.BURN),): 0,
        }
        assert {p.after for p in selection.picks} == {(), ((0, Seen.NO_BURN),), ((0, Seen.BURN),)}

    @pytest.mark.parametrize(
        ("steps", "turn"),
        [
            (((0, 1), (0, 1)), 1),   # Hold course, then after no burn the pick, Avoid
            (((1, 1), (0, 0)), 1),   # Evasive, then after a burn the pick, Hold
            (((1, 1), (1, 0)), 1),
            (((0, 1), (1, 1)), 1),
        ],
    )
    def test_the_best_branch_under_a_response_not_picked_is_its_continuation(
        self, steps: tuple[tuple[int, int], ...], turn: int,
    ) -> None:
        selection = _hand()
        assert continuation(_scenario(), selection, steps) == turn
        assert not follows_picks(_scenario(), selection, steps)

    @pytest.mark.parametrize(
        "steps",
        [
            ((0, 1),),                # the response not picked itself
            ((0, 1), (0, 0)),         # Hold after no burn, not the pick there
            ((1, 1), (1, 1)),         # Avoid after a burn, not the pick there
            ((0, 0), (0, 1)),         # on the plan
            ((0, 0),),                # on the plan
            ((0, 0), (0, 0)),         # under the pick, off the plan in turn 2: that branch is its own response
        ],
    )
    def test_no_other_branch_is_a_continuation(self, steps: tuple[tuple[int, int], ...]) -> None:
        assert continuation(_scenario(), _hand(), steps) is None

    def test_off_the_plan_in_turn_two_a_three_turn_tree_continues_from_there(self) -> None:
        """Three turns, each response costing its turn's index times 0.1 more for Avoid: the rule holds every turn,
        so Avoid in turn 2 is off the plan and Hold in turn 3 after it is its best continuation, from turn 2."""
        def score(path: tuple[tuple[int, int], ...]) -> float:
            return sum(0.1 * k * r for k, (_, r) in enumerate(path, start=1))

        scenario = _scenario(turns=3)
        selection = select(scenario, _tree(2, 2, 3, score), 3, _MINIMAX, matrix_pick=0)
        assert continuation(scenario, selection, ((0, 0), (0, 1), (0, 0))) == 2
        assert continuation(scenario, selection, ((0, 1), (0, 0), (1, 0))) == 1
        assert continuation(scenario, selection, ((0, 1), (0, 1), (1, 0))) == 2
        assert continuation(scenario, selection, ((0, 0), (0, 0), (0, 0))) is None


def _flat(nodes: tuple[NodeView, ...]) -> list[NodeView]:
    out: list[NodeView] = []
    for node in nodes:
        out += [node, *_flat(node.children)]
    return out


class TestTheViewMarksItApartFromThePlan:
    @pytest.mark.parametrize("strategy", list(SelectorStrategy))
    def test_each_continuation_says_so_in_its_own_words(self, strategy: SelectorStrategy) -> None:
        result = still_result(strategy)
        assert result.tree is not None and result.tree.selection is not None
        selection = result.tree.selection
        view = tree_view(result)
        assert view is not None
        rule = strategy.value.replace("_", " ")
        responses = [f.name for f in result.scenario.friendly_responses]
        marked = 0
        for node in _flat(view.nodes):
            turn = continuation(result.scenario, selection, node.steps)
            if turn is None:
                assert node.continuation == ""
                continue
            marked += 1
            response = responses[node.steps[turn - 1][1]]
            assert node.continuation == CONTINUATION_MARK.format(rule=rule, response=response, k=turn)
            assert not node.on_plan
            assert node.plan == ""
        not_picked = sum(1 for root in view.nodes if not root.on_plan)
        assert not_picked >= 1
        assert marked >= not_picked

    def test_the_mark_is_not_the_plans(self) -> None:
        mark = CONTINUATION_MARK.format(rule="minimax", response="Avoid", k=1)
        assert mark == "Best continuation under minimax after Avoid in turn 1, which minimax does not pick there; " \
                       "not on the plan"
        assert PLAN_MARK.format(rule="minimax") not in mark

    def test_the_page_shows_it_in_words_with_no_star(self) -> None:
        from spectre.web.app import templates as _app_templates

        result = still_result(_MINIMAX)
        view = tree_view(result)
        assert view is not None
        env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True, undefined=StrictUndefined)
        env.filters.update(_app_templates.env.filters)
        html = env.get_template("partials/decision_tree.html").render(tree=view)
        marks = re.findall(r'<span class="tree-continuation"[^>]*>([^<]*)</span>', html)
        expected = [node.continuation for node in _flat(view.nodes) if node.continuation]
        assert [" ".join(m.split()) for m in marks] == expected
        assert all("★" not in m and "&#9733;" not in m for m in marks)
        assert html.count("&#9733;") == sum(node.on_plan for node in _flat(view.nodes))
