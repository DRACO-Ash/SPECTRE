"""Collect-first advice says it is not available when a cue's outcome matrix holds a score that is not finite (V0.42
review of SPC-221, evaluation F-32).

cue_relevance picks on the matrix built again under each of a cue's outcomes when the page renders the collect-first
advice. A NonFiniteScoreError raised there escaped to the page as a 500. Now the cue's relevance holds NON_FINITE_SCORE,
the advice keeps the sweep's sentence and says whether that cue could change the recommended response is not
available, with the reason, and no collect-first row is listed for it.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    NON_FINITE_SCORE,
    NonFiniteScoreError,
    SelectorStrategy,
    cue_relevance,
    evaluate_scenario,
)
from tests.unit._band_stand_in import band_moves_a_figure  # noqa: F401 (a fixture, used by name)
from tests.unit.test_decision_figure_basis import _render
from tests.unit.test_decision_relevance import _cue, _held, _understanding

_MINIMAX = SelectorStrategy.MINIMAX


def _refusing(*_args: object, **_kwargs: object) -> object:
    raise NonFiniteScoreError("row 1 (Approach), response F1 (Hold)", math.nan, 0, 0)


@pytest.mark.usefixtures("band_moves_a_figure")
class TestACueWhoseOutcomeMatrixIsNotFinite:
    def test_its_relevance_is_refused_and_changes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = evaluate_scenario(_understanding(_held()), _MINIMAX)
        monkeypatch.setattr(decision, "find_robust_response", _refusing)
        relevance = cue_relevance(result, _cue(0.5), _MINIMAX)
        assert (relevance.benign, relevance.hostile, relevance.refused) == (None, None, NON_FINITE_SCORE)
        assert relevance.changes is False

    def test_the_advice_says_it_is_not_available_and_the_page_renders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A NaN written into each outcome's matrix, as a fault would: the evaluation's own matrix stays finite."""
        result = evaluate_scenario(_understanding(_held()), _MINIMAX)
        built = result.matrix_under

        def faulty(floor: object, ceiling: object) -> list[list[decision.OutcomeMetrics]]:
            matrix = [list(row) for row in built(floor, ceiling)]  # type: ignore[arg-type]
            matrix[0][0] = dataclasses.replace(matrix[0][0], composite_score=math.nan)
            return matrix

        monkeypatch.setattr(result, "matrix_under", faulty)
        advice = result.collection
        assert advice is not None
        assert advice.sentence.endswith(
            f"Whether probe collection could change the recommended response is not available: "
            f"{NON_FINITE_SCORE.removesuffix('.')} (from the sweep's picture assessed 20 min before this evaluation).",
        )
        assert result.collection_rows == ()
        page = " ".join(_render(result).replace("&#39;", "'").split())
        assert "could change the recommended response is not available: Nothing is recommended" in page
