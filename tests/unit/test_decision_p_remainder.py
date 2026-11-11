"""What P means: a probability over mutually exclusive adversary actions, the rest no adversary action (SPC-203).

Evaluation finding F-12 (High) found that expected value divided each P by the sum over the rows entered, with no
remainder and no check that P sums to 1, so a single row at P 0.1 was evaluated exactly as at P 1.0 (probe P-03b) and
the chance that none of the listed actions happens was never weighed. Now:

● the rows' P must sum to at most 1, within a rounding tolerance of 1e-9; a sum above 1 is refused with a sentence
  naming the sum and saying the rows must be mutually exclusive;
● below 1, the engine adds one row of its own, "No adversary action (remainder of P)", a no-action row carrying the
  rest of P, evaluated as any no-action row and read by every rule, the comparison, the tree and the record, and
  labelled as the engine's remainder, not the operator's row; even beside an operator's own no-action row;
● at exactly 1, nothing is added;
● the share of expected value each row takes is P itself, and is shown beside it;
● a record written by 0.28.0 or 0.29.0 still reads and replays as it was evaluated then, and the replay says so.

Every expected score and pick below is re-derived from the matrix's own cells, never pasted from an output.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from spectre.domain.decision import (
    P_SUM_TOLERANCE,
    REMAINDER_ID,
    REMAINDER_NAME,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    ProbabilityRule,
    Scenario,
    SelectorStrategy,
    evaluate_scenario,
    expected_scores,
    joint_points,
    p_sum_problem,
    p_sum_refusal,
    row_cap,
    row_shares,
    with_remainder,
    without_remainder,
)
from spectre.domain.decision_inputs import (
    VERSION,
    VERSIONS,
    InputsRefusedError,
    canonical_json,
    read_inputs,
    sha256_of,
    store_inputs,
)
from spectre.domain.decision_replay import LEGACY_SHARES, said_first
from spectre.domain.decision_tree import evaluate_tree
from spectre.domain.rule_comparison import compare_rules, matrix_picks
from spectre.web.decision_record import replay_record, stored_of
from spectre.web.models import DecisionRecord
from spectre.web.tree_view import tree_view
from tests.unit._decision_reference import EPOCH
from tests.unit.test_decision_prior_interval import _both_applied as both_applied
from tests.unit.test_decision_prior_interval import _evaluated
from tests.unit.test_decision_prior_interval import _prior as notso_prior
from tests.unit.test_decision_prior_interval import _result as interval_result
from tests.unit.test_decision_tree_select import _still

EV, MINIMAX, MINIMIN = SelectorStrategy.EXPECTED_VALUE, SelectorStrategy.MINIMAX, SelectorStrategy.MINIMIN
#: Three decision records exactly as SPECTRE 0.29.0 wrote them, schema version 2, each under expected value: rows
#: whose P sum to 1.8, one row at P 0.1, and a two-turn tree whose P sum to 1.3. Written by that release's own
#: new_record at ca9f4d0.
_V2 = Path(__file__).with_name("_decision_records_0_29_0.json")


def _row(p: float, kind: ActionType = ActionType.MANOEUVRE, row_id: str = "A1", name: str = "Approach") -> AdversaryAction:
    return AdversaryAction(row_id, name, kind, p, 0.5)


def _responses() -> list[FriendlyResponse]:
    return [FriendlyResponse("F0", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
            FriendlyResponse("F1", "Avoid", ActionType.MANOEUVRE, 0.1, 0.8, 2.0)]


def _scenario(*rows: AdversaryAction, **fields: Any) -> Scenario:
    return Scenario(name="P", epoch_utc=EPOCH, adversary_actions=list(rows), friendly_responses=_responses(), **fields)


def _scores(result: Any) -> list[list[float]]:
    return [[cell.composite_score for cell in row] for row in result.outcome_matrix]


def _v2_records() -> dict[str, DecisionRecord]:
    found = json.loads(_V2.read_text(encoding="utf-8"))
    return {
        name: DecisionRecord(**{**columns, "id": n, "created_at": datetime.fromisoformat(columns["created_at"])})
        for n, (name, columns) in enumerate(sorted(found.items()), start=1)
    }


class TestProbeP03bInverted:
    def test_one_row_at_p_0_1_and_at_p_1_give_different_expected_scores(self) -> None:
        low, high = (evaluate_scenario(_scenario(_row(p)), EV) for p in (0.1, 1.0))
        assert expected_scores(low.scenario, low.outcome_matrix) != expected_scores(high.scenario, high.outcome_matrix)

    def test_at_p_0_1_the_remainder_weighs_the_other_0_9(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1)), EV)
        s = _scores(result)
        derived = tuple(0.1 * s[0][j] + 0.9 * s[1][j] for j in range(2))
        assert expected_scores(result.scenario, result.outcome_matrix) == pytest.approx(derived, rel=1e-12)

    def test_at_p_1_the_row_alone_is_weighed(self) -> None:
        result = evaluate_scenario(_scenario(_row(1.0)), EV)
        assert len(result.outcome_matrix) == 1
        assert expected_scores(result.scenario, result.outcome_matrix) == tuple(_scores(result)[0])

    def test_the_pick_follows_what_p_says(self) -> None:
        """Against the manoeuvre Avoid scores below Hold; against no action Hold scores below Avoid. At P 1.0 the
        manoeuvre is certain and Avoid is the pick; at P 0.1 the remainder's 0.9 outweighs it and Hold is."""
        low, high = (evaluate_scenario(_scenario(_row(p)), EV) for p in (0.1, 1.0))
        s = _scores(low)
        assert s[0][1] < s[0][0] and s[1][0] < s[1][1]
        assert 0.1 * s[0][0] + 0.9 * s[1][0] < 0.1 * s[0][1] + 0.9 * s[1][1]
        assert (low.robust_best_response.id, high.robust_best_response.id) == ("F0", "F1")


class TestTheRemainderRow:
    def test_below_1_one_row_of_the_engines_is_added_last(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1), _row(0.2, ActionType.SENSOR_RETASK, "A2", "Retask")))
        rows = result.scenario.adversary_actions
        assert [a.id for a in rows] == ["A1", "A2", REMAINDER_ID]
        last = rows[-1]
        assert (last.name, last.action_type, last.remainder) == (REMAINDER_NAME, ActionType.NO_ACTION, True)
        assert REMAINDER_NAME == "No adversary action (remainder of P)"
        assert last.probability == pytest.approx(0.7, abs=1e-15)
        assert (len(result.outcome_matrix), len(result.ranked_per_adversary)) == (3, 3)

    def test_it_is_labelled_as_the_engines_remainder_not_the_operators_row(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.25)))
        source = result.row_sources[-1]
        assert "the engine's remainder, not your row" in source
        assert "1 less the sum of your rows' P, 0.25" in source

    def test_beside_an_operators_own_no_action_row_it_is_still_its_own_row(self) -> None:
        """The operator's no-action row is one listed action at the P they gave it; the remainder is the chance that
        none of the listed actions happens, so it is weighed apart from it, though its cells are alike."""
        result = evaluate_scenario(_scenario(_row(0.3), _row(0.2, ActionType.NO_ACTION, "A2", "Stay")))
        rows = result.scenario.adversary_actions
        assert [(a.action_type, a.remainder) for a in rows] == [
            (ActionType.MANOEUVRE, False), (ActionType.NO_ACTION, False), (ActionType.NO_ACTION, True),
        ]
        assert _scores(result)[2] == _scores(result)[1]
        assert [a.probability for a in rows] == pytest.approx([0.3, 0.2, 0.5], abs=1e-15)

    @pytest.mark.parametrize("ps", [(0.3, 0.7), (0.1, 0.2, 0.7), (1.0,), (0.5, 0.5 + P_SUM_TOLERANCE / 2)],
                             ids=["0.3 and 0.7", "0.1, 0.2 and 0.7 in floating point", "one row at 1",
                                  "within the tolerance above"])
    def test_at_exactly_1_nothing_is_added(self, ps: tuple[float, ...]) -> None:
        kinds = (ActionType.MANOEUVRE, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE)
        scenario = _scenario(*(_row(p, kinds[i], f"A{i}", f"Row {i}") for i, p in enumerate(ps)))
        result = evaluate_scenario(scenario, EV)
        assert not any(a.remainder for a in result.scenario.adversary_actions)
        assert len(result.outcome_matrix) == len(ps)
        assert with_remainder(scenario) is scenario

    def test_the_operators_scenario_is_left_as_it_was(self) -> None:
        scenario = _scenario(_row(0.1))
        before = list(scenario.adversary_actions)
        evaluate_scenario(scenario)
        assert scenario.adversary_actions == before

    def test_adding_it_twice_adds_one_row(self) -> None:
        once = with_remainder(_scenario(_row(0.1)))
        assert with_remainder(once) == once
        assert [a.id for a in with_remainder(once).adversary_actions] == ["A1", REMAINDER_ID]

    def test_the_shares_used_are_p_and_sum_to_1(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1), _row(0.2, ActionType.SENSOR_RETASK, "A2", "Retask")))
        assert result.row_shares == tuple(a.probability for a in result.scenario.adversary_actions)
        assert sum(result.row_shares) == pytest.approx(1.0, abs=1e-15)

    def test_a_scenario_holding_a_remainder_that_does_not_match_its_rows_is_refused(self) -> None:
        held = with_remainder(_scenario(_row(0.1)))
        rows = [held.adversary_actions[0], dataclasses.replace(held.adversary_actions[1], probability=0.5)]
        with pytest.raises(ValueError, match="remainder"):
            dataclasses.replace(held, adversary_actions=rows)


class TestEveryRuleWeighsIt:
    @pytest.mark.parametrize("rule", [MINIMAX, MINIMIN, EV], ids=lambda r: r.value)
    def test_each_rule_picks_over_the_rows_and_the_remainder(self, rule: SelectorStrategy) -> None:
        result = evaluate_scenario(_scenario(_row(0.1)), rule)
        s = _scores(result)
        columns = [[row[j] for row in s] for j in range(2)]
        hand = {
            MINIMAX: min(range(2), key=lambda j: max(columns[j])),
            MINIMIN: min(range(2), key=lambda j: min(columns[j])),
            EV: min(range(2), key=lambda j: 0.1 * columns[j][0] + 0.9 * columns[j][1]),
        }
        assert result.robust_best_response is result.scenario.friendly_responses[hand[rule]]

    def test_minimin_is_moved_by_the_remainder(self) -> None:
        """Read on the manoeuvre row alone, Avoid's best case is the least; with the remainder, Hold's against no
        action is, so minimin picks Hold."""
        result = evaluate_scenario(_scenario(_row(0.1)), MINIMIN)
        s = _scores(result)
        assert s[0][1] < s[0][0]
        assert min(s[0][0], s[1][0]) < min(s[0][1], s[1][1])
        assert result.robust_best_response.id == "F0"

    def test_the_side_by_side_comparison_reads_it(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1)), MINIMAX)
        picks = matrix_picks(result)
        assert (picks[MINIMAX].id, picks[MINIMIN].id, picks[EV].id) == ("F1", "F0", "F0")
        assert compare_rules(result, MINIMAX).line == (
            "The rules disagree: minimax picks Avoid (F1); minimin and expected value pick Hold (F0)."
        )

    def test_every_row_at_p_0_leaves_the_whole_weight_on_the_remainder(self) -> None:
        """No row at P 0 is weightless any more: the remainder carries P 1, so expected value picks the best response
        against no adversary action."""
        result = evaluate_scenario(_scenario(_row(0.0)), EV)
        s = _scores(result)
        assert result.scenario.adversary_actions[-1].probability == 1.0
        best = min(range(2), key=lambda j: s[1][j])
        assert matrix_picks(result)[EV] is result.scenario.friendly_responses[best]


@pytest.fixture(scope="module")
def tree_result() -> Any:
    """coplanar_leo's two still rows at P 0.2 and 0.3, a two-turn tree under expected value: the remainder is 0.5."""
    rows = [dataclasses.replace(a, probability=p) for a, p in zip(_still().adversary_actions, (0.2, 0.3), strict=True)]
    return evaluate_tree(dataclasses.replace(_still(), adversary_actions=rows), EV)


class TestTheTree:
    def test_the_remainder_is_one_of_reds_moves_in_every_turn(self, tree_result: Any) -> None:
        tree = tree_result.tree
        assert tree is not None and tree.refusal is None, tree.refusal
        assert {node.action for node in tree.roots} == {0, 1, 2}
        assert {child.action for node in tree.roots for child in node.children} == {0, 1, 2}
        assert tree_result.scenario.adversary_actions[2].name == REMAINDER_NAME

    def test_its_picks_and_update_weigh_the_remainder(self, tree_result: Any) -> None:
        selection = tree_result.tree.selection
        assert selection is not None
        assert len(selection.likelihood) == 3
        assert any(REMAINDER_NAME in line for line in selection.update)

    def test_its_header_counts_the_remainder_as_a_row(self, tree_result: Any) -> None:
        assert ": 3 red moves and 2 responses each turn" in tree_result.tree.lines[0]

    def test_each_of_its_branches_is_labelled_as_the_engines_remainder(self, tree_result: Any) -> None:
        view = tree_view(tree_result)
        assert view is not None
        headings = [node.heading for root in view.nodes for node in (root, *root.children)]
        remainder = [h for h in headings if REMAINDER_NAME in h]
        assert remainder
        assert all(f"red {REMAINDER_NAME}, our " in h for h in remainder)
        labelled = [node.remainder for root in view.nodes for node in (root, *root.children)
                    if REMAINDER_NAME in node.heading]
        assert set(labelled) == {"(red's move here is the engine's remainder, not your row)"}


class TestASumAbove1IsRefused:
    def test_the_scenario_refuses_it_naming_the_sum(self) -> None:
        rows = [_row(0.5, kind, f"A{i}", f"Row {i}") for i, kind in enumerate(
            (ActionType.MANOEUVRE, ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE))]
        with pytest.raises(ValueError, match=r"sum to 1\.5, above 1.*mutually exclusive"):
            _scenario(*rows)

    def test_just_above_the_tolerance_is_refused(self) -> None:
        with pytest.raises(ValueError, match="above 1"):
            _scenario(_row(0.5), _row(0.5 + 2 * P_SUM_TOLERANCE, ActionType.SENSOR_RETASK, "A2", "Retask"))

    def test_the_sentence_names_the_sum_and_why(self) -> None:
        assert p_sum_refusal(1.5) == (
            "Your rows' P sum to 1.5, above 1. P is the chance of each adversary action, and the rows must be "
            "mutually exclusive, so their P sum to at most 1; the engine weighs the rest as no adversary action. "
            "Lower the P of one or more rows."
        )

    @pytest.mark.parametrize(("rows", "named"), [
        ((0,), "With the NOTSO suggestion applied to row 1, your rows' P sum to 1.02, above 1."),
        ((0, 2), "With the NOTSO suggestions applied to rows 1 and 3, your rows' P sum to 1.02, above 1."),
        ((0, 1, 3), "With the NOTSO suggestions applied to rows 1, 2 and 4, your rows' P sum to 1.02, above 1."),
    ], ids=["one row", "two rows", "three rows"])
    def test_with_suggestions_applied_it_names_the_rows_that_carry_them(
        self, rows: tuple[int, ...], named: str,
    ) -> None:
        assert p_sum_refusal(1.02, rows).startswith(named)

    def test_a_sum_is_said_without_floating_point_noise(self) -> None:
        assert "sum to 1.2, above 1" in p_sum_refusal(0.6 + 0.3 + 0.3)
        assert "sum to 1.000000002, above 1" in p_sum_refusal(1.000000002)

    def test_under_the_0_29_0_rule_a_sum_above_1_is_still_taken(self) -> None:
        scenario = _scenario(_row(0.9), _row(0.9, ActionType.SENSOR_RETASK, "A2", "Retask"),
                             probability_rule=ProbabilityRule.SHARES)
        result = evaluate_scenario(scenario, EV)
        assert len(result.outcome_matrix) == 2
        assert result.row_shares == (0.5, 0.5)


class TestTheStoredInputs:
    def test_this_code_writes_version_3_and_reads_every_earlier_one(self) -> None:
        assert (VERSION, VERSIONS) == (3, (1, 2, 3))
        document = json.loads(store_inputs(evaluate_scenario(_scenario(_row(0.1))))[0])
        assert document["version"] == 3
        assert document["scenario"]["probability_rule"] == "remainder"

    def test_the_remainder_is_stored_beside_the_rows_not_as_one_of_them(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1)), EV)
        document = json.loads(store_inputs(result)[0])
        assert [a["id"] for a in document["scenario"]["adversary_actions"]] == ["A1"]
        assert all("remainder" not in a for a in document["scenario"]["adversary_actions"])
        assert document["remainder"] == {"id": REMAINDER_ID, "name": REMAINDER_NAME, "probability": 0.9}
        assert document["scores"] == _scores(result)

    def test_it_reads_back_the_operators_scenario_and_every_score(self) -> None:
        scenario = _scenario(_row(0.1))
        result = evaluate_scenario(scenario, EV)
        stored = read_inputs(*store_inputs(result))
        assert stored.scenario == scenario
        assert [list(row) for row in stored.scores] == _scores(result)

    def test_at_exactly_1_no_remainder_is_stored(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(_scenario(_row(1.0))))[0])
        assert document["remainder"] is None

    @pytest.mark.parametrize("remainder", [
        None, {"id": REMAINDER_ID, "name": REMAINDER_NAME, "probability": 0.8},
        {"id": REMAINDER_ID, "name": "Something else", "probability": 0.9},
    ], ids=["dropped", "another P", "another name"])
    def test_a_remainder_that_is_not_the_rows_own_is_refused(self, remainder: Any) -> None:
        document = json.loads(store_inputs(evaluate_scenario(_scenario(_row(0.1))))[0])
        text = canonical_json({**document, "remainder": remainder})
        with pytest.raises(InputsRefusedError, match="refused at remainder"):
            read_inputs(text, sha256_of(text))

    def test_a_version_3_document_whose_p_sum_above_1_is_refused(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(_scenario(_row(1.0))))[0])
        document["scenario"]["adversary_actions"].append(
            {**document["scenario"]["adversary_actions"][0], "id": "A2", "action_type": "sensor_retask"})
        document["scores"].append(document["scores"][0])
        text = canonical_json(document)
        with pytest.raises(InputsRefusedError, match="above 1"):
            read_inputs(text, sha256_of(text))

    def test_a_result_under_the_0_29_0_rule_is_never_stored_again(self) -> None:
        """Only a replay of a 0.28.0 or 0.29.0 record evaluates under that rule, and a replay writes no record:
        version 3 holds the remainder rule alone, so a version 3 record is never read as one evaluated before."""
        scenario = _scenario(_row(0.9), _row(0.9, ActionType.SENSOR_RETASK, "A2", "Retask"),
                             probability_rule=ProbabilityRule.SHARES)
        with pytest.raises(ValueError, match="never stored"):
            store_inputs(evaluate_scenario(scenario))

    def test_a_version_3_document_under_the_0_29_0_rule_is_refused(self) -> None:
        """A version 3 document rewritten to the 0.29.0 rule, its remainder and the remainder's scores taken out and
        its P raised to sum to 1.8, rehashed: refused, so its replay can never say it was evaluated before SPC-203."""
        document = json.loads(store_inputs(evaluate_scenario(_scenario(_row(0.1))))[0])
        document["scenario"]["probability_rule"] = "shares"
        document["scenario"]["adversary_actions"][0]["probability"] = 1.0
        document["scenario"]["adversary_actions"].append(
            {**document["scenario"]["adversary_actions"][0], "id": "A2", "action_type": "sensor_retask",
             "probability": 0.8})
        document["remainder"] = None
        text = canonical_json(document)
        with pytest.raises(InputsRefusedError, match=r"refused at scenario\.probability_rule: version 3 holds"):
            read_inputs(text, sha256_of(text))

    @pytest.mark.parametrize("version", [4, 0, "2"], ids=["a later one", "0", "text"])
    def test_an_old_shaped_document_of_an_unknown_version_is_refused_as_that_version(self, version: Any) -> None:
        """A version 2 document whose version is changed and rehashed is named for its version, not for a field
        version 3 would hold."""
        document = json.loads(_v2_records()["under_one"].inputs or "")
        text = canonical_json({**document, "version": version})
        with pytest.raises(InputsRefusedError, match=rf"version {version!r} is not one this code reads"):
            read_inputs(text, sha256_of(text))


class TestARecordWrittenBy0290StillReadsAndReplays:
    @pytest.mark.parametrize("name", ["over_one", "tree_over_one", "under_one"])
    def test_it_reads_under_the_rule_it_was_evaluated_under(self, name: str) -> None:
        row = _v2_records()[name]
        assert json.loads(row.inputs or "")["version"] == 2
        assert stored_of(row).scenario.probability_rule is ProbabilityRule.SHARES

    @pytest.mark.parametrize("name", ["over_one", "tree_over_one", "under_one"])
    def test_it_replays_exactly_and_says_how(self, name: str) -> None:
        done = replay_record(_v2_records()[name])
        assert done.matches, done.lines
        assert LEGACY_SHARES in done.preamble

    def test_the_replay_command_says_so_before_it_evaluates(self) -> None:
        """scripts/replay_decision.py says said_first's lines before it replays; a record of this code's says no such
        thing."""
        assert LEGACY_SHARES in said_first(stored_of(_v2_records()["over_one"]), "0.30.0")
        fresh = read_inputs(*store_inputs(evaluate_scenario(_scenario(_row(0.1)))))
        assert LEGACY_SHARES not in said_first(fresh, "0.30.0")

    def test_its_sum_above_1_is_read_as_it_was_evaluated(self) -> None:
        stored = stored_of(_v2_records()["over_one"])
        assert sum(a.probability for a in stored.scenario.adversary_actions) == pytest.approx(1.8)

    def test_under_this_codes_rule_its_expected_value_pick_would_differ(self) -> None:
        """The record at P 0.1 was evaluated with that row weighed as certain, so Avoid; with the remainder weighed,
        Hold. The replay reproduces Avoid, the pick the operator was shown."""
        row = _v2_records()["under_one"]
        stored = stored_of(row)
        now = evaluate_scenario(dataclasses.replace(stored.scenario, probability_rule=ProbabilityRule.REMAINDER), EV)
        assert (row.expected_value_id, matrix_picks(now)[EV].id) == ("F1", "F0")

    def test_its_scenario_hashes_as_0290_hashed_it(self) -> None:
        row = _v2_records()["over_one"]
        stored = stored_of(row)
        result = evaluate_scenario(stored.scenario, stored.rule)
        assert result.provenance is not None
        assert result.provenance.inputs[0].sha256 == json.loads(row.input_hashes)[0]["sha256"]

    def test_a_0280_record_says_so_too(self) -> None:
        found = json.loads(Path(__file__).with_name("_decision_records_0_28_0.json").read_text(encoding="utf-8"))
        columns = found["lookup"]
        row = DecisionRecord(**{**columns, "id": 1, "created_at": datetime.fromisoformat(columns["created_at"])})
        done = replay_record(row)
        assert done.matches, done.lines
        assert LEGACY_SHARES in done.preamble


def test_the_records_were_written_at_the_stated_time() -> None:
    """The fixture is what 0.29.0 wrote, not something this code made: its code version and time say so."""
    for row in _v2_records().values():
        assert row.code_version == "0.29.0"
        assert row.created_at == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _rounded(points: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    return [tuple(round(x, 9) for x in point) for point in points]


def _legacy_interval_result() -> Any:
    """test_decision_prior_interval's result, rows 1 and 2 at 0.13 and 0.6, under the 0.29.0 rule: no remainder."""
    result = interval_result([[0.9, 0.2], [0.1, 0.3]])
    rows = [a for a in result.scenario.adversary_actions if not a.remainder]
    legacy = dataclasses.replace(result.scenario, adversary_actions=rows, probability_rule=ProbabilityRule.SHARES)
    return _evaluated(legacy, [[0.9, 0.2], [0.1, 0.3]], EV)


class TestTheNotsoIntervalWithTheRemainder:
    """A NOTSO P moved across its interval moves the remainder the other way, and is checked no higher than the rows'
    P can sum to 1; with the rows' P at 1 no remainder row was evaluated, so nothing else is checked."""

    def test_an_interval_past_where_the_rows_reach_1_is_checked_to_there(self) -> None:
        """Row 2 at 0.8 leaves row 1 at most 0.2. With the remainder at 0.5 a response: Evade 0.18 + 0.4p against
        Watch 0.34 - 0.3p, equal at p 0.229, past 0.2, so Evade holds where P may go; unchecked, it would not."""
        (line,) = interval_result([[0.9, 0.2], [0.1, 0.3]], other_p=0.8).interval_lines
        assert line == (
            "Row 1, Approach: expected value recommends Evade at every P across its NOTSO interval, 0.04 to 0.30, "
            "checked to P 0.20, past which the rows' P would sum above 1, which is refused, with the other rows held "
            "at their P and the remainder of P taking up the difference."
        )

    def test_at_a_sum_of_1_neither_one_row_nor_the_rows_together_are_checked(self) -> None:
        alone = interval_result([[0.9, 0.2], [0.1, 0.3]], other_p=0.87)
        assert not alone.scenario.adversary_actions[-1].remainder
        (line,) = alone.interval_lines
        assert line == (
            "Row 1, Approach: expected value's pick is not checked across its NOTSO interval, 0.04 to 0.30: your "
            "rows' P sum to 1, so a higher P for this row would sum above 1, which is refused, and a lower one would "
            "leave a remainder of P, whose row this evaluation did not evaluate, since your rows left none. With your "
            "rows' P summing below 1 the remainder row is evaluated, and this interval is checked."
        )
        together = both_applied(interval_result([[0.9, 0.2], [0.1, 0.3]]), notso_prior(0.5), notso_prior(0.5))
        assert together.interval_lines[-1] == (
            "Moved together across their NOTSO intervals, rows 1 and 2's P are not checked: your rows' P sum to 1, so "
            "any lower sum would leave a remainder of P, whose row this evaluation did not evaluate, since your rows "
            "left none. With your rows' P summing below 1 the remainder row is evaluated, and they are checked."
        )

    def test_rows_moved_together_are_checked_at_the_corners_the_sum_of_1_cuts(self) -> None:
        """Rows 1 and 2 in 0.04 to 0.30 beside a row at 0.6 may sum to 0.4 at most: the box's corner at 0.30 and 0.30
        is refused, and the points on its edges where the sum reaches 0.4 stand in for it. Beside a row at 0.7 they
        may sum to 0.3: three corners are refused, and only the edges from the low corner reach the sum."""
        result = both_applied(interval_result([[0.9, 0.2], [0.1, 0.3]]), notso_prior(), notso_prior())
        third = AdversaryAction("A3", "Drift", ActionType.SENSOR_RETASK, 0.6, 0.7)
        rows = [*result.scenario.adversary_actions[:2], third]
        scenario = with_remainder(dataclasses.replace(result.scenario, adversary_actions=rows))
        points = _rounded(joint_points(scenario, {0: (0.04, 0.30), 1: (0.04, 0.30)}))
        assert points == [(0.04, 0.04), (0.04, 0.30), (0.30, 0.04), (0.10, 0.30), (0.30, 0.10)]
        tighter = [*rows[:2], dataclasses.replace(third, probability=0.7)]
        scenario = with_remainder(dataclasses.replace(result.scenario, adversary_actions=tighter))
        assert _rounded(joint_points(scenario, {0: (0.04, 0.30), 1: (0.04, 0.30)})) == [
            (0.04, 0.04), (0.04, 0.26), (0.26, 0.04),
        ]

    def test_under_the_0_29_0_rule_the_box_is_whole_and_nothing_takes_up_a_move(self) -> None:
        legacy = _legacy_interval_result()
        assert row_cap(legacy.scenario, 0) is None
        assert joint_points(legacy.scenario, {0: (0.04, 0.30), 1: (0.04, 0.30)}) == [
            (0.04, 0.04), (0.04, 0.30), (0.30, 0.04), (0.30, 0.30),
        ]
        (alone,) = legacy.interval_lines
        assert alone.endswith("with the other rows held at their P.")
        both = both_applied(legacy, notso_prior(), notso_prior())
        assert both.interval_lines[-1].endswith((" throughout.", "."))
        assert "remainder" not in both.interval_lines[-1]
        third = AdversaryAction("A3", "Drift", ActionType.SENSOR_RETASK, 0.6, 0.7)
        three = dataclasses.replace(both.scenario, adversary_actions=[*both.scenario.adversary_actions, third])
        held = _evaluated(three, [[0.9, 0.2], [0.1, 0.3], [0.5, 0.5]], EV)
        assert held.interval_lines[-1].endswith(", with the other rows held at their P.")


class TestTheGuards:
    def test_rows_that_leave_a_remainder_they_do_not_hold_have_no_shares(self) -> None:
        scenario = _scenario(_row(0.1))
        with pytest.raises(ValueError, match="no row weighs"):
            row_shares(scenario)
        with pytest.raises(ValueError, match="no row weighs"):
            expected_scores(scenario, evaluate_scenario(_scenario(_row(1.0))).outcome_matrix)

    def test_a_matrix_of_another_shape_is_refused(self) -> None:
        result = evaluate_scenario(_scenario(_row(0.1)))
        with pytest.raises(ValueError, match="holds 1 rows and the scenario 2"):
            expected_scores(result.scenario, result.outcome_matrix[:1])

    def test_a_response_not_permitted_has_no_expected_score(self) -> None:
        vetoed = [_responses()[0], dataclasses.replace(_responses()[1], vetoed=True, veto_reason="ROE 4.")]
        result = evaluate_scenario(dataclasses.replace(_scenario(_row(0.1)), friendly_responses=vetoed), EV)
        assert expected_scores(result.scenario, result.outcome_matrix)[1] is None

    @pytest.mark.parametrize("change", [
        {"id": "A9"}, {"name": "Mine"}, {"action_type": ActionType.MANOEUVRE},
    ], ids=["another id", "another name", "another action"])
    def test_a_remainder_row_is_only_the_engines(self, change: dict[str, Any]) -> None:
        row = with_remainder(_scenario(_row(0.1))).adversary_actions[-1]
        with pytest.raises(ValueError, match="the remainder row is the engine's"):
            dataclasses.replace(row, **change)

    def test_the_0_29_0_rule_holds_no_remainder_row(self) -> None:
        held = with_remainder(_scenario(_row(0.1)))
        with pytest.raises(ValueError, match="holds no remainder row"):
            dataclasses.replace(held, probability_rule=ProbabilityRule.SHARES)

    def test_a_remainder_row_held_anywhere_but_last_is_refused(self) -> None:
        held = with_remainder(_scenario(_row(0.1)))
        with pytest.raises(ValueError, match="once, last"):
            dataclasses.replace(held, adversary_actions=held.adversary_actions[::-1])

    def test_a_scenario_with_no_rows_takes_no_remainder(self) -> None:
        empty = _scenario()
        assert with_remainder(empty) is empty
        assert without_remainder(empty) is empty
        with pytest.raises(ValueError, match="at least one adversary action"):
            evaluate_scenario(empty)

    def test_a_sum_at_most_1_is_no_problem(self) -> None:
        assert p_sum_problem([_row(0.5), _row(0.5, ActionType.SENSOR_RETASK, "A2", "Retask")]) is None
        assert p_sum_problem([_row(0.7), _row(0.5, ActionType.SENSOR_RETASK, "A2", "Retask")]) == p_sum_refusal(1.2)
