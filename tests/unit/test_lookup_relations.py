"""The lookup model's relations, each an unsourced judgement, and the training-only label (SPC-207, evaluation F-17).

Where nothing is computed or sampled the engine sets a figure by the lookup model's relations: the custody rule, a
sensor retask's custody gap of half its time to execute, a closest approach by red's action type, widened by our
manoeuvre or posture change with its cost, our delta-V of cost times 50 m/s and a closest approach at 0.4 of the
horizon. None has a source. The lead ruled (SPC-207) to register each with its basis and to label any result resting
on one training only, on screen and in the decision record, naming each relation it rests on; the numbers stay.

The label is enforced, not decorative: a result is found to rest on a relation from the bases its own figures carry,
in the matrix and in a game tree's nodes, so no path that sets a lookup figure can leave it unnamed; the results page
fails closed, so a result that cannot say is shown as resting on every relation, never without the label; and the
page is rendered for every pairing of red's action and our response, unbound and bound, and must show the label
exactly when the result rests on a relation.
"""

from __future__ import annotations

import dataclasses
import html
import itertools
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    LOOKUP_BASES,
    LOOKUP_RELATION_WORDS,
    TRAINING_ONLY_MANY,
    TRAINING_ONLY_ONE,
    TRAINING_ONLY_UNKNOWN,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    LookupRelation,
    OutcomeBases,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    lookup_relations,
    outcome_bases,
    training_only_label,
)
from spectre.domain.decision_tree import GameTree
from spectre.domain.provenance import Basis, FigureBasis
from tests.unit._band_stand_in import band_moves_a_figure  # noqa: F401 (a fixture, used by name)
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_custody import _custodied
from tests.unit.test_decision_figure_basis import _render, _text
from tests.unit.test_decision_sampled import _never, _scenario

_M, _R, _P, _N = ActionType.MANOEUVRE, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE, ActionType.NO_ACTION
_CUSTODY, _RETASK, _MISS = LookupRelation.CUSTODY, LookupRelation.RETASK_GAP, LookupRelation.MISS_BY_ACTION
_OURS_M, _OURS_P = LookupRelation.MANOEUVRE_MISS, LookupRelation.POSTURE_MISS
_DV, _TCA = LookupRelation.DELTA_V, LookupRelation.TCA
_TEMPLATE = Path(decision.__file__).parents[1] / "web" / "templates" / "partials" / "decision_results.html"
_COMPUTED = FigureBasis(Basis.COMPUTED, "computed in a test")
#: What each pairing of red's action and our response rests on, unbound, where every figure is a lookup.
_UNBOUND: dict[tuple[ActionType, ActionType], set[LookupRelation]] = {
    (_M, _N): {_CUSTODY, _MISS, _TCA},
    (_M, _R): {_CUSTODY, _RETASK, _MISS, _TCA},
    (_M, _M): {_CUSTODY, _MISS, _OURS_M, _DV, _TCA},
    (_M, _P): {_CUSTODY, _MISS, _OURS_P, _TCA},
    (_R, _R): {_CUSTODY, _MISS, _TCA},
    (_N, _M): {_CUSTODY, _MISS, _OURS_M, _DV, _TCA},
    (_P, _P): {_CUSTODY, _MISS, _OURS_P, _TCA},
    (_N, _N): {_CUSTODY, _MISS, _TCA},
}


def _one(red: ActionType, ours: ActionType) -> ScenarioResult:
    """One unbound row against one response: every figure a lookup."""
    scenario = Scenario(
        name="Relations", epoch_utc=EPOCH,
        adversary_actions=[AdversaryAction("A1", "Red's move", red, 0.5, 0.7)],
        friendly_responses=[FriendlyResponse("F1", "Our move", ours, 0.3, 0.8, 6.0)],
    )
    return evaluate_scenario(scenario)


def _ordered(found: set[LookupRelation]) -> tuple[LookupRelation, ...]:
    return tuple(r for r in LookupRelation if r in found)


def _computed_bases() -> OutcomeBases:
    return outcome_bases(
        custody_maintained=_COMPUTED, custody_gap_hours=_COMPUTED, closest_approach_km=_COMPUTED,
        time_to_closest_hours=_COMPUTED, delta_v_cost_km_s=_COMPUTED,
    )


def _bound(rows: tuple[ActionType, ...], responses: tuple[ActionType, ...]) -> ScenarioResult:
    """The plane-change pair bound on both sides, red's custody held and read, with the rows and responses of
    *rows* and *responses* and no hypothesis: still rows are computed, a manoeuvre row's closest approach is a
    lookup."""
    scenario = _scenario(binding=_custodied())
    keep = dataclasses.replace(
        scenario,
        adversary_actions=[a for a in scenario.adversary_actions if a.action_type in rows],
        friendly_responses=[f for f in scenario.friendly_responses if f.action_type in responses],
    )
    return evaluate_scenario(keep, sampler=_never)


def _all_computed(result: ScenarioResult) -> list[list[object]]:
    """*result*'s matrix with every figure of every cell computed."""
    return [[dataclasses.replace(c, figure_bases=_computed_bases()) for c in row] for row in result.outcome_matrix]


def _page(result: ScenarioResult) -> str:
    return html.unescape(_text(_render(result)))


class TestTheRelations:
    def test_each_relation_says_the_number_the_code_holds(self) -> None:
        words = LOOKUP_RELATION_WORDS
        assert list(words) == list(LookupRelation)
        assert words[_CUSTODY] == (
            "custody is lost when red manoeuvres and our response neither manoeuvres nor retasks a sensor, for the "
            "row's custody gap share of the horizon, and is held otherwise"
        )
        assert words[_RETASK] == "against a manoeuvre, a sensor retask's custody gap is 0.5 of its time to execute"
        assert words[_MISS] == (
            "the closest approach is 200 km against a manoeuvre, 5,000 km against no action, 10,000 km against a "
            "sensor retask and 3,000 km against any other action"
        )
        assert words[_OURS_M] == "our manoeuvre multiplies that closest approach by 1 plus 5 times its cost"
        assert words[_OURS_P] == "our posture change multiplies that closest approach by 1 plus 2 times its cost"
        assert words[_DV] == "our manoeuvre with no sized burn spends its cost times 50 m/s of delta-V"
        assert words[_TCA] == "the closest approach comes at 0.4 of the horizon"

    def test_the_words_follow_the_constants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision, "_RETASK_GAP_SHARE", 0.25)
        assert decision.relation_words()[_RETASK] == (
            "against a manoeuvre, a sensor retask's custody gap is 0.25 of its time to execute"
        )


class TestWhereARelationSetsAFigure:
    @pytest.mark.parametrize(("red", "ours"), list(_UNBOUND))
    def test_an_unbound_result_names_each_relation_its_cell_rests_on(self, red: ActionType, ours: ActionType) -> None:
        assert _one(red, ours).lookup_relations == _ordered(_UNBOUND[(red, ours)])

    def test_a_retask_against_a_manoeuvre_rests_on_its_gap_and_the_gap_is_half_its_time(self) -> None:
        cell = _one(_M, _R).outcome_matrix[0][0]
        assert (cell.custody_maintained, cell.custody_gap_hours) == (True, 3.0)

    def test_a_result_names_the_relations_of_every_cell_once_in_the_registers_order(self) -> None:
        result = evaluate_scenario(_scenario())
        assert result.lookup_relations == tuple(LookupRelation)

    def test_a_cell_with_no_recorded_basis_reads_as_a_lookup(self) -> None:
        cell = SimpleNamespace()
        action = AdversaryAction("A1", "Red", _M, 0.5, 0.7)
        ours = FriendlyResponse("F1", "Ours", _M, 0.3, 0.8, 6.0)
        assert lookup_relations(action, ours, decision._cell_bases(cell)) == frozenset(
            {_CUSTODY, _MISS, _OURS_M, _DV, _TCA},
        )

    def test_a_still_bound_pair_with_custody_read_rests_on_none(self) -> None:
        result = _bound((_N, _R, _P), (_N, _R, _P))
        assert result.lookup_relations == ()
        assert result.training_only is None
        assert all(b.closest_approach_km.kind is Basis.COMPUTED for b in result._bases())

    def test_a_bound_manoeuvre_row_with_no_hypothesis_rests_on_the_lookup_miss_not_the_custody_rule(self) -> None:
        """Its custody is the worst case, a burn at the epoch, a bound taken on purpose, not the custody rule."""
        result = _bound((_M,), (_N, _P))
        assert result.lookup_relations == (_MISS, _OURS_P, _TCA)

    def test_custody_unread_brings_the_custody_rule_into_a_bound_result(self) -> None:
        scenario = _scenario(binding=_custodied(None))
        keep = dataclasses.replace(
            scenario, adversary_actions=[a for a in scenario.adversary_actions if a.action_type is _N],
            friendly_responses=[f for f in scenario.friendly_responses if f.action_type is _N],
        )
        assert evaluate_scenario(keep, sampler=_never).lookup_relations == (_CUSTODY,)

    def test_a_game_trees_nodes_count_where_the_matrix_rests_on_none(self) -> None:
        """A node's own figures are read: a later turn's custody or delta-V can be a lookup the matrix has not."""
        result = _bound((_N,), (_N,))
        computed = _all_computed(result)
        leaf = SimpleNamespace(action=0, response=0, children=(), figures=SimpleNamespace(bases=LOOKUP_BASES))
        root = SimpleNamespace(action=0, response=0, children=(leaf,), figures=SimpleNamespace(bases=_computed_bases()))
        tree = GameTree(2, (), (root,), 2, None, ())  # type: ignore[arg-type]
        assert dataclasses.replace(result, outcome_matrix=computed).lookup_relations == ()
        assert dataclasses.replace(result, outcome_matrix=computed, tree=tree).lookup_relations == (
            _CUSTODY, _MISS, _TCA,
        )

    def test_a_hand_built_node_with_no_figures_reads_as_a_lookup(self) -> None:
        result = _bound((_N,), (_N,))
        computed = _all_computed(result)
        bare = SimpleNamespace(action=0, response=0, children=())
        tree = GameTree(1, (), (bare,), 1, None, ())  # type: ignore[arg-type]
        assert dataclasses.replace(result, outcome_matrix=computed, tree=tree).lookup_relations == (
            _CUSTODY, _MISS, _TCA,
        )


class TestTheLabel:
    def test_one_relation_is_named_alone(self) -> None:
        assert training_only_label((_TCA,)) == (
            "Training only. This result rests on an unsourced relation of the lookup model, a judgement with no "
            "source behind it (docs/lookup-register.md, SPC-207), so use it to train, not to decide: the time to "
            "closest approach, that the closest approach comes at 0.4 of the horizon."
        )
        assert TRAINING_ONLY_ONE.startswith("Training only. ")

    def test_several_are_each_named_in_the_registers_order(self) -> None:
        label = training_only_label((_RETASK, _DV))
        assert label == (
            "Training only. This result rests on unsourced relations of the lookup model, judgements with no source "
            "behind them (docs/lookup-register.md, SPC-207), so use it to train, not to decide: the sensor-retask "
            "gap, that against a manoeuvre, a sensor retask's custody gap is 0.5 of its time to execute; the delta-V "
            "per cost, that our manoeuvre with no sized burn spends its cost times 50 m/s of delta-V."
        )
        assert TRAINING_ONLY_MANY.startswith("Training only. ")

    def test_none_gives_no_label(self) -> None:
        assert training_only_label(()) is None

    def test_a_result_carries_its_own(self) -> None:
        result = _one(_M, _R)
        assert result.training_only == training_only_label(result.lookup_relations)
        for relation in result.lookup_relations:
            assert LOOKUP_RELATION_WORDS[relation] in str(result.training_only)


#: Every pairing of red's action and our response, one row and one response each, unbound.
_PAIRINGS = list(itertools.product(ActionType, ActionType))


class TestThePageShowsItExactlyWhenTheResultRestsOnARelation:
    @pytest.mark.parametrize(("red", "ours"), _PAIRINGS)
    def test_every_unbound_pairing_is_labelled_naming_each_relation(self, red: ActionType, ours: ActionType) -> None:
        result = _one(red, ours)
        page = _page(result)
        assert result.lookup_relations
        assert str(result.training_only) in page
        for relation in result.lookup_relations:
            assert LOOKUP_RELATION_WORDS[relation] in page

    @pytest.mark.parametrize(("rows", "responses"), [((_N, _R, _P), (_N, _R, _P)), ((_M,), (_N, _P)), ((_N,), (_N,))])
    def test_a_bound_result_is_labelled_only_when_it_rests_on_one(
        self, rows: tuple[ActionType, ...], responses: tuple[ActionType, ...],
    ) -> None:
        result = _bound(rows, responses)
        page = _page(result)
        assert ("Training only." in page) is bool(result.lookup_relations)

    def test_the_label_sits_above_the_recommendation(self) -> None:
        markup = _render(_one(_M, _M))
        assert 0 < markup.index('class="training-only"') < markup.index('class="headline-pick"')
        tag = re.search(r'<p class="training-only"[^>]*>', markup)
        assert tag is not None and 'role="note"' in tag.group(0)

    def test_a_result_that_cannot_say_is_shown_as_resting_on_every_relation(self) -> None:
        class Silent(ScenarioResult):
            training_only = property(lambda self: self._missing)  # type: ignore[assignment]

            def __getattr__(self, name: str) -> object:
                raise AttributeError(name)

        result = _one(_M, _N)
        silent = Silent(**{f.name: getattr(result, f.name) for f in dataclasses.fields(result) if f.init})
        markup = _render(silent)
        assert TRAINING_ONLY_UNKNOWN in html.unescape(markup)
        assert 0 < markup.index('class="training-only"') < markup.index('class="headline-pick"')

    def test_the_pages_fallback_is_the_engines_own_words(self) -> None:
        """The template cannot import the constant, so it holds the words; they must be the engine's, exactly."""
        assert TRAINING_ONLY_UNKNOWN in _TEMPLATE.read_text(encoding="utf-8")
        assert TRAINING_ONLY_UNKNOWN.startswith("Training only. ")


class TestNoRecommendationIsShownAheadOfTheLabel:
    """The label comes before anything on the page that names a response: the collect-first advice, which names the
    engine's pick under each outcome of a cue, the headline and every rule's pick (SPC-207, the review of 0.39)."""

    @pytest.mark.usefixtures("band_moves_a_figure")
    @pytest.mark.parametrize("rule", list(SelectorStrategy), ids=[r.value for r in SelectorStrategy])
    def test_the_collect_first_advice_comes_after_it(self, rule: SelectorStrategy) -> None:
        from tests.unit.test_decision_relevance import _held, _understanding

        result = evaluate_scenario(_understanding(_held()), rule)
        assert result.training_only is not None
        markup = _render_with_rules(result)
        label = markup.index('class="training-only"')
        assert "the engine recommends" in markup[markup.index('class="collection-advice"'):]
        assert label < markup.index('class="collection-advice"')
        assert label < markup.index('class="headline-pick"')

    @pytest.mark.parametrize(("red", "ours"), [(_M, _M), (_M, _R), (_N, _P)])
    def test_no_response_is_named_before_it(self, red: ActionType, ours: ActionType) -> None:
        result = _one(red, ours)
        markup = _render_with_rules(result)
        label = markup.index('class="training-only"')
        for response in result.scenario.friendly_responses:
            assert markup.find(response.name) > label, response.name


def _render_with_rules(result: ScenarioResult) -> str:
    """The results as the route renders them, with every rule's pick beside the primary rule's."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    from spectre.domain.rule_comparison import compare_rules
    from spectre.web.app import templates

    env = Environment(loader=FileSystemLoader(str(_TEMPLATE.parents[1])), autoescape=True, undefined=StrictUndefined)
    env.filters.update(templates.env.filters)
    rules = compare_rules(result, SelectorStrategy.MINIMAX)
    return env.get_template("partials/decision_results.html").render(result=result, rules=rules)
