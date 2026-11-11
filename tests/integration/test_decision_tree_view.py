"""The game tree's view (SPC-142): a turn-depth selector, the tree in the results, and the update after turn 1.

The panel offers a labelled turn depth of 1 to 3 and a labelled observation of what turn 1 showed, which only the
update under expected value reads. A depth whose tree cannot fit the branch cap or the cost cap is refused inline
on Evaluate, naming the largest depth that would; nothing is started. The results show the tree server-rendered as
nested details and summary elements, each node with its figures, their basis and the path it rests on; the per-turn
recommendation for the selector in use; the update with its likelihood model for the stated observation, or a line
saying none was stated so nothing was updated; and, for a tree built in part, the deepest turn built in full. It
reads at phone width, says everything in words as well as colour, and renders under StrictUndefined.

The trees here are built for real, once each: a still tree in under a second and a small sampled one in a few.
"""

from __future__ import annotations

import dataclasses
import html
import re
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from spectre.domain.decision import ScenarioResult, Seen, SelectorStrategy
from spectre.domain.decision_tree import MAX_TREE_BRANCHES, TREE_DEEPEST, TREE_DEPTH_BRANCHES, TREE_UNBOUND
from spectre.domain.tree_selectors import NO_OBSERVATION, OBSERVED, PROBABILITY_IGNORED
from spectre.web.decision_job import DecisionJob, JobState
from spectre.web.routes.decision import _OBSERVATION_LABELS, _OBSERVED_ONE_TURN
from spectre.web.tree_view import PLAN_MARK, tree_view
from tests.integration.conftest import session_state
from tests.integration.test_decision_binding_on_screen import _hold
from tests.integration.test_decision_hypothesis_panel import _panel, _scenario_of, captured, held  # noqa: F401
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_job import _settled, owner  # noqa: F401
from tests.integration.test_form_labels import _unlabelled
from tests.unit._i13 import i13_problems
from tests.unit._tree_view_cases import sampled_result, still_result

_TEMPLATES = Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates"
_EV, _MINIMAX = SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMAX


def _block(html_text: str, marker: str) -> str:
    start = html_text.index(marker)
    return html_text[start:html_text.index("</label>", start) + len("</label>")]


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _sentences(fragment: str) -> list[str]:
    return [s for s in re.split(r"(?<=\.)\s", _text(fragment)) if s]


def _section(page: str) -> str:
    start = page.index('<section class="decision-tree"')
    return page[start:page.index("</section>", start)]


def _done(cookie: str, result: ScenarioResult) -> str:
    """Hold *result* as this sign-in's finished job; its id."""
    job = DecisionJob(job_id="tree-view-job", scenario=result.scenario, strategy=result.robust_strategy)
    job.state, job.result = JobState.DONE, result
    session_state(cookie).decision_job = job  # type: ignore[attr-defined]
    return job.job_id


def _results(client: Any, cookie: str, result: ScenarioResult) -> str:
    job_id = _done(cookie, result)
    resp = client.get("/plan/decision/job", params={"job_id": job_id}, cookies={"spectre_session": cookie})
    assert resp.status_code == 200
    return resp.text


@pytest.fixture
def no_job(auth_cookie: str) -> Any:
    state = session_state(auth_cookie)
    saved = state.decision_job  # type: ignore[attr-defined]
    yield state
    state.decision_job = saved  # type: ignore[attr-defined]


# ── The panel ──

class TestThePanel:
    def test_it_offers_a_labelled_turn_depth_of_1_to_3(self, client: Any, auth_cookie: str) -> None:
        block = _block(_panel(client, auth_cookie), '<label class="tree-depth"')
        assert "Turn depth" in block
        assert re.findall(r'<option value="(\d)"', block) == ["1", "2", "3"]
        assert re.search(r'<option value="1" selected>', block)
        assert 'name="turns"' in block
        assert _unlabelled(block) == []

    def test_it_offers_a_labelled_observation_of_turn_1(self, client: Any, auth_cookie: str) -> None:
        block = _block(_panel(client, auth_cookie), '<label class="tree-observed"')
        assert 'name="observed"' in block
        assert re.findall(r'<option value="([a-z_]*)"', block) == ["", "burn", "no_burn", "nothing"]
        assert "Not stated: nothing is updated" in block
        assert _unlabelled(block) == []

    def test_nothing_shown_names_degraded_custody(self, client: Any, auth_cookie: str) -> None:
        """SPC-179 keeps degraded custody as a case that shows nothing at a turn, so the choice says so, as served
        and in the panel's own list for a render without the route's."""
        block = _block(_panel(client, auth_cookie), '<label class="tree-observed"')
        nothing = "Nothing: custody degraded, lost for another reason, or not read"
        assert re.search(r'<option value="nothing"[^>]*>\s*' + re.escape(nothing) + r"\s*<", block)
        fallback = (_TEMPLATES / "partials" / "decision_panel.html").read_text(encoding="utf-8")
        for seen, label in _OBSERVATION_LABELS.items():
            assert f'("{seen.name.lower()}", "{label}")' in fallback

    def test_its_hint_says_what_a_tree_needs_and_what_is_refused(self, client: Any, auth_cookie: str) -> None:
        page = _panel(client, auth_cookie)
        start = page.index('<div class="tree-fields"')
        hint = _text(page[start:page.index("</div>", page.index('<p class="tree-hint"', start))])
        assert "red track and a blue asset bound" in hint
        assert "naming the largest that would" in hint
        assert "only expected value reads it" in hint

    def test_it_adds_no_handler_attribute_or_script(self, client: Any, auth_cookie: str) -> None:
        page = _panel(client, auth_cookie)
        start = page.index('<div class="tree-fields"')
        block = page[start:page.index("</div>", page.index('<p class="tree-hint"', start))]
        assert not re.search(r"\son[a-z]+=", block)
        assert "<script" not in block
        assert "hx-" not in block


# ── The form ──

class TestTheForm:
    @pytest.mark.parametrize("raw", ["0", "4", "two", "2.5"])
    def test_a_depth_out_of_range_is_refused_inline(self, client: Any, auth_cookie: str, raw: str) -> None:
        """A blank select cannot be posted from the panel; FastAPI reads a blank field as absent, which is 1 turn."""
        resp = _evaluate(client, auth_cookie, _form(turns=raw))
        assert resp.status_code == 200
        assert f"The turn depth must be a whole number between 1 and 3; got {raw}." in html.unescape(resp.text)

    def test_an_unlisted_observation_is_refused_inline(self, client: Any, auth_cookie: str) -> None:
        resp = _evaluate(client, auth_cookie, _form(observed="a burn"))
        assert "Choose a listed observation for turn 1." in resp.text

    def test_an_observation_at_a_depth_of_one_turn_is_refused_inline(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
    ) -> None:
        """One turn has no later pick for turn 1's observation to update, so it would be dropped unsaid."""
        _hold(held, red_leo=True)
        form = _form(horizon_hours="6", red_sat="RX", blue_sat="BY", adv_type=["no_action"], fr_type=["no_action"],
                     observed="burn")
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200
        assert 'class="error-msg"' in resp.text
        assert _OBSERVED_ONE_TURN in html.unescape(resp.text)
        assert "turn depth of 2 or 3" in _OBSERVED_ONE_TURN
        assert captured == []

    def test_the_depth_and_observation_reach_the_scenario(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
    ) -> None:
        _hold(held, red_leo=True)
        form = _form(horizon_hours="6", red_sat="RX", blue_sat="BY", adv_type=["no_action"], fr_type=["no_action"],
                     turns="2", observed="no_burn")
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200, resp.text
        scenario = _scenario_of(captured)
        assert (scenario.turns, scenario.observed) == (2, Seen.NO_BURN)

    def test_one_turn_and_none_stated_are_the_defaults(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
    ) -> None:
        _hold(held, red_leo=True)
        form = _form(horizon_hours="6", red_sat="RX", blue_sat="BY", adv_type=["no_action"], fr_type=["manoeuvre"],
                     fr_target=["20"], fr_budget=[""], fr_axis=["cheapest"])
        _evaluate(client, auth_cookie, form)
        scenario = _scenario_of(captured)
        assert (scenario.turns, scenario.observed) == (1, None)

    def test_a_tree_too_big_is_refused_inline_naming_the_largest_that_fits(
        self, client: Any, auth_cookie: str, held: Any, captured: list[DecisionJob],  # noqa: F811
    ) -> None:
        _hold(held, red_leo=True)
        form = _form(
            horizon_hours="6", red_sat="RX", blue_sat="BY", turns="3",
            adv_id=["A1", "A2", "A3", "A4"], adv_name=["S1", "S2", "S3", "S4"], adv_type=["no_action"] * 4,
            adv_prob=["0.25"] * 4, adv_conf=["0.7"] * 4,
            fr_id=["F1", "F2", "F3"], fr_name=["H1", "H2", "H3"], fr_type=["no_action"] * 3, fr_cost=["0.2"] * 3,
            fr_rev=["0.8"] * 3, fr_time=["1"] * 3,
        )
        resp = _evaluate(client, auth_cookie, form)
        assert resp.status_code == 200
        expected = TREE_DEPTH_BRANCHES.format(
            turns=3, rows=4, responses=3, nodes=1_884, cap=MAX_TREE_BRANCHES,
            largest="The largest turn depth that fits at these sizes is 2.",
        )
        assert 'class="error-msg"' in resp.text
        assert expected in html.unescape(resp.text)
        assert captured == []

    def test_an_unbound_tree_answers_at_once_saying_why_it_is_one_turn(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        resp = _evaluate(client, auth_cookie, _form(turns="2"))
        assert resp.status_code == 200
        section = _section(resp.text)
        assert TREE_UNBOUND in html.unescape(section)
        assert '<details class="tree-node"' not in section
        assert "Game tree: 2 turns asked for, none built" in _text(section)


# ── The results ──

class TestTheTree:
    def test_every_branch_is_a_collapsible_node_nested_under_its_parent(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        section = _section(_results(client, auth_cookie, still_result()))
        assert section.count('<details class="tree-node"') == 20
        assert section.count("<summary") >= 20
        # Each turn-1 node holds its four turn-2 nodes inside it.
        first = section.index('<details class="tree-node" data-turn="1"')
        second = section.index('<details class="tree-node" data-turn="1"', first + 1)
        assert section[first:second].count('data-turn="2"') == 4

    def test_each_node_shows_its_figures_their_basis_and_its_path(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        result = still_result()
        view = tree_view(result)
        assert view is not None
        text = _text(_section(_results(client, auth_cookie, result)))
        root = view.nodes[1]
        child = root.children[3]
        for node in (root, child):
            assert node.heading in text
            assert node.path in text
            for figure in node.figures:
                assert f"{figure.label}: {figure.value} ({figure.kind})" in text
                assert figure.note in text

    def test_delta_v_is_in_metres_per_second(self, client: Any, auth_cookie: str, no_job: Any) -> None:
        section = _section(_results(client, auth_cookie, still_result()))
        assert "Our burn this turn: 15 m/s (lookup)" in _text(section)

    def test_the_recommendation_for_the_selector_in_use_is_shown_per_turn(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        result = still_result(_MINIMAX)
        assert result.tree is not None and result.tree.selection is not None
        text = _text(_section(_results(client, auth_cookie, result)))
        assert "Recommendation per turn, minimax" in text
        for line in result.tree.selection.recommendation:
            assert line in text
        assert "Turn 1:" in text
        assert PROBABILITY_IGNORED.format(rule="Minimax") in text

    def test_under_minimax_the_block_says_what_each_turn_lets_us_see_not_an_update(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        section = _section(_results(client, auth_cookie, still_result(_MINIMAX)))
        start = section.index('<div class="tree-update"')
        block = _text(section[start:section.index("</div>", start)])
        assert block.startswith("What each turn lets us see")
        assert "The update after turn 1 rests" not in block
        assert "rows' P" not in block and "weighed by" not in block

    def test_a_node_on_the_plan_says_so_in_words(self, client: Any, auth_cookie: str, no_job: Any) -> None:
        result = still_result(_MINIMAX)
        view = tree_view(result)
        assert view is not None
        section = _section(_results(client, auth_cookie, result))
        marked = sum(n.on_plan for root in view.nodes for n in (root, *root.children))
        assert marked >= 2
        assert section.count(PLAN_MARK.format(rule="minimax")) == marked

    def test_with_no_observation_stated_nothing_is_updated_and_it_says_so(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        text = _text(_section(_results(client, auth_cookie, sampled_result(_EV))))
        assert "The update after turn 1" in text
        assert "likelihood model" in text
        assert NO_OBSERVATION in text
        assert "of the weight" not in text

    def test_a_stated_observation_shows_its_update_with_the_model_and_its_basis(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        result = sampled_result(_EV, Seen.BURN)
        assert result.tree is not None and result.tree.selection is not None
        stated = result.tree.selection.stated
        assert stated is not None
        text = _text(_section(_results(client, auth_cookie, result)))
        assert OBSERVED.format(seen="a burn") in text
        assert stated.line in text
        assert "likelihood model" in text
        assert f"Basis of the update (lookup): {stated.basis.note}" in text
        assert (
            "only row 2, Evasive, gives it, so the update puts all the weight there. That is the likelihood model's "
            "assumption, not evidence of more."
        ) in text

    def test_a_tree_built_in_part_names_the_deepest_turn_built_in_full(
        self, client: Any, auth_cookie: str, no_job: Any,
    ) -> None:
        result = still_result()
        tree = result.tree
        assert tree is not None
        roots = tuple(dataclasses.replace(r, children=()) for r in tree.roots)
        part = dataclasses.replace(result, tree=dataclasses.replace(tree, roots=roots, complete_turns=1))
        section = _section(_results(client, auth_cookie, part))
        assert TREE_DEEPEST.format(k=1, turns=2) in _text(section)
        assert 'data-turn="2"' not in section


class TestReadable:
    def test_it_reads_at_phone_width(self, client: Any, auth_cookie: str, no_job: Any) -> None:
        section = _section(_results(client, auth_cookie, sampled_result(_EV)))
        assert "<table" not in section
        assert "nowrap" not in section
        assert not re.search(r"min-width|width:\s*\d{3,}px", section)
        assert "overflow-wrap:anywhere" in section

    def test_the_panels_tree_fields_read_at_phone_width(self, client: Any, auth_cookie: str) -> None:
        """The longest option must wrap within its label, never push the select past the panel's edge."""
        page = _panel(client, auth_cookie)
        start = page.index('<div class="tree-fields"')
        block = page[start:page.index("</div>", page.index('<p class="tree-hint"', start))]
        assert "nowrap" not in block
        assert not re.search(r"min-width:\s*[1-9]|width:\s*\d{3,}px", block)
        assert "display:flex" not in block
        selects = re.findall(r"<select [^>]*>", block)
        assert len(selects) == 2
        for select in selects:
            assert "max-width:100%" in select and "box-sizing:border-box" in select
            assert "margin-left" not in select

    def test_nothing_is_said_by_colour_alone(self, client: Any, auth_cookie: str, no_job: Any) -> None:
        section = _section(_results(client, auth_cookie, still_result(_MINIMAX)))
        for kind in ("computed", "lookup"):
            assert f"({kind})" in section
        assert "On the plan minimax recommends" in section

    def test_every_sentence_passes_the_house_checks(self, client: Any, auth_cookie: str, no_job: Any) -> None:
        section = _section(_results(client, auth_cookie, sampled_result(_EV, Seen.BURN)))
        for sentence in _sentences(section):
            # The engine's own basis rules carry a search tolerance ("to within 1 %") and a bootstrap interval
            # ("95 % bootstrap"), already on the matrix: neither is a Threat or Understanding figure. Every band
            # check holds on every sentence.
            assert [p for p in i13_problems(sentence) if p != "a percentage"] == [], sentence
        for bad in ("—", "–", "--"):
            assert bad not in _text(section)

    def test_names_are_escaped(self, client: Any, auth_cookie: str, no_job: Any) -> None:
        result = still_result()
        payload = "<script>alert('x')</script>"
        scenario = result.scenario
        actions = [dataclasses.replace(a, name=payload) for a in scenario.adversary_actions]
        hostile = dataclasses.replace(result, scenario=dataclasses.replace(scenario, adversary_actions=actions))
        section = _section(_results(client, auth_cookie, hostile))
        assert "<script>alert(" not in section
        assert "&lt;script&gt;" in section


class TestStrictUndefined:
    def _env(self) -> Environment:
        from spectre.web.app import templates

        env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=True, undefined=StrictUndefined)
        env.filters.update(templates.env.filters)
        return env

    def test_the_results_render_with_the_tree(self) -> None:
        result = sampled_result(_EV, Seen.BURN)
        page = self._env().get_template("partials/decision_results.html").render(
            result=result, tree=tree_view(result),
        )
        assert '<section class="decision-tree"' in page

    def test_the_results_render_without_one(self) -> None:
        page = self._env().get_template("partials/decision_results.html").render(result=still_result())
        assert '<section class="decision-tree"' not in page

    def test_the_panel_renders_with_no_context(self) -> None:
        page = self._env().get_template("partials/decision_panel.html").render(pol=None)
        assert 'name="turns"' in page


# ── The job evaluates the tree ──

class TestTheJob:
    async def test_a_job_builds_the_tree(self, owner: Any) -> None:  # noqa: F811
        from spectre.web.decision_job import new_job, start_job
        from tests.unit.test_decision_tree_select import _still

        key, state = owner
        job = new_job(_still(), _MINIMAX)
        start_job(state, key, job)
        await _settled(job)
        assert job.state is JobState.DONE
        assert job.result is not None and job.result.tree is not None
        assert job.result.tree.refusal is None
        assert job.result.tree.complete_turns == 2

    async def test_a_job_that_reads_custody_then_needs_no_run_still_says_why_there_is_no_tree(
        self, owner: Any,  # noqa: F811
    ) -> None:
        from spectre.domain.decision import ScenarioBinding
        from spectre.web.decision_job import CustodyRead, new_job, start_job
        from tests.unit.test_decision_tree_select import _still

        key, state = owner
        scenario = _still()
        assert scenario.binding is not None
        red_only = dataclasses.replace(scenario, binding=ScenarioBinding(red=scenario.binding.red, blue=None))

        async def read(s: Any) -> Any:
            return s

        job = new_job(red_only, _MINIMAX, custody=CustodyRead(read, 1.0, "a test fetch"))
        start_job(state, key, job)
        await _settled(job)
        assert job.state is JobState.DONE
        assert job.result is not None and job.result.tree is not None
        assert job.result.tree.refusal == TREE_UNBOUND


class TestAFailedEvaluation:
    def test_the_page_says_only_that_it_failed(
        self, client: Any, auth_cookie: str, no_job: Any, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Never exception text in the page: the tree's evaluation fails as the matrix's does."""
        from spectre.web.routes import decision as decision_routes

        def fail(*_: Any, **__: Any) -> Any:
            raise RuntimeError("internal detail <b>do not show</b>")

        monkeypatch.setattr(decision_routes, "evaluate_tree", fail)
        resp = _evaluate(client, auth_cookie, _form(turns="2"))
        assert resp.status_code == 200
        assert "Evaluation error: the scenario could not be evaluated; the server log has the detail." in resp.text
        assert "internal detail" not in resp.text
