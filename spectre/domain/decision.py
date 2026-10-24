"""Decision Engine — Phase 1: deterministic scenario evaluation.

Evaluates a grid of adversary actions × friendly responses with a lookup model
and a weighted composite scoring function. No orbit is propagated: custody,
closest approach, time to approach and delta-V are rules of thumb and
constants per action type, scaled by the operator's inputs, and they are
uncalibrated against any observed outcome. A selector (minimax by default)
picks the friendly response with the least worst-case cost.

An earlier "TLE refinement" took one instant's separation, could only lower
the estimate, hid every error behind a bare except, and never ran because the
route passed no red element set; it was removed (audit F-111).

Phase 2 (future sprint) will attach a ``ManoeuvreHypothesis`` to
``AdversaryAction`` and wire in the Monte Carlo engine for probabilistic scoring.

Typical use::

    scenario = Scenario(
        name="GEO intercept threat",
        epoch_utc=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
        adversary_actions=[...],
        friendly_responses=[...],
        horizon_hours=72.0,
    )
    result = evaluate_scenario(scenario)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# ── Enumerations ──────────────────────────────────────────────────────────────

class ActionType(Enum):
    MANOEUVRE        = "manoeuvre"
    SENSOR_RETASK    = "sensor_retask"
    POSTURE_CHANGE   = "posture_change"
    NO_ACTION        = "no_action"


class SelectorStrategy(Enum):
    MINIMAX           = "minimax"           # minimise worst-case cost
    EXPECTED_VALUE    = "expected_value"    # minimise expected cost (uses probability)
    # Minimise the BEST-case cost: the optimistic rule, not a robust one. It
    # was labelled MAXIMIN, the name of the cautious rule, so an operator
    # asking for caution got the riskiest response (audit F-S05-01).
    MINIMIN           = "minimin"


#: What every Phase 1 outcome rests on, shown to the operator with the result.
MODELLED_BASIS = (
    "Outcomes are Phase 1 lookup constants and weights, not propagated orbits: "
    "closest approach is a fixed figure per action type scaled by response cost, "
    "time to approach is a fixed fraction of the horizon, and custody follows a "
    "rule of thumb. Use it to compare trade-offs, not as an operational answer."
)


# ── Data classes ──────────────────────────────────────────────────────────────

def _require_fraction(owner: str, field_name: str, value: float) -> None:
    """Refuse a value outside [0, 1], NaN or infinite included (audit F-112)."""
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        raise ValueError(f"{owner}.{field_name} must be in [0, 1]; got {value!r}")


@dataclass
class AdversaryAction:
    """A single adversary COA to evaluate."""

    id:          str
    name:        str
    action_type: ActionType
    probability: float            # [0, 1] — operator assessment
    confidence:  float            # [0, 1] — intelligence confidence
    description: str = ""
    # Phase 2: hypothesis: ManoeuvreHypothesis | None = None

    def __post_init__(self) -> None:
        _require_fraction("AdversaryAction", "probability", self.probability)
        _require_fraction("AdversaryAction", "confidence", self.confidence)


@dataclass
class FriendlyResponse:
    """A single friendly COA to evaluate against each adversary action."""

    id:                   str
    name:                 str
    action_type:          ActionType
    cost:                 float    # Normalised [0, 1] — propellant, ops tempo, etc.
    reversibility:        float    # [0, 1] — 1 = fully reversible
    time_to_execute_hours: float   # Execution latency
    description:          str = ""

    def __post_init__(self) -> None:
        _require_fraction("FriendlyResponse", "cost", self.cost)
        _require_fraction("FriendlyResponse", "reversibility", self.reversibility)
        if not (math.isfinite(self.time_to_execute_hours) and self.time_to_execute_hours >= 0.0):
            raise ValueError(
                f"FriendlyResponse.time_to_execute_hours must be finite and >= 0; "
                f"got {self.time_to_execute_hours!r}"
            )


@dataclass
class OutcomeMetrics:
    """Deterministic outcome metrics for one (adversary_action, friendly_response) pair."""

    custody_maintained:   bool
    custody_gap_hours:    float     # 0 if custody maintained
    closest_approach_km:  float
    time_to_closest_hours: float
    delta_v_cost_km_s:    float    # Friendly ΔV expended
    composite_score:      float    # Higher = worse for friendly
    # Every figure above is a Phase 1 lookup or weighting, not a propagated
    # result. Carried on the data so no consumer can present it as computed.
    modelled:             bool = True

    def __str__(self) -> str:
        cust = "✓" if self.custody_maintained else "✗"
        return (
            f"Custody:{cust}  CA:{self.closest_approach_km:.1f}km  "
            f"ΔV:{self.delta_v_cost_km_s*1000:.1f}m/s  "
            f"Score:{self.composite_score:.3f}"
        )


@dataclass
class Scenario:
    """A what-if scenario: N adversary actions × M friendly responses."""

    name:               str
    epoch_utc:          datetime
    adversary_actions:  list[AdversaryAction]
    friendly_responses: list[FriendlyResponse]
    horizon_hours:      float = 72.0

    # Scoring weights (sum should equal 1)
    w_custody:          float = 0.35    # Penalty for losing custody
    w_closest_approach: float = 0.25    # Reward for maximising CA distance
    w_dv_cost:          float = 0.20    # Penalty for ΔV expenditure
    w_time_to_exec:     float = 0.10    # Penalty for slow response
    w_reversibility:    float = 0.10    # Reward for reversible actions

    def __post_init__(self) -> None:
        # A zero horizon divided by zero in the score (audit F-112).
        if not (math.isfinite(self.horizon_hours) and self.horizon_hours > 0.0):
            raise ValueError(f"Scenario.horizon_hours must be finite and > 0; got {self.horizon_hours!r}")
        for name in ("w_custody", "w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility"):
            _require_fraction("Scenario", name, getattr(self, name))


@dataclass
class ScenarioResult:
    """Evaluated scenario with ranked responses and a robust recommendation."""

    scenario:               Scenario
    # outcome_matrix[i][j] = OutcomeMetrics for (adversary i, friendly j)
    outcome_matrix:         list[list[OutcomeMetrics]]
    # ranked_responses[i][j] = (friendly_response, score) sorted best→worst for adversary i
    ranked_per_adversary:   list[list[tuple[FriendlyResponse, float]]]
    # The robust best response (minimax by default)
    robust_best_response:   FriendlyResponse
    robust_strategy:        SelectorStrategy
    computation_time_s:     float
    # Phase 1 outcomes come from lookup constants, not propagation. The flag
    # and basis travel with the result so the page can say so (audit
    # F-S05-02, and the "modelled estimate" banner agreed in July 2026).
    modelled:               bool = True
    basis:                  str = MODELLED_BASIS

    def summary_table(self) -> str:
        """ASCII summary table for CLI / operator guide output."""
        adv  = self.scenario.adversary_actions
        fr   = self.scenario.friendly_responses
        lines = []
        header = f"{'':25s}" + "".join(f"{r.name[:12]:>13s}" for r in fr)
        lines.append(header)
        lines.append("-" * len(header))
        for i, a in enumerate(adv):
            row = f"{a.name[:24]:<25s}"
            for j in range(len(fr)):
                row += f"{self.outcome_matrix[i][j].composite_score:>13.3f}"
            lines.append(row)
        lines.append("")
        lines.append(
            f"Robust response ({self.robust_strategy.value}): "
            f"{self.robust_best_response.name}"
        )
        return "\n".join(lines)


# ── Scoring ────────────────────────────────────────────────────────────────────

def compute_outcome_metrics(
    adversary: AdversaryAction,
    friendly: FriendlyResponse,
    scenario: Scenario,
) -> OutcomeMetrics:
    """Outcome metrics for one (adversary, friendly) pair, from the lookup model.

    Rules as implemented (Phase 1, uncalibrated)
    --------------------------------------------
    - custody: lost when the adversary manoeuvres and the response is
      NO_ACTION or POSTURE_CHANGE; a MANOEUVRE or SENSOR_RETASK response keeps it
    - custody_gap_hours: when lost, horizon * adversary confidence *
      (1 - friendly.reversibility); against a SENSOR_RETASK response to a
      manoeuvre, half the response's time to execute
    - closest_approach_km: a constant per adversary action type, raised by
      response cost for a MANOEUVRE (x(1 + 5 cost)) or POSTURE_CHANGE
      (x(1 + 2 cost)) response
    - time_to_closest_hours: 0.4 of the horizon
    - delta_v_cost_km_s: friendly.cost * 0.05 for a MANOEUVRE response, else 0
    - composite_score: weighted sum of the normalised terms (higher = worse)
    """
    # ── Custody ──────────────────────────────────────────────────────────────
    adversary_is_manoeuvre = adversary.action_type == ActionType.MANOEUVRE
    friendly_is_active     = friendly.action_type in (ActionType.MANOEUVRE, ActionType.SENSOR_RETASK)

    custody_maintained = True
    custody_gap_hours  = 0.0

    if adversary_is_manoeuvre and not friendly_is_active:
        custody_maintained = False
        # Gap proportional to adversary confidence and horizon
        custody_gap_hours = scenario.horizon_hours * adversary.confidence * (1.0 - friendly.reversibility)
    elif adversary_is_manoeuvre and friendly.action_type == ActionType.SENSOR_RETASK:
        # Sensor retask reduces gap but doesn't eliminate manoeuvre risk
        custody_maintained = True
        custody_gap_hours  = friendly.time_to_execute_hours * 0.5

    # ── Closest approach ─────────────────────────────────────────────────────
    # Phase 1: analytic estimate based on action type pairing
    if adversary.action_type == ActionType.NO_ACTION:
        base_ca_km = 5000.0   # no approach threat
    elif adversary.action_type == ActionType.MANOEUVRE:
        base_ca_km = 200.0    # potential approach
    elif adversary.action_type == ActionType.SENSOR_RETASK:
        base_ca_km = 10000.0  # not a physical threat
    else:
        base_ca_km = 3000.0

    # Friendly response modifies CA distance
    if friendly.action_type == ActionType.MANOEUVRE:
        ca_km = base_ca_km * (1.0 + friendly.cost * 5.0)  # increase separation
    elif friendly.action_type == ActionType.POSTURE_CHANGE:
        ca_km = base_ca_km * (1.0 + friendly.cost * 2.0)
    else:
        ca_km = base_ca_km

    time_to_ca = scenario.horizon_hours * 0.4   # Phase 1: simplified

    # ── ΔV cost ───────────────────────────────────────────────────────────────
    if friendly.action_type == ActionType.MANOEUVRE:
        dv_km_s = friendly.cost * 0.05   # 0–50 m/s range
    else:
        dv_km_s = 0.0

    # ── Composite score (higher = worse) ──────────────────────────────────────
    # Normalise each component to [0, 1] with domain assumptions:
    # - Custody loss: 0 = maintained, 1 = full horizon gap
    # - CA: 0 = 0 km (co-location), 1 = 50 000 km (no threat) — inverted
    # - ΔV: 0 = 0 m/s, 1 = 100 m/s
    # - Execution time: 0 = immediate, 1 = full horizon
    # - Reversibility: 0 = irreversible, 1 = fully reversible — inverted (reward)

    norm_custody  = 0.0 if custody_maintained else min(custody_gap_hours / scenario.horizon_hours, 1.0)
    norm_ca       = 1.0 - min(ca_km / 50_000.0, 1.0)   # high CA = low score (good)
    norm_dv       = min(dv_km_s / 0.1, 1.0)
    norm_time     = min(friendly.time_to_execute_hours / scenario.horizon_hours, 1.0)
    norm_rev      = 1.0 - friendly.reversibility          # reward reversibility → lower score

    composite = (
        scenario.w_custody          * norm_custody
        + scenario.w_closest_approach * norm_ca
        + scenario.w_dv_cost          * norm_dv
        + scenario.w_time_to_exec     * norm_time
        + scenario.w_reversibility    * norm_rev
    )

    return OutcomeMetrics(
        custody_maintained=custody_maintained,
        custody_gap_hours=round(custody_gap_hours, 2),
        closest_approach_km=round(ca_km, 1),
        time_to_closest_hours=round(time_to_ca, 2),
        delta_v_cost_km_s=round(dv_km_s, 5),
        composite_score=round(composite, 6),
    )


# ── Response ranking ──────────────────────────────────────────────────────────

def rank_responses(
    adversary_idx: int,
    friendly_responses: list[FriendlyResponse],
    outcome_row: list[OutcomeMetrics],
) -> list[tuple[FriendlyResponse, float]]:
    """Sort friendly responses best→worst for a single adversary action.

    Best = lowest composite score.
    """
    pairs = [(fr, om.composite_score) for fr, om in zip(friendly_responses, outcome_row, strict=True)]
    return sorted(pairs, key=lambda x: x[1])


def find_robust_response(
    scenario: Scenario,
    outcome_matrix: list[list[OutcomeMetrics]],
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
) -> FriendlyResponse:
    """Select the robust best response across all adversary actions.

    Parameters
    ----------
    scenario:
        The evaluated scenario.
    outcome_matrix:
        outcome_matrix[i][j] for adversary i, friendly j.
    strategy:
        MINIMAX  — minimise the maximum (worst-case) composite score.
        EXPECTED_VALUE — minimise expected score weighted by adversary probabilities.
        MINIMIN  — minimise the minimum (best-case) composite score: optimistic,
                   not robust.

    Returns
    -------
    The ``FriendlyResponse`` that is robust under the chosen strategy.
    """
    n_adversary = len(scenario.adversary_actions)
    n_friendly  = len(scenario.friendly_responses)

    if n_friendly == 0:
        raise ValueError("No friendly responses to select from")

    scores = [0.0] * n_friendly

    if strategy == SelectorStrategy.MINIMAX:
        for j in range(n_friendly):
            scores[j] = max(outcome_matrix[i][j].composite_score for i in range(n_adversary))
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    elif strategy == SelectorStrategy.EXPECTED_VALUE:
        total_p = sum(a.probability for a in scenario.adversary_actions)
        if total_p <= 0:
            total_p = 1.0
        for j in range(n_friendly):
            scores[j] = sum(
                (scenario.adversary_actions[i].probability / total_p) * outcome_matrix[i][j].composite_score
                for i in range(n_adversary)
            )
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    else:  # MINIMIN: minimise the best-case score, the optimistic rule
        for j in range(n_friendly):
            scores[j] = min(outcome_matrix[i][j].composite_score for i in range(n_adversary))
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    return scenario.friendly_responses[best_j]


# ── Top-level evaluation ───────────────────────────────────────────────────────

def evaluate_scenario(
    scenario: Scenario,
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
) -> ScenarioResult:
    """Evaluate all (adversary × friendly) combinations and return a ranked result.

    Parameters
    ----------
    scenario:
        Fully populated Scenario dataclass.
    strategy:
        Selector strategy for the robust recommendation.

    Returns
    -------
    ScenarioResult with full outcome matrix, per-adversary rankings, and the
    robust best response.
    """
    if not scenario.adversary_actions:
        raise ValueError("Scenario must have at least one adversary action")
    if not scenario.friendly_responses:
        raise ValueError("Scenario must have at least one friendly response")

    t0 = time.monotonic()

    # Build outcome matrix
    outcome_matrix: list[list[OutcomeMetrics]] = []
    for adversary in scenario.adversary_actions:
        row: list[OutcomeMetrics] = []
        for friendly in scenario.friendly_responses:
            metrics = compute_outcome_metrics(adversary, friendly, scenario)
            row.append(metrics)
        outcome_matrix.append(row)

    # Rank per adversary action
    ranked_per_adversary = [
        rank_responses(i, scenario.friendly_responses, outcome_matrix[i])
        for i in range(len(scenario.adversary_actions))
    ]

    # Robust selection
    robust_response = find_robust_response(scenario, outcome_matrix, strategy)

    wall_time = time.monotonic() - t0

    return ScenarioResult(
        scenario=scenario,
        outcome_matrix=outcome_matrix,
        ranked_per_adversary=ranked_per_adversary,
        robust_best_response=robust_response,
        robust_strategy=strategy,
        computation_time_s=round(wall_time, 4),
    )
