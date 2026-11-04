"""Lookup constants retire wherever a computed or sampled figure exists (SPC-125).

The Phase 1 lookups are the per-type closest approaches (200, 3,000, 5,000 or
10,000 km), time to closest approach at 0.4 of the horizon, the rule-of-thumb
custody and our delta-V at response cost x 0.05 km/s. In a bound scenario a
cell's closest approach and its time are computed or sampled, custody is the
bound red track's once read, and our delta-V is computed for a sized burn; a
response that does not burn spends nothing, against the same no-burn blue
orbit the cell was computed or sampled on, so its 0 m/s is that computation's
and no longer reads the cost x 0.05 rule. The lookups stay for an unbound
scenario, and wherever no computed or sampled figure exists (a manoeuvre that
names no burn, a refused row, a manoeuvre response with no target), labelled
as lookups. The lookup model's public entry refuses a bound scenario, so no
consumer can take its figures for the bound scenario's.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest

from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import (
    LOOKUP_BASES,
    ActionType,
    FriendlyResponse,
    OutcomeMetrics,
    Scenario,
    ScenarioResult,
    compute_outcome_metrics,
    evaluate_scenario,
)
from spectre.domain.decision_figures import ResponseBurnSpec
from spectre.domain.provenance import Basis
from tests.unit.test_decision_response import _avoid, _computed_scenario, _hold
from tests.unit.test_decision_sampled import _binding, _evasive, _Fake, _never, _scenario

#: Words only a lookup's note carries: each names one Phase 1 constant.
_LOOKUP_WORDS = ("per adversary action type", "0.4 of the horizon", "rule of thumb", "response cost x 0.05")
_EARNED = frozenset({Basis.COMPUTED, Basis.SAMPLED})
_HELD = CustodyStatus(Custody.HELD, "Custody held.")


def _read(scenario: Scenario) -> Scenario:
    """*scenario* with its bound red track's custody read, as the route always reads it."""
    binding = scenario.binding
    assert binding is not None and binding.red is not None
    return dataclasses.replace(scenario, binding=dataclasses.replace(
        binding, red=dataclasses.replace(binding.red, custody=_HELD)))


def _bound_results() -> Iterator[tuple[str, ScenarioResult]]:
    """Bound scenarios with every kind of earned figure: computed rows, a sampled row, and a sized burn."""
    yield "computed", evaluate_scenario(_read(_scenario(binding=_binding())), sampler=_never)
    yield "sampled", evaluate_scenario(_read(_scenario({0: _evasive()}, binding=_binding())), sampler=_Fake())
    yield "burn", evaluate_scenario(_read(_computed_scenario(_hold(), _avoid(ResponseBurnSpec(20.0)))))


_RESULTS = dict(_bound_results())


def _cells(result: ScenarioResult) -> Iterator[tuple[OutcomeMetrics, FriendlyResponse]]:
    for row in result.outcome_matrix:
        yield from zip(row, result.scenario.friendly_responses, strict=True)


@pytest.mark.parametrize("name", list(_RESULTS))
class TestNoBoundFigureReadsALookupWhereAnEarnedOneExists:
    def test_an_earned_closest_approach_brings_an_earned_time_custody_and_delta_v(self, name: str) -> None:
        earned = 0
        for cell, friendly in _cells(_RESULTS[name]):
            bases = cell.figure_bases
            if bases.closest_approach_km.kind not in _EARNED:
                continue
            earned += 1
            assert bases.time_to_closest_hours.kind in _EARNED
            assert bases.custody_maintained.kind is Basis.COMPUTED
            assert bases.custody_gap_hours.kind is Basis.COMPUTED
            manoeuvre_without_target = friendly.action_type is ActionType.MANOEUVRE and friendly.burn is None
            if not manoeuvre_without_target:
                assert bases.delta_v_cost_km_s.kind is Basis.COMPUTED, (name, friendly.name)
        assert earned

    def test_no_note_beside_an_earned_figure_reads_a_lookup_constant(self, name: str) -> None:
        for cell, friendly in _cells(_RESULTS[name]):
            bases = cell.figure_bases
            if bases.closest_approach_km.kind not in _EARNED:
                continue
            for figure, basis in bases.items():
                if figure == "composite_score" or basis.kind is Basis.LOOKUP:
                    continue
                assert not any(word in basis.note for word in _LOOKUP_WORDS), (name, figure, basis.note)
            if bases.delta_v_cost_km_s.kind is Basis.LOOKUP:
                assert friendly.action_type is ActionType.MANOEUVRE and friendly.burn is None
                assert "Enter a target separation" in bases.delta_v_cost_km_s.note

    def test_a_response_that_does_not_burn_spends_nothing_and_says_why(self, name: str) -> None:
        still = [(c, f) for c, f in _cells(_RESULTS[name])
                 if f.action_type is not ActionType.MANOEUVRE and c.figure_bases.closest_approach_km.kind in _EARNED]
        assert still
        for cell, _friendly in still:
            assert cell.delta_v_cost_km_s == 0.0
            assert cell.figure_bases.delta_v_cost_km_s.note.startswith("this response does not burn")

    def test_custody_read_from_the_red_track_is_never_the_rule_of_thumb(self, name: str) -> None:
        for cell, _friendly in _cells(_RESULTS[name]):
            assert "rule of thumb" not in cell.figure_bases.custody_maintained.note
            assert "rule of thumb" not in cell.figure_bases.custody_gap_hours.note


class TestTheLookupsStayWhereNothingIsEarned:
    def test_an_unbound_scenario_keeps_every_lookup_labelled_as_one(self) -> None:
        result = evaluate_scenario(_scenario())
        for cell, _friendly in _cells(result):
            assert cell.figure_bases == LOOKUP_BASES
            assert all(basis.kind is Basis.LOOKUP for _figure, basis in cell.figure_bases.items())

    def test_a_manoeuvre_that_names_no_burn_keeps_its_lookup_and_says_why(self) -> None:
        result = _RESULTS["computed"]
        for cell in result.outcome_matrix[0]:   # row 0 is the manoeuvre, with no hypothesis
            assert cell.figure_bases.closest_approach_km.kind is Basis.LOOKUP
            assert cell.ca_refusal is not None and "names no burn" in cell.ca_refusal


class TestTheLookupModelRefusesABoundScenario:
    def test_compute_outcome_metrics_refuses_a_bound_scenario(self) -> None:
        scenario = _scenario(binding=_binding())
        with pytest.raises(ValueError, match="evaluate_scenario"):
            compute_outcome_metrics(scenario.adversary_actions[0], scenario.friendly_responses[0], scenario)

    def test_it_still_serves_an_unbound_scenario(self) -> None:
        scenario = _scenario()
        cell = compute_outcome_metrics(scenario.adversary_actions[0], scenario.friendly_responses[0], scenario)
        assert cell.figure_bases == LOOKUP_BASES
