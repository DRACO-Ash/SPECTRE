"""Decision Engine: scenario evaluation, from lookups and a sampled or computed closest approach.

Evaluates a grid of adversary actions × friendly responses with a lookup model
and a weighted composite scoring function. Delta-V, and custody, closest
approach and time to approach unless sampled or computed below, are rules of
thumb and constants per action type, scaled by the operator's inputs, and they
are uncalibrated against any observed outcome. A selector (minimax by default) picks the friendly response with the
least worst-case cost.

Every figure in a cell states its own basis (lookup, sampled or computed),
and the score's basis is derived from the figures it uses, never stronger
than lookup while its weights are rules of thumb (SPC-101).

An earlier "TLE refinement" took one instant's separation, could only lower
the estimate, hid every error behind a bare except, and never ran because the
route passed no red element set; it was removed (audit F-111).

A scenario may be bound to a held red track and blue asset (SPC-100). The
binding names the real objects the scenario is about and carries their element
sets, their epochs and their ages at evaluation. It is shown with the result
and goes into its provenance; the sampled and computed paths below read it.

An adversary action may carry a manoeuvre hypothesis (SPC-111): how the
adversary might move, taken from an archetype in the Monte Carlo table, a
delta-V and RIC direction the operator entered, or a manoeuvre detected in the
object's element-set history. It travels with its source, the archetype's name
and the direction's frame and basis, so a reader can tell an assumed direction
from a measured one (audit F-104), and it is checked when it is built. It goes
into the result's provenance and the scenario's recorded value, and on its own
changes no figure.

When a row's action carries a hypothesis and the scenario is bound on both
sides, that row's closest approach is sampled (SPC-112): plan_sampling runs
the Monte Carlo engine's separation series against the blue asset, and every
cell of the row scores on P5 of the sampled misses, the smallest-miss tail,
with its time to closest approach the earliest at or below P5. Every other
figure, and every other row, is still a lookup. A row that cannot be sampled
honestly (too few samples, an out-of-date orbit, a hypothesis built from
another element set, a failed or unconverged series, or a scenario over the
cost cap) is refused with a sentence in each of its cells and keeps its lookups.

A sampled evaluation may run under a RunControl (SPC-113): one wall-time
budget across its rows, a stop that names why it is no longer wanted, and a
progress callback. The web layer runs it as a session job the page polls, so
no request waits for it. A row the budget does not cover is refused, naming
the budget; a stop ends the evaluation with EvaluationStoppedError and no
result. Without a RunControl, evaluation is exactly as before.

A sampled cell also carries how closely its percentiles are known and the
composite score's spread across its samples (SPC-115); the score's basis stays
lookup.

When the scenario is bound on both sides, a row whose action does not move
red (no action, a sensor retask, a posture change) and carries no hypothesis
has its closest approach and time computed (SPC-120): plan_computed propagates
both bound orbits by SGP4 from their element sets with no burn, over the part
of the horizon both are within their limits, through the shared helper. The
figure belongs to the pair, one search shared by every computed row and
response, since our response is not applied to the blue orbit yet. A
manoeuvre with no hypothesis names no burn, so it stays a lookup and says why;
a stale orbit or a failed SGP4 instant refuses the figure. One figure never
mixes propagators: computed is SGP4 on both objects, sampled RK45 on both, and
a matrix holding both states the measured gap between the two. The panel builds a hypothesis from the bound red track's state at a
burn time counted from the scenario epoch (SPC-114): pre_manoeuvre_state,
with_spread and burn_line serve it.

When the bound red track carries its custody status as the sweep judges it
(SPC-018, read by the web layer), every row's custody and gap are that status
carried over the horizon on the assumption that no newer element set arrives
(SPC-123): lost from the earliest of the epoch, if lost already, the moment
the newest element set passes its limit, and a hypothesised burn newer than
it. Each gap is an upper bound, with basis computed, and the same for every
response in a row, since our response is not applied to custody yet. A
manoeuvre with no hypothesis names no burn time, so its custody takes the
worst case, a burn at the scenario epoch, as a lookup, unless custody is lost
from the epoch already, which no burn time can change. Degraded custody can
judge the warning time but not whether a burn is normal, and the operator's
custody needs both, so it is neither held nor lost: it stays degraded until
held custody would be lost, and each hour of it carries
DEGRADED_CUSTODY_WEIGHT of the custody penalty an hour lost carries, the
owner's ruling of 2026-11-05 (SPC-179). The custody gap counts lost hours
only. Without a red status the rule of thumb stays.

The lookup constants retire wherever a computed or sampled figure exists
(SPC-125): beside a computed or sampled closest approach, a response that
does not burn spends 0 m/s against the same no-burn blue orbit, not the
cost x 0.05 rule, and the lookup model's public entry, compute_outcome_metrics,
refuses a bound scenario. The per-type distances, 0.4 of the horizon, the
rule-of-thumb custody and the cost x 0.05 delta-V stay for an unbound
scenario, and wherever nothing is computed or sampled, labelled as lookups.

A scenario bound to a red track may carry the Threat picture the sweep held
for it (SPC-171): its range, Understanding, cues and decide-by. It moves no
figure. It gives the collect-first advice of the Threat Understanding
concept, section 4.10, only for a cue whose outcomes give different
recommended responses, the matrix built again under each outcome's picture
through the same cell step from the evaluation's plans, which hold no
picture (SPC-204, evaluation F-14): the matrix reads no Threat band, so none
does, and the advice says a collection would narrow the range but cannot
change the recommendation, beside the sweep's own advice to act on the
ceiling too. A collect-first row is listed for each such cue that needs an
analyst or a sensor; the picture is shown beside the probability and
confidence, which it never fills; and under expected value it says when the
probability has not been earned and what minimax would recommend.

P is the chance of each adversary action, the actions mutually exclusive (SPC-203, evaluation F-12): the rows' P
sum to at most 1, within P_SUM_TOLERANCE, and the scenario refuses more. When they sum below 1, with_remainder adds
the engine's own row last, "No adversary action (remainder of P)", a no-action row at the rest of P, which every rule,
the tree and the record read. A scenario read from a record 0.28.0 or 0.29.0 wrote keeps the rule it was evaluated
under, ProbabilityRule.SHARES: each row weighed by its P over the rows' sum, with no remainder.

A scenario may run 2 or 3 turns (SPC-140): spectre/domain/decision_tree.py's evaluate_tree builds the game tree
beside the matrix, which is its turn 1, and puts every computed cell on RK45 for both orbits even when nothing burns,
so no figure in a tree is SGP4. evaluate_scenario evaluates one turn, as before, and carries no tree.

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

import dataclasses
import itertools
import json
import logging
import math
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Protocol, cast

import numpy as np

from spectre.astro.along_track import ERROR_MODEL_WORDS, error_rate_words, regime_basis
from spectre.astro.closest_approach import ClosestApproach
from spectre.astro.elset_approach import (
    ElsetApproach,
    ElsetFailure,
    elset_closest_approach,
    elset_position_error_km,
)
from spectre.astro.monte_carlo import (
    _MIN_CONVERGENCE_SAMPLES,
    MANOEUVRE_ARCHETYPES,
    REENTRY_FLOOR_KM,
    BlueBurn,
    BlueTrack,
    BurnSeries,
    ElsetError,
    ManoeuvreHypothesis,
    ManoeuvreType,
    SeparationSeries,
    SeparationWindow,
    Tick,
    _ric_split,
    confirmed,
    elset_state,
    handover_words,
    hypothesis_from_tle_record,
    integrator_error_words,
    rk45_sgp4_gap_km,
    run_separation_series,
    second_seed,
    separation_integration_s,
)
from spectre.astro.response_burn import (
    MAX_SIZING_TRIALS,
    RESPONSE_PROPAGATOR,
    BurnAxis,
    BurnRefusal,
    BurnRequest,
    Rk45Plan,
    SizedBurn,
    SizingTick,
    elset_response_plan,
    hypothesis_response_plan,
)
from spectre.domain.custody import BASIS as CUSTODY_BASIS
from spectre.domain.custody import (
    Custody,
    CustodyOverHorizon,
    CustodyStatus,
    Horizon,
    age_text,
    custody_over_horizon,
    span_text,
)
from spectre.domain.decision_envelope import envelope_lines
from spectre.domain.decision_figures import (
    COMPUTED_ELSET,
    COMPUTED_ELSET_LINE,
    ELSET_MODEL,
    NOMINAL_BURN,
    SAMPLED_ELSET,
    SAMPLED_ELSET_LINE,
    ElsetErrorAt,
    ResponseBurnSpec,
    ResponseFigure,
    TcaHistogram,
    TcaUncertainty,
    lower_edge_km,
    tca_histogram,
    tca_uncertainty,
)
from spectre.domain.decision_transfer import (
    MAX_BURN_M_S,
    RowBurns,
    TransferBurn,
    require_transfer,
    row_burns,
    transfer_sentence,
)
from spectre.domain.manoeuvre_calibration import from_km_s, to_km_s
from spectre.domain.provenance import (
    Basis,
    FigureBasis,
    InputRef,
    Provenance,
    provenance,
    tle_input,
    value_input,
    weakest,
)
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import (
    Advice,
    CollectionAdvice,
    Cue,
    Understanding,
    collection_advice,
    landing_cues,
)

if TYPE_CHECKING:
    from spectre.astro.pattern_of_life import Manoeuvre, TLERecord
    from spectre.domain.decision_judgement import JudgementLine, ResponseInputs, RowInputs
    from spectre.domain.decision_tree import GameTree
    from spectre.domain.notso_prior import NotsoPrior

logger = logging.getLogger(__name__)

# ── Enumerations ──────────────────────────────────────────────────────────────

class ActionType(Enum):
    MANOEUVRE        = "manoeuvre"
    SENSOR_RETASK    = "sensor_retask"
    POSTURE_CHANGE   = "posture_change"
    NO_ACTION        = "no_action"


class ProbabilityRule(StrEnum):
    """What the rows' P mean to expected value (SPC-203, evaluation F-12).

    REMAINDER: each P is the chance of its action, the actions mutually exclusive, so the rows' P sum to at most 1
    and the rest is no adversary action, which the engine weighs as a row of its own. SHARES: the rule of 0.28.0 and
    0.29.0, each row weighed by its P over the rows' sum, with no remainder; it is read only from a record those
    releases wrote, so the replay evaluates it as it was evaluated then.
    """

    REMAINDER = "remainder"
    SHARES = "shares"


class MissRule(StrEnum):
    """What a closest approach the engine propagates holds of the element sets' own error (SPC-202, evaluation F-11).

    ELSET_ERROR: each sample of a sampled cell draws both objects' element-set error along track, and a computed cell
    carries a band, the miss less and plus both sets' error at the closest approach in quadrature, its score reading
    the lower edge. POINT: the rule of 0.28.0 to 0.31.0, a computed miss scored as it stands and a sampled band over
    the burn's spread alone; it is read only from a record those releases wrote, so the replay evaluates it as it
    was evaluated then.
    """

    ELSET_ERROR = "element-set error"
    POINT = "point"


class TurnRule(StrEnum):
    """How a game tree splits the span searched into turns (design D3; SPC-187, the owner's ruling of 2026-11-05).

    BURNS: the engine sets each turn from the rows' burn times, so every burn falls inside its own turn, a transfer's
    burns one to a turn; the operator never sets a length (spectre.domain.turn_update.turn_plan). EQUAL: the rule
    of 0.23.0 to 0.36.0, equal turns, a row of several burns refusing the tree; it is read only from a record those
    releases wrote, so the replay builds its tree as it was built then.
    """

    BURNS = "burns"
    EQUAL = "equal"


class TreeCap(StrEnum):
    """Which cost cap a game tree is checked against before it runs (design D6; SPC-188, the owner's ruling of
    2026-11-05 to measure trees under load and set their own cap).

    OWN: the tree's own cap, spectre.domain.decision_tree.MAX_TREE_SAMPLE_HOURS, set from trees measured under load.
    SHARED: the rule of 0.23.0 to 0.37.0, the matrix's cap, MAX_SAMPLE_HOURS, which the tree shared; it is read only
    from a record those releases wrote, so the replay refuses or builds its tree as it did then.
    """

    OWN = "own"
    SHARED = "shared"


class ConvergenceRule(StrEnum):
    """How many draws a sampled row's convergence is checked on (SPC-224, evaluation F-35).

    TWO_SEEDS: the row's series is drawn on its hypothesis's own seed, whose figures are shown, and again on
    monte_carlo.second_seed of it, and is converged only when both draws are; when they disagree the row is not
    converged and is not sampled. Each sampled row is charged twice against the sample-hour cap. ONE_SEED: the rule of
    0.28.0 to 0.41.0, convergence judged on the one draw; it is read only from a record those releases wrote, so the
    replay samples it as it was sampled then.
    """

    TWO_SEEDS = "two seeds"
    ONE_SEED = "one seed"


class SelectorStrategy(Enum):
    MINIMAX           = "minimax"           # minimise worst-case cost
    EXPECTED_VALUE    = "expected_value"    # minimise expected cost (uses probability)
    # Minimise the BEST-case cost: the optimistic rule, not a robust one. It
    # was labelled MAXIMIN, the name of the cautious rule, so an operator
    # asking for caution got the riskiest response (audit F-S05-01).
    MINIMIN           = "minimin"


_MODELLED = (
    "Outcomes are lookup constants and weights, not propagated orbits: "
    "closest approach is a fixed figure per action type scaled by response cost, "
    "time to approach is a fixed fraction of the horizon, and custody {custody}. "
    "Use it to compare trade-offs, not as an operational answer."
)
#: What an outcome rests on when every figure is a lookup, shown to the operator with the result.
MODELLED_BASIS = _MODELLED.format(custody="follows a rule of thumb")
#: MODELLED_BASIS when every figure is a lookup but custody is the worst case, not the rule of thumb (SPC-123).
WORST_CASE_BASIS = _MODELLED.format(
    custody="takes the worst case, a burn at the scenario epoch, since no manoeuvre names a burn time",
)
#: A single cell's MODELLED_BASIS when its custody is the worst case (SPC-123).
WORST_CASE_CELL_BASIS = _MODELLED.format(
    custody="takes the worst case, a burn at the scenario epoch, since this manoeuvre names no burn time",
)
#: Follows MODELLED_BASIS on the result when neither side is bound: what binding would earn.
BIND_TO_EARN = (
    "Bind a red track and a blue asset to compute the closest approach of a row whose action does not move the "
    "red track, or to sample one that carries a manoeuvre hypothesis."
)
#: BIND_TO_EARN once the red track is bound: only the blue asset is still to bind (SPC-119).
BIND_BLUE_TO_EARN = (
    "Bind a blue asset to compute the closest approach of a row whose action does not move the red track, or to "
    "sample one that carries a manoeuvre hypothesis."
)
#: BIND_TO_EARN once the blue asset is bound: only the red track is still to bind (SPC-119).
BIND_RED_TO_EARN = (
    "Bind a red track to compute the closest approach of a row whose action does not move it, or to sample one "
    "that carries a manoeuvre hypothesis."
)
#: Follows MODELLED_BASIS on the result when both sides are bound and every row was refused: binding is done.
EVERY_ROW_REFUSED = "Both orbits are bound, but no closest approach could be computed or sampled: each cell says why."


# ── Figure bases ──────────────────────────────────────────────────────────────

#: The figures composite_score is built from, read off its formula: norm_custody uses custody_maintained and
#: custody_gap_hours, and the hours custody is degraded (SPC-179), which are not a figure of their own but share
#: custody's basis; norm_ca closest_approach_km, norm_dv delta_v_cost_km_s. time_to_closest_hours is not used.
_SCORE_INPUTS: tuple[str, ...] = ("custody_maintained", "custody_gap_hours", "closest_approach_km", "delta_v_cost_km_s")
#: The weights and the scales (closest approach from the keep-out distance to 50,000 km, our delta-V up to the
#: 1,000 m/s per-burn limit, SPC-191) are rules of thumb, so the score is never stronger than lookup, whatever its
#: figures are. Citing the weights (SPC-151) does not change this.
_SCORING_RULE_KIND: Basis = Basis.LOOKUP


@dataclass(frozen=True)
class OutcomeBases:
    """What each figure of one cell rests on, one :class:`FigureBasis` per OutcomeMetrics figure."""

    custody_maintained:    FigureBasis
    custody_gap_hours:     FigureBasis
    closest_approach_km:   FigureBasis
    time_to_closest_hours: FigureBasis
    delta_v_cost_km_s:     FigureBasis
    composite_score:       FigureBasis

    def __post_init__(self) -> None:
        ceiling = weakest(_SCORING_RULE_KIND, *(getattr(self, name).kind for name in _SCORE_INPUTS))
        if self.composite_score.kind != weakest(self.composite_score.kind, ceiling):
            raise ValueError(
                f"composite_score cannot claim {self.composite_score.kind.value}: "
                f"its scoring rule and figures support at most {ceiling.value}"
            )

    def items(self) -> tuple[tuple[str, FigureBasis], ...]:
        """Each figure's name and basis, in field order."""
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


#: The keep-out distance a scenario takes unless the operator sets one, km (SPC-191). Claude's choice, not a ruling
#: and not a sourced figure: a miss of a few kilometres is close for any asset, and the panel says it is unsourced.
DEFAULT_KEEP_OUT_KM: float = 10.0
#: The range the keep-out distance may take, km: 100 m is already finer than any element set is known to, and the
#: upper end stays well below the 50,000 km at which closest approach scores nothing, so the scale between has room.
MIN_KEEP_OUT_KM: float = 0.1
MAX_KEEP_OUT_KM: float = 10_000.0


_SCORE_NOTE = (
    "weighted sum of custody, closest approach and our delta-V with the response's time to execute and "
    "reversibility; weights as set on the panel, scaled to sum to one, defaults not yet cited (SPC-151); closest "
    "approach valued in orders of magnitude, the full penalty at or inside the keep-out distance set on the panel, "
    f"whose default, {DEFAULT_KEEP_OUT_KM:g} km, is Claude's choice and unsourced, and none at 50,000 km or more; our "
    f"delta-V valued in orders of magnitude up to the {MAX_BURN_M_S:,.0f} m/s per-burn limit (SPC-191); never "
    "stronger than lookup"
)


#: Beside the outcome matrix and the game tree, where the composite score is shown (SPC-219, evaluation F-20). The score
#: adds custody lost and closest approach as separate weighted terms (score_terms, _score); no source for a term joining
#: them was found, so none is added and the assumption is stated. Not part of any record: it changes no figure.
TERMS_INDEPENDENT_LINE = (
    "Custody lost and closest approach are added to the score as separate terms, with nothing joining them: a close "
    "approach while custody is lost scores what the two score apart, no more, though an approach we cannot see may "
    "be worse than the two added together. No source for a term joining them was found, so none is added. An "
    "unsourced assumption, listed in docs/lookup-register.md."
)


def outcome_bases(
    *,
    custody_maintained: FigureBasis,
    custody_gap_hours: FigureBasis,
    closest_approach_km: FigureBasis,
    time_to_closest_hours: FigureBasis,
    delta_v_cost_km_s: FigureBasis,
) -> OutcomeBases:
    """The bases of one cell, with the score's derived from the figures it uses.

    The only builder for OutcomeBases: a later release sets one figure's
    kind (SPC-120: closest approach computed) and the score follows.
    """
    inputs = {
        "custody_maintained": custody_maintained,
        "custody_gap_hours": custody_gap_hours,
        "closest_approach_km": closest_approach_km,
        "delta_v_cost_km_s": delta_v_cost_km_s,
    }
    score_kind = weakest(_SCORING_RULE_KIND, *(inputs[name].kind for name in _SCORE_INPUTS))
    return OutcomeBases(
        time_to_closest_hours=time_to_closest_hours,
        composite_score=FigureBasis(score_kind, _SCORE_NOTE),
        **inputs,
    )


#: Each figure's name as the operator reads it.
FIGURE_LABELS: dict[str, str] = {
    "custody_maintained": "custody",
    "custody_gap_hours": "custody gap",
    "closest_approach_km": "closest approach",
    "time_to_closest_hours": "time to closest approach",
    "delta_v_cost_km_s": "our delta-V",
    "composite_score": "score",
}

#: Phase 1: every figure is a lookup, and each note matches compute_outcome_metrics as written.
LOOKUP_BASES: OutcomeBases = outcome_bases(
    custody_maintained=FigureBasis(
        Basis.LOOKUP,
        "rule of thumb: lost when the adversary manoeuvres and the response neither manoeuvres nor retasks "
        "a sensor; not the held, degraded or lost custody on the sweep",
    ),
    custody_gap_hours=FigureBasis(
        Basis.LOOKUP,
        "when custody is lost, the horizon x the row's custody gap share, not its intelligence confidence; "
        "against a sensor retask, half its time to execute; detection is not modelled",
    ),
    closest_approach_km=FigureBasis(
        Basis.LOOKUP,
        "a fixed 200, 3,000, 5,000 or 10,000 km per adversary action type, raised by response cost for a "
        "manoeuvre or posture change; no orbit propagated",
    ),
    time_to_closest_hours=FigureBasis(Basis.LOOKUP, "0.4 of the horizon"),
    delta_v_cost_km_s=FigureBasis(
        Basis.LOOKUP, "response cost x 0.05 km/s (0 to 50 m/s) for a manoeuvre response, else 0",
    ),
)

#: The result's basis once its figures rest on more than one kind; the lines list them.
MIXED_BASIS = (
    "Figures rest on mixed bases, listed below and marked in each cell. "
    "The ranking is still a weighted heuristic."
)

_ALL_LOOKUP_LINE = "Every figure in every cell is a lookup."


def _cell_bases(cell: object) -> OutcomeBases:
    """A cell's bases. An unrecorded basis reads as a lookup, never as computed."""
    bases = getattr(cell, "figure_bases", None)
    return bases if isinstance(bases, OutcomeBases) else LOOKUP_BASES


def _is_modelled(bases: OutcomeBases) -> bool:
    return any(fb.kind is not Basis.COMPUTED for _, fb in bases.items())


def _all_lookup(bases: OutcomeBases) -> bool:
    return all(fb.kind is Basis.LOOKUP for _, fb in bases.items())


def _figure_line(label: str, counts: Counter[Basis], total: int) -> str:
    """One banner line, kinds weakest first: "Closest approach: lookup in 1 of 2 cells, computed in 1." """
    present = [(kind, counts[kind]) for kind in Basis if counts[kind]]   # Basis is declared weakest first
    head = label[:1].upper() + label[1:]
    if len(present) == 1:
        return f"{head}: {present[0][0].value} in every cell."
    (first, n_first), *rest = present
    parts = [f"{first.value} in {n_first} of {total} cells", *(f"{kind.value} in {n}" for kind, n in rest)]
    return f"{head}: {', '.join(parts)}."


# ── Data classes ──────────────────────────────────────────────────────────────

def _require_fraction(owner: str, field_name: str, value: float) -> None:
    """Refuse a value outside [0, 1], NaN or infinite included (audit F-112)."""
    if not (math.isfinite(value) and 0.0 <= value <= 1.0):
        raise ValueError(f"{owner}.{field_name} must be in [0, 1]; got {value!r}")


# ── Manoeuvre hypothesis (SPC-111) ────────────────────────────────────────────

#: Shown with every hypothesis once the panel carries one (SPC-114).
HYPOTHESIS_NOTE: str = (
    "A manoeuvre hypothesis records how the adversary might move and where that came from. With a red track "
    "bound, its burn time sets when custody is lost; with both sides bound, the closest approach of its row and "
    "its time are sampled from it, and our burn is sized only for a manoeuvre response given a target "
    "separation; without one, a manoeuvre row's closest approach "
    "stays a lookup and its custody takes the worst case, a burn at the scenario epoch, since it names no burn."
)


class HypothesisSource(StrEnum):
    """Where an adversary action's manoeuvre hypothesis came from."""

    ARCHETYPE = "archetype"     # a row of MANOEUVRE_ARCHETYPES
    ENTERED = "entered"         # a delta-V and direction the operator gave
    DETECTED = "detected"       # a manoeuvre detected in the object's element-set history


#: The frames a hypothesis's direction may be read in. ManoeuvreHypothesis holds radial, in-track and
#: cross-track parts, so RIC is the only one until a later release adds another.
_FRAMES = frozenset({"RIC"})
#: Radial, in-track and cross-track.
_RIC_AXES = 3
#: Below this norm, or above any finite one, generate_samples cannot read the direction and quietly points the
#: burn in-track, so parts outside that range are stored at unit length instead.
_MIN_DIRECTION_NORM = 1e-15
#: The spreads a sampler draws from, each with how a refusal names it.
_DISPERSIONS: tuple[tuple[str, str], ...] = (
    ("delta_v_magnitude_1sigma_km_s", "delta-V spread"),
    ("delta_v_pointing_1sigma_deg", "pointing spread"),
    ("epoch_1sigma_seconds", "timing spread"),
    ("bstar_1sigma", "B* spread"),
)
_ARCHETYPE_DIRECTION = "assumed in-track: an archetype names no direction"
_ENTERED_DIRECTION = "entered by the operator"
_SOURCE_LEADS: dict[HypothesisSource, str] = {
    HypothesisSource.ARCHETYPE: "Archetype {archetype}",
    HypothesisSource.ENTERED: "Entered by the operator",
    HypothesisSource.DETECTED: "Detected manoeuvre",
}


#: The burn on its own line in the results (SPC-114), and whose state each source starts from.
_BURN_LINE = "Burn at {burn:%Y-%m-%d %H:%M} UTC, {h:+.1f} h from the scenario epoch, from {start} state then."
_STARTS: dict[HypothesisSource, str] = {
    HypothesisSource.ARCHETYPE: "the bound red track's",
    HypothesisSource.ENTERED: "the bound red track's",
    HypothesisSource.DETECTED: "the detected element set's",
}


class PreManoeuvreState(NamedTuple):
    """Where and when the adversary is just before the hypothesised burn."""

    epoch_utc:    datetime
    state_eci_km: Sequence[float]     # [x, y, z, vx, vy, vz]: km, and km per second


def _known_archetype(key: str) -> ManoeuvreType:
    archetype = MANOEUVRE_ARCHETYPES.get(key)
    if archetype is None:
        raise ValueError(
            f"{key!r} is not a known manoeuvre archetype; choose one of {', '.join(MANOEUVRE_ARCHETYPES)}."
        )
    return archetype


def _unit_ric(direction: Sequence[float]) -> tuple[float, float, float]:
    """*direction* scaled to unit length, refused when it has no length to scale.

    The parts are divided by the largest first, so a direction of any finite
    size normalises without its squares underflowing or overflowing.
    """
    parts = tuple(float(c) for c in direction)
    if len(parts) != _RIC_AXES or not all(math.isfinite(c) for c in parts):
        raise ValueError(
            f"A direction is three finite parts, radial, in-track and cross-track; got {tuple(direction)!r}."
        )
    peak = max(abs(c) for c in parts)
    if not peak:
        raise ValueError("A direction of zero cannot be normalised, and no direction is assumed in its place.")
    scaled = tuple(c / peak for c in parts)
    norm = math.hypot(*scaled)
    return (scaled[0] / norm, scaled[1] / norm, scaled[2] / norm)


def _parts(hypothesis: ManoeuvreHypothesis) -> tuple[float, float, float]:
    return (hypothesis.delta_v_radial, hypothesis.delta_v_in_track, hypothesis.delta_v_cross_track)


def _sampler_reads(parts: Sequence[float]) -> bool:
    """Whether generate_samples can read *parts* as a direction rather than quietly assume in-track."""
    norm = float(np.linalg.norm(np.asarray(parts, dtype=float)))
    return math.isfinite(norm) and norm >= _MIN_DIRECTION_NORM


def _pointed(hypothesis: ManoeuvreHypothesis, unit: tuple[float, float, float]) -> ManoeuvreHypothesis:
    """*hypothesis* along *unit*, scaled by its delta-V where the sampler can read that, else at unit length.

    The parts only point, so a zero or tiny burn keeps its direction this way.
    """
    scaled = tuple(hypothesis.delta_v_magnitude_km_s * c for c in unit)
    parts = scaled if _sampler_reads(scaled) else unit
    return dataclasses.replace(
        hypothesis, delta_v_radial=parts[0], delta_v_in_track=parts[1], delta_v_cross_track=parts[2],
    )


def _nominal(dv_km_s: float, unit: tuple[float, float, float], at: PreManoeuvreState, basis: str) -> ManoeuvreHypothesis:
    """The burn along *unit*."""
    return _pointed(
        ManoeuvreHypothesis(
            epoch_utc=at.epoch_utc,
            delta_v_magnitude_km_s=dv_km_s,
            delta_v_radial=unit[0],
            delta_v_in_track=unit[1],
            delta_v_cross_track=unit[2],
            pre_manoeuvre_state_eci_km=np.array(at.state_eci_km, dtype=float),
            direction_basis=basis,
        ),
        unit,
    )


def _dispersed(hypothesis: ManoeuvreHypothesis, archetype: ManoeuvreType | None, n_samples: int) -> ManoeuvreHypothesis:
    """*hypothesis* with *archetype*'s dispersions and name; the ManoeuvreHypothesis defaults when there is none."""
    if archetype is None:
        return dataclasses.replace(hypothesis, n_samples=n_samples)
    return dataclasses.replace(
        hypothesis,
        delta_v_magnitude_1sigma_km_s=hypothesis.delta_v_magnitude_km_s * archetype.delta_v_1sigma_fraction,
        delta_v_pointing_1sigma_deg=archetype.pointing_1sigma_deg,
        epoch_1sigma_seconds=archetype.timing_1sigma_seconds,
        archetype=archetype.name,
        n_samples=n_samples,
    )


def _require_origin(carried: AdversaryHypothesis) -> None:
    """The source, frame, direction basis and archetype say how the hypothesis was made, and agree."""
    if not isinstance(carried.source, HypothesisSource):
        raise ValueError(f"A hypothesis's source is archetype, entered or detected; got {carried.source!r}.")
    if carried.frame not in _FRAMES:
        raise ValueError(f"A hypothesis's direction is read in the RIC frame; got frame {carried.frame!r}.")
    if not carried.hypothesis.direction_basis.strip():
        raise ValueError("A hypothesis states its direction basis, so a reader can tell an assumed direction.")
    named = carried.hypothesis.archetype
    if carried.archetype_key is None:
        if carried.source is not HypothesisSource.ENTERED:
            raise ValueError(f"A {carried.source.value} hypothesis names its archetype.")
        if named:
            raise ValueError(f"A hypothesis with no archetype key names no archetype; it names {named}.")
        return
    expected = _known_archetype(carried.archetype_key).name
    if named != expected:
        raise ValueError(f"Archetype {carried.archetype_key!r} names {expected}, not {named or 'nothing'}.")


def _require_burn(hypothesis: ManoeuvreHypothesis) -> None:
    """The burn is finite and not negative, points somewhere, starts from a real state and is sampled at least once."""
    dv = hypothesis.delta_v_magnitude_km_s
    if not (math.isfinite(dv) and dv >= 0.0):
        raise ValueError(f"A hypothesis's delta-V must be finite and not negative; got {from_km_s(dv)!r} m/s.")
    _unit_ric(_parts(hypothesis))
    _require_dispersions(hypothesis)
    state = np.asarray(hypothesis.pre_manoeuvre_state_eci_km, dtype=float)
    if state.shape != (6,) or not bool(np.all(np.isfinite(state))):
        raise ValueError("The pre-manoeuvre state is six finite numbers: position in km, then velocity.")
    if hypothesis.n_samples < 1:
        raise ValueError(f"A hypothesis's sample count must be at least 1; got {hypothesis.n_samples!r}.")


def _require_dispersions(hypothesis: ManoeuvreHypothesis) -> None:
    """Every spread the sampler draws from is finite and not negative; zero means none."""
    for name, label in _DISPERSIONS:
        value = getattr(hypothesis, name)
        if not (math.isfinite(value) and value >= 0.0):
            shown = f"{from_km_s(value)!r} m/s" if name.endswith("_km_s") else repr(value)
            raise ValueError(f"A hypothesis's {label} must be finite and not negative; got {shown}.")


class _SealedHypothesis(ManoeuvreHypothesis):
    """A ManoeuvreHypothesis no field of which can be written or deleted once it is built.

    A frozen dataclass cannot inherit from a plain one, so the seal is set at
    the end of construction. ``dataclasses.replace`` still works, and gives
    another sealed copy.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise dataclasses.FrozenInstanceError(f"cannot assign to field {name!r}: a carried hypothesis is sealed")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        raise dataclasses.FrozenInstanceError(f"cannot delete field {name!r}: a carried hypothesis is sealed")


def _sealed_copy(hypothesis: ManoeuvreHypothesis) -> _SealedHypothesis:
    """A sealed copy, so the checks made at construction keep holding whatever the caller does later.

    Its direction is put where the sampler can read it, and its state is held
    in memory that cannot be made writeable again.
    """
    if not _sampler_reads(_parts(hypothesis)):
        hypothesis = _pointed(hypothesis, _unit_ric(_parts(hypothesis)))
    state = np.frombuffer(np.asarray(hypothesis.pre_manoeuvre_state_eci_km, dtype=float).tobytes(), dtype=float)
    values = {f.name: getattr(hypothesis, f.name) for f in dataclasses.fields(hypothesis)}
    return _SealedHypothesis(**{**values, "pre_manoeuvre_state_eci_km": state})


def pre_manoeuvre_state(tle: str, at: datetime) -> PreManoeuvreState | None:
    """Where the element set puts the object at *at*, as a hypothesis's start; None when it cannot be propagated."""
    track = elset_state(tle, at)
    return None if track is None else PreManoeuvreState(at, tuple(float(x) for x in track.state_eci_km))


@dataclass(frozen=True, eq=False)
class AdversaryHypothesis:
    """A manoeuvre hypothesis for one adversary action, with where it came from.

    Build one with :meth:`from_archetype`, :meth:`from_entered` or
    :meth:`from_detection`. It carries the source, the archetype's key and name
    and the direction's frame and basis, so a reader can always tell how it
    was made (audit F-104). It is checked here, whoever builds it, and the
    hypothesis is held as a sealed copy, so no later change, to the caller's
    object or to the one carried, can undo the check.
    """

    hypothesis:    ManoeuvreHypothesis
    source:        HypothesisSource
    archetype_key: str | None = None
    frame:         str = "RIC"
    # The delta-V spread was entered by the operator, not taken from the archetype (SPC-114); set by with_spread.
    spread_entered: bool = False
    # The transfer's burns after this one, in time order (SPC-184): with it, one action with one P, never
    # alternatives. Empty for a single burn; set by with_transfer.
    then: tuple[TransferBurn, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis, ManoeuvreHypothesis):
            raise TypeError(f"AdversaryHypothesis holds a ManoeuvreHypothesis; got {type(self.hypothesis).__name__}")
        _require_origin(self)
        _require_burn(self.hypothesis)
        object.__setattr__(self, "then", tuple(self.then))
        require_transfer(self.hypothesis.epoch_utc, self.then)
        object.__setattr__(self, "hypothesis", _sealed_copy(self.hypothesis))

    @classmethod
    def from_archetype(
        cls, archetype: str, at: PreManoeuvreState, *, direction_ric: Sequence[float] | None = None,
        n_samples: int = 500,
    ) -> AdversaryHypothesis:
        """An archetype's typical burn and dispersions, in-track unless a direction is entered."""
        row = _known_archetype(archetype)
        unit, basis = (0.0, 1.0, 0.0), _ARCHETYPE_DIRECTION
        if direction_ric is not None:
            unit, basis = _unit_ric(direction_ric), _ENTERED_DIRECTION
        nominal = _nominal(row.typical_delta_v_km_s, unit, at, basis)
        return cls(_dispersed(nominal, row, n_samples), HypothesisSource.ARCHETYPE, archetype_key=archetype)

    @classmethod
    def from_entered(
        cls, delta_v_m_s: float, direction_ric: Sequence[float] | None, at: PreManoeuvreState, *,
        archetype: str | None = None, n_samples: int = 500,
    ) -> AdversaryHypothesis:
        """A delta-V the operator entered, in m/s, along a RIC direction, with an archetype's dispersions if named.

        With no direction, the archetype's assumed in-track direction is taken, and the basis says so; without
        an archetype, a direction is needed.
        """
        row = None if archetype is None else _known_archetype(archetype)
        if direction_ric is None:
            if row is None:
                raise ValueError("An entered delta-V without an archetype needs a direction.")
            unit, basis = (0.0, 1.0, 0.0), _ARCHETYPE_DIRECTION
        else:
            unit, basis = _unit_ric(direction_ric), _ENTERED_DIRECTION
        nominal = _nominal(to_km_s(delta_v_m_s), unit, at, basis)
        return cls(_dispersed(nominal, row, n_samples), HypothesisSource.ENTERED, archetype_key=archetype)

    def with_spread(self, delta_v_1sigma_m_s: float) -> AdversaryHypothesis:
        """This hypothesis with a delta-V spread the operator entered, in m/s (1 sigma); the other spreads stay."""
        spread = dataclasses.replace(self.hypothesis, delta_v_magnitude_1sigma_km_s=to_km_s(delta_v_1sigma_m_s))
        return dataclasses.replace(self, hypothesis=spread, spread_entered=True)

    def with_transfer(self, then: Sequence[TransferBurn]) -> AdversaryHypothesis:
        """This hypothesis as the first burn of a transfer whose later burns are *then*, in time order (SPC-184)."""
        return dataclasses.replace(self, then=tuple(then))

    @classmethod
    def from_detection(
        cls, tle_record: TLERecord, manoeuvre: Manoeuvre, *, archetype: str, n_samples: int = 500,
    ) -> AdversaryHypothesis:
        """A detected manoeuvre's burn and direction, with *archetype*'s dispersions.

        The archetype is checked first: hypothesis_from_tle_record would read
        an unknown one as an orbit raise and say nothing. A detection of no or
        almost no delta-V keeps the detection's direction at unit length,
        where the split would have scaled it to nothing.
        """
        _known_archetype(archetype)
        built = hypothesis_from_tle_record(tle_record, manoeuvre, n_samples=n_samples, archetype_override=archetype)
        if not _sampler_reads(_parts(built)):
            unit, _basis = _ric_split(getattr(manoeuvre, "breakdown", None))
            built = _pointed(built, _unit_ric(unit.tolist()))
        return cls(built, HypothesisSource.DETECTED, archetype_key=archetype)

    @property
    def archetype(self) -> str:
        """The archetype's name, or empty when the dispersions are the defaults."""
        return self.hypothesis.archetype

    @property
    def direction_basis(self) -> str:
        return self.hypothesis.direction_basis

    @property
    def delta_v_m_s(self) -> float:
        return from_km_s(self.hypothesis.delta_v_magnitude_km_s)

    @property
    def direction_ric(self) -> tuple[float, float, float]:
        h = self.hypothesis
        return _unit_ric((h.delta_v_radial, h.delta_v_in_track, h.delta_v_cross_track))

    @property
    def sentence(self) -> str:
        """How the hypothesis was made, in one sentence."""
        lead = _SOURCE_LEADS[self.source].format(archetype=self.archetype)
        return f"{lead}: {self.delta_v_m_s:.1f} m/s; direction ({self.frame}) {self.direction_basis}; {self._spreads}."

    @property
    def _spreads(self) -> str:
        """Where the dispersions came from: the archetype, the defaults, or an entered delta-V spread (SPC-114)."""
        rest = f"from the {self.archetype} archetype" if self.archetype else "the defaults, no archetype"
        if not self.spread_entered:
            return f"dispersions {rest}" if self.archetype else "default dispersions, no archetype"
        sigma = from_km_s(self.hypothesis.delta_v_magnitude_1sigma_km_s)
        return f"delta-V spread {sigma:.1f} m/s (1 sigma) entered; pointing and timing spreads {rest}"

    def burn_line(self, scenario_epoch: datetime) -> str:
        """When the burn is, against the scenario epoch, and whose state it starts from (SPC-114)."""
        burn = self.hypothesis.epoch_utc
        hours = (burn - scenario_epoch).total_seconds() / 3600.0
        return _BURN_LINE.format(burn=burn, h=hours, start=_STARTS[self.source])

    @property
    def note(self) -> str:
        """HYPOTHESIS_NOTE, here for a template whose only context is the result."""
        return HYPOTHESIS_NOTE

    def recorded(self) -> dict[str, object]:
        """The hypothesis as plain values, for provenance: every figure at full precision."""
        inner = dataclasses.asdict(self.hypothesis)
        inner["epoch_utc"] = self.hypothesis.epoch_utc.isoformat()
        inner["pre_manoeuvre_state_eci_km"] = [float(x) for x in self.hypothesis.pre_manoeuvre_state_eci_km]
        recorded: dict[str, object] = {
            "source": self.source.value, "archetype_key": self.archetype_key, "frame": self.frame,
            "spread_entered": self.spread_entered, "hypothesis": inner,
        }
        if self.then:   # a single burn records as it did before SPC-184
            recorded["then"] = [burn.recorded() for burn in self.then]
        return recorded

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AdversaryHypothesis):
            return NotImplemented
        return self.recorded() == other.recorded()

    def __hash__(self) -> int:
        return hash(json.dumps(self.recorded(), sort_keys=True))


#: A row's probability when none is given, and the value the panel gives every row. A row reads as untouched when the
#: form records that its P was never edited (SPC-183), not because it holds this value (SPC-171 read it so).
DEFAULT_PROBABILITY = 0.5

#: A row's custody gap share when none is given: the confidence the page posted by default, which set the rule of
#: thumb's gap until SPC-161, so a page left at its defaults scores as it did.
DEFAULT_CUSTODY_GAP_FRACTION = 0.7

#: Where a new panel starts the operator's other inputs (SPC-196): a new adversary row's Conf, and a new response's
#: cost, reversibility and time to execute. The panel's fields carry these values and
#: tests/unit/test_lookup_register.py holds them to it; the results name them, since the form records no edit of them.
DEFAULT_CONFIDENCE = 0.7
DEFAULT_RESPONSE_COST = 0.3
DEFAULT_REVERSIBILITY = 0.8
DEFAULT_TIME_TO_EXECUTE_H = 6.0
#: The horizon a scenario takes, and a new panel starts at, unless one is given, hours.
DEFAULT_HORIZON_H = 72.0

#: How far above 1 the rows' P may sum and still be read as 1, and how far below 1 before a remainder is weighed: the
#: rounding of adding fractions, not a judgement (SPC-203).
P_SUM_TOLERANCE = 1e-9
#: The engine's own row for the chance that none of the operator's actions happens (SPC-203).
REMAINDER_ID = "remainder"
REMAINDER_NAME = "No adversary action (remainder of P)"
#: Beside the remainder row's name in the matrix and the rankings (SPC-203).
REMAINDER_LABEL = "the engine's remainder, not your row"
#: Why a sum of P above 1 is refused, at the panel and in the scenario (SPC-203).
P_SUM_REFUSED = (
    "{lead}, above 1. P is the chance of each adversary action, and the rows must be mutually exclusive, so their P "
    "sum to at most 1; the engine weighs the rest as no adversary action. Lower the P of one or more rows."
)
_P_SUM_TYPED = "Your rows' P sum to {total}"
_P_SUM_SUGGESTED = "With the NOTSO {suggestions} applied to {rows}, your rows' P sum to {total}"

#: Beside the adversary rows on the panel: what each of a row's three numbers means and what reads it (SPC-161).
ADVERSARY_FIELDS_NOTE = (
    "P: how likely you judge this action, from 0 to 1; the rows must be mutually exclusive, so their P sum to at "
    "most 1, and the engine weighs the rest as no adversary action. The expected-value selector weights each row "
    "by its P. "
    "Conf: how sure the intelligence behind P is, from 0 to 1; it is recorded and moves no figure. "
    "Gap: the share of the horizon we lose custody for if this action is a manoeuvre and our response neither "
    "manoeuvres nor retasks a sensor, a rule of thumb; a bound red track's custody replaces it once read."
)


@dataclass
class AdversaryAction:
    """A single adversary COA to evaluate.

    probability is the operator's likelihood that the action happens, the only weight the expected-value selector
    reads. confidence is how sure the intelligence behind that likelihood is: recorded, it moves no figure. The rule
    of thumb's custody gap is custody_gap_fraction of the horizon, a statement about our custody, not about the
    adversary's likelihood; until SPC-161 it was the horizon x confidence, so a surer row lost custody for longer.
    """

    id:          str
    name:        str
    action_type: ActionType
    probability: float            # [0, 1]: the operator's likelihood that this action happens
    confidence:  float            # [0, 1]: how sure the intelligence behind probability is; moves no figure
    description: str = ""
    # How the adversary might move, and where that came from (SPC-111). Carried
    # and put in provenance; in a scenario bound on both sides, plan_sampling
    # samples this row's closest approach from it (SPC-112).
    hypothesis:  AdversaryHypothesis | None = None
    # [0, 1]: the share of the horizon the rule of thumb loses custody for when this row is a manoeuvre and the
    # response neither manoeuvres nor retasks a sensor (SPC-161). A bound red track's read custody replaces it.
    custody_gap_fraction: float = DEFAULT_CUSTODY_GAP_FRACTION
    # The NOTSO suggestion the operator applied to this row (SPC-130), whose P, and Conf when it offers one, are the
    # row's; None when both are the operator's own. Recorded in the scenario's provenance; it moves no figure.
    accepted_prior: NotsoPrior | None = None
    # Whether P was stated rather than left at the panel's default: the form records each edit (the owner's ruling
    # of 2026-11-05, concept section 9, decision 11, SPC-183), so a deliberate 0.5 is the operator's own. A row
    # built in code states its P, so it is True unless the form says otherwise.
    probability_edited: bool = True
    # The engine's own row for the rest of P (SPC-203), never the operator's: with_remainder adds it, and it is never
    # stored as a row.
    remainder: bool = False

    def __post_init__(self) -> None:
        _require_fraction("AdversaryAction", "probability", self.probability)
        if not self.probability_edited and not math.isclose(self.probability, DEFAULT_PROBABILITY):
            raise ValueError(
                f"a probability not edited is the panel's default, {DEFAULT_PROBABILITY}; got {self.probability}"
            )
        _require_fraction("AdversaryAction", "confidence", self.confidence)
        _require_fraction("AdversaryAction", "custody_gap_fraction", self.custody_gap_fraction)
        if self.hypothesis is not None and not isinstance(self.hypothesis, AdversaryHypothesis):
            raise TypeError(
                "AdversaryAction.hypothesis takes an AdversaryHypothesis, which says where the hypothesis came "
                f"from; got {type(self.hypothesis).__name__}"
            )
        if self.accepted_prior is not None:
            _require_accepted(self)
        if self.remainder:
            _require_remainder_row(self)


def _require_remainder_row(action: AdversaryAction) -> None:
    """The remainder row is the engine's no-action row, as it builds it: no hypothesis, no suggestion (SPC-203)."""
    built = (action.id, action.name, action.action_type, action.hypothesis, action.accepted_prior)
    if built != (REMAINDER_ID, REMAINDER_NAME, ActionType.NO_ACTION, None, None):
        raise ValueError(f"the remainder row is the engine's {REMAINDER_NAME}, a no-action row with nothing else")


def _require_accepted(action: AdversaryAction) -> None:
    """An accepted NOTSO suggestion is for the row's action type and holds the row's P, and its Conf if it offers one."""
    from spectre.domain.notso_prior import NotsoPrior

    prior = action.accepted_prior
    if not isinstance(prior, NotsoPrior):
        raise TypeError(f"AdversaryAction.accepted_prior takes a NotsoPrior; got {type(prior).__name__}")
    if prior.action_type is not action.action_type:
        raise ValueError(
            f"an accepted NOTSO suggestion for a {prior.action_type.value} cannot set a "
            f"{action.action_type.value} row's action type"
        )
    if not math.isclose(prior.probability, action.probability):
        raise ValueError(
            f"an accepted NOTSO suggestion's probability, {prior.probability}, is not the row's, {action.probability}"
        )
    if prior.confidence is not None and not math.isclose(prior.confidence, action.confidence):
        raise ValueError(
            f"an accepted NOTSO suggestion's confidence, {prior.confidence}, is not the row's, {action.confidence}"
        )


#: The longest reason a response may give for being not permitted, in characters (SPC-195).
MAX_VETO_REASON = 500
#: A response not permitted, in the words the matrix, the rankings and the tree show beside it (SPC-195).
NOT_PERMITTED = "Not permitted: {reason}"
#: Each response not permitted, as the result lists it above the matrix (SPC-195).
VETO_LINE = (
    "{name} ({id}) is marked not permitted, so no rule picks it; it is still evaluated and shown. Its reason: "
    "{reason}"
)
#: What the expected-value guidance says of minimax when every response is marked not permitted (SPC-195).
MINIMAX_NONE_PERMITTED = (
    "Minimax, the cautious rule, needs no probability, but every response is marked not permitted, so it picks "
    "nothing."
)


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
    # Our burn on the blue asset (SPC-121): a target separation to size it to, with its budget and axis. A
    # manoeuvre response only; it burns at its time to execute after the scenario epoch.
    burn:                 ResponseBurnSpec | None = None
    # The operator's veto (SPC-195, evaluation F-04): a response marked not permitted on legal, rules-of-engagement
    # or safety grounds, with the reason in words. It is still evaluated and shown, but no rule ever picks it.
    vetoed:               bool = False
    veto_reason:          str = ""

    def __post_init__(self) -> None:
        _require_fraction("FriendlyResponse", "cost", self.cost)
        _require_fraction("FriendlyResponse", "reversibility", self.reversibility)
        if not (math.isfinite(self.time_to_execute_hours) and self.time_to_execute_hours >= 0.0):
            raise ValueError(
                f"FriendlyResponse.time_to_execute_hours must be finite and >= 0; "
                f"got {self.time_to_execute_hours!r}"
            )
        if self.burn is not None:
            _require_burn_spec(self)
        _require_veto(self)

    @property
    def not_permitted(self) -> str | None:
        """The words "Not permitted:" and the reason, for a vetoed response; None for one that is permitted."""
        return NOT_PERMITTED.format(reason=self.veto_reason) if self.vetoed else None


def _require_veto(response: FriendlyResponse) -> None:
    """A veto is a truth value; a vetoed response gives a reason of at most MAX_VETO_REASON characters, and a
    permitted one gives none, so no reason is held that nothing reads (SPC-195)."""
    if not isinstance(response.vetoed, bool):
        raise TypeError(f"FriendlyResponse.vetoed takes True or False; got {response.vetoed!r}")
    if not isinstance(response.veto_reason, str):
        raise TypeError(f"FriendlyResponse.veto_reason takes text; got {type(response.veto_reason).__name__}")
    if not response.vetoed:
        if response.veto_reason:
            raise ValueError("FriendlyResponse.veto_reason is given only for a response not permitted")
        return
    if not response.veto_reason.strip():
        raise ValueError("FriendlyResponse.veto_reason is required when a response is not permitted")
    if len(response.veto_reason) > MAX_VETO_REASON:
        raise ValueError(
            f"FriendlyResponse.veto_reason is at most {MAX_VETO_REASON} characters; got {len(response.veto_reason)}"
        )


def permitted_responses(scenario: Scenario) -> list[int]:
    """The places of *scenario*'s responses not marked not permitted, in order: the only ones a rule may pick."""
    return [j for j, response in enumerate(scenario.friendly_responses) if not response.vetoed]


def _require_burn_spec(response: FriendlyResponse) -> None:
    """Only a manoeuvre burns, toward a finite target above 0 within a finite budget above 0, on a known axis."""
    spec = response.burn
    if not isinstance(spec, ResponseBurnSpec):
        raise TypeError(f"FriendlyResponse.burn takes a ResponseBurnSpec; got {type(spec).__name__}")
    if response.action_type is not ActionType.MANOEUVRE:
        raise ValueError(f"only a manoeuvre response burns; this one is {response.action_type.value}")
    if not (math.isfinite(spec.target_km) and spec.target_km > 0.0):
        raise ValueError(f"FriendlyResponse.burn's target must be finite and above 0 km; got {spec.target_km!r}")
    if not (math.isfinite(spec.budget_km_s) and spec.budget_km_s > 0.0):
        raise ValueError(
            f"FriendlyResponse.burn's budget must be finite and above 0 m/s; got {from_km_s(spec.budget_km_s)!r}"
        )
    if not isinstance(spec.axis, BurnAxis):
        raise ValueError(f"FriendlyResponse.burn's axis must be one of {', '.join(BurnAxis)}; got {spec.axis!r}")


@dataclass
class OutcomeMetrics:
    """Deterministic outcome metrics for one (adversary_action, friendly_response) pair."""

    custody_maintained:   bool
    custody_gap_hours:    float     # 0 if custody maintained
    closest_approach_km:  float
    time_to_closest_hours: float
    delta_v_cost_km_s:    float    # Friendly ΔV expended
    composite_score:      float    # Higher = worse for friendly
    # What each figure above rests on, carried on the data so no consumer can
    # present a lookup as computed. The default is the weakest basis, so a
    # path that forgets to set it under-claims rather than over-claims.
    figure_bases:         OutcomeBases = LOOKUP_BASES
    # A sampled closest approach (SPC-112): P5, P50 and P95 of the misses in
    # km, at full precision, and their standard deviation. Set exactly when the
    # closest approach's basis is sampled; closest_approach_km is then P5.
    ca_percentiles:       dict[int, float] | None = None
    ca_std_km:            float | None = None
    # How many sampled misses the band is taken over, set with the band.
    ca_samples:           int | None = None
    # Why the closest approach was not sampled or computed, ending "is a lookup".
    ca_refusal:           str | None = None
    # What P5 does not say about a sampled cell: the closest sample, and any
    # that were still closing when the window ended.
    ca_caveat:            str | None = None
    # How closely P5, P50 and P95 are known, km (95 % bootstrap half-width),
    # and the composite score's P5, P50, P95 and 1-sigma spread across the
    # samples (SPC-115). Set with the band; the score's basis stays lookup.
    ca_half_width_km:     float | None = None
    score_percentiles:    dict[int, float] | None = None
    score_std:            float | None = None
    # A computed closest approach (SPC-120): both bound orbits on SGP4 with no
    # burn, the miss, TCA and edge flag unrounded. Set exactly when the closest
    # approach's basis is computed; closest_approach_km and time_to_closest_hours
    # are then its miss and TCA, rounded.
    ca_computed:          ElsetApproach | None = None
    # The bound red track's custody at the scenario epoch, held, degraded or lost (SPC-123). Set exactly when
    # custody's basis is computed; custody_maintained and custody_gap_hours then carry it over the horizon.
    custody_state:        Custody | None = None
    # Hours of the horizon the bound red track's custody is degraded, neither held nor lost (SPC-179): never in
    # custody_gap_hours, which counts lost hours only. Non-zero only on custody computed as degraded at the epoch.
    custody_degraded_hours: float = 0.0
    # How closely the time of closest approach is known (SPC-118); only on a computed or sampled closest approach.
    tca_uncertainty:      TcaUncertainty | None = None
    # The sampled TCA and its spread across samples (SPC-118); only on a sampled closest approach.
    ca_sampled_tca:       SampledTca | None = None
    # Our burn on the blue asset and what it buys (SPC-121). Set exactly when our delta-V's basis is computed;
    # delta_v_cost_km_s is then the burn's size, and the closest approach is computed after it or sampled.
    ca_response:          ResponseFigure | None = None
    # Why a manoeuvre response's target separation was not sized here, so its delta-V stays a lookup (SPC-121).
    response_refusal:     str | None = None
    # The samples' TCAs as a histogram, binned no finer than each is known (SPC-124); only on a sampled cell.
    tca_histogram:        TcaHistogram | None = None
    # The element-set error a computed or sampled closest approach holds (SPC-202): for a computed cell, both sets'
    # error at its TCA, the band beside the miss; for a sampled cell, the 1 sigma each sample drew at the scenario
    # epoch. None under the rule of 0.28.0 to 0.31.0, and on a lookup.
    ca_elset_error:       ElsetErrorAt | None = None
    # The figures the composite score was built from, unrounded (SPC-205, SPC-204): what the weight stability and a
    # cue's outcomes score again, so neither reads the rounded figures shown. Set by the engine on every cell it builds;
    # None on a cell built by hand, which is then scored again from the figures shown.
    score_figures:        _Figures | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        sampled = _cell_bases(self).closest_approach_km.kind is Basis.SAMPLED
        band = (
            self.ca_percentiles, self.ca_std_km, self.ca_samples, self.ca_half_width_km, self.score_percentiles,
            self.score_std,
        )
        if not all((part is not None) == sampled for part in band):
            raise ValueError(
                "ca_percentiles, ca_std_km, ca_samples, ca_half_width_km, score_percentiles and score_std are set "
                "exactly when the closest approach's basis is sampled"
            )
        if self.ca_percentiles is not None:
            _require_band(self.ca_percentiles, cast("float", self.ca_std_km), self.closest_approach_km)
            if self.ca_refusal is not None:
                raise ValueError("a cell is sampled or refused, not both")
        elif self.ca_caveat is not None:
            raise ValueError("a caveat on the sampled closest approach needs a sampled band")
        _require_computed(self)
        _require_custody(self)
        _require_tca(self)
        _require_response(self)
        _require_elset_error(self)

    @property
    def ca_band(self) -> str | None:
        """The sampled band in one sentence, for the cell; None when the closest approach is not sampled."""
        if self.ca_percentiles is None:
            return None
        p = self.ca_percentiles
        return _CA_BAND.format(p5=p[5], p95=p[95], p50=p[50], hw=self.ca_half_width_km, n=self.ca_samples)

    @property
    def ca_distribution(self) -> str | None:
        """The sampled distribution in full, for the band's hover; None when the closest approach is not sampled."""
        if self.ca_percentiles is None:
            return None
        p = self.ca_percentiles
        error = self.ca_elset_error
        distribution = _CA_DISTRIBUTION if error is None else _CA_DISTRIBUTION_ELSET
        return distribution.format(
            n=self.ca_samples, p5=p[5], p50=p[50], p95=p[95], std=self.ca_std_km, hw=self.ca_half_width_km,
            **({} if error is None else error.words()),
        )

    @property
    def ca_elset_band(self) -> tuple[float, float] | None:
        """A computed miss's element-set band, km: the miss less and plus both sets' error at the TCA in quadrature,
        the lower edge never below 0 (SPC-202). None on a sampled or lookup cell, and under the rule before it."""
        found, error = self.ca_computed, self.ca_elset_error
        if found is None or error is None:
            return None
        miss = found.approach.miss_km
        return lower_edge_km(miss, error.combined_km), miss + error.combined_km

    @property
    def ca_elset_line(self) -> str | None:
        """The element-set error the cell's closest approach holds, in one sentence; None when it holds none."""
        error, band = self.ca_elset_error, self.ca_elset_band
        if error is None:
            return None
        if band is None:
            return SAMPLED_ELSET_LINE.format(**error.words())
        return COMPUTED_ELSET_LINE.format(low=band[0], high=band[1], **error.words())

    @property
    def ca_title(self) -> str:
        """The closest approach's hover: the computed figure in full, the sampled distribution, or LOOKUP_CELL_TITLE."""
        found = self.ca_computed
        if found is not None:
            return _COMPUTED_TITLE.format(
                miss=found.approach.miss_km, tca_s=found.approach.tca_s, v=from_km_s(found.closing_speed_km_s),
                how=_TITLE_HOW[self._how],
            )
        return self.ca_distribution or LOOKUP_CELL_TITLE

    @property
    def _how(self) -> str:
        """How a computed figure was propagated, as its line says it."""
        found = self.ca_computed
        if found is None or found.propagator != RESPONSE_PROPAGATOR:
            return _SGP4_NO_BURN
        burnt = self.ca_response is not None and self.ca_response.sized.burn is not None
        return _RK45_AFTER_BURN if burnt else _RK45_NO_BURN

    @property
    def ca_response_line(self) -> str | None:
        """Our burn and what it buys, or why it was not sized; None when this response names no target."""
        return self.ca_response.line if self.ca_response is not None else self.response_refusal

    @property
    def ca_computed_line(self) -> str | None:
        """The computed closest approach and its time, to the minute, for the cell; None when not computed."""
        found = self.ca_computed
        if found is None:
            return None
        start = found.window.start_utc
        tca = self.tca_uncertainty or _NO_TCA_UNCERTAINTY
        return _COMPUTED_LINE.format(
            miss=found.approach.miss_km, tca=_to_the_minute(found.approach.tca_utc(start)), pm=_pm(tca),
            h=tca.hours(found.approach.tca_s / _SECONDS_PER_HOUR), how=self._how,
        )

    @property
    def ca_sampled_tca_line(self) -> str | None:
        """The sampled TCA with its uncertainty, and the TCA's spread across samples; None when not sampled."""
        found = self.ca_sampled_tca
        if found is None:
            return None
        tca = self.tca_uncertainty or _NO_TCA_UNCERTAINTY
        return _SAMPLED_TCA_LINE.format(
            tca=_to_the_minute(found.tca_utc), pm=_pm(tca), h=tca.hours(found.tca_h), t5=tca.hours(found.p5_h),
            t95=tca.hours(found.p95_h),
        )

    @property
    def tca_title(self) -> str | None:
        """What the TCA's uncertainty rests on, or why there is none, for the TCA line's hover."""
        return None if self.tca_uncertainty is None else self.tca_uncertainty.title

    @property
    def ca_computed_caveat(self) -> str | None:
        """What a computed minimum at an edge of the search is not: an encounter. None otherwise."""
        found = self.ca_computed
        if found is None or not found.approach.at_window_edge:
            return None
        return _STILL_CLOSING if found.approach.tca_s > 0.0 else _ALREADY_OPENING

    @property
    def score_spread_text(self) -> str:
        """The composite score's spread across samples, for a ranking card; a lookup cell says none was computed."""
        if self.score_std is None:
            return _SCORE_SPREAD_LOOKUP
        return _SCORE_SPREAD.format(s=_spread_figure(self.score_std), n=self.ca_samples)

    @property
    def score_percentiles_text(self) -> str | None:
        """The score's P5, P50 and P95 across samples, for the card's hover; None for a lookup cell."""
        p = self.score_percentiles
        if p is None:
            return None
        return _SCORE_PERCENTILES.format(p5=p[5], p50=p[50], p95=p[95])

    @property
    def modelled(self) -> bool:
        """True while any figure is not computed: always in Phase 1, since the score is a lookup."""
        return _is_modelled(self.figure_bases)

    @property
    def custody_reading(self) -> str:
        """Custody over the horizon in the cell's words: held, lost, degraded, or degraded then lost. Degraded is
        never shown as held or lost (SPC-179)."""
        if self.custody_maintained:
            return "held"
        if not self.custody_degraded_hours:
            return "lost"
        return "degraded, then lost" if self.custody_gap_hours > 0.0 else "degraded"

    @property
    def basis(self) -> str:
        if _all_lookup(self.figure_bases):
            worst_case = self.figure_bases.custody_maintained.note == _WORST_CASE_NOTE
            return WORST_CASE_CELL_BASIS if worst_case else MODELLED_BASIS
        return "; ".join(f"{FIGURE_LABELS[name]}: {fb.kind.value}, {fb.note}" for name, fb in self.figure_bases.items())

    def __str__(self) -> str:
        cust = {"held": "✓", "lost": "✗"}.get(self.custody_reading, "◐")
        return (
            f"Custody:{cust}  CA:{self.closest_approach_km:.1f}km  "
            f"ΔV:{self.delta_v_cost_km_s*1000:.1f}m/s  "
            f"Score:{self.composite_score:.3f}"
        )


_PERCENTILE_KEYS = (5, 50, 95)


class SampledTca(NamedTuple):
    """A sampled cell's TCA, the earliest at or below P5, and P5 and P95 of every sample's TCA, hours (SPC-118)."""

    tca_utc: datetime
    tca_h:   float
    p5_h:    float
    p95_h:   float


#: Stands in for a cell built before SPC-118, which carries no TCA uncertainty: no ±, hours to 2 decimals.
_NO_TCA_UNCERTAINTY = TcaUncertainty(None, math.nan, math.nan, math.nan, at_edge=False)
_SGP4_NO_BURN = "SGP4, no burn"
_RK45_NO_BURN = "RK45, no burn"
_RK45_AFTER_BURN = "RK45, after our burn"
_TITLE_HOW: dict[str, str] = {
    _SGP4_NO_BURN: "SGP4 for both orbits with no burn",
    _RK45_NO_BURN: "RK45 with J2 and drag for both orbits with no burn",
    _RK45_AFTER_BURN: "RK45 with J2 and drag for both orbits after our burn",
}
_SAMPLED_TCA_LINE = (
    "Earliest TCA at or below P5: {tca:%Y-%m-%d %H:%M} UTC{pm}, {h} h after the scenario epoch. Across samples the "
    "TCA runs from {t5} h (P5) to {t95} h (P95)."
)


def _pm(tca: TcaUncertainty) -> str:
    """The uncertainty after a time, with its space; nothing when there is none."""
    return f" {tca.pm}" if tca.pm else ""


def _require_response(cell: OutcomeMetrics) -> None:
    """Our burn is carried only with a computed delta-V; the cell shows its size, and its closest approach is
    computed after it on RK45 for both orbits, or sampled, never a lookup (SPC-121).

    Every path that computes our delta-V carries the burn. The converse is not enforced, so a cell built by hand
    with every figure computed, as the basis tests build one, still stands.
    """
    bases = _cell_bases(cell)
    figure = cell.ca_response
    if figure is None:
        return
    if bases.delta_v_cost_km_s.kind is not Basis.COMPUTED:
        raise ValueError("ca_response is set only when our delta-V's basis is computed")
    if cell.delta_v_cost_km_s != round(figure.delta_v_km_s, 5):
        raise ValueError(
            f"a sized burn's cell shows its size, {from_km_s(figure.delta_v_km_s):.2f} m/s; got delta_v_cost_km_s "
            f"{cell.delta_v_cost_km_s!r}"
        )
    if bases.closest_approach_km.kind is Basis.LOOKUP:
        raise ValueError("a sized burn's closest approach is computed or sampled, never a lookup")
    if cell.ca_computed is not None and cell.ca_computed.propagator != RESPONSE_PROPAGATOR:
        raise ValueError("a sized burn's computed closest approach is RK45 for both orbits, never SGP4")


def _require_elset_error(cell: OutcomeMetrics) -> None:
    """Element-set error is held only by a closest approach computed or sampled (SPC-202)."""
    if cell.ca_elset_error is None:
        return
    if _cell_bases(cell).closest_approach_km.kind not in (Basis.COMPUTED, Basis.SAMPLED):
        raise ValueError("ca_elset_error is set only on a computed or sampled closest approach")


def _require_one_propagator(matrix: Sequence[Sequence[OutcomeMetrics]]) -> None:
    """Every computed cell in a result names the same propagator, so no row is ranked across two (SPC-121)."""
    named = {cell.ca_computed.propagator for row in matrix for cell in row if cell.ca_computed is not None}
    if len(named) > 1:
        raise ValueError(f"a result's computed cells share one propagator; got {sorted(named)}")


def _require_tca(cell: OutcomeMetrics) -> None:
    """A TCA uncertainty only on a computed or sampled closest approach, and a sampled TCA only on a sampled one."""
    kind = _cell_bases(cell).closest_approach_km.kind
    if cell.tca_uncertainty is not None and kind not in (Basis.COMPUTED, Basis.SAMPLED):
        raise ValueError("tca_uncertainty is set only on a computed or sampled closest approach")
    if (cell.ca_sampled_tca is not None or cell.tca_histogram is not None) and kind is not Basis.SAMPLED:
        raise ValueError("ca_sampled_tca and tca_histogram are set only on a sampled closest approach")

#: The sampled band in the cell, with how closely its percentiles are known (SPC-117).
_CA_BAND = "Sampled: P5 {p5:.1f} km to P95 {p95:.1f} km, median {p50:.1f} km, each known to within {hw:.1f} km, {n} samples."

#: The band's hover (SPC-115). The element-set model is spectre/astro/along_track.py's _ERROR_MODEL_KM.
_CA_DISTRIBUTION = (
    "Distribution of {n} sampled misses: P5 {p5:.1f} km, P50 {p50:.1f} km, P95 {p95:.1f} km; spread {std:.1f} km "
    "(1 sigma); each percentile known to within {hw:.2f} km (95 % bootstrap). Not in this spread: element-set "
    "error, which the sweep takes as " + ERROR_MODEL_WORDS + ", and the hypothesis being wrong."
)
#: The band's hover once each sample draws element-set error (SPC-202).
_CA_DISTRIBUTION_ELSET = (
    "Distribution of {n} sampled misses: P5 {p5:.1f} km, P50 {p50:.1f} km, P95 {p95:.1f} km; spread {std:.1f} km "
    "(1 sigma); each percentile known to within {hw:.2f} km (95 % bootstrap). In this spread: the burn's spread and "
    "each object's element-set error along track, drawn from " + ELSET_MODEL + ", at each set's age at the scenario "
    "epoch: red {rk:.1f} km (1 sigma), its set {ra:.1f} h old, and blue {bk:.1f} km, its set {ba:.1f} h old. Not in "
    "it: element-set error across track, and the hypothesis being wrong."
)
_SCORE_SPREAD = "Score spread {s} (1 sigma, {n} samples)"
_SCORE_SPREAD_LOOKUP = "Score spread: lookup, none computed"
_SCORE_PERCENTILES = "Score P5 {p5:.4f}, P50 {p50:.4f}, P95 {p95:.4f} across samples; the score's basis is lookup."
#: Below this a spread would print as 0.0000, which reads as none; it is shown as under 0.0001 instead.
_SMALLEST_SHOWN_SPREAD = 0.00005


def _spread_figure(std: float) -> str:
    return "under 0.0001" if std < _SMALLEST_SHOWN_SPREAD else f"{std:.4f}"


def _require_computed(cell: OutcomeMetrics) -> None:
    """The computed figure is set exactly when the closest approach is computed, alone, and the cell shows it."""
    found = cell.ca_computed
    if (found is not None) != (_cell_bases(cell).closest_approach_km.kind is Basis.COMPUTED):
        raise ValueError("ca_computed is set exactly when the closest approach's basis is computed")
    if found is None:
        return
    if cell.ca_refusal is not None:
        raise ValueError("a cell is computed or refused, not both")
    miss, hours = round(found.approach.miss_km, 1), round(found.approach.tca_s / _SECONDS_PER_HOUR, 2)
    if cell.closest_approach_km != miss:
        raise ValueError(f"a computed cell shows the computed miss, {miss} km; got {cell.closest_approach_km!r}")
    if cell.time_to_closest_hours != hours:
        raise ValueError(f"a computed cell shows the computed time, {hours} h; got {cell.time_to_closest_hours!r}")


def _require_custody(cell: OutcomeMetrics) -> None:
    """Custody and its gap rest on one basis; a computed custody carries its state and agrees with it."""
    bases = _cell_bases(cell)
    kind = bases.custody_maintained.kind
    if bases.custody_gap_hours.kind is not kind:
        raise ValueError("custody and its gap share one basis")
    if (cell.custody_state is not None) != (kind is Basis.COMPUTED):
        raise ValueError("custody_state is set exactly when custody's basis is computed")
    if cell.custody_degraded_hours and cell.custody_state is not Custody.DEGRADED:
        raise ValueError("only custody computed as degraded at the scenario epoch has degraded hours")
    if cell.custody_state is None:
        return
    if cell.custody_maintained and cell.custody_gap_hours:
        raise ValueError(f"computed custody maintained has no gap; got {cell.custody_gap_hours!r} h")
    if cell.custody_state is not Custody.HELD and cell.custody_maintained:
        raise ValueError(f"custody {cell.custody_state.value} at the scenario epoch is not maintained")


def _to_the_minute(when: datetime) -> datetime:
    """*when* rounded to the nearest minute, for a time shown to the minute."""
    return (when + timedelta(seconds=30)).replace(second=0, microsecond=0)


def _require_band(percentiles: dict[int, float], std_km: float, closest_approach_km: float) -> None:
    """P5, P50 and P95 are finite, not negative and in order, and the closest approach shown is P5."""
    if tuple(sorted(percentiles)) != _PERCENTILE_KEYS:
        raise ValueError(f"ca_percentiles holds P5, P50 and P95, keyed 5, 50 and 95; got keys {sorted(percentiles)}")
    values = [percentiles[k] for k in _PERCENTILE_KEYS] + [std_km]
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"the sampled band and its spread must be finite; got {percentiles} and {std_km!r}")
    if not all(v >= 0.0 for v in values):
        raise ValueError(f"the sampled band and its spread must not be negative; got {percentiles} and {std_km!r}")
    p5, p50, p95 = (percentiles[k] for k in _PERCENTILE_KEYS)
    if not p5 <= p50 <= p95:
        raise ValueError(f"the sampled band must hold P5 <= P50 <= P95; got {percentiles}")
    if closest_approach_km != round(p5, 1):
        raise ValueError(f"a sampled cell scores and shows P5, {round(p5, 1)} km; got {closest_approach_km!r} km")


# ── Binding to real objects (SPC-100) ─────────────────────────────────────────

#: Shown with every binding, on the panel and with the result.
BINDING_NOTE: str = (
    "Binding records which real objects this scenario is about. With both sides bound, the closest approach and "
    "its time are computed from these orbits by SGP4, with no burn, for every row whose action does not move the "
    "red track, and sampled for a row whose action carries a hypothesis; a manoeuvre with no hypothesis names no "
    "burn and stays a lookup. With a red track bound, custody is its custody as the sweep judges it at evaluation, "
    "carried over the horizon. Our delta-V is computed for a manoeuvre response given a target separation, and is "
    "0 m/s for a response that does not burn wherever the closest approach is computed or sampled; a manoeuvre "
    "response with no target keeps the lookup."
)

_SIDES = frozenset({"red", "blue"})


class Freshness(StrEnum):
    """How a bound element set's age at evaluation stands against its regime's limit."""

    CURRENT = "current"
    OUT_OF_DATE = "out of date"
    UNKNOWN = "unknown"


def _require_side(elset: BoundElset) -> None:
    if elset.side not in _SIDES:
        raise ValueError(f"BoundElset.side must be red or blue; got {elset.side!r}")


def _require_age_facts(elset: BoundElset) -> None:
    """The epoch, age and limit are all known or all unknown, and a known age and limit make sense."""
    facts = (elset.epoch, elset.age_hours, elset.limit_hours)
    if all(f is None for f in facts):
        return
    if elset.epoch is None or elset.age_hours is None or elset.limit_hours is None:
        raise ValueError("an element set's epoch, age and limit are read together")
    if not (math.isfinite(elset.age_hours) and elset.age_hours >= 0.0):
        raise ValueError(f"BoundElset.age_hours must be finite and >= 0; got {elset.age_hours!r}")
    if not (math.isfinite(elset.limit_hours) and elset.limit_hours > 0.0):
        raise ValueError(f"BoundElset.limit_hours must be finite and > 0; got {elset.limit_hours!r}")


_FRESHNESS_SENTENCES: dict[Freshness, str] = {
    Freshness.CURRENT: "Orbit current: {age} old at evaluation, limit {limit}{figure}.",
    Freshness.OUT_OF_DATE: (
        "Orbit out of date: {age} old at evaluation against a {limit} limit{figure}, "
        "so a burn since its epoch would not be seen."
    ),
    Freshness.UNKNOWN: "Its epoch cannot be read, so its age is unknown; read it as out of date.",
}
#: A bound set's regime and whose figures the engine applies to it (SPC-215, evaluation F-29).
_REGIME_LINE = (
    "Regime {regime} (period {period:.0f} min, e {e:.3f}): staleness limit {limit:.0f} h and element-set error "
    "{rate}."
)


@dataclass(frozen=True)
class BoundElset:
    """One held object a scenario is bound to, with its element set's age at evaluation.

    The age and limit are worked out where the element set is read and passed
    in as plain values, so the domain stays free of the web layer. All three
    of epoch, age and limit are None when the epoch cannot be read.
    """

    side:        Literal["red", "blue"]
    name:        str
    stk_name:    str
    satno:       int | None
    tle:         str
    data_mode:   str
    epoch:       datetime | None
    age_hours:   float | None
    limit_hours: float | None
    training:    bool = False
    # The red track's custody at evaluation, as the sweep judges it (SPC-018), read by the web layer; red only.
    custody:     CustodyStatus | None = None

    def __post_init__(self) -> None:
        _require_side(self)
        _require_age_facts(self)
        if self.custody is not None and self.side != "red":
            raise ValueError("custody describes our information about the red track; a blue element set carries none")

    @property
    def freshness(self) -> Freshness:
        """The sweep's staleness rule (ElsetAge.stale): out of date only when the age is past the limit."""
        if self.age_hours is None or self.limit_hours is None:
            return Freshness.UNKNOWN
        return Freshness.OUT_OF_DATE if self.age_hours > self.limit_hours else Freshness.CURRENT

    @property
    def age_label(self) -> str | None:
        return None if self.age_hours is None else age_text(self.age_hours)

    @property
    def limit_label(self) -> str | None:
        return None if self.limit_hours is None else f"{self.limit_hours:.0f} h"

    @property
    def sentence(self) -> str:
        """The orbit's age in a sentence: it says orbit, never custody."""
        figure = self.limit_figure
        return _FRESHNESS_SENTENCES[self.freshness].format(
            age=self.age_label, limit=self.limit_label, figure=f", the {figure}" if figure else "",
        )

    @property
    def limit_figure(self) -> str:
        """Whose figure the staleness limit is, in words, "LEO figure applied to HEO/Molniya, unsourced for this
        regime" (V0.40 review); "" when the set's regime cannot be read."""
        basis = regime_basis(self.tle)
        return "" if basis is None else basis.applied

    @property
    def regime_line(self) -> str:
        """The set's regime, by its period and eccentricity, and whose staleness limit and element-set error rate the
        engine applies to it (SPC-215, evaluation F-29); empty when its limit or elements cannot be read."""
        basis = regime_basis(self.tle)
        if basis is None or self.limit_hours is None:
            return ""
        return _REGIME_LINE.format(regime=basis.regime, period=basis.period_min, e=basis.eccentricity,
                                   limit=self.limit_hours, rate=error_rate_words(self.tle))


@dataclass(frozen=True)
class ScenarioBinding:
    """The red track and blue asset a scenario is about; at least one of them."""

    red:  BoundElset | None = None
    blue: BoundElset | None = None

    def __post_init__(self) -> None:
        if self.red is None and self.blue is None:
            raise ValueError("a binding names at least one object; pass binding=None for an unbound scenario")
        if self.red is not None and self.red.side != "red":
            raise ValueError("ScenarioBinding.red must hold a red element set")
        if self.blue is not None and self.blue.side != "blue":
            raise ValueError("ScenarioBinding.blue must hold a blue element set")

    @property
    def bound(self) -> tuple[BoundElset, ...]:
        """The bound element sets, red first."""
        return tuple(b for b in (self.red, self.blue) if b is not None)

    @property
    def note(self) -> str:
        """BINDING_NOTE, here for the results template, whose only context is the result."""
        return BINDING_NOTE


# ── Threat Understanding beside the scenario (SPC-171) ───────────────────────

#: A collect-first row's time-to-execute note: the cue's duration is a tuned lookup, not a measured time.
COLLECTION_NOTE = "collection to narrow the threat range: the cue's tuned duration, a lookup"
#: Why a collection the sweep would collect first cannot change the recommended response (SPC-204, evaluation F-14):
#: under no outcome's picture of any cue the picture holds does any cell of the matrix move, which is so while no
#: figure reads a Threat band. Computed every time from the matrix built again, never assumed.
NO_BAND_READ = "the outcome matrix reads no Threat band"
CANNOT_CHANGE = (
    'Collecting "{observation}" would narrow the Threat range but cannot change the recommended response: {why}.'
)
#: The same, where an outcome's picture moves a cell of the matrix but not the pick.
SAME_EITHER_WAY = (
    'Collecting "{observation}" would narrow the Threat range, but under either of its outcomes the engine '
    "recommends {pick}."
)
#: Said beside the sweep's advice to act on the ceiling, or that the range is below the action line, when the picture
#: holds a cue and none of them can change the recommended response (SPC-204); the reason as above, or where a cue's
#: outcome moves a cell but no pick, that each cue's outcomes agree.
NONE_CAN_CHANGE = "No collection the picture holds can change the recommended response: {why}."
EACH_THE_SAME = "each cue's two outcomes give the same one"
#: What collect first adds when a cue's outcomes do change the recommended response: the pick under each.
OUTCOME_PICKS = "Under its benign outcome the engine recommends {benign}; under its hostile outcome, {hostile}."
#: Where the expected-value selector's weight has not been earned (concept section 7.5, item 4): Understanding LOW, or
#: a row whose P the form records as never edited, not one merely holding 0.5 (the owner's ruling of 2026-11-05 on
#: concept section 9, decision 11, SPC-183).
EXPECTED_VALUE_UNEARNED = "Expected value rests on a probability the evidence has not earned."
#: The same, for a bound red track the engine reads no picture for: it says only what the engine reads.
EXPECTED_VALUE_NO_PICTURE = "Expected value rests on a probability no Threat picture for {red} supports."
#: What the engine shows beside every figure and sentence the sweep's picture feeds, its age at evaluation in words
#: (SPC-181, the owner's ruling of 2026-11-05 on concept section 9, decision 9: the picture is read at any age).
PICTURE_AGE = "from the sweep's picture assessed {age} before this evaluation"
_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24


def _when(moment: datetime) -> str:
    """A moment as the sweep writes decide-by: "15:00 UTC on 4 Nov"."""
    return f"{moment:%H:%M} UTC on {moment.day} {moment:%b}"


def picture_age_words(age: timedelta) -> str:
    """*age* in words, rounded down to the unit shown: "under 1 min", "20 min", "3 h 10 min", "2 d 4 h"."""
    minutes = int(age.total_seconds() // _SECONDS_PER_MINUTE)
    hours, minute = divmod(minutes, _MINUTES_PER_HOUR)
    days, hour = divmod(hours, _HOURS_PER_DAY)
    if days:
        return f"{days} d" + (f" {hour} h" if hour else "")
    if hours:
        return f"{hours} h" + (f" {minute} min" if minute else "")
    return f"{minutes} min" if minutes else "under 1 min"


def _beside(sentence: str, age: str) -> str:
    """*sentence* with *age* in brackets before its full stop."""
    return f"{sentence.removesuffix('.')} ({age})."


@dataclass(frozen=True)
class CollectionRow:
    """A collect-first row (concept section 7.5, item 1): a cue that needs someone outside SPECTRE, named by the cue
    and timed by its lookup duration.

    Listed beside the ranking, never scored in it: no collection here tasks a sensor, and collecting moves no figure
    until what it finds is in the sweep, so as a friendly row it would win on a custody credit and a cost and
    reversibility made up for it.
    """

    name:  str
    hours: float
    #: The age of the sweep's picture the row comes from, as PICTURE_AGE words it (SPC-181).
    age:   str
    basis: FigureBasis = FigureBasis(Basis.LOOKUP, COLLECTION_NOTE)

    @property
    def sentence(self) -> str:
        return (
            f"{_beside(f'{self.name}, {self.hours:g} h: {self.basis.note}.', self.age)} Not ranked against your "
            "responses: collecting moves no figure until what it finds is in the sweep."
        )


@dataclass(frozen=True)
class ThreatPicture:
    """The bound red track's Threat range, Understanding, cues and decide-by, as the sweep assessed them (SPC-171).

    Context for the operator and the collect-first advice only: it moves no figure, no score and no field of an
    adversary row. *red* names the red track it was assessed for; *decide_at* is the sweep's decide-by, None when it
    set none, *decide_by* its sentence, *target* the blue asset it was set for and *arrival* the intercept it was set
    against, None when unknown. When decide-by needs a response time (SPC-211), *target* is the first target in reach
    with no response time set, and *decide_at* and *arrival* are None. *assessed_at* is when the sweep assessed it, which every picture states: the engine
    reads it at any age and shows that age beside every figure and sentence it feeds (SPC-181).
    """

    red:           str
    floor:         Band
    ceiling:       Band
    understanding: Understanding
    cues:          tuple[Cue, ...] = ()
    decide_at:     datetime | None = None
    decide_by:     str = ""
    target:        str = ""
    arrival:       datetime | None = None
    assessed_at:   datetime = field(kw_only=True)

    def __post_init__(self) -> None:
        if self.floor > self.ceiling:
            raise ValueError(f"a threat range with its floor {self.floor.name} above its ceiling {self.ceiling.name}")

    def age(self, now: datetime) -> str:
        """How old the picture is at *now*, the evaluation, as PICTURE_AGE words it."""
        return PICTURE_AGE.format(age=picture_age_words(now - self.assessed_at))

    def decide_line(self, now: datetime) -> str:
        """The decide-by as it stands at *now*, the evaluation; "" when the sweep gave none.

        The sweep words its decide-by against its own clock. A deadline still ahead holds only clock times, so its
        sentence stands at any age. One passed by *now* is said again against *now*, so the line never says "Decide
        by" a past time or counts hours from the sweep, and it agrees with the advice (concept section 7.5, item 5).
        """
        if self.decide_at is None or self.decide_at > now:
            return self.decide_by
        passed = f"Decide-by has passed{f' for {self.target}' if self.target else ''}: it was {_when(self.decide_at)}"
        if self.arrival is None:
            return f"{passed}."
        if self.arrival > now:
            left = (self.arrival - now).total_seconds() / _SECONDS_PER_HOUR
            return f"{passed}, and an intercept could arrive at {_when(self.arrival)}, {left:.1f} h after this evaluation."
        return (f"{passed}, and the intercept it was set against could have arrived at {_when(self.arrival)}, before "
                "this evaluation.")

    def advice(self, now: datetime, cues: tuple[Cue, ...] | None = None) -> CollectionAdvice:
        """The sweep's collect first, act on the ceiling, or below the action line, at *now* (concept section 4.10),
        over *cues*, every cue held when None, with the picture's age beside it."""
        advice = self.unaged(now, cues)
        return dataclasses.replace(advice, sentence=_beside(advice.sentence, self.age(now)))

    def unaged(self, now: datetime, cues: tuple[Cue, ...] | None = None) -> CollectionAdvice:
        """The advice as advice() gives it, before the picture's age is put beside it."""
        held = self.cues if cues is None else cues
        return collection_advice((self.floor, self.ceiling), held, now=now, decide_at=self.decide_at)

    def collection_rows(self, now: datetime, cues: tuple[Cue, ...] | None = None) -> tuple[CollectionRow, ...]:
        """One row per cue of *cues*, every cue held when None, that needs someone outside SPECTRE, when the sweep's
        advice over them at *now* is to collect first.

        Only a cue with value above 0, whose result SPECTRE can read, landing by decide-by, is listed (SPC-182). A
        cue SPECTRE runs itself is named by the advice and lists no row.
        """
        held = self.cues if cues is None else cues
        if self.unaged(now, held).advice is not Advice.COLLECT_FIRST:
            return ()
        landing = landing_cues(held, now=now, decide_at=self.decide_at)
        return tuple(CollectionRow(c.observation, c.hours, self.age(now)) for c in landing if not c.inside_spectre)


def _require_threat(scenario: Scenario) -> None:
    """A threat picture is about the bound red track it was assessed for, and no other, and was assessed by the
    scenario epoch, so its age there can be said."""
    picture = scenario.threat
    if picture is None:
        return
    red = None if scenario.binding is None else scenario.binding.red
    if red is None or red.stk_name != picture.red:
        raise ValueError(f"a threat picture belongs to the bound red track it was assessed for, {picture.red}")
    if picture.assessed_at > scenario.epoch_utc:
        raise ValueError(f"a threat picture assessed after the scenario epoch, at {picture.assessed_at.isoformat()}")


class Seen(StrEnum):
    """What a game tree's turn lets us see of red under the likelihood model (SPC-141), in the words the result
    uses; spectre.domain.turn_update reads it, and the operator may state it for turn 1 (SPC-142)."""

    BURN = "a burn"
    NO_BURN = "no burn"
    NOTHING = "nothing"


def _require_observed(observed: object) -> None:
    """A stated observation is one of the likelihood model's own, or none."""
    if observed is not None and not isinstance(observed, Seen):
        raise ValueError(f"Scenario.observed must be a Seen or None; got {observed!r}")


def _require_keep_out(keep_out_km: float) -> None:
    """A finite keep-out distance from MIN_KEEP_OUT_KM to MAX_KEEP_OUT_KM (SPC-191)."""
    if not (math.isfinite(keep_out_km) and MIN_KEEP_OUT_KM <= keep_out_km <= MAX_KEEP_OUT_KM):
        raise ValueError(
            f"Scenario.keep_out_km must be from {MIN_KEEP_OUT_KM:g} to {MAX_KEEP_OUT_KM:g} km; got {keep_out_km!r}"
        )


@dataclass
class Scenario:
    """A what-if scenario: N adversary actions × M friendly responses."""

    name:               str
    epoch_utc:          datetime
    adversary_actions:  list[AdversaryAction]
    friendly_responses: list[FriendlyResponse]
    horizon_hours:      float = DEFAULT_HORIZON_H

    # Scoring weights (sum should equal 1)
    w_custody:          float = 0.35    # Penalty for losing custody
    w_closest_approach: float = 0.25    # Reward for maximising CA distance
    w_dv_cost:          float = 0.20    # Penalty for ΔV expenditure
    w_time_to_exec:     float = 0.10    # Penalty for slow response
    w_reversibility:    float = 0.10    # Reward for reversible actions

    # The real objects this scenario is about (SPC-100). Carried, shown and put
    # in provenance; read by plan_sampling, for a row with a hypothesis, and by
    # plan_computed, for the pair's closest approach with no burn (SPC-120).
    binding:            ScenarioBinding | None = None
    # The bound red track's Threat range, Understanding, cues and decide-by as the sweep held them (SPC-171): shown
    # beside the rows and read by the collect-first advice; it moves no figure.
    threat:             ThreatPicture | None = None
    # How many turns the game tree runs (SPC-140): red moves and we respond, then red may move again. One turn is the
    # outcome matrix alone; evaluate_tree builds 2 or 3 over the span searched, each turn set by the engine from the
    # rows' burn times (turn_rule, SPC-187).
    turns:              int = 1
    # What the operator states turn 1 of the tree showed of red (SPC-142). Under expected value the update after
    # turn 1 is shown for it alone; None when nothing was stated, and then nothing is updated. It moves no figure.
    observed:           Seen | None = None
    # The miss at or inside which closest approach scores its full penalty, km (SPC-191): set on the panel, and
    # DEFAULT_KEEP_OUT_KM, Claude's choice and unsourced, for a scenario opened from the sweep or built in code.
    keep_out_km:        float = DEFAULT_KEEP_OUT_KM
    # What the rows' P mean to expected value (SPC-203): REMAINDER, unless the scenario was read from a record 0.28.0
    # or 0.29.0 wrote, which is replayed under the rule it was evaluated under, SHARES.
    probability_rule:   ProbabilityRule = ProbabilityRule.REMAINDER
    # What a propagated closest approach holds of element-set error (SPC-202): ELSET_ERROR, unless the scenario was
    # read from a record 0.28.0 to 0.31.0 wrote, which is replayed as it was evaluated, POINT.
    miss_rule:          MissRule = MissRule.ELSET_ERROR
    # How a game tree's turns are set (SPC-187): BURNS, by the engine from the rows' burn times, unless the scenario
    # was read from a record 0.23.0 to 0.36.0 wrote, which is replayed with the equal turns it was built with, EQUAL.
    turn_rule:          TurnRule = TurnRule.BURNS
    # Which cost cap a game tree is checked against (SPC-188): OWN, the tree's own measured cap, unless the scenario was
    # read from a record 0.23.0 to 0.37.0 wrote, which is checked against the matrix's cap it shared then, SHARED.
    tree_cap:           TreeCap = TreeCap.OWN
    # How many draws a sampled row's convergence is checked on (SPC-224): TWO_SEEDS, unless the scenario was read from
    # a record 0.28.0 to 0.41.0 wrote, which is replayed on its one seed, ONE_SEED.
    convergence_rule:   ConvergenceRule = ConvergenceRule.TWO_SEEDS

    def __post_init__(self) -> None:
        # A zero horizon divided by zero in the score (audit F-112).
        if not (math.isfinite(self.horizon_hours) and self.horizon_hours > 0.0):
            raise ValueError(f"Scenario.horizon_hours must be finite and > 0; got {self.horizon_hours!r}")
        for name in ("w_custody", "w_closest_approach", "w_dv_cost", "w_time_to_exec", "w_reversibility"):
            _require_fraction("Scenario", name, getattr(self, name))
        _require_threat(self)
        _require_turns(self.turns)
        _require_observed(self.observed)
        _require_keep_out(self.keep_out_km)
        _require_probabilities(self)


#: The most turns a game tree runs (SPC-140): a fourth would multiply the branches past what one evaluation builds.
MAX_TURNS = 3


# ── What P means (SPC-203, evaluation F-12) ───────────────────────────────────

def _sum_text(total: float) -> str:
    """A sum of P as the operator reads it: to the ninth decimal at most, with no floating-point noise."""
    return f"{total:.9f}".rstrip("0").rstrip(".")


def rows_listed(rows: Sequence[int]) -> str:
    """Rows by their numbers on the panel: "row 1", "rows 1 and 3", "rows 1, 2 and 4"."""
    numbers = [str(r + 1) for r in rows]
    if len(numbers) == 1:
        return f"row {numbers[0]}"
    return f"rows {', '.join(numbers[:-1])} and {numbers[-1]}"


def p_sum_refusal(total: float, suggested: Sequence[int] = ()) -> str:
    """Why rows whose P sum to *total*, above 1, are refused; *suggested* are the rows carrying an applied NOTSO
    suggestion, named when there are any, since it is their P that the suggestions set."""
    if not suggested:
        return P_SUM_REFUSED.format(lead=_P_SUM_TYPED.format(total=_sum_text(total)))
    words = "suggestion" if len(suggested) == 1 else "suggestions"
    lead = _P_SUM_SUGGESTED.format(suggestions=words, rows=rows_listed(suggested), total=_sum_text(total))
    return P_SUM_REFUSED.format(lead=lead)


def p_sum_problem(actions: Sequence[AdversaryAction]) -> str | None:
    """Why *actions* are refused, their P summing above 1, naming the rows carrying an applied NOTSO suggestion; None
    when their P sum to at most 1 within P_SUM_TOLERANCE (SPC-203). The panel asks it before a scenario is built."""
    total = rows_p_sum(actions)
    if total <= 1.0 + P_SUM_TOLERANCE:
        return None
    return p_sum_refusal(total, [i for i, a in enumerate(actions) if a.accepted_prior is not None])


def rows_p_sum(actions: Sequence[AdversaryAction]) -> float:
    """The operator's rows' P added up exactly (math.fsum), the remainder row left out."""
    return math.fsum(a.probability for a in actions if not a.remainder)


def _rest(scenario: Scenario) -> float | None:
    """The remainder of P the engine weighs as no adversary action, or None: at 1 within P_SUM_TOLERANCE, and
    under the 0.29.0 rule, which weighs none."""
    if scenario.probability_rule is ProbabilityRule.SHARES:
        return None
    rest = 1.0 - rows_p_sum(scenario.adversary_actions)
    return rest if rest > P_SUM_TOLERANCE else None


def _require_probabilities(scenario: Scenario) -> None:
    """Under the remainder rule, the rows' P sum to at most 1 within P_SUM_TOLERANCE, and a remainder row, where one
    is held, is the last row, held once, at exactly the rest of P; under the 0.29.0 rule none is held (SPC-203)."""
    rows = scenario.adversary_actions
    held = [i for i, a in enumerate(rows) if a.remainder]
    if scenario.probability_rule is ProbabilityRule.SHARES:
        if held:
            raise ValueError("a scenario under the 0.29.0 rule weighs no remainder, so holds no remainder row")
        return
    total = rows_p_sum(rows)
    if total > 1.0 + P_SUM_TOLERANCE:
        raise ValueError(p_sum_refusal(total))
    if held and (held != [len(rows) - 1] or rows[-1].probability != _rest(scenario)):
        raise ValueError("a scenario holds its remainder row once, last, at 1 less the sum of its rows' P")


def remainder_row(rest: float) -> AdversaryAction:
    """The engine's row for the chance *rest* that none of the operator's actions happens: no adversary action."""
    return AdversaryAction(REMAINDER_ID, REMAINDER_NAME, ActionType.NO_ACTION, rest, 0.0, remainder=True)


def with_remainder(scenario: Scenario) -> Scenario:
    """*scenario* as the engine evaluates it: the operator's rows and, when their P sum below 1, the remainder row
    last, carrying the rest. *scenario* itself when it already is, so adding it twice adds one row."""
    rest = _rest(scenario)
    rows = [a for a in scenario.adversary_actions if not a.remainder]
    if not rows:   # nothing listed, so nothing to be the rest of: _evaluate refuses it as before
        return scenario
    wanted = [*rows, *(() if rest is None else (remainder_row(rest),))]
    if wanted == scenario.adversary_actions:
        return scenario
    return dataclasses.replace(scenario, adversary_actions=wanted)


def without_remainder(scenario: Scenario) -> Scenario:
    """The operator's own scenario: *scenario* with any remainder row taken out, as the record stores it."""
    rows = [a for a in scenario.adversary_actions if not a.remainder]
    if len(rows) == len(scenario.adversary_actions):
        return scenario
    return dataclasses.replace(scenario, adversary_actions=rows)


def row_shares(scenario: Scenario) -> tuple[float, ...]:
    """The share of expected value each of *scenario*'s rows takes, in order: its P, the remainder row included,
    under the remainder rule; under the 0.29.0 rule its P over the rows' sum, or 0 when every P is 0.

    A scenario whose P leave a remainder it does not hold has no shares: with_remainder gives the rows to weigh.
    """
    weights = [a.probability for a in scenario.adversary_actions]
    if scenario.probability_rule is ProbabilityRule.REMAINDER:
        if scenario.adversary_actions and not scenario.adversary_actions[-1].remainder and _rest(scenario) is not None:
            raise ValueError("these rows leave a remainder of P that no row weighs: evaluate with_remainder(scenario)")
        return tuple(weights)
    total = sum(weights)
    return tuple(w / total if total > 0.0 else 0.0 for w in weights)


def _require_turns(turns: object) -> None:
    """A whole number of turns from 1 to MAX_TURNS; True is not a turn count, though Python counts it as 1."""
    if isinstance(turns, bool) or not isinstance(turns, int) or not 1 <= turns <= MAX_TURNS:
        raise ValueError(f"Scenario.turns must be a whole number from 1 to {MAX_TURNS}; got {turns!r}")


def _untouched(action: AdversaryAction) -> bool:
    """A row whose P the form records as never edited and that applied no suggestion. The record, not the value, is
    read: the owner ruled on 2026-11-05 that a deliberate 0.5 is not untouched (concept section 9, decision 11,
    SPC-183), and an accepted NOTSO suggestion counts as edited (SPC-130)."""
    return not action.probability_edited and action.accepted_prior is None


#: A row whose P and Conf are both the operator's (SPC-130).
OWN_VALUES = "P and Conf are your own."
#: A row whose P the form records as never edited (SPC-183): its P is the panel's default, only its Conf the
#: operator's.
DEFAULT_P_VALUES = f"P {DEFAULT_PROBABILITY} is the panel's default, never edited; Conf is your own."


#: The remainder row's own words, where a row's source goes (SPC-203).
REMAINDER_SOURCE = (
    "This row is the engine's remainder, not your row: its P, {p}, is 1 less the sum of your rows' P, {total}, the "
    "chance that none of the actions you listed happens. It is evaluated as any no-action row, and it has no Conf."
)
#: Beside it, when the operator listed a no-action row of their own (SPC-203).
REMAINDER_BESIDE_NO_ACTION = (
    " Your own no-action row is one of the actions you listed, at the P you gave it; this row is the chance that "
    "none of them happens, so it is weighed apart from yours."
)


def remainder_source(scenario: Scenario) -> str:
    """What the remainder row rests on: the rest of the operator's P, and why it stands apart from a no-action row
    of theirs (SPC-203)."""
    rest = scenario.adversary_actions[-1].probability
    line = REMAINDER_SOURCE.format(p=_sum_text(rest), total=_sum_text(rows_p_sum(scenario.adversary_actions)))
    listed = any(a.action_type is ActionType.NO_ACTION and not a.remainder for a in scenario.adversary_actions)
    return line + REMAINDER_BESIDE_NO_ACTION if listed else line


def _row_source(action: AdversaryAction) -> str:
    """Whose P and Conf a row holds, with what an applied NOTSO suggestion rests on. A P the form records as never
    edited is the panel's default, not the operator's (SPC-183)."""
    prior = action.accepted_prior
    if prior is None:
        return DEFAULT_P_VALUES if _untouched(action) else OWN_VALUES
    if prior.confidence is None:
        lead = f"P {prior.probability:.2f} is the NOTSO suggestion you applied; Conf is your own."
    else:
        lead = f"P {prior.probability:.2f} and Conf {prior.confidence:.2f} are the NOTSO suggestion you applied."
    return f"{lead} {prior.basis_line} {prior.confidence_line}"


def _bound_sides(binding: ScenarioBinding | None) -> tuple[bool, bool]:
    """Whether the red track and the blue asset are bound."""
    return (False, False) if binding is None else (binding.red is not None, binding.blue is not None)


#: What the all-lookup line asks for, by which sides are bound (red, blue): only what is still to bind (SPC-119).
_TO_EARN: dict[tuple[bool, bool], str] = {
    (False, False): BIND_TO_EARN,
    (True, False): BIND_BLUE_TO_EARN,
    (False, True): BIND_RED_TO_EARN,
    (True, True): EVERY_ROW_REFUSED,
}


@dataclass
class ScenarioResult:
    """Evaluated scenario with ranked responses and a robust recommendation."""

    scenario:               Scenario
    # outcome_matrix[i][j] = OutcomeMetrics for (adversary i, friendly j)
    outcome_matrix:         list[list[OutcomeMetrics]]
    # ranked_responses[i][j] = (friendly_response, score) sorted best→worst for adversary i
    ranked_per_adversary:   list[list[tuple[FriendlyResponse, float]]]
    # The robust best response (minimax by default); None when every response is marked not permitted (SPC-195)
    robust_best_response:   FriendlyResponse | None
    robust_strategy:        SelectorStrategy
    computation_time_s:     float
    # The code, calibration and scenario behind this result (audit F-121).
    provenance:             Provenance | None = None
    # Per adversary row: why a hypothesis it carries was not sampled, else None (SPC-112).
    row_notes:              tuple[str | None, ...] = ()
    # How far RK45 and SGP4 place the bound orbits apart over the horizon, km, red's plus blue's; measured only
    # when the matrix holds both a computed and a sampled cell, and None too when it could not be (SPC-120).
    propagator_gap_km:      float | None = None
    # Per adversary row: its custody over the horizon in a sentence, when not the rule of thumb (SPC-123).
    row_custody:            tuple[str | None, ...] = ()
    # The pair's closest approach with no burn on SGP4 and on RK45, once our burn put every computed cell on RK45
    # (SPC-121): shown so the operator sees what the propagators alone move.
    rk45_reference:         tuple[ElsetApproach, ElsetApproach] | None = None
    # The multi-turn game tree (SPC-140), or why none was built; None for one turn, whose result is this matrix alone.
    tree:                   GameTree | None = None
    # Per adversary row: the burns of its transfer, which it applies and which it drops and why, when it carries
    # more than one (SPC-184); None for a single burn or none.
    row_transfers:          tuple[str | None, ...] = ()
    # Per adversary row: when its series starts at a later burn than its first, the burn line in place of the
    # hypothesis's own, which names burn 1 (SPC-184); None otherwise.
    row_starts:             tuple[str | None, ...] = ()
    # Per adversary row: what it applies (SPC-184), None for a row with no hypothesis. Read by the trajectory view.
    row_burns:              tuple[RowBurns | None, ...] = field(default=(), compare=False, repr=False)
    # Whether the evaluation's time budget ran out (SPC-113, SPC-140): a row it refused for want of time, a burn it
    # left unsized, or a tree it stopped part-way. A replay runs in full, so it says so (SPC-193, evaluation F-02).
    budget_ran_out:         bool = False
    # Each breach of the operating envelope the bound element sets show, in a sentence: a set on SDP4, flagged, and a
    # set whose object is below the re-entry floor, refused (SPC-200, docs/decision-engine-envelope.md).
    envelope:               tuple[str, ...] = ()
    # What the matrix was built from, its picture taken out (SPC-204): each row's plan, its transfer and the end of the
    # span searched, so the matrix can be built again under another Threat picture. None on a result built by hand.
    matrix_plan:            MatrixPlan | None = field(default=None, compare=False, repr=False)
    # The matrix built again under each picture's (floor, ceiling), each once (matrix_under).
    _built_under:           dict[tuple[Band, Band], list[list[OutcomeMetrics]]] = field(
        default_factory=dict, init=False, compare=False, repr=False)

    # The flag and basis are worked out from the cells, so the page says what
    # the outcomes rest on (audit F-S05-02, and the "modelled estimate" banner
    # agreed in July 2026) and cannot claim more than the cells do.

    def _bases(self) -> list[OutcomeBases]:
        return [_cell_bases(cell) for row in self.outcome_matrix for cell in row]

    @property
    def tied_responses(self) -> tuple[FriendlyResponse, ...]:
        """The rule used's pick and every response tied with it, in the order entered (SPC-206): one when there is no
        tie, none with no pick. robust_best_response is still the response with the lowest score, as 0.37.0 did, which
        need not be the first entered of them."""
        return tied_responses(self.scenario, self.outcome_matrix, self.robust_strategy)

    @property
    def tie_line(self) -> str | None:
        """That the rule used finds a tie, naming every tied response; None when it finds none (SPC-206)."""
        return tie_line(self.robust_strategy, self.tied_responses)

    @property
    def modelled(self) -> bool:
        bases = self._bases()
        return not bases or any(_is_modelled(b) for b in bases)

    @property
    def basis(self) -> str:
        """MODELLED_BASIS while every figure is a lookup, else MIXED_BASIS; never the lines repeated.

        With custody the worst case in every cell, not the rule of thumb, it is WORST_CASE_BASIS instead (SPC-123).

        The all-lookup line then says what to do: bind both sides, or, with both bound, read each cell's refusal.
        """
        bases = self._bases()
        if not all(_all_lookup(b) for b in bases):
            return MIXED_BASIS
        worst_case = bool(bases) and not self.custody_rule_of_thumb   # every row a manoeuvre naming no burn time
        modelled = WORST_CASE_BASIS if worst_case else MODELLED_BASIS
        return f"{modelled} {_TO_EARN[_bound_sides(getattr(self.scenario, 'binding', None))]}"

    @property
    def lookup_relations(self) -> tuple[LookupRelation, ...]:
        """Every unsourced relation of the lookup model a figure of this result rests on, each once, in the register's
        order: read from the bases of each cell of the matrix and of each node of a game tree (SPC-207)."""
        actions, responses = self.scenario.adversary_actions, self.scenario.friendly_responses
        used: set[LookupRelation] = set()
        for action, row in zip(actions, self.outcome_matrix, strict=True):
            for response, cell in zip(responses, row, strict=True):
                used |= lookup_relations(action, response, _cell_bases(cell))
        for node in _tree_nodes(() if self.tree is None else self.tree.roots):
            used |= lookup_relations(actions[node.action], responses[node.response], _node_bases(node))
        return tuple(r for r in LookupRelation if r in used)

    @property
    def training_only(self) -> str | None:
        """The training-only label naming every unsourced relation this result rests on; None when it rests on none
        (SPC-207, evaluation F-17). The results page shows it above the recommendation and the record keeps it."""
        return training_only_label(self.lookup_relations)

    @property
    def custody_rule_of_thumb(self) -> bool:
        """Whether any cell's custody is still the rule of thumb, so the page says so only then.

        A manoeuvre with no hypothesis takes the worst case (SPC-123): a lookup, but not the rule of thumb.
        """
        return any(
            b.custody_maintained.kind is Basis.LOOKUP and b.custody_maintained.note != _WORST_CASE_NOTE
            for b in self._bases()
        )

    @property
    def custody_bind_note(self) -> str | None:
        """What would compute custody, while the rule of thumb stands: bind a red track, or none was read."""
        if not self.custody_rule_of_thumb:
            return None
        binding = getattr(self.scenario, "binding", None)
        return CUSTODY_BIND_RED if binding is None or binding.red is None else CUSTODY_NOT_READ

    @property
    def custody_note(self) -> str | None:
        """CUSTODY_NOTE when any cell's custody is computed from the bound red track's status, else None (SPC-123).

        The worst case does not rest on the status, so it alone does not bring the note: its row sentence says why.
        """
        computed = any(b.custody_maintained.kind is Basis.COMPUTED for b in self._bases())
        return CUSTODY_NOTE if computed else None

    # ── Threat Understanding beside the result (SPC-171): context, never a figure ──

    def _picture(self) -> ThreatPicture | None:
        return getattr(self.scenario, "threat", None)

    def _red_name(self) -> str | None:
        binding = getattr(self.scenario, "binding", None)
        red = None if binding is None else binding.red
        return None if red is None else red.stk_name

    @property
    def collection(self) -> CollectionAdvice | None:
        """The engine's advice at the scenario epoch under the rule the evaluation ran; None with no picture."""
        return self.collection_under(self.robust_strategy)

    @property
    def collection_rows(self) -> tuple[CollectionRow, ...]:
        """The collect-first rows at the scenario epoch under the rule the evaluation ran; none with no picture."""
        return self.collection_rows_under(self.robust_strategy)

    def _deciding(self, picture: ThreatPicture, rule: SelectorStrategy) -> tuple[Cue, ...]:
        """The picture's cues whose outcomes give different recommended responses under *rule* (SPC-204)."""
        return tuple(cue for cue in picture.cues if cue_relevance(self, cue, rule).changes)

    def collection_under(self, rule: SelectorStrategy) -> CollectionAdvice | None:
        """Collect first, act on the ceiling, below the action line, or cannot change the recommended response, at
        the scenario epoch, judged by *rule*'s pick; None with no picture (SPC-204, evaluation F-14).

        Where the sweep would collect first, the engine collects first only for a cue whose outcomes give different
        recommended responses and that lands by decide-by, naming the pick under each outcome. With no such cue the
        advice names the sweep's cue and says it would narrow the Threat range but cannot change the recommended
        response, and why, as the matrix built again under each outcome shows. Where the sweep acts on the ceiling or
        finds the range below the action line, its advice stands, and when the picture holds a cue and none of them
        can change the recommended response, a sentence says so.
        """
        picture = self._picture()
        if picture is None:
            return None
        now = self.scenario.epoch_utc
        swept = picture.unaged(now)
        relevance = {cue: cue_relevance(self, cue, rule) for cue in picture.cues}
        refused = next((seen for seen in relevance.values() if seen.refused is not None), None)
        if refused is not None:
            sentence = CUE_NOT_AVAILABLE.format(observation=refused.cue.observation, why=refused.refused)
            return dataclasses.replace(swept, sentence=_beside(f"{swept.sentence} {sentence}", picture.age(now)))
        # The matrix is said to read no Threat band only when no cue's outcome moved a cell: earned, not assumed.
        band_read = any(seen.moved for seen in relevance.values())
        if swept.advice is not Advice.COLLECT_FIRST:
            return _with_none_can_change(swept, picture, now, relevance, band_read)
        named = picture.unaged(now, tuple(cue for cue, seen in relevance.items() if seen.changes))
        if named.advice is Advice.COLLECT_FIRST:
            chosen = relevance[cast("Cue", named.cue)]
            picks = OUTCOME_PICKS.format(benign=_named(chosen.benign), hostile=_named(chosen.hostile))
            return dataclasses.replace(named, sentence=_beside(f"{named.sentence} {picks}", picture.age(now)))
        cue = cast("Cue", swept.cue)
        sentence = (SAME_EITHER_WAY.format(observation=cue.observation, pick=_named(relevance[cue].benign))
                    if band_read else CANNOT_CHANGE.format(observation=cue.observation, why=NO_BAND_READ))
        return CollectionAdvice(Advice.CANNOT_CHANGE_RESPONSE, cue, _beside(sentence, picture.age(now)), action_line="")

    def matrix_under(self, floor: Band, ceiling: Band) -> list[list[OutcomeMetrics]]:
        """The outcome matrix with the picture's range at *floor* to *ceiling*: built again through the engine's own
        cell step from the plans this evaluation made, the evaluation the engine runs under that picture (SPC-204).
        Each picture's matrix is built once. A result the engine did not build holds no plans, so each of its cells
        is scored again from the figures it was built from under that picture instead. Its scenario holds a picture.
        """
        key = (floor, ceiling)
        if key not in self._built_under:
            held = cast("ThreatPicture", self.scenario.threat)
            outcome = dataclasses.replace(self.scenario, threat=dataclasses.replace(held, floor=floor, ceiling=ceiling))
            self._built_under[key] = (_rescored(self, outcome) if self.matrix_plan is None
                                      else _build_matrix(outcome, self.matrix_plan))
        return self._built_under[key]

    def collection_rows_under(self, rule: SelectorStrategy) -> tuple[CollectionRow, ...]:
        """The collect-first rows at the scenario epoch, judged by *rule*'s pick, listed beside the ranking: one per
        cue that needs someone outside SPECTRE whose outcomes change the recommended response; none with no
        picture, and none unless the engine collects first."""
        picture = self._picture()
        if picture is None:
            return ()
        return picture.collection_rows(self.scenario.epoch_utc, self._deciding(picture, rule))

    @property
    def threat_lines(self) -> tuple[str, ...]:
        """The sweep's Threat range, its Understanding and its decide-by as it stands at evaluation, each its own
        sentence (I13), each with the picture's age at evaluation beside it (SPC-181)."""
        picture = self._picture()
        if picture is None:
            return ()
        age = picture.age(self.scenario.epoch_utc)
        return (
            _beside(f"Threat range for {picture.red}: from {picture.floor.name} to {picture.ceiling.name}.",
                    f"{age}, at {_when(picture.assessed_at)}"),
            _beside(f"Understanding {picture.understanding.name}: the sweep's rating of {picture.red}.", age),
            *([_beside(decide, age)] if (decide := picture.decide_line(self.scenario.epoch_utc)) else []),
        )

    @property
    def row_understanding(self) -> tuple[str | None, ...]:
        """Each adversary row's Understanding, carried into the result: the bound red track's, or not assessed.

        Shown beside P and Conf as context only (concept section 7.5, items 2 and 3): nothing fills either.
        """
        red, picture = self._red_name(), self._picture()
        rows = len(self.scenario.adversary_actions)
        if red is None:
            return (None,) * rows
        if picture is None:
            return (
                f"Understanding not assessed: the engine reads no picture from the sweep for {red}, so nothing fills "
                "P or Conf.",
            ) * rows
        note = f"Understanding {picture.understanding.name}: shown beside P and Conf as context; it fills neither."
        return (_beside(note, picture.age(self.scenario.epoch_utc)),) * rows

    def _unearned(self) -> str | None:
        """Why expected value's weights are not earned: a bound red track with no picture read, a picture at
        Understanding LOW, with its age beside it (SPC-181), or any row whose P the form records as never edited
        (SPC-183); None when none holds."""
        red, picture = self._red_name(), self._picture()
        if red is not None and picture is None:
            return EXPECTED_VALUE_NO_PICTURE.format(red=red)
        if picture is not None and picture.understanding is Understanding.LOW:
            return _beside(EXPECTED_VALUE_UNEARNED, picture.age(self.scenario.epoch_utc))
        if any(_untouched(a) for a in self.scenario.adversary_actions):
            return EXPECTED_VALUE_UNEARNED
        return None

    @property
    def row_shares(self) -> tuple[float, ...]:
        """The share of expected value each row takes, shown beside its P: P itself, the remainder row included
        (SPC-203)."""
        return row_shares(self.scenario)

    @property
    def row_p_texts(self) -> tuple[str, ...]:
        """Each row's P as the page shows it: the operator's as entered; the remainder's, 1 less their sum, to the
        ninth decimal at most, with no floating-point noise (SPC-203)."""
        return tuple(_sum_text(a.probability) if a.remainder else str(a.probability)
                     for a in self.scenario.adversary_actions)

    @property
    def row_share_texts(self) -> tuple[str, ...]:
        """Each row's share as the page shows it: under the remainder rule its P, written as the P beside it is, so
        the two read alike; under the 0.29.0 rule its P over the rows' sum, to the ninth decimal at most."""
        if self.scenario.probability_rule is ProbabilityRule.REMAINDER:
            return self.row_p_texts
        return tuple(_sum_text(share) for share in self.row_shares)

    @property
    def remainder_label(self) -> str:
        """What the page says beside the remainder row's name (SPC-203)."""
        return REMAINDER_LABEL

    @property
    def row_sources(self) -> tuple[str, ...]:
        """Per adversary row, whose P and Conf they are: the operator's own, or a NOTSO suggestion applied (SPC-130)."""
        return tuple(
            remainder_source(self.scenario) if a.remainder else _row_source(a) for a in self.scenario.adversary_actions
        )

    @property
    def interval_lines(self) -> tuple[str, ...]:
        """Per row holding an applied NOTSO suggestion, whether expected value's pick holds across its P's interval,
        and the P at which it changes if it does; under minimax or minimin, that the rule reads no probability, with
        no interval shown (SPC-132)."""
        return interval_lines(self.scenario, self.outcome_matrix, self.robust_strategy)

    @property
    def objective_guidance(self) -> str | None:
        """Under expected value, when its weights are not earned: say so, and name what minimax picks.

        The selector chosen is kept: the guidance recommends, it never switches (concept section 7.5, item 4).
        """
        why = self._unearned() if self.robust_strategy is SelectorStrategy.EXPECTED_VALUE else None
        if why is None:
            return None
        minimax = find_robust_response(self.scenario, self.outcome_matrix, SelectorStrategy.MINIMAX)
        if minimax is None:
            return f"{why} {MINIMAX_NONE_PERMITTED}"
        return f"{why} Minimax, the cautious rule, needs no probability: it picks {minimax.name}."

    @property
    def veto_lines(self) -> tuple[str, ...]:
        """Each response marked not permitted, with its reason, and that it is shown but never picked (SPC-195)."""
        return tuple(
            VETO_LINE.format(name=r.name, id=r.id, reason=r.veto_reason)
            for r in self.scenario.friendly_responses if r.vetoed
        )

    @property
    def basis_lines(self) -> tuple[str, ...]:
        """One line per figure saying which kinds it rests on and in how many cells."""
        bases = self._bases()
        if all(_all_lookup(b) for b in bases):
            return (_ALL_LOOKUP_LINE,)
        return tuple(
            _figure_line(label, Counter(getattr(b, name).kind for b in bases), len(bases))
            for name, label in FIGURE_LABELS.items()
        )

    def _bands(self) -> list[dict[int, float]]:
        cells = (cell for row in self.outcome_matrix for cell in row)
        return [band for cell in cells if (band := getattr(cell, "ca_percentiles", None)) is not None]

    @property
    def n_sampled_cells(self) -> int:
        """How many cells score on a sampled closest approach."""
        return len(self._bands())

    def _computed(self) -> list[ElsetApproach]:
        cells = (cell for row in self.outcome_matrix for cell in row)
        return [found for cell in cells if (found := getattr(cell, "ca_computed", None)) is not None]

    @property
    def n_computed_cells(self) -> int:
        """How many cells score on a computed closest approach (SPC-120)."""
        return len(self._computed())

    def _on_rk45(self) -> bool:
        """Whether the computed cells are RK45 for both orbits because a response's burn was sized (SPC-121)."""
        return any(found.propagator == RESPONSE_PROPAGATOR for found in self._computed())

    def _responses(self) -> list[tuple[int, OutcomeMetrics]]:
        return [
            (i, cell) for i, row in enumerate(self.outcome_matrix) for cell in row
            if getattr(cell, "ca_response", None) is not None
        ]

    @property
    def n_burn_cells(self) -> int:
        """How many cells carry our sized burn, a burn of none included (SPC-121)."""
        return len(self._responses())

    @property
    def computed_caveat(self) -> str | None:
        """What a computed closest approach does not say; None when no cell is computed (SPC-120)."""
        if not self._computed():
            return None
        if self.scenario.miss_rule is MissRule.ELSET_ERROR:
            caveat = COMPUTED_CAVEAT_WITH_BURNS_ELSET if self._on_rk45() else COMPUTED_CAVEAT_ELSET
            return caveat.format(ages=self._elset_ages())
        return COMPUTED_CAVEAT_WITH_BURNS if self._on_rk45() else COMPUTED_CAVEAT

    def _elset_ages(self) -> str:
        """Both bound sets' ages at the scenario epoch, as the result's sentences name them (SPC-202). Only asked where
        a cell is computed or sampled, so both sides are bound with their epochs."""
        at = elset_error_at(cast("ScenarioBinding", self.scenario.binding), self.scenario.epoch_utc)
        return ELSET_AGES.format(**at.words())

    @property
    def rk45_reference_line(self) -> str | None:
        """The SGP4 and RK45 figures with no burn and how far apart they are, once the computed cells are RK45, and
        the WGS-72 to WGS-84 handover over the span searched (SPC-225, evaluation F-36)."""
        if self.rk45_reference is None:
            return None
        sgp4, rk45 = (found.approach for found in self.rk45_reference)
        start = self.rk45_reference[0].window.start_utc
        words = handover_words(self.searched_span_s / _SECONDS_PER_HOUR)
        return RK45_FOR_BURNS.format(
            sm=sgp4.miss_km, st=sgp4.tca_utc(start), rm=rk45.miss_km, rt=rk45.tca_utc(start),
            dm=abs(rk45.miss_km - sgp4.miss_km), dt=abs(rk45.tca_s - sgp4.tca_s),
        ) + f" {words[0].upper()}{words[1:]} (SPC-225)."

    def _burn_moves(self) -> list[tuple[float, int, OutcomeMetrics]]:
        """Each cell with a sized burn, with how far its burn moves the cell's closest-approach term in the score:
        the term before the burn less the one after it, each by _norm_ca, so it holds whatever the scale (SPC-191)."""
        w = self.scenario
        moves = []
        for i, cell in self._responses():
            figure = cast("ResponseFigure", cell.ca_response)
            if figure.sized.burn is None:
                continue
            before, after = figure.misses_km
            move = w.w_closest_approach * abs(_norm_ca(before, w.keep_out_km) - _norm_ca(after, w.keep_out_km))
            moves.append((move, i, cell))
        return moves

    @property
    def burn_score_note(self) -> str | None:
        """How much what a burn buys moves its score, against what its delta-V adds; None with no burn (SPC-121).

        It reports the cell whose score the burn moves most, not the one it buys most kilometres in: on a scale in
        orders of magnitude the two differ (SPC-191). The delta-V's share is _norm_dv of that cell's delta-V.
        """
        moves = self._burn_moves()
        if not moves:
            return None
        move, i, cell = max(moves, key=lambda found: found[0])
        figure = cast("ResponseFigure", cell.ca_response)
        w = self.scenario
        return BURN_SCORE_NOTE.format(
            keep=_keep_out_text(w.keep_out_km), buys=figure.buys_km, adv=w.adversary_actions[i].name, ca=move,
            dv=from_km_s(cell.delta_v_cost_km_s), dvs=w.w_dv_cost * _norm_dv(cell.delta_v_cost_km_s),
        )

    @property
    def searched_span_s(self) -> float:
        """The seconds from the scenario epoch that computed and sampled cells were searched over (SPC-118)."""
        return _searched_span_s(self.scenario)

    @property
    def searched_span_note(self) -> str | None:
        """The span computed and sampled cells were searched over, when the element sets' limits cut it short of
        the horizon; None when no cell is computed or sampled, or the whole horizon was searched (SPC-118)."""
        if not (self._computed() or self._bands()):
            return None
        span = self.searched_span_s
        if span >= self.scenario.horizon_hours * _SECONDS_PER_HOUR:
            return None
        return _SEARCHED_SPAN.format(
            span=span / _SECONDS_PER_HOUR, horizon=self.scenario.horizon_hours,
            end=self.scenario.epoch_utc + timedelta(seconds=span),
        )

    @property
    def propagator_line(self) -> str | None:
        """How far apart the two propagators place these orbits, when computed and sampled rows sit together.

        None once the computed cells are RK45 too (SPC-121): every figure is then one propagator.
        """
        if not (self._computed() and self._bands()) or self._on_rk45():
            return None
        gap = self.propagator_gap_km
        return _PROPAGATORS_UNCOMPARED if gap is None else _PROPAGATOR_LINE.format(gap=gap)

    @property
    def computed_binding_note(self) -> str | None:
        """The binding note naming the side still to bind, when only one side is bound, so no closest approach can
        be computed (SPC-119: it asked for both, so an operator whose red track was bound was told to bind one)."""
        return _COMPUTED_BINDING_NOTES.get(_bound_sides(getattr(self.scenario, "binding", None)))

    @property
    def converged_means(self) -> str | None:
        """CONVERGED_MEANS when any cell is sampled, else None (SPC-117); its element-set variant (SPC-202)."""
        if not self._bands():
            return None
        if self.scenario.miss_rule is MissRule.ELSET_ERROR:
            return CONVERGED_MEANS_ELSET.format(ages=self._elset_ages())
        return CONVERGED_MEANS

    @property
    def seed_line(self) -> str | None:
        """The seeds the sampled rows were drawn on and, under the two-seed rule, the second each one's convergence is
        checked on (SPC-224, evaluation F-35); None when no cell is sampled."""
        if not self._bands():
            return None
        return self._seed_words(SEED_LINE_ONE, SEED_LINE_TWO)

    def _seed_words(self, one: str, two: str) -> str:
        """*one* or *two*, by the scenario's convergence rule, with the seeds its hypotheses carry (SPC-224)."""
        seeds = sorted({a.hypothesis.hypothesis.random_seed for a in self.scenario.adversary_actions if a.hypothesis})
        named = named_list([str(s) for s in seeds])
        if self.scenario.convergence_rule is ConvergenceRule.ONE_SEED:
            return one.format(seeds=named)
        return two.format(seeds=named, checks=named_list([str(second_seed(s)) for s in seeds]))

    @property
    def tree_seed_line(self) -> str | None:
        """Beside a game tree of more than one turn holding a sampled row: how its later turns are drawn and judged
        (V0.42 review of SPC-224); None for one turn or no sampled row."""
        if self.scenario.turns == 1 or not any(a.hypothesis for a in self.scenario.adversary_actions):
            return None
        return self._seed_words(TREE_SEEDS_LINE_ONE, TREE_SEEDS_LINE_TWO)

    @property
    def score_spread_note(self) -> str | None:
        """SCORE_SPREAD_NOTE when any cell is sampled, else None (SPC-115); its response variant once a response is
        flown in the samples, which points to the burn note only when a burn is sized and the note is shown."""
        if not self._bands():
            return None
        if not self._responses():
            return SCORE_SPREAD_NOTE
        return SCORE_SPREAD_NOTE_WITH_BURNS + (SCORE_SPREAD_BURN_POINTER if self._burn_moves() else "")

    @property
    def row_uncertainty(self) -> tuple[str, ...]:
        """One sentence per adversary row for the Uncertainty column: its spread, or why it has none (SPC-115)."""
        return tuple(_row_uncertainty(row) for row in self.outcome_matrix)

    @property
    def ranked_cells(self) -> list[list[tuple[FriendlyResponse, float, OutcomeMetrics]]]:
        """ranked_per_adversary with each response's cell beside it, matched by response id."""
        index = {r.id: j for j, r in enumerate(self.scenario.friendly_responses)}
        return [
            [(resp, score, self.outcome_matrix[i][index[resp.id]]) for resp, score in ranked]
            for i, ranked in enumerate(self.ranked_per_adversary)
        ]

    @property
    def sampled_caveat(self) -> str | None:
        """What a sampled closest approach does not say, with how far its spread can move a score; None unsampled."""
        bands = self._bands()
        if not bands:
            return None
        w, keep = self.scenario.w_closest_approach, self.scenario.keep_out_km
        delta = max(w * (_norm_ca(band[5], keep) - _norm_ca(band[95], keep)) for band in bands)
        caveats = (
            (_RESULT_CAVEAT_ELSET, _RESULT_CAVEAT_WITH_BURNS_ELSET) if self.scenario.miss_rule is MissRule.ELSET_ERROR
            else (_RESULT_CAVEAT, _RESULT_CAVEAT_WITH_BURNS)
        )
        caveat = caveats[1] if self._responses() else caveats[0]
        ages = self._elset_ages() if self.scenario.miss_rule is MissRule.ELSET_ERROR else ""
        return caveat.format(delta=delta, keep=_keep_out_text(keep), ages=ages)

    @property
    def score_scales_line(self) -> str:
        """How the score values closest approach and our delta-V, at this scenario's keep-out distance (SPC-191)."""
        return SCORE_SCALES_LINE.format(keep=_keep_out_text(self.scenario.keep_out_km))

    @property
    def terms_independent_line(self) -> str:
        """That custody lost and closest approach are separate terms of the score, with nothing joining them
        (SPC-219)."""
        return TERMS_INDEPENDENT_LINE

    # ── The operator's judgements and the code version (SPC-196, evaluation F-05) ──

    @property
    def judgement_head(self) -> str:
        """What heads the list of judgement inputs on the page."""
        from spectre.domain.decision_judgement import JUDGEMENT_HEAD

        return JUDGEMENT_HEAD

    @property
    def judgement_lines(self) -> tuple[JudgementLine, ...]:
        """Every input the operator entered that enters a score or a pick, each tagged with its basis in words."""
        from spectre.domain.decision_judgement import judgement_lines

        sampled = tuple(any(c.figure_bases.closest_approach_km.kind is Basis.SAMPLED for c in row)
                        for row in self.outcome_matrix)
        return judgement_lines(self.scenario, self.row_custody, sampled)

    @property
    def row_input_bases(self) -> tuple[RowInputs, ...]:
        """Per adversary row, the basis of its P, Conf and custody gap share, as its matrix row marks them; the
        remainder row's are the engine's (SPC-203)."""
        from spectre.domain.decision_judgement import remainder_inputs, row_inputs

        return tuple(
            remainder_inputs(self.scenario) if a.remainder else row_inputs(a) for a in self.scenario.adversary_actions
        )

    @property
    def response_input_bases(self) -> dict[str, ResponseInputs]:
        """Per response id, the basis of its cost, reversibility and time to execute, as the headline marks them."""
        from spectre.domain.decision_judgement import response_inputs

        return {r.id: response_inputs(r) for r in self.scenario.friendly_responses}

    @property
    def code_version_line(self) -> str:
        """The code version that computed this result, from its provenance, in words."""
        from spectre.domain.decision_judgement import code_version_line

        return code_version_line(self.provenance)


_ROW_SAMPLED = (
    "Closest approach spread {std:.1f} km (1 sigma) over {n} samples; P5, P50 and P95 known to within {hw:.2f} km. "
    "Score spread across samples {s}."
)
_ROW_LOOKUP = "Lookup: no spread computed."
_ROW_REFUSED = "Not sampled, so no spread: the cells say why."
_ROW_NOT_COMPUTED = "Not computed, so no spread: the cells say why."
_ROW_COMPUTED = "Computed by SGP4 with no burn: one figure, no spread; element-set error is not in it."
_ROW_RK45 = (
    "Computed by RK45 for both orbits, our burn applied where a response names a target: one figure per cell, no "
    "spread; element-set error is not in it."
)
#: _ROW_COMPUTED and _ROW_RK45 once the band is shown beside the miss (SPC-202).
_ROW_COMPUTED_ELSET = (
    "Computed by SGP4 with no burn: one figure, no spread, with element-set error as a band beside it; the score "
    "reads its lower edge. {elset}"
)
_ROW_RK45_ELSET = (
    "Computed by RK45 for both orbits, our burn applied where a response names a target: one figure per cell, no "
    "spread, with element-set error as a band beside it; the score reads its lower edge. {elset}"
)
#: What a computed row's band holds, from its first cell, in its Uncertainty sentence (SPC-202).
_ROW_ELSET = (
    "The band is {e:.1f} km (1 sigma) at the first cell's closest approach, red's {rk:.1f} km (its set {ra:.1f} h old "
    "then) and blue's {bk:.1f} km ({ba:.1f} h old) in quadrature, by " + ELSET_MODEL + "."
)


def _row_uncertainty(row: Sequence[OutcomeMetrics]) -> str:
    """A row's spread, from its first sampled cell, else its first cell: a row is sampled from one series or none.

    With our burn (SPC-121) a response's cell has its own band; the row's first sampled cell speaks for the row.
    """
    cell = next((c for c in row if c.ca_percentiles is not None), row[0])
    if cell.ca_percentiles is not None:
        return _ROW_SAMPLED.format(
            std=cell.ca_std_km, n=cell.ca_samples, hw=cell.ca_half_width_km, s=_spread_figure(cast("float", cell.score_std)),
        )
    found = getattr(cell, "ca_computed", None)
    if found is not None:
        rk45 = found.propagator == RESPONSE_PROPAGATOR
        error = getattr(cell, "ca_elset_error", None)
        if error is not None:
            return (_ROW_RK45_ELSET if rk45 else _ROW_COMPUTED_ELSET).format(elset=_ROW_ELSET.format(**error.words()))
        return _ROW_RK45 if rk45 else _ROW_COMPUTED
    if cell.ca_refusal is None:
        return _ROW_LOOKUP
    return _ROW_NOT_COMPUTED if cell.ca_refusal.startswith(_NOT_COMPUTED) else _ROW_REFUSED


# ── Scoring ────────────────────────────────────────────────────────────────────

class _Figures(NamedTuple):
    """The figures a score is built from, unrounded: custody, its gap, closest approach, our delta-V and the hours
    custody is degraded, which are not in the gap (SPC-179)."""

    custody_maintained:  bool
    custody_gap_hours:   float
    closest_approach_km: float
    delta_v_km_s:        float
    custody_degraded_hours: float = 0.0


#: The share of the custody penalty an hour of degraded custody carries, against 1 for an hour lost and 0 for an
#: hour held. It is the owner's ruling of 2026-11-05 (SPC-179), not a sourced figure: degraded custody can judge
#: how a burn changes the warning time but not whether it is normal, so it scores between held and lost.
DEGRADED_CUSTODY_WEIGHT: float = 0.25


#: The lookup closest approach per adversary action type, km; any other type is 3,000 km.
_BASE_CA_KM: dict[ActionType, float] = {
    ActionType.NO_ACTION: 5000.0,        # no approach threat
    ActionType.MANOEUVRE: 200.0,         # potential approach
    ActionType.SENSOR_RETASK: 10000.0,   # not a physical threat
}
_OTHER_CA_KM = 3000.0
#: The lookup model's rules of thumb, each unsourced and listed in docs/lookup-register.md (SPC-196): a manoeuvre
#: response raises the lookup closest approach to x(1 + 5 cost), a posture change to x(1 + 2 cost); a manoeuvre with no
#: sized burn spends cost x 0.05 km/s; against a manoeuvre, a sensor retask holds custody with a gap of half its time
#: to execute; and a lookup closest approach comes at 0.4 of the horizon.
_MANOEUVRE_CA_PER_COST = 5.0
_POSTURE_CA_PER_COST = 2.0
_LOOKUP_DV_KM_S_PER_COST = 0.05
_RETASK_GAP_SHARE = 0.5
_LOOKUP_TCA_SHARE = 0.4
#: The score's far anchor for closest approach, km: no threat at or beyond it (SPC-191 keeps it from before).
_CA_NORMALISATION_KM = 50_000.0


# ── The lookup model's relations, and the training-only label (SPC-207, evaluation F-17) ──

class LookupRelation(StrEnum):
    """One relation of the lookup model, by the name the register and the label give it, in the register's order.

    None has a source: each is an unsourced judgement (docs/lookup-register.md), so a result resting on any of them
    is labelled training only, naming each. The custody rule has no constant of its own: it reads the row's custody
    gap share, the operator's judgement, and sets which responses keep custody.
    """

    CUSTODY = "custody rule"
    RETASK_GAP = "sensor-retask gap"
    MISS_BY_ACTION = "closest approach by action type"
    MANOEUVRE_MISS = "manoeuvre multiplier"
    POSTURE_MISS = "posture multiplier"
    DELTA_V = "delta-V per cost"
    TCA = "time to closest approach"


#: Red's action types as the closest approach by action type names them; any other is a posture change.
_ACTION_WORDS: dict[ActionType, str] = {
    ActionType.MANOEUVRE: "a manoeuvre", ActionType.NO_ACTION: "no action", ActionType.SENSOR_RETASK: "a sensor retask",
}


def relation_words() -> dict[LookupRelation, str]:
    """Each relation in words, its numbers read from the constants the lookup model holds, so the words cannot say
    one number while the code uses another."""
    by_action = [f"{_BASE_CA_KM[kind]:,.0f} km against {words}" for kind, words in _ACTION_WORDS.items()]
    return {
        LookupRelation.CUSTODY: (
            "custody is lost when red manoeuvres and our response neither manoeuvres nor retasks a sensor, for the "
            "row's custody gap share of the horizon, and is held otherwise"
        ),
        LookupRelation.RETASK_GAP: (
            f"against a manoeuvre, a sensor retask's custody gap is {_RETASK_GAP_SHARE:g} of its time to execute"
        ),
        LookupRelation.MISS_BY_ACTION: (
            f"the closest approach is {', '.join(by_action)} and {_OTHER_CA_KM:,.0f} km against any other action"
        ),
        LookupRelation.MANOEUVRE_MISS: (
            f"our manoeuvre multiplies that closest approach by 1 plus {_MANOEUVRE_CA_PER_COST:g} times its cost"
        ),
        LookupRelation.POSTURE_MISS: (
            f"our posture change multiplies that closest approach by 1 plus {_POSTURE_CA_PER_COST:g} times its cost"
        ),
        LookupRelation.DELTA_V: (
            f"our manoeuvre with no sized burn spends its cost times {from_km_s(_LOOKUP_DV_KM_S_PER_COST):g} m/s of "
            "delta-V"
        ),
        LookupRelation.TCA: f"the closest approach comes at {_LOOKUP_TCA_SHARE:g} of the horizon",
    }


LOOKUP_RELATION_WORDS: dict[LookupRelation, str] = relation_words()
#: The label a result resting on one unsourced relation carries, on screen and in its decision record.
TRAINING_ONLY_ONE = (
    "Training only. This result rests on an unsourced relation of the lookup model, a judgement with no source behind "
    "it (docs/lookup-register.md, SPC-207), so use it to train, not to decide: {relations}."
)
#: What the results page shows of a result that cannot say which relations it rests on: it fails closed, read as
#: resting on every one, as a result that cannot say whether it is modelled is shown as modelled.
TRAINING_ONLY_UNKNOWN = (
    "Training only. This result cannot say which unsourced relations of the lookup model it rests on, so read it as "
    "resting on every one of them (docs/lookup-register.md, SPC-207): use it to train, not to decide."
)
#: The same, for several.
TRAINING_ONLY_MANY = (
    "Training only. This result rests on unsourced relations of the lookup model, judgements with no source behind "
    "them (docs/lookup-register.md, SPC-207), so use it to train, not to decide: {relations}."
)


def lookup_relations(
    action: AdversaryAction, response: FriendlyResponse, bases: OutcomeBases,
) -> frozenset[LookupRelation]:
    """The relations a cell of *action* against *response* rests on, read from its figures' bases: a figure the
    lookup model set is a lookup. Custody taken at its worst case, a burn at the epoch, is a bound chosen on purpose,
    not the custody rule."""
    used: set[LookupRelation] = set()
    if bases.custody_maintained.kind is Basis.LOOKUP and bases.custody_maintained.note != _WORST_CASE_NOTE:
        used.add(LookupRelation.CUSTODY)
        if action.action_type is ActionType.MANOEUVRE and response.action_type is ActionType.SENSOR_RETASK:
            used.add(LookupRelation.RETASK_GAP)
    if bases.closest_approach_km.kind is Basis.LOOKUP:
        used.add(LookupRelation.MISS_BY_ACTION)
        if response.action_type is ActionType.MANOEUVRE:
            used.add(LookupRelation.MANOEUVRE_MISS)
        elif response.action_type is ActionType.POSTURE_CHANGE:
            used.add(LookupRelation.POSTURE_MISS)
    if bases.delta_v_cost_km_s.kind is Basis.LOOKUP and response.action_type is ActionType.MANOEUVRE:
        used.add(LookupRelation.DELTA_V)
    if bases.time_to_closest_hours.kind is Basis.LOOKUP:
        used.add(LookupRelation.TCA)
    return frozenset(used)


def training_only_label(relations: Sequence[LookupRelation]) -> str | None:
    """The training-only label naming each of *relations*; None for none."""
    if not relations:
        return None
    named = "; ".join(f"the {r.value}, that {LOOKUP_RELATION_WORDS[r]}" for r in relations)
    return (TRAINING_ONLY_ONE if len(relations) == 1 else TRAINING_ONLY_MANY).format(relations=named)


def _tree_nodes(roots: Sequence[Any]) -> Iterator[Any]:
    """Every node under *roots*, depth first, a hand-built node included."""
    for node in roots:
        yield node
        yield from _tree_nodes(getattr(node, "children", ()))


def _node_bases(node: Any) -> OutcomeBases:
    """A node's bases; an unrecorded basis reads as a lookup, never as computed, as a cell's does."""
    bases = getattr(getattr(node, "figures", None), "bases", None)
    return bases if isinstance(bases, OutcomeBases) else LOOKUP_BASES


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
    - custody_gap_hours: when lost, horizon * the row's custody_gap_fraction,
      nothing of ours; never its confidence, which until SPC-161 set it, so
      surer intelligence lengthened our gap; against a SENSOR_RETASK response to a
      manoeuvre, half the response's time to execute. Detection capability is
      not modelled. Friendly reversibility counts only in its own term: it
      used to scale this gap too, so a fully reversible NO_ACTION lost custody
      at no cost and won the minimax ranking (audit F-035)
    - closest_approach_km: a constant per adversary action type, raised by
      response cost for a MANOEUVRE (x(1 + 5 cost)) or POSTURE_CHANGE
      (x(1 + 2 cost)) response
    - time_to_closest_hours: 0.4 of the horizon
    - delta_v_cost_km_s: friendly.cost * 0.05 for a MANOEUVRE response, else 0
    - composite_score: weighted sum of the normalised terms (higher = worse)

    It never reads the action's hypothesis: a sampled row is filled by
    evaluate_scenario from plan_sampling (SPC-112), a computed one from
    plan_computed (SPC-120), and custody from the bound red track's status
    (SPC-123). It refuses a bound scenario (SPC-125): its constants stand
    only where nothing is computed, and a consumer reading them for a bound
    scenario would take a lookup for the figure binding earns.
    """
    if scenario.binding is not None:
        raise ValueError(
            "compute_outcome_metrics is the lookup model, for an unbound scenario; a bound scenario's cells come from "
            "evaluate_scenario, which computes or samples what binding earns"
        )
    return _lookup_cell(adversary, friendly, scenario, None)


class _Built(NamedTuple):
    """What a cell is built from: its figures unrounded, its time to closest approach in hours, and their bases."""

    figures:   _Figures
    tca_hours: float
    bases:     OutcomeBases
    # The closest approach the cell shows, km, when it is not the one scored: a computed miss whose score reads its
    # element-set band's lower edge (SPC-202). None: the figure scored is the figure shown.
    shown_km:  float | None = None


def _outcome(
    scenario: Scenario, friendly: FriendlyResponse, built: _Built, custody: _RowCustody | None, **extra: Any,
) -> OutcomeMetrics:
    """One cell from *built*, with the row's custody in place of the rule of thumb when there is one (SPC-123)."""
    figures = _custodial(built.figures, custody)
    return OutcomeMetrics(
        custody_maintained=figures.custody_maintained,
        custody_gap_hours=round(figures.custody_gap_hours, 2),
        closest_approach_km=round(figures.closest_approach_km if built.shown_km is None else built.shown_km, 1),
        time_to_closest_hours=round(built.tca_hours, 2),
        delta_v_cost_km_s=round(figures.delta_v_km_s, 5),
        composite_score=round(_score(scenario, friendly, figures), 6),
        score_figures=figures,
        figure_bases=_custody_bases(built.bases, custody),
        custody_state=None if custody is None else custody.state,
        # Not rounded: a degraded span under 0.005 h is still degraded, and the cell's reading is read off it.
        custody_degraded_hours=figures.custody_degraded_hours,
        **extra,
    )


def _lookup_cell(
    adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario, custody: _RowCustody | None,
) -> OutcomeMetrics:
    """The lookup model's cell; with the row's custody when it is not the rule of thumb (SPC-123).

    A response that names a target says the target was not used, in the cell and in its delta-V's note (SPC-121).
    """
    figures = _lookup_figures(adversary, friendly, scenario)
    if friendly.burn is None:
        return _outcome(
            scenario, friendly, _Built(figures, scenario.horizon_hours * _LOOKUP_TCA_SHARE, LOOKUP_BASES), custody,
        )
    unused = _TARGET_UNUSED.format(target=friendly.burn.target_km)
    delta_v = FigureBasis(Basis.LOOKUP, f"{LOOKUP_BASES.delta_v_cost_km_s.note}. {unused}")
    bases = dataclasses.replace(LOOKUP_BASES, delta_v_cost_km_s=delta_v)
    built = _Built(figures, scenario.horizon_hours * _LOOKUP_TCA_SHARE, bases)
    return _outcome(scenario, friendly, built, custody, response_refusal=unused)


def _lookup_figures(adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario) -> _Figures:
    """The lookup model's custody, gap, closest approach and delta-V, unrounded."""
    # ── Custody ──────────────────────────────────────────────────────────────
    adversary_is_manoeuvre = adversary.action_type == ActionType.MANOEUVRE
    friendly_is_active     = friendly.action_type in (ActionType.MANOEUVRE, ActionType.SENSOR_RETASK)

    custody_maintained = True
    custody_gap_hours  = 0.0

    if adversary_is_manoeuvre and not friendly_is_active:
        custody_maintained = False
        # The row's share of the horizon, and nothing of ours: how reversible our response is does not shorten
        # the gap. Not its confidence: how sure the intelligence is says nothing of how long we lose custody.
        custody_gap_hours = scenario.horizon_hours * adversary.custody_gap_fraction
    elif adversary_is_manoeuvre and friendly.action_type == ActionType.SENSOR_RETASK:
        # Sensor retask reduces gap but doesn't eliminate manoeuvre risk
        custody_maintained = True
        custody_gap_hours  = friendly.time_to_execute_hours * _RETASK_GAP_SHARE

    # ── Closest approach ─────────────────────────────────────────────────────
    # Phase 1: analytic estimate based on action type pairing
    base_ca_km = _BASE_CA_KM.get(adversary.action_type, _OTHER_CA_KM)

    # Friendly response modifies CA distance
    if friendly.action_type == ActionType.MANOEUVRE:
        ca_km = base_ca_km * (1.0 + friendly.cost * _MANOEUVRE_CA_PER_COST)  # increase separation
    elif friendly.action_type == ActionType.POSTURE_CHANGE:
        ca_km = base_ca_km * (1.0 + friendly.cost * _POSTURE_CA_PER_COST)
    else:
        ca_km = base_ca_km

    # ── ΔV cost ───────────────────────────────────────────────────────────────
    dv_km_s = friendly.cost * _LOOKUP_DV_KM_S_PER_COST if friendly.action_type == ActionType.MANOEUVRE else 0.0

    return _Figures(custody_maintained, custody_gap_hours, ca_km, dv_km_s)


def _keep_out_text(keep_out_km: float) -> str:
    """The keep-out distance as scored, km: the shortest text that reads back as the same float, so an operator's
    1234.5678 is not shown as 1234.57, and 10.0 reads 10 (SPC-191)."""
    return repr(float(keep_out_km)).removesuffix(".0")


def _norm_ca(ca_km: float, keep_out_km: float) -> float:
    """Closest approach as a score term, in orders of magnitude (SPC-191): 1 at or inside the keep-out distance, 0 at
    50,000 km or more, and ln(50,000 / miss) / ln(50,000 / keep-out) between, so each tenfold of miss is worth the
    same. The only place the score reads a miss."""
    if ca_km <= keep_out_km:
        return 1.0
    if ca_km >= _CA_NORMALISATION_KM:
        return 0.0
    return math.log(_CA_NORMALISATION_KM / ca_km) / math.log(_CA_NORMALISATION_KM / keep_out_km)


def _norm_dv(delta_v_km_s: float) -> float:
    """Our delta-V as a score term, in orders of magnitude (SPC-191): ln(1 + dv) / ln(1 + 1,000) for dv in m/s, 1 at
    the engine's per-burn limit, MAX_BURN_M_S, and above. The only place the score reads our delta-V."""
    return min(math.log1p(from_km_s(delta_v_km_s)) / math.log1p(MAX_BURN_M_S), 1.0)


def score_terms(scenario: Scenario, friendly: FriendlyResponse, figures: _Figures) -> tuple[float, ...]:
    """The composite score's five terms before the weights, each in [0, 1], in the order of the weights: custody,
    closest approach, our delta-V, time to execute and reversibility.

    Each component is normalised to [0, 1] with domain assumptions:
    custody loss 0 when maintained, 1 for a full-horizon gap, each hour degraded
    counting DEGRADED_CUSTODY_WEIGHT of an hour lost (SPC-179); closest approach
    by _norm_ca, in orders of magnitude from the scenario's keep-out distance to
    50,000 km; our delta-V by _norm_dv, in orders of magnitude up to the 1,000 m/s
    per-burn limit (SPC-191); time to execute 0 to the full horizon;
    reversibility inverted, a reward. The weight stability reads them (SPC-205): the score is linear in each weight.
    """
    custody_h     = figures.custody_gap_hours + DEGRADED_CUSTODY_WEIGHT * figures.custody_degraded_hours
    norm_custody  = 0.0 if figures.custody_maintained else min(custody_h / scenario.horizon_hours, 1.0)
    norm_ca       = _norm_ca(figures.closest_approach_km, scenario.keep_out_km)   # high CA = low score (good)
    norm_dv       = _norm_dv(figures.delta_v_km_s)
    norm_time     = min(friendly.time_to_execute_hours / scenario.horizon_hours, 1.0)
    norm_rev      = 1.0 - friendly.reversibility          # reward reversibility → lower score
    return norm_custody, norm_ca, norm_dv, norm_time, norm_rev


def cell_figures(cell: OutcomeMetrics) -> _Figures:
    """The figures *cell*'s score was built from: those the engine kept, unrounded, or, on a cell built by hand, the
    figures it shows (SPC-205)."""
    kept = getattr(cell, "score_figures", None)
    if kept is not None:
        return cast("_Figures", kept)
    return _Figures(cell.custody_maintained, cell.custody_gap_hours, cell.closest_approach_km, cell.delta_v_cost_km_s,
                    getattr(cell, "custody_degraded_hours", 0.0))


def _score(scenario: Scenario, friendly: FriendlyResponse, figures: _Figures) -> float:
    """The composite score (higher = worse), unrounded: score_terms weighted by the scenario's weights, added in the
    order the score has always added them, so every score is the same float as before SPC-205."""
    norm_custody, norm_ca, norm_dv, norm_time, norm_rev = score_terms(scenario, friendly, figures)
    return (
        scenario.w_custody          * norm_custody
        + scenario.w_closest_approach * norm_ca
        + scenario.w_dv_cost          * norm_dv
        + scenario.w_time_to_exec     * norm_time
        + scenario.w_reversibility    * norm_rev
    )


# ── Sampled closest approach (SPC-112) ─────────────────────────────────────────

class Sampler(Protocol):
    """One hypothesis's separation series against the blue track over a window (SPC-110).

    *tick* is passed only when the evaluation runs under a RunControl (SPC-113), so a sampler that takes three
    arguments still serves an evaluation without one; *keep_at_s* only when a game tree asks for its turn boundary
    (SPC-140); *red_then* only when the row carries later burns of a transfer (SPC-184); *elset_error* only when the
    samples draw element-set error (SPC-202), which is every bound row under that rule.
    """

    # PLR0913: the series' own keywords, each passed only when used.
    def __call__(  # noqa: PLR0913
        self, hypothesis: ManoeuvreHypothesis, blue: BlueTrack, window: SeparationWindow, /, *,
        tick: Tick | None = ..., blue_burns: Sequence[BlueBurn] = ..., keep_at_s: Sequence[float] = ...,
        red_then: Sequence[ManoeuvreHypothesis] = ..., elset_error: ElsetError | None = ...,
    ) -> SeparationSeries: ...


#: The wall time one sampled evaluation may take, in seconds (SPC-113). It runs as a session job the page polls,
#: holding the server's only sampling slot, so this bounds how long a second operator waits too. 300 s is the
#: owner's ruling of 2026-11-05 (SPC-178), raised from 120 s so that larger scenarios and game trees fit.
EVALUATION_BUDGET_S: float = 300.0
#: The rate the cap assumes, in sample-hours per second of wall time: about a fifth under the slowest measured,
#: 51 (plane_change Evasive, 500 samples over 11.7 h, 115.7 s, with other work on the machine; the same case ran
#: at 74 and 75 idle). 40 was chosen under the 120 s budget, when a rate of 50 left that case 4.3 s to spare, too
#: little for a loaded server not to refuse it part-way after holding the only sampling slot for the whole budget.
#: Under the 300 s budget, at 40 the cap's worst case takes about 235 s at 51, leaving 65 s. See _cost for the table.
_SLOWEST_SAMPLE_HOURS_PER_S = 40.0
#: The most sample-hours one evaluation may run: what EVALUATION_BUDGET_S covers at _SLOWEST_SAMPLE_HOURS_PER_S.
#: A row costs the larger of its samples times the horizon and the hours its series integrates
#: (separation_integration_s, which counts any burn before the window), plus SET_UP_S_PER_SAMPLE for each
#: sample; the rows that would run are summed before any of them runs. The cap refuses what cannot fit before
#: anything runs; the budget, checked after every sample, refuses what overruns anyway.
MAX_SAMPLE_HOURS: float = EVALUATION_BUDGET_S * _SLOWEST_SAMPLE_HOURS_PER_S
#: What one sample costs whatever its window, in seconds of sample time: its solve_ivp set-up and its
#: closest-approach search. Fitted as wall = a x sample-hours + b x samples over six evaluations from 58
#: samples over 10 h to 20,000 over 0.028 h: b / a = 0.146 h, rounded up to 9 minutes. Without it the cap did
#: not bound wall time: 20,000 samples over 0.028 h counted 560 sample-hours and ran for 49 s.
SET_UP_S_PER_SAMPLE: float = 540.0
#: How far, km, the hypothesis's pre-burn position may sit from the bound red track at its burn time. J2000
#: against TEME differs by about 46 km at LEO radius and 275 km at GEO in 2026, so a frame mix is caught.
START_TOLERANCE_KM: float = 10.0
#: How far, km/s, the hypothesis's pre-burn velocity may sit from the bound red track's at its burn time (SPC-116).
#: Coarse on purpose. The element set's own error allows about 11 m/s within START_TOLERANCE_KM, so nothing finer
#: is honest; a units slip is a factor of 1,000, and another object at a crossing differs by hundreds of m/s (394 m/s
#: in the plane-change reference case at 1,411 s, 10.4 km apart). A frame mix is caught first by position (46 km at
#: LEO), its velocity effect being only about 50 m/s there. A burn under 100 m/s already folded into the state is
#: not caught here, so _after_burn stays the guard for that.
START_VELOCITY_TOLERANCE_KM_S: float = 0.1
_SECONDS_PER_HOUR = 3600.0
_TENTH_HOUR_S = 360.0

#: Custody may be computed in a refused cell (SPC-123), so a refusal speaks for the closest approach alone.
_LOOKUPS = " This cell's closest approach is a lookup."
_OVER_CAP = (
    "Not sampled: this scenario needs at least {total:,} sample-hours (samples times the hours each is "
    "propagated, counting any burn before the window, plus {set_up:g} minutes of set-up for each sample, across "
    "{rows}), above the {cap:,.0f} one evaluation may run within its {budget:g} s budget. "
)
_SHORTEN = "At these sample counts the longest horizon that fits is {h:.1f} h."
_NO_HORIZON = (
    "No horizon of 0.1 h or more fits at these sample counts: take fewer samples, at least {least}, or start the "
    "scenario nearer the burn."
)
_TOO_FEW = "Not sampled: {n} samples are fewer than the {least} the convergence check needs."
_STALE = (
    "Not sampled: the {side} orbit is out of date, at its limit already or of unknown age, so a miss sampled from "
    "it would not be earned."
)
_BURN_PAST_SPAN = (
    "Not sampled: the burn at {burn:%Y-%m-%d %H:%M} UTC is after {end:%Y-%m-%d %H:%M} UTC, when the {side} element "
    "set passes its limit, so the window this row can earn holds no burn and its figure would be the no-burn one."
)
_AFTER_BURN = (
    "Not sampled: the red element set dates from {epoch:%Y-%m-%d %H:%M} UTC, after the burn at "
    "{burn:%Y-%m-%d %H:%M} UTC, so it may already include the burn, and sampling would apply it twice."
)
#: _AFTER_BURN for a row of several burns each at or before the red set's epoch, the first at it (SPC-184).
_AT_EVERY_BURN = (
    "Not sampled: the red element set dates from {epoch:%Y-%m-%d %H:%M} UTC, at or after every burn of this row's "
    "transfer, so it may already include each, and sampling would apply them twice."
)
_NO_STATE = "Not sampled: the {side} element set cannot be propagated to {when:%Y-%m-%d %H:%M} UTC."
_START_MISMATCH = (
    "Not sampled: the hypothesis starts {d:.1f} km from the bound red track at its burn time, more than "
    "{tol:g} km, so it was built from another element set, time or frame."
)
_VELOCITY_MISMATCH = (
    "Not sampled: the hypothesis starts {dv:,.1f} m/s from the bound red track's velocity at its burn time, more "
    "than {tol:g} m/s, so its velocity is in other units or from another object."
)
_FAILED = "Not sampled: {k} of {n} samples failed to propagate{reentered}, and a P5 without them could hide the closest."
_REENTERED = ", {r} of them by re-entering below {floor:g} km"
_BUDGET_PART = (
    "Not sampled: this evaluation's {budget:g} s budget ran out after {k:,} of {n:,} samples of this hypothesis, "
    "and a P5 from part of them would not be earned. Take fewer samples or a shorter horizon."
)
_BUDGET_SECOND = (
    "Not sampled: this evaluation's {budget:g} s budget ran out after {k:,} of {n:,} samples of this hypothesis "
    "drawn on the second seed its convergence is checked on, so whether it converged is not known. Take fewer "
    "samples or a shorter horizon."
)
_BUDGET_NONE = (
    "Not sampled: this evaluation's {budget:g} s budget ran out before this hypothesis started. Take fewer samples "
    "or a shorter horizon."
)
_UNCONVERGED = (
    "Not sampled: P5, P50 and P95 are known only to within {hw:.1f} km, wider than the {tol:.1f} km this miss needs "
    "(1 km, or 5 % of P5 where that is larger), drawn on seed {seed}. Take more samples, with a shorter horizon if "
    "that goes over the {cap:,.0f} sample-hour cap."
)
#: A row whose draw on its own seed converged and whose draw on the second did not (SPC-224, evaluation F-35): the
#: seeds disagree, so whether it converged is the luck of one draw, and it is not converged.
_SEEDS_DIFFER = (
    "Not sampled: the samples converged on seed {seed}, known to within {hw:.2f} km against the {tol:.2f} km this "
    "miss needs, but not on seed {check}, the second its convergence is checked on, where they are known only to "
    "within {chw:.2f} km against {ctol:.2f} km. The two seeds disagree, so the band would rest on the luck of one "
    "draw, and the row is not converged. Take more samples, with a shorter horizon if that goes over the "
    "{cap:,.0f} sample-hour cap."
)
#: The sampled basis note. P5 carries its own half-width and convergence's figure, the widest of the three, is named
#: apart (SPC-213, F-26); the integrator's own error ends it (SPC-214, F-27).
_SAMPLED_CA_NOTE = (
    "P5 of {n} sampled misses, known to within {hw5:.2f} km (95 % bootstrap): 1 in 20 samples came closer. "
    "Convergence is judged on the widest of the P5, P50 and P95 half-widths, {hw:.2f} km. Each sample is the "
    "hypothesis's burn drawn from its delta-V, pointing, timing and drag spreads, propagated with the blue asset "
    "over {span:.1f} h of the {horizon:g} h horizon from the scenario epoch, while both element sets are within "
    "their limits, by RK45 with J2 and exponential drag; the element sets' own errors are not sampled, {ours}; "
    "{integrator}"
)
#: _SAMPLED_CA_NOTE once each sample draws element-set error (SPC-202): SAMPLED_ELSET in place of its last clause.
_SAMPLED_CA_NOTE_ELSET = (
    "P5 of {n} sampled misses, known to within {hw5:.2f} km (95 % bootstrap): 1 in 20 samples came closer. "
    "Convergence is judged on the widest of the P5, P50 and P95 half-widths, {hw:.2f} km. Each sample is the "
    "hypothesis's burn drawn from its delta-V, pointing, timing and drag spreads, propagated with the blue asset "
    "over {span:.1f} h of the {horizon:g} h horizon from the scenario epoch, while both element sets are within "
    "their limits, by RK45 with J2 and exponential drag; {elset}; {ours}; {integrator}"
)
#: How long RK45 runs for a sampled row, before the integrator's error for that span (V0.40 review).
_INTEGRATED = "RK45 runs up to {h:.1f} h here, from {start}; "
_FROM_BURN = "the burn to the window's end"
_FROM_WINDOW = "the window's start to its end"
_NO_BURN_ENDING = "and our response is not applied to the blue orbit"
_BURN_ENDING = "and our burn is applied to the blue asset in every sample"
_SAMPLED_TIME_NOTE = (
    "earliest time of closest approach among the samples at or below P5, of {n} samples over {span:.1f} h of the "
    "{horizon:g} h horizon from the scenario epoch; RK45 with J2 and exponential drag"
)
_CELL_CAVEAT = "1 in 20 samples came closer than P5; the closest of {n} was {closest:.1f} km."
_EDGE_CAVEAT = (
    " In {k} of {n} samples the objects were still closing when the window ended, so the closest approach may "
    "come after it."
)
_OPENING_CAVEAT = (
    " In {k} of {n} samples the objects were already opening when the window began, so the closest approach was "
    "before it."
)
_RESULT_CAVEAT = (
    "Sampled cells score on P5, the miss that 1 in 20 samples beat, not the median. The spread covers only the "
    "hypothesis: its delta-V, pointing, timing and drag. Element-set errors, and the hypothesis being wrong, are "
    "not in it. Our response is not applied to the blue orbit yet, so every response in a sampled row has the "
    "same closest approach. The score values closest approach in orders of magnitude from the {keep} km keep-out "
    "distance to 50,000 km, so the sampled spread moves it by at most {delta:.4f} here."
)
#: _RESULT_CAVEAT once a response's burn is sized (SPC-121).
_RESULT_CAVEAT_WITH_BURNS = (
    "Sampled cells score on P5, the miss that 1 in 20 samples beat, not the median. The spread covers only the "
    "hypothesis: its delta-V, pointing, timing and drag. Element-set errors, the hypothesis being wrong and our "
    "burn's execution error are not in it. A response with a target separation applies our burn, sized on the "
    "hypothesis's nominal burn, to the blue asset in every sample, so its cells differ from the rest of the row. The "
    "score values closest approach in orders of magnitude from the {keep} km keep-out distance to 50,000 km, so "
    "the sampled spread moves it by at most {delta:.4f} here."
)
#: _RESULT_CAVEAT and _RESULT_CAVEAT_WITH_BURNS once each sample draws element-set error (SPC-202).
_RESULT_CAVEAT_ELSET = (
    "Sampled cells score on P5, the miss that 1 in 20 samples beat, not the median. The spread covers the "
    "hypothesis, its delta-V, pointing, timing and drag, and each object's element-set error along track, drawn in "
    "every sample from " + ELSET_MODEL + ", at its set's age at the scenario epoch: {ages}. Element-set error across "
    "track, and the hypothesis being wrong, are not in it. Our response is not applied to the blue orbit yet, so "
    "every response in a sampled row has the same closest approach. The score values closest approach in orders of "
    "magnitude from the {keep} km keep-out distance to 50,000 km, so the sampled spread moves it by at most "
    "{delta:.4f} here."
)
_RESULT_CAVEAT_WITH_BURNS_ELSET = (
    "Sampled cells score on P5, the miss that 1 in 20 samples beat, not the median. The spread covers the "
    "hypothesis, its delta-V, pointing, timing and drag, and each object's element-set error along track, drawn in "
    "every sample from " + ELSET_MODEL + ", at its set's age at the scenario epoch: {ages}. Element-set error across "
    "track, the hypothesis being wrong and our burn's execution error are not in it. A response with a target "
    "separation applies our burn, sized on the hypothesis's nominal burn, to the blue asset in every sample, so its "
    "cells differ from the rest of the row. The score values closest approach in orders of magnitude from the "
    "{keep} km keep-out distance to 50,000 km, so the sampled spread moves it by at most {delta:.4f} here."
)
#: Shown with the sampled caveat when any cell is sampled (SPC-117): what a converged band is, in the operator's terms.
CONVERGED_MEANS = (
    "Converged means P5, P50 and P95 are each known to within 1 km, or to within 5 % of P5 where that is larger "
    "(95 % bootstrap): more samples would move them by less than that. Whether a move that size matters depends "
    "on how close is too close for your asset, which this page is not told. It says nothing about element-set error "
    "or the hypothesis being wrong."
)
#: Beside CONVERGED_MEANS (SPC-224, evaluation F-35): the seed every sample is drawn on, and the second each row's
#: convergence is checked on; a record 0.28.0 to 0.41.0 wrote replays on its one seed and says so.
SEED_LINE_TWO = (
    "Every sample in the outcome matrix is drawn on seed {seeds}, and the figures shown are that draw's. Each row's "
    "convergence is checked on seed {checks} as well, a second, independent draw, and a row is converged only when "
    "both draws are: a row whose two draws disagree is not sampled, and its cells say so. A game tree's later turns "
    "are drawn otherwise, and the tree says how."
)
SEED_LINE_ONE = (
    "Every sample in the outcome matrix is drawn on seed {seeds}. This result is under the rule of 0.28.0 to 0.41.0, "
    "which judged convergence on that one draw, as the record it replays was evaluated."
)
#: Beside a game tree of more than one turn holding a sampled row (V0.42 review): turn 1 is the matrix's row, checked
#: on two seeds; each later turn draws on a seed derived from the row's, the turn and the branch (decision_tree
#: _seeded), and each sequence's closest approach is judged converged on that one draw.
TREE_SEEDS_LINE_TWO = (
    "Turn 1's sampled rows are the matrix's, drawn on seed {seeds} and checked on seed {checks} as well. Turns 2 "
    "and 3 draw each branch's samples afresh on a seed derived from the row's seed, the turn and the branch, and each "
    "sequence's closest approach is judged converged on that one draw, not checked on a second."
)
TREE_SEEDS_LINE_ONE = (
    "Every turn's sampled figures are judged converged on one draw: turn 1 on seed {seeds}, and turns 2 and 3 on a "
    "seed derived from it, the turn and the branch, as the record it replays was built."
)
#: CONVERGED_MEANS once each sample draws element-set error (SPC-202).
CONVERGED_MEANS_ELSET = (
    "Converged means P5, P50 and P95 are each known to within 1 km, or to within 5 % of P5 where that is larger "
    "(95 % bootstrap): more samples would move them by less than that. Whether a move that size matters depends "
    "on how close is too close for your asset, which this page is not told. It says nothing about whether the "
    "element-set error drawn is right, " + ELSET_MODEL + ", at each set's age at the scenario epoch ({ages}), or "
    "about the hypothesis being wrong."
)
#: Both sets' ages at the scenario epoch, in the result's sentences under SPC-202's rule.
ELSET_AGES = "red's set {ra:.1f} h old and blue's {ba:.1f} h old"
#: The hover on a lookup cell's closest approach (SPC-115): it has no band to show.
LOOKUP_CELL_TITLE = "Lookup: a fixed figure, with no distribution."
#: Shown once under the sampled caveat when any cell is sampled (SPC-115).
SCORE_SPREAD_NOTE = (
    "Score spread is the 1-sigma spread of the composite score across samples, from the closest-approach term "
    "alone. Every miss at or inside the keep-out distance scores the full penalty, so a band inside it shows no "
    "spread however wide it is; a small spread does not mean the outcome is certain. Our response is not applied "
    "to the blue orbit, so within a sampled row the ranking is decided by lookup figures."
)
#: SCORE_SPREAD_NOTE once a response with a target separation is flown in the samples, a burn of none included
#: (SPC-121, SPC-191).
SCORE_SPREAD_NOTE_WITH_BURNS = (
    "Score spread is the 1-sigma spread of the composite score across samples, from the closest-approach term "
    "alone. Every miss at or inside the keep-out distance scores the full penalty, so a band inside it shows no "
    "spread however wide it is; a small spread does not mean the outcome is certain. A response given a target "
    "separation is flown in every sample, so its cells can differ from the rest of the row."
)
#: Added to SCORE_SPREAD_NOTE_WITH_BURNS once a burn is sized, when the burn note is shown (SPC-191).
SCORE_SPREAD_BURN_POINTER = (
    " Our burn moves the ranking by the change in the closest-approach term, against the delta-V term it adds; "
    "the burn note gives both for the cell whose score the burn moves most."
)
#: A row whose action carries a hypothesis in a scenario not bound on both sides.
UNSAMPLED_ROW_NOTE = (
    "Hypothesis carried, not sampled: bind a red track and a blue asset to sample its closest approach."
)


class RowSampling(NamedTuple):
    """One eligible row's separation series, or why it was not sampled; never both.

    *sized* holds each response's burn sized on the hypothesis's nominal burn, or why it was not (SPC-121).
    *spent* is True when the refusal is the evaluation's budget running out, so a game tree can say so (SPC-140).
    """

    series:  SeparationSeries | None
    refusal: str | None
    sized:   tuple[SizedBurn | BurnRefusal, ...] = ()
    spent:   bool = False


class _Row(NamedTuple):
    """What an eligible row is checked and sampled from."""

    hypothesis: ManoeuvreHypothesis
    red:        BoundElset
    blue:       BoundElset
    blue_track: BlueTrack | None   # blue's SGP4 state at the window start
    red_track:  BlueTrack | None   # red's SGP4 state at the hypothesis's burn
    window:     SeparationWindow   # from the scenario epoch over the span searched (SPC-118)
    horizon_s:  float
    # The later burns of the row's transfer it applies, after *hypothesis*, its first applied (SPC-184).
    then:       tuple[ManoeuvreHypothesis, ...] = ()
    # Every burn of the row's transfer is at or before the red element set's epoch, so none is applied (SPC-184).
    none_applied: bool = False
    # Each side's element-set error at the scenario epoch, which every sample draws (SPC-202); None under the rule
    # of 0.28.0 to 0.31.0.
    elset_error: ElsetError | None = None
    # Whether its convergence is checked on a second seed too (SPC-224); False under the rule of 0.28.0 to 0.41.0.
    two_seeds: bool = False

    @property
    def seeds(self) -> int:
        """How many draws of the row are charged against the cap: two when convergence is checked on a second."""
        return 2 if self.two_seeds else 1


def _refusal(sentence: str) -> str:
    return sentence + _LOOKUPS


def _too_few(row: _Row) -> str | None:
    n = row.hypothesis.n_samples
    return _TOO_FEW.format(n=n, least=_MIN_CONVERGENCE_SAMPLES) if n < _MIN_CONVERGENCE_SAMPLES else None


def _stale(row: _Row) -> str | None:
    """An orbit out of date, of unknown age or at its limit already earns no span to sample over (SPC-118)."""
    side = _unearned_side(row.red, row.blue)
    return None if side is None else _STALE.format(side=side)


def _burn_past_span(row: _Row) -> str | None:
    """A burn at or after the end of the span the row earns, when a limit cut it short, leaves the no-burn figure."""
    span = row.window.span_s
    burn_s = (row.hypothesis.epoch_utc - row.window.start_utc).total_seconds()
    if span >= row.horizon_s or burn_s < span:
        return None
    side = min((row.red, row.blue), key=_earned_s).side
    return _BURN_PAST_SPAN.format(
        burn=row.hypothesis.epoch_utc, end=row.window.start_utc + timedelta(seconds=span), side=side,
    )


def _after_burn(row: _Row) -> str | None:
    """An element set fitted after the burn may already include it, and the series would then apply it twice.

    The start check below cannot see this: an impulsive burn changes velocity, not position, so an element set
    that includes the burn sits where the pre-burn track does at the burn time.
    """
    epoch, burn = row.red.epoch, row.hypothesis.epoch_utc
    if epoch is not None and epoch > burn:
        return _AFTER_BURN.format(epoch=epoch, burn=burn)
    # A transfer whose burns all sit at or before the set's epoch, the first exactly at it (SPC-184).
    return _AT_EVERY_BURN.format(epoch=epoch) if row.none_applied else None


def _no_state(row: _Row) -> str | None:
    if row.blue_track is None:
        return _NO_STATE.format(side="blue", when=row.window.start_utc)
    if row.red_track is None:
        return _NO_STATE.format(side="red", when=row.hypothesis.epoch_utc)
    return None


def _start_mismatch(row: _Row) -> str | None:
    """The start's position against the bound red track at the burn time; _velocity_mismatch checks its velocity.

    Within the 10 km tolerance, velocity may differ by about 11 m/s from the element set's own error, more than
    the 2 m/s archetype burns, so no velocity check could tell an included burn apart (_after_burn does).
    """
    red = cast("BlueTrack", row.red_track)   # _no_state, run before this, refused a row without one
    pre = np.asarray(row.hypothesis.pre_manoeuvre_state_eci_km, dtype=float)
    d = float(np.linalg.norm(pre[:3] - red.state_eci_km[:3]))
    return None if d <= START_TOLERANCE_KM else _START_MISMATCH.format(d=d, tol=START_TOLERANCE_KM)


def _velocity_mismatch(row: _Row) -> str | None:
    """The start's velocity against the bound red track at the burn time, to START_VELOCITY_TOLERANCE_KM_S.

    Catches a velocity in other units or taken from another object; passing it is not validation.
    """
    red = cast("BlueTrack", row.red_track)   # _no_state, run before this, refused a row without one
    pre = np.asarray(row.hypothesis.pre_manoeuvre_state_eci_km, dtype=float)
    dv = float(np.linalg.norm(pre[3:] - red.state_eci_km[3:]))
    if dv <= START_VELOCITY_TOLERANCE_KM_S:
        return None
    return _VELOCITY_MISMATCH.format(dv=from_km_s(dv), tol=from_km_s(START_VELOCITY_TOLERANCE_KM_S))


def _failed(series: SeparationSeries) -> str | None:
    if series.n_failed <= 0:
        return None
    r = series.n_reentered
    reentered = _REENTERED.format(r=r, floor=REENTRY_FLOOR_KM) if r > 0 else ""
    return _FAILED.format(k=series.n_failed, n=series.n_samples_run, reentered=reentered)


def _unconverged(series: SeparationSeries) -> str | None:
    """Why a series that did not converge is refused: on its own seed, or, converged there, on the second (SPC-224)."""
    if series.converged:
        return None
    check = series.check
    if check is not None and series.percentile_half_width_km <= series.tolerance_km:
        return _SEEDS_DIFFER.format(
            seed=series.random_seed, hw=series.percentile_half_width_km, tol=series.tolerance_km, check=check.seed,
            chw=check.half_width_km, ctol=check.tolerance_km, cap=MAX_SAMPLE_HOURS,
        )
    return _UNCONVERGED.format(
        hw=series.percentile_half_width_km, tol=series.tolerance_km, cap=MAX_SAMPLE_HOURS, seed=series.random_seed,
    )


#: Checked in this order before anything runs; the first that speaks refuses the row.
_PRE_RUN_CHECKS: tuple[Callable[[_Row], str | None], ...] = (
    _too_few, _stale, _burn_past_span, _after_burn, _no_state, _start_mismatch, _velocity_mismatch,
)
#: Checked in this order once the series has run.
_POST_RUN_CHECKS: tuple[Callable[[SeparationSeries], str | None], ...] = (_failed, _unconverged)


def _first_refusal[T](subject: T, checks: tuple[Callable[[T], str | None], ...]) -> str | None:
    for check in checks:
        refusal = check(subject)
        if refusal is not None:
            return _refusal(refusal)
    return None


#: The share of a sample's own cost one more search against a burnt blue arc adds (SPC-121): rounded up from the
#: worst measured, 29 % in LEO over 1 h (3.0 to 3.6 ms a sample; 16 % over 24 h, 42 % at GEO, whose samples run
#: about 12 times cheaper and are refused conservatively anyway).
_BURN_SEARCH_FRACTION = 0.3


def _burn_extra_s(n: int, span_s: float, burns: int) -> float:
    """What sizing and applying *burns* of our burns adds to a row of *n* samples, s of sample time (SPC-121).

    Each burn: one more search per sample, at _BURN_SEARCH_FRACTION of the sample's own cost; MAX_SIZING_TRIALS
    trials to size it, each charged as a sample; and blue's burnt arc, integrated once over the span.
    """
    per_sample = span_s + SET_UP_S_PER_SAMPLE
    return burns * (n * _BURN_SEARCH_FRACTION * per_sample + MAX_SIZING_TRIALS * per_sample + span_s)


def _computed_sizing_s(span_s: float, burns: int) -> float:
    """What sizing *burns* of our burns against the computed rows costs, s of sample time: both RK45 arcs and
    MAX_SIZING_TRIALS trials per burn, each charged as a sample (SPC-121)."""
    return (2 + MAX_SIZING_TRIALS * burns) * (span_s + SET_UP_S_PER_SAMPLE)


def _floor_s(row: _Row, burns: int = 0) -> float:
    """A lower bound on a row's cost, known without drawing a sample: its samples times the window and set-up."""
    n = row.hypothesis.n_samples
    return n * (row.window.span_s + SET_UP_S_PER_SAMPLE) + _burn_extra_s(n, row.window.span_s, burns)


def _cost_s(row: _Row, burns: int = 0) -> float:
    """What a row costs: the larger of its samples times the window and what its series integrates, and set-up."""
    n = row.hypothesis.n_samples
    propagated = max(n * row.window.span_s, separation_integration_s(row.hypothesis, row.window))
    return propagated + n * SET_UP_S_PER_SAMPLE + _burn_extra_s(n, row.window.span_s, burns)


class _Work(NamedTuple):
    """What one evaluation would run: its ready sampled rows, how many of our burns each sizes and applies, and
    the span the computed rows' burns are sized over, None when they are not (SPC-121)."""

    rows:      Sequence[_Row]
    burns:     int = 0
    computed_s: float | None = None

    def at_span(self, span_s: float) -> _Work:
        rows = [_at_span(row, span_s) for row in self.rows]
        return self._replace(rows=rows, computed_s=None if self.computed_s is None else span_s)

    @property
    def span_s(self) -> float:
        return self.rows[0].window.span_s if self.rows else cast("float", self.computed_s)

    @property
    def empty(self) -> bool:
        return not self.rows and self.computed_s is None


def _cost(work: _Work) -> float:
    """What *rows* cost together, in sample-hours; their floor alone once that is over the cap. A row whose
    convergence is checked on a second seed is charged twice, sizing included, which the second draw does not repeat,
    so the charge is never under what runs (SPC-224).

    The exact cost draws every sample to find its burn time, so a row far over the cap is refused on the floor
    without drawing any: a million samples took 1 s and 238 MB just to be costed. The floor bounds the samples
    drawn to 40,000.

    The set-up term was fitted single-threaded in the venv (Python 3.13, scipy 1.17.1, numpy 2.4.6, 4 CPUs) on
    a 4 x 4 grid with one row sampled, LEO 300 km, idle machine, before it existed: 58 samples over 10 h (608.7
    with set-up) took 9.45 s, 200 over 2.9 h (615.8) 8.47 s, 1,000 over 0.5 h (651) 9.05 s, 2,000 over 0.29 h
    (880.6) 12.11 s, 5,000 over 0.115 h (1,325) 17.75 s and 20,000 over 0.028 h (3,560) 49.21 s.

    The cap and budget (SPC-113) rest on these, the reference element sets in tests/unit/_decision_reference.py,
    burn 0.25 h into the window unless stated, cost with set-up:

    plane_change Evasive, 100 samples over 1, 6, 24 and 48 h: 1.4, 7.6, 31.7 and 67.0 s (48 h costs 4,886,
    73 sample-hours a second), all converged, half-width 0.06 km; 500 over 1 h (about 575) 6.9 s; 500 over 12 h
    (6,075) 104.3 s, 58 a second, half-width 0.04 km. coplanar_leo (about 505 km) Evasive, 500 over 12 h (6,075)
    102.0 s, 60 a second; 100 over 1 h and 6 h (615) 2.4 and 10.7 s, 57.5 a second, with other work on the
    machine; Orbit Raise 100 over 1 h and 6 h 2.3 and 11.5 s, half-width 1.76 km (refused at 1 km before SPC-117,
    converged now against 5 % of its 153.25 km P5).
    geo_drift_in Station Keeping, 100 over 6 h and 24 h (2,438) 3.2 and 10.0 s, 243 a second, so GEO is refused
    conservatively; Intercept 100 over 6 h 2.1 s, not converged (3.94 km, P5 7.16 km). plane_change with the burn
    2 h before a 1 h window, 500 samples (1,582) 26.3 s, 60 a second, half-widths 1.77 km (Evasive) and 8.37 km
    (Orbit Raise), refused at 1 km before SPC-117; at seed 42 now 0.95 km against a 41.67 km P5 and 8.51 km against
    842.97 km, both converged.
    plane_change Evasive with the burn at the window start, under a RunControl, 500 over 11.7 h (5,951): 115.66 s
    with other work on the machine, 51 a second, the slowest rate measured; 80.2 s and 79.19 s idle, 74 and 75 a
    second. So MAX_SAMPLE_HOURS assumes 40, about a fifth under 51.

    Two series at once on two threads took 45.6 s against 10.6 s for one alone, so one sampled evaluation runs
    at a time, server-wide. The default hypothesis, 500 samples over 48 h, costs about 24,171 and is refused:
    it would hold the server's only sampling slot for 5 to 8 minutes at the rates measured. Not timed by any test.
    """
    computed = 0.0 if work.computed_s is None else _computed_sizing_s(work.computed_s, work.burns)
    floor = (sum(row.seeds * _floor_s(row, work.burns) for row in work.rows) + computed) / _SECONDS_PER_HOUR
    if floor > MAX_SAMPLE_HOURS:
        return floor
    return (sum(row.seeds * _cost_s(row, work.burns) for row in work.rows) + computed) / _SECONDS_PER_HOUR


def _at_span(row: _Row, span_s: float) -> _Row:
    return row._replace(window=row.window._replace(span_s=span_s))


def _longest_tenths(work: _Work) -> int:
    """The longest horizon, in tenths of an hour, at which *work* fits under the cap; 0 when none does.

    The cost never falls as the horizon grows, so a bisection over whole tenths finds it. The current horizon,
    rounded up, is over the cap, or this would not be asked.
    """
    fits, over = 0, math.ceil(work.span_s / _TENTH_HOUR_S)
    while over - fits > 1:
        mid = (fits + over) // 2
        if _cost(work.at_span(mid * _TENTH_HOUR_S)) > MAX_SAMPLE_HOURS:
            over = mid
        else:
            fits = mid
    return fits


class _OverCap(NamedTuple):
    """What an evaluation over the cap would cost, sample-hours, and what would fit instead."""

    total:  float
    advice: str


def _over_cap(work: _Work) -> _OverCap | None:
    """Whether *work* is over the cap, with the longest horizon that would fit; None when it fits or is empty."""
    if work.empty:
        return None
    total = _cost(work)
    if total <= MAX_SAMPLE_HOURS:
        return None
    tenths = _longest_tenths(work)
    advice = _SHORTEN.format(h=tenths / 10) if tenths > 0 else _NO_HORIZON.format(least=_MIN_CONVERGENCE_SAMPLES)
    return _OverCap(total, advice)


def _counted(work: _Work) -> str:
    """What the cap was summed across: the hypotheses, each on two seeds when its convergence is checked on a second
    (SPC-224), and our burns when any are sized."""
    n = len(work.rows)
    rows = f"{n} hypothesis" if n == 1 else f"{n} hypotheses"
    if any(row.two_seeds for row in work.rows):
        rows += ", each drawn on two seeds"
    if not work.burns:
        return rows
    burns = f"{work.burns} of our burns to size"
    return f"{rows} with {burns}" if n else burns


def _cap_refusal(work: _Work, over: _OverCap) -> str:
    """Why the rows that would run together are refused, naming what would fit."""
    sentence = _OVER_CAP.format(
        total=math.ceil(over.total), set_up=SET_UP_S_PER_SAMPLE / 60.0, rows=_counted(work), cap=MAX_SAMPLE_HOURS,
        budget=EVALUATION_BUDGET_S,
    )
    return _refusal(sentence + over.advice)


#: The stage a row's progress reports while it is drawn again on its second seed (SPC-224).
SECOND_SEED_STAGE = "second seed"


class SamplingProgress(NamedTuple):
    """How far an evaluation has got: row *row* of the *rows* that run, *done* of its *total* samples, or, at
    stage "sizing", trial *done* of at most *total* sizing our burn for the response *label* (SPC-121)."""

    row:       int
    rows:      int
    done:      int
    total:     int
    elapsed_s: float
    stage:     str = "sampling"
    label:     str = ""


def _ignore(_progress: SamplingProgress) -> None:
    """No one is watching the progress."""


@dataclass(frozen=True)
class RunControl:
    """How a sampled evaluation is bounded and watched (SPC-113).

    *budget_s* is the wall time its rows may take together, counted from the
    first row's start on *clock*. *stop* returns a fixed reason once the
    evaluation is no longer wanted, else None. *progress* hears once per
    sample. All three are called on the evaluating thread.
    """

    budget_s: float
    stop:     Callable[[], str | None]
    progress: Callable[[SamplingProgress], None] = _ignore
    clock:    Callable[[], float] = time.monotonic


class EvaluationStoppedError(Exception):
    """A sampled evaluation stopped because it was no longer wanted; *reason* is the stop's fixed sentence."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _BudgetSpentError(Exception):
    """The budget ran out with *done* of *total* samples of a row finished within it."""

    def __init__(self, done: int, total: int) -> None:
        super().__init__(f"{done} of {total}")
        self.done, self.total = done, total


class _Budget:
    """One evaluation's budget across its rows: its clock starts at the first row, and it ticks once per sample."""

    def __init__(self, run: RunControl, rows: int) -> None:
        self.run, self.rows = run, rows
        self.row = 0
        self.started: float | None = None
        self.spent = False
        self.stage, self.label = "sampling", ""

    def _elapsed(self) -> float:
        return self.run.clock() - cast("float", self.started)

    def begin_row(self) -> bool:
        """Whether the next sampled row may start: the first always does, and none once the budget is spent."""
        self.row += 1
        return self.may_start()

    def may_start(self) -> bool:
        """Whether the next piece of work may start, without counting it as a row: the computed rows' sizing."""
        if self.started is None:
            self.started = self.run.clock()
        elif not self.spent:
            self.spent = self._elapsed() > self.run.budget_s
        return not self.spent

    def tick(self, done: int, total: int) -> None:
        """Report progress, then stop when no longer wanted, then refuse the row once the budget is spent.

        A row whose last sample ends past the budget keeps its complete series; the next row will not start.
        Otherwise the budget ran out during sample *done*, so *done* - 1 were finished within it.
        """
        elapsed = self._elapsed()
        self.run.progress(SamplingProgress(self.row, self.rows, done, total, elapsed, self.stage, self.label))
        reason = self.run.stop()
        if reason:
            raise EvaluationStoppedError(reason)
        if elapsed > self.run.budget_s and done < total:
            self.spent = True
            raise _BudgetSpentError(done - 1, total)

    def sizing(self, labels: dict[str, str]) -> SizingTick:
        """A sizing tick that reports the response by name; the stage is sizing until sampling resumes."""

        def tick(key: str, done: int, total: int) -> None:
            self.stage, self.label = "sizing", labels.get(key, "")
            self.tick(done, total)

        return tick

    def sampling(self) -> Tick:
        """The sampling tick, after any sizing."""
        self.stage, self.label = "sampling", ""
        return self.tick

    def second_seed(self) -> Tick:
        """The tick while the row is drawn again on its second seed, so the page says what it waits on (SPC-224)."""
        self.stage, self.label = SECOND_SEED_STAGE, ""
        return self.tick


def _checked(series: SeparationSeries, sized: tuple[SizedBurn | BurnRefusal, ...] = ()) -> RowSampling:
    """A series that has run, or why it is refused."""
    refusal = _first_refusal(series, _POST_RUN_CHECKS)
    return RowSampling(series=None, refusal=refusal) if refusal is not None else RowSampling(series, None, sized)


class _Responses(NamedTuple):
    """The scenario's burns to size (SPC-121): one request per manoeuvre response with a target, keyed by its
    column, and each response's name for the job page."""

    requests: tuple[BurnRequest, ...]
    labels:   dict[str, str]


def _responses_to_size(scenario: Scenario) -> _Responses:
    requests, labels = [], {}
    for j, friendly in enumerate(scenario.friendly_responses):
        spec = friendly.burn
        if spec is None:
            continue
        key = str(j)
        requests.append(BurnRequest(
            key, friendly.time_to_execute_hours * _SECONDS_PER_HOUR, spec.target_km, spec.budget_km_s, spec.axis,
        ))
        labels[key] = friendly.name.strip() or f"response {friendly.id}"
    return _Responses(tuple(requests), labels)


def _size_row(
    row: _Row, blue: BlueTrack, responses: _Responses, budget: _Budget | None,
) -> tuple[SizedBurn | BurnRefusal, ...]:
    """Each response's burn sized on the row's nominal burn; refused for propagation when an arc fails."""
    tick = None if budget is None else budget.sizing(responses.labels)
    later: dict[str, Any] = {"then": row.then} if row.then else {}
    sized = hypothesis_response_plan(row.hypothesis, blue, row.window, responses.requests, tick=tick, **later)
    if sized is None:
        return tuple(BurnRefusal(request.key, "propagation", 0) for request in responses.requests)
    return sized


def _sample(
    row: _Row, sampler: Sampler, sized: tuple[SizedBurn | BurnRefusal, ...], tick: Tick | None,
    keep_at_s: Sequence[float] = (),
) -> SeparationSeries:
    """Run the row's series, passing *tick*, our sized burns and a tree's turn boundary only when there are any
    (SPC-113, SPC-121, SPC-140)."""
    kwargs: dict[str, Any] = {}
    if tick is not None:
        kwargs["tick"] = tick
    if burns := sized_burns(sized):
        kwargs["blue_burns"] = burns
    if keep_at_s:
        kwargs["keep_at_s"] = tuple(keep_at_s)
    if row.then:
        kwargs["red_then"] = row.then
    if row.elset_error is not None:
        kwargs["elset_error"] = row.elset_error
    return sampler(row.hypothesis, cast("BlueTrack", row.blue_track), row.window, **kwargs)


def sized_burns(sized: Sequence[SizedBurn | BurnRefusal]) -> tuple[BlueBurn, ...]:
    """The burns a sampled row applies, in the order its series searches them (SPC-121)."""
    return tuple(s.burn for s in sized if isinstance(s, SizedBurn) and s.burn is not None)


def _on_second_seed(row: _Row) -> tuple[_Row, int]:
    """*row* drawn again on the second seed of its own and of each later burn's, and that seed (SPC-224)."""
    seed = second_seed(row.hypothesis.random_seed)
    then = tuple(dataclasses.replace(h, random_seed=second_seed(h.random_seed)) for h in row.then)
    return row._replace(hypothesis=dataclasses.replace(row.hypothesis, random_seed=seed), then=then), seed


def _second_draw(
    row: _Row, sampler: Sampler, sized: tuple[SizedBurn | BurnRefusal, ...], series: SeparationSeries,
    budget: _Budget | None,
) -> SeparationSeries:
    """*series* with its convergence checked on the second seed, when the row's rule asks and it converged on its own
    with no sample failed; as it is otherwise, since such a series is refused whatever the other seed finds (SPC-224).
    Our burns are not sized again: they are sized on the nominal burn, which no seed moves."""
    if not row.two_seeds or not series.converged or series.n_failed:
        return series
    again, seed = _on_second_seed(row)
    tick = None if budget is None else budget.second_seed()
    return confirmed(series, _sample(again, sampler, sized, tick), seed)


def _run(
    row: _Row, sampler: Sampler, budget: _Budget | None, responses: _Responses | None = None,
    keep_at_s: Sequence[float] = (),
) -> RowSampling:
    """Run a row's series, under *budget* when there is one: a row it does not cover is refused, naming it.

    Our burns are sized first, on the row's nominal burn, and applied in every sample (SPC-121). Under the
    two-seed rule the series is drawn again on the second seed and converged only when both draws are (SPC-224).
    """
    blue = cast("BlueTrack", row.blue_track)   # _no_state refused None
    wanted = responses is not None and bool(responses.requests)
    if budget is None:
        sized = _size_row(row, blue, cast("_Responses", responses), None) if wanted else ()
        series = _sample(row, sampler, sized, None, keep_at_s)
        return _checked(_second_draw(row, sampler, sized, series, None), sized)
    budget_s = budget.run.budget_s
    if not budget.begin_row():
        return RowSampling(None, _refusal(_BUDGET_NONE.format(budget=budget_s)), spent=True)
    try:
        sized = _size_row(row, blue, cast("_Responses", responses), budget) if wanted else ()
    except _BudgetSpentError:
        return RowSampling(None, _refusal(_BUDGET_SIZING.format(budget=budget_s)), spent=True)
    try:
        series = _sample(row, sampler, sized, budget.sampling(), keep_at_s)
    except _BudgetSpentError as spent:
        return RowSampling(
            None, _refusal(_BUDGET_PART.format(budget=budget_s, k=spent.done, n=spent.total)), spent=True,
        )
    try:
        series = _second_draw(row, sampler, sized, series, budget)
    except _BudgetSpentError as spent:
        return RowSampling(
            None, _refusal(_BUDGET_SECOND.format(budget=budget_s, k=spent.done, n=spent.total)), spent=True,
        )
    return _checked(series, sized)


def _eligible_rows(scenario: Scenario) -> list[_Row | None]:
    """A _Row for each action carrying a hypothesis, None for the rest; empty when the scenario cannot be sampled.

    The binding is read only once some action carries a hypothesis, and then
    only for its red and blue element sets.
    """
    if all(a.hypothesis is None for a in scenario.adversary_actions):
        return []
    binding = scenario.binding
    red, blue = (None, None) if binding is None else (binding.red, binding.blue)
    if red is None or blue is None:
        return []
    window = SeparationWindow(start_utc=scenario.epoch_utc, span_s=_searched_span_s(scenario))
    blue_track = elset_state(blue.tle, window.start_utc)
    return [_eligible_row(a, red, blue, blue_track, window, scenario) for a in scenario.adversary_actions]


def sample_error(scenario: Scenario) -> ElsetError | None:
    """Each bound side's element-set error at the scenario epoch, for every sample to draw (SPC-202); None under the
    rule of 0.28.0 to 0.31.0, or with either side unbound."""
    binding = scenario.binding
    if scenario.miss_rule is not MissRule.ELSET_ERROR or binding is None or binding.red is None or binding.blue is None:
        return None
    if binding.red.epoch is None or binding.blue.epoch is None:
        return None   # an age unknown: the row is refused before it runs, so nothing is drawn
    at = elset_error_at(binding, scenario.epoch_utc)
    return ElsetError(red_km=at.red_km, blue_km=at.blue_km)


def elset_error_at(binding: ScenarioBinding, at: datetime) -> ElsetErrorAt:
    """Both bound element sets' along-track error at *at* by spectre/astro/along_track.py's model, with each set's
    age then (SPC-202). Only a computed or sampled cell asks, and both of its sets are current, so both epochs are
    known."""
    red, blue = cast("BoundElset", binding.red), cast("BoundElset", binding.blue)
    red_epoch, blue_epoch = cast("datetime", red.epoch), cast("datetime", blue.epoch)
    return ElsetErrorAt(
        at=at,
        red_age_h=(at - red_epoch).total_seconds() / _SECONDS_PER_HOUR,
        blue_age_h=(at - blue_epoch).total_seconds() / _SECONDS_PER_HOUR,
        red_km=elset_position_error_km(red.tle, red_epoch, at),
        blue_km=elset_position_error_km(blue.tle, blue_epoch, at),
    )


# PLR0913, PLR0917: one row's action, the two bound sides, blue's state and the window, all shared by the scenario.
def _eligible_row(  # noqa: PLR0913, PLR0917
    action: AdversaryAction, red: BoundElset, blue: BoundElset, blue_track: BlueTrack | None,
    window: SeparationWindow, scenario: Scenario,
) -> _Row | None:
    """The row as sampled from its first applied burn, with its later burns (SPC-184); None with no hypothesis."""
    burns = _row_burns(action, red)
    if burns is None:
        return None
    end = window.start_utc + timedelta(seconds=window.span_s)
    return _Row(
        hypothesis=burns.first, red=red, blue=blue, blue_track=blue_track,
        red_track=elset_state(red.tle, burns.first.epoch_utc), window=window,
        horizon_s=scenario.horizon_hours * _SECONDS_PER_HOUR, none_applied=burns.all_dropped,
        # A burn due after the span searched ends is handed to no sample, so no figure flies it.
        then=tuple(h for h in burns.then if h.epoch_utc < end),
        elset_error=sample_error(scenario),
        two_seeds=scenario.convergence_rule is ConvergenceRule.TWO_SEEDS,
    )


def _row_burns(action: AdversaryAction, red: BoundElset | None) -> RowBurns | None:
    """What *action*'s row applies against the bound red element set (SPC-184); None with no hypothesis.

    With no red track bound, or an epoch it cannot read, nothing is dropped.
    """
    carried = action.hypothesis
    if carried is None:
        return None
    epoch, tle = (None, "") if red is None else (red.epoch, red.tle)
    return row_burns(carried.hypothesis, carried.then, epoch, tle)


class _PrePlan(NamedTuple):
    """What an evaluation will run, known before anything does: each row as checked and why it is refused, the
    burns to size, whether the computed rows' burns will be sized, and why not when they are over the cap."""

    rows:      list[_Row | None]
    refusals:  list[str | None]
    responses: _Responses
    sizing:    bool
    sizing_refusal: str | None
    # A game tree's first turn (SPC-140): the computed rows go on RK45 for both orbits even when nothing burns.
    rk45:      bool = False

    @property
    def ready(self) -> int:
        return sum(row is not None and refusal is None for row, refusal in zip(self.rows, self.refusals, strict=True))


def _computes_rows(scenario: Scenario) -> bool:
    """Whether some row's closest approach will be computed: bound on both sides with time earned, and a row whose
    action does not move red and carries no hypothesis."""
    binding = scenario.binding
    if binding is None or binding.red is None or binding.blue is None or _searched_span_s(scenario) <= 0.0:
        return False
    return any(a.action_type in _STILL_ACTIONS and a.hypothesis is None for a in scenario.adversary_actions)


def _pre_plan(scenario: Scenario, *, rk45: bool = False) -> _PrePlan:
    """Each row as checked before anything runs, and why it is refused (the cap included); None where it is not.

    The cap counts our burns to size, in the sampled rows and against the computed rows (SPC-121); over it, the
    rows and the computed burns are refused together.
    """
    rows = _eligible_rows(scenario)
    responses = _responses_to_size(scenario)
    refusals = [None if row is None else _first_refusal(row, _PRE_RUN_CHECKS) for row in rows]
    ready = [row for row, refusal in zip(rows, refusals, strict=True) if row is not None and refusal is None]
    computes = (bool(responses.requests) or rk45) and _computes_rows(scenario)   # the binding is read only then
    sizing = bool(responses.requests) and computes
    forced = rk45 and computes
    work = _Work(ready, len(responses.requests), _searched_span_s(scenario) if sizing or forced else None)
    over = _over_cap(work)
    row_over = None if over is None else _cap_refusal(work, over)
    sizing_refusal = None
    if over is not None and sizing:
        sizing_refusal = _RESPONSE_OVER_CAP.format(
            total=math.ceil(over.total), cap=MAX_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
        ) + over.advice + _DV_LOOKUP
    if over is not None:
        sizing = forced = False
    checked = [None if row is None else refusal or row_over for row, refusal in zip(rows, refusals, strict=True)]
    return _PrePlan(rows, checked, responses, sizing, sizing_refusal, forced)


def _turn_one_cost_h(scenario: Scenario) -> float:
    """What a game tree's first turn costs as one evaluation, sample-hours, with the computed rows on RK45 for both
    orbits whether or not anything burns (SPC-140); the rows refused before anything runs cost nothing."""
    rows = [row for row in _eligible_rows(scenario) if row is not None]
    ready = [row for row in rows if _first_refusal(row, _PRE_RUN_CHECKS) is None]
    requests = _responses_to_size(scenario).requests
    work = _Work(ready, len(requests), _searched_span_s(scenario) if _computes_rows(scenario) else None)
    return 0.0 if work.empty else _cost(work)


def longest_horizon_h(n_samples: int, rows: int = 1, burns: int = 0, seeds: int = 2) -> float:
    """The longest horizon, in hours floored to tenths, at which *rows* hypotheses of *n_samples* fit the cap.

    For the panel's hint (SPC-114): a burn at the scenario epoch integrates about (n + 2) times the horizon per
    row (each sample, blue and red's unburnt arc), and each sample adds SET_UP_S_PER_SAMPLE. A burn before the
    epoch costs more, so this is an upper bound; the cap itself is checked on the real cost. Each of *burns* of
    our burns (SPC-121) adds _BURN_SEARCH_FRACTION of a sample per sample, MAX_SIZING_TRIALS samples to size it
    and blue's burnt arc: m = n (1 + 0.3 k) + 16 k samples, each with set-up, over (m + 2 + k) arcs. Each row is
    charged *seeds* times: twice under the two-seed rule (SPC-224), once under the rule of 0.28.0 to 0.41.0.
    """
    m = n_samples * (1.0 + _BURN_SEARCH_FRACTION * burns) + MAX_SIZING_TRIALS * burns
    set_up_h = seeds * rows * m * SET_UP_S_PER_SAMPLE / _SECONDS_PER_HOUR
    hours = (MAX_SAMPLE_HOURS - set_up_h) / (seeds * rows * (m + 2 + burns))
    return max(math.floor(hours * 10) / 10, 0.0)


def needs_a_run(scenario: Scenario) -> bool:
    """Whether evaluating *scenario* would sample or size anything: some row passes every check before the run and
    the cap, or the computed rows' burns will be sized (SPC-121), or it is a bound game tree (SPC-140).

    False for a lookup scenario and for one whose every eligible row is refused before anything runs; those
    evaluate in milliseconds, so the route can answer them on the request.
    """
    if scenario.turns > 1 and _tree_bound(scenario):
        return True
    pre = _pre_plan(with_remainder(scenario))
    return pre.ready > 0 or pre.sizing


def _tree_bound(scenario: Scenario) -> bool:
    """Whether a game tree could start (SPC-140): both sides bound and current, so it propagates every branch even
    when nothing is sampled or sized. Its other checks refuse it in milliseconds, in the job."""
    binding = scenario.binding
    if binding is None or binding.red is None or binding.blue is None:
        return False
    return _unearned_side(binding.red, binding.blue) is None


def plan_sampling(
    scenario: Scenario, sampler: Sampler = run_separation_series, *, run: RunControl | None = None,
) -> tuple[RowSampling | None, ...]:
    """Each adversary row's separation series, or why it was refused; None for a row that is not eligible.

    A row is eligible when its action carries a hypothesis and the scenario
    is bound to a red track and a blue asset. Each eligible row is checked
    before anything runs: at least 50 samples, both orbits current, the red
    element set no newer than the burn, both element sets propagated (blue to
    the scenario epoch, red to the burn) and the hypothesis starting within
    START_TOLERANCE_KM of the bound red track and within
    START_VELOCITY_TOLERANCE_KM_S of its velocity. The rows that pass are costed
    together against MAX_SAMPLE_HOURS; above it every one is refused, naming
    the longest horizon that would fit, and nothing runs. The rest run one at
    a time on this thread, and a series with a failed sample or not converged
    is refused. Under *run*, the rest share its budget in order: a row it
    does not cover is refused, naming it, and a stop raises
    EvaluationStoppedError. The remainder row, where the rows' P leave one, is a row like any other (SPC-203).
    """
    scenario = with_remainder(scenario)
    pre = _pre_plan(scenario)
    budget = None if run is None else _Budget(run, pre.ready)
    return _plan_sampling(scenario, sampler, budget, pre)


def _plan_sampling(
    scenario: Scenario, sampler: Sampler, budget: _Budget | None, pre: _PrePlan, keep_at_s: Sequence[float] = (),
) -> tuple[RowSampling | None, ...]:
    if not pre.rows:
        return (None,) * len(scenario.adversary_actions)
    return tuple(
        None if row is None else _plan_row(row, refusal, sampler, budget, pre.responses, keep_at_s)
        for row, refusal in zip(pre.rows, pre.refusals, strict=True)
    )


# PLR0913, PLR0917: the row and each thing its sampling plan is drawn from.
def _plan_row(  # noqa: PLR0913, PLR0917
    row: _Row, refusal: str | None, sampler: Sampler, budget: _Budget | None, responses: _Responses,
    keep_at_s: Sequence[float] = (),
) -> RowSampling:
    """A row refused before anything runs, or its series run and checked."""
    return RowSampling(None, refusal) if refusal is not None else _run(row, sampler, budget, responses, keep_at_s)


def _integrated_hours(window: SeparationWindow, burn_at: datetime | None) -> float:
    """The longest span RK45 integrates for a series over *window*, h (V0.40 review): each sample's red arc runs
    from the nominal burn at *burn_at*, back to the window's start or on to its end, so from whichever is earlier,
    the burn or the window's start, to the window's end; blue runs the window."""
    start = window.start_utc if burn_at is None else min(burn_at, window.start_utc)
    end = window.start_utc + timedelta(seconds=window.span_s)
    return (end - start).total_seconds() / _SECONDS_PER_HOUR


#: The seed a sampled cell's figures were drawn on, for its basis note (SPC-224, evaluation F-35), and, under the
#: two-seed rule, the second its convergence was checked on as well; a shown cell converged on both.
SEED_ONE = "drawn on seed {seed}, its convergence judged on that draw alone, as before 0.42.0"
SEED_TWO = "drawn on seed {seed}, its convergence checked on seed {check} as well, which converged too"


def seed_words(series: SeparationSeries) -> str:
    """The seed *series* was drawn on and, when its convergence was checked on a second, that one (SPC-224)."""
    if series.check is None:
        return SEED_ONE.format(seed=series.random_seed)
    return SEED_TWO.format(seed=series.random_seed, check=series.check.seed)


def _sampled_bases(
    series: SeparationSeries, horizon_hours: float, *, burnt: bool = False, drawn: ElsetErrorAt | None = None,
    burn_at: datetime | None = None,
) -> OutcomeBases:
    n, span = len(series.approaches), series.window.span_s / _SECONDS_PER_HOUR
    ours = _BURN_ENDING if burnt else _NO_BURN_ENDING
    integrated = _integrated_hours(series.window, burn_at)
    early = burn_at is not None and burn_at < series.window.start_utc
    integrator = _INTEGRATED.format(h=integrated, start=_FROM_BURN if early else _FROM_WINDOW)
    handover = f"{handover_words(integrated)}; {seed_words(series)}"
    note = (_SAMPLED_CA_NOTE if drawn is None else _SAMPLED_CA_NOTE_ELSET).format(
        n=n, hw5=series.p5_half_width_km, hw=series.percentile_half_width_km, span=span, horizon=horizon_hours,
        ours=ours, integrator=f"{integrator}{integrator_error_words(integrated)}; {handover}",
        elset="" if drawn is None else SAMPLED_ELSET.format(**drawn.words()),
    )
    return outcome_bases(
        custody_maintained=LOOKUP_BASES.custody_maintained,
        custody_gap_hours=LOOKUP_BASES.custody_gap_hours,
        closest_approach_km=FigureBasis(Basis.SAMPLED, note),
        time_to_closest_hours=FigureBasis(
            Basis.SAMPLED, _SAMPLED_TIME_NOTE.format(n=n, span=span, horizon=horizon_hours),
        ),
        delta_v_cost_km_s=LOOKUP_BASES.delta_v_cost_km_s,
    )


def _cell_caveat(series: SeparationSeries) -> str:
    n = len(series.approaches)
    caveat = _CELL_CAVEAT.format(n=n, closest=series.closest_sample_km)
    closing = sum(a.at_window_edge and a.tca_s > 0.0 for a in series.approaches)
    opening = series.n_at_window_edge - closing
    if closing:
        caveat += _EDGE_CAVEAT.format(k=closing, n=n)
    if opening:
        caveat += _OPENING_CAVEAT.format(k=opening, n=n)
    return caveat


def _sampled_cell(
    adversary: AdversaryAction, scenario: Scenario, series: SeparationSeries, custody: _RowCustody | None,
    response: _ResponseCell,
) -> OutcomeMetrics:
    """A cell scored on the sampled P5, with its time the earliest TCA at or below it; the rest are lookups.

    Each sample's miss is scored too, through the same _score, for the composite score's P5, P50, P95 and
    1-sigma spread across samples (SPC-115). The score falls with each order of magnitude of miss between the
    keep-out distance and 50,000 km (SPC-191), so its percentiles mirror the misses'. With our burn (SPC-121),
    *series* is the samples after it and the delta-V is the burn's.
    """
    friendly = response.friendly
    figures = _custodial(_lookup_figures(adversary, friendly, scenario), custody)._replace(
        closest_approach_km=series.miss_km_p5,
    )
    figures = response.figures(figures)
    scores = np.array([
        _score(scenario, friendly, figures._replace(closest_approach_km=a.miss_km)) for a in series.approaches
    ])
    drawn = None if series.elset_error is None else elset_error_at(
        cast("ScenarioBinding", scenario.binding), scenario.epoch_utc,
    )
    burn_at = None if adversary.hypothesis is None else adversary.hypothesis.hypothesis.epoch_utc
    bases = response.bases(_sampled_bases(series, scenario.horizon_hours, burnt=response.burnt, drawn=drawn,
                                          burn_at=burn_at))
    built = _Built(figures, series.earliest_tca_at_or_below_p5_s / _SECONDS_PER_HOUR, bases)
    tca, sampled_tca = _sampled_tca(scenario, series)
    return _outcome(
        scenario, friendly, built, custody, tca_uncertainty=tca, ca_sampled_tca=sampled_tca,
        tca_histogram=_tca_histogram(scenario, series),
        ca_response=response.figure, response_refusal=response.refusal,
        ca_percentiles=series.percentiles,
        ca_std_km=series.miss_km_std,
        ca_samples=len(series.approaches),
        ca_caveat=_cell_caveat(series),
        ca_half_width_km=series.percentile_half_width_km,
        score_percentiles={k: float(np.percentile(scores, k)) for k in _PERCENTILE_KEYS},
        score_std=float(np.std(scores)),
        ca_elset_error=drawn,
    )


def _sampled_tca(scenario: Scenario, series: SeparationSeries) -> tuple[TcaUncertainty, SampledTca]:
    """The uncertainty of a sampled cell's TCA, from the sample that sets it, and the TCA's spread (SPC-118)."""
    index = cast("int", series.earliest_at_or_below_p5_index)   # a converged series has a sample at or below P5
    approach = series.approaches[index]
    speeds = series.closing_speeds_km_s
    speed = speeds[index] if speeds else math.nan
    start = series.window.start_utc
    binding = cast("ScenarioBinding", scenario.binding)
    tca = (
        _tca_uncertainty(binding, start, approach, speed, series.window.span_s) if series.elset_error is None
        else _drawn_tca_uncertainty(binding, scenario.epoch_utc, series.window, (approach, speed))
    )
    hours = np.array([a.tca_s for a in series.approaches]) / _SECONDS_PER_HOUR
    p5, p95 = (float(p) for p in np.percentile(hours, (5, 95)))
    return tca, SampledTca(approach.tca_utc(start), approach.tca_s / _SECONDS_PER_HOUR, p5, p95)


def _tca_histogram(scenario: Scenario, series: SeparationSeries) -> TcaHistogram | None:
    """The samples' TCAs, hours after the scenario epoch, each with its own uncertainty, from its closing speed; the
    samples at an edge of the search, and those too slow to fix a time, counted, not drawn (SPC-124). None when the
    series recorded no closing speed."""
    speeds = series.closing_speeds_km_s
    if not speeds:
        return None
    binding, start, span = cast("ScenarioBinding", scenario.binding), series.window.start_utc, series.window.span_s
    offset_h = (start - scenario.epoch_utc).total_seconds() / _SECONDS_PER_HOUR
    shown = [(a, v) for a, v in zip(series.approaches, speeds, strict=True) if not a.at_window_edge]
    closing = sum(a.at_window_edge and a.tca_s > 0.0 for a in series.approaches)
    drawn = series.elset_error is not None
    return tca_histogram(
        [offset_h + a.tca_s / _SECONDS_PER_HOUR for a, _ in shown],
        [(_drawn_tca_uncertainty(binding, scenario.epoch_utc, series.window, (a, v)) if drawn
          else _tca_uncertainty(binding, start, a, v, span)).sigma_s for a, v in shown],
        n_closing=closing, n_opening=series.n_at_window_edge - closing, undrawn=drawn,
    )


def _response_of(
    results: Sequence[SizedBurn | BurnRefusal], column: int,
) -> SizedBurn | BurnRefusal | None:
    key = str(column)
    return next((result for result in results if result.key == key), None)


def _burn_at(scenario: Scenario, friendly: FriendlyResponse) -> datetime:
    return scenario.epoch_utc + timedelta(hours=friendly.time_to_execute_hours)


def _burnt_series(series: SeparationSeries, after: BurnSeries) -> SeparationSeries:
    """The row's series as it stands after one of our burns: the same samples, against the burnt blue asset."""
    stats = after.stats
    return dataclasses.replace(
        series, approaches=after.approaches, closing_speeds_km_s=after.closing_speeds_km_s, n_failed=after.n_failed,
        miss_km_p5=stats.p5, miss_km_p50=stats.p50, miss_km_p95=stats.p95, miss_km_std=stats.std,
        percentile_half_width_km=stats.half_width_km, converged=stats.converged, tolerance_km=stats.tolerance_km,
        p5_half_width_km=stats.p5_half_width_km, after_burns=(),
    )


def _after_burn_refusal(after: BurnSeries | None, n: int) -> str | None:
    """Why a sampled cell after our burn is not earned: its series is missing, a sample failed, or unconverged."""
    if after is None or after.n_failed > 0:
        failed = n if after is None else after.n_failed
        return _refusal(_AFTER_BURN_FAILED.format(k=failed, n=n))
    if not after.stats.converged and after.stats.half_width_km <= after.stats.tolerance_km:
        # Converged on the hypothesis's own seed, so it was the second seed that did not (SPC-224).
        return _refusal(_AFTER_BURN_SEEDS_DIFFER.format(hw=after.stats.half_width_km, tol=after.stats.tolerance_km))
    if not after.stats.converged:
        return _refusal(_AFTER_BURN_UNCONVERGED.format(hw=after.stats.half_width_km, tol=after.stats.tolerance_km))
    return None


def _sampled_response_cell(
    adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario, plan: _RowPlan, column: int,
) -> OutcomeMetrics:
    """A sampled cell, after our burn where this response's was sized and applied (SPC-121)."""
    sampling = cast("RowSampling", plan.sampling)
    series = cast("SeparationSeries", sampling.series)
    result = _response_of(sampling.sized, column)
    spec = friendly.burn
    if spec is None or result is None:
        return _sampled_cell(adversary, scenario, series, plan.custody, _ResponseCell(friendly, None, None))
    at = _burn_at(scenario, friendly)
    nominal, tca_basis = _nominal_words(adversary, scenario)
    if isinstance(result, BurnRefusal):
        sentence = _response_refusal(result, at, series.window, tca_basis)
        return _sampled_cell(adversary, scenario, series, plan.custody, _ResponseCell(friendly, None, sentence))
    if result.burn is None:
        figure = ResponseFigure(
            result, at, spec.target_km, spec.budget_km_s, sampled_before_p5_km=series.miss_km_p5,
            sampled_under_target=_under_target(series, spec.target_km),
        )
        return _sampled_cell(adversary, scenario, series, plan.custody, _ResponseCell(friendly, figure, None))
    after = next((b for b in series.after_burns if b.burn == result.burn), None)
    refusal = _after_burn_refusal(after, series.n_samples_run)
    if refusal is not None:
        return _refused_cell(_lookup_cell(adversary, friendly, scenario, plan.custody), refusal)
    burnt = _burnt_series(series, cast("BurnSeries", after))
    figure = ResponseFigure(
        result, at, spec.target_km, spec.budget_km_s, sampled_before_p5_km=series.miss_km_p5,
        sampled_after_p5_km=burnt.miss_km_p5, sampled_under_target=_under_target(burnt, spec.target_km),
        nominal=nominal,
    )
    return _sampled_cell(adversary, scenario, burnt, plan.custody, _ResponseCell(friendly, figure, None))


def _nominal_words(adversary: AdversaryAction, scenario: Scenario) -> tuple[str, str]:
    """What a sampled row's burn is sized against and the TCA it is decided on rests on: red's nominal burn, or for
    a row of several burns its nominal transfer, naming how many of them it flies (SPC-184)."""
    red = None if scenario.binding is None else scenario.binding.red
    burns = _row_burns(adversary, red)
    if burns is None or not burns.several:
        return NOMINAL_BURN, _NOMINAL_TCA
    flown = burns.applied_by(scenario.epoch_utc + timedelta(seconds=_searched_span_s(scenario)))
    return (_NOMINAL_TRANSFER.format(k=flown, n=burns.carried),
            _NOMINAL_TRANSFER_TCA.format(k=flown, n=burns.carried))


def _under_target(series: SeparationSeries, target_km: float) -> tuple[int, int]:
    """How many of the series' samples came closer than *target_km*, of how many."""
    return sum(a.miss_km < target_km for a in series.approaches), len(series.approaches)


def _response_refusal(result: BurnRefusal, at: datetime, window: SeparationWindow, basis: str) -> str:
    """Why this response's burn was not sized, ending with its delta-V a lookup (SPC-121).

    A burn after the closest approach names the one it was decided on, the RK45 figure with no burn, and *basis*
    says how it was propagated: never the cell's own TCA, which may be SGP4's or a sample's.
    """
    if result.reason == "after_window":
        return _RESPONSE_AFTER_SPAN.format(at=at, span=window.span_s / _SECONDS_PER_HOUR)
    if result.reason == "after_tca":
        tca = _to_the_minute(window.start_utc + timedelta(seconds=cast("float", result.tca_s)))
        return _RESPONSE_AFTER_TCA.format(at=at, tca=tca, basis=basis)
    reentered = _RESPONSE_REENTERED.format(floor=REENTRY_FLOOR_KM) if result.reason == "reentered" else ""
    return _RESPONSE_FAILED.format(reentered=reentered)


class _ResponseCell(NamedTuple):
    """What one response brings to its cell (SPC-121): our sized burn, or why it was not sized, or neither."""

    friendly: FriendlyResponse
    figure:   ResponseFigure | None
    refusal:  str | None

    @property
    def burnt(self) -> bool:
        return self.figure is not None and self.figure.sized.burn is not None

    def figures(self, figures: _Figures) -> _Figures:
        """*figures* with the burn's delta-V in place of the lookup's."""
        return figures if self.figure is None else figures._replace(delta_v_km_s=self.figure.delta_v_km_s)

    def bases(self, bases: OutcomeBases) -> OutcomeBases:
        """*bases* with our delta-V's: computed for a sized burn; else the lookup, saying why it was not sized."""
        if self.figure is not None:
            delta_v = FigureBasis(Basis.COMPUTED, self.figure.note)
        elif self.refusal is not None:
            delta_v = FigureBasis(Basis.LOOKUP, f"{LOOKUP_BASES.delta_v_cost_km_s.note}. {self.refusal}")
        elif self.friendly.action_type is ActionType.MANOEUVRE:
            delta_v = FigureBasis(Basis.LOOKUP, f"{LOOKUP_BASES.delta_v_cost_km_s.note}. {_ENTER_TARGET}")
        else:
            delta_v = FigureBasis(Basis.COMPUTED, _NO_BURN_DV_NOTE)
        return outcome_bases(
            custody_maintained=bases.custody_maintained, custody_gap_hours=bases.custody_gap_hours,
            closest_approach_km=bases.closest_approach_km, time_to_closest_hours=bases.time_to_closest_hours,
            delta_v_cost_km_s=delta_v,
        )


def _refused_cell(metrics: OutcomeMetrics, refusal: str | None) -> OutcomeMetrics:
    """The lookup cell, with the refusal in the cell and in its closest approach's note; its custody is kept."""
    note = f"{LOOKUP_BASES.closest_approach_km.note}. {refusal}"
    bases = dataclasses.replace(metrics.figure_bases, closest_approach_km=FigureBasis(Basis.LOOKUP, note))
    return dataclasses.replace(metrics, figure_bases=bases, ca_refusal=refusal)


#: The custody figures, which read one burn of a row: the earliest it applies (SPC-184).
_CUSTODY_FIGURES = frozenset({"custody_maintained", "custody_gap_hours"})
#: The figures a sampled row propagates with red making its burns.
_FLOWN_FIGURES = frozenset({"closest_approach_km", "time_to_closest_hours"})


def _burns_suffix(name: str, basis: FigureBasis, cell: OutcomeMetrics, burns: RowBurns, flown: int) -> str:
    """How many of the row's burns one figure applies, in its basis's words (SPC-184)."""
    n = burns.carried
    if name == "composite_score":
        return f"; it applies none of this row's {n} burns itself"
    if basis.kind is Basis.LOOKUP:
        return f"; it applies none of this row's {n} burns"
    if name in _CUSTODY_FIGURES:
        if burns.all_dropped:
            return f"; it reads none of this row's {n} burns, since none is newer than the red element set"
        return f"; it reads burn {burns.applied[0]} of this row's {n}, the earliest applied"
    if name in _FLOWN_FIGURES:
        return (f"; red flies the {flown} of this row's {n} burns due before the span searched ends, each at its own "
                "drawn time if that is inside the span")
    sized = cell.ca_response is not None and cell.ca_response.sized.burn is not None
    return f"; sized against red flying {flown} of this row's {n} burns" if sized else (
        f"; it applies none of this row's {n} burns")


def _burns_named(cell: OutcomeMetrics, burns: RowBurns | None, end: datetime) -> OutcomeMetrics:
    """*cell* with each figure's basis naming how many of the row's burns it applies, for a row of several burns
    (SPC-184); a single burn's cell unchanged. A burn applied after *end*, when the span searched ends, is flown
    by no figure."""
    if burns is None or not burns.several:
        return cell
    flown = burns.applied_by(end)
    named = {
        name: FigureBasis(basis.kind, basis.note + _burns_suffix(name, basis, cell, burns, flown))
        for name, basis in cell.figure_bases.items()
    }
    return dataclasses.replace(cell, figure_bases=OutcomeBases(**named))


def _row_notes(scenario: Scenario, plan: Sequence[RowSampling | None]) -> tuple[str | None, ...]:
    return tuple(
        UNSAMPLED_ROW_NOTE if a.hypothesis is not None and p is None else None
        for a, p in zip(scenario.adversary_actions, plan, strict=True)
    )


# ── Computed closest approach (SPC-120) ────────────────────────────────────────

#: The actions that do not move the red track. In a scenario bound on both sides, a row of one of these without a
#: hypothesis has its closest approach computed: where the pair goes with no burn is that row's outcome.
_STILL_ACTIONS: frozenset[ActionType] = frozenset(
    {ActionType.NO_ACTION, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE},
)
_NOT_COMPUTED = "Not computed: "
_NOT_COMPUTED_STALE = (
    _NOT_COMPUTED + "the {side} orbit is out of date or its age is unknown, so a miss computed from it would not "
    "be earned."
)
_NOT_COMPUTED_SGP4 = (
    _NOT_COMPUTED + "SGP4 could not propagate the {side} element set across the horizon, so a miss without those "
    "instants could hide the closest."
)
#: The RK45 path's altitude floor on the SGP4 path (SPC-200, evaluation F-30).
_NOT_COMPUTED_DECAYED = (
    _NOT_COMPUTED + "the {side} object is below the {floor:g} km re-entry floor at an instant searched, so it has "
    "decayed or is decaying and a miss computed from it would not be earned."
)
_NOT_A_BURN = (
    _NOT_COMPUTED + "a manoeuvre with no hypothesis names no burn, and propagating the orbit as it stands would show "
    "only where it goes if it does not move. Add a manoeuvre hypothesis to sample this row."
)
_COMPUTED_CA_NOTE = (
    "smallest separation of the bound red track {red} and blue asset {blue} over {span:.1f} h of the {horizon:g} h "
    "horizon from the scenario epoch, both propagated by SGP4 from their element sets (red epoch "
    "{re:%Y-%m-%d %H:%M} UTC, blue epoch {be:%Y-%m-%d %H:%M} UTC) with no burn, sampled every {step:g} s and each "
    "local minimum refined to 0.01 s; element-set error is not in it, and our response is not applied to the blue "
    "orbit"
)
_COMPUTED_TIME_NOTE = (
    "time of that closest approach from the scenario epoch, SGP4 for both orbits, refined to 0.01 s and shown to "
    "the minute"
)
_COMPUTED_LINE = "Computed: {miss:.1f} km at {tca:%Y-%m-%d %H:%M} UTC{pm}, {h} h after the scenario epoch; {how}."
_COMPUTED_TITLE = (
    "Computed: {miss:.3f} km at {tca_s:,.2f} s after the scenario epoch, passing at {v:,.0f} m/s; {how}, so one "
    "figure, with no distribution."
)
#: The computed note once our burn put every computed cell on RK45 (SPC-121).
_RK45_CA_NOTE = (
    "smallest separation of the bound red track {red} and blue asset {blue} over {span:.1f} h of the {horizon:g} h "
    "horizon from the scenario epoch, both propagated by RK45 with J2 and exponential drag from their SGP4 states "
    "then (red epoch {re:%Y-%m-%d %H:%M} UTC, blue epoch {be:%Y-%m-%d %H:%M} UTC) {burn}, sampled every {step:g} s "
    "and each local minimum refined to 0.01 s; element-set error is not in it"
)
_RK45_NO_BURN_NOTE = "with no burn"
_RK45_BURN_NOTE = "with our burn applied to the blue asset"
_RK45_TIME_NOTE = (
    "time of that closest approach from the scenario epoch, RK45 for both orbits, refined to 0.01 s and shown to "
    "the minute"
)
_STILL_CLOSING = (
    "Still closing when the search ends, so the closest approach comes after it: this is the separation then, not "
    "an encounter."
)
_ALREADY_OPENING = (
    "Already opening at the scenario epoch: the closest in the horizon is now, and any closer approach was before "
    "it."
)
_SEARCHED_SPAN = (
    "Closest approaches are searched over the first {span:.1f} h of the {horizon:g} h horizon, while both element "
    "sets are within their limits; past {end:%Y-%m-%d %H:%M} UTC a miss would rest on an out-of-date orbit."
)
#: Shown once with the result when any cell is computed (SPC-120). The element-set model is along_track.py's.
COMPUTED_CAVEAT = (
    "Computed cells propagate both bound orbits with SGP4 as their element sets stand, with no burn: where the pair "
    "goes if the red track does not move, so every row whose action does not move it shares one figure. Our "
    "response is not applied to the blue orbit yet, so every response in a computed row has the same closest "
    "approach, and the ranking within it is decided by lookup figures. Element-set error, which the sweep takes as "
    + ERROR_MODEL_WORDS + ", is not in it."
)
#: COMPUTED_CAVEAT once the band is shown beside the miss (SPC-202).
COMPUTED_CAVEAT_ELSET = (
    "Computed cells propagate both bound orbits with SGP4 as their element sets stand, with no burn: where the pair "
    "goes if the red track does not move, so every row whose action does not move it shares one figure. Our "
    "response is not applied to the blue orbit yet, so every response in a computed row has the same closest "
    "approach, and the ranking within it is decided by lookup figures. Element-set error, by " + ELSET_MODEL + ", "
    "is shown beside each computed miss as a band, the miss less and plus both sets' error at the closest approach "
    "in quadrature (1 sigma), read at each set's age then ({ages} at the scenario epoch, older by the time to the "
    "closest approach), and the score reads the band's lower edge: Claude's choice, since you read the closer case "
    "to answer whether it can reach one of yours."
)
#: COMPUTED_CAVEAT once a response's burn is sized (SPC-121).
COMPUTED_CAVEAT_WITH_BURNS = (
    "Computed cells propagate both bound orbits as their element sets stand, with no red burn, so every row whose "
    "action does not move the red track shares its no-burn figure. A response with a target separation applies our "
    "burn to the blue asset, so its cells differ from the rest of the row. Element-set error, which the sweep takes "
    "as " + ERROR_MODEL_WORDS + ", is not in any of them."
)
#: COMPUTED_CAVEAT_WITH_BURNS once the band is shown beside the miss (SPC-202).
COMPUTED_CAVEAT_WITH_BURNS_ELSET = (
    "Computed cells propagate both bound orbits as their element sets stand, with no red burn, so every row whose "
    "action does not move the red track shares its no-burn figure. A response with a target separation applies our "
    "burn to the blue asset, so its cells differ from the rest of the row. Element-set error, by " + ELSET_MODEL + ", "
    "is shown beside each computed miss as a band, the miss less and plus both sets' error at the closest approach "
    "in quadrature (1 sigma), read at each set's age then ({ages} at the scenario epoch, older by the time to the "
    "closest approach), and the score reads the band's lower edge: Claude's choice, since you read the closer case "
    "to answer whether it can reach one of yours. Our burn is sized on the miss itself, not the band, so a response "
    "whose burn is sized scores its own band's lower edge, short of its target by its error."
)
#: Shown with the result once a response's burn put every computed cell on RK45 (SPC-121).
RK45_FOR_BURNS = (
    "Our burn cannot be applied to an element set, so in this result every closest approach is propagated by RK45 "
    "with J2 and exponential drag for both orbits, from their SGP4 states at the scenario epoch. With no burn, SGP4 "
    "puts the closest approach at {sm:.3f} km at {st:%Y-%m-%d %H:%M:%S} UTC and RK45 at {rm:.3f} km at "
    "{rt:%H:%M:%S} UTC: {dm:.3f} km and {dt:.0f} s apart, which is the propagators, not any burn."
)
#: Shown with the result when a burn is sized: what it buys against what it costs in the score (SPC-121, SPC-191;
#: weights are SPC-151).
BURN_SCORE_NOTE = (
    "The score values closest approach in orders of magnitude from the {keep} km keep-out distance to 50,000 km, "
    f"and our delta-V in orders of magnitude up to {MAX_BURN_M_S:,.0f} m/s, so the {{buys:.1f}} km our burn buys "
    "against {adv} moves its score by {ca:.4f} while its {dv:.2f} m/s adds {dvs:.4f}: read what a burn buys from "
    "its cell as well as from the ranking."
)
#: Shown with every result (SPC-191): the two scales the score reads a miss and our delta-V on, and the keep-out
#: distance it used, with the basis of its default.
SCORE_SCALES_LINE = (
    "The score values closest approach in orders of magnitude: the full penalty at or inside the keep-out distance "
    f"of {{keep}} km, none at 50,000 km or more. Our delta-V is valued in orders of magnitude up to "
    f"{MAX_BURN_M_S:,.0f} m/s, the engine's per-burn limit. The keep-out distance is set on the panel; its default, "
    f"{DEFAULT_KEEP_OUT_KM:g} km, is Claude's choice and unsourced, and neither scale has been signed off by the "
    "technical authority."
)
#: Beside the keep-out distance on the panel (SPC-191).
KEEP_OUT_NOTE = (
    "A miss at or inside the keep-out distance scores the full closest-approach penalty, and each tenfold beyond it "
    f"scores less, down to none at 50,000 km. The default, {DEFAULT_KEEP_OUT_KM:g} km, is Claude's choice and "
    "unsourced: set the distance inside which a miss is unacceptable for your asset."
)
_DV_LOOKUP = " This cell's delta-V is a lookup."
#: Our delta-V in a computed or sampled cell for a response that does not burn (SPC-125): the cost x 0.05 rule does
#: not apply, since the blue asset is flown with no burn of ours, as the cell's closest approach is.
_NO_BURN_DV_NOTE = (
    "this response does not burn, so our delta-V is 0 m/s: the blue asset is flown with no burn of ours, as this "
    "cell's closest approach is"
)
_ENTER_TARGET = "Enter a target separation to size this burn."
_RESPONSE_AFTER_TCA = (
    "Our burn is not sized: at {at:%Y-%m-%d %H:%M} UTC, the response's time to execute after the scenario epoch, it "
    "comes after the closest approach at {tca:%Y-%m-%d %H:%M} UTC ({basis}), so it cannot open it. Shorten the time "
    "to execute." + _DV_LOOKUP
)
#: What an after-TCA refusal's closest approach rests on, in a computed and in a sampled row.
_RK45_TCA = "RK45 for both orbits, no burn"
_NOMINAL_TCA = "RK45, red with the hypothesis's nominal burn"
#: What our burn is sized against, and the TCA it is decided on, in a sampled row of several burns (SPC-184).
_NOMINAL_TRANSFER = "red's nominal transfer ({k} of its {n} burns)"
_NOMINAL_TRANSFER_TCA = "RK45, red flying its nominal transfer, {k} of its {n} burns"
#: Follows the lookup delta-V of a cell whose response names a target but whose closest approach is a lookup.
_TARGET_UNUSED = (
    "No burn is shown for the {target:g} km target: it is sized against this cell's closest approach computed or "
    "sampled, and here that is a lookup." + _DV_LOOKUP
)
_RESPONSE_AFTER_SPAN = (
    "Our burn is not sized: at {at:%Y-%m-%d %H:%M} UTC it comes after the {span:.1f} h searched, so it cannot change "
    "the closest approach in it." + _DV_LOOKUP
)
_RESPONSE_FAILED = (
    "Our burn is not sized: the blue asset's arc after it could not be propagated{reentered}." + _DV_LOOKUP
)
_RESPONSE_REENTERED = ", since it re-entered below {floor:g} km"
_RESPONSE_OVER_CAP = (
    "Our burn is not sized: sizing it with the rest of this evaluation needs at least {total:,} sample-hours, above "
    "the {cap:,.0f} one evaluation may run within its {budget:g} s budget. "
)
_RESPONSE_BUDGET = (
    "Our burn is not sized: this evaluation's {budget:g} s budget ran out before it was." + _DV_LOOKUP
)
_BUDGET_SIZING = (
    "Not sampled: this evaluation's {budget:g} s budget ran out while our burn was sized for this row. Take fewer "
    "samples or a shorter horizon."
)
_AFTER_BURN_FAILED = (
    "Not sampled after our burn: {k} of {n} samples failed to propagate against the burnt blue asset, and a P5 "
    "without them could hide the closest."
)
_AFTER_BURN_UNCONVERGED = (
    "Not sampled after our burn: P5, P50 and P95 are known only to within {hw:.1f} km, wider than the {tol:.1f} km "
    "this miss needs."
)
_AFTER_BURN_SEEDS_DIFFER = (
    "Not sampled after our burn: the samples converged on the hypothesis's own seed, known to within {hw:.2f} km "
    "against the {tol:.2f} km this miss needs, but not on the second seed its convergence is checked on. The two "
    "seeds disagree, so the row is not converged after our burn (SPC-224)."
)
_PROPAGATOR_LINE = (
    "Computed rows use SGP4; sampled rows use RK45 with J2 and drag, from the same element sets. Over this horizon "
    "the two propagators place these orbits up to {gap:.1f} km apart in separation, so a difference between a "
    "computed row and a sampled row smaller than {gap:.1f} km is the propagators, not the burn."
)
_PROPAGATORS_UNCOMPARED = (
    "The two propagators could not be compared for these orbits, so do not compare a computed row with a sampled "
    "row."
)
#: Shown with a scenario bound on one side only (SPC-120).
COMPUTED_BINDING_NOTE = "Closest approach not computed: bind {side} to compute it."
_COMPUTED_BINDING_NOTES: dict[tuple[bool, bool], str] = {
    (True, False): COMPUTED_BINDING_NOTE.format(side="a blue asset"),
    (False, True): COMPUTED_BINDING_NOTE.format(side="a red track"),
}


class ComputedPlan(NamedTuple):
    """The bound pair's computed closest approach, or why it was not computed; never both.

    Once a response's burn is sized (SPC-121), *approach* is RK45 for both orbits with no burn, *responses* holds
    each burn or why it was not sized, and *sgp4_reference* the SGP4 figure with no burn, shown beside it.
    *response_refusal* says why no burn was sized at all, when the cap or the budget stopped it.
    """

    approach: ElsetApproach | None
    refusal:  str | None
    responses: tuple[SizedBurn | BurnRefusal, ...] = ()
    sgp4_reference: ElsetApproach | None = None
    response_refusal: str | None = None
    # The side, name and floor of a bound set whose object was below the re-entry floor at an instant searched.
    decayed: tuple[str, str, float] | None = None


def _earned_s(elset: BoundElset) -> float:
    """Seconds from the scenario epoch until *elset* passes its limit; 0 or less when it has none left."""
    return (cast("float", elset.limit_hours) - cast("float", elset.age_hours)) * _SECONDS_PER_HOUR


def _unearned_side(red: BoundElset, blue: BoundElset) -> str | None:
    """The first side whose orbit is out of date, of unknown age or at its limit already; None when both earn time."""
    for elset in (red, blue):
        if elset.freshness is not Freshness.CURRENT or _earned_s(elset) <= 0.0:
            return elset.side
    return None


def _searched_span_s(scenario: Scenario) -> float:
    """The seconds from the scenario epoch both paths search (SPC-118): to the horizon's end or the moment either
    bound element set passes its limit, whichever is first; 0 when either earns no time; the horizon unbound."""
    horizon = scenario.horizon_hours * _SECONDS_PER_HOUR
    binding = scenario.binding
    red, blue = (None, None) if binding is None else (binding.red, binding.blue)
    if red is None or blue is None:
        return horizon
    if _unearned_side(red, blue) is not None:
        return 0.0
    return min(horizon, _earned_s(red), _earned_s(blue))


def plan_computed(scenario: Scenario) -> ComputedPlan | None:
    """The bound pair's closest approach, or why not; None unless bound on both sides (SPC-120, SPC-121)."""
    scenario = with_remainder(scenario)
    return _plan_computed(scenario, _pre_plan(scenario), None)


def _size_computed(
    scenario: Scenario, window: SeparationWindow, responses: _Responses, budget: _Budget | None,
) -> Rk45Plan | ElsetFailure | str:
    """The pair on RK45 with each response's burn sized, or why not: an arc failed, or the budget ran out."""
    binding = cast("ScenarioBinding", scenario.binding)
    red, blue = cast("BoundElset", binding.red), cast("BoundElset", binding.blue)
    if budget is None:
        return elset_response_plan(red.tle, blue.tle, window, responses.requests)
    if not budget.may_start():
        return _RESPONSE_BUDGET.format(budget=budget.run.budget_s)
    try:
        return elset_response_plan(red.tle, blue.tle, window, responses.requests, tick=budget.sizing(responses.labels))
    except _BudgetSpentError:
        return _RESPONSE_BUDGET.format(budget=budget.run.budget_s)


def _plan_computed(scenario: Scenario, pre: _PrePlan, budget: _Budget | None) -> ComputedPlan | None:
    """The bound pair's closest approach with no burn, both on SGP4, or why not; None unless bound on both sides.

    One search per scenario, shared by every computed row and response: our response is not applied to the blue
    orbit yet (SPC-121). It runs from the scenario epoch to the earlier of the horizon's end and the moment
    either element set passes its limit, since past that a computed miss would rest on an out-of-date orbit.
    Refused, as sampling refuses it, when either orbit is out of date or of unknown age, when SGP4 cannot
    propagate either element set at any instant searched, and when either object is below the re-entry floor at
    any instant searched (SPC-200), which the plan carries for the result's envelope line.
    """
    binding = scenario.binding
    red, blue = (None, None) if binding is None else (binding.red, binding.blue)
    if red is None or blue is None:
        return None
    side = _unearned_side(red, blue)
    if side is not None:
        return ComputedPlan(None, _refusal(_NOT_COMPUTED_STALE.format(side=side)))
    window = SeparationWindow(start_utc=scenario.epoch_utc, span_s=_searched_span_s(scenario))
    found = elset_closest_approach(red.tle, blue.tle, window)
    if isinstance(found, ElsetFailure) and found.reason == "reentered":
        decayed = red if found.side == "red" else blue
        sentence = _NOT_COMPUTED_DECAYED.format(side=found.side, floor=REENTRY_FLOOR_KM)
        return ComputedPlan(None, _refusal(sentence), decayed=(found.side, decayed.name, REENTRY_FLOOR_KM))
    if isinstance(found, ElsetFailure):
        return ComputedPlan(None, _refusal(_NOT_COMPUTED_SGP4.format(side=found.side)))
    if not (pre.sizing or pre.rk45):
        return ComputedPlan(found, None, response_refusal=pre.sizing_refusal)
    sized = _size_computed(scenario, window, pre.responses, budget)
    return _with_burns(found, sized, pre.responses, rk45=pre.rk45)


def _with_burns(
    found: ElsetApproach, sized: Rk45Plan | ElsetFailure | str, responses: _Responses, *, rk45: bool = False,
) -> ComputedPlan:
    """The computed plan once the burns were sized: on RK45 when any was, or always in a game tree's first turn
    (SPC-140), else the SGP4 figure with why not."""
    if isinstance(sized, str):
        return ComputedPlan(found, None, response_refusal=sized)
    if isinstance(sized, ElsetFailure):
        failed = tuple(BurnRefusal(request.key, "propagation", 0) for request in responses.requests)
        return ComputedPlan(found, None, responses=failed)
    if not rk45 and not any(isinstance(result, SizedBurn) for result in sized.responses):
        return ComputedPlan(found, None, responses=sized.responses)   # nothing burns, so SGP4 stands
    return ComputedPlan(sized.before, None, responses=sized.responses, sgp4_reference=found)


#: The clause of _COMPUTED_CA_NOTE and _RK45_CA_NOTE that COMPUTED_ELSET takes the place of (SPC-202).
_NOT_IN_IT = "element-set error is not in it"


def _computed_bases(
    scenario: Scenario, found: ElsetApproach, *, burnt: bool = False, error: ElsetErrorAt | None = None,
) -> OutcomeBases:
    binding = cast("ScenarioBinding", scenario.binding)   # plan_computed computes only when both sides are bound
    red, blue = cast("BoundElset", binding.red), cast("BoundElset", binding.blue)
    rk45 = found.propagator == RESPONSE_PROPAGATOR
    note = (_RK45_CA_NOTE if rk45 else _COMPUTED_CA_NOTE).format(
        red=red.stk_name, blue=blue.stk_name, span=found.window.span_s / _SECONDS_PER_HOUR,
        horizon=scenario.horizon_hours, re=red.epoch, be=blue.epoch, step=found.window.step_s,
        burn=_RK45_BURN_NOTE if burnt else _RK45_NO_BURN_NOTE,
    )
    if error is not None:
        clause = COMPUTED_ELSET.format(low=lower_edge_km(found.approach.miss_km, error.combined_km), **error.words())
        note = note.replace(_NOT_IN_IT, clause)
    return outcome_bases(
        custody_maintained=LOOKUP_BASES.custody_maintained,
        custody_gap_hours=LOOKUP_BASES.custody_gap_hours,
        closest_approach_km=FigureBasis(Basis.COMPUTED, note),
        time_to_closest_hours=FigureBasis(Basis.COMPUTED, _RK45_TIME_NOTE if rk45 else _COMPUTED_TIME_NOTE),
        delta_v_cost_km_s=LOOKUP_BASES.delta_v_cost_km_s,
    )


def _computed_cell(
    adversary: AdversaryAction, scenario: Scenario, found: ElsetApproach, custody: _RowCustody | None,
    response: _ResponseCell,
) -> OutcomeMetrics:
    """A cell showing the computed miss, with its time the computed TCA; the rest are lookups, but our delta-V where
    this response's burn was sized (SPC-121). It is scored on the miss, unrounded, or, under SPC-202's rule, on the
    lower edge of its element-set band: the miss less both sets' error at the TCA in quadrature, never below 0."""
    friendly = response.friendly
    binding = cast("ScenarioBinding", scenario.binding)
    miss = found.approach.miss_km
    error = (
        elset_error_at(binding, found.approach.tca_utc(found.window.start_utc))
        if scenario.miss_rule is MissRule.ELSET_ERROR else None
    )
    scored = miss if error is None else lower_edge_km(miss, error.combined_km)
    figures = _lookup_figures(adversary, friendly, scenario)._replace(closest_approach_km=scored)
    bases = response.bases(_computed_bases(scenario, found, burnt=response.burnt, error=error))
    built = _Built(response.figures(figures), found.approach.tca_s / _SECONDS_PER_HOUR, bases, shown_km=miss)
    tca = _tca_uncertainty(binding, found.window.start_utc, found.approach, found.closing_speed_km_s, found.window.span_s)
    return _outcome(
        scenario, friendly, built, custody, ca_computed=found, tca_uncertainty=tca, ca_response=response.figure,
        response_refusal=response.refusal, ca_elset_error=error,
    )


def _computed_response_cell(
    adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario, plan: _RowPlan, column: int,
) -> OutcomeMetrics:
    """A computed cell, after our burn where this response's was sized (SPC-121)."""
    computed = cast("ComputedPlan", plan.computed)
    found = cast("ElsetApproach", computed.approach)
    spec = friendly.burn
    result = _response_of(computed.responses, column)
    if spec is None:
        return _computed_cell(adversary, scenario, found, plan.custody, _ResponseCell(friendly, None, None))
    if result is None:
        refusal = computed.response_refusal
        return _computed_cell(adversary, scenario, found, plan.custody, _ResponseCell(friendly, None, refusal))
    at = _burn_at(scenario, friendly)
    if isinstance(result, BurnRefusal):
        sentence = _response_refusal(result, at, found.window, _RK45_TCA)
        return _computed_cell(adversary, scenario, found, plan.custody, _ResponseCell(friendly, None, sentence))
    figure = ResponseFigure(result, at, spec.target_km, spec.budget_km_s)
    return _computed_cell(adversary, scenario, result.after, plan.custody, _ResponseCell(friendly, figure, None))


def _tca_uncertainty(
    binding: ScenarioBinding, start: datetime, approach: ClosestApproach, speed_km_s: float, span_s: float,
) -> TcaUncertainty:
    """The TCA's uncertainty: both bound element sets' position error at the TCA, in quadrature, over the closing
    speed (SPC-118). Only a computed or sampled cell asks, and both of its element sets are current, so both epochs
    are known."""
    error = elset_error_at(binding, approach.tca_utc(start))
    return tca_uncertainty(error.combined_km, speed_km_s, span_s, at_edge=approach.at_window_edge)


def _undrawn_error_km(binding: ScenarioBinding, drawn_at: datetime, at: datetime) -> float:
    """What every sample's draw at *drawn_at* leaves out of both sets' element-set error at *at*, km (SPC-202): each
    set's error at *at* less its error at *drawn_at* in quadrature, both sides in quadrature; 0 at *drawn_at*."""
    then, now = elset_error_at(binding, drawn_at), elset_error_at(binding, at)
    red = max(now.red_km ** 2 - then.red_km ** 2, 0.0)
    blue = max(now.blue_km ** 2 - then.blue_km ** 2, 0.0)
    return math.sqrt(red + blue)


def _drawn_tca_uncertainty(
    binding: ScenarioBinding, drawn_at: datetime, window: SeparationWindow, found: tuple[ClosestApproach, float],
) -> TcaUncertainty:
    """A sampled TCA's uncertainty under SPC-202's rule: every sample drew both sets' error at *drawn_at*, so the
    samples' TCAs spread by it already, and the ± holds only its growth from then to this TCA. *found* is the
    sample's approach and its closing speed, km/s."""
    approach, speed_km_s = found
    error_km = _undrawn_error_km(binding, drawn_at, approach.tca_utc(window.start_utc))
    return tca_uncertainty(error_km, speed_km_s, window.span_s, at_edge=approach.at_window_edge, undrawn=True)


def _propagator_gap(scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]]) -> float | None:
    """The propagators' gap over the horizon, measured only when computed and sampled cells sit together.

    Red is measured on each sampled row's own arc, from its burn, which may be days before the window.
    """
    binding = scenario.binding
    red = None if binding is None else binding.red
    sampled = [
        cast("RowBurns", _row_burns(action, red)).first
        for action, row in zip(scenario.adversary_actions, matrix, strict=True)
        if any(c.ca_percentiles is not None for c in row)
    ]
    computed = [c.ca_computed for row in matrix for c in row if c.ca_computed is not None]
    if not (sampled and computed) or computed[0].propagator == RESPONSE_PROPAGATOR:
        return None   # nothing to compare, or every figure is RK45 already (SPC-121)
    red, blue = cast("BoundElset", red), cast("BoundElset", cast("ScenarioBinding", binding).blue)
    window = SeparationWindow(start_utc=scenario.epoch_utc, span_s=_searched_span_s(scenario))
    return rk45_sgp4_gap_km(red.tle, blue.tle, window, tuple(sampled))


class _RowPlan(NamedTuple):
    """What one adversary row's cells are built from: its sampling, if eligible, the pair's computed plan, and
    its custody when the bound red track's status was read (SPC-123)."""

    sampling: RowSampling | None
    computed: ComputedPlan | None
    custody:  _RowCustody | None = None


class MatrixPlan(NamedTuple):
    """What an evaluation builds its matrix from, besides the scenario (SPC-204): each row's plan, made with no
    Threat picture in it, each row's transfer, and the end of the span searched."""

    rows:      tuple[_RowPlan, ...]
    transfers: tuple[RowBurns | None, ...]
    end:       datetime


def _build_matrix(scenario: Scenario, plan: MatrixPlan) -> list[list[OutcomeMetrics]]:
    """The outcome matrix of *scenario* from *plan*: every cell from its row's plan, its figures' bases naming the
    row's burns. The one cell step, run by the evaluation and again under another Threat picture (SPC-204)."""
    return [
        [
            _burns_named(_cell(adversary, friendly, scenario, row, j), burns, plan.end)
            for j, friendly in enumerate(scenario.friendly_responses)
        ]
        for adversary, row, burns in zip(scenario.adversary_actions, plan.rows, plan.transfers, strict=True)
    ]


def _cell(
    adversary: AdversaryAction, friendly: FriendlyResponse, scenario: Scenario, plan: _RowPlan, column: int = 0,
) -> OutcomeMetrics:
    """One cell, with exactly one closest approach.

    A row carrying a hypothesis is sampled, or refused and kept a lookup: the no-burn figure is not its outcome.
    Otherwise, bound on both sides, a row whose action does not move red is computed, or refused; a manoeuvre
    names no burn, so it is refused. Unbound, every cell is a lookup.
    """
    if plan.sampling is not None:
        if plan.sampling.series is None:
            return _refused_cell(_lookup_cell(adversary, friendly, scenario, plan.custody), plan.sampling.refusal)
        return _sampled_response_cell(adversary, friendly, scenario, plan, column)
    if plan.computed is None:
        return _lookup_cell(adversary, friendly, scenario, plan.custody)
    refusal = plan.computed.refusal
    if adversary.action_type not in _STILL_ACTIONS:
        refusal = _refusal(_NOT_A_BURN)
    elif plan.computed.approach is not None:
        return _computed_response_cell(adversary, friendly, scenario, plan, column)
    return _refused_cell(_lookup_cell(adversary, friendly, scenario, plan.custody), refusal)


# ── Custody over the horizon (SPC-123) ─────────────────────────────────────────

_CUSTODY_COMPUTED_NOTE = (
    "the bound red track {red}'s custody as the sweep judges it at the scenario epoch, {state}, carried over the "
    "{h:g} h horizon on the assumption that no newer element set arrives: lost once its newest element set passes "
    "its limit or a hypothesised burn is newer than it{degraded}; our response is not applied"
)
#: Inserted in _CUSTODY_COMPUTED_NOTE for custody degraded for some of the horizon (SPC-179).
_DEGRADED_SPAN_NOTE = (
    "; degraded, neither held nor lost, for {span} of the horizon, each such hour carrying {w:g} of the custody "
    "penalty an hour lost carries (the owner's ruling of 2026-11-05), since degraded custody can judge the warning "
    "time but not whether a burn is normal"
)
_CUSTODY_GAP_NOTE = (
    "hours of the horizon custody is lost from then, an upper bound, since a newer element set may arrive sooner; "
    "our response is not applied"
)
#: _CUSTODY_GAP_NOTE for custody degraded for some of the horizon: its degraded hours are not lost hours (SPC-179).
_DEGRADED_GAP_NOTE = (
    "hours of the horizon custody is lost, an upper bound, since a newer element set may arrive sooner; the hours "
    "it is degraded, {span}, are not lost hours and are not in this gap; our response is not applied"
)
_WORST_CASE_NOTE = (
    "worst case: this manoeuvre names no burn time, so the burn is taken at the scenario epoch and custody is lost "
    "for the whole horizon"
)
_WORST_CASE_GAP_NOTE = "the whole horizon, the worst case for a manoeuvre that names no burn time"
_WORST_CASE = (
    "Custody lost for up to the whole {h:g} h horizon, taking the worst case: this manoeuvre names no burn time, so "
    "the burn is taken at the scenario epoch. Add a manoeuvre hypothesis with a burn time to compute it."
)
#: Shown with the result when any row's custody comes from the bound red track's status (SPC-123).
CUSTODY_NOTE = (
    "Custody is the bound red track's as the sweep judges it, held, degraded or lost, carried over the horizon on "
    "the assumption that no newer element set arrives, so each custody gap is an upper bound. Our response is not "
    "applied to custody yet: a sensor retask that would bring a newer element set sooner is not modelled, so every "
    "response in a row has the same custody. Degraded custody can judge the warning time but not whether a burn "
    "is normal, so the hours it is degraded are shown as degraded, neither held nor lost: each carries "
    f"{DEGRADED_CUSTODY_WEIGHT:g} of the custody penalty an hour lost carries, the owner's ruling of 2026-11-05 "
    "rather than a sourced figure, and the custody gap counts only the hours lost. Like held custody, it is lost "
    "once its newest element set passes its limit or a burn is newer than it, and a manoeuvre that names no burn "
    "time takes the worst case. " + CUSTODY_BASIS
)
#: Follows the rule-of-thumb line when no red track is bound (SPC-123).
CUSTODY_BIND_RED = "Bind a red track to compute it from its element set and history."
#: Follows the rule-of-thumb line when a red track is bound but its custody was not read.
CUSTODY_NOT_READ = "The bound red track's custody was not read for this evaluation, so the rule of thumb stands."


class _RowCustody(NamedTuple):
    """One row's custody over the horizon, the same for every response: our response is not applied to it."""

    maintained: bool
    gap_hours:  float
    state:      Custody | None   # at the scenario epoch when computed; None for the worst case, a lookup
    bases:      tuple[FigureBasis, FigureBasis]
    sentence:   str
    degraded_hours: float = 0.0  # not in gap_hours (SPC-179)


def _custodial(figures: _Figures, custody: _RowCustody | None) -> _Figures:
    if custody is None:
        return figures
    return figures._replace(
        custody_maintained=custody.maintained, custody_gap_hours=custody.gap_hours,
        custody_degraded_hours=custody.degraded_hours,
    )


def custody_bases(red: str, over: CustodyOverHorizon, note: str, horizon_h: float) -> tuple[FigureBasis, FigureBasis]:
    """Custody and its gap, computed from *over*, with *note* formatted for *red*: each says so where custody is
    degraded for some of the horizon, and the gap counts its lost hours only (SPC-179). The game tree's sequences
    share it with the matrix's rows."""
    d = over.degraded_hours
    span = span_text(d)
    degraded = _DEGRADED_SPAN_NOTE.format(span=span, w=DEGRADED_CUSTODY_WEIGHT) if d > 0.0 else ""
    gap = _DEGRADED_GAP_NOTE.format(span=span) if d > 0.0 else _CUSTODY_GAP_NOTE
    custody = note.format(red=red, state=over.at_epoch.value, h=horizon_h, degraded=degraded)
    return FigureBasis(Basis.COMPUTED, custody), FigureBasis(Basis.COMPUTED, gap)


def _custody_bases(bases: OutcomeBases, custody: _RowCustody | None) -> OutcomeBases:
    if custody is None:
        return bases
    maintained, gap = custody.bases
    return outcome_bases(
        custody_maintained=maintained, custody_gap_hours=gap, closest_approach_km=bases.closest_approach_km,
        time_to_closest_hours=bases.time_to_closest_hours, delta_v_cost_km_s=bases.delta_v_cost_km_s,
    )


def _row_custody(action: AdversaryAction, red: BoundElset, scenario: Scenario) -> _RowCustody:
    """The bound red track's custody carried over the horizon for *action*, or the worst case when it names no burn.

    Custody lost from the epoch already is lost whatever the burn time, so it is computed for every row.
    """
    h = scenario.horizon_hours
    burns = _row_burns(action, red)
    # The earliest burn the row applies (SPC-184); its first, which custody passes over, when it applies none.
    burn = None if burns is None else burns.first.epoch_utc
    over = custody_over_horizon(
        cast("CustodyStatus", red.custody), elset_hours=red.age_hours, limit_hours=red.limit_hours,
        limit_figure=red.limit_figure,
        horizon=Horizon(scenario.epoch_utc, h, burn),
    )
    if action.hypothesis is None and action.action_type is ActionType.MANOEUVRE and not over.lost_from_epoch:
        worst = (FigureBasis(Basis.LOOKUP, _WORST_CASE_NOTE), FigureBasis(Basis.LOOKUP, _WORST_CASE_GAP_NOTE))
        return _RowCustody(False, h, None, worst, _WORST_CASE.format(h=h))
    computed = custody_bases(red.stk_name, over, _CUSTODY_COMPUTED_NOTE, h)
    return _RowCustody(over.maintained, over.lost_hours, over.at_epoch, computed, over.sentence, over.degraded_hours)


def _custody_plan(scenario: Scenario) -> tuple[_RowCustody | None, ...]:
    """Each row's custody when a red track is bound with its status read; None for every row otherwise."""
    red = None if scenario.binding is None else scenario.binding.red
    if red is None or red.custody is None:
        return (None,) * len(scenario.adversary_actions)
    return tuple(_row_custody(action, red, scenario) for action in scenario.adversary_actions)


def expected_scores(
    scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]],
) -> tuple[float | None, ...]:
    """Each response's expected score on *matrix*, each row weighed by its share (row_shares); None for a response
    marked not permitted, which no rule weighs (SPC-195). *scenario* is the one evaluated, its remainder row held."""
    shares = row_shares(scenario)
    if len(matrix) != len(shares):
        raise ValueError(f"the matrix holds {len(matrix)} rows and the scenario {len(shares)}")
    return tuple(
        None if response.vetoed else _expected(shares, matrix, j)
        for j, response in enumerate(scenario.friendly_responses)
    )


def _expected(shares: Sequence[float], matrix: Sequence[Sequence[OutcomeMetrics]], j: int) -> float:
    """Response *j*'s expected score: each row's score weighed by its share, added in row order as 0.29.0 added it,
    so a record that release wrote replays to the same float."""
    return sum(shares[i] * matrix[i][j].composite_score for i in range(len(shares)))


# ── Scores that are not finite (SPC-221, evaluation F-32) ──────────────────

#: What the operator is shown when a composite score is not a finite number: a fixed sentence, never the exception's
#: text, which names the cell for the log. A NaN compares false with everything, so a rule's min() kept whatever it
#: met first and the pick followed the row order (probe P-14); an infinite score would have picked by it alone.
NON_FINITE_SCORE = (
    "Nothing is recommended: a composite score is not a finite number, so no rule can rank the responses on it. "
    "This is a fault in the engine or in a figure it was given, not in your entries; the server log names the cell."
)


class NonFiniteScoreError(ValueError):
    """A composite score that is not finite, found before any rule picked on it: in the matrix, *row* and *response*
    name the cell, 0-based; over a game tree both are None and the message names the sequence."""

    def __init__(self, where: str, score: float, row: int | None = None, response: int | None = None) -> None:
        super().__init__(f"{where} scores {score!r}: {NON_FINITE_SCORE}")
        self.row, self.response = row, response


def require_finite_scores(scenario: Scenario, outcome_matrix: Sequence[Sequence[OutcomeMetrics]]) -> None:
    """Refuse *outcome_matrix* when any composite score in it is not finite, naming the first such cell in row order,
    under a response not permitted too, since a cell no rule weighs still says the engine went wrong (SPC-221)."""
    for i, row in enumerate(outcome_matrix):
        for j, cell in enumerate(row):
            if not math.isfinite(cell.composite_score):
                action, response = scenario.adversary_actions[i], scenario.friendly_responses[j]
                where = f"row {i + 1} ({action.name}), response {response.id} ({response.name})"
                raise NonFiniteScoreError(where, cell.composite_score, i, j)


# ── Response ranking ──────────────────────────────────────────────────────────

def rank_responses(
    friendly_responses: list[FriendlyResponse],
    outcome_row: list[OutcomeMetrics],
) -> list[tuple[FriendlyResponse, float]]:
    """Sort friendly responses best→worst for a single adversary action.

    Best = lowest composite score. A response marked not permitted is listed after every permitted one, in score
    order among themselves, so it is never ranked first (SPC-195).
    """
    pairs = [(fr, om.composite_score) for fr, om in zip(friendly_responses, outcome_row, strict=True)]
    return sorted(pairs, key=lambda x: (x[0].vetoed, x[1]))


def find_robust_response(
    scenario: Scenario,
    outcome_matrix: list[list[OutcomeMetrics]],
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
) -> FriendlyResponse | None:
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
    The ``FriendlyResponse`` that is robust under the chosen strategy, or None when every response is marked not
    permitted, or under expected value when every row has P 0, which leaves it no weight to pick on (SPC-200,
    evaluation F-31; the tree's selectors already give none there). A response marked not permitted is removed
    before any rule aggregates, so it is never the pick, and a tie is broken among the permitted responses alone
    (SPC-195). A composite score anywhere in the matrix that is not finite raises NonFiniteScoreError before any
    rule aggregates (SPC-221, evaluation F-32).
    """
    n_adversary = len(scenario.adversary_actions)

    if not scenario.friendly_responses:
        raise ValueError("No friendly responses to select from")
    require_finite_scores(scenario, outcome_matrix)
    allowed = permitted_responses(scenario)
    if not allowed:
        return None

    if strategy == SelectorStrategy.MINIMAX:
        best_j = min(allowed, key=lambda j: max(outcome_matrix[i][j].composite_score for i in range(n_adversary)))

    elif strategy == SelectorStrategy.EXPECTED_VALUE:
        shares = row_shares(scenario)
        if sum(shares) <= 0.0:
            return None  # every share 0: only a 0.28.0 or 0.29.0 record replayed (SPC-200, SPC-203)
        best_j = _expected_value_pick(shares, outcome_matrix, allowed)

    else:  # MINIMIN: minimise the best-case score, the optimistic rule
        best_j = min(allowed, key=lambda j: min(outcome_matrix[i][j].composite_score for i in range(n_adversary)))

    return scenario.friendly_responses[best_j]


def _expected_value_pick(
    shares: Sequence[float], outcome_matrix: Sequence[Sequence[OutcomeMetrics]], allowed: Sequence[int],
) -> int:
    """The index, among *allowed*, of the response with the least expected score, each row weighed by its share in
    *shares* (row_shares). The first such response wins a tie. Every caller holds some weight: under the
    remainder rule the shares sum to 1 (SPC-203), and find_robust_response gives no pick when every share is 0,
    which only a replayed 0.28.0 or 0.29.0 record can hold (SPC-200)."""
    return min(allowed, key=lambda j: _expected(shares, outcome_matrix, j))


# ── Ties (SPC-206, evaluation F-13) ──────────────────────────────────────────

#: How close two responses' values under a rule may come and still tie (SPC-206, evaluation F-13): half a unit in
#: the sixth decimal place, to which the engine rounds every composite score. Each score is kept only to within this
#: of the value before rounding, so a difference no larger is below the precision the scores hold, and the rule has
#: no ground to prefer one response to the other. Reasoned from the engine's own rounding, not sourced; Claude's
#: choice, not a ruling. Minimax and minimin read rounded scores, so for them it is equality.
TIE_TOLERANCE: float = 5e-7
#: The places a difference between two values is rounded to before it is set against TIE_TOLERANCE, so a difference of
#: exactly the tolerance ties whatever the values' size: floating-point error in a difference of scores near 1 is about
#: 1e-16, far below the 12th place, and the 12th place is far below the tolerance. At the tolerance it is a tie.
_TIE_PLACES = 12
#: What the recommendation says of a tie: every tied response, and that the rule does not choose between them.
TIE_LINE = (
    "A tie under {rule}: {names} score within {tolerance:g} of each other, the precision every composite score is "
    "kept to, so {rule} does not choose between them. Each is shown in the order entered; the choice is yours."
)


def rule_values(
    scenario: Scenario, outcome_matrix: Sequence[Sequence[OutcomeMetrics]], strategy: SelectorStrategy,
) -> tuple[float | None, ...]:
    """Each response's value under *strategy*, lower being better, as find_robust_response works it out: its worst
    score over the rows under minimax, its best under minimin, its expected score under expected value. None for a
    response marked not permitted, which no rule values (SPC-195), and for every response under expected value when
    every share is 0, which leaves it no weight (SPC-200). A score that is not finite is refused, as there (SPC-221)."""
    require_finite_scores(scenario, outcome_matrix)
    rows = range(len(scenario.adversary_actions))
    if strategy is SelectorStrategy.EXPECTED_VALUE:
        shares = row_shares(scenario)
        if sum(shares) <= 0.0:
            return (None,) * len(scenario.friendly_responses)
        return expected_scores(scenario, outcome_matrix)
    aggregate = max if strategy is SelectorStrategy.MINIMAX else min
    return tuple(
        None if response.vetoed else aggregate(outcome_matrix[i][j].composite_score for i in rows)
        for j, response in enumerate(scenario.friendly_responses)
    )


def tied_with(values: Sequence[float | None]) -> tuple[int, ...]:
    """The places of every finite value within TIE_TOLERANCE of the least finite one, in order, the difference rounded
    to _TIE_PLACES so a difference of exactly the tolerance is a tie; none when no finite value is known. A value that
    is not finite never ties."""
    known = [v for v in values if v is not None and math.isfinite(v)]
    if not known:
        return ()
    best = min(known)
    return tuple(
        j for j, v in enumerate(values)
        if v is not None and math.isfinite(v) and round(v - best, _TIE_PLACES) <= TIE_TOLERANCE
    )


def ties_of(values: Sequence[float | None], pick: int | None) -> tuple[int, ...]:
    """The places tied with *pick*, the pick among them, in order: tied_with's, when they hold the pick; the pick
    alone when they do not, as with a score that is not finite; none with no pick. A pick never loses its tie set."""
    if pick is None:
        return ()
    places = tied_with(values)
    return places if pick in places else (pick,)


def tied_responses(
    scenario: Scenario, outcome_matrix: Sequence[Sequence[OutcomeMetrics]], strategy: SelectorStrategy,
) -> tuple[FriendlyResponse, ...]:
    """The pick of *strategy* and every permitted response tied with it within TIE_TOLERANCE, in the order entered
    (SPC-206): one response when there is no tie, none when the rule has no pick. find_robust_response still returns
    the response with the lowest score, as 0.37.0 did, so a record's pick and its replay are unchanged; it need not be
    the first entered of the tie, which is said beside it."""
    pick = find_robust_response(scenario, list(map(list, outcome_matrix)), strategy)
    place = None if pick is None else next(j for j, r in enumerate(scenario.friendly_responses) if r is pick)
    places = ties_of(rule_values(scenario, outcome_matrix, strategy), place)
    return tuple(scenario.friendly_responses[j] for j in places)


def named_list(names: Sequence[str]) -> str:
    """Names joined in words: "A", "A and B", "A, B and C"."""
    return names[0] if len(names) == 1 else " and ".join((", ".join(names[:-1]), names[-1]))


def tie_line(strategy: SelectorStrategy, tied: Sequence[FriendlyResponse]) -> str | None:
    """The sentence saying *tied* tie under *strategy*, each named with its id; None for one response or none."""
    if len(tied) <= 1:
        return None
    return TIE_LINE.format(
        rule=strategy.value.replace("_", " "), names=named_list([f"{r.name} ({r.id})" for r in tied]),
        tolerance=TIE_TOLERANCE,
    )


# ── Whether a collection can change the recommended response (SPC-204, evaluation F-14) ──

def _with_none_can_change(
    swept: CollectionAdvice, picture: ThreatPicture, now: datetime, relevance: Mapping[Cue, CueRelevance],
    band_read: bool,
) -> CollectionAdvice:
    """The sweep's advice to act on the ceiling, or that the range is below the action line, with the picture's age
    beside it; and when the picture holds a cue and none of them can change the recommended response, saying so."""
    if not relevance or any(seen.changes for seen in relevance.values()):
        return dataclasses.replace(swept, sentence=_beside(swept.sentence, picture.age(now)))
    why = EACH_THE_SAME if band_read else NO_BAND_READ
    none_can = NONE_CAN_CHANGE.format(why=why)
    return dataclasses.replace(swept, sentence=_beside(f"{swept.sentence} {none_can}", picture.age(now)))


#: Beside the sweep's advice when a cue's outcome matrix held a score that is not finite (V0.42 review of SPC-221).
CUE_NOT_AVAILABLE = "Whether {observation} could change the recommended response is not available: {why}"


@dataclass(frozen=True)
class CueRelevance:
    """The recommended response under each of a cue's outcomes: *benign* with the picture's range at the cue's
    benign (floor, ceiling), *hostile* at its hostile one, each None when the rule has no pick. *moved* is whether
    either outcome's picture moves any score in the matrix."""

    cue:     Cue
    benign:  FriendlyResponse | None
    hostile: FriendlyResponse | None
    moved:   bool
    # Why no pick could be had under an outcome's picture: NON_FINITE_SCORE when its matrix held a score that is not
    # finite (V0.42 review of SPC-221); None when both picks were had.
    refused: str | None = None

    @property
    def changes(self) -> bool:
        """Whether collecting it could change the recommended response: its two outcomes give different picks. Not
        when either outcome's matrix was refused, which leaves nothing to compare."""
        return self.refused is None and self.benign is not self.hostile


def cue_relevance(result: ScenarioResult, cue: Cue, rule: SelectorStrategy) -> CueRelevance:
    """*rule*'s pick on *result*'s matrix with the picture's range moved to each of *cue*'s outcomes.

    The matrix under each outcome's picture is the one the engine builds under it (ScenarioResult.matrix_under): its
    cell step run again from the evaluation's plans, which are built with no picture in them, so the evaluation the
    engine would run under that picture. A band that moved any figure or score would move a cell here. The picks are
    find_robust_response's on each matrix, and *moved* is whether either differs from the matrix built again under
    the picture held. *result*'s scenario must hold a picture.
    """
    held = cast("ThreatPicture", result.scenario.threat)
    as_held = result.matrix_under(held.floor, held.ceiling)
    picks: list[FriendlyResponse | None] = []
    moved = False
    for floor, ceiling in (cue.benign, cue.hostile):
        matrix = result.matrix_under(floor, ceiling)
        moved = moved or matrix != as_held
        outcome = dataclasses.replace(result.scenario, threat=dataclasses.replace(held, floor=floor, ceiling=ceiling))
        try:
            picks.append(find_robust_response(outcome, matrix, rule))
        except NonFiniteScoreError:
            # Asked while the page renders: a fault here must say so, never fail the page (V0.42 review).
            logger.exception("A cue's outcome matrix held a score that is not finite")
            return CueRelevance(cue, None, None, moved, refused=NON_FINITE_SCORE)
    return CueRelevance(cue, picks[0], picks[1], moved)


def _rescored(result: ScenarioResult, outcome: Scenario) -> list[list[OutcomeMetrics]]:
    """*result*'s matrix, for a result the engine did not build, with each cell's score moved by what *outcome*'s
    picture changes of it, scored again from the figures the cell was built from; a cell it does not move is the
    cell itself."""
    rows = []
    for row in result.outcome_matrix:
        cells = []
        for friendly, cell in zip(outcome.friendly_responses, row, strict=True):
            figures = cell_figures(cell)
            shift = _score(outcome, friendly, figures) - _score(result.scenario, friendly, figures)
            cells.append(cell if not shift else dataclasses.replace(cell, composite_score=cell.composite_score + shift))
        rows.append(cells)
    return rows


def _named(response: FriendlyResponse | None) -> str:
    """A pick as the advice names it, or that there is none."""
    return "no response" if response is None else f"{response.name} ({response.id})"


# ── The interval on a NOTSO-derived P, carried into the pick (SPC-132) ─────────

_INTERVAL_HOLDS = (
    "{row}: expected value recommends {pick} at every P across its NOTSO interval, {low} to {high:.2f}{capped}, "
    "{held}."
)
_INTERVAL_MOVES = (
    "{row}: expected value recommends {pick} at P {p:.2f}, but not across its NOTSO interval, {low} to "
    "{high:.2f}{capped}: {changes}, {held}."
)
#: Under the remainder rule, a P whose interval reaches past where the rows' P sum to 1 (SPC-203).
_CAPPED = ", checked to P {cap}, past which the rows' P would sum above 1, which is refused"
#: Under the remainder rule, with the rows' P at 1 no remainder row was evaluated, so no other P can be checked: a
#: lower one leaves a remainder whose cells this evaluation does not hold (SPC-203).
_INTERVAL_UNCHECKED = (
    "{row}: expected value's pick is not checked across its NOTSO interval, {low} to {high:.2f}: your rows' P sum to "
    "1, so a higher P for this row would sum above 1, which is refused, and a lower one would leave a remainder of "
    "P, whose row this evaluation did not evaluate, since your rows left none. With your rows' P summing below 1 the "
    "remainder row is evaluated, and this interval is checked."
)
_BELOW = "below P {at:.3f} it recommends {pick}"
_ABOVE = "above P {at:.3f} it recommends {pick}"
_JOINT_HOLDS = "Moved together across their NOTSO intervals, {rows} P keep expected value at {pick} throughout{held}."
_JOINT_MOVES = (
    "Moved together across their NOTSO intervals, {rows} P do not keep expected value at {pick}: with {corner}, it "
    "recommends {other}{held}."
)
_JOINT_UNCHECKED = (
    "Moved together across their NOTSO intervals, {rows} P are not checked: your rows' P sum to 1, so any lower sum "
    "would leave a remainder of P, whose row this evaluation did not evaluate, since your rows left none. With your "
    "rows' P summing below 1 the remainder row is evaluated, and they are checked."
)
_JOINT_HELD = ", with the other rows held at their P"
#: Under the remainder rule, what takes up a moved P: the remainder row (SPC-203).
_REMAINDER_TAKES = "the remainder of P taking up the difference"
#: The finest step a P is shown to.
_HUNDREDTH = 0.01
_PROBABILITY_IGNORED = (
    "{rule} does not use probability, so the NOTSO interval on {rows} P cannot move its pick and is not shown."
)


class IntervalPick(NamedTuple):
    """Where expected value's pick changes as one row's P moves across its interval, the others held.

    *below* and *above* are each the P nearest the row's own at which the pick changes, with the response it
    changes to, or None when it does not change on that side.
    """

    row:    int
    pick:   int
    below:  tuple[float, int] | None
    above:  tuple[float, int] | None


def _held_remainder(scenario: Scenario) -> bool:
    """Whether *scenario* holds the remainder row, which takes up any move of a row's P (SPC-203)."""
    return bool(scenario.adversary_actions) and scenario.adversary_actions[-1].remainder


def moved_weights(scenario: Scenario, moved: Mapping[int, float]) -> list[float]:
    """Each row's P with each row in *moved* at its P there, the others held, and the remainder row, where one is
    held, at 1 less the rest, so it takes up the move (SPC-203). Off the region a caller keeps to it can fall below
    0; under the 0.29.0 rule nothing takes up a move."""
    weights = [moved.get(i, a.probability) for i, a in enumerate(scenario.adversary_actions)]
    if _held_remainder(scenario):
        weights[-1] = 1.0 - math.fsum(weights[:-1])
    return weights


def _shares_of(scenario: Scenario, weights: Sequence[float]) -> list[float]:
    """*weights* as expected value weighs them: as they are under the remainder rule, over their sum under 0.29.0's."""
    if scenario.probability_rule is ProbabilityRule.REMAINDER:
        return list(weights)
    total = sum(weights)
    return [w / total if total > 0.0 else 0.0 for w in weights]


def _pick_at(
    scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]], allowed: Sequence[int], moved: Mapping[int, float],
) -> int:
    return _expected_value_pick(_shares_of(scenario, moved_weights(scenario, moved)), matrix, allowed)


def _crossings(scenario: Scenario, row: int, matrix: Sequence[Sequence[OutcomeMetrics]]) -> list[float]:
    """Each P for *row* at which two responses' expected scores are equal, the other rows held.

    Every response's weighted sum is a line in the row's P, B_j + p s_j: s_j is the row's score less, under the
    remainder rule, the remainder row's, which gives up what the row takes. Under the 0.29.0 rule every response
    shares the one total, so the same lines order them. Two lines cross at (B_k - B_j) / (s_j - s_k).
    """
    n = len(matrix[0])
    at_zero = moved_weights(scenario, {row: 0.0})
    held = [sum(at_zero[i] * matrix[i][j].composite_score for i in range(len(at_zero)) if i != row) for j in range(n)]
    last = len(matrix) - 1
    given = [matrix[last][j].composite_score if _held_remainder(scenario) else 0.0 for j in range(n)]
    slope = [matrix[row][j].composite_score - given[j] for j in range(n)]
    return [(held[k] - held[j]) / (slope[j] - slope[k])
            for j in range(n) for k in range(j + 1, n) if not math.isclose(slope[j], slope[k])]


def _first_change(
    pick_at: Callable[[float], int], pick: int, steps: Sequence[float],
) -> tuple[float, int] | None:
    """The first of *steps*, walked from the row's own P, past which the pick is no longer *pick*, and the new one.

    The pick holds between two crossings, so it is read halfway along each step.
    """
    for near, far in itertools.pairwise(steps):
        found = pick_at((near + far) / 2.0)
        if found != pick:
            return near, found
    return None


def interval_pick(
    scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]], row: int, span: tuple[float, float],
) -> IntervalPick:
    """Expected value's pick as *row*'s P moves across *span*, low and high, the other rows held at their P and, under
    the remainder rule, the remainder row taking up the move. *span* is one the remainder rule takes (row_cap)."""
    centre = scenario.adversary_actions[row].probability
    allowed = permitted_responses(scenario)

    def pick_at(p: float) -> int:
        return _pick_at(scenario, matrix, allowed, {row: p})

    low, high = span
    points = sorted({low, high, centre, *(c for c in _crossings(scenario, row, matrix) if low < c < high)})
    pick = pick_at(centre)
    below = [p for p in points if p <= centre][::-1]
    above = [p for p in points if p >= centre]
    return IntervalPick(row, pick, _first_change(pick_at, pick, below), _first_change(pick_at, pick, above))


def row_cap(scenario: Scenario, row: int) -> float | None:
    """The most *row*'s P can be, the other rows held, before the rows' P sum above 1: 1 less the others; None under
    the 0.29.0 rule, which holds no sum to 1 (SPC-203)."""
    if scenario.probability_rule is ProbabilityRule.SHARES:
        return None
    others = [a for i, a in enumerate(scenario.adversary_actions) if i != row]
    return 1.0 - rows_p_sum(others)


def _corner_points(
    corner: tuple[float, ...], spans: Sequence[tuple[float, float]], budget: float,
) -> list[tuple[float, ...]]:
    """*corner* of the box of *spans* where its P fit *budget*; where they do not, each point on an edge from it at
    which they reach *budget* exactly, the box's corners past the budget being refused."""
    if math.fsum(corner) <= budget + P_SUM_TOLERANCE:
        return [corner]
    found = []
    for k, (low, high) in enumerate(spans):
        at = budget - math.fsum(corner[:k] + corner[k + 1:])
        if low < at < high:
            found.append((*corner[:k], at, *corner[k + 1:]))
    return found


def joint_points(scenario: Scenario, spans: Mapping[int, tuple[float, float]]) -> list[tuple[float, ...]]:
    """Every corner of the region the rows in *spans* may take together, one P per row in row order: the corners of
    their box; under the remainder rule, the box cut where the rows' P would sum above 1, its corners being those of
    the box within the sum and the points on the box's edges where the sum reaches 1 (SPC-203)."""
    rows = sorted(spans)
    corners = itertools.product(*(spans[r] for r in rows))
    if scenario.probability_rule is ProbabilityRule.SHARES:
        return list(corners)
    budget = 1.0 - rows_p_sum([a for i, a in enumerate(scenario.adversary_actions) if i not in spans])
    found: list[tuple[float, ...]] = []
    for corner in corners:
        found += [point for point in _corner_points(corner, [spans[r] for r in rows], budget) if point not in found]
    return found


def joint_pick(
    scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]], spans: Mapping[int, tuple[float, float]],
) -> tuple[int, tuple[tuple[float, ...], int] | None]:
    """Expected value's pick with each row in *spans* moved across its span, low and high, together, the other rows
    held at their P; and the first corner of that region (joint_points), one P per row in row order, at which the
    pick changes, with the response it changes to, or None when it holds.

    Each response's region, where it is the pick, is the set of P at which its weighted sum is no more than each
    other's, every one a line in the P, the remainder's P too: an intersection of half-spaces, so convex. A convex
    region that holds every corner of a polytope holds the whole of it, so the corners alone say whether the pick
    changes anywhere.
    """
    allowed = permitted_responses(scenario)
    pick = _pick_at(scenario, matrix, allowed, {})
    rows = sorted(spans)
    for corner in joint_points(scenario, spans):
        found = _pick_at(scenario, matrix, allowed, dict(zip(rows, corner, strict=True)))
        if found != pick:
            return pick, (corner, found)
    return pick, None


def _edge(value: float) -> str:
    """An interval edge a pick was checked at: to the hundredth, or the thousandth when it is under the hundredth."""
    return f"{value:.2f}" if value >= _HUNDREDTH else f"{value:.3f}"


def _unchecked(scenario: Scenario) -> bool:
    """Under the remainder rule with the rows' P at 1, no remainder row was evaluated, so no P but those entered can
    be checked (SPC-203)."""
    return scenario.probability_rule is ProbabilityRule.REMAINDER and not _held_remainder(scenario)


def _joint_held(scenario: Scenario, rows: Sequence[int]) -> str:
    """What the joint line says holds still: the other rows, and under the remainder rule what takes up the move."""
    others = len(rows) < sum(not a.remainder for a in scenario.adversary_actions)
    takes = _held_remainder(scenario)
    if others and takes:
        return f"{_JOINT_HELD} and {_REMAINDER_TAKES}"
    if takes:
        return f", with {_REMAINDER_TAKES}"
    return _JOINT_HELD if others else ""


def _joint_line(scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]], rows: Sequence[int]) -> str:
    """Whether expected value's pick holds with *rows* moved together across their NOTSO intervals."""
    if _unchecked(scenario):
        return _JOINT_UNCHECKED.format(rows=_rows_named(rows))
    intervals = {r: cast("NotsoPrior", scenario.adversary_actions[r].accepted_prior).interval for r in rows}
    pick, change = joint_pick(scenario, matrix, {r: (i.checked_low, i.high) for r, i in intervals.items()})
    names = [r.name for r in scenario.friendly_responses]
    common = {"rows": _rows_named(rows), "pick": names[pick], "held": _joint_held(scenario, rows)}
    if change is None:
        return _JOINT_HOLDS.format(**common)
    corner, other = change
    first, *rest = [_edge(p) for p in corner]
    at = [f"row {rows[0] + 1}'s P at {first}", *(f"row {r + 1}'s at {p}" for r, p in zip(rows[1:], rest, strict=True))]
    joined = at[0] if len(at) == 1 else f"{', '.join(at[:-1])} and {at[-1]}"
    return _JOINT_MOVES.format(corner=joined, other=names[other], **common)


def _row_label(action: AdversaryAction, row: int) -> str:
    return f"Row {row + 1}, {action.name}" if action.name else f"Row {row + 1}"


def _single_held(scenario: Scenario) -> str:
    """What the single-row line says holds still, and under the remainder rule what takes up the move."""
    held = _JOINT_HELD.removeprefix(", ")
    return f"{held} and {_REMAINDER_TAKES}" if _held_remainder(scenario) else held


def _interval_line(scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]], row: int) -> str:
    """What expected value recommends across *row*'s NOTSO interval, and the P at which it changes, if it does; under
    the remainder rule, checked no higher than the rows' P can sum to 1 (SPC-203)."""
    action = scenario.adversary_actions[row]
    interval = cast("NotsoPrior", action.accepted_prior).interval
    low = f"{interval.low:.2f}" if interval.low > 0.0 else "under 0.01"
    label = _row_label(action, row)
    if _unchecked(scenario):
        return _INTERVAL_UNCHECKED.format(row=label, low=low, high=interval.high)
    cap = row_cap(scenario, row)
    high = interval.high if cap is None else min(interval.high, cap)
    capped = "" if high == interval.high else _CAPPED.format(cap=_edge(high))
    found = interval_pick(scenario, matrix, row, (interval.checked_low, high))
    names = [r.name for r in scenario.friendly_responses]
    common = {"row": label, "pick": names[found.pick], "low": low, "high": interval.high, "capped": capped,
              "held": _single_held(scenario)}
    changes = [line.format(at=side[0], pick=names[side[1]])
               for line, side in ((_BELOW, found.below), (_ABOVE, found.above)) if side is not None]
    if not changes:
        return _INTERVAL_HOLDS.format(**common)
    return _INTERVAL_MOVES.format(p=action.probability, changes="; ".join(changes), **common)


def _rows_named(rows: Sequence[int]) -> str:
    return f"{rows_listed(rows)}'s"


def interval_lines(
    scenario: Scenario, matrix: Sequence[Sequence[OutcomeMetrics]], strategy: SelectorStrategy,
) -> tuple[str, ...]:
    """Per row holding an applied NOTSO suggestion, whether expected value's pick holds across its P's interval, and
    with two or more such rows, whether it holds with them moved together; under a rule that reads no probability,
    one line saying so in place of an interval it ignores."""
    rows = [i for i, a in enumerate(scenario.adversary_actions) if a.accepted_prior is not None]
    if not rows or not permitted_responses(scenario):
        return ()
    if strategy is not SelectorStrategy.EXPECTED_VALUE:
        return (_PROBABILITY_IGNORED.format(rule=strategy.value.capitalize(), rows=_rows_named(rows)),)
    alone = tuple(_interval_line(scenario, matrix, row) for row in rows)
    return alone if len(rows) == 1 else (*alone, _joint_line(scenario, matrix, rows))


# ── Top-level evaluation ───────────────────────────────────────────────────────

def _binding_inputs(scenario: Scenario) -> tuple[InputRef, ...]:
    """Each bound element set as a provenance input, so a bound result traces to its orbits (F-121)."""
    if scenario.binding is None:
        return ()
    return tuple(tle_input(f"{b.side} {b.stk_name}", b.tle, b.epoch) for b in scenario.binding.bound)


def _hypothesis_inputs(scenario: Scenario) -> tuple[InputRef, ...]:
    """Each adversary action's hypothesis as a provenance input, dated at its burn (SPC-111)."""
    return tuple(
        dataclasses.replace(
            value_input(f"hypothesis {a.id} ({a.hypothesis.source.value})", a.hypothesis.recorded()),
            epoch=a.hypothesis.hypothesis.epoch_utc,
        )
        for a in scenario.adversary_actions
        if a.hypothesis is not None
    )


_STARTS_LATER = (
    "Starts at burn {k}, {at:%Y-%m-%d %H:%M} UTC, {h:+.1f} h from the scenario epoch, from the bound red track's "
    "state then: {before} not applied."
)


def _start_line(burns: RowBurns | None, scenario_epoch: datetime) -> str | None:
    """The burn line of a row whose series starts at a later burn than its first, burn 1 dropped (SPC-184)."""
    if burns is None or burns.all_dropped or burns.applied[0] == 1:
        return None
    k, at = burns.applied[0], burns.first.epoch_utc
    # PLR2004: burn 1 alone.
    before = "the burn before it is" if k == 2 else "the burns before it are"  # noqa: PLR2004
    return _STARTS_LATER.format(k=k, at=at, h=(at - scenario_epoch).total_seconds() / 3600.0, before=before)


def _transfer_inputs(scenario: Scenario, transfers: Sequence[RowBurns | None]) -> tuple[InputRef, ...]:
    """Each row of several burns, as every burn it applies and every burn it drops (SPC-184)."""
    return tuple(
        value_input(f"transfer {action.id}", burns.recorded())
        for action, burns in zip(scenario.adversary_actions, transfers, strict=True)
        if burns is not None and burns.several
    )


def _prior_inputs(scenario: Scenario) -> tuple[InputRef, ...]:
    """Each NOTSO suggestion the operator applied, as a lookup input dated at the end of its span (SPC-130)."""
    return tuple(
        dataclasses.replace(
            value_input(f"NOTSO suggestion applied to {a.id} ({a.accepted_prior.basis.kind.value})", a.accepted_prior),
            epoch=a.accepted_prior.span_end,
        )
        for a in scenario.adversary_actions
        if a.accepted_prior is not None
    )


def evaluate_scenario(
    scenario: Scenario,
    strategy: SelectorStrategy = SelectorStrategy.MINIMAX,
    *,
    sampler: Sampler = run_separation_series,
    run: RunControl | None = None,
) -> ScenarioResult:
    """Evaluate all (adversary × friendly) combinations and return a ranked result.

    Parameters
    ----------
    scenario:
        Fully populated Scenario dataclass.
    strategy:
        Selector strategy for the robust recommendation.
    sampler:
        Runs a row's separation series (SPC-112); a test passes a fake. Only
        a row plan_sampling finds eligible calls it.
    run:
        Bounds and watches the sampled rows (SPC-113): one wall-time budget,
        a stop and progress. Without it, evaluation is exactly as before.
        A stop raises EvaluationStoppedError and returns no result.

    Returns
    -------
    ScenarioResult with full outcome matrix, per-adversary rankings, and the
    robust best response.
    """
    return _evaluate(scenario, strategy, sampler, run)[0]


class TurnOne(NamedTuple):
    """What a game tree's first turn is built from besides its matrix (SPC-140): each row as checked, its sampling
    with the turn boundary kept, the pair's computed plan, and the one budget the later turns go on spending."""

    pre:      _PrePlan
    plan:     tuple[RowSampling | None, ...]
    computed: ComputedPlan | None
    budget:   _Budget | None


def _evaluate(
    scenario: Scenario, strategy: SelectorStrategy, sampler: Sampler, run: RunControl | None,
    tree_turn_s: float | None = None,
) -> tuple[ScenarioResult, TurnOne]:
    """evaluate_scenario, with what a game tree's first turn needs when *tree_turn_s* is given (SPC-140): each sampled
    row keeps its state at the end of the turn, and every computed cell is RK45 for both orbits even when nothing
    burns."""
    keep_at_s = () if tree_turn_s is None else (tree_turn_s,)
    if not scenario.adversary_actions:
        raise ValueError("Scenario must have at least one adversary action")
    # The rows as the engine weighs them: the operator's, and the remainder of P as a row of its own (SPC-203).
    scenario = with_remainder(scenario)
    if not scenario.friendly_responses:
        raise ValueError("Scenario must have at least one friendly response")

    t0 = time.monotonic()

    # Build outcome matrix: a lookup in every cell but those of a row sampled, computed or refused. One budget
    # covers the sampled rows and the computed rows' burns (SPC-113, SPC-121), and a tree's later turns (SPC-140).
    # Each plan is made from the scenario with its Threat picture taken out, so no band reaches one: a band can reach
    # a figure only in the cell step, which the matrix under another picture runs again (SPC-204).
    planning = scenario if scenario.threat is None else dataclasses.replace(scenario, threat=None)
    pre = _pre_plan(planning, rk45=tree_turn_s is not None)
    budget = None if run is None else _Budget(run, pre.ready)
    plan = _plan_sampling(planning, sampler, budget, pre, keep_at_s)
    computed = _plan_computed(planning, pre, budget)
    custody = _custody_plan(planning)
    red = None if scenario.binding is None else scenario.binding.red
    transfers = tuple(_row_burns(action, red) for action in scenario.adversary_actions)
    end = scenario.epoch_utc + timedelta(seconds=_searched_span_s(planning))
    rows = tuple(_RowPlan(sampling, computed, held) for sampling, held in zip(plan, custody, strict=True))
    matrix_plan = MatrixPlan(rows, transfers, end)
    outcome_matrix = _build_matrix(scenario, matrix_plan)
    _require_one_propagator(outcome_matrix)

    # Rank per adversary action
    ranked_per_adversary = [
        rank_responses(scenario.friendly_responses, outcome_matrix[i])
        for i in range(len(scenario.adversary_actions))
    ]

    # Robust selection
    robust_response = find_robust_response(scenario, outcome_matrix, strategy)

    wall_time = time.monotonic() - t0

    result = ScenarioResult(
        scenario=scenario,
        outcome_matrix=outcome_matrix,
        ranked_per_adversary=ranked_per_adversary,
        robust_best_response=robust_response,
        robust_strategy=strategy,
        computation_time_s=round(wall_time, 4),
        provenance=provenance(
            [value_input("scenario", _hashed(scenario)), *_binding_inputs(scenario), *_hypothesis_inputs(scenario),
             *_transfer_inputs(scenario, transfers), *_prior_inputs(scenario)],
        ),
        row_notes=_row_notes(scenario, plan),
        propagator_gap_km=_propagator_gap(scenario, outcome_matrix),
        row_custody=tuple(None if c is None else c.sentence for c in custody),
        rk45_reference=_rk45_reference(computed),
        row_transfers=tuple(None if burns is None else transfer_sentence(burns, end) for burns in transfers),
        row_starts=tuple(_start_line(burns, scenario.epoch_utc) for burns in transfers),
        row_burns=transfers,
        budget_ran_out=_ran_out(budget),
        envelope=envelope_lines(scenario, None if computed is None else computed.decayed),
        matrix_plan=matrix_plan,
    )
    return result, TurnOne(pre, plan, computed, budget)


def _hashed(scenario: Scenario) -> dict[str, Any]:
    """*scenario* as its provenance hashes it: the operator's own, every field, except that a permitted response omits
    its veto and reason, so a scenario with nothing vetoed hashes as it did before vetoes existed and a 0.28.0 record's
    input hashes still match its replay (SPC-195). The remainder row is derived, so left out, as is each row's flag;
    and the 0.29.0 rule is left out, so a record 0.28.0 or 0.29.0 wrote hashes as it did then (SPC-203); so is the
    miss rule of 0.28.0 to 0.31.0, so a record those releases wrote hashes as it did then (SPC-202); and so is the turn
    rule where it sets nothing, one turn, or is the equal turns of 0.23.0 to 0.36.0, so a record those releases wrote,
    and any one-turn scenario, hashes as it did then (SPC-187); and so is the tree's cost cap where it sets nothing, one
    turn, or is the shared cap of 0.23.0 to 0.37.0, for the same reason (SPC-188); and so is the convergence rule
    where it sets nothing, no row carrying a hypothesis, or is the one seed of 0.28.0 to 0.41.0 (SPC-224)."""
    plain = dataclasses.asdict(without_remainder(scenario))
    for response in plain["friendly_responses"]:
        if not response["vetoed"]:
            del response["vetoed"], response["veto_reason"]
    for action in plain["adversary_actions"]:
        del action["remainder"]
    if scenario.probability_rule is ProbabilityRule.SHARES:
        del plain["probability_rule"]
    if scenario.miss_rule is MissRule.POINT:
        del plain["miss_rule"]
    if scenario.turns == 1 or scenario.turn_rule is TurnRule.EQUAL:
        del plain["turn_rule"]
    if scenario.turns == 1 or scenario.tree_cap is TreeCap.SHARED:
        del plain["tree_cap"]
    if scenario.convergence_rule is ConvergenceRule.ONE_SEED or all(
        a.hypothesis is None for a in scenario.adversary_actions
    ):
        del plain["convergence_rule"]
    return plain


def _ran_out(budget: _Budget | None) -> bool:
    """Whether *budget* was spent: something was refused or left out for want of time; never with no budget."""
    return budget is not None and budget.spent


def _rk45_reference(computed: ComputedPlan | None) -> tuple[ElsetApproach, ElsetApproach] | None:
    """The SGP4 and RK45 figures with no burn, once the computed cells are on RK45 (SPC-121).

    Sizing runs only when some row will be computed (_computes_rows), so the pair's figure always has a cell.
    """
    if computed is None or computed.sgp4_reference is None or computed.approach is None:
        return None
    return computed.sgp4_reference, computed.approach
