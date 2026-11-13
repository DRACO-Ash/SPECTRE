"""A composite score that is not finite is refused before any rule picks on it (SPC-221, evaluation F-32).

Probe P-14 injected a NaN lookup: every score of that row read NaN, the matrix printed "nan", and the pick followed
the row order, since NaN compares false with everything, so min() keeps whatever it saw first. The closing evidence
is a test with an injected NaN. Here the injection is a NaN and an infinite lookup closest approach, and NaN and
infinite scores written into a matrix and into a game tree's leaves, under each of minimax, expected value and
minimin, over the matrix and over the tree: each is refused with NonFiniteScoreError, which names the cell, and the
operator is shown NON_FINITE_SCORE, a fixed sentence, never the exception's text.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    NON_FINITE_SCORE,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    NonFiniteScoreError,
    OutcomeMetrics,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
    rule_values,
    tied_responses,
)
from spectre.domain.tree_selectors import select
from tests.unit.test_tree_selectors import _scenario as _tree_scenario
from tests.unit.test_tree_selectors import _tree, _two_turn_score

_RULES = (SelectorStrategy.MINIMAX, SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMIN)
_BAD = (math.nan, math.inf, -math.inf)


def _scenario() -> Scenario:
    rows = [
        AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.6, 0.7),
        AdversaryAction("A2", "Hold course", ActionType.NO_ACTION, 0.4, 0.7),
    ]
    responses = [
        FriendlyResponse("F1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 1.0),
        FriendlyResponse("F2", "Avoid", ActionType.MANOEUVRE, 0.3, 0.8, 6.0),
    ]
    return Scenario(name="F-32", epoch_utc=datetime(2026, 11, 5, tzinfo=UTC), adversary_actions=rows,
                    friendly_responses=responses)


def _with_score(matrix: list[list[OutcomeMetrics]], i: int, j: int, score: float) -> list[list[OutcomeMetrics]]:
    changed = [list(row) for row in matrix]
    changed[i][j] = dataclasses.replace(changed[i][j], composite_score=score)
    return changed


class TestTheMatrix:
    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    @pytest.mark.parametrize("bad", _BAD, ids=["nan", "inf", "-inf"])
    def test_each_rule_refuses_a_score_that_is_not_finite(self, rule: SelectorStrategy, bad: float) -> None:
        result = evaluate_scenario(_scenario(), rule)
        matrix = _with_score(result.outcome_matrix, 0, 1, bad)
        with pytest.raises(NonFiniteScoreError) as refused:
            find_robust_response(result.scenario, matrix, rule)
        assert str(refused.value) == (
            f"row 1 (Approach), response F2 (Avoid) scores {bad!r}: {NON_FINITE_SCORE}"
        )
        assert (refused.value.row, refused.value.response) == (0, 1)

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_the_values_and_the_ties_refuse_it_too(self, rule: SelectorStrategy) -> None:
        result = evaluate_scenario(_scenario(), rule)
        matrix = _with_score(result.outcome_matrix, 1, 0, math.nan)
        with pytest.raises(NonFiniteScoreError):
            rule_values(result.scenario, matrix, rule)
        with pytest.raises(NonFiniteScoreError):
            tied_responses(result.scenario, matrix, rule)

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_a_score_not_finite_under_a_response_not_permitted_is_refused_too(self, rule: SelectorStrategy) -> None:
        """A cell no rule weighs still says the engine went wrong, so it is not passed over unsaid."""
        scenario = _scenario()
        vetoed = dataclasses.replace(scenario.friendly_responses[1], vetoed=True, veto_reason="ROE 4.")
        scenario = dataclasses.replace(scenario, friendly_responses=[scenario.friendly_responses[0], vetoed])
        result = evaluate_scenario(scenario, rule)
        with pytest.raises(NonFiniteScoreError):
            find_robust_response(result.scenario, _with_score(result.outcome_matrix, 0, 1, math.nan), rule)

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_finite_scores_pick_as_before(self, rule: SelectorStrategy) -> None:
        result = evaluate_scenario(_scenario(), rule)
        pick = find_robust_response(result.scenario, result.outcome_matrix, rule)
        assert pick is not None and pick.id == result.robust_best_response.id  # type: ignore[union-attr]


class TestAnInjectedLookup:
    """P-14's fault: the lookup closest approach for a manoeuvre row made NaN by a code fault. An infinite one is
    not a score that is not finite: the closest-approach term saturates at 1 inside the keep-out distance and 0 at
    50,000 km, so its score is finite, and the matrix tests above cover an infinite score itself."""

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_the_evaluation_refuses_it_under_every_rule(
        self, rule: SelectorStrategy, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(decision._BASE_CA_KM, ActionType.MANOEUVRE, math.nan)
        with pytest.raises(NonFiniteScoreError) as refused:
            evaluate_scenario(_scenario(), rule)
        assert (refused.value.row, refused.value.response) == (0, 0)
        assert str(refused.value) == f"row 1 (Approach), response F1 (Hold) scores nan: {NON_FINITE_SCORE}"

    @pytest.mark.parametrize("bad", [math.inf, -math.inf], ids=["inf", "-inf"])
    def test_an_infinite_lookup_saturates_to_a_finite_score(self, bad: float, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(decision._BASE_CA_KM, ActionType.MANOEUVRE, bad)
        result = evaluate_scenario(_scenario())
        assert all(math.isfinite(cell.composite_score) for row in result.outcome_matrix for cell in row)


class TestTheTree:
    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    @pytest.mark.parametrize("bad", _BAD, ids=["nan", "inf", "-inf"])
    def test_each_rule_refuses_a_leaf_that_is_not_finite(self, rule: SelectorStrategy, bad: float) -> None:
        def score(path: Any) -> float:
            return bad if path == ((1, 0), (0, 1)) else _two_turn_score(path)

        with pytest.raises(NonFiniteScoreError) as refused:
            select(_tree_scenario(), _tree(2, 2, 2, score), 2, rule, matrix_pick=0)
        assert str(refused.value) == (
            f"the sequence turn 1 row 2 and response 1, then turn 2 row 1 and response 2 scores {bad!r}: "
            f"{NON_FINITE_SCORE}"
        )

    @pytest.mark.parametrize("rule", _RULES, ids=[r.value for r in _RULES])
    def test_a_finite_tree_still_picks(self, rule: SelectorStrategy) -> None:
        selection = select(_tree_scenario(), _tree(2, 2, 2, _two_turn_score), 2, rule, matrix_pick=0)
        assert selection.picks[0].pick in (0, 1)

