"""Unit tests for spectre.domain.decision — Phase 1 deterministic scenario evaluation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeMetrics,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    compute_outcome_metrics,
    evaluate_scenario,
    find_robust_response,
    rank_responses,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _epoch() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _adv(id: str = "A1", name: str = "Proximity approach",
          atype: ActionType = ActionType.MANOEUVRE,
          prob: float = 0.6, conf: float = 0.8) -> AdversaryAction:
    return AdversaryAction(id=id, name=name, action_type=atype,
                            probability=prob, confidence=conf)


def _fr(id: str = "R1", name: str = "COLA manoeuvre",
         atype: ActionType = ActionType.MANOEUVRE,
         cost: float = 0.3, rev: float = 0.8, time_h: float = 6.0) -> FriendlyResponse:
    return FriendlyResponse(id=id, name=name, action_type=atype,
                             cost=cost, reversibility=rev,
                             time_to_execute_hours=time_h)


def _scenario(adv_list=None, fr_list=None) -> Scenario:
    adv_list = adv_list or [_adv()]
    fr_list  = fr_list  or [_fr()]
    return Scenario(
        name="Test Scenario",
        epoch_utc=_epoch(),
        adversary_actions=adv_list,
        friendly_responses=fr_list,
        horizon_hours=72.0,
    )


# ── ActionType enum ────────────────────────────────────────────────────────────

class TestActionType:
    def test_all_values_accessible(self):
        assert ActionType.MANOEUVRE.value        == "manoeuvre"
        assert ActionType.SENSOR_RETASK.value    == "sensor_retask"
        assert ActionType.POSTURE_CHANGE.value   == "posture_change"
        assert ActionType.NO_ACTION.value        == "no_action"


# ── SelectorStrategy enum ─────────────────────────────────────────────────────

class TestSelectorStrategy:
    def test_all_strategies_accessible(self):
        assert SelectorStrategy.MINIMAX.value        == "minimax"
        assert SelectorStrategy.EXPECTED_VALUE.value == "expected_value"
        assert SelectorStrategy.MAXIMIN.value        == "maximin"


# ── Data model validation ─────────────────────────────────────────────────────

class TestDataModels:
    def test_adversary_action_fields(self):
        a = _adv()
        assert a.id == "A1"
        assert a.probability == pytest.approx(0.6)
        assert a.confidence  == pytest.approx(0.8)

    def test_friendly_response_fields(self):
        r = _fr()
        assert r.id == "R1"
        assert r.cost == pytest.approx(0.3)
        assert r.reversibility == pytest.approx(0.8)
        assert r.time_to_execute_hours == pytest.approx(6.0)

    def test_scenario_defaults(self):
        s = _scenario()
        assert s.horizon_hours == 72.0
        assert s.w_custody + s.w_closest_approach + s.w_dv_cost + s.w_time_to_exec + s.w_reversibility == pytest.approx(1.0)


# ── compute_outcome_metrics ────────────────────────────────────────────────────

class TestComputeOutcomeMetrics:
    def test_returns_outcome_metrics(self):
        a = _adv()
        r = _fr()
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert isinstance(om, OutcomeMetrics)

    def test_composite_score_in_unit_interval(self):
        a = _adv()
        r = _fr()
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert 0.0 <= om.composite_score <= 1.0

    def test_manoeuvre_vs_no_action_loses_custody(self):
        """Adversary manoeuvre + friendly NO_ACTION → custody not maintained."""
        a = _adv(atype=ActionType.MANOEUVRE)
        r = _fr(atype=ActionType.NO_ACTION, cost=0.0, rev=0.5)
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert not om.custody_maintained

    def test_manoeuvre_vs_cola_maintains_custody(self):
        """Adversary manoeuvre + friendly COLA → custody maintained."""
        a = _adv(atype=ActionType.MANOEUVRE)
        r = _fr(atype=ActionType.MANOEUVRE)
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert om.custody_maintained

    def test_no_action_adversary_no_custody_loss(self):
        a = _adv(atype=ActionType.NO_ACTION)
        r = _fr(atype=ActionType.NO_ACTION, cost=0.0, rev=1.0)
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert om.custody_maintained

    def test_manoeuvre_response_has_positive_dv(self):
        a = _adv()
        r = _fr(atype=ActionType.MANOEUVRE, cost=0.5)
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert om.delta_v_cost_km_s > 0.0

    def test_non_manoeuvre_response_zero_dv(self):
        a = _adv()
        r = _fr(atype=ActionType.SENSOR_RETASK)
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert om.delta_v_cost_km_s == 0.0

    def test_str_representation(self):
        a = _adv()
        r = _fr()
        s = _scenario([a], [r])
        om = compute_outcome_metrics(a, r, s)
        assert "Custody" in str(om)


# ── rank_responses ────────────────────────────────────────────────────────────

class TestRankResponses:
    def test_ranked_best_first(self):
        a = _adv()
        r_cola  = _fr(id="R1", name="COLA",   atype=ActionType.MANOEUVRE, cost=0.3)
        r_noop  = _fr(id="R2", name="No Op",  atype=ActionType.NO_ACTION, cost=0.0)
        s = _scenario([a], [r_cola, r_noop])
        om_cola = compute_outcome_metrics(a, r_cola, s)
        om_noop = compute_outcome_metrics(a, r_noop, s)
        ranked  = rank_responses(0, [r_cola, r_noop], [om_cola, om_noop])
        assert ranked[0][1] <= ranked[1][1]   # sorted ascending by score

    def test_returns_all_responses(self):
        a  = _adv()
        rs = [_fr(id=f"R{i}", name=f"R{i}") for i in range(4)]
        s  = _scenario([a], rs)
        row = [compute_outcome_metrics(a, r, s) for r in rs]
        ranked = rank_responses(0, rs, row)
        assert len(ranked) == 4


# ── find_robust_response ──────────────────────────────────────────────────────

class TestFindRobustResponse:
    def _two_adversary_scenario(self):
        a1 = _adv(id="A1", atype=ActionType.MANOEUVRE)
        a2 = _adv(id="A2", atype=ActionType.NO_ACTION)
        r1 = _fr(id="R1", atype=ActionType.MANOEUVRE, cost=0.4, rev=0.7)
        r2 = _fr(id="R2", atype=ActionType.SENSOR_RETASK, cost=0.1, rev=0.9)
        r3 = _fr(id="R3", atype=ActionType.NO_ACTION, cost=0.0, rev=1.0)
        s  = _scenario([a1, a2], [r1, r2, r3])
        om = [[compute_outcome_metrics(a, r, s) for r in [r1, r2, r3]] for a in [a1, a2]]
        return s, om

    def test_minimax_returns_a_friendly_response(self):
        s, om = self._two_adversary_scenario()
        robust = find_robust_response(s, om, SelectorStrategy.MINIMAX)
        assert isinstance(robust, FriendlyResponse)

    def test_expected_value_returns_a_friendly_response(self):
        s, om = self._two_adversary_scenario()
        robust = find_robust_response(s, om, SelectorStrategy.EXPECTED_VALUE)
        assert isinstance(robust, FriendlyResponse)

    def test_maximin_returns_a_friendly_response(self):
        s, om = self._two_adversary_scenario()
        robust = find_robust_response(s, om, SelectorStrategy.MAXIMIN)
        assert isinstance(robust, FriendlyResponse)

    def test_minimax_deterministic(self):
        """Same scenario → same minimax recommendation on repeated calls."""
        s, om = self._two_adversary_scenario()
        r1 = find_robust_response(s, om, SelectorStrategy.MINIMAX)
        r2 = find_robust_response(s, om, SelectorStrategy.MINIMAX)
        assert r1.id == r2.id

    def test_no_friendly_raises(self):
        s  = _scenario(fr_list=[])
        s.friendly_responses = []
        om = [[]]
        with pytest.raises(ValueError):
            find_robust_response(s, om)


# ── evaluate_scenario ─────────────────────────────────────────────────────────

class TestEvaluateScenario:
    def test_smoke_test_minimal(self):
        s      = _scenario()
        result = evaluate_scenario(s)
        assert isinstance(result, ScenarioResult)

    def test_outcome_matrix_shape(self):
        adv_list = [_adv(id=f"A{i}") for i in range(3)]
        fr_list  = [_fr(id=f"R{i}")  for i in range(2)]
        s        = _scenario(adv_list, fr_list)
        result   = evaluate_scenario(s)
        assert len(result.outcome_matrix) == 3
        assert len(result.outcome_matrix[0]) == 2

    def test_ranked_per_adversary_shape(self):
        adv_list = [_adv(id=f"A{i}") for i in range(2)]
        fr_list  = [_fr(id=f"R{i}")  for i in range(3)]
        s        = _scenario(adv_list, fr_list)
        result   = evaluate_scenario(s)
        assert len(result.ranked_per_adversary) == 2
        assert len(result.ranked_per_adversary[0]) == 3

    def test_robust_response_is_in_friendly_list(self):
        fr_list = [_fr(id=f"R{i}") for i in range(3)]
        s       = _scenario(fr_list=fr_list)
        result  = evaluate_scenario(s)
        assert result.robust_best_response in s.friendly_responses

    def test_wall_time_positive(self):
        s = _scenario()
        result = evaluate_scenario(s)
        assert result.computation_time_s >= 0.0

    def test_summary_table_contains_robust_header(self):
        s = Scenario(
            name="Test GEO Scenario",
            epoch_utc=_epoch(),
            adversary_actions=[_adv()],
            friendly_responses=[_fr()],
        )
        result = evaluate_scenario(s)
        assert "Robust response" in result.summary_table()

    def test_empty_adversary_raises(self):
        s = Scenario(
            name="Empty",
            epoch_utc=_epoch(),
            adversary_actions=[],
            friendly_responses=[_fr()],
        )
        with pytest.raises(ValueError):
            evaluate_scenario(s)

    def test_empty_friendly_raises(self):
        s = Scenario(
            name="Empty",
            epoch_utc=_epoch(),
            adversary_actions=[_adv()],
            friendly_responses=[],
        )
        with pytest.raises(ValueError):
            evaluate_scenario(s)

    def test_expected_value_strategy(self):
        s = _scenario(
            [_adv(id="A1", prob=0.7), _adv(id="A2", prob=0.3)],
            [_fr(id="R1"), _fr(id="R2")],
        )
        result = evaluate_scenario(s, strategy=SelectorStrategy.EXPECTED_VALUE)
        assert result.robust_strategy == SelectorStrategy.EXPECTED_VALUE

    def test_mc_integration_stub_does_not_crash(self):
        """Ensure Phase 2 ManoeuvreHypothesis field absence doesn't crash."""
        a = AdversaryAction(
            id="A1", name="Intercept approach",
            action_type=ActionType.MANOEUVRE,
            probability=0.6, confidence=0.8,
        )
        assert not hasattr(a, "hypothesis")   # Phase 1: no hypothesis attribute
