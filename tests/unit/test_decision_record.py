"""The durable decision record (SPC-192, evaluation F-01): what one finished evaluation recommended, by every rule.

A record holds when, who, the scenario's name, the rule used and its pick, the picks of all three rules taken with
the engine's own find_robust_response on the result's matrix, the code version and every input hash from the
result's provenance, the turns and the keep-out distance; since SPC-194 the deployment's primary rule and whether the
rule used differed, and since SPC-193 (F-02) the evaluation's canonical inputs and their SHA-256. The table is
portable across SQLite and PostgreSQL: only generic column types.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from spectre.domain.decision import (
    EXPECTED_VALUE_UNEARNED,
    ActionType,
    AdversaryAction,
    FriendlyResponse,
    Scenario,
    ScenarioResult,
    SelectorStrategy,
    evaluate_scenario,
    find_robust_response,
)
from spectre.domain.decision_inputs import read_inputs, store_inputs
from spectre.domain.decision_tree import GameTree
from spectre.domain.tree_selectors import select
from spectre.web.decision_record import RULES, Operator, listed, new_record, rule_picks
from spectre.web.models import DecisionRecord
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import COPLANAR_LEO
from tests.unit.test_tree_selectors import _tree

_EPOCH = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
#: Composite scores, rows by responses, under which the three rules pick three different responses:
#: minimax R2 (worst cases 0.9, 0.5, 0.55), minimin R1 (best cases 0.1, 0.5, 0.35) and expected value at P 0.5
#: each R3 (0.5, 0.5, 0.45).
_SCORES = ((0.9, 0.5, 0.55), (0.1, 0.5, 0.35))


def _scenario(name: str = "Approach on BLUE-1", turns: int = 1) -> Scenario:
    return Scenario(
        name=name, epoch_utc=_EPOCH,
        adversary_actions=[
            AdversaryAction("A1", "Approach", ActionType.MANOEUVRE, 0.5, 0.7),
            AdversaryAction("A2", "Hold course", ActionType.NO_ACTION, 0.5, 0.7),
        ],
        friendly_responses=[
            FriendlyResponse("R1", "Hold", ActionType.NO_ACTION, 0.0, 1.0, 0.0),
            FriendlyResponse("R2", "Avoid", ActionType.MANOEUVRE, 0.3, 0.8, 2.0),
            FriendlyResponse("R3", "Retask", ActionType.SENSOR_RETASK, 0.1, 0.9, 1.0),
        ],
        horizon_hours=24.0, keep_out_km=12.5, turns=turns,
    )


@pytest.fixture(scope="module")
def disagreeing() -> ScenarioResult:
    """A real result with its matrix's scores set so the three rules disagree."""
    result = evaluate_scenario(_scenario())
    matrix = [
        [dataclasses.replace(cell, composite_score=score) for cell, score in zip(row, scores, strict=True)]
        for row, scores in zip(result.outcome_matrix, _SCORES, strict=True)
    ]
    return dataclasses.replace(result, outcome_matrix=matrix, robust_best_response=result.scenario.friendly_responses[1])


class TestThePicksOfAllThreeRules:
    def test_each_is_find_robust_responses_own_pick(self, disagreeing: ScenarioResult) -> None:
        picks = rule_picks(disagreeing)
        assert set(picks) == set(SelectorStrategy)
        for rule in SelectorStrategy:
            assert picks[rule] == find_robust_response(disagreeing.scenario, disagreeing.outcome_matrix, rule)

    def test_they_disagree_here_so_a_swapped_rule_would_show(self, disagreeing: ScenarioResult) -> None:
        picks = rule_picks(disagreeing)
        assert [picks[rule].id for rule in RULES] == ["R2", "R1", "R3"]

    def test_reading_them_changes_no_figure(self, disagreeing: ScenarioResult) -> None:
        before = [[cell.composite_score for cell in row] for row in disagreeing.outcome_matrix]
        rule_picks(disagreeing)
        assert [[cell.composite_score for cell in row] for row in disagreeing.outcome_matrix] == before
        assert disagreeing.robust_best_response.id == "R2"


class TestTheRecordOfOneEvaluation:
    def test_it_holds_who_when_what_and_by_which_rule(self, disagreeing: ScenarioResult) -> None:
        at = datetime(2026, 11, 10, 9, 5, tzinfo=UTC)
        row = new_record(disagreeing, Operator(7, "alice"), at)
        assert (row.user_id, row.username, row.created_at) == (7, "alice", at)
        assert row.scenario_name == "Approach on BLUE-1"
        assert row.rule == "minimax"
        assert (row.recommended_id, row.recommended_name) == ("R2", "Avoid")
        assert (row.minimax_id, row.minimax_name) == ("R2", "Avoid")
        assert (row.minimin_id, row.minimin_name) == ("R1", "Hold")
        assert (row.expected_value_id, row.expected_value_name) == ("R3", "Retask")
        assert (row.turns, row.keep_out_km) == (1, 12.5)

    def test_it_holds_the_code_version_and_every_input_hash(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH)
        provenance = disagreeing.provenance
        assert provenance is not None
        assert row.code_version == provenance.code_version
        assert row.calibration_source == provenance.calibration_source
        hashes = json.loads(row.input_hashes)
        assert [(h["label"], h["sha256"]) for h in hashes] == [(i.label, i.sha256) for i in provenance.inputs]
        assert len(hashes) >= 1

    def test_it_lists_the_responses_the_operator_may_choose_from(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH)
        assert json.loads(row.responses) == [
            {"id": "R1", "name": "Hold"}, {"id": "R2", "name": "Avoid"}, {"id": "R3", "name": "Retask"},
        ]

    def test_it_holds_no_decision_until_the_operator_makes_one(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH)
        assert (row.decision, row.decision_name, row.rationale, row.decided_at) == (None, None, None, None)

    def test_it_holds_the_canonical_inputs_with_their_hash(self) -> None:
        """SPC-193 reverses 0.27.0's "no element-set text": a bound result's record keeps both element sets in its
        stored inputs, beside their hashes, so the recommendation can be replayed from the record alone."""
        result = evaluate_scenario(_scenario())
        result = dataclasses.replace(result, scenario=dataclasses.replace(result.scenario, binding=cases.binding()))
        row = new_record(result, Operator(7, "alice"), _EPOCH)
        assert (row.inputs, row.inputs_sha256) == store_inputs(result)
        assert row.inputs is not None
        for tle in (COPLANAR_LEO.red_tle, COPLANAR_LEO.blue_tle):
            assert json.dumps(tle) in row.inputs
        stored = read_inputs(row.inputs, row.inputs_sha256 or "")
        assert stored.scenario == result.scenario
        assert stored.rule is result.robust_strategy

    def test_the_inputs_columns_hold_any_length_on_both_databases(self) -> None:
        compiled = {
            name: DecisionRecord.__table__.columns[name].type.compile(dialect=postgresql.dialect())
            for name in ("inputs", "inputs_sha256")
        }
        assert compiled == {"inputs": "TEXT", "inputs_sha256": "VARCHAR(64)"}

    def test_a_result_with_no_provenance_records_none(self) -> None:
        result = dataclasses.replace(evaluate_scenario(_scenario()), provenance=None)
        row = new_record(result, Operator(7, "alice"), _EPOCH)
        assert (row.code_version, row.calibration_source, json.loads(row.input_hashes)) == ("", "", [])

    def test_a_tree_records_its_turns(self) -> None:
        result = evaluate_scenario(_scenario(turns=3))
        assert new_record(result, Operator(7, "alice"), _EPOCH).turns == 3


#: The generic SQLAlchemy types both SQLite and PostgreSQL carry; nothing dialect-specific, no JSON, no enum. Boolean
#: is generic: BOOLEAN on PostgreSQL, an integer 0 or 1 on SQLite (SPC-194, whether the chosen rule differed).
_PORTABLE = (Integer, String, Text, DateTime, Float, Boolean)


class TestTheTableIsPortable:
    def test_every_column_is_a_generic_type(self) -> None:
        odd = [
            f"{c.name}: {type(c.type).__name__}" for c in DecisionRecord.__table__.columns
            if type(c.type) not in _PORTABLE
        ]
        assert odd == []

    def test_every_time_is_stored_with_its_zone(self) -> None:
        for name in ("created_at", "decided_at"):
            column = DecisionRecord.__table__.columns[name]
            assert isinstance(column.type, DateTime)
            assert column.type.timezone, name

    @pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
    def test_its_ddl_compiles_on_both_databases(self, dialect: object) -> None:
        ddl = str(CreateTable(DecisionRecord.__table__).compile(dialect=dialect))  # type: ignore[arg-type]
        assert "CREATE TABLE decision_records" in ddl

    def test_free_text_has_no_length_postgres_would_refuse_and_sqlite_would_not(self) -> None:
        """A String(n) is a limit PostgreSQL enforces and SQLite ignores; operator text is Text on both."""
        names = (
            "scenario_name", "recommended_name", "rationale", "decision_name", "responses", "tree_pick_name",
            "tree_recommendation", "expected_value_caveat",
        )
        compiled = {
            name: DecisionRecord.__table__.columns[name].type.compile(dialect=postgresql.dialect()) for name in names
        }
        assert compiled == dict.fromkeys(names, "TEXT")


# ── Review of SPC-192: what a tree recommended, expected value's basis, and text PostgreSQL cannot store ──

def _tree_result(*, refused: str | None = None) -> ScenarioResult:
    """A two-turn result whose tree picks Hold (R1) for turn 1 under minimax, where the matrix picks Avoid (R2)."""
    scenario = _scenario(turns=2)
    result = dataclasses.replace(evaluate_scenario(scenario), robust_best_response=scenario.friendly_responses[1])
    if refused is not None:
        return dataclasses.replace(result, tree=GameTree(2, (), (), 0, refused, (refused,)))
    selection = select(scenario, _tree(2, 3, 2, _two_turn_cost), 2, SelectorStrategy.MINIMAX, matrix_pick=1)
    return dataclasses.replace(result, tree=GameTree(2, (), (), 2, None, (), selection))


def _two_turn_cost(path: tuple[tuple[int, int], ...]) -> float:
    """Each response's turn-1 cost is 0.1 per place in the list, and a second turn adds 0.5."""
    return 0.1 * path[0][1] + (0.5 if len(path) > 1 else 0.0)


class TestWhatATreeRecommended:
    def test_it_records_the_trees_turn_one_pick_beside_the_matrix_pick(self) -> None:
        result = _tree_result()
        assert result.tree is not None and result.tree.selection is not None
        row = new_record(result, Operator(7, "alice"), _EPOCH)
        assert (row.recommended_id, row.recommended_name) == ("R2", "Avoid")
        assert (row.tree_pick_id, row.tree_pick_name) == ("R1", "Hold")
        assert json.loads(row.tree_recommendation) == list(result.tree.selection.recommendation)
        assert any(line.startswith("Over the 2 turns, minimax picks Hold") for line in json.loads(row.tree_recommendation))

    def test_a_tree_refused_records_why_and_no_pick(self) -> None:
        row = new_record(_tree_result(refused="No tree: the rows carry no binding."), Operator(7, "alice"), _EPOCH)
        assert (row.tree_pick_id, row.tree_pick_name) == (None, None)
        assert json.loads(row.tree_recommendation) == ["No tree: the rows carry no binding."]

    def test_one_turn_records_no_tree(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH)
        assert (row.tree_pick_id, row.tree_pick_name, json.loads(row.tree_recommendation)) == (None, None, [])


class TestExpectedValuesBasis:
    def test_an_unearned_probability_is_recorded_whatever_the_rule_used(self) -> None:
        scenario = _scenario()
        untouched = dataclasses.replace(
            scenario, adversary_actions=[dataclasses.replace(a, probability_edited=False) for a in scenario.adversary_actions],
        )
        result = evaluate_scenario(untouched, SelectorStrategy.MINIMAX)
        row = new_record(result, Operator(7, "alice"), _EPOCH)
        screen = dataclasses.replace(result, robust_strategy=SelectorStrategy.EXPECTED_VALUE).objective_guidance
        assert screen is not None
        assert row.expected_value_caveat == screen
        assert row.expected_value_caveat.startswith(EXPECTED_VALUE_UNEARNED)

    def test_an_earned_probability_records_none(self, disagreeing: ScenarioResult) -> None:
        assert new_record(disagreeing, Operator(7, "alice"), _EPOCH).expected_value_caveat is None


class TestTextPostgresCannotStore:
    def test_a_nul_in_a_name_is_kept_as_the_replacement_character(self) -> None:
        """PostgreSQL's text refuses U+0000, which SQLite stores: the record keeps U+FFFD in its place on both."""
        scenario = _scenario(name="X\x00Y")
        responses = [dataclasses.replace(scenario.friendly_responses[0], id="R\x001", name="Ho\x00ld"),
                     *scenario.friendly_responses[1:]]
        result = evaluate_scenario(dataclasses.replace(scenario, friendly_responses=responses))
        row = new_record(result, Operator(7, "alice"), _EPOCH)
        stored = [str(getattr(row, c.name)) for c in DecisionRecord.__table__.columns if c.name != "inputs"]
        assert not any("\x00" in value or "\\u0000" in value for value in stored)
        # The stored inputs keep each name exactly, its U+0000 escaped as JSON writes it, which both databases take.
        assert row.inputs is not None
        assert "\x00" not in row.inputs
        assert read_inputs(row.inputs, row.inputs_sha256 or "").scenario.name == "X\x00Y"
        assert row.scenario_name == "X�Y"
        assert json.loads(row.responses)[0] == {"id": "R�1", "name": "Ho�ld"}


class TestThePrimaryRuleOnTheRecord:
    """SPC-194: the record keeps the deployment's primary rule when it ran, and whether the chosen rule differed."""

    def test_it_holds_the_primary_rule_given(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH, primary=SelectorStrategy.EXPECTED_VALUE)
        assert (row.rule, row.primary_rule, row.rule_differed) == ("minimax", "expected_value", True)

    def test_the_primary_rule_chosen_did_not_differ(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH, primary=SelectorStrategy.MINIMAX)
        assert (row.primary_rule, row.rule_differed) == ("minimax", False)

    def test_without_one_given_it_is_the_deployments_setting(
        self, disagreeing: ScenarioResult, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SPECTRE_PRIMARY_RULE", "minimin")
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH)
        assert (row.primary_rule, row.rule_differed) == ("minimin", True)

    def test_the_records_page_names_the_primary_rule_and_its_pick(self, disagreeing: ScenarioResult) -> None:
        row = new_record(disagreeing, Operator(7, "alice"), _EPOCH, primary=SelectorStrategy.MINIMIN)
        row.id = 1
        assert listed(row, Operator(7, "alice")).primary == (
            "Primary rule: minimin; the recommendation shown was its pick, Hold (R1). The rule used, minimax, differed "
            "from it."
        )
        same = new_record(disagreeing, Operator(7, "alice"), _EPOCH, primary=SelectorStrategy.MINIMAX)
        same.id = 2
        assert listed(same, Operator(7, "alice")).primary == (
            "Primary rule: minimax, the rule used; the recommendation shown was its pick, Avoid (R2)."
        )
        assert listed(same, Operator(7, "alice")).used == "Rule used: minimax, picking Avoid (R2)."

    def test_a_tree_record_says_the_rule_used_picks_on_the_matrix(self) -> None:
        result = _tree_result()
        row = new_record(result, Operator(7, "alice"), _EPOCH, primary=SelectorStrategy.MINIMAX)
        row.id = 3
        pick = result.robust_best_response
        assert listed(row, Operator(7, "alice")).used == (
            f"Rule used: minimax; on the one-turn matrix it picks {pick.name} ({pick.id})."
        )

    def test_with_every_row_at_p_zero_expected_value_holds_no_pick(self) -> None:
        from tests.unit.test_decision_rule_comparison import _ONE_WAY, _scored

        row = new_record(_scored(_ONE_WAY, SelectorStrategy.MINIMAX, p=0.0), Operator(7, "alice"), _EPOCH,
                         primary=SelectorStrategy.EXPECTED_VALUE)
        row.id = 4
        assert (row.expected_value_id, row.expected_value_name) == ("", "")
        shown = listed(row, Operator(7, "alice"))
        assert ("expected value", "nothing, since every row had P 0") in shown.picks
        assert shown.primary == (
            "Primary rule: expected value; it had no pick, since every row had P 0, so no recommendation was shown. "
            "The rule used, minimax, differed from it."
        )
        assert shown.used == "Rule used: minimax, picking Avoid (R2)."


class TestTheRecordAsListed:
    @pytest.mark.parametrize(("km", "shown"), [(10.0, "10"), (12.5, "12.5"), (1234.5678, "1234.5678"),
                                               (9999.9999, "9999.9999"), (0.1, "0.1")])
    def test_the_keep_out_distance_is_shown_as_entered(self, km: float, shown: str) -> None:
        result = evaluate_scenario(dataclasses.replace(_scenario(), keep_out_km=km))
        row = new_record(result, Operator(7, "alice"), _EPOCH)
        row.id = 1
        assert listed(row, Operator(7, "alice")).keep_out_km == shown
