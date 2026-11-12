"""Unequal turns, set by the engine from the rows' burn times (SPC-187, design D3).

The owner's ruling of 2026-11-05 on D3 (docs/decision_engine_phases.md): the engine places each turn boundary from
the rows' burn times, so every burn falls inside its own turn, and the operator never sets a length. A row carrying
several burns of one transfer (SPC-184) gives each burn a turn of its own: taken in turn 1, its burn j falls in turn
j at its own time, carried there as the matrix flew it; taken again in a later turn, it makes each burn the same time
after its own turn starts. Each boundary is the equal split where that falls after every row's burn of the turn
ending and by every row's next burn, and midway between them where it does not. A record written before SPC-187
holds no turn rule: it reads as equal turns and replays exactly as it was evaluated.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from typing import Any

import numpy as np
import pytest

from spectre.astro.monte_carlo import (
    ContinuedRed,
    SeparationWindow,
    TurnBurn,
    continue_series,
    elset_state,
    nominal_turn_burns,
    rk45_arc,
)
from spectre.domain import decision_tree
from spectre.domain.decision import ActionType, AdversaryAction, Scenario, TurnRule, evaluate_scenario
from spectre.domain.decision_inputs import (
    VERSION,
    VERSIONS,
    InputsRefusedError,
    canonical_json,
    read_inputs,
    sha256_of,
    store_inputs,
)
from spectre.domain.decision_replay import LEGACY_TURNS, said_first
from spectre.domain.decision_transfer import TransferBurn
from spectre.domain.decision_tree import (
    SENTENCES,
    TREE_BURN_OUTSIDE,
    TREE_RED_AGAIN,
    TREE_SEVERAL_BURNS,
    evaluate_tree,
    refused_before_run,
)
from spectre.domain.turn_update import (
    TREE_BURN_OUTSIDE_TURN,
    TREE_NO_BOUNDARY,
    TREE_TOO_FEW_TURNS,
    TurnPlan,
    burns_on,
    plan_or_equal,
    turn_plan,
)
from spectre.web.decision_record import replay_record, stored_of
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import EPOCH, PLANE_CHANGE
from tests.unit._i13 import i13_problems
from tests.unit.test_decision_elset_error import _V3, _records
from tests.unit.test_decision_sampled import _steady

_H = 3600.0


def _transfer(*at_h: float, n: int = 50) -> AdversaryAction:
    """A transfer of 1 m/s in-track burns at *at_h* hours after the epoch, the first from plane_change red's state."""
    first, *later = at_h
    hypothesis = _steady(n, at=EPOCH + timedelta(hours=first))
    then = tuple(TransferBurn(EPOCH + timedelta(hours=h), 1.0, 0.0, 0.0) for h in later)
    return AdversaryAction("A1", "Transfer", ActionType.MANOEUVRE, 0.5, 0.7,
                           hypothesis=hypothesis.with_transfer(then) if then else hypothesis)


def _plan(rows: list[AdversaryAction], *, turns: int = 2, horizon_h: float = 6.0, responses: Any = None,
          bind: Any = PLANE_CHANGE) -> TurnPlan | str:
    return turn_plan(cases.scenario(rows, responses or [cases.hold()], turns=turns, horizon_h=horizon_h, bind=bind))


def _starts_h(plan: TurnPlan | str) -> list[float]:
    assert isinstance(plan, TurnPlan), plan
    return [round(s / _H, 6) for s in plan.starts_s]


# ── Where the engine puts the turns ──

class TestTheEngineSetsTheTurns:
    def test_single_burns_that_fit_take_the_equal_split(self) -> None:
        plan = _plan([cases.still(), cases.evasive(PLANE_CHANGE, offset_h=0.5)])
        assert _starts_h(plan) == [0.0, 3.0]
        assert isinstance(plan, TurnPlan)
        assert plan.burns_s == ((), (0.5 * _H,))
        assert [plan.length_s(k) / _H for k in (1, 2)] == [3.0, 3.0]

    def test_a_transfers_second_burn_falls_in_turn_two(self) -> None:
        plan = _plan([cases.still(), _transfer(0.5, 4.0)])
        assert _starts_h(plan) == [0.0, 3.0]
        assert isinstance(plan, TurnPlan)
        assert plan.burns_s[1] == (0.5 * _H, 1.0 * _H)

    def test_where_the_equal_split_falls_after_the_next_burn_the_boundary_is_midway(self) -> None:
        plan = _plan([cases.still(), _transfer(0.5, 2.0)])
        assert _starts_h(plan) == [0.0, 1.25]
        assert isinstance(plan, TurnPlan)
        assert plan.burns_s[1] == (0.5 * _H, 0.75 * _H)

    def test_three_turns_place_each_boundary_in_turn(self) -> None:
        plan = _plan([cases.still(), _transfer(0.5, 2.5)], turns=3)
        assert _starts_h(plan) == [0.0, 2.0, 4.0]

    def test_the_turns_run_the_whole_span_and_every_burn_falls_inside_its_own(self) -> None:
        plan = _plan([cases.evasive(PLANE_CHANGE, offset_h=0.25), _transfer(0.5, 2.5)], turns=3)
        assert isinstance(plan, TurnPlan)
        assert sum(plan.length_s(k) for k in (1, 2, 3)) == pytest.approx(6.0 * _H)
        for row in range(2):
            for k in (1, 2, 3):
                for j, at_s in enumerate(plan.move_burns_s(row, k)):
                    assert plan.start_s(k + j) <= at_s < plan.end_s(k + j), (row, k, j)

    def test_a_burn_that_would_fall_after_the_last_turn_is_not_made(self) -> None:
        plan = _plan([_transfer(0.5, 4.0)])
        assert isinstance(plan, TurnPlan)
        assert plan.move_burns_s(0, 1) == (0.5 * _H, 4.0 * _H)
        assert plan.move_burns_s(0, 2) == (3.5 * _H,)

    def test_the_operator_sets_no_length(self) -> None:
        assert [f.name for f in dataclasses.fields(Scenario) if "turn" in f.name] == ["turns", "turn_rule"]
        assert Scenario("S", EPOCH, [], []).turn_rule is TurnRule.BURNS


class TestWhatTheEngineCannotPlace:
    def test_a_transfer_of_more_burns_than_turns(self) -> None:
        plan = _plan([_transfer(0.5, 1.0, 1.5)])
        assert plan == TREE_TOO_FEW_TURNS.format(row=1, name="Transfer", n=3, turns=2)
        assert plan == (
            "No tree built: row 1, Transfer, makes 3 burns of one transfer within the span searched, and every burn "
            "falls inside a turn of its own, so it needs 3 turns, more than the 2 asked for. This result is one turn."
        )

    def test_a_row_burning_again_before_another_has_burnt_once(self) -> None:
        late = dataclasses.replace(cases.evasive(PLANE_CHANGE, offset_h=1.5), id="A2", name="Late")
        plan = _plan([_transfer(0.5, 1.0), late])
        assert plan == TREE_NO_BOUNDARY.format(late=1, late_name="Transfer", j1=2, h1=1.0, early=2,
                                               early_name="Late", j=1, h0=1.5)

    def test_a_first_burn_at_or_after_the_span_is_refused_naming_its_row(self) -> None:
        late = dataclasses.replace(cases.evasive(PLANE_CHANGE, offset_h=7.0), name="Late")
        plan = _plan([late, cases.still()])
        assert plan == TREE_BURN_OUTSIDE_TURN.format(what="Late's burn", h=7.0, k=1, turn_h=6.0)
        assert isinstance(plan, str) and "row 0" not in plan

    def test_a_burn_again_that_does_not_fit_its_later_turn(self) -> None:
        plan = _plan([cases.still(), cases.evasive(offset_h=2.5)], horizon_h=4.0, bind=cases.COPLANAR_LEO)
        assert plan == TREE_BURN_OUTSIDE_TURN.format(what="Evasive's burn", h=2.5, k=2, turn_h=0.75)

    def test_a_response_executing_after_a_turn_ends(self) -> None:
        plan = _plan([cases.still()], horizon_h=4.0, responses=[cases.hold(), cases.avoid(hours=3.0)])
        assert plan == TREE_BURN_OUTSIDE_TURN.format(what="Avoid's burn", h=3.0, k=1, turn_h=2.0)

    def test_a_transfers_burn_taken_again_names_its_number(self) -> None:
        # Turns of 2.0, 3.5 and 0.5 h: taken in turn 2, its second burn falls 3.0 h into turn 3.
        plan = _plan([cases.still(), _transfer(0.1, 5.0)], turns=3)
        assert plan == TREE_BURN_OUTSIDE_TURN.format(what="Transfer's burn 2", h=3.0, k=3, turn_h=0.5)
        assert plan == (
            "No tree built: Transfer's burn 2 at 3.00 h after turn 3 starts falls outside that turn, 0.50 h long. "
            "The engine sets each turn from the rows' burn times so every burn falls inside its own turn; take "
            "fewer turns. This result is one turn."
        )

    def test_the_refusals_keep_the_house_checks(self) -> None:
        for sentence in (TREE_TOO_FEW_TURNS, TREE_NO_BOUNDARY, TREE_BURN_OUTSIDE_TURN):
            assert sentence in SENTENCES
            assert i13_problems(sentence.replace("{", "").replace("}", "")) == []
            assert "--" not in sentence and "—" not in sentence


class TestTheTreeIsRefusedOnlyWhereNoTurnsFit:
    def test_a_transfer_is_no_longer_refused_for_its_burns(self) -> None:
        scenario = cases.scenario([cases.still(), _transfer(0.5, 4.0)], [cases.hold()], bind=PLANE_CHANGE)
        assert refused_before_run(scenario) is None

    def test_a_plan_refusal_refuses_the_tree(self) -> None:
        scenario = cases.scenario([_transfer(0.5, 1.0, 1.5)], [cases.hold()], bind=PLANE_CHANGE)
        assert refused_before_run(scenario) == TREE_TOO_FEW_TURNS.format(row=1, name="Transfer", n=3, turns=2)


class TestEqualTurnsStandForARecordWrittenBefore:
    def _equal(self, rows: list[AdversaryAction], **kw: Any) -> Scenario:
        built = cases.scenario(rows, kw.pop("responses", [cases.hold()]), bind=kw.pop("bind", PLANE_CHANGE), **kw)
        return dataclasses.replace(built, turn_rule=TurnRule.EQUAL)

    def test_its_turns_are_equal(self) -> None:
        assert _starts_h(turn_plan(self._equal([cases.still(), _transfer(0.5, 2.0)]))) == [0.0, 3.0]

    def test_a_row_of_several_burns_refuses_its_tree(self) -> None:
        scenario = self._equal([_transfer(0.5, 4.0)])
        assert refused_before_run(scenario) == TREE_SEVERAL_BURNS.format(row=1, name="Transfer", n=2)

    def test_a_burn_outside_its_equal_turn_is_named_as_before(self) -> None:
        scenario = self._equal([cases.still(), cases.evasive(offset_h=2.5)], horizon_h=4.0, bind=cases.COPLANAR_LEO)
        assert refused_before_run(scenario) == TREE_BURN_OUTSIDE.format(what="Evasive's burn", h=2.5, turn_h=2.0)

    def test_a_response_burning_after_its_equal_turn_ends_is_named_as_before(self) -> None:
        scenario = self._equal([cases.still()], responses=[cases.hold(), cases.avoid(hours=3.0)], horizon_h=4.0,
                               bind=cases.COPLANAR_LEO)
        assert refused_before_run(scenario) == TREE_BURN_OUTSIDE.format(what="Avoid's burn", h=3.0, turn_h=2.0)

    def test_a_plan_the_engine_refuses_is_equal_for_a_selector(self) -> None:
        scenario = cases.scenario([_transfer(0.5, 1.0, 1.5)], [cases.hold()], bind=PLANE_CHANGE)
        assert _starts_h(plan_or_equal(scenario)) == [0.0, 3.0]


# ── What each turn holds of red ──

class TestTheBurnsOnAPath:
    def test_a_transfer_taken_in_turn_one_makes_its_second_burn_in_turn_two(self) -> None:
        scenario = cases.scenario([cases.still(), _transfer(0.5, 4.0)], [cases.hold()], bind=PLANE_CHANGE)
        plan = turn_plan(scenario)
        assert isinstance(plan, TurnPlan)
        assert burns_on(scenario, (1, 0), plan) == (EPOCH + timedelta(hours=0.5), EPOCH + timedelta(hours=4.0))

    def test_taken_in_turn_two_its_second_burn_would_fall_after_the_last_turn(self) -> None:
        scenario = cases.scenario([cases.still(), _transfer(0.5, 4.0)], [cases.hold()], bind=PLANE_CHANGE)
        plan = turn_plan(scenario)
        assert isinstance(plan, TurnPlan)
        assert burns_on(scenario, (0, 1), plan) == (EPOCH + timedelta(hours=3.5),)

    def test_a_length_in_seconds_still_reads_as_equal_turns(self) -> None:
        scenario = cases.scenario([cases.still(), cases.evasive(offset_h=1.0)], [cases.hold()])
        assert burns_on(scenario, (1, 1), 3 * _H) == (EPOCH + timedelta(hours=1.0), EPOCH + timedelta(hours=4.0))


# ── A tree over a transfer ──

@pytest.fixture(scope="module")
def transfer_tree() -> tuple[Any, list[ContinuedRed]]:
    """plane_change, Hold course and a 2-burn transfer at 0.1 h and 0.7 h, against Hold and Avoid at 20 km
    executing 0.05 h in, over a 1 h span: the engine ends turn 1 at 0.5 h, the equal split."""
    rows = [cases.still(), _transfer(0.1, 0.7)]
    scenario = cases.scenario(rows, [cases.hold(), cases.avoid(20.0, hours=0.05)], horizon_h=1.0, bind=PLANE_CHANGE)
    seen: list[ContinuedRed] = []
    real = decision_tree.continue_series

    def recording(red: ContinuedRed, *args: Any, **kwargs: Any) -> Any:
        seen.append(red)
        return real(red, *args, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(decision_tree, "continue_series", recording)
    try:
        result = evaluate_tree(scenario)
    finally:
        patch.undo()
    return result, seen


class TestATreeOverATransfer:
    def test_it_is_built(self, transfer_tree: tuple[Any, list[ContinuedRed]]) -> None:
        result, _ = transfer_tree
        tree = result.tree
        assert tree is not None
        assert tree.refusal is None, tree.refusal
        assert tree.complete_turns == 2
        assert [w.start_utc for w in tree.windows] == [EPOCH, EPOCH + timedelta(hours=0.5)]

    def test_turn_two_under_the_transfer_carries_its_second_burn(
        self, transfer_tree: tuple[Any, list[ContinuedRed]],
    ) -> None:
        _, seen = transfer_tree
        carried = [red for red in seen if red.pending and any(red.pending)]
        assert carried, "no turn carried a burn into turn 2"
        for red in carried:
            assert {len(p) for p in red.pending} == {1}
            assert {round(p[0].at_s, 6) for p in red.pending} == {720.0}

    def test_the_transfer_taken_in_turn_two_makes_its_first_burn_there(
        self, transfer_tree: tuple[Any, list[ContinuedRed]],
    ) -> None:
        _, seen = transfer_tree
        again = [red.burn for red in seen if red.burn is not None]
        assert again
        assert {(round(b.at_s, 6), b.then) for b in again} == {(360.0, ())}

    def test_its_lines_say_how_the_engine_set_the_turns(self, transfer_tree: tuple[Any, list[ContinuedRed]]) -> None:
        result, _ = transfer_tree
        tree = result.tree
        assert tree is not None
        assert tree.lines[0] == (
            "A 2-turn tree: 2 red moves and 2 responses each turn, 20 branches. The engine sets each turn from the "
            "rows' burn times, so every burn falls inside its own turn: turn 1 runs 0.50 h and turn 2 0.50 h, of the "
            "1.0 h searched; turn 2 starts at 12:30 UTC."
        )
        assert decision_tree.TREE_TRANSFER_AGAIN.format(row=2, name="Transfer", n=2, offsets="0.10 h and 0.20 h") in (
            tree.lines)
        assert not any(line.startswith("Row 2, Transfer: in turns 2 and on") for line in tree.lines)

    def test_a_single_burn_row_keeps_its_line(self) -> None:
        line = TREE_RED_AGAIN.format(row=2, name="Evasive", offset=0.1)
        assert line.startswith("Row 2, Evasive: in turns 2 and on it burns again 0.10 h after each turn starts")

    def test_the_same_inputs_give_the_same_tree(self, transfer_tree: tuple[Any, list[ContinuedRed]]) -> None:
        result, _ = transfer_tree
        again = evaluate_tree(result.scenario)
        assert again.tree is not None and result.tree is not None
        first = [n.path.score for n in result.tree.nodes()]
        assert [n.path.score for n in again.tree.nodes()] == first
        assert np.isfinite(first).all()


@pytest.fixture(scope="module")
def three_turns() -> tuple[list[tuple[ContinuedRed, Any]], list[tuple[float, Any, tuple[Any, ...], float]]]:
    """plane_change, Hold course and a 2-burn transfer at 0.1 h and 0.4 h, against Hold, over a 1 h span in three
    turns: the engine starts turn 2 at 1/3 h and turn 3 at 2/3 h, the equal splits, so the transfer's second burn
    falls 0.0667 h, 240 s, into its own turn. Every series and every nominal arc the later turns ask for is recorded:
    (red, window start) and (B*, red's move, pending burns as stated, span)."""
    scenario = cases.scenario([cases.still(), _transfer(0.1, 0.4)], [cases.hold()], turns=3, horizon_h=1.0,
                              bind=PLANE_CHANGE)
    series: list[tuple[ContinuedRed, Any]] = []
    nominal: list[tuple[float, Any, tuple[Any, ...], float]] = []
    real_series, real_nominal = decision_tree.continue_series, decision_tree.nominal_continued_arc

    def on_series(red: ContinuedRed, blues: Any, window: SeparationWindow, **kw: Any) -> Any:
        series.append((red, window.start_utc))
        return real_series(red, blues, window, **kw)

    def on_nominal(state: Any, bstar: float, burn: Any, span_s: float, pending: Any = ()) -> Any:
        nominal.append((bstar, burn, tuple(pending), span_s))
        return real_nominal(state, bstar, burn, span_s, pending)

    patch = pytest.MonkeyPatch()
    patch.setattr(decision_tree, "continue_series", on_series)
    patch.setattr(decision_tree, "nominal_continued_arc", on_nominal)
    try:
        result = evaluate_tree(scenario)
    finally:
        patch.undo()
    assert result.tree is not None and result.tree.refusal is None, result.tree
    assert result.tree.complete_turns == 3
    return series, nominal


_TURN_2, _TURN_3 = EPOCH + timedelta(seconds=1200), EPOCH + timedelta(seconds=2400)


class TestThreeTurnsOverATransfer:
    def test_taken_in_turn_two_its_second_burn_falls_in_turn_three_at_its_own_offset(
        self, three_turns: tuple[list[tuple[ContinuedRed, Any]], Any],
    ) -> None:
        series, _ = three_turns
        moves = {(round(red.burn.at_s, 6), tuple(round(t, 6) for _, t in red.burn.then))
                 for red, at in series if at == _TURN_2 and red.burn is not None}
        assert moves == {(360.0, (1440.0,))}
        last = {tuple(red.burn.then) for red, at in series if at == _TURN_3 and red.burn is not None}
        assert last == {()}

    def test_turn_three_makes_each_second_burn_carried_into_it_240_s_in(
        self, three_turns: tuple[list[tuple[ContinuedRed, Any]], Any],
    ) -> None:
        series, _ = three_turns
        carried = {round(b.at_s, 6) for red, at in series if at == _TURN_3 for p in red.pending for b in p}
        assert carried == {240.0}

    def test_our_burn_is_sized_against_the_transfers_burns_still_to_come(
        self, three_turns: tuple[Any, list[tuple[float, Any, tuple[Any, ...], float]]],
    ) -> None:
        _, nominal = three_turns
        second = [pending for _, _, pending, span in nominal if round(span) == 2400 and pending]
        assert second
        assert {tuple((round(b.at_s, 6), b.bstar_after) for b in p) for p in second} == {((240.0, 1e-4),)}

    def test_the_bstar_red_flies_into_turn_three_is_the_one_after_its_last_burn(
        self, three_turns: tuple[Any, list[tuple[float, Any, tuple[Any, ...], float]]],
    ) -> None:
        # Every path whose turn-2 move was the transfer has burnt by turn 3, so flies its B* after: 1e-4, not 0.
        _, nominal = three_turns
        after = {bstar for bstar, _, pending, span in nominal if round(span) == 1200 and pending}
        assert after == {1e-4}
        assert {bstar for bstar, _, pending, span in nominal if round(span) == 1200} == {0.0, 1e-4}


# ── Records written before SPC-187 ──

class TestARecordWrittenBeforeReplaysUnderEqualTurns:
    def test_this_code_writes_version_5_holding_the_rule(self) -> None:
        assert (VERSION, VERSIONS) == (5, (1, 2, 3, 4, 5))
        scenario = cases.scenario([cases.still()], [cases.hold()], turns=1)
        document = json.loads(store_inputs(evaluate_scenario(scenario))[0])
        assert (document["version"], document["scenario"]["turn_rule"]) == (5, "burns")

    def test_the_0310_tree_reads_as_equal_turns_and_replays_exactly(self) -> None:
        row = _records(_V3)["tree"]
        stored = stored_of(row)
        assert (stored.scenario.turns, stored.scenario.turn_rule) == (2, TurnRule.EQUAL)
        done = replay_record(row)
        assert done.matches, done.lines
        assert LEGACY_TURNS in done.preamble

    def test_a_one_turn_record_says_nothing_of_turns(self) -> None:
        stored = stored_of(_records(_V3)["sampled_and_computed"])
        assert stored.scenario.turns == 1
        assert LEGACY_TURNS not in said_first(stored, "0.37.0")

    def test_a_result_under_equal_turns_is_never_stored_again(self) -> None:
        scenario = dataclasses.replace(cases.scenario([cases.still()], [cases.hold()], turns=1),
                                       turn_rule=TurnRule.EQUAL)
        with pytest.raises(ValueError, match="never stored again"):
            store_inputs(evaluate_scenario(scenario))

    def test_a_version_5_document_under_equal_turns_is_refused(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(cases.scenario([cases.still()], [cases.hold()],
                                                                             turns=1)))[0])
        document["scenario"]["turn_rule"] = TurnRule.EQUAL.value
        text = canonical_json(document)
        with pytest.raises(InputsRefusedError, match=r"refused at scenario\.turn_rule: version 5 holds"):
            read_inputs(text, sha256_of(text))

    def test_a_version_4_document_holding_the_rule_is_refused(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(cases.scenario([cases.still()], [cases.hold()],
                                                                             turns=1)))[0])
        document.pop("version")
        text = canonical_json({**document, "version": 4})
        with pytest.raises(InputsRefusedError, match="unknown field turn_rule"):
            read_inputs(text, sha256_of(text))

    def test_the_replay_line_keeps_the_house_checks(self) -> None:
        assert i13_problems(LEGACY_TURNS) == []
        assert "--" not in LEGACY_TURNS and "—" not in LEGACY_TURNS


class TestALaterBurnPastTheSpan:
    def test_it_takes_no_turn(self) -> None:
        plan = _plan([cases.still(), _transfer(0.5, 7.0)])
        assert isinstance(plan, TurnPlan)
        assert (_starts_h(plan), plan.burns_s[1]) == ([0.0, 3.0], (0.5 * _H,))


# ── A transfer's later burns, drawn and as stated, in a later turn ──

class TestATurnBurnCarriesItsTransfer:
    def _burn(self) -> TurnBurn:
        first = _steady(50, at=EPOCH).hypothesis
        return TurnBurn(first, 60.0, ((dataclasses.replace(first, random_seed=7), 600.0),))

    def test_as_stated_each_burn_is_at_its_time_with_its_nominal_parts(self) -> None:
        stated = nominal_turn_burns(self._burn())
        assert [b.at_s for b in stated] == [60.0, 600.0]
        assert [round(float(np.linalg.norm(b.delta_v_ric_km_s)), 9) for b in stated] == [0.001, 0.001]
        assert nominal_turn_burns(None) == ()

    def test_each_sample_draws_the_later_burn_and_one_past_the_turn_is_kept_for_the_next(self) -> None:
        red, blue = elset_state(PLANE_CHANGE.red_tle, EPOCH), elset_state(PLANE_CHANGE.blue_tle, EPOCH)
        assert red is not None and blue is not None
        blue_arc = rk45_arc(blue.state_eci_km, 1800.0, blue.bstar)
        assert blue_arc is not None
        states = np.repeat(red.state_eci_km[None, :], 50, axis=0)
        carried = ContinuedRed(states, np.full(50, red.bstar), self._burn())
        out = continue_series(carried, [blue_arc], SeparationWindow(EPOCH, 1800.0), keep_at_s=(300.0,))
        assert out.kept is not None
        assert {len(p) for p in out.kept.pending} == {1}
        assert {round(p[0].at_s, 6) for p in out.kept.pending} == {300.0}
        assert len(out.series[0].approaches) == 50
