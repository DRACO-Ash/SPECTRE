"""Two assumptions of the score and the game tree, stated where they bite (SPC-219 and SPC-220).

Evaluation F-20: the composite score adds custody lost and closest approach as separate terms, with nothing joining
them, so a close approach while custody is lost scores only what the two score apart. No source for a term joining
them was found, so none is added and the assumption is stated: beside the outcome matrix and the game tree, in the
Decision Engine's documentation, in the operator guide's limitations, and in the lookup register.

Evaluation F-21: each branch of a game tree's last turn, at most turn 3, is valued as if no one moves after it. It is
stated beside the tree and in the guide's limitations.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import MAX_TURNS, TERMS_INDEPENDENT_LINE
from spectre.web.tree_view import LEAVES_LINE, TreeView, tree_view
from tests.unit._tree_view_cases import still_result
from tests.unit.test_decision_figure_basis import _render as render_results
from tests.unit.test_deployment_contract import _repo_only

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _view() -> TreeView:
    view = tree_view(still_result())
    assert view is not None
    return view


def _tree_html(view: TreeView) -> str:
    from spectre.web.app import templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True, undefined=StrictUndefined)
    env.filters.update(templates.env.filters)
    return env.get_template("partials/decision_tree.html").render(tree=view)


class TestTheWords:
    def test_the_independence_is_said_plainly(self) -> None:
        assert TERMS_INDEPENDENT_LINE == (
            "Custody lost and closest approach are added to the score as separate terms, with nothing joining them: "
            "a close approach while custody is lost scores what the two score apart, no more, though an approach "
            "we cannot see may be worse than the two added together. No source for a term joining them was found, "
            "so none is added. An unsourced assumption, listed in docs/lookup-register.md."
        )

    def test_the_leaves_line_names_the_last_turn_and_the_most_there_can_be(self) -> None:
        assert MAX_TURNS == 3
        assert _view().assumptions[0] == LEAVES_LINE.format(turns=2, most=MAX_TURNS) == (
            "Each branch of the last turn shown, turn 2 here and turn 3 at most, is valued as if no one moves after "
            "it: its figures run to the end of the span searched with neither red nor us burning again, so a move "
            "either side would make later is in no figure."
        )


    def test_a_tree_built_in_part_names_the_deepest_turn_it_shows(self) -> None:
        """Built in full to turn 1 of 2, the branches shown last are turn 1's, and the line says so."""
        result = still_result()
        tree = result.tree
        assert tree is not None and tree.turns == 2
        roots = tuple(dataclasses.replace(r, children=()) for r in tree.roots)
        part = dataclasses.replace(result, tree=dataclasses.replace(tree, roots=roots, complete_turns=1))
        view = tree_view(part)
        assert view is not None
        assert view.assumptions[0] == LEAVES_LINE.format(turns=1, most=MAX_TURNS)
        assert view.assumptions[0].startswith("Each branch of the last turn shown, turn 1 here and turn 3 at most")


class TestOnScreen:
    def test_beside_the_outcome_matrix(self) -> None:
        page = _flat(render_results(still_result()))
        heading = page.index("Outcome Matrix")
        line = page.index('<p class="terms-independent" role="note"')
        assert heading < line < page.index("<table", heading)
        assert TERMS_INDEPENDENT_LINE in page

    def test_beside_the_game_tree_both_are_stated(self) -> None:
        view = _view()
        assert view.assumptions == (LEAVES_LINE.format(turns=2, most=MAX_TURNS), TERMS_INDEPENDENT_LINE)
        section = _flat(_tree_html(view))
        notes = re.findall(r'<p class="tree-assumption" role="note"[^>]*>([^<]*)</p>', section)
        assert notes == list(view.assumptions)
        assert section.index("</h3>") < section.index('class="tree-assumption"') < section.index("tree-lines")

    def test_a_tree_not_built_states_neither(self) -> None:
        result = still_result()
        assert result.tree is not None
        bare = dataclasses.replace(result, tree=dataclasses.replace(result.tree, roots=()))
        view = tree_view(bare)
        assert view is not None
        assert view.assumptions == ()
        assert "tree-assumption" not in _tree_html(view)


class TestInTheDocuments:
    def test_the_guides_limitations_state_both(self) -> None:
        # Adjacent string literals joined, as Python joins them.
        guide = re.sub(r'"\s+"', "", _repo_only("docs/generate_guide.py").read_text("utf-8"))
        start = guide.index('"What It Does Not Do"')
        limits = guide[start:guide.index("_add_callout", start)]
        assert "It adds custody lost and closest approach to the score as separate terms" in limits
        assert "a move red or you would make later is in no figure" in limits

    def test_the_decision_engine_docs_state_the_independence(self) -> None:
        docs = _flat(_repo_only("docs/decision_engine_phases.md").read_text("utf-8"))
        assert "Custody lost and closest approach are separate terms (SPC-219, evaluation F-20)" in docs
        assert "may be worse than the two added together" in docs

    def test_every_document_names_the_compound_risk_not_either_alone(self) -> None:
        """F-20's point is a risk worse than the two penalties added together, which the sum cannot hold."""
        guide = re.sub(r'"\s+"', "", _repo_only("docs/generate_guide.py").read_text("utf-8"))
        register = _flat(_repo_only("docs/lookup-register.md").read_text("utf-8"))
        assert "may be worse than the two added together" in guide
        assert "may be worse than the two added together" in register
        for text in (guide, register, _flat(_repo_only("docs/decision_engine_phases.md").read_text("utf-8"))):
            assert "worse than either alone" not in text

    def test_the_decision_engine_docs_say_the_view_scripts_only_collapse_and_zoom(self) -> None:
        docs = _flat(_repo_only("docs/decision_engine_phases.md").read_text("utf-8"))
        assert "adds no script" not in docs
        assert (
            "The view reads at phone width and says everything in words as well as colour. Its only script collapses "
            "and zooms the drawn tree; the drawing and the branches in words work without it."
        ) in docs

    def test_the_register_lists_both_as_unsourced(self) -> None:
        register = _flat(_repo_only("docs/lookup-register.md").read_text("utf-8"))
        section = register[register.index("## Assumptions with no constant"):]
        assert "● **Custody lost and closest approach are independent** (SPC-219, evaluation F-20)" in section
        assert "● **No one moves after the last turn** (SPC-220, evaluation F-21)" in section
        assert section.count("Basis: none: unsourced judgement.") == 2
