"""The training-only label on the results and in the decision record (SPC-207, evaluation F-17).

A result resting on an unsourced relation of the lookup model says above its recommendation that it is for training
only, naming each relation. The record keeps the label as the results showed it, in a column of its own that init_db
adds to an older database in place, or "" for a result resting on none; the Decision records page shows it, marks it,
and says when a record holds none. The label is no input and no pick: the stored inputs are unchanged, still version
6, and a record written as 0.38.0 wrote it, with no label, replays exactly.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from spectre.domain.decision import (
    LOOKUP_RELATION_WORDS,
    ActionType,
    LookupRelation,
    SelectorStrategy,
    evaluate_scenario,
)
from spectre.domain.decision_inputs import VERSION
from spectre.domain.decision_tree import evaluate_tree
from spectre.web.decision_job import evaluated_line
from spectre.web.decision_record import (
    NO_TRAINING_LABEL,
    SOURCED_RELATIONS,
    Operator,
    listed,
    new_record,
    replay_record,
    stored_of,
)
from tests.integration.test_decision_input_validation import _evaluate, _form
from tests.integration.test_decision_record_route import _records, _sign_in
from tests.unit.test_decision_replay import _alone
from tests.unit.test_lookup_relations import _bound, _one

_NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
_MINIMAX = SelectorStrategy.MINIMAX
_MANOEUVRE, _RETASK, _N_ACTION = ActionType.MANOEUVRE, ActionType.SENSOR_RETASK, ActionType.NO_ACTION
#: What the route's default form rests on: one manoeuvre row against one manoeuvre response, unbound.
_FORM_RELATIONS = (
    LookupRelation.CUSTODY, LookupRelation.MISS_BY_ACTION, LookupRelation.MANOEUVRE_MISS, LookupRelation.DELTA_V,
    LookupRelation.TCA,
)


def _flat(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


class TestTheResultsPage:
    def test_an_unbound_evaluation_is_labelled_above_its_recommendation(self, client: TestClient) -> None:
        cookie = _sign_in(client, "training_page")
        page = _evaluate(client, cookie, _form()).text
        assert 0 < page.index('class="training-only"') < page.index('class="headline-pick"')
        text = _flat(page)
        assert "Training only. This result rests on unsourced relations of the lookup model" in text
        for relation in _FORM_RELATIONS:
            assert f"the {relation.value}, that {LOOKUP_RELATION_WORDS[relation]}" in text


class TestTheRecord:
    def test_the_record_keeps_the_label_the_page_showed_and_the_records_page_marks_it(self, client: TestClient) -> None:
        cookie = _sign_in(client, "training_record")
        text = _flat(_evaluate(client, cookie, _form()).text)
        (row,) = _records(client, "training_record")
        assert row.training_only is not None and row.training_only.startswith("Training only. ")
        assert row.training_only in text
        page = client.get("/plan/decision/records", cookies={"spectre_session": cookie}).text
        assert row.training_only in _flat(page)
        tag = re.search(r'<p class="record-training-only"[^>]*>', page)
        assert tag is not None and "var(--gold)" in tag.group(0)

    def test_a_result_resting_on_none_is_recorded_as_such(self) -> None:
        row = new_record(_bound((_N_ACTION,), (_N_ACTION,)), Operator(1, "sourced"), _NOW, primary=_MINIMAX)
        assert row.training_only == ""
        shown = listed(row, Operator(1, "sourced"))
        assert (shown.training_only, shown.training) == (SOURCED_RELATIONS, False)
        assert SOURCED_RELATIONS == "Rests on no unsourced relation of the lookup model."

    def test_a_record_from_before_says_none_was_recorded(self) -> None:
        row = new_record(_one(_MANOEUVRE, _MANOEUVRE), Operator(1, "before"), _NOW, primary=_MINIMAX)
        assert listed(row, Operator(1, "before")).training is True
        row.training_only = None
        shown = listed(row, Operator(1, "before"))
        assert (shown.training_only, shown.training) == (NO_TRAINING_LABEL, False)
        assert NO_TRAINING_LABEL == (
            "Training-only label: not recorded (this record predates it): it was written by a version of SPECTRE "
            "that did not record whether its result rests on an unsourced relation of the lookup model."
        )
        assert not NO_TRAINING_LABEL.startswith("Training only.")


class TestOldRecordsReplayExactly:
    def test_the_stored_inputs_are_unchanged(self) -> None:
        row = new_record(_one(_MANOEUVRE, _MANOEUVRE), Operator(1, "inputs"), _NOW, primary=_MINIMAX)
        # SPC-207 left the stored inputs at version 6; SPC-224 moved them to 7, adding the convergence rule.
        assert VERSION == 7
        assert row.inputs is not None and json.loads(row.inputs)["version"] == 7

    def test_a_simulated_pre_label_record_replays_exactly(self) -> None:
        """Simulates a record from before the label: this code writes it, then its training_only column is nulled,
        as 0.38.0 left it. Its stored inputs are what 0.38.0 would have written, version 6, so it replays exactly and
        its report is the labelled record's. Not a real 0.38.0 fixture: test_decision_record_upgrade.py upgrades a
        database made by an older release."""
        result = evaluate_tree(_one(_MANOEUVRE, _RETASK).scenario, _MINIMAX)
        labelled = new_record(result, Operator(7, "alice"), _NOW, primary=_MINIMAX)
        labelled.id = 1
        as_0_38_0 = new_record(result, Operator(7, "alice"), _NOW, primary=_MINIMAX)
        as_0_38_0.id = 2
        as_0_38_0.training_only = None
        done, before = replay_record(_alone(labelled)), replay_record(_alone(as_0_38_0))
        assert done.matches and before.matches, before.lines
        assert before.lines == done.lines
        assert as_0_38_0.inputs == labelled.inputs and as_0_38_0.inputs_sha256 == labelled.inputs_sha256

    def test_a_replay_of_a_record_reaches_the_same_label(self) -> None:
        result = evaluate_scenario(_one(_MANOEUVRE, _RETASK).scenario)
        row = new_record(result, Operator(7, "alice"), _NOW, primary=_MINIMAX)
        again = evaluate_tree(stored_of(row).scenario, _MINIMAX)
        assert row.training_only == again.training_only


class TestTheSessionLog:
    def test_the_logged_recommendation_carries_the_label_naming_each_relation(self) -> None:
        result = _one(_MANOEUVRE, _RETASK)
        line = evaluated_line(result.scenario, result)
        assert result.training_only is not None
        recommendation = line.index("Modelled recommendation: ")
        assert line.index(result.training_only) > recommendation
        for relation in result.lookup_relations:
            assert LOOKUP_RELATION_WORDS[relation] in line

    def test_a_result_resting_on_none_logs_no_label(self) -> None:
        result = _bound((_N_ACTION,), (_N_ACTION,))
        assert "Training only" not in evaluated_line(result.scenario, result)
