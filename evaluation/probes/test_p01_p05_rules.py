"""Probes P-01 to P-05 and P-03b: the decision rules against hand-computed answers and metamorphic relations.

Framework references: section 1c and 4 (reference cases), section 2 table (metamorphic and property tests), probes 1 to
5 of the evaluation brief. P-03b is added by the assessor (framework 1a and 1b: probability normalisation).

Every probe prints what it measured, so evidence/probes.log holds the numbers whether a probe passes or fails.
The rules are driven through the engine's own entry points: find_robust_response (spectre/domain/decision.py:3584)
on stand-in cells that carry only composite_score, which is the one field that function reads, and evaluate_scenario
end to end where a probe needs real cells.
"""

from __future__ import annotations

import dataclasses
import itertools
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from spectre.web.routes.decision import _normalised_weights

EPOCH = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
RULES = (SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE)


def _scenario(p: list[float], n_responses: int) -> Scenario:
    rows = [AdversaryAction(id=f"A{i}", name=f"A{i}", action_type=ActionType.MANOEUVRE, probability=pi, confidence=0.5)
            for i, pi in enumerate(p)]
    cols = [FriendlyResponse(id=f"R{j}", name=f"R{j}", action_type=ActionType.NO_ACTION, cost=0.0, reversibility=1.0,
                             time_to_execute_hours=0.0) for j in range(n_responses)]
    return Scenario(name="probe", epoch_utc=EPOCH, adversary_actions=rows, friendly_responses=cols)


def _cells(costs: list[list[float]]) -> list[list[SimpleNamespace]]:
    return [[SimpleNamespace(composite_score=c) for c in row] for row in costs]


def _pick(costs: list[list[float]], p: list[float], rule: SelectorStrategy) -> str:
    s = _scenario(p, len(costs[0]))
    return find_robust_response(s, _cells(costs), rule).id  # type: ignore[arg-type]


# ── P-01: reference matrices with hand-computed answers ──────────────────────

#: Costs, rows = adversary actions, columns = responses. Hand-computed:
#:   minimax: column maxima 0.80, 0.60, 0.55 -> R2;  minimin: column minima 0.20, 0.30, 0.40 -> R0;
#:   expected value at P 0.6, 0.4: 0.44, 0.48, 0.46 -> R0.
REF_A = ([[0.2, 0.6, 0.4], [0.8, 0.3, 0.55]], [0.6, 0.4], {"minimax": "R2", "minimin": "R0", "expected_value": "R0"})
#: Four responses, three rows. Hand-computed:
#:   minimax: maxima 0.9, 0.7, 0.65, 0.8 -> R2;  minimin: minima 0.1, 0.2, 0.5, 0.05 -> R3;
#:   expected value at P 0.2, 0.3, 0.5: 0.640, 0.500, 0.595, 0.475 -> R3.
REF_B = ([[0.1, 0.7, 0.6, 0.8], [0.9, 0.2, 0.5, 0.05], [0.7, 0.6, 0.65, 0.6]], [0.2, 0.3, 0.5],
         {"minimax": "R2", "minimin": "R3", "expected_value": "R3"})


@pytest.mark.parametrize("case", [REF_A, REF_B], ids=["A", "B"])
def test_p01_rules_match_hand_computed_answers(case: tuple) -> None:
    costs, p, expected = case
    observed = {rule.value: _pick(costs, p, rule) for rule in RULES}
    print(f"P-01 costs={costs} P={p} expected={expected} observed={observed}")
    assert observed == expected


# ── P-02: matching pennies, pure maximin against the mixed value ─────────────

def test_p02_pure_strategy_minimax_is_not_the_mixed_value() -> None:
    """Costs 1 when red matches our response, 0 otherwise. Pure minimax: every response's worst case is 1, so the
    engine's guaranteed floor is 1 and the pick is decided by order. The mixed-strategy value of this zero-sum game
    is 0.5 (each response with probability 1/2). The engine computes no mixed strategy."""
    costs = [[1.0, 0.0], [0.0, 1.0]]
    pick = _pick(costs, [0.5, 0.5], SelectorStrategy.MINIMAX)
    pure_value = min(max(row[j] for row in costs) for j in range(2))
    mixed_value = 0.5
    reversed_pick = _pick([row[::-1] for row in costs], [0.5, 0.5], SelectorStrategy.MINIMAX)
    print(f"P-02 pure minimax value={pure_value} mixed value={mixed_value} pick={pick} "
          f"pick with columns reversed={reversed_pick} (index 0 both times: tie broken by order)")
    assert pure_value == 1.0
    assert pick == "R0" and reversed_pick == "R0"


# ── P-03: adding a dominated response does not change the pick ───────────────

@pytest.mark.parametrize("case", [REF_A, REF_B], ids=["A", "B"])
def test_p03_a_dominated_response_changes_no_pick(case: tuple) -> None:
    costs, p, expected = case
    # A new last response worse than every existing response in every row.
    worst = [max(row) + 0.05 for row in costs]
    widened = [row + [w] for row, w in zip(costs, worst, strict=True)]
    observed = {rule.value: _pick(widened, p, rule) for rule in RULES}
    print(f"P-03 dominated column {worst} added: expected={expected} observed={observed}")
    assert observed == expected


def test_p03_end_to_end_a_dominated_response_changes_no_pick() -> None:
    """Through evaluate_scenario on the lookup model: a copy of the recommended response made worse on every term
    (higher cost, so more delta-V and no more separation; lower reversibility; slower) is added."""
    base = _real_scenario()
    before = {r: evaluate_scenario(base, r).robust_best_response.id for r in RULES}
    for rule in RULES:
        best = next(f for f in base.friendly_responses if f.id == before[rule])
        worse = dataclasses.replace(best, id="DOM", name="dominated", cost=min(1.0, best.cost + 0.2),
                                    reversibility=max(0.0, best.reversibility - 0.2),
                                    time_to_execute_hours=best.time_to_execute_hours + 4.0)
        widened = dataclasses.replace(base, friendly_responses=[*base.friendly_responses, worse])
        after = evaluate_scenario(widened, rule).robust_best_response.id
        print(f"P-03 end to end {rule.value}: before={before[rule]} after adding a dominated copy={after}")
        assert after == before[rule]


def _real_scenario() -> Scenario:
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
    return Scenario(name="probe", epoch_utc=EPOCH, adversary_actions=rows, friendly_responses=cols)


# ── P-03b: what P means once it is renormalised over the rows entered ────────

def test_p03b_p_is_renormalised_over_the_rows_entered() -> None:
    """Assessor's probe (framework 1a, 1b). A single manoeuvre row entered at P 0.1 and at P 1.0 gives the same
    expected-value pick and the same expected scores: with no residual row, a 10 % likely action is treated as
    certain. Two rows at 0.9 and 0.9 equal two rows at 0.5 and 0.5. A row at P 0 changes nothing."""
    costs = [[0.2, 0.6, 0.4], [0.8, 0.3, 0.55]]
    one_low = _pick(costs[:1], [0.1], SelectorStrategy.EXPECTED_VALUE)
    one_high = _pick(costs[:1], [1.0], SelectorStrategy.EXPECTED_VALUE)
    pair_high = _pick(costs, [0.9, 0.9], SelectorStrategy.EXPECTED_VALUE)
    pair_half = _pick(costs, [0.5, 0.5], SelectorStrategy.EXPECTED_VALUE)
    with_zero = _pick([*costs, [0.0, 0.0, 9.0]], [0.6, 0.4, 0.0], SelectorStrategy.EXPECTED_VALUE)
    base = _pick(costs, [0.6, 0.4], SelectorStrategy.EXPECTED_VALUE)
    # What expected value would pick if P were read as stated, the remainder being "nothing happens" at cost 0.
    stated = [0.1 * c for c in costs[0]]
    print(f"P-03b one row P 0.1 -> {one_low}; P 1.0 -> {one_high}; rows 0.9/0.9 -> {pair_high}; 0.5/0.5 -> "
          f"{pair_half}; P 0 row added -> {with_zero} (base {base}); expected scores if P 0.1 were read as stated "
          f"with a residual nothing-happens row at cost 0: {stated}, versus the engine's {costs[0]}")
    assert one_low == one_high
    assert pair_high == pair_half
    assert with_zero == base


# ── P-04: scaling every payoff by a positive constant changes no choice ──────

@pytest.mark.parametrize("k", [0.01, 3.0, 1000.0])
@pytest.mark.parametrize("case", [REF_A, REF_B], ids=["A", "B"])
def test_p04_positive_scaling_changes_no_choice(case: tuple, k: float) -> None:
    costs, p, expected = case
    scaled = [[k * c for c in row] for row in costs]
    observed = {rule.value: _pick(scaled, p, rule) for rule in RULES}
    print(f"P-04 k={k}: expected={expected} observed={observed}")
    assert observed == expected


def test_p04_end_to_end_scaling_the_weights_changes_nothing() -> None:
    """The panel rescales the weights to sum to one (spectre/web/routes/decision.py:589-594): weights times 7 give the
    same normalised weights, so the same scores and picks."""
    base = (0.35, 0.25, 0.20, 0.10, 0.10)
    scaled = tuple(7.0 * w for w in base)
    a, b = _normalised_weights(*base), _normalised_weights(*scaled)
    print(f"P-04 weights {base} -> {a}; times 7 -> {b}")
    assert a == pytest.approx(b)


# ── P-05: permuting rows or columns changes no result ────────────────────────

@pytest.mark.parametrize("case", [REF_A, REF_B], ids=["A", "B"])
def test_p05_permutations_without_ties_change_no_result(case: tuple) -> None:
    costs, p, expected = case
    n_rows, n_cols = len(costs), len(costs[0])
    seen: set[tuple[str, str, str]] = set()
    for rows in itertools.permutations(range(n_rows)):
        for cols in itertools.permutations(range(n_cols)):
            permuted = [[costs[i][j] for j in cols] for i in rows]
            pp = [p[i] for i in rows]
            observed = {}
            for rule in RULES:
                picked = int(_pick(permuted, pp, rule)[1:])
                observed[rule.value] = f"R{cols[picked]}"
            seen.add(tuple(observed.values()))
            assert observed == expected
    print(f"P-05 case: every row and column permutation gives {expected}; distinct outcomes seen: {seen}")


def test_p05_a_tie_is_broken_by_the_order_responses_were_entered() -> None:
    """Two different responses whose worst cases tie under minimax: X costs 0.5 and 0.1 across the rows, Y costs 0.2
    and 0.5. The engine recommends whichever was entered first, and says nothing of the tie (F-13)."""
    x, y, z = [0.5, 0.1], [0.2, 0.5], [0.9, 0.9]
    as_xy = [[x[i], y[i], z[i]] for i in range(2)]
    as_yx = [[y[i], x[i], z[i]] for i in range(2)]
    first = _pick(as_xy, [0.5, 0.5], SelectorStrategy.MINIMAX)
    second = _pick(as_yx, [0.5, 0.5], SelectorStrategy.MINIMAX)
    named = {"as (X, Y, Z)": {"R0": "X", "R1": "Y"}[first], "as (Y, X, Z)": {"R0": "Y", "R1": "X"}[second]}
    print(f"P-05 tie: worst cases X 0.5, Y 0.5, Z 0.9; recommendation when entered {named}")
    assert named == {"as (X, Y, Z)": "X", "as (Y, X, Z)": "Y"}
