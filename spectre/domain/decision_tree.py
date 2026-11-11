"""Decision Engine: a game tree of 1 to 3 turns (SPC-140).

Red moves, we respond, and then red may move again. Turn 1 is the outcome matrix itself, one node per cell. Each
later turn starts where the turn before left both orbits: red after its hypothesised burn, sample by sample, and
blue after our sized burn. No element set exists for an orbit after a burn, so every figure in a tree is RK45 with
J2 and exponential drag for both orbits, from their SGP4 states at the scenario epoch, and turn 1's computed cells
go on RK45 too, with the SGP4 figure shown beside them.

Each node's closest approach runs from its turn's start to the end of the span searched, as if no one moves again,
so turn 1's nodes are the one-turn figures. A sequence's closest approach is the smallest along it: each turn's
slice runs to the next turn's start and the last to the span's end, and where red was sampled it is P5 of each
sample's own minimum, sample k carried from turn to turn as sample k, with any burn its draw puts after its turn's
end made then, in the turn after. Its delta-V is our burns added up, its custody the bound red track's over the
horizon with every red burn on it, and its score the one-turn weighted sum on those figures, a lookup; each carries
its basis.

A tree is checked before anything runs: both sides bound and current, every row with a propagated orbit to carry
on, every burn inside its own turn, the branches under MAX_TREE_BRANCHES and the cost under the cap. A tree that
does not fit says so and the result is one turn. While it runs it shares the evaluation's budget: once spent, the
tree stops at the deepest turn built in full and says so; a branch that fails or does not converge keeps the turns
built in full and says which. Nothing is cut short silently.

Imports the Decision Engine, never the reverse; nothing here imports the web layer.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple, cast

import numpy as np

from spectre.astro.elset_approach import ELSET_PROPAGATOR, ElsetFailure
from spectre.astro.monte_carlo import (
    SEPARATION_PROPAGATOR,
    BlueBurn,
    BlueTrack,
    ContinuedRed,
    RedBurn,
    ReenteredError,
    Sampled,
    SeparationSeries,
    SeparationWindow,
    TurnBurn,
    _miss_stats,
    along_track_shifts_s,
    burnt_arc,
    continue_series,
    elset_offsets_km,
    elset_state,
    moved_states,
    nominal_continued_arc,
    nominal_red_arc,
    rk45_arc,
    run_separation_series,
    searched_approach,
    shift_pad_s,
)
from spectre.astro.response_burn import (
    MAX_SIZING_TRIALS,
    BurnRefusal,
    BurnRequest,
    Rk45Pair,
    SizedBurn,
    Trajectory,
    rk45_pair,
    size_against,
)
from spectre.domain.custody import Horizon, custody_over_horizon
from spectre.domain.decision import (
    _BURN_SEARCH_FRACTION,
    _NOMINAL_TCA,
    _PRE_RUN_CHECKS,
    _SCORE_NOTE,
    _STILL_ACTIONS,
    EVALUATION_BUDGET_S,
    LOOKUP_BASES,
    MAX_SAMPLE_HOURS,
    MAX_TURNS,
    SET_UP_S_PER_SAMPLE,
    AdversaryAction,
    AdversaryHypothesis,
    BoundElset,
    FriendlyResponse,
    OutcomeBases,
    OutcomeMetrics,
    RowSampling,
    RunControl,
    SampledTca,
    Sampler,
    Scenario,
    ScenarioBinding,
    ScenarioResult,
    SelectorStrategy,
    TurnOne,
    _Budget,
    _BudgetSpentError,
    _drawn_tca_uncertainty,
    _eligible_rows,
    _evaluate,
    _Figures,
    _first_refusal,
    _lookup_figures,
    _ran_out,
    _response_of,
    _response_refusal,
    _ResponseCell,
    _score,
    _searched_span_s,
    _tca_uncertainty,
    _turn_one_cost_h,
    _unearned_side,
    custody_bases,
    elset_error_at,
    evaluate_scenario,
    outcome_bases,
    sample_error,
    sized_burns,
    with_remainder,
)
from spectre.domain.decision_figures import ELSET_MODEL, ElsetErrorAt, ResponseFigure, TcaUncertainty, lower_edge_km
from spectre.domain.decision_transfer import MAX_BURN_M_S
from spectre.domain.provenance import Basis, FigureBasis, weakest
from spectre.domain.tree_selectors import TreeSelection, select

#: The most branches one evaluation builds: the sum over turns k of (rows x responses) to the k (design D6).
MAX_TREE_BRANCHES = 1_000

_SECONDS_PER_HOUR = 3600.0

# ── What the result says (SPC-140; the view is SPC-142) ──────────────────────

TREE_HEADER = (
    "A {turns}-turn tree: {rows} red moves and {responses} responses each turn, {nodes:,} branches. Each turn is "
    "{turn_h:.1f} h of the {span_h:.1f} h searched; turn 2 starts at {t2:%H:%M} UTC{t3}."
)
_TREE_HEADER_T3 = " and turn 3 at {t3:%H:%M} UTC"
TREE_PROPAGATOR = (
    "Every figure in the tree is RK45 with J2 and exponential drag for both orbits, from their SGP4 states at the "
    "scenario epoch: no element set exists for an orbit after a burn, so each turn starts where the one before left "
    "each orbit, after red's hypothesised burn and ours."
)
TREE_NODE_MEANS = (
    "Each branch's closest approach runs from its turn's start to the end of the span, as if no one moves again; "
    "turn 1's are the one-turn figures above."
)
TREE_PATH_MEANS = (
    "A sequence's closest approach is the smallest along it, P5 across samples where red was sampled, each sample "
    "carried from turn to turn; its delta-V is our burns added up; its custody is the bound red track's over the "
    "horizon with every red burn on it; its score is the one-turn weighted sum on those figures, a lookup."
)
TREE_RED_AGAIN = (
    "Row {row}, {name}: in turns 2 and on it burns again {offset:.2f} h after each turn starts, with its spread "
    "drawn afresh for each sample from where that sample's last turn left it; a sample whose drawn time falls after "
    "its turn ends still burns then, in the turn after."
)
TREE_RESPONSE_AGAIN = (
    "Each response executes its time to execute after each turn starts; a target separation is sized again against "
    "red's nominal burn in that turn."
)

TREE_UNBOUND = (
    "No tree built: a tree starts each turn from where the last one left both orbits, so it needs a red track and a "
    "blue asset bound, both current. This result is one turn."
)
TREE_LOOKUP_ROW = (
    "No tree built: row {row}, {name}, has no propagated orbit for turn 2 to start from, since its closest approach "
    "is a lookup. Add a manoeuvre hypothesis to it, or remove it. This result is one turn."
)
TREE_REFUSED_ROW = (
    "No tree built: row {row}, {name}, has no propagated orbit for turn 2 to start from, since its closest approach "
    "is refused: its cell says why. This result is one turn."
)
# D3 places a row's burn at one offset in every turn, so a transfer's later burns have no turn of their own: unequal
# turns, set by the engine, are SPC-187 (owner ruling, 2026-11-05). Until then a row of several burns refuses the
# tree, and the one-turn result stands with this reason (D7, SPC-184).
TREE_SEVERAL_BURNS = (
    "No tree built: row {row}, {name}, carries {n} burns of one transfer. Equal turns put a row's burn at the same "
    "time after every turn starts, so they cannot give each of its burns a turn of its own. This result is one turn."
)
TREE_BUDGET_TURN_ONE = (
    "No tree built: the evaluation's {budget:g} s budget ran out in turn 1 before row {row}, {name}, was sampled, so "
    "turn 2 has no orbit to start from. This result is one turn."
)
TREE_BURN_OUTSIDE = (
    "No tree built: {what} at {h:.2f} h after a turn starts falls outside the {turn_h:.2f} h turn. Every burn in a "
    "tree falls inside its own turn; shorten it, or take fewer turns. This result is one turn."
)
TREE_OVER_BRANCHES = (
    "No tree built: {turns} turns of {rows} red moves and {responses} responses make {nodes:,} branches, more than "
    "the {cap:,} one evaluation builds. {fits} This result is one turn."
)
TREE_OVER_CAP = (
    "No tree built: {turns} turns would cost about {total:,} sample-hours against a cap of {cap:,.0f}, what the "
    "{budget:.0f} s budget covers at the slowest rate measured. {fits} This result is one turn."
)
_FITS = "At these sizes, {k} turns fit."
_NONE_FITS = "No tree fits at these sizes: take fewer samples, rows or responses."
TREE_BUDGET = (
    "The {turns}-turn tree ran out of its {budget:.0f} s budget in turn {k}, with {done} of {total} branches built. "
    "The tree stops at turn {last}, the deepest turn built in full, and no pick is shown for later turns."
)
TREE_BRANCH_REFUSED = (
    "No {turns}-turn pick: the branch {path} {why}, and a pick over a tree missing a branch could miss its worst "
    "case."
)
# The panel refuses a turn depth that cannot fit before anything runs, naming the largest that would (SPC-142).
TREE_DEPTH_BRANCHES = (
    "Turn depth {turns} does not fit: {rows} red moves and {responses} responses make {nodes:,} branches over "
    "{turns} turns, more than the {cap:,} one evaluation builds. {largest}"
)
TREE_DEPTH_COST = (
    "Turn depth {turns} does not fit: it would cost about {total:,} sample-hours against a cap of {cap:,.0f}, what "
    "the {budget:.0f} s budget covers at the slowest rate measured. {largest}"
)
_LARGEST = "The largest turn depth that fits at these sizes is {k}."
_LARGEST_ONE = (
    "The largest turn depth that fits at these sizes is 1, the outcome matrix alone: take fewer samples, rows or "
    "responses for a tree."
)
TREE_DEEPEST = "Built in full to turn {k} of {turns}: no figure or pick is shown below turn {k}."
#: Where the rows' P leave a remainder, the tree's lines and every size or cost refusal say it counts as a red move,
#: so a tree that fits when the P sum to 1 and not below says why (SPC-203).
TREE_REMAINDER_COUNTED = (
    "Red's moves count the remainder of P, the engine's no-action row, beside your {listed}: rows whose P sum to 1 "
    "leave no remainder, and one red move fewer."
)
_WHY_TURN_ONE = "is refused in turn 1, as its cell says"
_WHY_FAILED = "lost {k} of {n} samples, which failed to propagate"
_WHY_UNCONVERGED = "did not converge: its P5, P50 and P95 are known only to within {hw:.1f} km"
_WHY_PATH_UNCONVERGED = "did not converge along the sequence: its P5 is known only to within {hw:.1f} km"
_WHY_ARC = "could not be propagated"
_WHY_RK45 = "could not be put on RK45 within the budget"

#: Every sentence the result may carry, for the house checks.
SENTENCES: tuple[str, ...] = (
    TREE_HEADER, TREE_PROPAGATOR, TREE_NODE_MEANS, TREE_PATH_MEANS, TREE_RED_AGAIN, TREE_RESPONSE_AGAIN,
    TREE_UNBOUND, TREE_LOOKUP_ROW, TREE_REFUSED_ROW, TREE_SEVERAL_BURNS, TREE_BUDGET_TURN_ONE, TREE_BURN_OUTSIDE,
    TREE_OVER_BRANCHES, TREE_OVER_CAP, TREE_BUDGET,
    TREE_BRANCH_REFUSED, TREE_DEPTH_BRANCHES, TREE_DEPTH_COST, TREE_DEEPEST, TREE_REMAINDER_COUNTED,
)

_NODE_LABEL = "Turn {k} of {turns}, {path}: "
_SAMPLED_NOTE = (
    "P5 of {n} sampled misses from this turn's start to the end of the span, as if no one moves again, each "
    "sample carried from where its last turn left it, by RK45 with J2 and exponential drag for both orbits; the "
    "element sets' own errors are not sampled"
)
_COMPUTED_NOTE = (
    "smallest separation from this turn's start to the end of the span, as if no one moves again, both orbits "
    "carried from where the last turn left them by RK45 with J2 and exponential drag; element-set error is not in it"
)
_TIME_NOTE = "time of that closest approach from the scenario epoch, RK45 for both orbits"
_PATH_COMPUTED_NOTE = (
    "the smallest separation along this sequence, each turn's slice to the next turn's start and the last turn's "
    "to the end of the span, as if no one moves after it, both orbits carried from turn to turn by RK45 with J2 and "
    "exponential drag; element-set error is not in it."
)
_PATH_SAMPLED_NOTE = (
    "P5 of each sample's own smallest separation along this sequence, sample k carried from turn to turn as sample "
    "k, each turn's slice to the next turn's start and the last turn's to the end of the span, as if no one moves "
    "after it, by RK45 with J2 and exponential drag for both orbits; the element sets' own errors are not sampled."
)
#: The four notes above once element-set error is in every propagated figure (SPC-202).
_SAMPLED_NOTE_ELSET = (
    "P5 of {n} sampled misses from this turn's start to the end of the span, as if no one moves again, each "
    "sample carried from where its last turn left it, by RK45 with J2 and exponential drag for both orbits; each "
    "sample carries both objects' element-set error along track, drawn once at the start of its first sampled turn "
    "from " + ELSET_MODEL + ", at each set's age at the scenario epoch: red {rk:.1f} km, {ra:.1f} h old, and blue "
    "{bk:.1f} km, {ba:.1f} h old"
)
_COMPUTED_NOTE_ELSET = (
    "smallest separation from this turn's start to the end of the span, as if no one moves again, both orbits "
    "carried from where the last turn left them by RK45 with J2 and exponential drag; element-set error is beside "
    "it, not in it: {e:.1f} km (1 sigma) at its closest approach, red's {rk:.1f} km ({ra:.1f} h old then) and "
    "blue's {bk:.1f} km ({ba:.1f} h old) in quadrature, by " + ELSET_MODEL + "; the sequence's score reads its "
    "closest approach along the path, {closest:.1f} km, less this error: {low:.1f} km"
)
_PATH_COMPUTED_NOTE_ELSET = (
    "the smallest separation along this sequence, each turn's slice to the next turn's start and the last turn's "
    "to the end of the span, as if no one moves after it, both orbits carried from turn to turn by RK45 with J2 and "
    "exponential drag. Its score reads it less the element-set error at this turn's closest approach, {e:.1f} km "
    "(1 sigma): red's {rk:.1f} km (its set {ra:.1f} h old then) and blue's {bk:.1f} km ({ba:.1f} h old) in "
    "quadrature, by " + ELSET_MODEL + ", which is no less than the error at any closest approach before it."
)
_PATH_SAMPLED_NOTE_ELSET = (
    "P5 of each sample's own smallest separation along this sequence, sample k carried from turn to turn as sample "
    "k, each turn's slice to the next turn's start and the last turn's to the end of the span, as if no one moves "
    "after it, by RK45 with J2 and exponential drag for both orbits; each sample carries both objects' element-set "
    "error along track, drawn once at the start of its first sampled turn from " + ELSET_MODEL + ", at each set's "
    "age at the scenario epoch: red {rk:.1f} km (1 sigma), its set {ra:.1f} h old, and blue {bk:.1f} km, "
    "{ba:.1f} h old; a computed turn before that enters as its one figure."
)
_PATH_UNSIZED = " No burn is sized for {which}, so the blue asset is flown there without one."
_PATH_DV_NOTE = "our burns along this sequence added up, each as its own turn states it"
_PATH_DV_LOOKUP = "; the delta-V for {which} is a lookup, not a sized burn, so the sum is a lookup"
_PATH_SCORE_NOTE = (
    f"the one-turn score on this sequence's figures: {_SCORE_NOTE}; here our delta-V is this sequence's burns added "
    f"up, so burns adding up to {MAX_BURN_M_S:,.0f} m/s or more score the full delta-V term, as one burn at the "
    "per-burn limit does"
)
_PATH_CUSTODY_NOTE = (
    "the bound red track {red}'s custody as the sweep judges it at the scenario epoch, {state}, carried over the "
    "{h:g} h horizon with the earliest red burn on this sequence, on the assumption that no newer element set "
    "arrives{degraded}; our responses are not applied"
)


# ── The tree as the result carries it ────────────────────────────────────────

class TurnStart(NamedTuple):
    """Where a turn begins, from the arcs the turn before left; at the scenario epoch for turn 1."""

    at_s:           float                  # seconds after the scenario epoch
    red:            np.ndarray             # (n, 6) per sample, or (1, 6) while red has not been sampled
    red_bstar:      np.ndarray             # per sample
    red_burns_utc:  tuple[datetime, ...]   # every red burn on the path before this turn
    blue:           np.ndarray             # (6,), after our burns on the path
    our_dv_km_s:    float                  # our burns so far, summed
    seed:           int                    # this turn's red draws, from the row's seed, the turn and the path
    red_nominal:    np.ndarray             # (6,) red with every burn on the path as stated: what our burn is sized on
    red_nominal_bstar: float


@dataclass(frozen=True)
class NodeFigures:
    """One node's figures, from its turn's start to the span's end, as if no one moves again."""

    closest_approach_km: float                 # P5 when sampled
    tca_utc:             datetime
    band:                Mapping[int, float] | None   # P5, P50 and P95 when sampled
    half_width_km:       float | None
    slice_min_km:        tuple[float, ...]     # per sample, the minimum within this turn's own slice
    delta_v_km_s:        float                 # our burn this turn, 0 when none
    tca_uncertainty:     TcaUncertainty | None
    bases:               OutcomeBases          # computed or sampled, noted with the turn and the path
    propagator:          str                   # always RK45


class PathBases(NamedTuple):
    """What a sequence's closest approach, delta-V and score rest on: the delta-V is a lookup when any turn's is."""

    closest_approach_km: FigureBasis
    delta_v_km_s:        FigureBasis
    score:               FigureBasis


class PathFigures(NamedTuple):
    """A sequence's figures, from the scenario epoch to the end of this node's turn and on, as if no one moves again."""

    closest_approach_km: float     # the smallest along it; P5 of each sample's own minimum when sampled
    delta_v_km_s:        float     # our burns added up
    custody_maintained:  bool
    custody_gap_hours:   float
    time_to_execute_hours: float   # summed and capped at the horizon
    reversibility:       float     # the least reversible response on it
    score:               float     # the one-turn weighted sum on these figures, a lookup
    custody_bases:       tuple[FigureBasis, FigureBasis]
    bases:               PathBases
    custody_degraded_hours: float = 0.0   # not in custody_gap_hours (SPC-179)


@dataclass(frozen=True, eq=False)
class GameNode:
    """One branch: red's move *action* and our *response* in *turn*, from where the turn before left both orbits."""

    turn:     int
    action:   int
    response: int
    start:    TurnStart
    figures:  NodeFigures
    path:     PathFigures
    children: tuple[GameNode, ...] = ()

    @property
    def path_closest_km(self) -> float:
        return self.path.closest_approach_km

    @property
    def path_score(self) -> float:
        return self.path.score

    def walk(self) -> Iterator[GameNode]:
        """This node and every node below it, depth first in order."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True, eq=False)
class GameTree:
    """The tree, or why none was built: its turns, each turn's window, turn 1's nodes, its sentences in order, and
    the result's rule's picks over the turns built in full, with the update after turn 1 (SPC-141), None when no
    turn was built."""

    turns:          int
    windows:        tuple[SeparationWindow, ...]   # each turn, from its start to the span's end
    roots:          tuple[GameNode, ...]           # turn 1, the same cells as the outcome matrix, row by row
    complete_turns: int
    refusal:        str | None
    lines:          tuple[str, ...]
    selection:      TreeSelection | None = None

    def nodes(self) -> Iterator[GameNode]:
        for root in self.roots:
            yield from root.walk()

    @property
    def deepest(self) -> str | None:
        """The deepest turn built in full, for a tree built in part (SPC-142); None for a whole tree or none."""
        if 0 < self.complete_turns < self.turns:
            return TREE_DEEPEST.format(k=self.complete_turns, turns=self.turns)
        return None


# ── Counting before anything runs ────────────────────────────────────────────

def branches(rows: int, responses: int, turns: int) -> int:
    """The branches of a tree: the sum over turns k of (rows x responses) to the k."""
    return sum((rows * responses) ** k for k in range(1, turns + 1))


class _Sizes(NamedTuple):
    """What a tree's cost is counted from: each row's samples (0 for a row that does not move red), the responses,
    how many of them burn, the span searched and the turns."""

    samples:   tuple[int, ...]
    responses: int
    burning:   int
    span_s:    float
    turns:     int

    @property
    def turn_s(self) -> float:
        return self.span_s / self.turns


def _sizes(scenario: Scenario) -> _Sizes:
    return _Sizes(
        tuple(0 if a.hypothesis is None else a.hypothesis.hypothesis.n_samples for a in scenario.adversary_actions),
        len(scenario.friendly_responses),
        sum(f.burn is not None for f in scenario.friendly_responses),
        _searched_span_s(scenario),
        scenario.turns,
    )


def _red_arcs(samples: Sequence[int], k: int) -> int:
    """Red's arcs in turn *k*, one per red path, or one per sample once a row on it has moved red.

    A path is sampled from its first moving row on, with that row's samples: counted by where that row falls.
    """
    rows, still, moved = len(samples), sum(n == 0 for n in samples), sum(samples)
    return int(still**k + sum(still ** (m - 1) * moved * rows ** (k - m) for m in range(1, k + 1)))


def _turn_cost_s(sizes: _Sizes, k: int) -> float:
    """What turn *k* costs, seconds of sample time: red's arcs, each searched against every blue path that shares
    its red path, a slice search for each before the last turn, a blue arc per branch, and the sizing of each
    burning response, 2 arcs and MAX_SIZING_TRIALS trials, against each red path and blue path before it."""
    rest = sizes.span_s - (k - 1) * sizes.turn_s
    per = rest + SET_UP_S_PER_SAMPLE
    rows = len(sizes.samples)
    blues = sizes.responses**k
    arcs = _red_arcs(sizes.samples, k)
    searches = arcs * (blues - 1) * _BURN_SEARCH_FRACTION * per
    slices = arcs * blues * _BURN_SEARCH_FRACTION * (sizes.turn_s + SET_UP_S_PER_SAMPLE) if k < sizes.turns else 0.0
    sizing_paths = rows**k * sizes.responses ** (k - 1) if sizes.burning else 0
    sizing = sizing_paths * (2 + MAX_SIZING_TRIALS * sizes.burning) * per
    return float(arcs * per + searches + slices + rows**k * blues * per + sizing)


def _turn_one_extra_s(sizes: _Sizes) -> float:
    """What carrying turn 1 on adds to the matrix, seconds of sample time: each sample's slice search against each
    blue, and blue's and red's nominal arcs integrated again for each row."""
    variants = 1 + sizes.burning
    searched = sum(max(n, 1) for n in sizes.samples) * variants
    slices = searched * _BURN_SEARCH_FRACTION * (sizes.turn_s + SET_UP_S_PER_SAMPLE)
    return slices + len(sizes.samples) * (variants + 1) * (sizes.span_s + SET_UP_S_PER_SAMPLE)


def tree_cost(scenario: Scenario) -> float:
    """What the tree costs, sample-hours, before anything runs: turn 1 as one evaluation with every computed cell
    on RK45, and what the later turns add, on the cap's own model (SPC-113, SPC-121). The remainder row, where the
    rows' P leave one, is one of red's moves like any other (SPC-203)."""
    scenario = with_remainder(scenario)
    sizes = _sizes(scenario)
    later = sum(_turn_cost_s(sizes, k) for k in range(2, sizes.turns + 1))
    return _turn_one_cost_h(scenario) + (_turn_one_extra_s(sizes) + later) / _SECONDS_PER_HOUR


def largest_tree(scenario: Scenario) -> int:
    """The most turns, the span split equally among them, that fit the branch cap and the cost cap; 1 when none."""
    scenario = with_remainder(scenario)
    rows, responses = len(scenario.adversary_actions), len(scenario.friendly_responses)
    fits = 1
    for k in range(2, MAX_TURNS + 1):
        if branches(rows, responses, k) > MAX_TREE_BRANCHES:
            break
        if tree_cost(dataclasses.replace(scenario, turns=k)) > MAX_SAMPLE_HOURS:
            break
        fits = k
    return fits


# ── Refused before anything runs ─────────────────────────────────────────────

def _unbound(scenario: Scenario) -> str | None:
    binding = scenario.binding
    if binding is None or binding.red is None or binding.blue is None:
        return TREE_UNBOUND
    return TREE_UNBOUND if _unearned_side(binding.red, binding.blue) is not None else None


def _lookup_row(scenario: Scenario) -> str | None:
    """The first row whose turn-1 closest approach is a lookup or refused before it runs, so leaves no orbit."""
    rows = _eligible_rows(scenario) or [None] * len(scenario.adversary_actions)
    for i, (action, row) in enumerate(zip(scenario.adversary_actions, rows, strict=True)):
        if action.hypothesis is None and action.action_type not in _STILL_ACTIONS:
            return TREE_LOOKUP_ROW.format(row=i + 1, name=action.name)
        if row is not None and _first_refusal(row, _PRE_RUN_CHECKS) is not None:
            return TREE_REFUSED_ROW.format(row=i + 1, name=action.name)
    return None


def _several_burns(scenario: Scenario) -> str | None:
    """The first row carrying more than one burn of a transfer, which equal turns cannot place (SPC-184)."""
    for i, action in enumerate(scenario.adversary_actions):
        if action.hypothesis is not None and action.hypothesis.then:
            return TREE_SEVERAL_BURNS.format(row=i + 1, name=action.name, n=len(action.hypothesis.then) + 1)
    return None


def _offset_s(scenario: Scenario, action: AdversaryAction) -> float:
    """When a row's hypothesis burns, seconds after the scenario epoch, and so after each turn starts."""
    hypothesis = cast("AdversaryHypothesis", action.hypothesis).hypothesis
    return float((hypothesis.epoch_utc - scenario.epoch_utc).total_seconds())


def _burns(scenario: Scenario) -> Iterator[tuple[str, float]]:
    """Every burn a turn holds, named, with its time after the turn starts: red's hypotheses, then our targets."""
    for action in scenario.adversary_actions:
        if action.hypothesis is not None:
            yield action.name, _offset_s(scenario, action)
    for friendly in scenario.friendly_responses:
        if friendly.burn is not None:
            yield friendly.name, friendly.time_to_execute_hours * _SECONDS_PER_HOUR


def _burn_outside(scenario: Scenario) -> str | None:
    turn_s = _searched_span_s(scenario) / scenario.turns
    for name, at_s in _burns(scenario):
        if not 0.0 <= at_s < turn_s:
            return TREE_BURN_OUTSIDE.format(
                what=f"{name}'s burn", h=at_s / _SECONDS_PER_HOUR, turn_h=turn_s / _SECONDS_PER_HOUR,
            )
    return None


def remainder_counted(scenario: Scenario) -> str | None:
    """That red's moves count the remainder of P, where *scenario*, as the engine weighs it, holds the remainder row;
    else None (SPC-203)."""
    rows = scenario.adversary_actions
    if not rows or not rows[-1].remainder:
        return None
    listed = len(rows) - 1
    return TREE_REMAINDER_COUNTED.format(listed="row" if listed == 1 else f"{listed} rows")


def _counted(refusal: str, scenario: Scenario) -> str:
    """*refusal* of a tree's size or cost, and, where the remainder counts as a red move, the sentence saying so."""
    counted = remainder_counted(scenario)
    return refusal if counted is None else f"{refusal} {counted}"


def _fits(scenario: Scenario) -> str:
    k = largest_tree(scenario)
    return _FITS.format(k=k) if 1 < k < scenario.turns else _NONE_FITS


def _over_branches(scenario: Scenario) -> str | None:
    rows, responses = len(scenario.adversary_actions), len(scenario.friendly_responses)
    nodes = branches(rows, responses, scenario.turns)
    if nodes <= MAX_TREE_BRANCHES:
        return None
    return _counted(TREE_OVER_BRANCHES.format(
        turns=scenario.turns, rows=rows, responses=responses, nodes=nodes, cap=MAX_TREE_BRANCHES, fits=_fits(scenario),
    ), scenario)


def _over_cap(scenario: Scenario) -> str | None:
    total = tree_cost(scenario)
    if total <= MAX_SAMPLE_HOURS:
        return None
    return _counted(TREE_OVER_CAP.format(
        turns=scenario.turns, total=math.ceil(total), cap=MAX_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
        fits=_fits(scenario),
    ), scenario)


#: What a tree needs before its size is counted: both sides bound and current, an orbit from every row, one burn a
#: row, every burn inside its turn. Then what it fits: the branch cap and the cost cap.
_SHAPE_CHECKS = (_unbound, _lookup_row, _several_burns, _burn_outside)
_FIT_CHECKS = (_over_branches, _over_cap)


def _first_problem(scenario: Scenario, checks: Sequence[Callable[[Scenario], str | None]]) -> str | None:
    for check in checks:
        refusal = check(scenario)
        if refusal is not None:
            return refusal
    return None


def refused_before_run(scenario: Scenario) -> str | None:
    """Why a tree of *scenario.turns* turns is not built, checked in order before anything runs; None to build it."""
    return _first_problem(with_remainder(scenario), (*_SHAPE_CHECKS, *_FIT_CHECKS))


def depth_refusal(scenario: Scenario) -> str | None:
    """Why the turn depth asked for does not fit, for the panel to refuse before anything runs (SPC-142).

    It names the largest depth that would fit at the same sizes. None when it fits, for one turn, and when the
    tree is refused for another reason first: the result then states that reason beside the one-turn matrix.
    """
    scenario = with_remainder(scenario)
    if scenario.turns == 1 or _first_problem(scenario, _SHAPE_CHECKS) is not None:
        return None
    k = largest_tree(scenario)
    largest = _LARGEST.format(k=k) if k > 1 else _LARGEST_ONE
    rows, responses = len(scenario.adversary_actions), len(scenario.friendly_responses)
    nodes = branches(rows, responses, scenario.turns)
    if nodes > MAX_TREE_BRANCHES:
        return _counted(TREE_DEPTH_BRANCHES.format(
            turns=scenario.turns, rows=rows, responses=responses, nodes=nodes, cap=MAX_TREE_BRANCHES, largest=largest,
        ), scenario)
    total = tree_cost(scenario)
    if total > MAX_SAMPLE_HOURS:
        return _counted(TREE_DEPTH_COST.format(
            turns=scenario.turns, total=math.ceil(total), cap=MAX_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
            largest=largest,
        ), scenario)
    return None


# ── Combining a sequence ─────────────────────────────────────────────────────

def paired_minima(earlier: np.ndarray, this: np.ndarray) -> np.ndarray:
    """Each sample's smallest separation along its path: sample k against sample k, never across samples.

    A single computed figure, from before red was sampled, stands for every sample.
    """
    minima: np.ndarray = np.minimum(np.asarray(earlier, dtype=float), np.asarray(this, dtype=float))
    return minima


class PathStep(NamedTuple):
    """One turn of a sequence: red's move, our response, our burn's delta-V, red's burn, if it burnt, and what our
    delta-V rests on, a lookup unless the turn says it was computed."""

    action:        AdversaryAction
    response:      FriendlyResponse
    delta_v_km_s:  float
    red_burn_utc:  datetime | None = None
    delta_v_basis: Basis = Basis.LOOKUP


class _PathCustody(NamedTuple):
    """A sequence's custody: held throughout or not, its hours lost, its hours degraded (SPC-179) and their bases."""

    maintained:     bool
    gap_hours:      float
    degraded_hours: float
    bases:          tuple[FigureBasis, FigureBasis]


def _path_custody(scenario: Scenario, steps: Sequence[PathStep]) -> _PathCustody:
    """The bound red track's custody over the horizon with the sequence's earliest red burn, when it was read; else
    the rule of thumb's worst turn, a lookup, which has no degraded hours."""
    red = scenario.binding.red if scenario.binding is not None else None
    if red is None or red.custody is None:
        figures = [_lookup_figures(s.action, s.response, scenario) for s in steps]
        bases = (LOOKUP_BASES.custody_maintained, LOOKUP_BASES.custody_gap_hours)
        return _PathCustody(
            all(f.custody_maintained for f in figures), max(f.custody_gap_hours for f in figures), 0.0, bases,
        )
    burns = [s.red_burn_utc for s in steps if s.red_burn_utc is not None]
    over = custody_over_horizon(
        red.custody, elset_hours=red.age_hours, limit_hours=red.limit_hours,
        horizon=Horizon(scenario.epoch_utc, scenario.horizon_hours, min(burns, default=None)),
    )
    bases = custody_bases(red.stk_name, over, _PATH_CUSTODY_NOTE, scenario.horizon_hours)
    return _PathCustody(over.maintained, over.lost_hours, over.degraded_hours, bases)


def _listed(items: Sequence[str], joiner: str) -> str:
    """*items* as a list in prose: "a", "a and b", "a, b and c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {joiner} {items[-1]}"


def _path_bases(steps: Sequence[PathStep], *, sampled: bool, elset: ElsetErrorAt | None = None) -> PathBases:
    """What a sequence's figures rest on: its closest approach computed or sampled, with *elset*, the element-set
    error in it or beside it under SPC-202's rule, its delta-V the weakest of its turns', naming each lookup, and its
    score a lookup."""
    unsized = [f"{s.response.name} in turn {k}" for k, s in enumerate(steps, start=1) if s.delta_v_basis is not Basis.COMPUTED]
    if elset is None:
        closest_note = _PATH_SAMPLED_NOTE if sampled else _PATH_COMPUTED_NOTE
    else:
        closest_note = (_PATH_SAMPLED_NOTE_ELSET if sampled else _PATH_COMPUTED_NOTE_ELSET).format(**elset.words())
    delta_v_note = _PATH_DV_NOTE
    if unsized:
        closest_note += _PATH_UNSIZED.format(which=_listed(unsized, "or"))
        delta_v_note += _PATH_DV_LOOKUP.format(which=_listed(unsized, "and"))
    return PathBases(
        FigureBasis(Basis.SAMPLED if sampled else Basis.COMPUTED, closest_note),
        FigureBasis(weakest(*(s.delta_v_basis for s in steps)), delta_v_note),
        FigureBasis(Basis.LOOKUP, _PATH_SCORE_NOTE),
    )


def path_figures(
    scenario: Scenario, steps: Sequence[PathStep], closest_km: float, *, sampled: bool, elset: ElsetErrorAt | None = None,
) -> PathFigures:
    """A sequence's figures from its steps and its closest approach, *sampled* or computed: our burns added up,
    custody with the earliest red burn, time to execute summed and capped at the horizon, the least reversible
    response, and the score, each with its basis. *elset* is the element-set error under SPC-202's rule: drawn in a
    sampled sequence's samples, at the scenario epoch, or beside a computed one's closest approach, at this turn's,
    where the score reads the closest approach less it, never below 0 km."""
    custody = _path_custody(scenario, steps)
    delta_v = sum(s.delta_v_km_s for s in steps)
    tte = min(sum(s.response.time_to_execute_hours for s in steps), scenario.horizon_hours)
    reversibility = min(s.response.reversibility for s in steps)
    standing = dataclasses.replace(steps[-1].response, time_to_execute_hours=tte, reversibility=reversibility)
    scored = closest_km if sampled or elset is None else lower_edge_km(closest_km, elset.combined_km)
    figures = _Figures(custody.maintained, custody.gap_hours, scored, delta_v, custody.degraded_hours)
    score = _score(scenario, standing, figures)
    bases = _path_bases(steps, sampled=sampled, elset=elset)
    return PathFigures(
        closest_km, delta_v, custody.maintained, custody.gap_hours, tte, reversibility, score, custody.bases, bases,
        custody.degraded_hours,
    )


def _require_tree_propagator(tree: GameTree, matrix: Sequence[Sequence[OutcomeMetrics]]) -> None:
    """No node and no cell of a built tree names SGP4: one propagator for every figure (extends SPC-121's rule)."""
    if not tree.roots:
        return
    cells = [c.ca_computed.propagator for row in matrix for c in row if c.ca_computed is not None]
    named = {n.figures.propagator for n in tree.nodes()} | set(cells)
    if ELSET_PROPAGATOR in named:
        raise ValueError("a game tree's figures are RK45 for both orbits, never SGP4")


# ── Building the tree ────────────────────────────────────────────────────────

class _RefusedError(Exception):
    """The tree stops here, and *sentence* says why."""

    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence


class _Carry(NamedTuple):
    """What a branch hands the next turn: where each orbit is at its turn's end, each sample's minimum so far, and
    each sample's burns drawn past its turn's end, for the next turn to make; empty when none is."""

    red:           np.ndarray
    red_bstar:     np.ndarray
    nominal:       np.ndarray
    nominal_bstar: float
    blue:          np.ndarray
    slices:        np.ndarray
    pending:       tuple[tuple[RedBurn, ...], ...] = ()
    # Each sample's blue, read that many seconds on along its own orbit: its element-set draw (SPC-202); None for none.
    blue_shift_s:  np.ndarray | None = None


class _Drawn(NamedTuple):
    """Each sample's red start and B*, and blue's shift, s, drawn where a sampled turn follows a computed one, which
    leaves red one state (SPC-202)."""

    red:          np.ndarray
    red_bstar:    np.ndarray
    blue_shift_s: np.ndarray


class _RedTurn(NamedTuple):
    """Red's move in a turn: its burn, if any, its nominal arc and the B* it ends on, and what was drawn at the turn's
    start, if anything."""

    burn:    TurnBurn | None
    nominal: tuple[Trajectory, float]
    drawn:   _Drawn | None = None


@dataclass(eq=False)
class _Branch:
    """A node while the tree is built, with what its children start from."""

    turn:     int
    steps:    tuple[tuple[int, int], ...]   # (action, response) per turn, this one last
    start:    TurnStart
    figures:  NodeFigures
    path:     PathFigures
    walk:     tuple[PathStep, ...]
    carry:    _Carry | None
    sampled:  bool
    children: list[_Branch] = field(default_factory=list)

    @property
    def red_path(self) -> tuple[int, ...]:
        return tuple(a for a, _ in self.steps)

    def node(self) -> GameNode:
        action, response = self.steps[-1]
        children = tuple(child.node() for child in self.children)
        return GameNode(self.turn, action, response, self.start, self.figures, self.path, children)


class _Blue(NamedTuple):
    """One response's blue over a turn, from its parent, and what the response brings to its node."""

    parent:   _Branch
    column:   int
    arc:      Trajectory
    response: _ResponseCell


class _Found(NamedTuple):
    """One child's searched figures: each sample's miss over the rest of the span and within its turn's slice."""

    misses:   np.ndarray
    slices:   np.ndarray
    approach: Sampled
    series:   SeparationSeries | None


def _sampled_found(series: SeparationSeries, slices: np.ndarray) -> _Found:
    index = cast("int", series.earliest_at_or_below_p5_index)
    approach = series.approaches[index]
    speed = series.closing_speeds_km_s[index] if series.closing_speeds_km_s else math.nan
    misses = np.array([a.miss_km for a in series.approaches])
    return _Found(misses, slices, Sampled(approach, speed), series)


def _series_why(series: SeparationSeries) -> str | None:
    if series.n_failed > 0:
        return _WHY_FAILED.format(k=series.n_failed, n=series.n_samples_run)
    if not series.converged:
        return _WHY_UNCONVERGED.format(hw=series.percentile_half_width_km)
    return None


class _Tree:
    """Builds a tree breadth first under the evaluation's one budget, from the matrix turn 1 left."""

    def __init__(self, scenario: Scenario, result: ScenarioResult, one: TurnOne) -> None:
        self.scenario, self.result, self.one = scenario, result, one
        binding = cast("ScenarioBinding", scenario.binding)
        self.red, self.blue = cast("BoundElset", binding.red), cast("BoundElset", binding.blue)
        self.span_s = _searched_span_s(scenario)
        self.turn_s = self.span_s / scenario.turns
        # Turn 1's matrix propagated both element sets from the epoch already, or the tree was refused at its root.
        self.red0 = cast("BlueTrack", elset_state(self.red.tle, scenario.epoch_utc))
        self.blue0 = cast("BlueTrack", elset_state(self.blue.tle, scenario.epoch_utc))
        self.window = SeparationWindow(scenario.epoch_utc, self.span_s)
        # What every sample draws, red's and blue's 1 sigma at the scenario epoch; None under the rule before SPC-202.
        self.error = sample_error(scenario)
        self.labels = {str(j): f.name for j, f in enumerate(scenario.friendly_responses)}
        self.built = 0

    # ── shared ──

    @property
    def budget(self) -> _Budget | None:
        return self.one.budget

    def _may_start(self) -> None:
        if self.budget is not None and not self.budget.may_start():
            raise _BudgetSpentError(0, 0)

    def _label(self, steps: Sequence[tuple[int, int]]) -> str:
        actions, responses = self.scenario.adversary_actions, self.scenario.friendly_responses
        return ", then ".join(
            f"{actions[a].name} against {responses[r].name} in turn {k}" for k, (a, r) in enumerate(steps, start=1)
        )

    def _refuse(self, steps: Sequence[tuple[int, int]], why: str) -> _RefusedError:
        return _RefusedError(TREE_BRANCH_REFUSED.format(turns=self.scenario.turns, path=self._label(steps), why=why))

    def _path_closest(self, steps: Sequence[tuple[int, int]], minima: np.ndarray, seed: int) -> float:
        """The sequence's closest approach: the one computed figure, or P5 of each sample's own minimum, converged."""
        if minima.size == 1:
            return float(minima[0])
        stats = _miss_stats(minima.tolist(), seed)
        if not stats.converged:
            raise self._refuse(steps, _WHY_PATH_UNCONVERGED.format(hw=stats.half_width_km))
        return stats.p5

    # ── turn 1: the matrix ──

    def roots(self) -> list[_Branch]:
        branches_: list[_Branch] = []
        for i, action in enumerate(self.scenario.adversary_actions):
            sampling = self.one.plan[i]
            if action.hypothesis is not None:
                branches_ += self._sampled_roots(i, cast("RowSampling", sampling))
            else:
                branches_ += self._computed_roots(i)
        self.built = len(branches_)
        return branches_

    def _row_refused(self, i: int, *, spent: bool = False) -> _RefusedError:
        """Row *i* left no orbit in turn 1: the budget ran out before it was sampled, or its cell says why."""
        name = self.scenario.adversary_actions[i].name
        if spent:
            budget_s = cast("_Budget", self.budget).run.budget_s
            return _RefusedError(TREE_BUDGET_TURN_ONE.format(budget=budget_s, row=i + 1, name=name))
        return _RefusedError(TREE_REFUSED_ROW.format(row=i + 1, name=name))

    def _cell(self, i: int, j: int) -> OutcomeMetrics:
        cell = self.result.outcome_matrix[i][j]
        if cell.figure_bases.closest_approach_km.kind is Basis.LOOKUP:
            raise self._refuse([(i, j)], _WHY_TURN_ONE)
        return cell

    def _sampled_roots(self, i: int, sampling: RowSampling) -> list[_Branch]:
        series = sampling.series
        if series is None:
            raise self._row_refused(i, spent=sampling.spent)
        kept = series.kept
        hypothesis = cast("AdversaryHypothesis", self.scenario.adversary_actions[i].hypothesis).hypothesis
        # The series integrated blue over the span already, so its arc does not re-enter here.
        blue = rk45_arc(self.blue0.state_eci_km, self.span_s, self.blue0.bstar)
        nominal = nominal_red_arc(hypothesis, self.window)
        if kept is None or blue is None or nominal is None:
            raise self._refuse([(i, 0)], _WHY_ARC)
        burns = sized_burns(sampling.sized)
        roots = []
        for j in range(len(self.scenario.friendly_responses)):
            cell = self._cell(i, j)
            result = _response_of(sampling.sized, j)
            burn = result.burn if isinstance(result, SizedBurn) else None
            arc = blue if burn is None else self._burnt(blue, burn, self.span_s, [(i, j)])
            variant = 0 if burn is None else burns.index(burn) + 1
            carry = _Carry(
                kept.red[:, 0, :], kept.bstar, nominal(self.turn_s), hypothesis.bstar_post, arc(self.turn_s),
                kept.slice_min_km[variant], kept.pending, None if self.error is None else kept.blue_shift_s,
            )
            roots.append(self._root(i, j, cell, carry, sampled=True))
        return roots

    def _computed_roots(self, i: int) -> list[_Branch]:
        computed = self.one.computed
        if computed is None or computed.approach is None:
            raise self._row_refused(i)
        if computed.approach.propagator == ELSET_PROPAGATOR:
            raise self._refuse([(i, 0)], _WHY_RK45)
        pair = rk45_pair(self.red.tle, self.blue.tle, self.window)
        if isinstance(pair, ElsetFailure):
            raise self._refuse([(i, 0)], _WHY_ARC)
        slice_window = SeparationWindow(self.scenario.epoch_utc, self.turn_s)
        red_at = pair.red(self.turn_s)
        roots = []
        for j in range(len(self.scenario.friendly_responses)):
            cell = self._cell(i, j)
            result = _response_of(computed.responses, j)
            burn = result.burn if isinstance(result, SizedBurn) else None
            arc = pair.blue if burn is None else self._burnt(pair.blue, burn, self.span_s, [(i, j)])
            sliced = searched_approach(pair.red, arc, slice_window).approach.miss_km
            carry = _Carry(
                red_at[None, :], np.array([self.red0.bstar]), red_at, self.red0.bstar, arc(self.turn_s),
                np.array([sliced]),
            )
            roots.append(self._root(i, j, cell, carry, sampled=False))
        return roots

    def _burnt(self, arc: Trajectory, burn: BlueBurn, end_s: float, steps: Sequence[tuple[int, int]]) -> Trajectory:
        try:
            burnt = burnt_arc(arc, burn, end_s, self.blue0.bstar)
        except ReenteredError:
            burnt = None
        if burnt is None:
            raise self._refuse(steps, _WHY_ARC)
        return burnt

    def _root(self, i: int, j: int, cell: OutcomeMetrics, carry: _Carry, *, sampled: bool) -> _Branch:
        action, friendly = self.scenario.adversary_actions[i], self.scenario.friendly_responses[j]
        hypothesis = action.hypothesis
        burn_utc = None if hypothesis is None else hypothesis.hypothesis.epoch_utc
        step = PathStep(action, friendly, _delta_v(cell), burn_utc, cell.figure_bases.delta_v_cost_km_s.kind)
        seed = 0 if hypothesis is None else hypothesis.hypothesis.random_seed
        figures = _cell_figures(cell, carry.slices)
        start = TurnStart(
            0.0, self.red0.state_eci_km[None, :], np.array([self.red0.bstar]), (), self.blue0.state_eci_km, 0.0, seed,
            self.red0.state_eci_km, self.red0.bstar,
        )
        last = self.scenario.turns == 1
        return _Branch(
            1, ((i, j),), start, figures,
            path_figures(self.scenario, [step], figures.closest_approach_km, sampled=sampled, elset=cell.ca_elset_error),
            (step,), None if last else carry, sampled,
        )

    # ── later turns ──

    def level(self, k: int, parents: Sequence[_Branch]) -> list[_Branch]:
        """Turn *k*'s branches, one red path at a time: every response of every parent on it shares red's arcs."""
        groups: dict[tuple[int, ...], list[_Branch]] = {}
        for parent in parents:
            groups.setdefault(parent.red_path, []).append(parent)
        children: list[_Branch] = []
        for group in groups.values():
            for a in range(len(self.scenario.adversary_actions)):
                children += self._continue(k, group, a)
        return children

    def _seed(self, k: int, red_path: Sequence[int], action: AdversaryAction) -> int:
        base = 0 if action.hypothesis is None else action.hypothesis.hypothesis.random_seed
        return int(np.random.SeedSequence([base, k, *red_path]).generate_state(1)[0])

    def _turn_burn(self, k: int, red_path: Sequence[int], action: AdversaryAction) -> TurnBurn | None:
        if action.hypothesis is None:
            return None
        hypothesis = dataclasses.replace(action.hypothesis.hypothesis, random_seed=self._seed(k, red_path, action))
        return TurnBurn(hypothesis, _offset_s(self.scenario, action))

    def _window(self, k: int) -> SeparationWindow:
        at_s = (k - 1) * self.turn_s
        return SeparationWindow(self.scenario.epoch_utc + timedelta(seconds=at_s), self.span_s - at_s)

    def _continue(self, k: int, group: Sequence[_Branch], a: int) -> list[_Branch]:
        action = self.scenario.adversary_actions[a]
        red_path = (*group[0].red_path, a)
        carry = cast("_Carry", group[0].carry)
        window = self._window(k)
        burn = self._turn_burn(k, red_path, action)
        self._may_start()
        nominal = nominal_continued_arc(carry.nominal, carry.nominal_bstar, burn, window.span_s)
        if nominal is None:
            raise self._refuse([*group[0].steps, (a, 0)], _WHY_ARC)
        turn = _RedTurn(burn, nominal, self._draw(carry, burn, [*group[0].steps, (a, 0)]))
        pad = shift_pad_s(carry.blue_shift_s if turn.drawn is None else turn.drawn.blue_shift_s)
        blues = [blue for parent in group for blue in self._responses(k, parent, (a, pad), window, nominal[0])]
        sampled = group[0].sampled or burn is not None
        found = (
            self._sampled(k, (a, carry, turn), blues, window) if sampled else self._computed(k, nominal[0], blues, window)
        )
        return [self._child(blue, a, f, turn, sampled=sampled) for blue, f in zip(blues, found, strict=True)]

    def _draw(self, carry: _Carry, burn: TurnBurn | None, steps: Sequence[tuple[int, int]]) -> _Drawn | None:
        """Each sample's element-set draw where a sampled turn follows a computed one (SPC-202): red's one state moved
        along its orbit by each sample's draw, and blue's draw as the seconds it is read on; None where nothing is
        drawn here: no burn, red sampled already, or the rule before SPC-202."""
        if burn is None or self.error is None or carry.red.shape[0] != 1:
            return None
        n = burn.hypothesis.n_samples
        offsets = elset_offsets_km(self.error, burn.hypothesis.random_seed, n)
        red = moved_states(carry.red[0], float(carry.red_bstar[0]), offsets[:, 0])
        if red is None:
            raise self._refuse(steps, _WHY_ARC)
        return _Drawn(red, np.repeat(carry.red_bstar, n), along_track_shifts_s(offsets[:, 1], carry.blue))

    def _responses(
        self, k: int, parent: _Branch, move: tuple[int, float], window: SeparationWindow, nominal: Trajectory,
    ) -> list[_Blue]:
        """Each response's blue over turn *k* from *parent*: our burn sized again against red's nominal burn. *move*
        is red's move and how far past each end blue's arcs run for each sample's shift to read (SPC-202)."""
        a, pad = move
        try:
            coast = rk45_arc(cast("_Carry", parent.carry).blue, window.span_s, self.blue0.bstar, pad)
        except ReenteredError:
            coast = None
        if coast is None:
            raise self._refuse([*parent.steps, (a, 0)], _WHY_ARC)
        pair = Rk45Pair(nominal, coast, self.blue0.bstar)
        ends = window._replace(span_s=window.span_s + pad)
        return [self._respond(parent, (a, j), (window, ends), pair) for j in range(len(self.scenario.friendly_responses))]

    def _respond(
        self, parent: _Branch, step: tuple[int, int], windows: tuple[SeparationWindow, SeparationWindow], pair: Rk45Pair,
    ) -> _Blue:
        """Our response *step* = (red's move, our response) from *parent*, its burn sized against red's nominal arc.
        *windows* is the turn's window and the same window running as far as blue's arc does (SPC-202)."""
        a, j = step
        window, ends = windows
        friendly = self.scenario.friendly_responses[j]
        spec = friendly.burn
        if spec is None:
            return _Blue(parent, j, pair.blue, _ResponseCell(friendly, None, None))
        at_s = friendly.time_to_execute_hours * _SECONDS_PER_HOUR
        at = window.start_utc + timedelta(seconds=at_s)
        self._may_start()
        tick = None if self.budget is None else self.budget.sizing(self.labels)
        request = BurnRequest(str(j), at_s, spec.target_km, spec.budget_km_s, spec.axis)
        result = size_against(pair, window, request, tick=tick)
        if isinstance(result, BurnRefusal):
            refusal = _response_refusal(result, at, window, _NOMINAL_TCA)
            return _Blue(parent, j, pair.blue, _ResponseCell(friendly, None, refusal))
        figure = ResponseFigure(result, at, spec.target_km, spec.budget_km_s)
        arc = pair.blue if result.burn is None else self._burnt(pair.blue, result.burn, ends.span_s, [*parent.steps, (a, j)])
        return _Blue(parent, j, arc, _ResponseCell(friendly, figure, None))

    def _sampled(
        self, k: int, red: tuple[int, _Carry, _RedTurn], blues: Sequence[_Blue], window: SeparationWindow,
    ) -> list[_Found]:
        a, carry, turn = red
        burn = turn.burn
        if turn.drawn is not None:
            carry = carry._replace(red=turn.drawn.red, red_bstar=turn.drawn.red_bstar,
                                   blue_shift_s=turn.drawn.blue_shift_s)
        n = carry.red.shape[0]
        reps = burn.hypothesis.n_samples if n == 1 and burn is not None else 1
        starts, bstars = np.repeat(carry.red, reps, axis=0), np.repeat(carry.red_bstar, reps)
        pending = tuple(p for p in carry.pending for _ in range(reps))
        shifts = None if carry.blue_shift_s is None else np.repeat(carry.blue_shift_s, reps)
        self._may_start()
        tick = None if self.budget is None else self.budget.sampling()
        keep = (self.turn_s,) if k < self.scenario.turns else ()
        red_on = ContinuedRed(starts, bstars, burn, pending, shifts)
        out = continue_series(red_on, [b.arc for b in blues], window, tick=tick, keep_at_s=keep)
        found = []
        for b, (blue, series) in enumerate(zip(blues, out.series, strict=True)):
            why = _series_why(series)
            if why is not None:
                raise self._refuse([*blue.parent.steps, (a, blue.column)], why)
            misses = np.array([x.miss_km for x in series.approaches])
            found.append(_sampled_found(series, misses if out.kept is None else out.kept.slice_min_km[b]))
        return found

    def _computed(self, k: int, red: Trajectory, blues: Sequence[_Blue], window: SeparationWindow) -> list[_Found]:
        slice_window = SeparationWindow(window.start_utc, self.turn_s)
        found = []
        for blue in blues:
            approach = searched_approach(red, blue.arc, window)
            miss = np.array([approach.approach.miss_km])
            sliced = miss if k == self.scenario.turns else np.array(
                [searched_approach(red, blue.arc, slice_window).approach.miss_km],
            )
            found.append(_Found(miss, sliced, approach, None))
        return found

    def _child(self, blue: _Blue, a: int, found: _Found, red: _RedTurn, *, sampled: bool) -> _Branch:
        parent, action = blue.parent, self.scenario.adversary_actions[a]
        steps = (*parent.steps, (a, blue.column))
        k = len(steps)
        window = self._window(k)
        carry = cast("_Carry", parent.carry)
        if red.drawn is not None:
            carry = carry._replace(red=red.drawn.red, red_bstar=red.drawn.red_bstar, blue_shift_s=red.drawn.blue_shift_s)
        burn, (nominal, nominal_bstar) = red.burn, red.nominal
        friendly = self.scenario.friendly_responses[blue.column]
        delta_v = blue.response.figures(_lookup_figures(action, friendly, self.scenario)).delta_v_km_s
        burn_utc = None if burn is None else window.start_utc + timedelta(seconds=burn.at_s)
        delta_v_basis = blue.response.bases(LOOKUP_BASES).delta_v_cost_km_s.kind
        walk = (*parent.walk, PathStep(action, friendly, delta_v, burn_utc, delta_v_basis))
        seed = 0 if burn is None else burn.hypothesis.random_seed
        closest = self._path_closest(steps, paired_minima(carry.slices, found.misses), seed)
        path = path_figures(self.scenario, walk, closest, sampled=sampled, elset=self._path_error(found, window, sampled=sampled))
        start = TurnStart(
            (k - 1) * self.turn_s, carry.red, carry.red_bstar,
            tuple(s.red_burn_utc for s in parent.walk if s.red_burn_utc is not None), carry.blue,
            parent.path.delta_v_km_s, seed, carry.nominal, carry.nominal_bstar,
        )
        figures = self._figures(steps, found, blue.response, path, delta_v)
        nxt = None if k == self.scenario.turns else self._carry(found, carry, (nominal, nominal_bstar), blue.arc)
        branch = _Branch(k, steps, start, figures, path, walk, nxt, sampled)
        parent.children.append(branch)
        self.built += 1
        return branch

    def _error_at(self, found: _Found, window: SeparationWindow) -> ElsetErrorAt:
        """Both sets' element-set error at *found*'s closest approach (SPC-202)."""
        return elset_error_at(cast("ScenarioBinding", self.scenario.binding), found.approach.approach.tca_utc(window.start_utc))

    def _path_error(self, found: _Found, window: SeparationWindow, *, sampled: bool) -> ElsetErrorAt | None:
        """A sequence's element-set error under SPC-202's rule: what its samples drew, at the scenario epoch, or,
        computed, the error at this turn's closest approach, the latest and so the largest along it, which its score
        reads its closest approach less. None under the rule before."""
        if self.error is None:
            return None
        if sampled:
            return elset_error_at(cast("ScenarioBinding", self.scenario.binding), self.scenario.epoch_utc)
        return self._error_at(found, window)

    def _carry(self, found: _Found, carry: _Carry, nominal: tuple[Trajectory, float], blue: Trajectory) -> _Carry:
        kept = None if found.series is None else found.series.kept
        pending: tuple[tuple[RedBurn, ...], ...] = ()
        shifts = None
        if kept is None:
            red, bstar = nominal[0](self.turn_s)[None, :], carry.red_bstar
        else:
            red, bstar, pending = kept.red[:, 0, :], kept.bstar, kept.pending
            shifts = None if self.error is None else kept.blue_shift_s
        return _Carry(
            red, bstar, nominal[0](self.turn_s), nominal[1], blue(self.turn_s), paired_minima(carry.slices, found.slices),
            pending, shifts,
        )

    def _figures(
        self, steps: Sequence[tuple[int, int]], found: _Found, response: _ResponseCell, path: PathFigures,
        delta_v: float,
    ) -> NodeFigures:
        k = len(steps)
        window = self._window(k)
        series = found.series
        approach, speed = found.approach
        binding = cast("ScenarioBinding", self.scenario.binding)
        tca = (
            _tca_uncertainty(binding, window.start_utc, approach, speed, window.span_s)
            if series is None or self.error is None
            else _drawn_tca_uncertainty(binding, self.scenario.epoch_utc, window, (approach, speed))
        )
        label = _NODE_LABEL.format(k=k, turns=self.scenario.turns, path=self._label(steps))
        if series is None:
            kind, note, ca, band, hw = Basis.COMPUTED, self._computed_note(found, window, path), approach.miss_km, None, None
        else:
            kind, note = Basis.SAMPLED, self._sampled_note(len(series.approaches))
            ca, band, hw = series.miss_km_p5, series.percentiles, series.percentile_half_width_km
        maintained, gap = path.custody_bases
        bases = response.bases(outcome_bases(
            custody_maintained=maintained, custody_gap_hours=gap, closest_approach_km=FigureBasis(kind, label + note),
            time_to_closest_hours=FigureBasis(kind, label + _TIME_NOTE), delta_v_cost_km_s=LOOKUP_BASES.delta_v_cost_km_s,
        ))
        propagator = SEPARATION_PROPAGATOR if series is not None else _TREE_COMPUTED_PROPAGATOR
        return NodeFigures(
            ca, approach.tca_utc(window.start_utc), band, hw, tuple(float(x) for x in found.slices), delta_v, tca,
            bases, propagator,
        )

    def _computed_note(self, found: _Found, window: SeparationWindow, path: PathFigures) -> str:
        """A later computed node's note: with its element-set band and what its sequence's score reads, under SPC-202's
        rule: the path's closest approach less this node's error."""
        if self.error is None:
            return _COMPUTED_NOTE
        error = self._error_at(found, window)
        closest = path.closest_approach_km
        return _COMPUTED_NOTE_ELSET.format(closest=closest, low=lower_edge_km(closest, error.combined_km), **error.words())

    def _sampled_note(self, n: int) -> str:
        """A later sampled node's note: with each sample's element-set draw, under SPC-202's rule."""
        if self.error is None:
            return _SAMPLED_NOTE.format(n=n)
        drawn = elset_error_at(cast("ScenarioBinding", self.scenario.binding), self.scenario.epoch_utc)
        return _SAMPLED_NOTE_ELSET.format(n=n, **drawn.words())


#: A later turn's computed figure: one red and one blue arc, both carried on by RK45.
_TREE_COMPUTED_PROPAGATOR = "RK45 with J2 and exponential drag for both orbits, carried from the turn before"


def _delta_v(cell: OutcomeMetrics) -> float:
    """A cell's delta-V unrounded: our sized burn's, else the lookup or the 0 m/s it shows exactly."""
    return cell.delta_v_cost_km_s if cell.ca_response is None else cell.ca_response.delta_v_km_s


def _cell_figures(cell: OutcomeMetrics, slices: np.ndarray) -> NodeFigures:
    """A turn-1 node's figures: its cell's, unrounded."""
    found = cell.ca_computed
    if found is not None:
        ca, tca = found.approach.miss_km, found.approach.tca_utc(found.window.start_utc)
        band, hw, propagator = None, None, found.propagator
    else:
        percentiles = cast("dict[int, float]", cell.ca_percentiles)
        ca, tca = percentiles[5], cast("SampledTca", cell.ca_sampled_tca).tca_utc
        band, hw, propagator = dict(percentiles), cell.ca_half_width_km, SEPARATION_PROPAGATOR
    return NodeFigures(
        ca, tca, band, hw, tuple(float(x) for x in slices), _delta_v(cell), cell.tca_uncertainty,
        cell.figure_bases, propagator,
    )


# ── The tree's sentences ─────────────────────────────────────────────────────

def _lines(scenario: Scenario) -> tuple[str, ...]:
    span_s = _searched_span_s(scenario)
    turn_s = span_s / scenario.turns
    rows, responses = len(scenario.adversary_actions), len(scenario.friendly_responses)
    t3 = "" if scenario.turns < MAX_TURNS else _TREE_HEADER_T3.format(
        t3=scenario.epoch_utc + timedelta(seconds=2 * turn_s),
    )
    header = TREE_HEADER.format(
        turns=scenario.turns, rows=rows, responses=responses, nodes=branches(rows, responses, scenario.turns),
        turn_h=turn_s / _SECONDS_PER_HOUR, span_h=span_s / _SECONDS_PER_HOUR,
        t2=scenario.epoch_utc + timedelta(seconds=turn_s), t3=t3,
    )
    again = tuple(
        TREE_RED_AGAIN.format(row=i + 1, name=a.name, offset=_offset_s(scenario, a) / _SECONDS_PER_HOUR)
        for i, a in enumerate(scenario.adversary_actions) if a.hypothesis is not None
    )
    counted = remainder_counted(scenario)
    return (header, *(() if counted is None else (counted,)), TREE_PROPAGATOR, TREE_NODE_MEANS, TREE_PATH_MEANS,
            *again, TREE_RESPONSE_AGAIN)


def _windows(scenario: Scenario) -> tuple[SeparationWindow, ...]:
    span_s = _searched_span_s(scenario)
    turn_s = span_s / scenario.turns
    return tuple(
        SeparationWindow(scenario.epoch_utc + timedelta(seconds=k * turn_s), span_s - k * turn_s)
        for k in range(scenario.turns)
    )


def _budget_refusal(scenario: Scenario, budget_s: float, k: int, done: int) -> str:
    rows, responses = len(scenario.adversary_actions), len(scenario.friendly_responses)
    return TREE_BUDGET.format(
        turns=scenario.turns, budget=budget_s, k=k, done=done,
        total=branches(rows, responses, scenario.turns), last=k - 1,
    )


def _build(scenario: Scenario, result: ScenarioResult, one: TurnOne) -> GameTree:
    """Turn by turn under the one budget; a stop part-way keeps the turns built in full and says why."""
    tree = _Tree(scenario, result, one)
    lines, windows = _lines(scenario), _windows(scenario)
    levels: list[list[_Branch]] = []
    try:
        levels.append(tree.roots())
        for k in range(2, scenario.turns + 1):
            levels.append(tree.level(k, levels[-1]))
    except _BudgetSpentError:
        refusal = _budget_refusal(scenario, cast("_Budget", one.budget).run.budget_s, len(levels) + 1, tree.built)
        return _partial(scenario, levels, windows, (*lines, refusal), refusal)
    except _RefusedError as refused:
        return _partial(scenario, levels, windows, (*lines, refused.sentence), refused.sentence)
    return GameTree(scenario.turns, windows, tuple(b.node() for b in levels[0]), scenario.turns, None, lines)


def _partial(
    scenario: Scenario, levels: list[list[_Branch]], windows: tuple[SeparationWindow, ...], lines: tuple[str, ...],
    refusal: str,
) -> GameTree:
    """The turns built in full, with nothing below the deepest of them."""
    if not levels:
        return GameTree(scenario.turns, (), (), 0, refusal, (refusal,))
    for branch in levels[-1]:
        branch.children.clear()
    return GameTree(scenario.turns, windows, tuple(b.node() for b in levels[0]), len(levels), refusal, lines)


def evaluate_tree(
    scenario: Scenario, strategy: SelectorStrategy = SelectorStrategy.MINIMAX, *,
    sampler: Sampler = run_separation_series, run: RunControl | None = None,
) -> ScenarioResult:
    """evaluate_scenario with a game tree of *scenario.turns* turns beside the matrix, or why none was built.

    One turn is evaluate_scenario exactly, with no tree. A tree refused before anything runs keeps the one-turn
    result and says why. Otherwise turn 1 is the matrix, with every computed cell on RK45, and the later turns are
    built under the same budget; a stop raises EvaluationStoppedError, as one turn's does. *strategy* then picks
    over the turns built in full (SPC-141); the matrix's own pick is unchanged. Red's moves are the rows as the engine
    weighs them, the remainder of P among them (SPC-203).
    """
    if scenario.turns == 1:
        return evaluate_scenario(scenario, strategy, sampler=sampler, run=run)
    refusal = refused_before_run(scenario)
    if refusal is not None:
        result = evaluate_scenario(scenario, strategy, sampler=sampler, run=run)
        return dataclasses.replace(result, tree=GameTree(scenario.turns, (), (), 0, refusal, (refusal,)))
    turn_s = _searched_span_s(scenario) / scenario.turns
    result, one = _evaluate(scenario, strategy, sampler, run, turn_s)
    scenario = result.scenario
    tree = _build(scenario, result, one)
    _require_tree_propagator(tree, result.outcome_matrix)
    if tree.complete_turns > 0:
        best = result.robust_best_response
        matrix = None if best is None else scenario.friendly_responses.index(best)
        picked = select(scenario, tree.roots, tree.complete_turns, strategy, matrix_pick=matrix)
        tree = dataclasses.replace(tree, selection=picked)
    return dataclasses.replace(result, tree=tree, budget_ran_out=_ran_out(one.budget))
