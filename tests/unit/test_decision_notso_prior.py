"""An adversary row records whether its P and Conf are the operator's own or an accepted NOTSO suggestion (SPC-130).

Concept section 7.5: probability and confidence are never filled in on the
operator's behalf. A NOTSO prior is offered beside the row, and the operator
applies it or ignores it. When applied, the row carries the suggestion it
accepted, which must be the values the row holds; the result says, row by row,
whose values they are and what an accepted one rests on; and the scenario's
provenance tells the two apart at the same values. An accepted suggestion is
not an untouched default, whatever its value. No test reads the wall clock.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.notso import NOTSOType
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.domain.notso_prior import NotsoPrior
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _prior(probability: float = 0.13, confidence: float | None = 0.3) -> NotsoPrior:
    return NotsoPrior(
        red="RX", action_type=ActionType.MANOEUVRE, probability=probability, confidence=confidence, events=5,
        notices=6, span_start=_NOW - timedelta(days=100), span_end=_NOW, covered_days=100.0, gaps=0,
        horizon_hours=72.0,
        mapped=(NOTSOType.MANOEUVRE, NOTSOType.PROXIMITY_OPS), confidence_line="Conf line.",
    )


def _row(probability: float = 0.13, confidence: float = 0.3, prior: NotsoPrior | None = None,
         action: ActionType = ActionType.MANOEUVRE) -> AdversaryAction:
    return AdversaryAction(id="A1", name="Approach", action_type=action, probability=probability,
                           confidence=confidence, accepted_prior=prior)


def _scenario(*rows: AdversaryAction) -> Scenario:
    return Scenario(
        name="Prior", epoch_utc=_NOW, adversary_actions=list(rows),
        friendly_responses=[FriendlyResponse(id="F1", name="Hold", action_type=ActionType.NO_ACTION, cost=0.1,
                                             reversibility=1.0, time_to_execute_hours=1.0)],
    )


class TestTheRowCarriesWhatItAccepted:
    def test_a_row_is_its_operators_own_by_default(self) -> None:
        assert _row().accepted_prior is None

    def test_an_accepted_prior_must_be_the_probability_the_row_holds(self) -> None:
        with pytest.raises(ValueError, match="probability"):
            _row(probability=0.5, prior=_prior())

    def test_an_accepted_prior_must_be_the_confidence_the_row_holds_when_it_offers_one(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            _row(confidence=0.7, prior=_prior())

    def test_a_prior_offering_no_confidence_leaves_the_operators_own(self) -> None:
        assert _row(confidence=0.7, prior=_prior(confidence=None)).confidence == 0.7

    def test_an_accepted_prior_must_be_for_the_rows_action_type(self) -> None:
        with pytest.raises(ValueError, match="action type"):
            _row(prior=_prior(), action=ActionType.NO_ACTION)

    def test_only_a_notso_prior_is_accepted(self) -> None:
        with pytest.raises(TypeError, match="NotsoPrior"):
            _row(prior="0.13")  # type: ignore[arg-type]


class TestTheResultSaysWhoseValuesTheyAre:
    def test_own_values_say_so(self) -> None:
        assert evaluate_scenario(_scenario(_row(0.3, 0.6))).row_sources == ("P and Conf are your own.",)

    def test_an_accepted_suggestion_says_so_with_its_basis(self) -> None:
        prior = _prior()
        (line,) = evaluate_scenario(_scenario(_row(prior=prior))).row_sources
        assert line == f"P 0.13 and Conf 0.30 are the NOTSO suggestion you applied. {prior.basis_line} Conf line."

    def test_an_accepted_suggestion_with_no_confidence_keeps_the_operators_conf(self) -> None:
        prior = _prior(confidence=None)
        (line,) = evaluate_scenario(_scenario(_row(confidence=0.7, prior=prior))).row_sources
        assert line.startswith("P 0.13 is the NOTSO suggestion you applied; Conf is your own.")

    def test_no_source_line_breaks_i13(self) -> None:
        result = evaluate_scenario(_scenario(_row(prior=_prior()), dataclasses.replace(_row(0.3, 0.6), id="A2")))
        assert [s for s in result.row_sources if i13_problems(s)] == []


class TestTheEvaluationRecordsIt:
    def test_the_provenance_tells_an_accepted_suggestion_from_the_same_values_typed(self) -> None:
        own = evaluate_scenario(_scenario(_row())).provenance
        accepted = evaluate_scenario(_scenario(_row(prior=_prior()))).provenance
        assert own is not None
        assert accepted is not None
        assert own.inputs[0].sha256 != accepted.inputs[0].sha256

    def test_the_provenance_names_an_accepted_suggestion_as_a_lookup_dated_at_the_end_of_its_span(self) -> None:
        own = evaluate_scenario(_scenario(_row())).provenance
        accepted = evaluate_scenario(_scenario(_row(prior=_prior()))).provenance
        assert own is not None
        assert accepted is not None
        assert [i for i in own.inputs if i.label.startswith("NOTSO")] == []
        (named,) = [i for i in accepted.inputs if i.label.startswith("NOTSO")]
        assert (named.label, named.epoch) == ("NOTSO suggestion applied to A1 (lookup)", _NOW)

    def test_an_accepted_suggestion_at_the_default_is_not_an_untouched_probability(self) -> None:
        row = _row(0.5, 0.3, prior=_prior(probability=0.5))
        assert evaluate_scenario(_scenario(row), SelectorStrategy.EXPECTED_VALUE).objective_guidance is None

    def test_a_typed_default_is_still_untouched(self) -> None:
        guidance = evaluate_scenario(_scenario(_row(0.5, 0.3)), SelectorStrategy.EXPECTED_VALUE).objective_guidance
        assert (guidance or "").startswith("Expected value rests on a probability the evidence has not earned.")
