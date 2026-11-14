"""Probes P-15 to P-18: reproducibility, weight sensitivity, closest-approach sensitivity and the rendered page.

Framework references: gate G2 and section 2 (reproducibility, probe 15); section 1b and 1h, L3 (weight stability,
probe 16); section 1b, L1 (the assessor's probe P-17 for finding F-10); gate G6 (the assessor's probe P-18, uncertainty
indications on the rendered page).

Every probe prints what it measured, so evidence/probes.log holds the numbers whether a probe passes or fails.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from tests.unit.test_decision_sampled import _binding, _bound, _page
from tests.unit.test_decision_sampled import _scenario as _bound_rows

EPOCH = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
WEIGHTS = ("w_custody", "w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility")


def _lookup() -> Scenario:
    rows = [
        AdversaryAction(id="A0", name="approach", action_type=ActionType.MANOEUVRE, probability=0.6, confidence=0.7),
        AdversaryAction(id="A1", name="hold", action_type=ActionType.NO_ACTION, probability=0.3, confidence=0.7),
        AdversaryAction(id="A2", name="posture", action_type=ActionType.POSTURE_CHANGE, probability=0.1,
                        confidence=0.7),
    ]
    cols = [
        FriendlyResponse(id="F0", name="do nothing", action_type=ActionType.NO_ACTION, cost=0.0, reversibility=1.0,
                         time_to_execute_hours=0.0),
        FriendlyResponse(id="F1", name="retask sensor", action_type=ActionType.SENSOR_RETASK, cost=0.2,
                         reversibility=0.9, time_to_execute_hours=2.0),
        FriendlyResponse(id="F2", name="manoeuvre", action_type=ActionType.MANOEUVRE, cost=0.4, reversibility=0.5,
                         time_to_execute_hours=6.0),
        FriendlyResponse(id="F3", name="posture", action_type=ActionType.POSTURE_CHANGE, cost=0.3,
                         reversibility=0.8, time_to_execute_hours=3.0),
    ]
    return Scenario(name="lookup probe", epoch_utc=EPOCH, adversary_actions=rows, friendly_responses=cols)


def _computed() -> Scenario:
    """Both plane-change element sets bound, no hypothesis: every closest approach computed by SGP4."""
    return _bound_rows(binding=_binding(), horizon_hours=1.0)


SCENARIOS = {"lookup": _lookup, "computed": _computed, "sampled": _bound}


@pytest.fixture(scope="module")
def results() -> dict[str, ScenarioResult]:
    return {name: evaluate_scenario(make()) for name, make in SCENARIOS.items()}


# ── P-15: the same inputs and seed reproduce the same recommendation ─────────

@pytest.mark.parametrize("name", list(SCENARIOS))
def test_p15_same_inputs_same_result(name: str, results: dict[str, ScenarioResult]) -> None:
    first = results[name]
    again = evaluate_scenario(SCENARIOS[name]())
    same_scores = ([[c.composite_score for c in r] for r in first.outcome_matrix]
                   == [[c.composite_score for c in r] for r in again.outcome_matrix])
    same_bands = ([[getattr(c, "ca_percentiles", None) for c in r] for r in first.outcome_matrix]
                  == [[getattr(c, "ca_percentiles", None) for c in r] for r in again.outcome_matrix])
    hashes_a = [(i.label, i.sha256) for i in first.provenance.inputs]
    hashes_b = [(i.label, i.sha256) for i in again.provenance.inputs]
    print(f"P-15 {name}: pick {first.robust_best_response.id} then {again.robust_best_response.id}; scores identical "
          f"{same_scores}; sampled bands identical {same_bands}; input hashes identical {hashes_a == hashes_b} "
          f"({len(hashes_a)} inputs); code version {first.provenance.code_version}; computed_at differs "
          f"{first.provenance.computed_at != again.provenance.computed_at}; nothing is stored to replay from")
    assert first.robust_best_response.id == again.robust_best_response.id
    assert same_scores and same_bands and hashes_a == hashes_b


# ── P-16: the smallest single weight change that changes the recommendation ──

def _figures(cell: object) -> decision._Figures:
    return decision._Figures(cell.custody_maintained, cell.custody_gap_hours,  # type: ignore[attr-defined]
                             cell.closest_approach_km, cell.delta_v_cost_km_s)  # type: ignore[attr-defined]


def _picks(scenario: Scenario, result: ScenarioResult, weights: dict[str, float]) -> dict[str, str]:
    s = dataclasses.replace(scenario, **weights)
    cells = [[SimpleNamespace(composite_score=decision._score(s, f, _figures(c)))
              for f, c in zip(s.friendly_responses, row, strict=True)] for row in result.outcome_matrix]
    return {rule.value: find_robust_response(s, cells, rule).id  # type: ignore[arg-type]
            for rule in (SelectorStrategy.MINIMAX, SelectorStrategy.EXPECTED_VALUE)}


def _moved(base: dict[str, float], key: str, new: float) -> dict[str, float]:
    rest = sum(v for k, v in base.items() if k != key)
    return {k: (new if k == key else v * (1.0 - new) / rest) for k, v in base.items()}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_p16_smallest_single_weight_change_that_flips_the_pick(name: str, results: dict[str, ScenarioResult]) -> None:
    scenario, result = SCENARIOS[name](), results[name]
    base = {k: getattr(scenario, k) for k in WEIGHTS}
    rebuilt = [[decision._score(scenario, f, _figures(c)) for f, c in zip(scenario.friendly_responses, row,
                                                                              strict=True)]
               for row in result.outcome_matrix]
    drift = max(abs(a - c.composite_score) for row_a, row in zip(rebuilt, result.outcome_matrix, strict=True)
                for a, c in zip(row_a, row, strict=True))
    start = _picks(scenario, result, base)
    report = {}
    for key in WEIGHTS:
        found = {}
        for step in range(1, 1001):
            d = step / 1000.0
            for sign in (-1.0, 1.0):
                new = base[key] + sign * d
                if not 0.0 <= new <= 1.0:
                    continue
                now = _picks(scenario, result, _moved(base, key, new))
                for rule, pick in now.items():
                    if rule not in found and pick != start[rule]:
                        found[rule] = (round(sign * d, 3), pick)
            if len(found) == len(start):
                break
        report[key] = found
    confirm = {}
    for key, found in report.items():
        for rule, (delta, pick) in found.items():
            full = evaluate_scenario(dataclasses.replace(scenario, **_moved(base, key, base[key] + delta)),
                                     SelectorStrategy(rule))
            confirm[(key, rule)] = full.robust_best_response.id == pick
    print(f"P-16 {name}: starting picks {start}; score rebuilt from cell figures within {drift:.2e}; smallest change "
          f"per weight (others rescaled) that changes the pick: {report}; confirmed by a full re-evaluation: {confirm}")
    assert drift < 1e-3
    assert all(confirm.values())


# ── P-17: how much closest approach moves the score (finding F-10) ──────────

def test_p17_closest_approach_barely_moves_the_score() -> None:
    """Two responses identical in time to execute and reversibility, custody held in both. X burns nothing and
    leaves a 1 km miss; Y burns 1 m/s and moves the miss to 100 km. At the default weights the engine prefers X."""
    s = _lookup()
    same = dict(action_type=ActionType.MANOEUVRE, cost=0.0, reversibility=1.0, time_to_execute_hours=1.0)
    x = FriendlyResponse(id="X", name="no burn, 1 km miss", **same)  # type: ignore[arg-type]
    y = FriendlyResponse(id="Y", name="1 m/s burn, 100 km miss", **same)  # type: ignore[arg-type]
    fx = decision._Figures(True, 0.0, 1.0, 0.0)
    fy = decision._Figures(True, 0.0, 100.0, 0.001)
    sx, sy = decision._score(s, x, fx), decision._score(s, y, fy)
    two = dataclasses.replace(s, adversary_actions=s.adversary_actions[:1], friendly_responses=[x, y])
    pick = find_robust_response(two, [[SimpleNamespace(composite_score=sx), SimpleNamespace(composite_score=sy)]],
                                SelectorStrategy.MINIMAX).id  # type: ignore[list-item]
    km_per_m_s = (s.w_dv_cost / (decision._DV_NORMALISATION_KM_S * 1000.0)) / (
        s.w_closest_approach / decision._CA_NORMALISATION_KM)
    big = decision._score(s, y, decision._Figures(True, 0.0, 100.0, 0.1))
    bigger = decision._score(s, y, decision._Figures(True, 0.0, 100.0, 0.5))
    print(f"P-17 score X (no burn, 1 km) {sx:.6f}; score Y (1 m/s, 100 km) {sy:.6f}; minimax recommends {pick}; "
          f"break-even: 1 m/s of our delta-V weighs the same as {km_per_m_s:.0f} km of miss distance; "
          f"a 100 m/s and a 500 m/s burn score {big:.6f} and {bigger:.6f}")
    assert pick == "X"
    assert big == bigger


# ── P-18: uncertainty indications on the rendered page (gate G6) ─────────────

@pytest.mark.parametrize("name", ["lookup", "computed"])
def test_p18_every_figure_on_the_page_carries_its_basis(name: str, results: dict[str, ScenarioResult]) -> None:
    text = _page(results[name])
    cells = sum(len(r) for r in results[name].outcome_matrix)
    marks = len(re.findall(r"\((lookup|sampled|computed)\)", text))
    spread_lines = text.count("Score spread")
    stability = [w for w in ("ranks first", "would change if", "weight stability", "holds if the weights")
                 if w in text]
    banner = "Modelled estimate, not a computed solution." in text
    print(f"P-18 {name}: {cells} cells, {marks} basis marks on the page (closest approach and custody per cell), "
          f"{spread_lines} score spread lines, modelled banner {banner}, recommendation stability wording found: "
          f"{stability}")
    assert marks >= 2 * cells
    assert spread_lines >= cells
    assert stability == []
