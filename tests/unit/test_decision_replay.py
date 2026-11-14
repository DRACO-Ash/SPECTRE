"""Replay a recommendation from its stored decision record (SPC-193, evaluation F-02, gate G2).

The record alone rebuilds the Scenario from its stored inputs and evaluates it again under the stored rule; the
replay reports whether the recommendation, the three rules' picks, a tree's turn-1 pick and every composite score
match the record exactly. Sampling is seeded, so identical inputs repeat exactly (evaluation probe P-15). A record
written by another code version is replayed across versions, and the report says so before anything else.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.domain import decision_tree
from spectre.domain.decision import RunControl, Scenario, ScenarioResult, SelectorStrategy
from spectre.domain.decision_inputs import InputsRefusedError, canonical_json, read_inputs, sha256_of
from spectre.domain.decision_replay import (
    ACROSS_VERSIONS,
    BUDGET_RAN_OUT,
    SAME_VERSION,
    replay,
    said_first,
    version_line,
)
from spectre.domain.decision_tree import evaluate_tree
from spectre.web.decision_record import NO_INPUTS, Operator, new_record, recorded_of, replay_record, stored_of
from spectre.web.models import DecisionRecord
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import PLANE_CHANGE
from tests.unit.test_decision_inputs import _computed, _lookup, _sampled
from tests.unit.test_decision_tree_select import _still

_AT = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
_ALICE = Operator(7, "alice")


def _alone(row: DecisionRecord) -> DecisionRecord:
    """A record rebuilt from its stored columns alone, as a later reader takes it from the table."""
    return DecisionRecord(**{c.name: getattr(row, c.name) for c in DecisionRecord.__table__.columns})


def _recorded(scenario: Scenario, rule: SelectorStrategy) -> tuple[ScenarioResult, DecisionRecord]:
    result = evaluate_tree(scenario, rule)
    row = new_record(result, _ALICE, _AT, primary=SelectorStrategy.MINIMAX)
    row.id = 1
    return result, _alone(row)


@pytest.fixture(scope="module")
def sampled() -> tuple[ScenarioResult, DecisionRecord]:
    result, row = _recorded(_sampled(), SelectorStrategy.EXPECTED_VALUE)
    assert result.n_sampled_cells > 0
    return result, row


def _sampled_tree() -> Scenario:
    """plane_change, Hold course and a 50-sample Evasive burning 0.1 h in, against Hold and Avoid at 20 km executing
    0.05 h in, over two 0.5 h turns: test_decision_tree's sampled tree."""
    rows = [cases.still(), cases.evasive(PLANE_CHANGE, n=50, offset_h=0.1)]
    return cases.scenario(rows, [cases.hold(), cases.avoid(20.0, hours=0.05)], horizon_h=1.0, bind=PLANE_CHANGE)


@pytest.fixture(scope="module")
def tree() -> tuple[ScenarioResult, DecisionRecord]:
    result, row = _recorded(_sampled_tree(), SelectorStrategy.MINIMAX)
    assert result.tree is not None and result.tree.selection is not None and result.tree.complete_turns == 2
    return result, row


class TestAReplayReproducesTheRecord:
    def test_a_lookup_scenario(self) -> None:
        result, row = _recorded(_lookup(), SelectorStrategy.MINIMIN)
        assert result.n_sampled_cells == result.n_computed_cells == 0
        done = replay_record(row)
        assert done.matches, done.lines
        assert not done.across_versions
        assert len([c for c in done.comparisons if c.what.startswith("Score")]) == 4 * 3

    def test_a_computed_scenario(self) -> None:
        result, row = _recorded(_computed(), SelectorStrategy.MINIMAX)
        assert result.n_computed_cells > 0
        done = replay_record(row)
        assert done.matches, done.lines

    def test_a_sampled_scenario(self, sampled: tuple[ScenarioResult, DecisionRecord]) -> None:
        _result, row = sampled
        done = replay_record(row)
        assert done.matches, done.lines
        assert {c.what for c in done.comparisons} >= {
            "Recommendation, the pick of the primary rule, minimax", "Pick of the rule used, expected value",
            "Minimax's pick", "Minimin's pick", "Expected value's pick", "Rule used", "Code version",
        }

    def test_a_two_turn_tree(self, tree: tuple[ScenarioResult, DecisionRecord]) -> None:
        result, row = tree
        done = replay_record(row)
        assert done.matches, done.lines
        (turn_one,) = [c for c in done.comparisons if c.what == "Tree's turn-1 pick (minimax)"]
        assert turn_one.recorded == f"{row.tree_pick_name} ({row.tree_pick_id})"

    def test_every_score_is_compared_at_full_precision(self, sampled: tuple[ScenarioResult, DecisionRecord]) -> None:
        result, row = sampled
        done = replay_record(row)
        scores = [c for c in done.comparisons if c.what.startswith("Score")]
        assert [c.recorded for c in scores] == [repr(cell.composite_score) for r in result.outcome_matrix for cell in r]
        assert scores[0].what == "Score, row 1 (A0), response 1 (F0)"

    def test_the_report_says_it_matches(self, sampled: tuple[ScenarioResult, DecisionRecord]) -> None:
        done = replay_record(sampled[1])
        assert done.lines[0] == SAME_VERSION.format(version=sampled[1].code_version)
        hashes = len(json.loads(sampled[1].input_hashes))
        assert hashes > 0
        assert done.lines[-1] == (
            f"Replay matches the record exactly: the recommendation, every pick, every score (4) and every input "
            f"hash ({hashes})."
        )

    def test_the_report_names_each_check_and_pick_and_says_each_is_the_same(
        self, sampled: tuple[ScenarioResult, DecisionRecord],
    ) -> None:
        done = replay_record(sampled[1])
        shown = done.lines[1:-1]
        assert shown[0] == "Rule used: the record says expected value, its stored inputs say expected value: same."
        assert shown[1] == (
            f"Code version: the record says {sampled[1].code_version}, its stored inputs say "
            f"{sampled[1].code_version}: same."
        )
        assert all(line.endswith(": same.") for line in shown)
        assert not any(line.startswith(("Score", "Input hash")) for line in shown)

    def test_names_are_compared_as_the_record_keeps_them(self) -> None:
        """A NUL in a name is kept as U+FFFD; the replayed name is put in the same form before it is compared."""
        scenario = _lookup()
        named = [dataclasses.replace(r, name=f"{r.name} \x00") for r in scenario.friendly_responses]
        result, row = _recorded(dataclasses.replace(scenario, friendly_responses=named), SelectorStrategy.MINIMIN)
        pick = result.robust_best_response
        assert pick.name.endswith(" \x00")
        done = replay_record(row)
        assert done.matches, done.lines
        (used,) = [c for c in done.comparisons if c.what == "Pick of the rule used, minimin"]
        assert used.replayed == f"{pick.name[:-1]}\ufffd ({pick.id})"


def _nudged(result_scores: dict[str, Any]) -> Any:
    """An evaluator that runs the real one and then moves one composite score by the smallest step."""
    def evaluate(scenario: Scenario, rule: SelectorStrategy) -> ScenarioResult:
        result = evaluate_tree(scenario, rule)
        cell = result.outcome_matrix[0][1]
        moved = dataclasses.replace(cell, composite_score=cell.composite_score + 1e-15)
        result.outcome_matrix[0][1] = moved
        result_scores["moved"] = moved.composite_score
        return result
    return evaluate


class TestAReplayThatDiffersSaysWhere:
    def test_a_pick_that_differs_is_named(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        row.minimin_id, row.minimin_name = "R9", "Imagined"
        done = replay_record(row)
        assert not done.matches
        (differs,) = [c for c in done.comparisons if not c.same]
        assert differs.what == "Minimin's pick"
        assert "Minimin's pick: recorded Imagined (R9), replayed" in "\n".join(done.lines)
        assert done.lines[-1] == f"Replay does not match the record: 1 of {len(done.comparisons)} comparisons differ."

    def test_a_score_that_differs_in_its_last_digit_is_named(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        seen: dict[str, Any] = {}
        done = replay_record(row, evaluate=_nudged(seen))
        differs = [c for c in done.comparisons if not c.same and c.what.startswith("Score")]
        assert [c.what for c in differs] == ["Score, row 1 (A1), response 2 (F4)"]
        assert differs[0].replayed == repr(seen["moved"])
        assert not done.matches
        line = f"Score, row 1 (A1), response 2 (F4): recorded {differs[0].recorded}, replayed {differs[0].replayed}: DIFFERS."
        assert line in done.lines
        assert sum(item.startswith("Score") for item in done.lines) == 1


def _rehashed(row: DecisionRecord, change: Any) -> None:
    """*row*'s stored inputs changed by *change*, then put back in canonical form with a fresh SHA-256, as someone
    editing the table would leave them: the inputs' own hash no longer shows the change."""
    document = json.loads(row.inputs or "")
    change(document)
    row.inputs = canonical_json(document)
    row.inputs_sha256 = sha256_of(row.inputs)


class TestTheStoredInputsAreSetAgainstTheRecordsOwnColumns:
    def test_a_rehashed_edit_to_the_bound_element_set_is_caught_by_the_records_input_hashes(self) -> None:
        _result, row = _recorded(_computed(), SelectorStrategy.MINIMAX)

        def rename(document: dict[str, Any]) -> None:
            document["scenario"]["binding"]["red"]["name"] = "SOMETHING ELSE"
            document["scenario"]["binding"]["red"]["satno"] = 99999

        _rehashed(row, rename)
        done = replay_record(row)
        assert not done.matches
        hashes = [c for c in done.comparisons if c.what.startswith("Input hash") and not c.same]
        assert hashes
        assert any(line.startswith("Input hash") and line.endswith("DIFFERS.") for line in done.lines)

    def test_an_input_hash_held_that_the_replay_does_not_give_differs(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        held = json.loads(row.input_hashes)
        row.input_hashes = json.dumps([*held, {"label": "extra", "sha256": "0" * 64, "epoch": None}])
        done = replay_record(row)
        assert not done.matches
        extra = f"Input hash {len(held) + 1}: recorded extra: {'0' * 64}, replayed none: DIFFERS."
        assert extra in done.lines

    def test_a_rule_column_that_disagrees_with_the_stored_rule_differs(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMIN)
        row.rule = "minimax"
        done = replay_record(row)
        assert not done.matches
        assert "Rule used: the record says minimax, its stored inputs say minimin: DIFFERS." in done.lines

    def test_a_code_version_column_that_disagrees_with_the_stored_one_differs(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        stored_version = row.code_version
        row.code_version = "0.26.0"
        done = replay_record(row)
        assert not done.matches
        assert done.lines[0] == SAME_VERSION.format(version=stored_version)
        assert (f"Code version: the record says 0.26.0, its stored inputs say {stored_version}: DIFFERS."
                in done.lines)

    def test_the_version_said_first_is_the_one_inside_the_hashed_document(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)

        def older(document: dict[str, Any]) -> None:
            document["code_version"] = "0.26.0"

        _rehashed(row, older)
        done = replay_record(row, running="0.27.0")
        assert done.lines[0] == ACROSS_VERSIONS.format(recorded="0.26.0", running="0.27.0")
        assert done.across_versions
        assert said_first(stored_of(row), "0.27.0") == (done.lines[0],)


def _cut_short() -> RunControl:
    """A budget of 0 s: the first sampled row starts, and every row after it is refused for want of time."""
    return RunControl(budget_s=0.0, stop=lambda: None)


class TestAnEvaluationTheBudgetCutShort:
    def test_the_result_says_whether_the_budget_ran_out(self) -> None:
        cut = evaluate_tree(_sampled(), SelectorStrategy.MINIMAX, run=_cut_short())
        assert cut.budget_ran_out
        assert not evaluate_tree(_lookup(), SelectorStrategy.MINIMAX, run=_cut_short()).budget_ran_out
        assert not evaluate_tree(_lookup(), SelectorStrategy.MINIMAX).budget_ran_out

    def test_a_tree_the_budget_cut_after_turn_one_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = {"now": 0.0}
        real = decision_tree.rk45_pair

        def then_late(*args: Any) -> Any:
            clock["now"] = 200.0
            return real(*args)

        monkeypatch.setattr(decision_tree, "rk45_pair", then_late)
        run = RunControl(budget_s=100.0, stop=lambda: None, clock=lambda: clock["now"])
        result = evaluate_tree(_still(), run=run)
        assert result.tree is not None and result.tree.complete_turns == 1
        assert result.budget_ran_out

    def test_its_replay_says_so_before_comparing_and_in_its_verdict(self) -> None:
        result = evaluate_tree(_sampled(), SelectorStrategy.MINIMAX, run=_cut_short())
        row = _alone(new_record(result, _ALICE, _AT, primary=SelectorStrategy.MINIMAX))
        done = replay_record(row)
        assert done.lines[:2] == (SAME_VERSION.format(version=row.code_version), BUDGET_RAN_OUT)
        assert said_first(stored_of(row), row.code_version) == done.lines[:2]
        assert not done.matches
        assert done.lines[-1].endswith(
            "comparisons differ. The evaluation recorded ran out of its time budget, so a difference may come from "
            "what it left out."
        )

    def test_a_replay_of_a_whole_evaluation_says_nothing_of_a_budget(
        self, sampled: tuple[ScenarioResult, DecisionRecord],
    ) -> None:
        assert BUDGET_RAN_OUT not in replay_record(sampled[1]).lines


class TestAcrossVersions:
    def test_a_record_from_another_version_is_said_to_be_replayed_across_versions(
        self, sampled: tuple[ScenarioResult, DecisionRecord],
    ) -> None:
        _result, row = sampled
        done = replay_record(row, running="9.9.9")
        assert done.across_versions
        assert done.lines[0] == ACROSS_VERSIONS.format(recorded=row.code_version, running="9.9.9")
        assert done.matches
        assert done.lines[-1].startswith("Replay across versions matches the record exactly")

    def test_the_version_line_is_said_before_anything_is_evaluated(self) -> None:
        assert version_line("0.27.0", "0.28.0") == (
            "This record was written by SPECTRE 0.27.0 and the running code is 0.28.0: the replay is compared across "
            "versions, so a difference may come from the code rather than the inputs."
        )
        assert version_line("0.28.0", "0.28.0") == "This record was written by SPECTRE 0.28.0, the version running."

    def test_a_difference_across_versions_says_so(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        row.minimax_id = "R9"
        done = replay_record(row, running="9.9.9")
        assert done.lines[-1].startswith("Replay across versions does not match the record:")


class TestARecordWithNothingToReplay:
    def test_a_record_from_before_inputs_were_stored_holds_none(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        row.inputs, row.inputs_sha256 = None, None
        with pytest.raises(InputsRefusedError, match="no stored inputs"):
            replay_record(row)
        with pytest.raises(InputsRefusedError, match="no stored inputs"):
            stored_of(row)
        assert NO_INPUTS == (
            "This record holds no stored inputs: it was written by a version of SPECTRE that did not store them."
        )

    def test_a_record_whose_inputs_were_altered_is_refused(self) -> None:
        _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
        assert row.inputs is not None
        row.inputs = row.inputs.replace('"horizon_hours":36.5', '"horizon_hours":48.0')
        with pytest.raises(InputsRefusedError, match="SHA-256"):
            replay_record(row)

    def test_what_the_record_recommended_is_read_from_its_columns(self) -> None:
        result, row = _recorded(_lookup(), SelectorStrategy.MINIMIN)
        said = recorded_of(row)
        assert said.recommended == (result.robust_best_response.id, result.robust_best_response.name)
        assert set(said.picks) == set(SelectorStrategy)
        assert said.tree_pick is None
        assert (said.rule, said.code_version, said.primary) == ("minimin", row.code_version, SelectorStrategy.MINIMAX)
        assert said.input_hashes == tuple(json.loads(row.input_hashes))


def test_replay_takes_the_stored_rule_not_the_primary(sampled: tuple[ScenarioResult, DecisionRecord]) -> None:
    calls: list[SelectorStrategy] = []

    def evaluate(scenario: Scenario, rule: SelectorStrategy) -> ScenarioResult:
        calls.append(rule)
        return evaluate_tree(scenario, rule)

    replay_record(sampled[1], evaluate=evaluate)
    assert calls == [SelectorStrategy.EXPECTED_VALUE]


def test_the_domain_replay_reads_nothing_of_the_web() -> None:
    import spectre.domain.decision_replay as module

    with open(module.__file__, encoding="utf-8") as source:
        assert "spectre.web" not in source.read()
    assert callable(replay)


def test_the_domain_replay_compares_names_as_given_unless_told_how_the_record_keeps_them() -> None:
    _result, row = _recorded(_lookup(), SelectorStrategy.MINIMAX)
    stored = read_inputs(row.inputs or "", row.inputs_sha256 or "")
    assert replay(stored, recorded_of(row)).matches
