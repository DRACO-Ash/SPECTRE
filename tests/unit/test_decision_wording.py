"""Decision Engine wording that told the operator something untrue about their own scenario (SPC-119).

BIND_TO_EARN predates 0.15.0 and always asked for both sides, so an operator
whose red track was already bound was told to bind one. The closest
approach's binding note did the same. Each now names only the side still to
bind. The custody sentence for an element set that reaches its limit exactly
as the horizon ends said the limit fell after the horizon ended; it falls as
the horizon ends, and the set is still within it, since custody is lost only
once its age is strictly past the limit.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from spectre.domain import decision
from spectre.domain.custody import Custody, CustodyStatus, Horizon, custody_over_horizon
from spectre.domain.decision import (
    BIND_TO_EARN,
    WORST_CASE_BASIS,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioBinding,
    evaluate_scenario,
)
from tests.unit.test_decision_sampled import _elset

_EPOCH = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
_HELD = CustodyStatus(Custody.HELD, "Custody held.")


def _manoeuvre_only(binding: ScenarioBinding | None) -> Scenario:
    """One manoeuvre with no hypothesis: every figure a lookup, custody the worst case once red is read."""
    return Scenario(
        name="Wording", epoch_utc=_EPOCH, horizon_hours=1.0, binding=binding,
        # P 1: the manoeuvre alone, certain, so no remainder row of no adversary action joins it (SPC-203).
        adversary_actions=[AdversaryAction(id="A1", name="Approach", action_type=ActionType.MANOEUVRE,
                                           probability=1.0, confidence=0.7)],
        friendly_responses=[FriendlyResponse(id="F1", name="Hold", action_type=ActionType.NO_ACTION, cost=0.0,
                                             reversibility=1.0, time_to_execute_hours=1.0)],
    )


def _red_read() -> ScenarioBinding:
    return ScenarioBinding(red=dataclasses.replace(_elset("red"), custody=_HELD))


class TestBindToEarn:
    def test_an_operator_whose_red_track_is_bound_is_asked_only_for_a_blue_asset(self) -> None:
        result = evaluate_scenario(_manoeuvre_only(_red_read()))
        assert result.basis == f"{WORST_CASE_BASIS} {decision.BIND_BLUE_TO_EARN}"
        assert decision.BIND_BLUE_TO_EARN == (
            "Bind a blue asset to compute the closest approach of a row whose action does not move the red track, "
            "or to sample one that carries a manoeuvre hypothesis."
        )
        assert "Bind a red track" not in result.basis

    def test_an_operator_whose_blue_asset_is_bound_is_asked_only_for_a_red_track(self) -> None:
        result = evaluate_scenario(_manoeuvre_only(ScenarioBinding(blue=_elset("blue"))))
        assert result.basis.endswith(decision.BIND_RED_TO_EARN)
        assert decision.BIND_RED_TO_EARN == (
            "Bind a red track to compute the closest approach of a row whose action does not move it, or to "
            "sample one that carries a manoeuvre hypothesis."
        )
        assert "blue asset" not in result.basis

    def test_with_nothing_bound_both_are_asked_for_as_before(self) -> None:
        assert evaluate_scenario(_manoeuvre_only(None)).basis.endswith(BIND_TO_EARN)


class TestTheComputedBindingNote:
    @pytest.mark.parametrize(("binding", "line"), [
        (ScenarioBinding(red=_elset("red")), "Closest approach not computed: bind a blue asset to compute it."),
        (ScenarioBinding(blue=_elset("blue")), "Closest approach not computed: bind a red track to compute it."),
    ], ids=["red only", "blue only"])
    def test_it_names_only_the_side_still_to_bind(self, binding: ScenarioBinding, line: str) -> None:
        assert evaluate_scenario(_manoeuvre_only(binding)).computed_binding_note == line


class TestTheLimitAtTheHorizonsEnd:
    def test_a_limit_reached_exactly_as_the_horizon_ends_says_so(self) -> None:
        start = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
        over = custody_over_horizon(_HELD, elset_hours=14.0, limit_hours=24.0, horizon=Horizon(start, 10.0))
        assert over.maintained
        assert over.sentence == (
            "Custody held through the 10 h horizon: its newest element set reaches its 24 h limit at "
            "2026-10-29 22:00 UTC, as the horizon ends, and passes it only after."
        )

    def test_a_limit_after_the_horizon_still_says_after(self) -> None:
        start = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
        over = custody_over_horizon(_HELD, elset_hours=13.0, limit_hours=24.0, horizon=Horizon(start, 10.0))
        assert over.sentence.endswith("until 2026-10-29 23:00 UTC, after the horizon ends.")

    @pytest.mark.parametrize(("elset_hours", "h"), [
        (4.00000000000001, 68.0), (3.99999999999999, 68.0), (5.000000000277778, 67.0),
    ], ids=["a float step early", "a float step late", "a microsecond early"])
    def test_a_limit_within_float_tolerance_of_the_end_is_reached_as_it_ends_on_either_side(
        self, elset_hours: float, h: float,
    ) -> None:
        """Float error either side of the end is not an hour of custody lost: the set reaches its limit as it ends."""
        start = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
        over = custody_over_horizon(_HELD, elset_hours=elset_hours, limit_hours=72.0, horizon=Horizon(start, h))
        assert (over.maintained, over.lost_from_h, over.lost_hours) == (True, None, 0.0)
        assert ", as the horizon ends, and passes it only after." in over.sentence
