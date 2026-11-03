"""The custody gap is not the adversary row's intelligence confidence (SPC-161).

The rule of thumb lost custody for the horizon x the row's confidence when the
adversary manoeuvred and our response neither manoeuvred nor retasked a
sensor, so raising how sure the intelligence is lengthened our own custody
gap: how sure we are of the action was read as how long we lose the object.
The gap's share of the horizon is now the row's own field,
custody_gap_fraction, defaulting to 0.7, the confidence the page posted by
default, so a page left at its defaults scores as it did. Confidence moves no
figure and no ranking. Probability stays the operator's likelihood, the only
weight the expected-value selector reads. With a red track bound and its
status read, custody is the red track's (SPC-123), and neither field moves it.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    LOOKUP_BASES,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    SelectorStrategy,
    compute_outcome_metrics,
    evaluate_scenario,
    find_robust_response,
)
from tests.unit.test_decision_custody import _burn_at_quarter_hour, _custodied
from tests.unit.test_decision_figure_basis import _render, _text
from tests.unit.test_decision_sampled import _Fake, _scenario

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_HOLD = FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0)
_RETASK = FriendlyResponse("R2", "Retask", ActionType.SENSOR_RETASK, 0.1, 0.9, 6.0)


def _approach(confidence: float = 0.7, **fields: float) -> AdversaryAction:
    return AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.5, confidence, **fields)  # type: ignore[arg-type]


def _unanswered(action: AdversaryAction) -> decision.OutcomeMetrics:
    """The row against doing nothing, over 72 h: the cell where the rule of thumb loses custody."""
    scenario = Scenario("gap", _EPOCH, [action], [_HOLD], horizon_hours=72.0)
    return compute_outcome_metrics(action, _HOLD, scenario)


class TestTheRuleOfThumb:
    def test_raising_intelligence_confidence_no_longer_lengthens_the_gap(self) -> None:
        unsure, sure = _unanswered(_approach(0.1)), _unanswered(_approach(0.9))
        assert not unsure.custody_maintained and not sure.custody_maintained
        assert sure.custody_gap_hours == unsure.custody_gap_hours
        assert sure.composite_score == unsure.composite_score

    def test_the_gap_is_the_rows_own_share_of_the_horizon(self) -> None:
        assert _unanswered(_approach(custody_gap_fraction=0.25)).custody_gap_hours == pytest.approx(18.0)
        assert _unanswered(_approach(custody_gap_fraction=1.0)).custody_gap_hours == pytest.approx(72.0)

    def test_at_the_default_a_page_left_alone_scores_as_it_did(self) -> None:
        """The page posted confidence 0.7 by default, so its gap was 0.7 of the horizon; the default share is 0.7."""
        assert decision.DEFAULT_CUSTODY_GAP_FRACTION == 0.7
        assert _approach().custody_gap_fraction == 0.7
        cell = _unanswered(_approach())
        assert cell.custody_gap_hours == pytest.approx(72.0 * 0.7)
        assert cell.composite_score == pytest.approx(0.35 * 0.7 + 0.25 * (1.0 - 200.0 / 50_000.0))

    @pytest.mark.parametrize("share", [-0.1, 1.1, math.nan])
    def test_the_share_is_a_fraction(self, share: float) -> None:
        with pytest.raises(ValueError, match="custody_gap_fraction"):
            _approach(custody_gap_fraction=share)

    def test_the_gap_note_names_the_share_and_not_confidence(self) -> None:
        note = LOOKUP_BASES.custody_gap_hours.note
        assert "x adversary confidence" not in note
        assert "the horizon x the row's custody gap share, not its intelligence confidence" in note


class TestABoundRedTrack:
    def test_neither_field_moves_its_custody(self) -> None:
        """SPC-123's path already overrode the rule-of-thumb gap; the row's share does not reach it either."""
        scenario = _burn_at_quarter_hour(_scenario(binding=_custodied()))

        def evaluated(confidence: float, share: float) -> list[list[decision.OutcomeMetrics]]:
            rows = [
                dataclasses.replace(a, confidence=confidence, custody_gap_fraction=share)
                for a in scenario.adversary_actions
            ]
            return evaluate_scenario(dataclasses.replace(scenario, adversary_actions=rows), sampler=_Fake()).outcome_matrix

        assert evaluated(0.1, 0.1) == evaluated(0.9, 0.9)


class TestTheSelector:
    @staticmethod
    def _pick(confidence: float, p_manoeuvre: float = 0.5) -> str:
        rows = [
            AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, p_manoeuvre, confidence),
            AdversaryAction("A2", "Hold", ActionType.NO_ACTION, 1.0 - p_manoeuvre, confidence),
        ]
        scenario = Scenario("ev", _EPOCH, rows, [_HOLD, _RETASK], horizon_hours=72.0)
        matrix = [[compute_outcome_metrics(a, r, scenario) for r in (_HOLD, _RETASK)] for a in rows]
        return find_robust_response(scenario, matrix, SelectorStrategy.EXPECTED_VALUE).id

    def test_expected_value_weights_by_probability_and_not_by_confidence(self) -> None:
        """Confidence reached the selector through the gap: at 0.1 it picked Hold, at 0.9 the retask."""
        assert self._pick(0.1) == self._pick(0.9) == "R2"
        assert self._pick(0.7, p_manoeuvre=0.05) == "R1", "probability still weights each row"


class TestThePage:
    def test_a_rule_of_thumb_manoeuvre_row_shows_its_gap_share_and_no_other_row_does(self) -> None:
        """The share is shown where it sets the gap: a manoeuvre row whose custody is the rule of thumb."""
        rows = [
            AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.6, 0.8, custody_gap_fraction=0.4),
            AdversaryAction("A2", "Hold", ActionType.NO_ACTION, 0.4, 0.3, custody_gap_fraction=0.9),
        ]
        scenario = Scenario("page", _EPOCH, rows, [_HOLD], horizon_hours=72.0)
        text = _text(_render(evaluate_scenario(scenario)))
        assert "P=0.6 · Conf=0.8 · Gap=0.4" in text
        assert "P=0.4 · Conf=0.3" in text and "Gap=0.9" not in text
        bound = _burn_at_quarter_hour(_scenario(binding=_custodied()))
        assert "Gap=" not in _render(evaluate_scenario(bound, sampler=_Fake())), "the red track's custody sets it"


class TestTheWrittenDescriptions:
    """The operator guide and the README describe the three fields as the panel does."""

    _ROOT = Path(__file__).resolve().parents[2]

    def _read(self, relative: str) -> str:
        path = self._ROOT / relative
        if not path.exists():
            pytest.skip(f"{relative} not present in this checkout")
        return " ".join(path.read_text(encoding="utf-8").split())

    def test_the_guide_does_not_say_confidence_weights_the_selector(self) -> None:
        guide = self._read("docs/generate_guide.py")
        assert "reduced weighting" not in guide
        assert "moves no figure" in guide
        assert '"Custody gap share"' in guide

    def test_the_readme_lists_the_gap_share_on_each_adversary_row(self) -> None:
        readme = self._read("README.md")
        assert "adversary action rows (type, probability, confidence, custody gap share)" in readme
