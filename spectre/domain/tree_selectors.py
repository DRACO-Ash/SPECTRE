"""Decision Engine: selectors over a game tree (SPC-141).

A tree's pick for each turn may depend only on what we would have seen by then. What a turn shows of red is
spectre.domain.turn_update's likelihood model, so earlier red moves that show the same thing are one information
set, and one pick must serve every branch in it. Each rule is applied by backward induction over those sets:

● Minimax takes, for each response, the worst sequence over every red move and every branch in the set, and picks
  the least: red is taken to choose each move against us, knowing our rule.
● Expected value weighs each red move by its row's share of P and each branch in the set by the product of its moves'
  shares, which is the update after what we have seen (Bayes' rule with the likelihood model), and picks the least
  weighted mean. A set no branch of which has weight has no pick, and says so.
● Minimin takes the best sequence and picks the least: the optimistic rule, not a robust one.

The leaves are each sequence's score, the one-turn weighted sum on its figures, a lookup; lower is better. A tree
built in part is picked over the turns built in full. The first response wins a tie, as in one turn. A response
marked not permitted (SPC-195) is never valued, so no turn picks it and a tie never brings it back; with every
response so marked, turn 1 has no pick and says why. Its branches are still built and shown. Nothing here writes a
probability into a row, and the update is shown only under expected value, the one rule that reads P.
Imports the Decision Engine, never the reverse; nothing here imports the web layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple, Protocol, cast

from spectre.domain.decision import Scenario, SelectorStrategy, _searched_span_s, permitted_responses, row_shares
from spectre.domain.provenance import Basis, FigureBasis
from spectre.domain.turn_update import Posterior, Seen, likelihood, model_lines, posteriors, seen_after, seen_lines

# ── What the result says (SPC-141; the view is SPC-142) ──────────────────────

RULES: dict[SelectorStrategy, str] = {
    SelectorStrategy.MINIMAX: (
        "Minimax over {span}: each turn's pick is the response whose worst sequence scores least, over every red "
        "move and every earlier branch that fits what we would have seen by then. Red is taken to choose each move "
        "against us."
    ),
    SelectorStrategy.EXPECTED_VALUE: (
        "Expected value over {span}: each turn's pick is the response whose sequences score least on average, each "
        "red move weighed by its row's share of P and each earlier branch by the update after what we would have "
        "seen by then."
    ),
    SelectorStrategy.MINIMIN: (
        "Minimin over {span}: each turn's pick is the response whose best sequence scores least, over every red "
        "move and every earlier branch that fits what we would have seen by then. It is the optimistic rule, not a "
        "robust one."
    ),
}
PARTIAL = "The picks stop at turn {k}, the deepest of the {turns} turns built in full."
PICK_FIRST = "Turn 1: {pick}."
PICK_LATER = "Turn {k}, if {history}: {pick}."
NO_PICK_FIRST = "Turn 1: no pick, since every row has P 0."
NO_PICK = "Turn {k}, if {history}: no pick, since every row that fits it has P 0."
# A response marked not permitted (SPC-195): never a pick in any turn, and with every response so marked, no pick.
NO_PICK_VETOED_FIRST = "Turn 1: no pick, since every response is marked not permitted."
EXCLUDED = "Never picked in any turn, being marked not permitted: {names}."
MATRIX_DIFFERS = (
    "Over the {turns} turns, {rule} picks {tree} for turn 1, where the one-turn matrix picks {matrix}: the matrix "
    "sees turn 1 alone."
)
SCORE_NOTE = "each sequence's score, the one-turn weighted sum on its figures, a lookup"
SCORE_LINE = "Each pick rests on its sequences' scores, the one-turn weighted sum on each sequence's figures, a lookup."
PROBABILITY_IGNORED = (
    "{rule} does not use probability, so no update after turn 1 is shown; its later picks rest only on what each "
    "turn lets us see."
)
# What the operator stated turn 1 showed (SPC-142): the update for it alone, or why nothing was updated.
NO_OBSERVATION = (
    "No observation of turn 1 was stated, so nothing was updated: each row keeps the P it was given. State what "
    "turn 1 shows to see the update after it."
)
OBSERVED = "You stated that turn 1 shows {seen}."
OBSERVED_NOT_GIVEN = (
    "You stated that turn 1 shows {seen}, which no row gives under this likelihood model, so nothing was updated."
)
OBSERVED_NO_LATER_TURN = (
    "You stated that turn 1 shows {seen}, but no turn after it was built in full, so nothing was updated."
)
OBSERVED_UNUSED = "You stated that turn 1 shows {seen}; {rule} does not use probability, so it updated nothing."
OBSERVED_NO_PICK = "You stated that turn 1 shows {seen}, but the tree gives no pick, so nothing was updated."
_SHOWS = "turn {m} shows {seen} after {response}"
_SPAN_ONE = "turn 1"
_SPAN = "the {turns} turns"

#: Every sentence the result may carry, for the house checks.
SENTENCES: tuple[str, ...] = (
    *RULES.values(), PARTIAL, PICK_FIRST, PICK_LATER, NO_PICK_FIRST, NO_PICK, NO_PICK_VETOED_FIRST, EXCLUDED,
    MATRIX_DIFFERS, SCORE_LINE,
    PROBABILITY_IGNORED, NO_OBSERVATION, OBSERVED, OBSERVED_NOT_GIVEN, OBSERVED_NO_LATER_TURN, OBSERVED_UNUSED,
    OBSERVED_NO_PICK,
)


# ── The selection as the result carries it ───────────────────────────────────

class TreeNode(Protocol):
    """What a selector reads of a node: red's move, our response, the sequence's score and the next turn's nodes."""

    @property
    def action(self) -> int: ...
    @property
    def response(self) -> int: ...
    @property
    def path_score(self) -> float: ...
    @property
    def children(self) -> Sequence[TreeNode]: ...


#: What we have seen before a turn: our response and what the turn showed, each earlier turn in order.
After = tuple[tuple[int, Seen], ...]


class TurnPick(NamedTuple):
    """The pick for *turn* after *after*, and each response's value there under the rule, lower being better;
    None for a pick or a value that has no weight under expected value, and None for the value of a response marked
    not permitted, which is never valued (SPC-195)."""

    turn:   int
    after:  After
    pick:   int | None
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class TreeSelection:
    """A rule's picks over a tree: turn 1's, then each later turn's after each thing it may have seen, following our
    own picks; what turn 1 shows under each row; the update after turn 1 for each thing it may show, under expected
    value only; the lines of the recommendation, then of the update; and the update for what the operator stated
    turn 1 showed, None when nothing was stated or nothing was updated (SPC-142)."""

    strategy:       SelectorStrategy
    turns:          int
    picks:          tuple[TurnPick, ...]
    likelihood:     tuple[Seen, ...]
    posteriors:     tuple[Posterior, ...]
    recommendation: tuple[str, ...]
    update:         tuple[str, ...]
    basis:          FigureBasis
    stated:         Posterior | None = None

    @property
    def lines(self) -> tuple[str, ...]:
        """Every line, the recommendation's then the update's."""
        return (*self.recommendation, *self.update)


# ── Backward induction over what we have seen ────────────────────────────────

class _Member(NamedTuple):
    """One earlier branch in an information set: its next turn's nodes, red's moves on it and its weight."""

    nodes:  Sequence[TreeNode]
    reds:   tuple[int, ...]
    weight: float


class _Selector:
    def __init__(self, scenario: Scenario, strategy: SelectorStrategy, turns: int, turn_s: float) -> None:
        self.scenario, self.strategy, self.turns, self.turn_s = scenario, strategy, turns, turn_s
        # Each red move's share: its P, the remainder of P a move of its own (SPC-203); over their sum under 0.29.0's rule.
        self.shares = list(row_shares(scenario))
        self.allowed = set(permitted_responses(scenario))
        self.found: dict[After, TurnPick] = {}

    def value(self, members: Sequence[_Member], k: int, after: After) -> float | None:
        """The rule's value of the set *members* in turn *k*, its pick recorded; None with no weight in it, or with
        every response marked not permitted. A response not permitted is never valued, so it is never the pick."""
        values = tuple(
            self._take(members, k, after, r) if r in self.allowed else None
            for r in range(len(self.scenario.friendly_responses))
        )
        known = [j for j, v in enumerate(values) if v is not None]
        pick = min(known, key=lambda j: cast("float", values[j])) if known else None
        self.found[after] = TurnPick(k, after, pick, values)
        return None if pick is None else values[pick]

    def _take(self, members: Sequence[_Member], k: int, after: After, r: int) -> float | None:
        """The value of response *r* in the set: each red move's leaf, or the set each one leads to."""
        moves = [(m, n) for m in members for n in m.nodes if n.response == r]
        if k == self.turns:
            return self._combine([(n.path_score, m.weight * self.shares[n.action]) for m, n in moves])
        groups: dict[Seen, list[_Member]] = {}
        for m, n in moves:
            reds = (*m.reds, n.action)
            seen = seen_after(self.scenario, reds, self.turn_s)
            groups.setdefault(seen, []).append(_Member(n.children, reds, m.weight * self.shares[n.action]))
        return self._combine([
            (self.value(groups[seen], k + 1, (*after, (r, seen))), sum(m.weight for m in groups[seen]))
            for seen in Seen if seen in groups
        ])

    def _combine(self, outcomes: Sequence[tuple[float | None, float]]) -> float | None:
        if self.strategy is SelectorStrategy.MINIMAX:
            return max(cast("float", v) for v, _ in outcomes)
        if self.strategy is SelectorStrategy.MINIMIN:
            return min(cast("float", v) for v, _ in outcomes)
        total = sum(w for _, w in outcomes)
        if total <= 0.0:
            return None
        return sum(w * cast("float", v) for v, w in outcomes if w > 0.0) / total

    def own(self) -> tuple[TurnPick, ...]:
        """Turn 1's pick, then each later turn's after each thing it may show, following our own picks, turn by turn."""
        picks: list[TurnPick] = []
        frontier: list[After] = [()]
        while frontier:
            pick = self.found[frontier.pop(0)]
            picks.append(pick)
            if pick.pick is not None:
                frontier += [key for key in self.found if key and key[:-1] == pick.after and key[-1][0] == pick.pick]
        return tuple(picks)


# ── The lines ────────────────────────────────────────────────────────────────

def _history(scenario: Scenario, after: After) -> str:
    names = [f.name for f in scenario.friendly_responses]
    return " and ".join(
        _SHOWS.format(m=m, seen=seen.value, response=names[r]) for m, (r, seen) in enumerate(after, start=1)
    )


def _pick_line(scenario: Scenario, pick: TurnPick) -> str:
    if pick.pick is None and not permitted_responses(scenario):
        return NO_PICK_VETOED_FIRST
    if pick.pick is None:
        return NO_PICK_FIRST if pick.turn == 1 else NO_PICK.format(k=pick.turn, history=_history(scenario, pick.after))
    name = scenario.friendly_responses[pick.pick].name
    if pick.turn == 1:
        return PICK_FIRST.format(pick=name)
    return PICK_LATER.format(k=pick.turn, history=_history(scenario, pick.after), pick=name)


def _matrix_line(
    scenario: Scenario, strategy: SelectorStrategy, turns: int, picks: Sequence[TurnPick], matrix_pick: int | None,
) -> tuple[str, ...]:
    tree_pick = picks[0].pick
    if turns == 1 or tree_pick is None or matrix_pick is None or tree_pick == matrix_pick:
        return ()
    names = [f.name for f in scenario.friendly_responses]
    rule = strategy.value.replace("_", " ")
    return (MATRIX_DIFFERS.format(turns=turns, rule=rule, tree=names[tree_pick], matrix=names[matrix_pick]),)


def _stated(observed: Seen | None, posts: Sequence[Posterior]) -> Posterior | None:
    """The update for what the operator stated turn 1 showed; None when nothing was stated or no row gives it."""
    return next((p for p in posts if p.seen is observed), None)


def _update_lines(
    scenario: Scenario, strategy: SelectorStrategy, gives: Sequence[Seen], stated: Posterior | None,
) -> tuple[str, ...]:
    """Under expected value, the likelihood model, then the update for what the operator stated, or why nothing was
    updated; under minimax and minimin, what each turn lets us see and that nothing was updated (SPC-142)."""
    observed = scenario.observed
    if not gives:
        return () if observed is None else (OBSERVED_NO_LATER_TURN.format(seen=observed.value),)
    if strategy is not SelectorStrategy.EXPECTED_VALUE:
        rule = strategy.value.capitalize()
        unused = () if observed is None else (OBSERVED_UNUSED.format(seen=observed.value, rule=rule),)
        return (*seen_lines(scenario, gives), PROBABILITY_IGNORED.format(rule=rule), *unused)
    model = model_lines(scenario, gives)
    if observed is None:
        return (*model, NO_OBSERVATION)
    if stated is None:
        return (*model, OBSERVED_NOT_GIVEN.format(seen=observed.value))
    return (*model, OBSERVED.format(seen=observed.value), stated.line)


def _excluded(scenario: Scenario) -> tuple[str, ...]:
    """The line naming each response marked not permitted, which no turn picks; none when every one is permitted."""
    names = [r.name for r in scenario.friendly_responses if r.vetoed]
    return (EXCLUDED.format(names=", ".join(names)),) if names else ()


def select(
    scenario: Scenario, roots: Sequence[TreeNode], turns: int, strategy: SelectorStrategy, *, matrix_pick: int | None,
) -> TreeSelection:
    """*strategy*'s picks over the first *turns* turns of the tree under *roots*, beside the one-turn matrix's pick,
    *matrix_pick*, which a turn-1 pick that differs from it names; None when the matrix has no pick. Each turn is the
    span searched split equally."""
    turn_s = _searched_span_s(scenario) / scenario.turns
    selector = _Selector(scenario, strategy, turns, turn_s)
    selector.value([_Member(roots, (), 1.0)], 1, ())
    picks = selector.own()
    gives = likelihood(scenario, turn_s) if turns > 1 else ()
    posts = posteriors(scenario, gives) if gives and strategy is SelectorStrategy.EXPECTED_VALUE else ()
    stated = _stated(scenario.observed, posts)
    span = _SPAN_ONE if turns == 1 else _SPAN.format(turns=turns)
    partial = (PARTIAL.format(k=turns, turns=scenario.turns),) if turns < scenario.turns else ()
    recommendation = (
        RULES[strategy].format(span=span), *partial, *(_pick_line(scenario, p) for p in picks), *_excluded(scenario),
        *_matrix_line(scenario, strategy, turns, picks, matrix_pick), SCORE_LINE,
    )
    update = _update_lines(scenario, strategy, gives, stated)
    return TreeSelection(
        strategy, turns, picks, gives, posts, recommendation, update, FigureBasis(Basis.LOOKUP, SCORE_NOTE), stated,
    )


def follows_picks(scenario: Scenario, selection: TreeSelection, steps: Sequence[tuple[int, int]]) -> bool:
    """Whether every response on the sequence *steps*, (red's move, our response) per turn, is the rule's pick for
    its turn after what the turns before it showed: the plan the recommendation follows, whatever red does
    (SPC-142). False where the rule has no pick."""
    turn_s = _searched_span_s(scenario) / scenario.turns
    picks = {p.after: p.pick for p in selection.picks}
    after: After = ()
    for k, (_, response) in enumerate(steps, start=1):
        if picks.get(after) != response:
            return False
        after = (*after, (response, seen_after(scenario, [a for a, _ in steps[:k]], turn_s)))
    return True
