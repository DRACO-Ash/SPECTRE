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
The rule is the custody rule, not calibrated against any outcome, so the posterior is a lookup.

Nothing here writes a probability into a row; the selectors show the posterior only under expected value, the one
rule that reads P. Under minimax and minimin the same model says only what each turn lets us see (SPC-142). Imports the Decision Engine, never the reverse; nothing here imports the web layer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple, cast

from spectre.domain.custody import Custody, Horizon, LossCause, custody_over_horizon
from spectre.domain.decision import (
    AdversaryAction,
    ProbabilityRule,
    Scenario,
    Seen,
    _untouched,
    joint_points,
    moved_weights,
    row_shares,
)
from spectre.domain.provenance import Basis, FigureBasis

if TYPE_CHECKING:
    from spectre.domain.notso_prior import NotsoPrior

__all__ = [
    "INDEPENDENT_TURNS", "LIKELIHOOD_MODEL", "POSTERIOR_EVERY_ROW", "POSTERIOR_NO_WEIGHT", "POSTERIOR_NOTE",
    "POSTERIOR_ONE_ROW", "POSTERIOR_SHARES", "SEEN_MODEL", "SENTENCES", "Posterior", "Seen", "burns_on", "likelihood",
    "model_lines", "posteriors", "seen_after", "seen_lines", "share_ranges",
]

_SECONDS_PER_HOUR = 3600.0
#: A moment within this of a turn's boundary is on it: burn times are kept to the microsecond.
_ON_THE_BOUNDARY_H = 1e-3 / _SECONDS_PER_HOUR
_HUNDREDTHS = 100


# ── What the result says (SPC-141; the view is SPC-142) ──────────────────────

LIKELIHOOD_MODEL = (
    "The update after turn 1 rests on this likelihood model: what turn 1 lets us see of red is the bound red "
    "track's custody, as the sweep judges it, carried over turn 1 with each row's burn. Custody lost at a burn in "
    "the turn shows that red burnt, not which burn; custody held through it shows that red did not; custody "
    "degraded, lost for any other reason, or not read, shows nothing. {rows}. Each row gives what it gives for certain, so rows "
    "that give the same thing are not told apart. It is the custody rule, not calibrated against any outcome, so "
    "the update is a lookup; the same rule reads turn 2 in a 3-turn tree."
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
    "likelihood model, a lookup"
)

#: Every sentence the result may carry, for the house checks.
SENTENCES: tuple[str, ...] = (
    LIKELIHOOD_MODEL, SEEN_MODEL, INDEPENDENT_TURNS, POSTERIOR_SHARES, POSTERIOR_ONE_ROW, POSTERIOR_EVERY_ROW, POSTERIOR_NO_WEIGHT,
)


# ── What a turn shows ────────────────────────────────────────────────────────

def burns_on(scenario: Scenario, red_path: Sequence[int], turn_s: float) -> tuple[datetime, ...]:
    """Each red burn on *red_path*, the move in turn k burning its stated offset after turn k starts."""
    burns = []
    for k, a in enumerate(red_path):
        hypothesis = scenario.adversary_actions[a].hypothesis
        if hypothesis is not None:
            offset = hypothesis.hypothesis.epoch_utc - scenario.epoch_utc
            burns.append(scenario.epoch_utc + timedelta(seconds=k * turn_s) + offset)
    return tuple(burns)


def seen_after(scenario: Scenario, red_path: Sequence[int], turn_s: float) -> Seen:
    """What we see of red at the end of turn len(*red_path*), red having made its moves on *red_path* so far."""
    red = None if scenario.binding is None else scenario.binding.red
    if red is None or red.custody is None or red.custody.state is Custody.DEGRADED:
        return Seen.NOTHING   # degraded is neither held through a turn nor lost at a burn from held (D10, SPC-179)
    burns = burns_on(scenario, red_path, turn_s)
    over = custody_over_horizon(
        red.custody, elset_hours=red.age_hours, limit_hours=red.limit_hours,
        horizon=Horizon(scenario.epoch_utc, scenario.horizon_hours, min(burns, default=None)),
    )
    k = len(red_path)
    end_h, start_h = k * turn_s / _SECONDS_PER_HOUR, (k - 1) * turn_s / _SECONDS_PER_HOUR
    lost = over.lost_from_h
    if lost is None or lost >= end_h - _ON_THE_BOUNDARY_H:
        return Seen.NO_BURN
    if over.cause is LossCause.BURN and lost >= start_h - _ON_THE_BOUNDARY_H:
        return Seen.BURN
    return Seen.NOTHING


def likelihood(scenario: Scenario, turn_s: float) -> tuple[Seen, ...]:
    """Per row, what turn 1 shows when red takes it: the one thing under which that row's likelihood is 1."""
    return tuple(seen_after(scenario, (i,), turn_s) for i in range(len(scenario.adversary_actions)))


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
