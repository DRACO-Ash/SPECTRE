"""How far each weight can move before the recommendation changes (SPC-205, evaluation finding F-16).

The default weights are uncited direct ratings, and no weight stability was shown, though in the bound scenario of
probe P-16 moving one weight by 0.089 (our delta-V, 0.20 to 0.111) or 0.082 (reversibility) flipped the pick under
minimax and expected value. For each recommendation the engine now finds, for each of the five weights, the smallest
change of that weight, the other four scaled in proportion to keep the sum 1 as the panel's normalisation does, that
changes the pick, in each direction, and what it changes to; or that no change within 0 to 1 does.

It is exact, not sampled: for fixed cell figures every composite score is linear in the moved weight along that
path, so the pick can change only where two responses' lines cross (expected value) or where the row-wise maxima or
minima of two responses meet (minimax and minimin). Every such point is found, and the pick is read at each and
between each, ties at a point resolved as find_robust_response resolves them: the first permitted response wins.

The matrices below are worked by hand. Each cell's figures give a score term of exactly 0 or 1 for closest approach
and our delta-V (a miss beyond 50,000 km or inside the keep-out distance; no burn, or 1,000 m/s), custody lost for
the whole horizon or held, and each response's reversibility and time to execute give its own column terms. Every
weight is a multiple of 1/8, so the scores at the panel's weights are exact. The brute-force scan that checks the
exact search is done here, in the test only.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime
from fractions import Fraction
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain import decision
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from spectre.domain.weight_stability import (
    STABILITY_BASIS,
    TREE_NOT_COVERED,
    WEIGHTS,
    Change,
    weight_stability,
)
from tests.unit._i13 import i13_problems

_EPOCH = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
_MINIMAX, _MINIMIN, _EV = SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN, SelectorStrategy.EXPECTED_VALUE
_H = 8.0
#: The panel's weights, scaled to sum to 1: custody, closest approach, our delta-V, time to execute, reversibility.
_WEIGHTS = {"w_custody": 0.25, "w_closest_approach": 0.125, "w_dv_cost": 0.125, "w_time_to_exec": 0.125,
            "w_reversibility": 0.375}
_FAR, _NEAR = 1.0e6, 1.0          # closest approach term 0 and 1 at the default keep-out distance, 10 km
_LOST = decision._Figures(False, _H, _FAR, 0.0)             # custody term 1, nothing else
_HELD = decision._Figures(True, 0.0, _FAR, 0.0)             # every cell term 0
_CLOSE = decision._Figures(True, 0.0, _NEAR, 0.0)           # closest approach term 1
_BURNT = decision._Figures(True, 0.0, _FAR, 1.0)            # our delta-V term 1: 1,000 m/s


def _response(rid: str, reversibility: float, *, vetoed: bool = False, hours: float = 0.0) -> FriendlyResponse:
    reason = "Rules of engagement" if vetoed else ""
    return FriendlyResponse(rid, f"Resp {rid}", ActionType.NO_ACTION, 0.0, reversibility, hours, vetoed=vetoed,
                            veto_reason=reason)


#: Each response's reversibility and its cells, row R1 then row R2, at P 0.5 each.
#: X: reversibility 1 (term 0); custody lost in R1 (term 1), a close approach in R2 (term 1).
#: Y: reversibility 0.5 (term 0.5); nothing in R1, our delta-V's full term in R2.
_X = ("X", 1.0, (_LOST, _CLOSE))
_Y = ("Y", 0.5, (_HELD, _BURNT))


def _result(columns: tuple[tuple[Any, ...], ...], rule: SelectorStrategy, *,
            vetoed: frozenset[str] = frozenset(), **weights: float) -> ScenarioResult:
    """A real result for the hand-built matrix *columns*, every cell's figures and score set to them. Each column is
    a response's id, reversibility and cells, row R1 then R2, and, when given, its time to execute in hours."""
    scenario = Scenario(
        name="Hand-built", epoch_utc=_EPOCH, horizon_hours=_H, **{**_WEIGHTS, **weights},
        adversary_actions=[AdversaryAction("R1", "Approach", ActionType.MANOEUVRE, 0.5, 0.7),
                           AdversaryAction("R2", "Hold course", ActionType.NO_ACTION, 0.5, 0.7)],
        friendly_responses=[_response(c[0], c[1], vetoed=c[0] in vetoed, hours=c[3] if len(c) > 3 else 0.0)
                            for c in columns],
    )
    base = evaluate_scenario(scenario, rule)
    s = base.scenario
    matrix = [
        [dataclasses.replace(cell, composite_score=round(decision._score(s, f, column[2][i]), 6),
                             score_figures=column[2][i])
         for cell, f, column in zip(row, s.friendly_responses, columns, strict=True)]
        for i, row in enumerate(base.outcome_matrix)
    ]
    return dataclasses.replace(base, outcome_matrix=matrix,
                               robust_best_response=find_robust_response(s, matrix, rule))


def _move(result: ScenarioResult, rule: SelectorStrategy, name: str) -> Any:
    return next(m for m in weight_stability(result, rule).moves if m.name == name)


def _at(change: Change | None) -> tuple[float, str, bool] | None:
    return None if change is None else (change.weight_at, change.pick.id, change.reached)


# ── Hand-computed breakpoints, one rule at a time ────────────────────────────

class TestHandComputedBreakpoints:
    def test_the_base_picks_are_x_under_every_rule(self) -> None:
        """Minimax: X's worst 0.25 against Y's 0.3125. Minimin: X's best 0.125 against Y's 0.1875. Expected value:
        X 0.1875 against Y 0.25."""
        for rule in (_MINIMAX, _MINIMIN, _EV):
            assert weight_stability(_result((_X, _Y), rule), rule).pick.id == "X"

    def test_minimax_custody(self) -> None:
        """Custody's weight at v, the rest scaled by (1 - v) / 0.75. X's worst is max(v, (1 - v) / 6); Y's worst is
        R2's (0.1875 + 0.125) (1 - v) / 0.75 = 5 (1 - v) / 12. They meet at v = 5/17, above 0.25, where X still wins
        the tie as the first response, so the pick is Y only past it. Lowered to 0, X's worst is 1/6 against 5/12."""
        move = _move(_result((_X, _Y), _MINIMAX), _MINIMAX, "w_custody")
        assert move.down is None
        assert move.up is not None
        assert move.up.weight_at == pytest.approx(5 / 17, abs=1e-12)
        assert move.up.by == pytest.approx(5 / 17 - 0.25, abs=1e-12)
        assert (move.up.pick.id, move.up.reached) == ("Y", False)

    def test_expected_value_custody(self) -> None:
        """X's mean is v / 2 + (1 - v) / 12 and Y's (1 - v) / 3: they meet at v = 1/3, a change of 1/12 up."""
        move = _move(_result((_X, _Y), _EV), _EV, "w_custody")
        assert move.down is None
        assert move.up is not None
        assert move.up.weight_at == pytest.approx(1 / 3, abs=1e-12)
        assert (move.up.pick.id, move.up.reached) == ("Y", False)

    def test_minimin_reversibility(self) -> None:
        """Reversibility's weight at v, the rest scaled by (1 - v) / 0.625. X's best is R2's 0.125 (1 - v) / 0.625
        = (1 - v) / 5 and Y's is R1's v / 2: they meet at v = 2/7, below 0.375, so lowering it past 2/7 picks Y.
        Raised to 1, X's best falls to 0 and Y's rises: X holds."""
        move = _move(_result((_X, _Y), _MINIMIN), _MINIMIN, "w_reversibility")
        assert move.up is None
        assert move.down is not None
        assert move.down.weight_at == pytest.approx(2 / 7, abs=1e-12)
        assert move.down.by == pytest.approx(0.375 - 2 / 7, abs=1e-12)
        assert (move.down.pick.id, move.down.reached) == ("Y", False)

    def test_a_weight_that_cannot_change_the_pick(self) -> None:
        """Under minimin, X's best is min(v, (1 - v) / 6) against Y's (1 - v) / 4 as custody's weight runs from 0
        to 1: X's is always less, so no change of custody's weight within 0 to 1 changes the pick."""
        move = _move(_result((_X, _Y), _MINIMIN), _MINIMIN, "w_custody")
        assert (move.down, move.up) == (None, None)
        assert move.base == 0.25

    def test_the_overall_smallest_is_the_least_change_over_every_weight_and_direction(self) -> None:
        stability = weight_stability(_result((_X, _Y), _MINIMAX), _MINIMAX)
        everything = [(c.by, m.name) for m in stability.moves for c in (m.down, m.up) if c is not None]
        move, change = stability.smallest
        assert (change.by, move.name) == min(everything)


#: Mirror responses for ties that the engine's rounding keeps: X loses custody in R1, Y comes close in R2. With
#: custody's weight lowered to v, the rest scaled by (1 - v) / 0.75, X's R1 scores v and Y's R2 (1 - v) / 6: they meet
#: at v = 1/7, where every other cell is 0, so both rows' rounded scores are the same two numbers, swapped, and the
#: two responses tie exactly under minimax and expected value. (Under minimin each has a 0 and they always tie: the
#: minimin tie is tested on X and Y below.)
_XM = ("X", 1.0, (_LOST, _HELD))
_YM = ("Y", 1.0, (_HELD, _CLOSE))


class TestTiesAtABreakpoint:
    """At the point where two responses score alike the pick is find_robust_response's: the first permitted one."""

    @pytest.mark.parametrize("rule", [_MINIMAX, _EV])
    def test_the_challenger_listed_first_takes_the_pick_at_the_point_itself(self, rule: SelectorStrategy) -> None:
        result = _result((_XM, _YM), rule)
        assert result.robust_best_response.id == "Y"
        move = _move(result, rule, "w_custody")
        assert move.down is not None
        assert move.down.weight_at == pytest.approx(1 / 7, abs=1e-12)
        assert (move.down.pick.id, move.down.reached) == ("X", True)
        assert _picks(result, "w_custody", move.down.weight_at)[rule] == "X"

    @pytest.mark.parametrize("rule", [_MINIMAX, _EV])
    def test_the_incumbent_listed_first_keeps_it_there(self, rule: SelectorStrategy) -> None:
        result = _result((_YM, _XM), rule)
        move = _move(result, rule, "w_custody")
        assert move.down is not None
        assert move.down.weight_at == pytest.approx(1 / 7, abs=1e-12)
        assert (move.down.pick.id, move.down.reached) == ("X", False)
        assert _picks(result, "w_custody", move.down.weight_at)[rule] == "Y"

    def test_where_the_engines_rounding_parts_two_lines_that_meet_the_rounding_decides(self) -> None:
        """X and Y's expected-value lines meet at custody's weight 1/3, but there X's rounded cells, 0.333333 and
        0.111111, average 0.222222, under Y's 0.166667 and 0.277778, which average 0.2222225: the engine keeps X at
        the point itself, wherever Y is listed, so the change is only past it."""
        for order in ((_X, _Y), (_Y, _X)):
            result = _result(order, _EV)
            change = _move(result, _EV, "w_custody").up
            assert change.weight_at == pytest.approx(1 / 3, abs=1e-12)
            assert (change.pick.id, change.reached) == ("Y", False)
            assert _picks(result, "w_custody", change.weight_at)[_EV] == "X"

    @pytest.mark.parametrize("order", [(_X, _Y), (_Y, _X)])
    def test_the_pick_reported_at_the_point_is_find_robust_responses_there(self, order: Any) -> None:
        result = _result(order, _EV)
        change = _move(result, _EV, "w_custody").up
        assert _picks(result, "w_custody", change.weight_at)[_EV] == (change.pick.id if change.reached else "X")


    @pytest.mark.parametrize(("rule", "name", "at", "way"), [
        (_MINIMAX, "w_custody", 5 / 17, "up"), (_MINIMIN, "w_reversibility", 2 / 7, "down"),
    ])
    def test_under_minimax_and_minimin_the_first_listed_wins_the_tie_at_the_point(
        self, rule: SelectorStrategy, name: str, at: float, way: str,
    ) -> None:
        """Where the row-wise maxima (minimax) or minima (minimin) meet, the response listed first takes the pick at
        the point itself, as find_robust_response's min over the permitted responses does."""
        first_y = getattr(_move(_result((_Y, _X), rule), rule, name), way)
        first_x = getattr(_move(_result((_X, _Y), rule), rule, name), way)
        assert first_y.weight_at == pytest.approx(at, abs=1e-12) == first_x.weight_at
        assert (first_y.pick.id, first_y.reached) == ("Y", True)
        assert (first_x.pick.id, first_x.reached) == ("Y", False)


class TestVetoes:
    def test_a_vetoed_response_is_never_a_pick_it_reports(self) -> None:
        """Z would win as soon as reversibility's weight falls a little, but it is marked not permitted."""
        z = ("Z", 0.0, (_HELD, _HELD))
        result = _result((_X, _Y, z), _MINIMAX, vetoed=frozenset({"Z"}))
        stability = weight_stability(result, _MINIMAX)
        assert all(c.pick.id != "Z" for m in stability.moves for c in (m.down, m.up) if c is not None)
        unvetoed = weight_stability(_result((_X, _Y, z), _MINIMAX), _MINIMAX)
        assert next(m for m in unvetoed.moves if m.name == "w_reversibility").down.pick.id == "Z"
        assert next(m for m in stability.moves if m.name == "w_reversibility").down.pick.id == "Y"

    def test_with_one_response_permitted_nothing_can_change_the_pick(self) -> None:
        stability = weight_stability(_result((_X, _Y), _MINIMAX, vetoed=frozenset({"Y"})), _MINIMAX)
        assert all((m.down, m.up) == (None, None) for m in stability.moves)
        assert stability.smallest is None

    def test_with_every_response_vetoed_there_is_no_pick_and_no_stability(self) -> None:
        stability = weight_stability(_result((_X, _Y), _MINIMAX, vetoed=frozenset({"X", "Y"})), _MINIMAX)
        assert stability.pick is None
        assert stability.moves == ()
        assert stability.line == "There is no pick to hold, so no weight stability is shown."


class TestEdges:
    def test_a_weight_at_1_carries_the_whole_weight_and_cannot_move_in_proportion(self) -> None:
        result = _result((_X, _Y), _MINIMAX, w_custody=1.0, w_closest_approach=0.0, w_dv_cost=0.0,
                         w_time_to_exec=0.0, w_reversibility=0.0)
        stability = weight_stability(result, _MINIMAX)
        custody = stability.moves[0]
        assert custody.whole and (custody.down, custody.up) == (None, None)
        assert stability.weight_lines[0] == (
            "Custody 1.000: it carries the whole weight, so no other weight can take up a move of it in proportion."
        )
        # Every other weight starts at 0: it cannot be lowered, and raising it can change the pick.
        assert all(m.down is None for m in stability.moves[1:])

    def test_weights_that_do_not_sum_to_1_are_read_as_the_panel_scales_them(self) -> None:
        """Scores scale with the weights' sum, so the picks are those of the weights over their sum."""
        doubled = {k: min(1.0, 2 * v) for k, v in _WEIGHTS.items() if k != "w_reversibility"}
        result = _result((_X, _Y), _EV, **doubled, w_reversibility=0.75)
        assert [m.base for m in weight_stability(result, _EV).moves] == list(_WEIGHTS.values())
        assert _move(result, _EV, "w_custody").up.weight_at == pytest.approx(1 / 3, abs=1e-12)

    def test_a_cell_built_by_hand_is_scored_from_the_figures_it_shows(self) -> None:
        """A cell the engine did not build keeps no unrounded figures, so its terms come from the figures shown."""
        result = _result((_X, _Y), _MINIMAX)
        bare = [[dataclasses.replace(
            cell, score_figures=None, custody_maintained=cell.score_figures.custody_maintained,
            custody_gap_hours=cell.score_figures.custody_gap_hours,
            closest_approach_km=cell.score_figures.closest_approach_km,
            delta_v_cost_km_s=cell.score_figures.delta_v_km_s,
        ) for cell in row] for row in result.outcome_matrix]
        cell = bare[0][0]
        assert decision.cell_figures(cell) == decision._Figures(
            cell.custody_maintained, cell.custody_gap_hours, cell.closest_approach_km, cell.delta_v_cost_km_s, 0.0)
        assert weight_stability(dataclasses.replace(result, outcome_matrix=bare), _MINIMAX) == weight_stability(
            result, _MINIMAX)

    def test_every_weight_at_0_gives_no_stability_and_says_why(self) -> None:
        zero = dict.fromkeys(_WEIGHTS, 0.0)
        stability = weight_stability(_result((_X, _Y), _MINIMAX, **zero), _MINIMAX)
        assert stability.moves == ()
        assert stability.line == "Every weight is 0, so every score is 0 and no weight stability is shown."

    def test_two_responses_alike_at_every_weight_never_change_places(self) -> None:
        """Y's cells and column terms are X's: every score alike at every weight, so X, listed first, holds."""
        y_alike = ("Y", 1.0, (_LOST, _CLOSE))
        stability = weight_stability(_result((_X, y_alike), _MINIMAX), _MINIMAX)
        assert stability.pick.id == "X"
        assert stability.smallest is None

    def test_a_weight_just_under_1_is_moved_in_proportion(self) -> None:
        """At 0.999 the other four still hold 0.001 between them, so custody's weight moves as any other does."""
        rest = 0.001
        result = _result((_X, _Y), _MINIMAX, w_custody=1.0 - rest, w_closest_approach=rest / 6, w_dv_cost=rest / 6,
                         w_time_to_exec=rest / 6, w_reversibility=rest / 2)
        custody = weight_stability(result, _MINIMAX).moves[0]
        assert not custody.whole
        assert custody.down is not None and custody.down.weight_at == pytest.approx(5 / 17, abs=1e-9)
        assert custody.line.startswith("Custody 0.999: lowered, ")

    def test_a_tie_at_the_panels_weights_that_only_lowering_breaks_says_lowered(self) -> None:
        """The tie below with Y listed first, so Y holds it: only lowering custody's weight favours X."""
        result = _result((_Y, _X), _EV, w_custody=0.375, w_closest_approach=0.125, w_dv_cost=0.125,
                         w_time_to_exec=0.0, w_reversibility=0.375)
        stability = weight_stability(result, _EV)
        assert stability.pick.id == "Y"
        custody = stability.moves[0]
        assert custody.up is None
        assert (custody.down.by, custody.down.pick.id, custody.down.lowered) == (0.0, "X", True)
        assert (_picks(result, "w_custody", 0.374)[_EV], _picks(result, "w_custody", 0.376)[_EV]) == ("X", "Y")
        assert stability.line == ("The recommendation holds only at these weights: custody's weight lowered by under "
                                  "0.001 from 0.375 makes it Resp X (X).")

    def test_a_change_only_where_every_response_scores_alike_says_the_first_listed_takes_it(self) -> None:
        """X scores 0 at every weight. Y scores 0 only with custody's weight at 1, where custody alone counts and
        neither loses it: every response alike there, and Y, listed first, takes the pick."""
        nothing = ("X", 1.0, (_HELD, _HELD))
        result = _result((_Y, nothing), _MINIMAX)
        stability = weight_stability(result, _MINIMAX)
        custody = stability.moves[0]
        assert (custody.up.weight_at, custody.up.pick.id, custody.up.reached, custody.up.alike) == (1.0, "Y", True,
                                                                                                     True)
        assert stability.weight_lines[0] == (
            "Custody 0.250: lowered, no value down to 0 changes it; raised, at 1.000, where every response scores "
            "alike, it makes it Resp Y (Y) as the first listed."
        )
        assert stability.line == (
            "The recommendation holds unless a weight moves by at least 0.750: custody's weight from 0.250 to 1.000, "
            "where every response scores alike, makes it Resp Y (Y) as the first listed."
        )
        for line in (stability.line, *stability.weight_lines):
            assert i13_problems(line) == [], line

    def test_a_tie_at_the_panels_weights_changes_with_any_move_that_favours_the_other(self) -> None:
        """Custody and reversibility at 0.375 each, closest approach and our delta-V at 0.125, time to execute 0:
        expected value gives X and Y 0.25 each, and X holds as the first. Any rise of custody's weight favours Y, so
        the line says the pick holds only at these weights."""
        result = _result((_X, _Y), _EV, w_custody=0.375, w_closest_approach=0.125, w_dv_cost=0.125,
                         w_time_to_exec=0.0, w_reversibility=0.375)
        stability = weight_stability(result, _EV)
        move, change = stability.smallest
        assert (move.name, change.by, change.pick.id, change.reached, change.lowered) == ("w_custody", 0.0, "Y",
                                                                                           False, False)
        assert stability.line == ("The recommendation holds only at these weights: custody's weight raised by under "
                                  "0.001 from 0.375 makes it Resp Y (Y).")


# ── The exact search against a brute-force fine scan, done here only ─────────

def _moved(base: dict[str, float], key: str, new: float) -> dict[str, float]:
    rest = sum(v for k, v in base.items() if k != key)
    return {k: (new if k == key else v * (1.0 - new) / rest) for k, v in base.items()}


def _picks(result: ScenarioResult, key: str, new: float) -> dict[SelectorStrategy, str | None]:
    """Each rule's pick with *key*'s weight at *new*, every score built again by the engine's own _score and rounded
    to 6 decimal places as the engine rounds it."""
    scenario = result.scenario
    base = {name: getattr(scenario, name) for name, _ in WEIGHTS}
    total = sum(base.values())
    weights = _moved({k: v / total for k, v in base.items()}, key, new)
    scoring = SimpleNamespace(**weights, horizon_hours=scenario.horizon_hours, keep_out_km=scenario.keep_out_km)
    cells = [[SimpleNamespace(composite_score=round(decision._score(scoring, f, c.score_figures), 6))  # type: ignore[arg-type]
              for f, c in zip(scenario.friendly_responses, row, strict=True)] for row in result.outcome_matrix]
    picks = {rule: find_robust_response(scenario, cells, rule) for rule in (_MINIMAX, _MINIMIN, _EV)}  # type: ignore[arg-type]
    return {rule: None if pick is None else pick.id for rule, pick in picks.items()}


_STEP = Fraction(1, 2000)


def _scan(result: ScenarioResult, key: str, base: float, sign: int) -> dict[SelectorStrategy, tuple[float, str | None]]:
    """For each rule, the first point on a grid of _STEP, walking from *base* by *sign*, at which its pick is not
    its pick at *base*; a rule whose pick never changes is not listed."""
    start = _picks(result, key, base)
    found: dict[SelectorStrategy, tuple[float, str | None]] = {}
    step = 1
    while len(found) < len(start) and 0.0 <= (v := base + sign * float(step * _STEP)) <= 1.0:
        for rule, pick in _picks(result, key, v).items():
            if rule not in found and pick != start[rule]:
                found[rule] = (float(step * _STEP), pick)
        step += 1
    return found


def _scenarios() -> dict[str, ScenarioResult]:
    from tests.unit.test_decision_understanding import _scenario as understanding

    probe_lookup = Scenario(
        name="P-16 lookup", epoch_utc=_EPOCH,
        adversary_actions=[
            AdversaryAction("A0", "approach", ActionType.MANOEUVRE, 0.6, 0.7),
            AdversaryAction("A1", "hold", ActionType.NO_ACTION, 0.3, 0.7),
            AdversaryAction("A2", "posture", ActionType.POSTURE_CHANGE, 0.1, 0.7),
        ],
        friendly_responses=[
            FriendlyResponse("F0", "do nothing", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
            FriendlyResponse("F1", "retask sensor", ActionType.SENSOR_RETASK, 0.2, 0.9, 2.0),
            FriendlyResponse("F2", "manoeuvre", ActionType.MANOEUVRE, 0.4, 0.5, 6.0),
            FriendlyResponse("F3", "posture", ActionType.POSTURE_CHANGE, 0.3, 0.8, 3.0),
        ],
    )
    return {
        "hand-built": _result((_X, _Y, ("Z", 0.25, (_CLOSE, _LOST))), _MINIMAX),
        "probe lookup": evaluate_scenario(probe_lookup),
        # 0.3 beside 0.5 leaves the engine's remainder row, 0.2 of no adversary action, which every rule reads.
        "with the remainder of P": evaluate_scenario(dataclasses.replace(
            understanding(probability=0.3), adversary_actions=understanding(probability=0.3).adversary_actions[:1])),
    }


@pytest.mark.parametrize("name", ["hand-built", "probe lookup", "with the remainder of P"])
def test_the_exact_search_matches_a_brute_force_fine_scan(name: str) -> None:
    """Each rule, each weight, each direction: the scan's first change lies within one grid step past the exact
    one, to the same response, and where the exact search finds none, neither does the scan."""
    result = _scenarios()[name]
    found = 0
    for move in weight_stability(result, _MINIMAX).moves:
        for sign in (-1, 1):
            scanned = _scan(result, move.name, move.base, sign)
            for rule in (_MINIMAX, _MINIMIN, _EV):
                stability = weight_stability(result, rule)
                this = next(m for m in stability.moves if m.name == move.name)
                change = this.down if sign < 0 else this.up
                if change is None:
                    assert rule not in scanned, (rule, move.name, sign, scanned)
                    continue
                found += 1
                assert rule in scanned, (rule, move.name, sign, change)
                at, pick = scanned[rule]
                assert change.by - 1e-9 <= at <= change.by + float(_STEP) + 1e-9, (rule, move.name, sign)
                assert pick == change.pick.id, (rule, move.name, sign)
    assert found


# ── Probe P-16's bound scenario, through the real engine ─────────────────────

def _old_scales(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test stand-in: the score scales of 0.24.2, which P-16 measured, in place of SPC-191's. Closest approach
    entered linearly over 0 to 50,000 km, and our delta-V linearly to a full penalty at 100 m/s."""
    monkeypatch.setattr(decision, "_norm_ca", lambda ca_km, _keep_out_km: 1.0 - min(ca_km / 50_000.0, 1.0))
    monkeypatch.setattr(decision, "_norm_dv", lambda dv_km_s: min(dv_km_s / 0.1, 1.0))


def _p16() -> Scenario:
    """P-16's computed scenario: the plane-change pair bound, every closest approach computed by SGP4."""
    from tests.unit.test_decision_sampled import _binding
    from tests.unit.test_decision_sampled import _scenario as bound_rows

    return bound_rows(binding=_binding(), horizon_hours=1.0)


def _p16_sampled() -> Scenario:
    """P-16's sampled scenario: the same pair bound, its manoeuvre row carrying an evasive hypothesis, sampled."""
    from tests.unit.test_decision_sampled import _bound

    return _bound()


class TestProbeP16:
    @pytest.mark.parametrize(("make", "rule", "dv", "rev"), [
        (_p16, _MINIMAX, "0.089", "0.082"), (_p16, _EV, "0.088", "0.081"),
        (_p16_sampled, _MINIMAX, "0.089", "0.082"), (_p16_sampled, _EV, "0.089", "0.082"),
    ], ids=["computed, minimax", "computed, expected value", "sampled, minimax", "sampled, expected value"])
    def test_under_the_scales_p16_measured_it_reproduces_p16(
        self, monkeypatch: pytest.MonkeyPatch, make: Any, rule: SelectorStrategy, dv: str, rev: str,
    ) -> None:
        """P-16: our delta-V's weight from 0.20 to 0.111 flips the pick from the sensor retask (F1) to the
        manoeuvre (F0); reversibility up 0.082 does the same, in its computed and its sampled scenario. P-16's figures
        are the first 0.001 step of its scan that flipped; the exact change lies within that step below it."""
        _old_scales(monkeypatch)
        result = evaluate_scenario(make(), rule)
        stability = weight_stability(result, rule)
        assert stability.pick.id == "F1"
        delta_v = next(m for m in stability.moves if m.name == "w_dv_cost")
        reversibility = next(m for m in stability.moves if m.name == "w_reversibility")
        assert delta_v.up is None and reversibility.down is None
        assert float(dv) - 0.001 < delta_v.down.by <= float(dv)
        assert float(rev) - 0.001 < reversibility.up.by <= float(rev)
        assert delta_v.down.pick.id == reversibility.up.pick.id == "F0"
        move, change = stability.smallest
        assert (move.name, change) == ("w_reversibility", reversibility.up)

    def test_under_the_scales_p16_measured_the_page_states_the_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _old_scales(monkeypatch)
        stability = weight_stability(evaluate_scenario(_p16(), _MINIMAX), _MINIMAX)
        lines = dict(zip([m.name for m in stability.moves], stability.weight_lines, strict=True))
        moves = {m.name: m for m in stability.moves}
        assert lines["w_dv_cost"].startswith("Our delta-V 0.200: lowered, at 0.111 it makes it manoeuvre (F0); ")
        assert lines["w_reversibility"].startswith("Reversibility 0.100: lowered, ")
        assert moves["w_reversibility"].up.weight_at == pytest.approx(0.181818, abs=1e-6)
        assert lines["w_reversibility"].endswith("raised, at 0.182 it makes it manoeuvre (F0).")
        assert stability.line == (
            "The recommendation holds unless a weight moves by at least 0.081: reversibility's weight from 0.100 to "
            "0.182 makes it manoeuvre (F0)."
        )

    def test_under_the_scales_built_since_spc_191_the_same_scenario_is_steadier(self) -> None:
        """SPC-191 put closest approach and our delta-V in orders of magnitude, so the same matrix now holds its pick
        until our delta-V's weight falls by 0.165 (minimax), where P-16 measured 0.089. The manoeuvre is
        listed first, so it takes the tie at the point itself."""
        stability = weight_stability(evaluate_scenario(_p16(), _MINIMAX), _MINIMAX)
        moves = {m.name: m for m in stability.moves}
        assert round(moves["w_dv_cost"].down.by, 3) == 0.165
        assert moves["w_dv_cost"].down.pick.id == "F0"
        move, change = stability.smallest
        assert move.name == "w_dv_cost"
        floor, outward = math.floor(change.by * 1000) / 1000, math.floor(change.weight_at * 1000) / 1000
        assert stability.line == (
            f"The recommendation holds unless a weight moves by at least {floor:.3f}: our delta-V's weight from "
            f"0.200 to {outward:.3f} makes it manoeuvre (F0)."
        )


class TestTheEnginesOwnRounding:
    """The engine rounds each composite score to 6 decimal places and picks on the rounded scores, so the search
    reads them as the engine does: a tie the rounding makes is the engine's tie, and only a move that breaks it the
    engine's way changes the pick."""

    def test_a_tie_the_rounding_makes_changes_only_the_way_the_engine_breaks_it(self) -> None:
        """X's custody term 0.2 scores 0.07 at custody's weight 0.35; Y's time to execute term 0.699997 scores
        0.0699997 at time's 0.1. Rounded, both are 0.07, and X, listed first, is the engine's pick. Lowering custody's
        weight lowers X's score: X holds all the way to 0. Raising it takes X above Y once the rounding parts them."""
        part = decision._Figures(False, 0.2 * _H, _FAR, 0.0)
        x = ("X", 1.0, (part, part))
        y = ("Y", 1.0, (_HELD, _HELD), 0.699997 * _H)
        result = _result((x, y), _MINIMAX, w_custody=0.35, w_closest_approach=0.25, w_dv_cost=0.2,
                         w_time_to_exec=0.1, w_reversibility=0.1)
        assert [c.composite_score for c in result.outcome_matrix[0]] == [0.07, 0.07]
        stability = weight_stability(result, _MINIMAX)
        assert stability.pick.id == "X"
        custody = stability.moves[0]
        assert custody.down is None
        assert all(_picks(result, "w_custody", v)[_MINIMAX] == "X" for v in (0.349, 0.34, 0.3, 0.2, 0.0))
        assert custody.up is not None and custody.up.pick.id == "Y" and custody.up.by < 0.001
        assert _picks(result, "w_custody", 0.351)[_MINIMAX] == "Y"
        assert stability.line == ("The recommendation holds only at these weights: custody's weight raised by under "
                                  "0.001 from 0.350 makes it Resp Y (Y).")


class TestTheWordsNeverOverstate:
    """Each change is shown rounded down, so the "at least" or "more than" it states is never above the exact change;
    each weight's value is shown rounded away from the panel's weight, so the pick there is the one the line names,
    which the search checks, giving a place more where a rounded value would pass a further change."""

    @pytest.mark.parametrize("name", ["hand-built", "probe lookup", "with the remainder of P"])
    def test_every_shown_change_is_at_most_the_exact_one_and_every_shown_value_gives_the_pick_named(
        self, name: str,
    ) -> None:
        result = _scenarios()[name]
        checked = 0
        for rule in (_MINIMAX, _MINIMIN, _EV):
            for move in weight_stability(result, rule).moves:
                for change in (move.down, move.up):
                    if change is None:
                        continue
                    checked += 1
                    # Never above the exact change, but for the float's own error where it falls on a step.
                    assert float(change.shown_by) <= change.by + 1e-12
                    assert change.by - float(change.shown_by) < 0.001
                    at = float(change.shown_at)
                    assert (at <= change.weight_at) if change.lowered else (at >= change.weight_at)
                    assert _picks(result, move.name, at)[rule] == change.pick.id, (rule, move.name, change)
        assert checked

    def test_p16s_bound_today_the_stated_bound_holds_through_a_whole_evaluation(self) -> None:
        """The evaluation's case: our delta-V's exact change is 0.15469 under expected value. The line says more than
        0.154, and a whole evaluation with the weight moved by 0.154 still picks the sensor retask (F1), while at the
        value the line names, 0.045, it picks the manoeuvre (F0)."""
        stability = weight_stability(evaluate_scenario(_p16(), _EV), _EV)
        move, change = stability.smallest
        assert move.name == "w_dv_cost" and change.by == pytest.approx(0.1546870, abs=1e-6)
        assert stability.line == ("The recommendation holds unless a weight moves by more than 0.154: our delta-V's "
                                  "weight from 0.200 past 0.045 makes it manoeuvre (F0).")
        held = _p16()
        weights = {name: getattr(held, name) for name, _ in WEIGHTS}
        for at, pick in ((0.200 - 0.154, "F1"), (0.045, "F0")):
            moved = dataclasses.replace(held, **_moved(weights, "w_dv_cost", at))
            assert evaluate_scenario(moved, _EV).robust_best_response.id == pick

    def test_where_rounding_would_pass_a_further_change_a_place_more_is_shown(self) -> None:
        """Raising reversibility's weight from 0.375: X's mean is 0.39968 v, Y's 0.2 less 0.00032 v and Z's 0.4 less
        0.4 v. X gives way to Y past 0.5, and Y to Z past 0.5004. Rounded up to 3 places, 0.501 would already give Z,
        so the value is shown to 4: past 0.5001, where the pick is Y."""
        x = ("X", 1.0 - 0.39968, (_HELD, _HELD))
        y = ("Y", 1.0 - 0.19968, (_LOST, _HELD))
        z = ("Z", 1.0, (_LOST, _LOST))
        result = _result((x, y, z), _EV)
        reversibility = _move(result, _EV, "w_reversibility")
        change = reversibility.up
        assert change is not None
        assert (change.pick.id, change.reached) == ("Y", False)
        assert change.weight_at == pytest.approx(0.5, abs=1e-12)
        assert (change.shown_at, change.shown_by) == ("0.5001", "0.125")
        assert _picks(result, "w_reversibility", 0.501)[_EV] == "Z"
        assert reversibility.line.endswith("raised, past 0.5001 it makes it Resp Y (Y).")


class TestTheLeastChangeShown:
    """A change under 0.001 is said to be under it, and the line then says the pick holds only at these weights."""

    @staticmethod
    def _near_the_crossing(gap: float) -> ScenarioResult:
        """Custody's weight *gap* below 1/3, where X and Y meet under expected value, the other weights in the
        panel's proportions: the meeting point does not move with custody's own weight."""
        base = 1.0 / 3.0 - gap
        rest = 1.0 - base
        return _result((_X, _Y), _EV, w_custody=base, w_closest_approach=rest / 6, w_dv_cost=rest / 6,
                       w_time_to_exec=rest / 6, w_reversibility=rest / 2)

    def test_a_change_of_0_0009_is_under_0_001(self) -> None:
        stability = weight_stability(self._near_the_crossing(0.0009), _EV)
        move, change = stability.smallest
        assert move.name == "w_custody" and change.by == pytest.approx(0.0009, abs=1e-12)
        assert stability.line == ("The recommendation holds only at these weights: custody's weight raised by under "
                                  "0.001 from 0.332 makes it Resp Y (Y).")

    def test_a_change_of_0_0011_is_more_than_0_001(self) -> None:
        stability = weight_stability(self._near_the_crossing(0.0011), _EV)
        move, change = stability.smallest
        assert move.name == "w_custody" and change.by == pytest.approx(0.0011, abs=1e-12)
        assert stability.line == ("The recommendation holds unless a weight moves by more than 0.001: custody's weight "
                                  "from 0.332 past 0.334 makes it Resp Y (Y).")


# ── The words ─────────────────────────────────────────────────────────────────

class TestTheWords:
    def test_the_line_names_the_overall_smallest_change_its_weight_and_what_it_makes_the_pick(self) -> None:
        """Raising closest approach's weight to v, the rest scaled by (1 - v) / 0.875, Y's R2 scores v and X's R1
        0.25 (1 - v) / 0.875: they meet at 2/9, a change of 0.0972, where the two score alike and X, listed first,
        takes the tie. Lowering custody's weight to 1/7, a change of 0.107, is further."""
        stability = weight_stability(_result((_XM, _YM), _EV), _EV)
        move, change = stability.smallest
        assert stability.pick.id == "Y"
        assert (move.name, change.reached) == ("w_closest_approach", True)
        assert change.weight_at == pytest.approx(2 / 9, abs=1e-12)
        assert stability.line == (
            "The recommendation holds unless a weight moves by at least 0.097: closest approach's weight from 0.125 "
            "to 0.223, where every response scores alike, makes it Resp X (X) as the first listed."
        )

    def test_a_change_only_past_the_point_says_more_than(self) -> None:
        line = weight_stability(_result((_X, _Y), _EV), _EV).line
        assert line == ("The recommendation holds unless a weight moves by more than 0.083: custody's weight from "
                        "0.250 past 0.334 makes it Resp Y (Y).")

    def test_no_change_within_0_to_1(self) -> None:
        stability = weight_stability(_result((_X, _Y), _MINIMAX, vetoed=frozenset({"Y"})), _MINIMAX)
        assert stability.line == ("The recommendation holds whatever one weight is set to, from 0 to 1, with the "
                                  "other four scaled in proportion to keep the sum 1.")

    def test_every_weight_is_listed_in_the_panels_order(self) -> None:
        stability = weight_stability(_result((_X, _Y), _MINIMIN), _MINIMIN)
        assert stability.weight_lines == (
            "Custody 0.250: lowered, no value down to 0 changes it; raised, no value up to 1 changes it.",
            stability.weight_lines[1],
            stability.weight_lines[2],
            stability.weight_lines[3],
            "Reversibility 0.375: lowered, past 0.285 it makes it Resp Y (Y); raised, no value up to 1 changes it.",
        )
        assert [line.split(" ")[0] for line in stability.weight_lines] == [
            "Custody", "Closest", "Our", "Time", "Reversibility"]

    def test_a_weight_at_0_cannot_be_lowered(self) -> None:
        result = _result((_X, _Y), _MINIMAX, w_custody=0.0, w_closest_approach=0.25, w_dv_cost=0.25,
                         w_time_to_exec=0.125, w_reversibility=0.375)
        assert weight_stability(result, _MINIMAX).weight_lines[0].startswith("Custody 0.000: lowered, it is at 0 "
                                                                              "already; raised, ")

    def test_a_subject_other_than_the_recommendation(self) -> None:
        stability = weight_stability(_result((_X, _Y), _EV), _EV, subject="Expected value's pick, the rule chosen,")
        assert stability.line.startswith("Expected value's pick, the rule chosen, holds unless a weight moves by ")

    def test_the_basis_and_the_trees_line(self) -> None:
        assert "linear in the moved weight" in STABILITY_BASIS
        assert "not sampled" in STABILITY_BASIS and "not permitted" in STABILITY_BASIS
        assert "lookup" in STABILITY_BASIS
        assert TREE_NOT_COVERED == ("The game tree's picks are not covered: this is the weight stability of the "
                                    "one-turn matrix's pick.")

    def test_no_line_breaks_i13_or_uses_a_long_dash(self) -> None:
        stability = weight_stability(_result((_X, _Y), _MINIMAX), _MINIMAX)
        for line in (stability.line, *stability.weight_lines, STABILITY_BASIS, TREE_NOT_COVERED):
            assert i13_problems(line) == [], line
            assert "—" not in line and "--" not in line
