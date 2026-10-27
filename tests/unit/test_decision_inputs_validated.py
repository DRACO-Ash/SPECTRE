"""The Decision Engine's data classes refuse values outside their meaning.

Audit F-112. Nothing validated horizon, probability, confidence, cost or
reversibility in the domain: a zero horizon raised ZeroDivisionError, a
reversibility above 1 made scores negative, and negative probabilities could
pass the expected-value guard. The route has refused these since F-164; the
classes now refuse them for every caller.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.domain.decision import ActionType, AdversaryAction, FriendlyResponse, Scenario

_BAD = [-0.1, 1.1, math.nan, math.inf]


def _adv(**k: Any) -> AdversaryAction:
    return AdversaryAction(**{"id": "A", "name": "a", "action_type": ActionType.MANOEUVRE,
                              "probability": 0.5, "confidence": 0.5, **k})


def _fr(**k: Any) -> FriendlyResponse:
    return FriendlyResponse(**{"id": "F", "name": "f", "action_type": ActionType.MANOEUVRE,
                               "cost": 0.5, "reversibility": 0.5, "time_to_execute_hours": 6.0, **k})


def _sc(**k: Any) -> Scenario:
    return Scenario(**{"name": "s", "epoch_utc": datetime(2026, 1, 1, tzinfo=UTC),
                       "adversary_actions": [_adv()], "friendly_responses": [_fr()], **k})


@pytest.mark.parametrize("field", ["probability", "confidence"])
@pytest.mark.parametrize("value", _BAD)
def test_adversary_fractions(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        _adv(**{field: value})


@pytest.mark.parametrize("field", ["cost", "reversibility"])
@pytest.mark.parametrize("value", _BAD)
def test_friendly_fractions(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        _fr(**{field: value})


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf])
def test_time_to_execute(value: float) -> None:
    with pytest.raises(ValueError, match="time_to_execute_hours"):
        _fr(time_to_execute_hours=value)


@pytest.mark.parametrize("value", [0.0, -5.0, math.nan, math.inf])
def test_horizon(value: float) -> None:
    with pytest.raises(ValueError, match="horizon_hours"):
        _sc(horizon_hours=value)


@pytest.mark.parametrize("field", ["w_custody", "w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility"])
@pytest.mark.parametrize("value", _BAD)
def test_weights(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        _sc(**{field: value})


def test_valid_inputs_still_construct() -> None:
    s = _sc(horizon_hours=0.5, w_custody=0.0, w_dv_cost=1.0)
    assert (s.horizon_hours, s.w_custody, s.w_dv_cost) == (0.5, 0.0, 1.0)
