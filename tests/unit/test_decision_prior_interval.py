"""The interval on a NOTSO-derived P, carried into the expected-value pick (SPC-132).

Expected value weighs each adversary row by its P, so a P read from NOTSO
history moves the pick wherever it falls in its interval, not only at its
centre. For each row holding an applied suggestion, the result varies that
row's P across its interval, holding the other rows at theirs, and says
whether the recommended response changes anywhere in it, naming the P at
which it would. With two or more such rows it also moves them together across
their intervals and says whether the pick holds at every combination, naming
one at which it changes if it does. Minimax and minimin read no probability, so under either the
result says so and shows no interval it ignores. No test reads the wall clock.

Since SPC-203 the rows' P sum to at most 1 and the engine weighs the rest as a remainder row, which takes up any move
of a row's P. Each result here gives that row the same score under every response, _REMAINDER_SCORE, so it adds the
same to every response's expected score and moves no crossing and no pick: every P and pick pinned below is the one
derived before the remainder, re-derived by that argument, and each line now names what takes up the move.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from spectre.astro.notso import NOTSOType
from spectre.domain.decision import (
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    OutcomeMetrics,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    find_robust_response,
    with_remainder,
)
from spectre.domain.notso_prior import NotsoPrior
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _prior(probability: float = 0.13) -> NotsoPrior:
    """5 events over 100 days carried over 72 h: P 0.13 in 0.04 to 0.30."""
    return NotsoPrior(
        red="RX", action_type=ActionType.MANOEUVRE, probability=probability, confidence=None, events=5,
        notices=5, span_start=_NOW - timedelta(days=100), span_end=_NOW, covered_days=100.0, gaps=0,
        horizon_hours=72.0, mapped=(NOTSOType.MANOEUVRE, NOTSOType.PROXIMITY_OPS), confidence_line="",
    )


def _sparse() -> NotsoPrior:
    """3 events over 200 days carried over 72 h: P 0.04 in under 0.01 to 0.13, its exact lower edge 0.009."""
    return dataclasses.replace(_prior(0.04), events=3, covered_days=200.0)


#: The remainder row's score under every response: one constant, so it moves no crossing and no pick (SPC-203).
_REMAINDER_SCORE = 0.5
_SUFFIX = " and the remainder of P taking up the difference."
_JOINT_SUFFIX = ", with the remainder of P taking up the difference."


def _both_applied(result: ScenarioResult, first: NotsoPrior, second: NotsoPrior) -> ScenarioResult:
    """*result* with rows 1 and 2 each holding an applied suggestion, at its own P."""
    rows = [a for a in result.scenario.adversary_actions if not a.remainder]
    rows[0] = dataclasses.replace(rows[0], probability=first.probability, accepted_prior=first)
    rows[1] = dataclasses.replace(rows[1], name="", action_type=ActionType.MANOEUVRE, probability=second.probability,
                                  accepted_prior=second)
    return _rows(result, rows)


def _rows(
    result: ScenarioResult, rows: list[AdversaryAction], scores: list[list[float]] | None = None,
) -> ScenarioResult:
    """*result* with the operator's rows *rows*, scored *scores* (by default as they were), the remainder row they
    leave scored _REMAINDER_SCORE, and its pick taken again."""
    kept = [[cell.composite_score for cell in row] for row, action in
            zip(result.outcome_matrix, result.scenario.adversary_actions, strict=True) if not action.remainder]
    return _evaluated(dataclasses.replace(result.scenario, adversary_actions=rows), scores or kept,
                      result.robust_strategy)


def _evaluated(scenario: Scenario, scores: list[list[float]], strategy: SelectorStrategy) -> ScenarioResult:
    scenario = with_remainder(scenario)
    matrix = [[_metrics(s) for s in row] for row in scores]
    if scenario.adversary_actions[-1].remainder:
        matrix.append([_metrics(_REMAINDER_SCORE) for _ in scores[0]])
    return ScenarioResult(
        scenario=scenario, outcome_matrix=matrix, ranked_per_adversary=[], computation_time_s=0.0,
        robust_best_response=find_robust_response(scenario, matrix, strategy), robust_strategy=strategy,
    )


def _metrics(score: float) -> OutcomeMetrics:
    return OutcomeMetrics(
        custody_maintained=True, custody_gap_hours=0.0, closest_approach_km=1000.0,
        time_to_closest_hours=1.0, delta_v_cost_km_s=0.0, composite_score=score,
    )


def _result(
    scores: list[list[float]], other_p: float = 0.6, strategy: SelectorStrategy = SelectorStrategy.EXPECTED_VALUE,
    *, applied: bool = True,
) -> ScenarioResult:
    """Row 1, Approach, holds the NOTSO suggestion (or the same P typed); row 2, Hold, the operator's *other_p*."""
    rows = [
        AdversaryAction(id="A1", name="Approach", action_type=ActionType.MANOEUVRE, probability=0.13, confidence=0.7,
                        accepted_prior=_prior() if applied else None),
        AdversaryAction(id="A2", name="Hold", action_type=ActionType.POSTURE_CHANGE, probability=other_p,
                        confidence=0.7),
    ]
    responses = [
        FriendlyResponse(id=f"F{j}", name=name, action_type=ActionType.NO_ACTION, cost=0.1, reversibility=1.0,
                         time_to_execute_hours=1.0)
        for j, name in enumerate(("Evade", "Watch", "Wait")[:len(scores[0])])
    ]
    scenario = Scenario(name="Interval", epoch_utc=_NOW, adversary_actions=rows, friendly_responses=responses)
    return _evaluated(scenario, scores, strategy)


class TestUnderExpectedValue:
    def test_a_pick_that_holds_across_the_interval_says_so(self) -> None:
        # Evade 0.06 + 0.9p against Watch 0.30 + 0.2p, over 0.6 + p: they cross at p 0.343, past 0.30.
        (line,) = _result([[0.9, 0.2], [0.1, 0.5]]).interval_lines
        assert line == ("Row 1, Approach: expected value recommends Evade at every P across its NOTSO interval, "
                        "0.04 to 0.30, with the other rows held at their P" + _SUFFIX)

    def test_a_pick_that_changes_above_the_centre_names_the_p_it_changes_at(self) -> None:
        # Evade 0.06 + 0.9p against Watch 0.18 + 0.2p: Evade at 0.13, Watch past their crossing at p 0.171.
        result = _result([[0.9, 0.2], [0.1, 0.3]])
        assert result.robust_best_response.name == "Evade"
        (line,) = result.interval_lines
        assert line == ("Row 1, Approach: expected value recommends Evade at P 0.13, but not across its NOTSO "
                        "interval, 0.04 to 0.30: above P 0.171 it recommends Watch, with the other rows held at "
                        "their P" + _SUFFIX)

    def test_a_pick_that_changes_below_the_centre_names_the_p_it_changes_at(self) -> None:
        # Row 2 at 0.2: Evade 0.02 + 0.7p against Watch 0.06 + 0.2p, crossing at p 0.080: Watch at 0.13, Evade below.
        (line,) = _result([[0.7, 0.2], [0.1, 0.3]], other_p=0.2).interval_lines
        assert "recommends Watch at P 0.13, but not across its NOTSO interval, 0.04 to 0.30: below P 0.080 it " \
               "recommends Evade, with" in line

    def test_a_pick_can_change_on_both_sides(self) -> None:
        # Row 2 at 0.2: Evade 0.004 + 0.8p, Watch 0.079 + 0.2p and Wait 0.019 + 0.6p. Wait is best at 0.13;
        # Evade takes over below its crossing with Wait at p 0.075, and Watch above its own at p 0.150.
        result = _result([[0.8, 0.2, 0.6], [0.02, 0.395, 0.095]], other_p=0.2)
        assert result.robust_best_response.name == "Wait"
        (line,) = result.interval_lines
        assert ": below P 0.075 it recommends Evade; above P 0.150 it recommends Watch, with the other rows" in line

    def test_a_lower_edge_under_the_hundredth_reads_under_0_01_and_the_pick_is_checked_from_above_0(self) -> None:
        # 3 events over 200 days carried over 72 h: P 0.04 in under 0.01 to 0.13, checked from its exact edge, 0.009.
        sparse = _sparse()
        result = _result([[0.9, 0.2], [0.1, 0.5]])
        row = dataclasses.replace(result.scenario.adversary_actions[0], name="", probability=0.04,
                                  accepted_prior=sparse)
        (line,) = _rows(result, [row, result.scenario.adversary_actions[1]]).interval_lines
        assert line == ("Row 1: expected value recommends Evade at every P across its NOTSO interval, under 0.01 to "
                        "0.13, with the other rows held at their P" + _SUFFIX)

    def test_the_pick_is_checked_from_the_exact_lower_edge_not_the_0_shown_beneath_it(self) -> None:
        # Row 2 at 0.6: Evade 0.06 + 0.9p against Watch 0.0635 + 0.2p, crossing at p 0.005. That lies below the exact
        # lower edge, 0.009, so Watch holds across the interval; read from 0 it would name a change at 0.005.
        result = _result([[0.9, 0.2], [0.1, 0.105833]])
        row = dataclasses.replace(result.scenario.adversary_actions[0], name="", probability=0.04,
                                  accepted_prior=_sparse())
        (line,) = _rows(result, [row, result.scenario.adversary_actions[1]]).interval_lines
        assert line == ("Row 1: expected value recommends Watch at every P across its NOTSO interval, under 0.01 to "
                        "0.13, with the other rows held at their P" + _SUFFIX)

    def test_two_responses_scoring_the_same_in_the_moved_row_never_cross(self) -> None:
        # Evade 0.06 + 0.5p against Watch 0.12 + 0.5p: parallel, so no P makes them equal, and Evade holds.
        (line,) = _result([[0.5, 0.5], [0.1, 0.2]]).interval_lines
        assert line == ("Row 1, Approach: expected value recommends Evade at every P across its NOTSO interval, "
                        "0.04 to 0.30, with the other rows held at their P" + _SUFFIX)

    def test_a_crossing_outside_the_interval_is_not_named(self) -> None:
        # Row 2 at 0.2: Evade 0.046 + 0.01p, Watch 0.2 + 0.84p and Wait 0.094 + 0.26p cross only below 0, at -0.192,
        # -0.186 and -0.183, where Watch would take over; inside 0.04 to 0.30 Evade holds.
        (line,) = _result([[0.01, 0.84, 0.26], [0.23, 1.0, 0.47]], other_p=0.2).interval_lines
        assert line == ("Row 1, Approach: expected value recommends Evade at every P across its NOTSO interval, "
                        "0.04 to 0.30, with the other rows held at their P" + _SUFFIX)

    def test_a_row_whose_p_is_the_operators_own_carries_no_interval(self) -> None:
        assert _result([[0.9, 0.2], [0.1, 0.3]], applied=False).interval_lines == ()

    def test_no_line_breaks_i13(self) -> None:
        lines = [*_result([[0.9, 0.2], [0.1, 0.5]]).interval_lines,
                 *_result([[0.8, 0.2, 0.6], [0.02, 0.395, 0.095]], other_p=0.2).interval_lines]
        assert [s for line in lines for s in line.split(". ") if i13_problems(s)] == []


class TestRowsMovedTogether:
    def test_a_pick_each_row_holds_alone_can_change_when_they_move_together(self) -> None:
        # Both at P 0.13, each in 0.04 to 0.30. Moved alone, neither changes Watch; with row 1 at 0.04 and row 2 at
        # 0.30, Wait 0.2312 beats Watch 0.2675, over the same total.
        result = _both_applied(_result([[0.96, 0.01, 0.78], [0.82, 0.89, 0.74]], other_p=0.13), _prior(), _prior())
        first, second, together = result.interval_lines
        assert "recommends Watch at every P across its NOTSO interval" in first
        assert "recommends Watch at every P across its NOTSO interval" in second
        assert together == ("Moved together across their NOTSO intervals, rows 1 and 2's P do not keep expected "
                            "value at Watch: with row 1's P at 0.04 and row 2's at 0.30, it recommends Wait"
                            + _JOINT_SUFFIX)

    def test_a_pick_that_holds_at_every_combination_says_so_and_names_the_rows_held(self) -> None:
        # Evade 0.06 + 0.9s against Watch 0.54 + 0.2s, s the sum of rows 1 and 2's P: they cross at s 0.686, past
        # the 0.60 both upper edges reach, and past the 0.40 row 3's P of 0.6 leaves them, where the box is cut so
        # the rows' P never sum above 1 (SPC-203).
        result = _both_applied(_result([[0.9, 0.2], [0.9, 0.2]], other_p=0.13), _prior(), _prior())
        third = AdversaryAction(id="A3", name="Drift", action_type=ActionType.POSTURE_CHANGE, probability=0.6,
                                confidence=0.7)
        operators = [a for a in result.scenario.adversary_actions if not a.remainder]
        lines = _rows(result, [*operators, third], [[0.9, 0.2], [0.9, 0.2], [0.1, 0.9]]).interval_lines
        assert lines[-1] == ("Moved together across their NOTSO intervals, rows 1 and 2's P keep expected value at "
                             "Evade throughout, with the other rows held at their P" + _SUFFIX)

    def test_a_combination_at_a_lower_edge_under_the_hundredth_names_the_exact_edge(self) -> None:
        # Evade 0.4(p1 + p2) against Watch p1 + 0.3p2: Watch wins once p1 is under a sixth of p2. Not at P 0.04 and
        # 0.13, but at row 1's exact lower edge, 0.009, and row 2's upper, 0.30.
        result = _both_applied(_result([[0.4, 1.0], [0.4, 0.3]]), _sparse(), _prior())
        assert result.robust_best_response.name == "Evade"
        assert result.interval_lines[-1].endswith(
            "with row 1's P at 0.009 and row 2's at 0.30, it recommends Watch" + _JOINT_SUFFIX)

    def test_one_row_holding_a_suggestion_is_not_moved_with_any_other(self) -> None:
        lines = _result([[0.9, 0.2], [0.1, 0.5]]).interval_lines
        assert [line for line in lines if "Moved together" in line] == []

    def test_no_line_breaks_i13(self) -> None:
        result = _both_applied(_result([[0.96, 0.01, 0.78], [0.82, 0.89, 0.74]], other_p=0.13), _prior(), _prior())
        assert [s for line in result.interval_lines for s in line.split(". ") if i13_problems(s)] == []


class TestUnderARuleThatReadsNoProbability:
    def test_minimax_says_it_does_not_use_probability_and_shows_no_interval(self) -> None:
        (line,) = _result([[0.9, 0.2], [0.1, 0.3]], strategy=SelectorStrategy.MINIMAX).interval_lines
        assert line == ("Minimax does not use probability, so the NOTSO interval on row 1's P cannot move its pick "
                        "and is not shown.")
        assert "0.04" not in line

    def test_it_names_every_row_holding_a_suggestion_in_one_line(self) -> None:
        result = _result([[0.9, 0.2], [0.1, 0.3]], strategy=SelectorStrategy.MINIMAX)
        first = result.scenario.adversary_actions[0]
        (line,) = _rows(result, [first, dataclasses.replace(first, id="A2", name="")]).interval_lines
        assert "the NOTSO interval on rows 1 and 2's P cannot move its pick" in line

    def test_minimin_says_the_same(self) -> None:
        (line,) = _result([[0.9, 0.2], [0.1, 0.3]], strategy=SelectorStrategy.MINIMIN).interval_lines
        assert line.startswith("Minimin does not use probability")

    def test_with_no_suggestion_applied_it_says_nothing(self) -> None:
        assert _result([[0.9, 0.2], [0.1, 0.3]], strategy=SelectorStrategy.MINIMAX, applied=False).interval_lines == ()


class TestThePickItself:
    def test_expected_value_still_weighs_by_probability(self) -> None:
        # A refactor that moves the arithmetic keeps the pick: Evade 0.177 against Watch 0.206 at P 0.13.
        assert _result([[0.9, 0.2], [0.1, 0.3]]).robust_best_response.name == "Evade"
