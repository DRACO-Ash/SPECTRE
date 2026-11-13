"""The sampled path searches only while both element sets are within their limits, as the computed path does (SPC-118).

0.15.0 trimmed the computed search to the earlier of the horizon's end and the moment either element set passes
its limit, but sampled over the whole horizon: 100 samples over 48 h were admitted on a 24 h LEO limit, and a
miss sampled past the limit rests on an out-of-date orbit. One helper now sets the span both paths search and the
span the propagator gap is measured over. An element set at its limit already earns no span and is refused before
anything runs, and a hypothesised burn after the span the row can earn is refused, since its figure would be the
no-burn one.

The bound fixtures are the plane-change reference element sets (tests/unit/_decision_reference.py), each given an
age against the 24 h LEO limit.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest

from spectre.astro.monte_carlo import ManoeuvreHypothesis, SeparationWindow
from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    AdversaryHypothesis,
    FriendlyResponse,
    PreManoeuvreState,
    Scenario,
    ScenarioBinding,
    evaluate_scenario,
    needs_a_run,
)
from spectre.domain.provenance import Basis
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_sampled import _LOOKUPS, _elset, _evasive, _Fake, _never, _page, _red_at

_HOUR_S = 3600.0


def _aged(age_h: float) -> ScenarioBinding:
    """Both plane-change element sets *age_h* old at evaluation against the 24 h LEO limit."""
    return ScenarioBinding(red=_elset("red", age=age_h), blue=_elset("blue", age=age_h))


def _evasive_at(at: datetime, n_samples: int = 50) -> AdversaryHypothesis:
    red = _red_at(at)
    return AdversaryHypothesis.from_archetype(
        "evasive", PreManoeuvreState(at, tuple(red.state_eci_km)), n_samples=n_samples,
    )


def _one_row(hypothesis: AdversaryHypothesis, *, age_h: float, horizon_h: float = 48.0, still: bool = False) -> Scenario:
    """One manoeuvre row carrying *hypothesis*, and a no-action row when *still*; one no-action response."""
    # Alone, the action is certain, P 1, so no remainder row is computed beside it (SPC-203); with the still row,
    # the two share P equally.
    actions = [AdversaryAction("A0", "Evade", ActionType.MANOEUVRE, 0.5 if still else 1.0, 0.7, hypothesis=hypothesis)]
    if still:
        actions.append(AdversaryAction("A1", "Hold", ActionType.NO_ACTION, 0.5, 0.7))
    return Scenario(
        name="Span", epoch_utc=EPOCH, adversary_actions=actions,
        friendly_responses=[FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0)],
        horizon_hours=horizon_h, binding=_aged(age_h),
    )


class TestTheSampledSearchStopsAtTheLimit:
    def test_it_searches_only_while_both_element_sets_are_current(self) -> None:
        """1: 20 h old on a 24 h limit, over a 48 h horizon, the series runs over 4 h, not 48."""
        fake = _Fake()
        evaluate_scenario(_one_row(_evasive(50), age_h=20.0), sampler=fake)
        assert len(fake.calls) == 2   # on its own seed and the second (SPC-224), over the same span
        assert fake.calls[0][2] == fake.calls[1][2] == SeparationWindow(start_utc=EPOCH, span_s=4 * _HOUR_S)

    def test_the_trim_admits_what_the_horizon_alone_would_not(self) -> None:
        """2: enough samples that over 48 h their floor alone, samples times hours, is past MAX_SAMPLE_HOURS, so
        they would be refused before anything ran; over the 24 h earned, they fit, each row charged twice for the
        second seed its convergence is checked on (SPC-224)."""
        n = int(decision.MAX_SAMPLE_HOURS / 72.0)
        assert 2 * n * 48.0 > decision.MAX_SAMPLE_HOURS
        fake = _Fake()
        result = evaluate_scenario(_one_row(_evasive(n), age_h=0.0), sampler=fake)
        assert fake.calls[0][2].span_s == 24 * _HOUR_S
        cell = result.outcome_matrix[0][0]
        assert cell.ca_refusal is None
        assert cell.figure_bases.closest_approach_km.kind is Basis.SAMPLED

    def test_an_element_set_at_its_limit_is_refused_before_it_runs(self) -> None:
        """3: 24.0 h old on a 24 h limit is still current, but it earns no time at all."""
        scenario = _one_row(_evasive(50), age_h=24.0)
        result = evaluate_scenario(scenario, sampler=_never)
        stale = (
            "Not sampled: the red orbit is out of date, at its limit already or of unknown age, so a miss sampled "
            "from it would not be earned."
        )
        assert result.outcome_matrix[0][0].ca_refusal == stale + _LOOKUPS
        assert needs_a_run(scenario) is False

    def test_a_burn_past_the_earned_span_is_refused(self) -> None:
        """4: 20 h old, so the row earns 4 h; a burn at +6 h would leave the no-burn figure."""
        scenario = _one_row(_evasive_at(EPOCH + timedelta(hours=6.0)), age_h=20.0)
        result = evaluate_scenario(scenario, sampler=_never)
        sentence = (
            "Not sampled: the burn at 2026-10-17 18:00 UTC is after 2026-10-17 16:00 UTC, when the red element set "
            "passes its limit, so the window this row can earn holds no burn and its figure would be the no-burn one."
        )
        assert result.outcome_matrix[0][0].ca_refusal == sentence + _LOOKUPS
        assert needs_a_run(scenario) is False

    def test_the_sampled_basis_names_the_span(self) -> None:
        """5."""
        result = evaluate_scenario(_one_row(_evasive(50), age_h=20.0), sampler=_Fake())
        bases = result.outcome_matrix[0][0].figure_bases
        assert "over 4.0 h of the 48 h horizon from the scenario epoch, while both element sets are within their " \
            "limits, by RK45" in bases.closest_approach_km.note
        assert "of 50 samples over 4.0 h of the 48 h horizon" in bases.time_to_closest_hours.note


class TestTheSpanNote:
    _NOTE = (
        "Closest approaches are searched over the first 4.0 h of the 48 h horizon, while both element sets are "
        "within their limits; past 2026-10-17 16:00 UTC a miss would rest on an out-of-date orbit."
    )

    def test_the_span_note_covers_a_sampled_only_result(self) -> None:
        """6: 0.15.0 said nothing without a computed cell."""
        result = evaluate_scenario(_one_row(_evasive(50), age_h=20.0), sampler=_Fake())
        assert result.n_computed_cells == 0
        assert result.searched_span_note == self._NOTE
        assert self._NOTE in _page(result)

    def test_no_note_when_the_whole_horizon_is_searched(self) -> None:
        result = evaluate_scenario(_one_row(_evasive(50), age_h=0.0, horizon_h=1.0), sampler=_Fake())
        assert result.searched_span_note is None

    def test_no_note_when_nothing_is_searched(self) -> None:
        result = evaluate_scenario(_one_row(_evasive(50), age_h=24.0), sampler=_never)
        assert result.searched_span_note is None


class TestThePropagatorGap:
    def test_the_gap_is_measured_over_the_searched_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """7: 0.15.0 measured it over the whole horizon, past the limit."""
        asked: list[SeparationWindow] = []

        def gap(_red: str, _blue: str, window: SeparationWindow, _h: tuple[ManoeuvreHypothesis, ...]) -> float:
            asked.append(window)
            return 1.0

        monkeypatch.setattr(decision, "rk45_sgp4_gap_km", gap)
        evaluate_scenario(_one_row(_evasive(50), age_h=20.0, still=True), sampler=_Fake())
        assert asked == [SeparationWindow(start_utc=EPOCH, span_s=4 * _HOUR_S)]


def test_the_helper_takes_the_earliest_limit() -> None:
    """The shared span is the least of the horizon and each side's time left before its limit."""
    scenario = _one_row(_evasive(50), age_h=0.0)
    scenario = dataclasses.replace(
        scenario, binding=ScenarioBinding(red=_elset("red", age=10.0), blue=_elset("blue", age=22.0)),
    )
    assert decision._searched_span_s(scenario) == 2 * _HOUR_S
