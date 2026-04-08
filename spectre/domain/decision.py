"""Decision Engine — Phase 1: deterministic scenario evaluation.

Evaluates a grid of adversary actions × friendly responses using deterministic
SGP4 propagation and a weighted composite scoring function.  A minimax selector
identifies the "robust" friendly response that minimises worst-case cost across
all adversary actions.

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
    result = evaluate_scenario(scenario, blue_tle="...", red_tle="...")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger(__name__)

# Earth radius (km) — used for GCA (ground closest approach) estimates
_R_EARTH_KM = 6371.0


# ── Enumerations ──────────────────────────────────────────────────────────────

class ActionType(Enum):
    MANOEUVRE        = "manoeuvre"
    SENSOR_RETASK    = "sensor_retask"
    POSTURE_CHANGE   = "posture_change"
    NO_ACTION        = "no_action"


class SelectorStrategy(Enum):
    MINIMAX           = "minimax"           # minimise worst-case cost
    EXPECTED_VALUE    = "expected_value"    # minimise expected cost (uses probability)
    MAXIMIN           = "maximin"           # maximise worst-case benefit


# ── Data classes ──────────────────────────────────────────────────────────────

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


@dataclass
class OutcomeMetrics:
    """Deterministic outcome metrics for one (adversary_action, friendly_response) pair."""

    custody_maintained:   bool
    custody_gap_hours:    float     # 0 if custody maintained
    closest_approach_km:  float
    time_to_closest_hours: float
    delta_v_cost_km_s:    float    # Friendly ΔV expended
    composite_score:      float    # Higher = worse for friendly

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
    blue_tle: str | None = None,
    red_tle: str | None = None,
) -> OutcomeMetrics:
    """Compute deterministic outcome metrics for one (adversary, friendly) pair.

    Phase 1 uses a simplified analytic model since full SGP4 propagation
    requires TLE strings.  When both ``blue_tle`` and ``red_tle`` are supplied,
    closest-approach estimation uses the TLE epoch separation as a proxy.

    Scoring model (Phase 1)
    -----------------------
    - custody_maintained: True unless adversary is a MANOEUVRE and friendly is NO_ACTION
    - custody_gap_hours: 0 if maintained, else horizon * (1 - friendly.reversibility)
    - closest_approach_km: modelled by action type and response combination
    - delta_v_cost_km_s: 0 for non-manoeuvre responses, else friendly.cost * 0.05
    - composite_score: weighted sum (higher = worse for friendly)
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

    # TLE-based refinement (Phase 1.5): if TLEs supplied, use epoch delta as a
    # proxy for current conjunction geometry
    if blue_tle and red_tle:
        try:
            from spectre.astro.propagator import TLEOrbit
            blue_orbit = TLEOrbit(blue_tle)
            red_orbit  = TLEOrbit(red_tle)
            # Use propagation difference at horizon midpoint as geometry hint
            t_mid_min  = scenario.horizon_hours * 30.0
            blue_sv = blue_orbit.propagate(scenario.epoch_utc, t_mid_min)
            red_sv  = red_orbit.propagate(scenario.epoch_utc, t_mid_min)
            import math
            sep = math.sqrt(sum(
                (blue_sv.position_km[i] - red_sv.position_km[i]) ** 2
                for i in range(3)
            ))
            if sep > 0:
                # Scale analytic CA by ratio of actual/typical separation
                ca_km = min(ca_km, sep * friendly.reversibility + base_ca_km * (1.0 - friendly.reversibility))
        except Exception:
            pass   # Fall back to analytic estimate

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
    pairs = [(fr, om.composite_score) for fr, om in zip(friendly_responses, outcome_row)]
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
        MAXIMIN  — maximise the minimum (best-case) composite score.

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

    else:  # MAXIMIN — maximise best-case score (here: minimise min score)
        for j in range(n_friendly):
            scores[j] = min(outcome_matrix[i][j].composite_score for i in range(n_adversary))
        best_j = min(range(n_friendly), key=lambda j: scores[j])

    return scenario.friendly_responses[best_j]


# ── Top-level evaluation ───────────────────────────────────────────────────────

def evaluate_scenario(
    scenario: Scenario,
    blue_tle: str | None = None,
    red_tle: str | None = None,
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
) -> ScenarioResult:
    """Evaluate all (adversary × friendly) combinations and return a ranked result.

    Parameters
    ----------
    scenario:
        Fully populated Scenario dataclass.
    blue_tle:
        Two-line element string for the friendly (blue) object (optional).
    red_tle:
        Two-line element string for the adversary (red) object (optional).
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
            metrics = compute_outcome_metrics(adversary, friendly, scenario, blue_tle, red_tle)
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
