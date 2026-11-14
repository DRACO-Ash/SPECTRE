"""Decision Engine: how far each weight can move before the recommendation changes (SPC-205, evaluation F-16).

The composite score's weights are the operator's judgement, and the panel's starting weights are uncited direct
ratings (SPC-151). In a bound scenario of probe P-16 a move of one weight by 0.089 flipped the pick, and nothing said
so. For a pick on the one-turn matrix this finds, for each of the five weights, the smallest change of that weight
alone that changes the pick, in each direction, and what it changes to; or that no change from 0 to 1 does.

● **The path.** One weight moves from its value to v, the other four scaled in proportion to keep the sum 1, as the
  panel's normalisation scales them. Weights that do not sum to 1 are first read as the panel scales them, over their
  sum: every score scales with the sum, so no pick moves.
● **Exact, not sampled.** For fixed cell figures every composite score is linear in v along that path: its five terms
  (decision.score_terms, from the figures the engine kept unrounded) weighed by the moved weights. Expected value's
  means are lines; minimax's and minimin's row-wise maxima and minima are piecewise lines. The pick can change only
  where two responses' aggregates meet, so only where a line of one meets a line of another: every such point inside
  0 to 1 is found, and the pick is read at each point and between each.
● **Ties and rounding as the engine has them.** The engine rounds each composite score to 6 decimal places and
  picks on the rounded scores, the first permitted response winning a tie. At each point read, the search scores
  every cell as the engine would at those weights, rounds it so, and aggregates and picks as find_robust_response
  does: a tie the rounding makes is the engine's tie, and only a move that breaks it the engine's way changes the
  pick. A change at the point itself is "at"; one only beyond it is "past". The points are where the unrounded lines
  meet, and the rounded pick turns within a millionth or so of each; where two responses' unrounded aggregates stay
  within one rounding step of each other over a stretch of the weight, the pick there turns on the rounding, and the
  point is still placed where the lines meet.
● **The words never overstate.** A change is shown rounded down to 3 decimal places, so "at least" or "more than" is
  never above it; the weight's value it names is rounded away from the panel's weight, and the engine's pick there is
  checked to be the one named, a place more being shown where 3 would pass a further change.
● **Vetoes.** A response marked not permitted is never a pick here, as it is never a pick anywhere (SPC-195).
● **What it covers.** The one-turn matrix's pick under one rule. The game tree's picks are not covered.

It reads the result and changes nothing: no figure, no score and no pick. Imports the Decision Engine, never the
reverse; nothing here imports the web layer.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from spectre.domain.decision import (
    FriendlyResponse,
    ScenarioResult,
    SelectorStrategy,
    cell_figures,
    find_robust_response,
    permitted_responses,
    row_shares,
    score_terms,
)
from spectre.domain.provenance import Basis, FigureBasis

#: The five weights, by the Scenario's field and in the words the page uses, in the panel's order.
WEIGHTS: tuple[tuple[str, str], ...] = (
    ("w_custody", "custody"), ("w_closest_approach", "closest approach"), ("w_dv_cost", "our delta-V"),
    ("w_time_to_exec", "time to execute"), ("w_reversibility", "reversibility"),
)
#: The places a weight and a change are shown to, and the least change shown as a number: a smaller one is said to be
#: under 0.001.
_SHOWN_PLACES = 3
_FINEST_SHOWN = 0.001
#: The places the engine rounds each composite score to (decision._outcome), which the search rounds to as well; and
#: the most places a weight's value is shown to, where 3 would pass a further change.
_SCORE_PLACES = 6
#: Who the line is about when the caller names no one: the headline recommendation.
RECOMMENDATION = "The recommendation"

STABILITY_BASIS = (
    "Each weight is moved alone, from 0 to 1, the other four scaled in proportion to keep the sum 1, as the panel "
    "scales them. For fixed cell figures each score is linear in the moved weight, so every point at which the pick "
    "can change is found exactly, not sampled. Each score is rounded to 6 decimal places, as the engine rounds it, "
    "and a tie goes to the response listed first, as the engine breaks it. A response marked not permitted is never "
    "a pick. Each change is rounded down to 3 decimal places, so it is never overstated, and each weight's value is "
    "rounded away from the panel's, so the pick named is the engine's there. It rests on the composite scores, a "
    "lookup."
)
#: What the line beside the recommendation rests on, marked beside it as every figure's basis is.
STABILITY_MARK = FigureBasis(
    Basis.LOOKUP, "worked out from the composite scores, a lookup while the weights are uncited (SPC-151)",
)
TREE_NOT_COVERED = (
    "The game tree's picks are not covered: this is the weight stability of the one-turn matrix's pick."
)
_NO_PICK = "There is no pick to hold, so no weight stability is shown."
_ALL_ZERO = "Every weight is 0, so every score is 0 and no weight stability is shown."
_HOLDS = (
    "{subject} holds whatever one weight is set to, from 0 to 1, with the other four scaled in proportion to keep the "
    "sum 1."
)
_UNLESS = "{subject} holds unless a weight moves by {least} {by}: {label}'s weight from {base} {to} {at}{alike} makes it {pick}."
#: Beside a change at a point where every permitted response scores alike, which the first listed takes.
_ALIKE = ", where every response scores alike,"
_FIRST_LISTED = " as the first listed"
_AT_ONCE = "{subject} holds only at these weights: {label}'s weight {moved} by under 0.001 from {base} makes it {pick}."
_WHOLE = "{label} {base}: it carries the whole weight, so no other weight can take up a move of it in proportion."
_WEIGHT_LINE = "{label} {base}: lowered, {down}; raised, {up}."
_CHANGES = "{to} {at}{alike} it makes it {pick}"
_NONE_DOWN = "no value down to 0 changes it"
_NONE_UP = "no value up to 1 changes it"
_AT_0 = "it is at 0 already"
_AT_1 = "it is at 1 already"


@dataclass(frozen=True)
class Change:
    """Where moving one weight changes the pick: the weight's value there, how far that is from its value, the new
    pick, whether the pick has changed at that value itself (a tie the new pick wins) or only beyond it, and whether
    the weight was lowered. *alike* when every permitted response scores alike there, so the first listed takes it.
    *shown_at* is the value as the words give it, rounded away from the weight's own, the pick there checked."""

    weight_at: float
    by: float
    pick: FriendlyResponse
    reached: bool
    lowered: bool
    shown_at: str
    alike: bool = False

    @property
    def shown_by(self) -> str:
        """The change as the words give it: rounded down, so never above it."""
        return _shown(math.floor(round(self.by * 10.0 ** _SHOWN_PLACES, _SCORE_PLACES)) / 10.0 ** _SHOWN_PLACES)


@dataclass(frozen=True)
class WeightMove:
    """One weight: its value, the change lowering it and the change raising it, None for none from 0 to 1. *whole*
    when it carries the whole weight, which no other can take up in proportion."""

    name: str
    label: str
    base: float
    down: Change | None
    up: Change | None
    whole: bool = False

    @property
    def line(self) -> str:
        """This weight in a sentence, for the list of every weight."""
        label, base = self.label[0].upper() + self.label[1:], _shown(self.base)
        if self.whole:
            return _WHOLE.format(label=label, base=base)
        down = _AT_0 if self.base <= 0.0 else _change_words(self.down, _NONE_DOWN)
        up = _AT_1 if self.base >= 1.0 else _change_words(self.up, _NONE_UP)
        return _WEIGHT_LINE.format(label=label, base=base, down=down, up=up)


@dataclass(frozen=True)
class WeightStability:
    """A pick's weight stability under one rule: the pick, None for none, and each weight's move in WEIGHTS order.

    *moves* is empty when there is no pick or every weight is 0, and *line* then says which. *subject* names the
    pick in the line: the recommendation, or another rule's pick.
    """

    rule: SelectorStrategy
    pick: FriendlyResponse | None
    moves: tuple[WeightMove, ...]
    subject: str = RECOMMENDATION
    empty: str = _NO_PICK

    @property
    def smallest(self) -> tuple[WeightMove, Change] | None:
        """The least change over every weight and direction, the first weight and then lowering winning a tie."""
        found = [(change.by, n, move, change) for n, move in enumerate(self.moves)
                 for change in (move.down, move.up) if change is not None]
        if not found:
            return None
        _by, _n, move, change = min(found, key=lambda f: (f[0], f[1]))
        return move, change

    @property
    def line(self) -> str:
        """The overall smallest change in a sentence, said beside the pick."""
        if not self.moves:
            return self.empty
        smallest = self.smallest
        if smallest is None:
            return _HOLDS.format(subject=self.subject)
        move, change = smallest
        words = {"subject": self.subject, "label": move.label, "base": _shown(move.base), "pick": _label(change.pick)}
        if change.by < _FINEST_SHOWN:
            return _AT_ONCE.format(**words, moved="lowered" if change.lowered else "raised")
        if change.alike:
            words["pick"] += _FIRST_LISTED
        return _UNLESS.format(
            **words, least="at least" if change.reached else "more than", by=change.shown_by,
            to="to" if change.reached else "past", at=change.shown_at, alike=_ALIKE if change.alike else "",
        )

    @property
    def weight_lines(self) -> tuple[str, ...]:
        """Every weight in a sentence of its own, in the panel's order."""
        return tuple(move.line for move in self.moves)


def _shown(value: float) -> str:
    return f"{value:.{_SHOWN_PLACES}f}"


def _label(response: FriendlyResponse) -> str:
    return f"{response.name} ({response.id})"


def _change_words(change: Change | None, none: str) -> str:
    if change is None:
        return none
    pick = _label(change.pick) + (_FIRST_LISTED if change.alike else "")
    return _CHANGES.format(to="at" if change.reached else "past", at=change.shown_at, pick=pick,
                           alike=_ALIKE if change.alike else "")


# ── The search ────────────────────────────────────────────────────────────────

#: A cell's score as a line in the moved weight: (its score at the weight's own value, its slope).
_Line = tuple[float, float]


@dataclass(frozen=True)
class _Matrix:
    """What the search reads: each cell's five terms, the weights over their sum, the rows' shares and the permitted
    responses."""

    terms: tuple[tuple[tuple[float, ...], ...], ...]
    weights: tuple[float, ...]
    shares: tuple[float, ...]
    allowed: tuple[int, ...]
    responses: tuple[FriendlyResponse, ...]


def weight_stability(
    result: ScenarioResult, rule: SelectorStrategy, *, subject: str = RECOMMENDATION,
) -> WeightStability:
    """*rule*'s pick on *result*'s one-turn matrix, and for each weight the smallest change of it alone that changes
    that pick, each way. *subject* names the pick in the line."""
    scenario = result.scenario
    pick = find_robust_response(scenario, result.outcome_matrix, rule)
    if pick is None:
        return WeightStability(rule, None, (), subject)
    weights = tuple(getattr(scenario, name) for name, _ in WEIGHTS)
    total = math.fsum(weights)
    if total <= 0.0:
        return WeightStability(rule, pick, (), subject, _ALL_ZERO)
    responses = tuple(scenario.friendly_responses)
    matrix = _Matrix(
        terms=tuple(tuple(score_terms(scenario, f, cell_figures(cell)) for f, cell in zip(responses, row, strict=True))
                    for row in result.outcome_matrix),
        weights=tuple(w / total for w in weights), shares=row_shares(scenario),
        allowed=tuple(permitted_responses(scenario)), responses=responses,
    )
    current = next(j for j, r in enumerate(responses) if r is pick)
    moves = tuple(_move(matrix, rule, k, current) for k in range(len(WEIGHTS)))
    return WeightStability(rule, pick, moves, subject)


def _move(matrix: _Matrix, rule: SelectorStrategy, k: int, current: int) -> WeightMove:
    """Weight *k*'s change each way that moves the pick off response *current*."""
    name, label = WEIGHTS[k]
    base = matrix.weights[k]
    if base >= 1.0:
        return WeightMove(name, label, base, None, None, whole=True)
    crossings = _crossings(_compared(_lines(matrix, k), matrix.shares, rule), base)

    def aggregates_at(v: float) -> dict[int, float]:
        return _aggregates(matrix, rule, _moved(matrix.weights, k, v))

    down = _walk(aggregates_at, current, base, sorted((c for c in crossings if c < base), reverse=True), 0.0)
    up = _walk(aggregates_at, current, base, sorted(c for c in crossings if c > base), 1.0)
    return WeightMove(name, label, base, _change(matrix, aggregates_at, down, base, lowered=True),
                      _change(matrix, aggregates_at, up, base, lowered=False))


def _moved(weights: Sequence[float], k: int, v: float) -> tuple[float, ...]:
    """The weights with *k*'s at *v* and the others scaled in proportion to keep the sum 1."""
    rest = 1.0 - weights[k]
    return tuple(v if i == k else w * (1.0 - v) / rest for i, w in enumerate(weights))


def _lines(matrix: _Matrix, k: int) -> dict[int, list[_Line]]:
    """Each permitted response's cells, row by row, as lines in weight *k*. A cell's slope is its term for *k* less
    its other terms weighed by the other weights over their sum: how its score moves as *k*'s weight moves and the
    others make room."""
    weights, rest = matrix.weights, 1.0 - matrix.weights[k]
    return {
        j: [(math.fsum(w * t for w, t in zip(weights, row[j], strict=True)), _slope(row[j], weights, k, rest))
            for row in matrix.terms]
        for j in matrix.allowed
    }


def _slope(terms: Sequence[float], weights: Sequence[float], k: int, rest: float) -> float:
    others = math.fsum(w * t for i, (w, t) in enumerate(zip(weights, terms, strict=True)) if i != k)
    return terms[k] - others / rest


def _compared(lines: dict[int, list[_Line]], shares: Sequence[float], rule: SelectorStrategy) -> list[list[_Line]]:
    """The lines whose meeting can change *rule*'s pick, by response: under expected value each response's mean, one
    line; under minimax and minimin every row's, since a row-wise maximum or minimum is one of them."""
    if rule is SelectorStrategy.EXPECTED_VALUE:
        return [[(math.fsum(s * a for s, (a, _m) in zip(shares, own, strict=True)),
                  math.fsum(s * m for s, (_a, m) in zip(shares, own, strict=True)))] for own in lines.values()]
    return list(lines.values())


def _crossings(compared: list[list[_Line]], base: float) -> set[float]:
    """Every value of the weight inside 0 to 1, other than its own, at which a line of one response meets a line of
    another: the only places the pick can change."""
    found = set()
    for mine, theirs in itertools.combinations(compared, 2):
        for (a, s), (b, t) in itertools.product(mine, theirs):
            if s != t and 0.0 <= (v := base + (b - a) / (s - t)) <= 1.0 and v != base:
                found.add(v)
    return found


def _aggregates(matrix: _Matrix, rule: SelectorStrategy, weights: Sequence[float]) -> dict[int, float]:
    """Each permitted response's aggregate at *weights*, as the engine forms it: each cell's score its terms weighed in
    the order decision._score adds them, rounded to 6 decimal places, then aggregated as find_robust_response
    aggregates them."""
    aggregate: Callable[[list[float]], float]
    if rule is SelectorStrategy.MINIMAX:
        aggregate = max
    elif rule is SelectorStrategy.MINIMIN:
        aggregate = min
    else:
        def aggregate(cells: list[float]) -> float:
            return sum(share * cell for share, cell in zip(matrix.shares, cells, strict=True))
    return {
        j: aggregate([round(sum(w * t for w, t in zip(weights, row[j], strict=True)), _SCORE_PLACES)
                      for row in matrix.terms])
        for j in matrix.allowed
    }


def _pick(aggregates: dict[int, float]) -> int:
    """The response with the least aggregate, the first permitted winning a tie, as find_robust_response picks."""
    return min(aggregates, key=lambda j: aggregates[j])


def _walk(
    aggregates_at: Callable[[float], dict[int, float]], current: int, base: float, points: list[float], end: float,
) -> tuple[float, int, bool] | None:
    """Walk from *base* through *points* to *end*: the first point at which, or past which, the pick is no longer
    *current*, the pick there, and whether it changed at the point itself; None when it holds to *end*."""
    near = base
    for far in [*points, end]:
        if far == near:
            continue
        between = _pick(aggregates_at((near + far) / 2.0))
        if between != current:
            return near, between, False
        there = _pick(aggregates_at(far))
        if there != current:
            return far, there, True
        near = far
    return None


def _change(
    matrix: _Matrix, aggregates_at: Callable[[float], dict[int, float]], found: tuple[float, int, bool] | None,
    base: float, *, lowered: bool,
) -> Change | None:
    if found is None:
        return None
    at, pick, reached = found
    alike = reached and len(set(aggregates_at(at).values())) == 1
    shown = _shown_value(found, lowered, aggregates_at)
    return Change(at, abs(at - base), matrix.responses[pick], reached, lowered, shown, alike)


def _rounded_away(at: float, lowered: bool, reached: bool, places: int) -> float:
    """*at* to *places*, rounded away from the weight's own value: down when it was lowered, up when raised, and
    strictly beyond *at* for a change only past it; within 0 to 1."""
    scale = 10.0 ** places
    nearest = round(at * scale, _SCORE_PLACES)
    if lowered:
        steps = math.floor(nearest) if reached else math.ceil(nearest) - 1
    else:
        steps = math.ceil(nearest) if reached else math.floor(nearest) + 1
    return min(max(steps / scale, 0.0), 1.0)


def _shown_value(
    found: tuple[float, int, bool], lowered: bool, aggregates_at: Callable[[float], dict[int, float]],
) -> str:
    """The value a change is at, as the words give it: rounded away from the weight's own value, to 3 places, or as
    many more as it takes for the engine's pick there to be the change's; at 6, the places the engine scores to, as
    it stands."""
    at, pick, reached = found
    tried = ((_rounded_away(at, lowered, reached, places), places)
             for places in range(_SHOWN_PLACES, _SCORE_PLACES + 1))
    return next(f"{value:.{places}f}" for value, places in tried
                if places == _SCORE_PLACES or _pick(aggregates_at(value)) == pick)
