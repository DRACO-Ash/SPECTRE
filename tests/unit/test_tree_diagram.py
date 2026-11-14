"""The game tree drawn (SPC-190, owner ruling of 2026-11-05 on D15).

A drawn tree beside the plain branches, which stay as its text alternative. tree_view lays it out on the server, left
to right, a column per turn and each branch a box beside its children; partials/decision_tree.html writes it as SVG,
and static/js/tree_diagram.js collapses and zooms it. Every box shows its branch's heading and two of its figures,
the sequence's score and closest approach along it, written exactly as the branch below writes them, so the drawing
and the text cannot differ. A box on the plan, a best continuation and a branch excluded as not permitted each say
so in words.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from spectre.domain.decision import ScenarioResult, SelectorStrategy
from spectre.web.tree_view import (
    DIAGRAM_FIGURES,
    REMAINDER_BESIDE,
    DiagramBox,
    NodeView,
    TreeDiagram,
    TreeView,
    diagram,
    tree_view,
)
from tests.unit._tree_view_cases import still_result

_MINIMAX = SelectorStrategy.MINIMAX


def _view(result: ScenarioResult) -> TreeView:
    view = tree_view(result)
    assert view is not None
    return view


def _diagram(result: ScenarioResult) -> TreeDiagram:
    diagram = _view(result).diagram
    assert diagram is not None
    return diagram


def _flat(nodes: tuple[NodeView, ...]) -> list[NodeView]:
    out: list[NodeView] = []
    for node in nodes:
        out += [node, *_flat(node.children)]
    return out


def _pairs(result: ScenarioResult) -> list[tuple[NodeView, DiagramBox]]:
    return list(zip(_flat(_view(result).nodes), _diagram(result).boxes, strict=True))


def _vetoed(result: ScenarioResult, response: int) -> ScenarioResult:
    """*result* with its *response* marked not permitted, as the operator marks it (SPC-195)."""
    scenario = result.scenario
    responses = list(scenario.friendly_responses)
    responses[response] = dataclasses.replace(responses[response], vetoed=True, veto_reason="rules of engagement")
    return dataclasses.replace(result, scenario=dataclasses.replace(scenario, friendly_responses=responses))


class TestEveryBranchIsDrawn:
    def test_one_box_per_branch_in_the_order_the_branches_are_listed(self) -> None:
        result = still_result()
        assert [box.key for box in _diagram(result).boxes] == [node.key for node in _flat(_view(result).nodes)]
        assert len(_diagram(result).boxes) == 20

    def test_a_branch_key_is_its_moves_and_responses_turn_by_turn(self) -> None:
        view = _view(still_result())
        assert view.nodes[1].key == "0.1"
        assert view.nodes[1].children[3].key == "0.1-1.1"

    def test_each_box_names_its_parent(self) -> None:
        for node, box in _pairs(still_result()):
            assert box.parent == ("" if node.turn == 1 else box.key.rsplit("-", 1)[0])

    def test_a_tree_with_no_branch_draws_nothing(self) -> None:
        result = still_result()
        assert result.tree is not None
        bare = dataclasses.replace(result, tree=dataclasses.replace(result.tree, roots=()))
        assert _view(bare).diagram is None


class TestEachBoxSaysWhatItsBranchSays:
    def test_its_title_is_the_branchs_heading(self) -> None:
        for node, box in _pairs(still_result()):
            assert box.title == node.heading

    def test_its_figures_are_the_branchs_own_written_the_same(self) -> None:
        assert DIAGRAM_FIGURES == ("Sequence score", "Closest approach along the sequence")
        for node, box in _pairs(still_result()):
            shown = {f.label: f"{f.label}: {f.value} ({f.kind})" for f in node.figures}
            assert box.figures == tuple(shown[label] for label in DIAGRAM_FIGURES)

    def test_its_lines_are_title_figures_then_mark(self) -> None:
        for _, box in _pairs(still_result(_MINIMAX)):
            texts = [line.text for line in box.lines]
            assert texts == [box.title, *box.figures, *([box.mark] if box.mark else [])]
            assert [line.kind for line in box.lines][:3] == ["title", "figure", "figure"]
            assert all(b.y < a.y for b, a in itertools.pairwise(box.lines))

    def test_a_remainder_branch_carries_its_caveat_under_its_title_as_the_list_does(self) -> None:
        """A figure shown must carry its caveat: red's move there is the engine's remainder of P (SPC-203)."""
        view = _view(still_result())
        marked = tuple(
            dataclasses.replace(root, remainder=REMAINDER_BESIDE if i == 1 else "", children=tuple(
                dataclasses.replace(child, remainder=REMAINDER_BESIDE if child.steps[-1][0] == 1 else "")
                for child in root.children
            ))
            for i, root in enumerate(view.nodes)
        )
        drawn = diagram(marked, [False, False])
        assert drawn is not None
        for node, box in zip(_flat(marked), drawn.boxes, strict=True):
            kinds = [(line.kind, line.text) for line in box.lines]
            if node.remainder:
                assert kinds[:2] == [("title", node.heading), ("remainder", REMAINDER_BESIDE)]
            else:
                assert "remainder" not in [kind for kind, _ in kinds]
        assert drawn.box_h == 2 * drawn.pad + 5 * 13.0, "room for the title, the caveat, two figures and a mark"

    def test_the_real_remainder_tree_draws_every_caveat_the_list_shows(self) -> None:
        from tests.unit.test_decision_p_remainder_weight import _tree_result

        view = _view(_tree_result())
        drawn = view.diagram
        assert drawn is not None
        caveats = [box.key for box in drawn.boxes if any(line.kind == "remainder" for line in box.lines)]
        assert caveats == [node.key for node in _flat(view.nodes) if node.remainder]
        assert caveats


class TestMarksInWords:
    def test_a_box_on_the_plan_says_so(self) -> None:
        pairs = _pairs(still_result(_MINIMAX))
        planned = [(n, b) for n, b in pairs if n.on_plan]
        assert len(planned) >= 2
        for node, box in pairs:
            if node.on_plan:
                assert (box.mark_kind, box.mark) == ("plan", "★ On the plan")
            elif not node.continuation:
                assert (box.mark_kind, box.mark) == ("", "")

    def test_a_best_continuation_says_so_and_never_as_the_plan(self) -> None:
        pairs = _pairs(still_result(_MINIMAX))
        continued = [b for n, b in pairs if n.continuation]
        assert continued
        assert {(b.mark_kind, b.mark) for b in continued} == {("continuation", "Best continuation, not on the plan")}

    def test_a_branch_not_permitted_and_every_branch_after_it_say_so(self) -> None:
        pairs = _pairs(_vetoed(still_result(_MINIMAX), 1))
        own = [b for n, b in pairs if n.steps[-1][1] == 1]
        after = [b for n, b in pairs if n.steps[-1][1] != 1 and any(r == 1 for _, r in n.steps[:-1])]
        assert own and after
        assert {(b.mark_kind, b.mark) for b in own} == {("not-permitted", "Not permitted")}
        assert {(b.mark_kind, b.mark) for b in after} == {
            ("not-permitted", "Excluded: it follows a response not permitted"),
        }


class TestTheLayout:
    def test_a_column_per_turn_from_the_left(self) -> None:
        diagram = _diagram(still_result())
        for node, box in _pairs(still_result()):
            assert box.x == diagram.margin + (node.turn - 1) * diagram.col_pitch

    def test_each_leaf_a_row_and_each_parent_between_its_first_and_last_child(self) -> None:
        diagram = _diagram(still_result())
        leaves = [box for box in diagram.boxes if not box.toggle]
        assert [box.y for box in leaves] == [diagram.margin + i * diagram.row_pitch for i in range(len(leaves))]
        by_key = {box.key: box for box in diagram.boxes}
        for box in diagram.boxes:
            children = [b for b in diagram.boxes if b.parent == box.key]
            if children:
                assert box.y == (children[0].y + children[-1].y) / 2
                assert by_key[children[0].parent] is box

    def test_the_drawing_holds_every_box_with_its_margin(self) -> None:
        diagram = _diagram(still_result())
        assert diagram.width == 2 * diagram.margin + diagram.col_pitch + diagram.box_w
        assert diagram.height == 2 * diagram.margin + 15 * diagram.row_pitch + diagram.box_h
        assert diagram.col_pitch == diagram.box_w + diagram.col_gap
        assert diagram.row_pitch == diagram.box_h + diagram.row_gap

    def test_a_box_is_as_wide_as_its_longest_line(self) -> None:
        diagram = _diagram(still_result())
        longest = max(len(line.text) for box in diagram.boxes for line in box.lines)
        assert diagram.box_w == round(longest * diagram.char_w + 2 * diagram.pad)

    def test_each_edge_runs_from_its_parents_right_side_to_its_own_left_side(self) -> None:
        diagram = _diagram(still_result())
        by_key = {box.key: box for box in diagram.boxes}
        half = diagram.box_h / 2
        for box in diagram.boxes:
            if not box.parent:
                assert box.edge == ""
                continue
            parent = by_key[box.parent]
            x1, y1, x2, y2 = parent.x + diagram.box_w, parent.y + half, box.x, box.y + half
            middle = (x1 + x2) / 2
            assert box.edge == f"M{x1:g} {y1:g} C{middle:g} {y1:g} {middle:g} {y2:g} {x2:g} {y2:g}"


class TestTheControls:
    def test_only_a_box_with_branches_after_it_has_a_control(self) -> None:
        for node, box in _pairs(still_result()):
            assert box.toggle is bool(node.children)

    @pytest.mark.parametrize("index", [0, 3])
    def test_the_controls_names_say_what_they_do_and_to_which_branch(self, index: int) -> None:
        node, box = _pairs(still_result())[index * 5]
        assert node.turn == 1
        assert box.collapse_label == f"Collapse the branches after {node.heading}"
        assert box.expand_label == f"Open the branches after {node.heading}"
