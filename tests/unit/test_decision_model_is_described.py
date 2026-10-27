"""The Decision Engine says what it computes, and computes nothing it hides.

Audit F-111: a "TLE refinement" took one instant's separation, not a closest
approach, could only lower the estimate, and sat behind ``except Exception:
pass``; the route always passed ``red_tle=None``, so it never ran.

Audit F-113: the docstrings said custody is lost only against NO_ACTION, that
the gap is horizon times (1 - reversibility), that the refinement used TLE
epoch separation, and that SGP4 propagation drives the evaluation. One test
per rule as implemented.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from spectre.domain import decision
from spectre.domain.decision import ActionType, AdversaryAction, FriendlyResponse, Scenario


def _pair(friendly_type: ActionType, *, confidence: float = 0.8, reversibility: float = 0.25) -> decision.OutcomeMetrics:
    adv = AdversaryAction("A", "approach", ActionType.MANOEUVRE, 0.6, confidence)
    fr = FriendlyResponse("F", "resp", friendly_type, 0.3, reversibility, 6.0)
    sc = Scenario("s", datetime(2026, 1, 1, tzinfo=UTC), [adv], [fr], horizon_hours=72.0)
    return decision.compute_outcome_metrics(adv, fr, sc)


@pytest.mark.parametrize("friendly", [ActionType.NO_ACTION, ActionType.POSTURE_CHANGE])
def test_custody_is_lost_unless_the_response_manoeuvres_or_retasks(friendly: ActionType) -> None:
    assert _pair(friendly).custody_maintained is False


def test_the_gap_is_scaled_by_adversary_confidence() -> None:
    # Not scaled by our reversibility any more (audit F-035).
    assert _pair(ActionType.NO_ACTION).custody_gap_hours == pytest.approx(72.0 * 0.8)


def test_no_tle_path_remains() -> None:
    for fn in (decision.compute_outcome_metrics, decision.evaluate_scenario):
        params = inspect.signature(fn).parameters
        assert "blue_tle" not in params and "red_tle" not in params
    source = inspect.getsource(decision)
    assert "except Exception" not in source
    assert "TLEOrbit" not in source


def test_the_docstrings_describe_the_lookup_model() -> None:
    module = " ".join((decision.__doc__ or "").split())
    assert "SGP4" not in module
    assert "lookup" in module and "uncalibrated" in module
    rules = " ".join((decision.compute_outcome_metrics.__doc__ or "").split())
    assert "POSTURE_CHANGE" in rules
    assert "confidence" in rules
    assert "epoch separation" not in rules
