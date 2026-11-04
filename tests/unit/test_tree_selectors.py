"""Selectors over a game tree (SPC-141): recursive minimax, expected value and minimin.

Our pick in each turn may depend only on what we would have seen by then, through the likelihood model of
spectre.domain.turn_update: earlier red moves that show the same thing are one information set, and a pick must
serve every branch in it. Minimax takes the worst branch in it, minimin the best, and expected value weighs each by
the rows' P, which after turn 1 is the update. The leaves are each sequence's score, a lookup; lower is better.

The trees here are hand-built, so each value can be worked by hand; three turns are checked against every policy.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pytest

from spectre.domain import decision
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import AdversaryAction, Scenario, SelectorStrategy
from spectre.domain.provenance import Basis
from spectre.domain.tree_selectors import (
    MATRIX_DIFFERS,
    NO_OBSERVATION,
    NO_PICK,
    NO_PICK_FIRST,
    PARTIAL,
    PICK_FIRST,
    PICK_LATER,
    PROBABILITY_IGNORED,
    RULES,
    SCORE_LINE,
    SENTENCES,
    TreeSelection,
    TurnPick,
    select,
)
from spectre.domain.turn_update import Seen, seen_after
from tests.unit import _decision_tree_cases as cases
from tests.unit._i13 import i13_problems

_TURN_S = 3 * 3600.0
_MINIMAX, _EV, _MINIMIN = SelectorStrategy.MINIMAX, SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMIN

Path = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Node:
    action:     int
    response:   int
    path_score: float
    children:   tuple[Node, ...] = ()


def _tree(rows: int, responses: int, turns: int, score: Callable[[Path], float]) -> tuple[Node, ...]:
    def level(prefix: Path) -> tuple[Node, ...]:
        nodes = []
        for a, r in itertools.product(range(rows), range(responses)):
            path = (*prefix, (a, r))
            below = level(path) if len(path) < turns else ()
            nodes.append(Node(a, r, score(path), below))
        return tuple(nodes)

    return level(())


#: Each turn-2 leaf's own cost, by (red's turn-1 move, red's turn-2 move, our turn-2 response).
_SECOND = {
    (0, 0, 0): 0.2, (0, 0, 1): 0.3, (0, 1, 0): 0.9, (0, 1, 1): 0.5,
    (1, 0, 0): 0.1, (1, 0, 1): 0.4, (1, 1, 0): 0.3, (1, 1, 1): 0.6,
}


def _two_turn_score(path: Path) -> float:
    """Turn 1 costs 0 for Hold and 0.1 for Avoid; turn 2 adds _SECOND."""
    (a1, r1), *rest = path
    first = 0.1 * r1
    if not rest:
        return first
    ((a2, r2),) = rest
    return first + _SECOND[(a1, a2, r2)]


def _scenario(*, read: bool = True, p: tuple[float, float] = (0.25, 0.75), turns: int = 2) -> Scenario:
    """Hold course (P p[0]) and Evasive burning 1 h in (P p[1]), against Hold and Avoid; with custody read, held."""
    red = cases.bound("red")
    if read:
        red = dataclasses.replace(red, custody=CustodyStatus(Custody.HELD, "Custody held."))
    rows: list[AdversaryAction] = [
        dataclasses.replace(cases.still(), probability=p[0]),
        dataclasses.replace(cases.evasive(n=50, offset_h=1.0), probability=p[1]),
    ]
    return cases.scenario(
        rows, [cases.hold(), cases.avoid(20.0)], turns=turns, horizon_h=6.0,
        bind=decision.ScenarioBinding(red=red, blue=cases.bound("blue")),
    )


def _pick(selection: TreeSelection, after: tuple[tuple[int, Seen], ...]) -> TurnPick:
    (found,) = [p for p in selection.picks if p.after == after]
    return found


class TestRecursiveMinimax:
    def test_each_turn_two_pick_serves_the_branch_we_can_see(self) -> None:
        """33: custody held, so turn 1 shows which row red took. After no burn the worst is 0.9 holding and 0.5
        avoiding, so Avoid; after a burn 0.3 and 0.6, so Hold. Turn 1 then weighs 0.5 holding against 0.6."""
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)
        first = _pick(selection, ())
        assert first.turn == 1
        assert first.pick == 0
        assert first.values == pytest.approx((0.5, 0.6))
        quiet = _pick(selection, ((0, Seen.NO_BURN),))
        assert (quiet.turn, quiet.pick) == (2, 1)
        assert quiet.values == pytest.approx((0.9, 0.5))
        burnt = _pick(selection, ((0, Seen.BURN),))
        assert burnt.pick == 0
        assert burnt.values == pytest.approx((0.3, 0.6))
        assert len(selection.picks) == 3
        assert selection.posteriors == ()
        assert selection.likelihood == (Seen.NO_BURN, Seen.BURN)

    def test_a_pick_hedges_across_branches_it_cannot_tell_apart(self) -> None:
        """34: custody not read, so turn 1 shows nothing and turn 2's pick must serve both turn-1 rows: the worst
        is 0.9 holding and 0.6 avoiding, so Avoid, though Hold is better on the branch after a burn."""
        selection = select(
            _scenario(read=False), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0,
        )
        blind = _pick(selection, ((0, Seen.NOTHING),))
        assert blind.pick == 1
        assert blind.values == pytest.approx((0.9, 0.6))
        assert _pick(selection, ()).values == pytest.approx((0.6, 0.7))
        assert selection.likelihood == (Seen.NOTHING, Seen.NOTHING)


class TestExpectedValueWithTheUpdate:
    def test_each_branch_is_weighed_by_the_update(self) -> None:
        """35: P 0.25 and 0.75. After no burn only Hold course's branch remains: 0.725 holding, 0.45 avoiding;
        after a burn only Evasive's: 0.25 and 0.55. Turn 1: 0.25 x 0.45 + 0.75 x 0.25 = 0.3 holding, 0.4 avoiding."""
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        assert _pick(selection, ((0, Seen.NO_BURN),)).values == pytest.approx((0.725, 0.45))
        assert _pick(selection, ((0, Seen.BURN),)).values == pytest.approx((0.25, 0.55))
        first = _pick(selection, ())
        assert first.values == pytest.approx((0.3, 0.4))
        assert first.pick == 0
        burn, quiet = selection.posteriors
        assert (burn.seen, burn.shares) == (Seen.BURN, (None, 1.0))
        assert (quiet.seen, quiet.shares) == (Seen.NO_BURN, (1.0, None))
        # With no observation stated, neither update is shown (SPC-142): only the one for what was stated.
        assert burn.line not in selection.lines
        assert quiet.line not in selection.lines

    def test_seeing_nothing_keeps_the_prior_across_both_branches(self) -> None:
        """35: custody not read: 0.25 x 0.725 + 0.75 x 0.25 holding, 0.25 x 0.45 + 0.75 x 0.55 avoiding."""
        selection = select(
            _scenario(read=False), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0,
        )
        blind = _pick(selection, ((0, Seen.NOTHING),))
        assert blind.values == pytest.approx((0.36875, 0.525))
        assert blind.pick == 0
        (only,) = selection.posteriors
        assert only.shares == pytest.approx((0.25, 0.75))

    def test_a_branch_with_no_weight_has_no_pick_and_says_so(self) -> None:
        """36: Evasive at P 0, so after a burn nothing weighs: no pick there, and turn 1 weighs only Hold course,
        whose turn 2 holds against Hold course for 0.2: 0.2 holding in turn 1, 0.3 avoiding."""
        scenario = _scenario(p=(0.5, 0.0))
        selection = select(scenario, _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        burnt = _pick(selection, ((0, Seen.BURN),))
        assert burnt.pick is None
        assert burnt.values == (None, None)
        assert _pick(selection, ()).values == pytest.approx((0.2, 0.3))
        line = NO_PICK.format(k=2, history="turn 1 shows a burn after Hold")
        assert line in selection.lines

    def test_with_every_p_at_0_turn_one_has_no_pick(self) -> None:
        """36."""
        selection = select(
            _scenario(p=(0.0, 0.0)), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0,
        )
        assert selection.picks == (TurnPick(1, (), None, (None, None)),)
        assert NO_PICK_FIRST in selection.lines


class TestMinimin:
    def test_the_best_branch_decides(self) -> None:
        """37: after no burn 0.2 holding and 0.3 avoiding; after a burn 0.1 and 0.4; turn 1 0.1 and 0.2."""
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMIN, matrix_pick=0)
        assert _pick(selection, ((0, Seen.NO_BURN),)).values == pytest.approx((0.2, 0.3))
        assert _pick(selection, ((0, Seen.BURN),)).values == pytest.approx((0.1, 0.4))
        assert _pick(selection, ()).values == pytest.approx((0.1, 0.2))
        assert PROBABILITY_IGNORED.format(rule="Minimin") in selection.lines


def _policies(scenario: Scenario) -> list[dict[tuple[tuple[int, Seen], ...], int]]:
    """Every policy for three turns of two responses: a response for turn 1, for each thing turn 1 can show, and
    for each thing turns 1 and 2 can show together, given what red can do."""
    shows = sorted({seen_after(scenario, (a,), 7200.0) for a in range(2)})
    pairs = sorted({
        (seen_after(scenario, (a1,), 7200.0), seen_after(scenario, (a1, a2), 7200.0))
        for a1, a2 in itertools.product(range(2), repeat=2)
    })
    found = []
    for r1, second, third in itertools.product(range(2), itertools.product(range(2), repeat=len(shows)),
                                                itertools.product(range(2), repeat=len(pairs))):
        policy = {(): r1}
        r2 = dict(zip(shows, second, strict=True))
        for o1 in shows:
            policy[((r1, o1),)] = r2[o1]
        for (o1, o2), r3 in zip(pairs, third, strict=True):
            policy[((r1, o1), (r2[o1], o2))] = r3
        found.append(policy)
    return found


def _outcomes(scenario: Scenario, policy: dict[tuple[tuple[int, Seen], ...], int], score: Callable[[Path], float]) -> list[tuple[float, float]]:
    """Each red path's leaf score under *policy*, with its weight: the product of the rows' P shares."""
    shares = [a.probability for a in scenario.adversary_actions]
    out = []
    for reds in itertools.product(range(2), repeat=3):
        after: tuple[tuple[int, Seen], ...] = ()
        path: list[tuple[int, int]] = []
        for k, a in enumerate(reds, start=1):
            r = policy[after]
            path.append((a, r))
            after = (*after, (r, seen_after(scenario, reds[:k], 7200.0)))
        out.append((score(tuple(path)), float(np.prod([shares[a] for a in reds]))))
    return out


class TestThreeTurnsAgainstEveryPolicy:
    @pytest.mark.parametrize("read", [True, False])
    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_the_recursion_finds_the_best_policy(self, seed: int, read: bool) -> None:
        """38: random leaf scores over three 2 h turns; minimax's root value is the least worst case over every
        policy that picks by what it has seen, and expected value's the least weighted mean; following each
        rule's own picks earns that value."""
        rng = np.random.default_rng(seed)
        table = {path: float(rng.uniform()) for path in itertools.product(itertools.product(range(2), range(2)), repeat=3)}

        def score(path: Path) -> float:
            return table[path] if len(path) == 3 else 0.0

        scenario = _scenario(read=read, p=(0.4, 0.6), turns=3)
        roots = _tree(2, 2, 3, score)
        policies = _policies(scenario)
        worst = [max(s for s, _ in _outcomes(scenario, p, score)) for p in policies]
        mean = [sum(s * w for s, w in _outcomes(scenario, p, score)) for p in policies]
        for strategy, values in ((_MINIMAX, worst), (_EV, mean)):
            selection = select(scenario, roots, 3, strategy, matrix_pick=0)
            first = _pick(selection, ())
            assert first.pick is not None
            assert first.values[first.pick] == pytest.approx(min(values))
            own = {p.after: p.pick for p in selection.picks}
            assert own in policies
            assert values[policies.index(own)] == pytest.approx(min(values))


class TestATreeBuiltOnlyInPart:
    def test_one_turn_built_picks_over_turn_one_alone(self) -> None:
        """39: a 2-turn tree stopped after turn 1: the pick is the matrix rule on the roots' scores, worst 0.4
        holding and 0.5 avoiding, and says where it stops."""
        roots = _tree(2, 2, 1, lambda path: [[0.4, 0.2], [0.1, 0.5]][path[0][0]][path[0][1]])
        selection = select(_scenario(), roots, 1, _MINIMAX, matrix_pick=0)
        assert selection.picks == (TurnPick(1, (), 0, pytest.approx((0.4, 0.5))),)
        assert PARTIAL.format(k=1, turns=2) in selection.lines
        assert selection.likelihood == ()
        assert selection.posteriors == ()
        assert not any("likelihood model" in line for line in selection.lines)


class TestTiesAndTheMatrix:
    def test_a_tie_goes_to_the_first_response(self) -> None:
        """40."""
        selection = select(_scenario(), _tree(2, 2, 1, lambda _: 0.3), 1, _MINIMAX, matrix_pick=0)
        assert selection.picks[0].pick == 0

    def test_a_turn_one_pick_that_differs_from_the_matrix_says_so(self) -> None:
        """40: the tree picks Hold for turn 1 where the one-turn matrix picked Avoid."""
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=1)
        assert MATRIX_DIFFERS.format(rule="minimax", turns=2, tree="Hold", matrix="Avoid") in selection.lines
        same = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)
        assert not any(line.startswith("Over the 2 turns") for line in same.lines)


class TestTheLines:
    def test_the_lines_in_order(self) -> None:
        """41: the rule, each pick, the scores' basis, then the likelihood model and the update, which with no
        observation stated says nothing was updated (SPC-142)."""
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _EV, matrix_pick=0)
        rule, first, burnt, quiet, basis, model, independent, said = selection.lines
        assert rule == RULES[_EV].format(span="the 2 turns")
        assert first == PICK_FIRST.format(pick="Hold")
        assert burnt == PICK_LATER.format(k=2, history="turn 1 shows a burn after Hold", pick="Hold")
        assert quiet == PICK_LATER.format(k=2, history="turn 1 shows no burn after Hold", pick="Avoid")
        assert basis == SCORE_LINE
        assert "likelihood model" in model
        assert "nothing sourced" in independent
        assert said == NO_OBSERVATION
        assert selection.basis.kind is Basis.LOOKUP

    @pytest.mark.parametrize("sentence", SENTENCES)
    def test_each_sentence_passes_the_house_checks(self, sentence: str) -> None:
        """41."""
        assert i13_problems(sentence) == []
        for bad in ("\u2014", "\u2013", "--", "%"):
            assert bad not in sentence

    def test_minimax_shows_no_probability(self) -> None:
        """41: minimax reads no P, so no update is shown, only what each turn lets us see."""
        selection = select(_scenario(), _tree(2, 2, 2, _two_turn_score), 2, _MINIMAX, matrix_pick=0)
        assert selection.posteriors == ()
        assert PROBABILITY_IGNORED.format(rule="Minimax") in selection.lines
        assert not any("of the weight" in line for line in selection.lines)
