"""The update after turn 1 for what the operator states turn 1 showed, and the plan the picks follow (SPC-142).

Under expected value the result shows the likelihood model and then the update for the observation the operator
stated, and only that one. With none stated it says so and that nothing was updated; an observation no row gives
under the model updates nothing and says so; minimax and minimin read no probability, so a stated observation
updates nothing under them either. The recommendation's lines come before the update's, and a node is marked on
the plan when every response on its sequence is the rule's pick, given what the turns before it showed.
"""

from __future__ import annotations

import dataclasses

import pytest

from spectre.domain.decision import ProbabilityRule, Scenario, Seen
from spectre.domain.tree_selectors import (
    NO_OBSERVATION,
    OBSERVED,
    OBSERVED_NO_LATER_TURN,
    OBSERVED_NO_PICK,
    OBSERVED_NOT_GIVEN,
    OBSERVED_UNUSED,
    PROBABILITY_IGNORED,
    SENTENCES,
    follows_picks,
    select,
)
from spectre.domain.turn_update import INDEPENDENT_TURNS, POSTERIOR_ONE_ROW, SEEN_MODEL
from spectre.domain.turn_update import SENTENCES as MODEL_SENTENCES
from spectre.domain.turn_update import Seen as SeenFromTheModel
from tests.unit._i13 import i13_problems
from tests.unit.test_tree_selectors import _EV, _MINIMAX, _MINIMIN, _scenario, _tree, _two_turn_score


def _stated(seen: Seen | None, **kwargs: object) -> Scenario:
    return dataclasses.replace(_scenario(**kwargs), observed=seen)  # type: ignore[arg-type]


class TestTheScenarioCarriesIt:
    def test_none_is_the_default(self) -> None:
        assert _scenario().observed is None

    def test_it_is_the_likelihood_models_own_words(self) -> None:
        assert Seen is SeenFromTheModel
        assert _stated(Seen.BURN).observed is Seen.BURN

    @pytest.mark.parametrize("bad", ["a burn", 1, True])
    def test_anything_else_is_refused(self, bad: object) -> None:
        with pytest.raises(ValueError, match="observed"):
            _stated(bad)  # type: ignore[arg-type]


class TestExpectedValue:
    def test_with_none_stated_nothing_is_updated_and_it_says_so(self) -> None:
        selection = select(_stated(None), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        model, independent, said = selection.update
        assert "likelihood model" in model
        assert "nothing sourced" in independent
        assert said == NO_OBSERVATION
        assert selection.stated is None
        assert not any("of the weight" in line or line.startswith("If turn 1 shows") for line in selection.lines)

    def test_a_stated_burn_shows_its_update_alone(self) -> None:
        """Hold course gives no burn and Evasive a burn, so a burn puts all the weight on Evasive."""
        selection = select(_stated(Seen.BURN), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        burn, quiet = selection.posteriors
        model, independent, said, update = selection.update
        assert said == OBSERVED.format(seen="a burn")
        assert update == burn.line
        assert selection.stated == burn
        assert quiet.line not in selection.lines
        assert "likelihood model" in model and "nothing sourced" in independent

    def test_a_stated_no_burn_shows_its_own_update_not_the_burns(self) -> None:
        """Burn comes first among the updates, so only a stated no burn shows which one the operator's picks."""
        selection = select(_stated(Seen.NO_BURN), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        burn, quiet = selection.posteriors
        *_, said, update = selection.update
        assert said == OBSERVED.format(seen="no burn")
        assert update == quiet.line
        assert update.startswith("If turn 1 shows no burn:")
        assert selection.stated == quiet
        assert burn.line not in selection.lines

    def test_a_one_row_update_says_it_is_the_models_assumption_not_more_evidence(self) -> None:
        """All the weight on one row reads stronger than the likelihood model earns, so the line says so."""
        assert POSTERIOR_ONE_ROW.endswith("That is the likelihood model's assumption, not evidence of more.")
        selection = select(_stated(Seen.BURN), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        assert selection.update[-1].endswith(
            "so the update puts all the weight there. That is the likelihood model's assumption, not evidence of more.",
        )

    def test_an_observation_no_row_gives_updates_nothing(self) -> None:
        """With custody read and held, turn 1 shows a burn or no burn, never nothing."""
        selection = select(_stated(Seen.NOTHING), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        assert selection.update[-1] == OBSERVED_NOT_GIVEN.format(seen="nothing")
        assert selection.stated is None

    def test_a_tree_built_to_turn_one_alone_says_the_observation_updated_nothing(self) -> None:
        roots = tuple(dataclasses.replace(r, children=()) for r in _tree(2, 2, 2, _two_turn_score))
        selection = select(_stated(Seen.BURN), roots, 1, _EV, matrix_pick=0)
        assert selection.update == (OBSERVED_NO_LATER_TURN.format(seen="a burn"),)
        assert selection.stated is None

    def test_one_turn_built_with_none_stated_shows_no_update(self) -> None:
        roots = tuple(dataclasses.replace(r, children=()) for r in _tree(2, 2, 2, _two_turn_score))
        assert select(_stated(None), roots, 1, _EV, matrix_pick=0).update == ()


class TestRulesThatReadNoProbability:
    @pytest.mark.parametrize(("strategy", "rule"), [(_MINIMAX, "Minimax"), (_MINIMIN, "Minimin")])
    def test_a_stated_observation_updates_nothing(self, strategy: object, rule: str) -> None:
        selection = select(_stated(Seen.BURN), _tree(2, 2, 2, _two_turn_score), 2, strategy, matrix_pick=0)  # type: ignore[arg-type]
        *_, ignored, unused = selection.update
        assert ignored == PROBABILITY_IGNORED.format(rule=rule)
        assert unused == OBSERVED_UNUSED.format(seen="a burn", rule=rule)
        assert selection.stated is None

    def test_none_stated_adds_nothing(self) -> None:
        selection = select(_stated(None), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)
        assert selection.update[-1] == PROBABILITY_IGNORED.format(rule="Minimax")

    @pytest.mark.parametrize("strategy", [_MINIMAX, _MINIMIN])
    @pytest.mark.parametrize("seen", [None, Seen.BURN])
    def test_they_show_what_each_turn_lets_us_see_and_no_update_or_weight(
        self, strategy: object, seen: Seen | None,
    ) -> None:
        """The likelihood model sets what each later pick may see, but no update is made and no P weighs red."""
        selection = select(_stated(seen), _tree(2, 2, 2, _two_turn_score), 2, strategy, matrix_pick=0)  # type: ignore[arg-type]
        assert selection.update[0] == SEEN_MODEL.format(
            rows="row 1, Hold course, gives no burn; row 2, Evasive, gives a burn",
        )
        assert INDEPENDENT_TURNS not in selection.update
        for line in selection.update:
            assert "weighed by" not in line and "rows' P" not in line, line
            assert not line.startswith("The update after turn 1 rests"), line


class TestATreeWithNoPick:
    def test_a_stated_observation_is_said_to_update_nothing(self) -> None:
        assert OBSERVED_NO_PICK.format(seen="a burn") == (
            "You stated that turn 1 shows a burn, but the tree gives no pick, so nothing was updated."
        )


class TestTheLinesInTwoParts:
    def test_the_recommendation_comes_before_the_update(self) -> None:
        selection = select(_stated(Seen.BURN), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        assert selection.lines == (*selection.recommendation, *selection.update)
        assert selection.recommendation[0].startswith("Expected value over the 2 turns")
        assert not any("likelihood model" in line for line in selection.recommendation)


class TestThePlan:
    def test_a_node_is_on_the_plan_when_each_response_is_the_pick_for_what_was_seen(self) -> None:
        """Minimax: Hold in turn 1; then Avoid after no burn (Hold course) and Hold after a burn (Evasive)."""
        scenario = _scenario()
        selection = select(scenario, _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)
        assert follows_picks(scenario, selection, [(0, 0)])
        assert follows_picks(scenario, selection, [(1, 0)])
        assert not follows_picks(scenario, selection, [(0, 1)])
        assert follows_picks(scenario, selection, [(0, 0), (1, 1)])
        assert not follows_picks(scenario, selection, [(0, 0), (1, 0)])
        assert follows_picks(scenario, selection, [(1, 0), (0, 0)])
        assert not follows_picks(scenario, selection, [(1, 0), (0, 1)])
        assert not follows_picks(scenario, selection, [(0, 1), (0, 1)])

    def test_nothing_is_on_the_plan_where_there_is_no_pick(self) -> None:
        """Every row at P 0 under the rule a record 0.28.0 or 0.29.0 wrote is replayed by (SPC-203)."""
        scenario = dataclasses.replace(_scenario(p=(0.0, 0.0)), probability_rule=ProbabilityRule.SHARES)
        selection = select(scenario, _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        assert not any(follows_picks(scenario, selection, [(a, r)]) for a in range(2) for r in range(2))


@pytest.mark.parametrize(
    "sentence",
    (NO_OBSERVATION, OBSERVED, OBSERVED_NOT_GIVEN, OBSERVED_NO_LATER_TURN, OBSERVED_UNUSED, OBSERVED_NO_PICK, SEEN_MODEL),
)
def test_each_new_sentence_is_listed_and_passes_the_house_checks(sentence: str) -> None:
    assert sentence in (*SENTENCES, *MODEL_SENTENCES)
    assert i13_problems(sentence) == []
    for bad in ("—", "–", "--", "%"):
        assert bad not in sentence
