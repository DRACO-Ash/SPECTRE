"""A response marked not permitted, through the stored inputs, the record and the replay (SPC-195, evaluation F-04).

The veto is part of the Scenario, so the stored inputs carry it: version 2 of the document holds each response's
veto and reason, and reads them back exactly. A record written by 0.28.0 holds version 1, with no veto; it still
reads, every response permitted, and replays to the same picks, scores and input hashes. The record keeps which
responses were vetoed and why beside each response, and never a vetoed response as a pick.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from spectre.domain.decision import Scenario, SelectorStrategy, evaluate_scenario
from spectre.domain.decision_inputs import (
    VERSION,
    InputsRefusedError,
    canonical_json,
    decode_scenario,
    encode_scenario,
    read_inputs,
    sha256_of,
    store_inputs,
)
from spectre.domain.decision_tree import evaluate_tree
from spectre.web.decision_record import Operator, new_record, replay_record, stored_of
from spectre.web.models import DecisionRecord
from tests.unit.test_decision_inputs import _lookup
from tests.unit.test_decision_tree_select import _still

_AT = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
_REASON = 'Safety: <b>"no"</b> burn within 5 km of the station – ROE 4.'
#: Three decision records exactly as SPECTRE 0.28.0 wrote them, schema version 1: a lookup scenario under minimin, a
#: computed one under minimax and a two-turn tree under expected value. Written by that release's own new_record.
_V1 = Path(__file__).with_name("_decision_records_0_28_0.json")


def _vetoed(scenario: Scenario, *places: int, reason: str = _REASON) -> Scenario:
    responses = [
        dataclasses.replace(r, vetoed=True, veto_reason=reason) if j in places else r
        for j, r in enumerate(scenario.friendly_responses)
    ]
    return dataclasses.replace(scenario, friendly_responses=responses)


def _v1_records() -> dict[str, DecisionRecord]:
    found = json.loads(_V1.read_text(encoding="utf-8"))
    return {
        name: DecisionRecord(**{**columns, "id": n, "created_at": datetime.fromisoformat(columns["created_at"])})
        for n, (name, columns) in enumerate(sorted(found.items()), start=1)
    }


def _record(scenario: Scenario, rule: SelectorStrategy) -> DecisionRecord:
    row = new_record(evaluate_tree(scenario, rule), Operator(7, "alice"), _AT, primary=SelectorStrategy.MINIMAX)
    row.id = 1
    return DecisionRecord(**{c.name: getattr(row, c.name) for c in DecisionRecord.__table__.columns})


class TestTheStoredInputsCarryTheVeto:
    def test_this_code_writes_version_2(self) -> None:
        assert VERSION == 2
        text, _sha256 = store_inputs(evaluate_scenario(_vetoed(_lookup(), 1)))
        assert json.loads(text)["version"] == 2

    def test_each_response_holds_its_veto_and_reason(self) -> None:
        encoded = encode_scenario(_vetoed(_lookup(), 1))
        assert [(r["vetoed"], r["veto_reason"]) for r in encoded["friendly_responses"]] == [
            (False, ""), (True, _REASON), (False, ""),
        ]

    def test_a_vetoed_scenario_comes_back_equal(self) -> None:
        scenario = _vetoed(_lookup(), 0, 2)
        text, sha256 = store_inputs(evaluate_scenario(scenario))
        assert read_inputs(text, sha256).scenario == scenario
        assert decode_scenario(encode_scenario(scenario)) == scenario

    def test_a_vetoed_response_with_no_reason_is_refused_as_the_engine_refuses_it(self) -> None:
        document = encode_scenario(_vetoed(_lookup(), 1))
        document["friendly_responses"][1]["veto_reason"] = ""
        with pytest.raises(InputsRefusedError, match="not a scenario the engine takes"):
            decode_scenario(document)

    def test_a_veto_that_is_not_a_truth_value_is_refused_where_it_is(self) -> None:
        document = encode_scenario(_vetoed(_lookup(), 1))
        document["friendly_responses"][1]["vetoed"] = 1
        with pytest.raises(InputsRefusedError, match=r"friendly_responses\[1\]\.vetoed"):
            decode_scenario(document)


class TestARecordWrittenBy0280StillReadsAndReplays:
    @pytest.mark.parametrize("name", ["computed", "lookup", "tree"])
    def test_it_reads_as_version_1_with_every_response_permitted(self, name: str) -> None:
        row = _v1_records()[name]
        assert json.loads(row.inputs or "")["version"] == 1
        stored = stored_of(row)
        assert stored.scenario.friendly_responses
        assert not any(r.vetoed or r.veto_reason for r in stored.scenario.friendly_responses)

    @pytest.mark.parametrize("name", ["computed", "lookup", "tree"])
    def test_it_replays_to_the_same_picks_scores_and_input_hashes(self, name: str) -> None:
        done = replay_record(_v1_records()[name])
        assert done.matches, done.lines
        assert not any(c.what.startswith("Not permitted") for c in done.comparisons)

    def test_a_version_1_document_holding_a_veto_is_refused_where_it_is(self) -> None:
        row = _v1_records()["lookup"]
        document = json.loads(row.inputs or "")
        document["scenario"]["friendly_responses"][0] |= {"vetoed": True, "veto_reason": "added later"}
        text = canonical_json(document)
        with pytest.raises(InputsRefusedError, match=r"friendly_responses\[0\].*unknown field veto_reason, vetoed"):
            read_inputs(text, sha256_of(text))

    def test_a_version_this_code_does_not_know_is_refused_naming_both_it_knows(self) -> None:
        document: dict[str, Any] = json.loads(store_inputs(evaluate_scenario(_lookup()))[0])
        text = canonical_json({**document, "version": 3})
        with pytest.raises(InputsRefusedError, match="version 3 is not one this code reads; it knows versions 1 and 2"):
            read_inputs(text, sha256_of(text))

    def test_its_scenario_hashes_as_0280_hashed_it(self) -> None:
        """A scenario with no veto hashes as before, so a 0.28.0 record's own input hashes still match."""
        row = _v1_records()["lookup"]
        stored = stored_of(row)
        result = evaluate_scenario(stored.scenario, stored.rule)
        assert result.provenance is not None
        assert result.provenance.inputs[0].sha256 == json.loads(row.input_hashes)[0]["sha256"]

    def test_a_veto_changes_the_scenario_hash(self) -> None:
        free, vetoed = evaluate_scenario(_lookup()), evaluate_scenario(_vetoed(_lookup(), 1))
        assert free.provenance is not None and vetoed.provenance is not None
        assert free.provenance.inputs[0].sha256 != vetoed.provenance.inputs[0].sha256


class TestTheRecordOfAVetoedScenario:
    @pytest.mark.parametrize("rule", list(SelectorStrategy), ids=lambda r: r.value)
    def test_it_stores_no_vetoed_response_as_a_pick(self, rule: SelectorStrategy) -> None:
        row = _record(_vetoed(_still(), 0), rule)
        held = {row.recommended_id, row.minimax_id, row.minimin_id, row.expected_value_id, row.tree_pick_id}
        assert "F0" not in held
        assert "" not in held

    def test_it_stores_which_responses_were_vetoed_and_why(self) -> None:
        row = _record(_vetoed(_lookup(), 1), SelectorStrategy.MINIMAX)
        responses = json.loads(row.responses)
        assert responses[1] == {"id": "F4", "name": "Retask", "not_permitted": _REASON}
        assert "not_permitted" not in responses[0]
        assert [r.veto_reason for r in stored_of(row).scenario.friendly_responses] == ["", _REASON, ""]

    def test_with_every_response_vetoed_it_stores_no_pick(self) -> None:
        row = _record(_vetoed(_still(), 0, 1), SelectorStrategy.MINIMAX)
        assert (row.recommended_id, row.minimax_id, row.minimin_id, row.expected_value_id) == ("", "", "", "")
        assert row.tree_pick_id is None

    @pytest.mark.parametrize("rule", list(SelectorStrategy), ids=lambda r: r.value)
    def test_it_replays_exactly(self, rule: SelectorStrategy) -> None:
        done = replay_record(_record(_vetoed(_still(), 0), rule))
        assert done.matches, done.lines
        (check,) = [c for c in done.comparisons if c.what == "Not permitted"]
        assert check.recorded == check.replayed == f"Hold (F0): {_REASON}"

    def test_with_every_response_vetoed_it_replays_exactly(self) -> None:
        done = replay_record(_record(_vetoed(_still(), 0, 1), SelectorStrategy.EXPECTED_VALUE))
        assert done.matches, done.lines

    def test_a_veto_dropped_from_the_records_column_is_caught(self) -> None:
        row = _record(_vetoed(_lookup(), 1), SelectorStrategy.MINIMAX)
        row.responses = json.dumps([{"id": r["id"], "name": r["name"]} for r in json.loads(row.responses)])
        done = replay_record(row)
        assert not done.matches
        (check,) = [c for c in done.comparisons if c.what == "Not permitted"]
        assert (check.recorded, check.replayed) == ("none", f"Retask (F4): {_REASON}")

    def test_a_veto_in_the_records_column_that_the_stored_inputs_lack_is_caught(self) -> None:
        row = _record(_lookup(), SelectorStrategy.MINIMAX)
        responses = json.loads(row.responses)
        responses[1]["not_permitted"] = "Added after the evaluation."
        row.responses = json.dumps(responses)
        done = replay_record(row)
        assert not done.matches
        (check,) = [c for c in done.comparisons if c.what == "Not permitted"]
        assert (check.recorded, check.replayed) == ("Retask (F4): Added after the evaluation.", "none")
