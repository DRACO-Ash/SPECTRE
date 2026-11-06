"""Probes P-06 to P-10: vetoes, tree consistency, the Bayesian update and collect first.

Framework references: section 1b (compensatory aggregation, gate G4), 1d (tree against matrix, pruning), 1e
(Bayesian updating), 1f (value of information), section 2 table; probes 6 to 10 of the evaluation brief.

Every probe prints what it measured, so evidence/probes.log holds the numbers whether a probe passes or fails.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    SelectorStrategy,
    Seen,
    ThreatPicture,
    evaluate_scenario,
)
from spectre.domain.decision_tree import MAX_TREE_BRANCHES, branches, evaluate_tree
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Advice, Cue, Dimension, Understanding, collection_advice
from spectre.domain.turn_update import posteriors
from tests.unit.test_decision_sampled import _binding
from tests.unit.test_decision_sampled import _scenario as _bound_rows
from tests.unit.test_threat_understanding_cues import _CASES

EPOCH = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
RULES = (SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE)


def _rows(p: list[float]) -> list[AdversaryAction]:
    return [AdversaryAction(id=f"A{i}", name=f"A{i}", action_type=ActionType.MANOEUVRE, probability=pi,
                            confidence=0.5) for i, pi in enumerate(p)]


def _lookup_scenario(**changes: object) -> Scenario:
    cols = [
        FriendlyResponse(id="F0", name="do nothing", action_type=ActionType.NO_ACTION, cost=0.0, reversibility=1.0,
                         time_to_execute_hours=0.0),
        FriendlyResponse(id="F1", name="retask sensor", action_type=ActionType.SENSOR_RETASK, cost=0.2,
                         reversibility=0.9, time_to_execute_hours=2.0),
        FriendlyResponse(id="F2", name="manoeuvre", action_type=ActionType.MANOEUVRE, cost=0.4, reversibility=0.5,
                         time_to_execute_hours=6.0),
    ]
    base = Scenario(name="probe", epoch_utc=EPOCH, adversary_actions=_rows([0.6, 0.4]), friendly_responses=cols)
    return dataclasses.replace(base, **changes)


# ── P-06: a response that violates a hard constraint is never recommended ────

def test_p06_no_veto_can_be_expressed() -> None:
    """Gate G4. The probe cannot be written as specified: no field on FriendlyResponse or Scenario marks a response
    as unacceptable, so there is nothing to veto with. The probe records the fields that exist, and shows the best
    score is recommended whatever the response is."""
    response_fields = [f.name for f in dataclasses.fields(FriendlyResponse)]
    scenario_fields = [f.name for f in dataclasses.fields(Scenario)]
    words = ("veto", "constraint", "forbid", "allowed", "permitted", "roe", "unacceptable", "lawful")
    hits = [f for f in response_fields + scenario_fields if any(w in f.lower() for w in words)]
    result = evaluate_scenario(_lookup_scenario(), SelectorStrategy.MINIMAX)
    print(f"P-06 FriendlyResponse fields={response_fields}; Scenario fields={scenario_fields}; "
          f"constraint-like fields={hits}; minimax recommends {result.robust_best_response.name}, chosen on score alone")
    assert hits == []


# ── P-07: tree depth 1 equals the matrix; pruning ────────────────────────────

@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.value)
def test_p07_depth_one_equals_the_matrix(rule: SelectorStrategy) -> None:
    s = _lookup_scenario()
    matrix = evaluate_scenario(s, rule)
    tree = evaluate_tree(s, rule)
    scores_m = [[c.composite_score for c in row] for row in matrix.outcome_matrix]
    scores_t = [[c.composite_score for c in row] for row in tree.outcome_matrix]
    print(f"P-07 {rule.value}: matrix pick {matrix.robust_best_response.id}, depth-1 tree pick "
          f"{tree.robust_best_response.id}; scores equal: {scores_m == scores_t}")
    assert matrix.robust_best_response.id == tree.robust_best_response.id
    assert scores_m == scores_t


def test_p07_an_unbound_two_turn_tree_is_refused_and_the_matrix_stands() -> None:
    s = _lookup_scenario(turns=2)
    one = evaluate_scenario(dataclasses.replace(s, turns=1))
    two = evaluate_tree(s)
    refusal = None if two.tree is None else two.tree.refusal
    print(f"P-07 two turns, unbound: refusal={refusal!r}; pick {two.robust_best_response.id} against one-turn "
          f"{one.robust_best_response.id}")
    assert refusal
    assert two.robust_best_response.id == one.robust_best_response.id


def test_p07_no_pruning_full_enumeration_is_counted() -> None:
    """There is no pruning to compare against: the tree enumerates every branch under a cap. Recorded: the branch
    count formula and the cap (spectre/domain/decision_tree.py:121, :363-365)."""
    counts = {(r, f, t): branches(r, f, t) for r, f, t in ((2, 3, 2), (3, 3, 3), (5, 5, 2))}
    print(f"P-07 branches(rows, responses, turns)={counts}; cap {MAX_TREE_BRANCHES}")
    assert counts[(2, 3, 2)] == 6 + 36
    assert counts[(3, 3, 3)] == 9 + 81 + 729


# ── P-08: the posterior against a hand computation; numerics ─────────────────

def test_p08_posterior_matches_a_hand_computation() -> None:
    """Rows P 0.5, 0.3, 0.2; rows 0 and 1 show a burn, row 2 shows no burn. Seeing a burn, Bayes with a 0 or 1
    likelihood gives 0.5 / 0.8 = 0.625 and 0.3 / 0.8 = 0.375, and 0 for row 2."""
    s = _lookup_scenario(adversary_actions=_rows([0.5, 0.3, 0.2]))
    gives = (Seen.BURN, Seen.BURN, Seen.NO_BURN)
    post = {p.seen: p for p in posteriors(s, gives)}
    shares = post[Seen.BURN].shares
    print(f"P-08 shares after a burn: {shares}; line: {post[Seen.BURN].line}")
    assert shares[0] == pytest.approx(0.625) and shares[1] == pytest.approx(0.375)
    assert shares[2] is None


def test_p08_tiny_priors_do_not_underflow() -> None:
    """A single observation enters, so a long sequence cannot be entered; tiny priors are the numerical stress."""
    s = _lookup_scenario(adversary_actions=_rows([1e-300, 1e-300, 0.0]))
    gives = (Seen.BURN, Seen.BURN, Seen.BURN)
    shares = {p.seen: p.shares for p in posteriors(s, gives)}
    burn = shares[Seen.BURN]
    print(f"P-08 priors 1e-300, 1e-300, 0: shares after a burn {burn}")
    assert all(x is None or math.isfinite(x) for x in burn)


# ── P-09: a duplicated observation ───────────────────────────────────────────

def test_p09_an_observation_cannot_be_entered_twice() -> None:
    """Scenario.observed holds one Seen (spectre/domain/decision.py:1449-1452); a second copy cannot be entered, so
    the posterior cannot move twice for one event."""
    with pytest.raises(ValueError) as raised:
        _lookup_scenario(observed=[Seen.BURN, Seen.BURN])
    print(f"P-09 two copies of one observation refused: {raised.value}")


# ── P-10: value of information, recast (no EVPI or EVSI exists) ──────────────

def test_p10_cue_value_is_never_negative_and_never_exceeds_the_range() -> None:
    """The analogue of EVSI no greater than EVPI for a range measure: a cue's steps lie between 0 and the width of
    the range it narrows (spectre/domain/threat_understanding.py:1909-1922). Checked on every worked-example case
    the repository's own tests use."""
    checked = []
    for items, situation in _CASES:
        now = tu.threat_range(items, situation)
        width = int(now.ceiling) - int(now.floor)
        for cue in tu.cues(items, situation):
            checked.append((cue.observation[:30], cue.steps, width))
            assert 0 <= cue.steps <= width
    print(f"P-10 cues checked (observation, steps, range width): {checked}")
    assert checked


def _cue(hours: float) -> Cue:
    return Cue(observation="probe collection", dimensions=(Dimension.BEHAVIOUR,), steps=2, hours=hours,
               effect="could settle it", benign=(Band.LOW, Band.MEDIUM), hostile=(Band.HIGH, Band.CRITICAL))


def test_p10_delay_changes_the_advice() -> None:
    """A cue taking 4 h: with decide-by 10 h away it is collected first; with decide-by 3 h away the advice is to act
    on the ceiling. The deadline is a hard cut-off; there is no continuous cost of delay."""
    span = (Band.LOW, Band.CRITICAL)
    early = collection_advice(span, (_cue(4.0),), now=EPOCH, decide_at=EPOCH + timedelta(hours=10))
    late = collection_advice(span, (_cue(4.0),), now=EPOCH, decide_at=EPOCH + timedelta(hours=3))
    print(f"P-10 decide-by in 10 h: {early.advice.name}: {early.sentence}")
    print(f"P-10 decide-by in 3 h: {late.advice.name}: {late.sentence}")
    assert early.advice is Advice.COLLECT_FIRST
    assert late.advice is Advice.ACT_ON_CEILING


def test_p10_collect_first_cannot_change_the_engines_recommendation() -> None:
    """F-14. The same bound scenario evaluated with two threat pictures: one straddling the action line with a cue
    that lands in time (collect first), and one entirely at CRITICAL (act on the ceiling). If the threat range can
    change the recommendation, the outcome matrix or the pick should differ between them."""
    base = dataclasses.replace(_bound_rows(binding=_binding()), epoch_utc=EPOCH)
    red = base.binding.red.stk_name  # type: ignore[union-attr]
    straddle = ThreatPicture(red=red, floor=Band.LOW, ceiling=Band.CRITICAL, understanding=Understanding.LOW,
                             cues=(_cue(1.0),), decide_at=EPOCH + timedelta(hours=10))
    critical = ThreatPicture(red=red, floor=Band.CRITICAL, ceiling=Band.CRITICAL, understanding=Understanding.HIGH,
                             cues=(), decide_at=EPOCH + timedelta(hours=10))
    seen = {}
    for name, picture in (("straddle", straddle), ("critical", critical)):
        r = evaluate_scenario(dataclasses.replace(base, threat=picture), SelectorStrategy.MINIMAX)
        seen[name] = (r.collection.advice.name if r.collection else None, r.robust_best_response.id,
                      [[c.composite_score for c in row] for row in r.outcome_matrix])
    print(f"P-10 straddle: advice {seen['straddle'][0]}, pick {seen['straddle'][1]}; critical: advice "
          f"{seen['critical'][0]}, pick {seen['critical'][1]}; matrices identical: "
          f"{seen['straddle'][2] == seen['critical'][2]}")
    assert seen["straddle"][0] == "COLLECT_FIRST" and seen["critical"][0] == "ACT_ON_CEILING"
    assert seen["straddle"][1:] == seen["critical"][1:]
