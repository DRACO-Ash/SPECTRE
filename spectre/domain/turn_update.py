"""Decision Engine: what a turn lets us see of red, and the update it makes after turn 1 (SPC-141).

An update needs a stated likelihood model: what we observe of red after a turn, and how likely that is under each
red move. Here it is the bound red track's custody, as the sweep judges it, carried over the horizon with the red
burns on the path (SPC-123), read at the turn's end. Custody lost at a burn in the turn shows that red burnt, though
not which burn; custody held through the turn shows that it did not; custody degraded at the scenario epoch, lost
for any other reason, lost in an earlier turn, or never read, shows nothing. Degraded custody scores between held and
lost (the owner's ruling of 2026-11-05, SPC-179), but it is neither held through a turn nor lost at a burn after
being held: its history cannot judge whether a burn is normal, so it shows nothing here, as before that ruling. Each move gives one of these for certain, so the likelihood of what we
see is 1 under each move that gives it and 0 under the rest, and moves that give the same thing are not told apart.

The posterior after turn 1 is the rows' P restricted to the rows that give what we see, renormalised: Bayes' rule
with that likelihood. It says which turn-1 branch we are on, not what red does next: red's move in each later turn
is weighed by the rows' P as entered, since nothing sourced says how its turn-1 move bears on its next. A row whose
P is a NOTSO suggestion the operator applied carries its interval into the posterior, which is shown across the
range it takes over those intervals, and every share is shown rounded down, so none reads stronger than its inputs.
The rule is the custody rule, not calibrated against any outcome, so the posterior is a lookup. No calibration data
exists yet (SPC-210, evaluation F-22): spectre.domain.likelihood_calibration is the harness a back-test runs through,
but no held history has been run through it, so wherever the update's probability is shown, in the likelihood model's
line and in the update's basis, it says the likelihood is uncalibrated with no calibration data yet (UNCALIBRATED).

Nothing here writes a probability into a row; the selectors show the posterior only under expected value, the one
rule that reads P. Under minimax and minimin the same model says only what each turn lets us see (SPC-142).

Where each turn starts is the engine's (design D3, SPC-187, the owner's ruling of 2026-11-05): ``turn_plan`` places
each boundary from the rows' burn times so every burn falls inside its own turn, and the operator never sets a
length. A row's burns fall one to a turn: taken in turn 1, its burn j falls in turn j at its own time; taken in turn
k, its burn j falls in turn k + j - 1, the same time after that turn starts, and one that would fall after the last
turn is not made. Each boundary is the equal split where that falls after every row's burn of the turn ending and by
every row's next burn, and midway between them where it does not, or midway to the span's end with no next burn.
A record 0.23.0 to 0.36.0 wrote holds equal turns (TurnRule.EQUAL), with each row's one burn at its offset after
every turn starts, and is built as it was then. Imports the Decision Engine, never the reverse; nothing here
imports the web layer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple, cast

from spectre.domain.custody import Custody, Horizon, LossCause, custody_over_horizon
from spectre.domain.decision import (
    MAX_TURNS,
    AdversaryAction,
    ProbabilityRule,
    Scenario,
    Seen,
    TurnRule,
    _row_burns,
    _searched_span_s,
    _untouched,
    joint_points,
    moved_weights,
    row_shares,
)
from spectre.domain.provenance import Basis, FigureBasis

if TYPE_CHECKING:
    from spectre.astro.monte_carlo import ManoeuvreHypothesis
    from spectre.domain.decision_transfer import RowBurns
    from spectre.domain.notso_prior import NotsoPrior

__all__ = [
    "INDEPENDENT_TURNS", "LIKELIHOOD_MODEL", "POSTERIOR_EVERY_ROW", "POSTERIOR_NO_WEIGHT", "POSTERIOR_NOTE",
    "POSTERIOR_ONE_ROW", "POSTERIOR_SHARES", "SEEN_MODEL", "SENTENCES", "TREE_BURN_OUTSIDE_TURN", "TREE_NO_BOUNDARY",
    "TREE_TOO_FEW_TURNS", "UNCALIBRATED", "Posterior", "Seen", "TurnPlan", "burns_on", "likelihood", "model_lines",
    "plan_or_equal", "posteriors", "row_hypotheses", "seen_after", "seen_lines", "share_ranges", "turn_plan",
]

_SECONDS_PER_HOUR = 3600.0
#: Where a boundary goes when the equal split does not fall between the burns it must separate: midway between
#: the latest burn of the turn ending and the earliest of the turn after, or the span's end with no burn after it
#: (SPC-187). Claude's choice, not sourced.
_MIDWAY = 0.5
#: A moment within this of a turn's boundary is on it: burn times are kept to the microsecond.
_ON_THE_BOUNDARY_H = 1e-3 / _SECONDS_PER_HOUR
_HUNDREDTHS = 100


# ── What the result says (SPC-141; the view is SPC-142) ──────────────────────

#: Said wherever the update's probability is shown (SPC-210, evaluation F-22): in the likelihood model's line and in
#: the update's basis. It stays until held histories have been run through spectre.domain.likelihood_calibration
#: and the owner rules on what they show.
UNCALIBRATED = (
    "the likelihood is uncalibrated, with no calibration data yet: no held history of what red did has been "
    "scored against it (SPC-210)"
)
LIKELIHOOD_MODEL = (
    "The update after turn 1 rests on this likelihood model: what turn 1 lets us see of red is the bound red "
    "track's custody, as the sweep judges it, carried over turn 1 with each row's burn. Custody lost at a burn in "
    "the turn shows that red burnt, not which burn; custody held through it shows that red did not; custody "
    "degraded, lost for any other reason, or not read, shows nothing. {rows}. Each row gives what it gives for certain, so rows "
    "that give the same thing are not told apart. It is the custody rule, not calibrated against any outcome: "
    f"{UNCALIBRATED}. So the update is a lookup; the same rule reads turn 2 in a 3-turn tree."
)
# Under minimax and minimin (SPC-142): the same model sets what each later pick may see, but nothing is updated.
SEEN_MODEL = (
    "Each later pick may rest only on what the turns before it let us see of red: the bound red track's custody, "
    "as the sweep judges it, carried over each turn with each row's burn. Custody lost at a burn in the turn shows "
    "that red burnt, not which burn; custody held through it shows that red did not; custody degraded, lost for any "
    "other reason, or not read, shows nothing. In turn 1: {rows}. Each row gives what it gives for certain, so branches "
    "that show the same thing share one pick. It is the custody rule, not calibrated against any outcome."
)
INDEPENDENT_TURNS = (
    "The update says which turn-1 branch we are on, not what red does next: red's move in each later turn is "
    "weighed by the rows' P as entered, since nothing sourced says how its turn-1 move bears on its next."
)
POSTERIOR_SHARES = "If turn 1 shows {seen}: {shares}."
POSTERIOR_ONE_ROW = (
    "If turn 1 shows {seen}: only row {row}, {name}, gives it, so the update puts all the weight there. That is the "
    "likelihood model's assumption, not evidence of more."
)
POSTERIOR_EVERY_ROW = "If turn 1 shows {seen}: every row gives it, so the update leaves the weights as P set them."
POSTERIOR_NO_WEIGHT = "If turn 1 shows {seen}: no update, since every row that gives it has P 0."
_SHARE = "row {row}, {name}, {share} of the weight{range}, from {source}"
_RANGE = ", {low} to {high} across the NOTSO intervals"
_FROM_NOTSO = "the NOTSO suggestion you applied"
_FROM_DEFAULT = "the default P of 0.5, untouched"
_FROM_OWN = "your P"
_FROM_REMAINDER = "the engine's remainder of P, the chance that none of your actions happens"
_GIVES = "{lead} {row}, {name}, gives {seen}"
POSTERIOR_NOTE = (
    "the rows' P restricted to those that give what turn 1 shows, renormalised, under the custody rule as the "
    f"likelihood model, a lookup; {UNCALIBRATED}"
)

# Why the engine sets no turns (SPC-187): the tree is refused before anything runs and the one-turn result stands.
TREE_TOO_FEW_TURNS = (
    "No tree built: row {row}, {name}, makes {n} burns of one transfer within the span searched, and every burn falls "
    "inside a turn of its own, so it needs {n} turns, more than the {turns} asked for. This result is one turn."
)
TREE_NO_BOUNDARY = (
    "No tree built: row {late}, {late_name}, makes burn {j1} at {h1:.2f} h, no later than row {early}, {early_name}, "
    "makes burn {j} at {h0:.2f} h, so no turn {j} can end after every row's burn {j} and by every row's burn {j1}. "
    "This result is one turn."
)
TREE_BURN_OUTSIDE_TURN = (
    "No tree built: {what} at {h:.2f} h after turn {k} starts falls outside that turn, {turn_h:.2f} h long. The "
    "engine sets each turn from the rows' burn times so every burn falls inside its own turn; take fewer turns. This "
    "result is one turn."
)

#: Every sentence the result may carry, for the house checks.
SENTENCES: tuple[str, ...] = (
    UNCALIBRATED, LIKELIHOOD_MODEL, SEEN_MODEL, INDEPENDENT_TURNS, POSTERIOR_SHARES, POSTERIOR_ONE_ROW,
    POSTERIOR_EVERY_ROW, POSTERIOR_NO_WEIGHT, TREE_TOO_FEW_TURNS, TREE_NO_BOUNDARY, TREE_BURN_OUTSIDE_TURN,
)


# ── Where each turn starts (design D3, SPC-187) ──────────────────────────────

@dataclass(frozen=True)
class TurnPlan:
    """Where each turn of a game tree starts, seconds after the scenario epoch, and when each row burns in its turns.

    *starts_s* holds turn 1's start, 0, then each boundary; *span_s* ends the last turn. *burns_s* holds, per row,
    each of its burns' seconds after its own turn starts, burn 1 first: empty for a row that does not burn.
    """

    starts_s: tuple[float, ...]
    span_s:   float
    burns_s:  tuple[tuple[float, ...], ...]

    @property
    def turns(self) -> int:
        return len(self.starts_s)

    def start_s(self, k: int) -> float:
        """Turn *k*'s start, from 1."""
        return self.starts_s[k - 1]

    def end_s(self, k: int) -> float:
        """Turn *k*'s end: the next turn's start, or the span's end for the last."""
        return self.starts_s[k] if k < self.turns else self.span_s

    def length_s(self, k: int) -> float:
        return self.end_s(k) - self.start_s(k)

    def move_burns_s(self, row: int, k: int) -> tuple[float, ...]:
        """Row *row*'s burns when it is red's move in turn *k*, seconds after the scenario epoch: its burn j in turn
        k + j - 1, the same time after that turn starts as in turn j; one that would fall after the last turn is not
        made."""
        return tuple(self.start_s(k + j) + d for j, d in enumerate(self.burns_s[row]) if k + j <= self.turns)


def row_hypotheses(scenario: Scenario, action: AdversaryAction) -> tuple[tuple[int, ManoeuvreHypothesis], ...]:
    """Each burn *action*'s row applies within the span searched, numbered as the transfer numbers it, as the matrix
    samples it (SPC-184); empty with no hypothesis. Under equal turns, the row's first burn alone, as it was then."""
    if action.hypothesis is None:
        return ()
    if scenario.turn_rule is TurnRule.EQUAL:
        return ((1, action.hypothesis.hypothesis),)
    red = None if scenario.binding is None else scenario.binding.red
    burns = cast("RowBurns", _row_burns(action, red))
    # A row whose every burn is dropped is refused before any tree is planned (decision._after_burn): its own burn 1.
    numbers = burns.applied or (1,)
    end = scenario.epoch_utc + timedelta(seconds=_searched_span_s(scenario))
    later = [(k, h) for k, h in zip(numbers[1:], burns.then, strict=True) if h.epoch_utc < end]
    return ((numbers[0], burns.first), *later)


def _stated_offsets(scenario: Scenario) -> list[tuple[float, ...]]:
    """Each row's first burn as stated, seconds after the scenario epoch: the one burn equal turns read."""
    return [
        () if a.hypothesis is None else ((a.hypothesis.hypothesis.epoch_utc - scenario.epoch_utc).total_seconds(),)
        for a in scenario.adversary_actions
    ]


def _equal(span_s: float, offsets: Sequence[tuple[float, ...]], turns: int) -> TurnPlan:
    """Equal turns over *span_s*, each row's first burn at its offset after every turn starts (the rule to 0.36.0)."""
    return TurnPlan(tuple(k * span_s / turns for k in range(turns)), span_s, tuple(o[:1] for o in offsets))


def _boundary(scenario: Scenario, previous: float, offsets: Sequence[tuple[float, ...]], at: tuple[int, int],
              span_s: float) -> float | str:
    """Where turn j ends, *at* being (j, turns): after every row's burn j and by every row's burn j + 1, at the
    equal split where that falls between them, else midway, to the span's end with no burn j + 1; or why no
    moment does."""
    j, turns = at
    ending = [(o[j - 1], i) for i, o in enumerate(offsets) if len(o) >= j]
    following = [(o[j], i) for i, o in enumerate(offsets) if len(o) > j]
    lo, early = max(ending, default=(previous, -1))
    lo = max(lo, previous)
    hi, late = min(following, default=(span_s, -1))
    if hi <= lo:
        rows = scenario.adversary_actions
        return TREE_NO_BOUNDARY.format(
            late=late + 1, late_name=rows[late].name, j1=j + 1, h1=hi / _SECONDS_PER_HOUR,
            early=early + 1, early_name=rows[early].name, j=j, h0=lo / _SECONDS_PER_HOUR,
        )
    equal = j * span_s / turns
    return equal if lo < equal <= hi else lo + _MIDWAY * (hi - lo)


def _outside(scenario: Scenario, plan: TurnPlan) -> str | None:
    """The first burn that falls outside a turn it is made in, red's rows first, then our responses; None for none."""
    for i, action in enumerate(scenario.adversary_actions):
        numbered = row_hypotheses(scenario, action)
        for j, ((number, _), d) in enumerate(zip(numbered, plan.burns_s[i], strict=True)):
            refused = _first_outside(plan, _burn_name(scenario, i, number), d, range(j + 1, plan.turns + 1))
            if refused is not None:
                return refused
    for response in scenario.friendly_responses:
        if response.burn is not None:
            d = response.time_to_execute_hours * _SECONDS_PER_HOUR
            refused = _first_outside(plan, f"{response.name}'s burn", d, range(1, plan.turns + 1))
            if refused is not None:
                return refused
    return None


def _burn_name(scenario: Scenario, row: int, number: int = 1) -> str:
    """A row's burn as a refusal names it: "Name's burn", or "Name's burn 2" for a transfer."""
    action = scenario.adversary_actions[row]
    several = len(row_hypotheses(scenario, action)) > 1
    return f"{action.name}'s burn {number}" if several else f"{action.name}'s burn"


def _first_outside(plan: TurnPlan, what: str, d: float, turns: Sequence[int]) -> str | None:
    """*what*, *d* seconds after each of *turns* starts, refused in the first it falls outside; None for none."""
    for k in turns:
        if not 0.0 <= d < plan.length_s(k):
            return TREE_BURN_OUTSIDE_TURN.format(
                what=what, h=d / _SECONDS_PER_HOUR, k=k, turn_h=plan.length_s(k) / _SECONDS_PER_HOUR,
            )
    return None


def _engine(scenario: Scenario, span_s: float, offsets: Sequence[tuple[float, ...]]) -> TurnPlan | str:
    """The turns the engine sets from the rows' burn times (SPC-187), or why it can set none."""
    turns = scenario.turns
    for i, o in enumerate(offsets):
        name = scenario.adversary_actions[i].name
        if o and o[0] >= span_s:
            # Its first burn falls after the span searched, so in no turn: refused before any boundary is placed.
            return TREE_BURN_OUTSIDE_TURN.format(what=_burn_name(scenario, i), h=o[0] / _SECONDS_PER_HOUR, k=1,
                                                 turn_h=span_s / _SECONDS_PER_HOUR)
        if len(o) > turns:
            return TREE_TOO_FEW_TURNS.format(row=i + 1, name=name, n=len(o), turns=turns)
    starts = [0.0]
    for j in range(1, turns):
        placed = _boundary(scenario, starts[-1], offsets, (j, turns), span_s)
        if isinstance(placed, str):
            return placed
        starts.append(placed)
    plan = TurnPlan(tuple(starts), span_s, tuple(tuple(t - starts[j] for j, t in enumerate(o)) for o in offsets))
    return _outside(scenario, plan) or plan


def turn_plan(scenario: Scenario) -> TurnPlan | str:
    """Where each of *scenario.turns* turns starts and when each row burns in them, or why no turns fit (D3).

    Under the engine's rule (SPC-187) each boundary is set from the rows' burn times so every burn falls inside its
    own turn, a transfer's burns one to a turn; refused when a transfer has more burns than turns, when no moment
    falls between one row's burn and another's next, or when a burn made again, or a response's burn, falls outside a
    turn it is made in. Under equal turns, the rule of 0.23.0 to 0.36.0, the span is split equally, and decision_tree
    checks each burn as it did then.
    """
    span_s = _searched_span_s(scenario)
    if scenario.turn_rule is TurnRule.EQUAL:
        return _equal(span_s, _stated_offsets(scenario), scenario.turns)
    offsets = [
        tuple((h.epoch_utc - scenario.epoch_utc).total_seconds() for _, h in row_hypotheses(scenario, action))
        for action in scenario.adversary_actions
    ]
    return _engine(scenario, span_s, offsets)


def plan_or_equal(scenario: Scenario) -> TurnPlan:
    """The turns the engine sets, or equal turns where it sets none: only a selector over nodes a test gives asks for
    turns no tree was built over."""
    plan = turn_plan(scenario)
    if isinstance(plan, TurnPlan):
        return plan
    return _equal(_searched_span_s(scenario), _stated_offsets(scenario), scenario.turns)


def _as_plan(scenario: Scenario, turns: TurnPlan | float) -> TurnPlan:
    """*turns* as a plan: a length in seconds is equal turns of it, each row's first burn at its offset after every
    turn starts, as before SPC-187."""
    if isinstance(turns, TurnPlan):
        return turns
    return _equal(MAX_TURNS * turns, _stated_offsets(scenario), MAX_TURNS)


# ── What a turn shows ────────────────────────────────────────────────────────

def burns_on(scenario: Scenario, red_path: Sequence[int], turns: TurnPlan | float) -> tuple[datetime, ...]:
    """Each red burn on *red_path*, the move in turn k making its burns as *turns* places them: a TurnPlan, or a
    length in seconds for equal turns, each burn its stated offset after turn k starts."""
    plan = _as_plan(scenario, turns)
    return tuple(
        scenario.epoch_utc + timedelta(seconds=s)
        for k, a in enumerate(red_path, start=1) for s in plan.move_burns_s(a, k)
    )


def seen_after(scenario: Scenario, red_path: Sequence[int], turns: TurnPlan | float) -> Seen:
    """What we see of red at the end of turn len(*red_path*), red having made its moves on *red_path* so far, the
    turns as *turns* places them."""

    red = None if scenario.binding is None else scenario.binding.red
    if red is None or red.custody is None or red.custody.state is Custody.DEGRADED:
        return Seen.NOTHING   # degraded is neither held through a turn nor lost at a burn from held (D10, SPC-179)
    plan = _as_plan(scenario, turns)
    burns = burns_on(scenario, red_path, plan)
    over = custody_over_horizon(
        red.custody, elset_hours=red.age_hours, limit_hours=red.limit_hours,
        limit_figure=red.limit_figure,
        horizon=Horizon(scenario.epoch_utc, scenario.horizon_hours, min(burns, default=None)),
    )
    k = len(red_path)
    end_h, start_h = plan.end_s(k) / _SECONDS_PER_HOUR, plan.start_s(k) / _SECONDS_PER_HOUR
    lost = over.lost_from_h
    if lost is None or lost >= end_h - _ON_THE_BOUNDARY_H:
        return Seen.NO_BURN
    if over.cause is LossCause.BURN and lost >= start_h - _ON_THE_BOUNDARY_H:
        return Seen.BURN
    return Seen.NOTHING


def likelihood(scenario: Scenario, turns: TurnPlan | float) -> tuple[Seen, ...]:
    """Per row, what turn 1 shows when red takes it: the one thing under which that row's likelihood is 1."""
    return tuple(seen_after(scenario, (i,), turns) for i in range(len(scenario.adversary_actions)))


# ── The posterior after turn 1 ───────────────────────────────────────────────

class Posterior(NamedTuple):
    """The weight on each turn-1 row once turn 1 shows *seen*; None for a row that does not give it, or for every
    row when those that do have no weight. *ranges* is each share across the NOTSO intervals of the rows that give
    it; *line* says it in words."""

    seen:   Seen
    shares: tuple[float | None, ...]
    ranges: tuple[tuple[float, float] | None, ...]
    line:   str
    basis:  FigureBasis


def _span(prior: NotsoPrior) -> tuple[float, float]:
    """A NOTSO P's interval, from the edge a pick is checked from."""
    interval = prior.interval
    return interval.checked_low, interval.high


def share_ranges(scenario: Scenario, members: Sequence[int]) -> tuple[tuple[float, float], ...]:
    """Each member's share of the weight, least and most, across the NOTSO intervals of the rows that carry one.

    A share is a member's P over the members' sum, a ratio of two lines in the moved P, so its least and its most
    fall on corners of the region those P may take together (decision.joint_points): under the remainder rule the
    box of the intervals cut where the rows' P would sum above 1, the remainder row taking up each move (SPC-203).
    With the rows' P at 1 no remainder row was evaluated to take up a move, so the shares are read at the P entered.
    A corner where the members have no weight between them is passed over.
    """
    row_shares(scenario)   # refuses rows that leave a remainder of P they do not hold
    rows = scenario.adversary_actions
    spans = {i: _span(a.accepted_prior) for i, a in enumerate(rows) if a.accepted_prior is not None}
    if scenario.probability_rule is ProbabilityRule.REMAINDER and not (rows and rows[-1].remainder):
        spans = {}
    order = sorted(spans)
    corners = joint_points(scenario, spans)
    points = [moved_weights(scenario, dict(zip(order, corner, strict=True))) for corner in corners]
    shares = [[w[m] / total for m in members] for w in points if (total := sum(w[m] for m in members)) > 0.0]
    return tuple((min(s[k] for s in shares), max(s[k] for s in shares)) for k in range(len(members)))


def _down(value: float) -> str:
    return f"{math.floor(value * _HUNDREDTHS + 1e-9) / _HUNDREDTHS:.2f}"


def _up(value: float) -> str:
    return f"{math.ceil(value * _HUNDREDTHS - 1e-9) / _HUNDREDTHS:.2f}"


def _source(action: AdversaryAction) -> str:
    if action.remainder:
        return _FROM_REMAINDER
    if action.accepted_prior is not None:
        return _FROM_NOTSO
    return _FROM_DEFAULT if _untouched(action) else _FROM_OWN


def _shares_line(scenario: Scenario, members: Sequence[int], shares: Sequence[float], ranges: Sequence[tuple[float, float]]) -> str:
    moved = any(scenario.adversary_actions[i].accepted_prior is not None for i in members)
    parts = []
    for i, share, (low, high) in zip(members, shares, ranges, strict=True):
        action = scenario.adversary_actions[i]
        span = _RANGE.format(low=_down(low), high=_up(high)) if moved else ""
        parts.append(_SHARE.format(row=i + 1, name=action.name, share=_down(share), range=span, source=_source(action)))
    return "; ".join(parts)


def _posterior(scenario: Scenario, seen: Seen, gives: Sequence[Seen]) -> Posterior:
    rows = len(gives)
    members = [i for i, g in enumerate(gives) if g is seen]
    weights = [scenario.adversary_actions[i].probability for i in members]
    total = sum(weights)
    basis = FigureBasis(Basis.LOOKUP, POSTERIOR_NOTE)
    if total <= 0.0:
        return Posterior(seen, (None,) * rows, (None,) * rows, POSTERIOR_NO_WEIGHT.format(seen=seen.value), basis)
    found = share_ranges(scenario, members)
    shares: list[float | None] = [None] * rows
    ranges: list[tuple[float, float] | None] = [None] * rows
    for i, w, r in zip(members, weights, found, strict=True):
        shares[i], ranges[i] = w / total, r
    if len(members) == rows:
        line = POSTERIOR_EVERY_ROW.format(seen=seen.value)
    elif len(members) == 1:
        line = POSTERIOR_ONE_ROW.format(seen=seen.value, row=members[0] + 1, name=scenario.adversary_actions[members[0]].name)
    else:
        held = [cast("float", shares[i]) for i in members]
        line = POSTERIOR_SHARES.format(seen=seen.value, shares=_shares_line(scenario, members, held, found))
    return Posterior(seen, tuple(shares), tuple(ranges), line, basis)


def posteriors(scenario: Scenario, gives: Sequence[Seen]) -> tuple[Posterior, ...]:
    """The posterior after turn 1 for each thing turn 1 may show, in the order Seen lists them."""
    return tuple(_posterior(scenario, seen, gives) for seen in Seen if seen in gives)


def _rows_give(scenario: Scenario, gives: Sequence[Seen], first: str) -> str:
    return "; ".join(
        _GIVES.format(lead=first if i == 0 else "row", row=i + 1, name=a.name, seen=g.value)
        for i, (a, g) in enumerate(zip(scenario.adversary_actions, gives, strict=True))
    )


def model_lines(scenario: Scenario, gives: Sequence[Seen]) -> tuple[str, str]:
    """The likelihood model, naming what each row gives, and that the update leaves red's later moves at their P."""
    return LIKELIHOOD_MODEL.format(rows=_rows_give(scenario, gives, "Row")), INDEPENDENT_TURNS


def seen_lines(scenario: Scenario, gives: Sequence[Seen]) -> tuple[str]:
    """What each turn lets us see, naming what each row gives in turn 1, for a rule that reads no probability: the
    model sets what each later pick may depend on, but nothing is updated and no P weighs red (SPC-142)."""
    return (SEEN_MODEL.format(rows=_rows_give(scenario, gives, "row")),)
