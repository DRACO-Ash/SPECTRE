"""A game tree has its own cost cap, set from trees measured under load (SPC-188, design D6).

The owner ruled on 2026-11-05 to raise the evaluation budget to 300 s (SPC-178) and then to measure trees under load
and set their own cap; until then a tree shared the matrix's, 12,000 sample-hours. scripts/measure_tree_cost.py ran
four trees the engine builds in full, each under the 300 s budget with every core of the build container kept busy:
the slowest ran at 90.8 sample-hours a second by the cost model. A fifth off that, rounded down, is 70, so the cap is
300 s x 70 = 21,000 sample-hours, and a tree at it takes about 231 s at the slowest rate measured. The figures come
from the build container, not a deployment target, and the register says so.

A record a release before 0.38.0 wrote checked its tree against the shared cap: stored inputs versions 1 to 5 read
under it (TreeCap.SHARED), so a tree refused then for its cost is refused again on replay, and the replay says so
first. Version 6 holds the tree's own cap.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
from typing import Any, NoReturn

import pytest

from spectre.domain import decision_tree
from spectre.domain.decision import (
    EVALUATION_BUDGET_S,
    MAX_SAMPLE_HOURS,
    Scenario,
    SelectorStrategy,
    TreeCap,
    _hashed,
    evaluate_scenario,
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
from spectre.domain.decision_replay import LEGACY_CAP, replay, said_first
from spectre.domain.decision_tree import (
    _SLOWEST_TREE_SAMPLE_HOURS_PER_S,
    MAX_TREE_SAMPLE_HOURS,
    TREE_DEPTH_COST,
    TREE_OVER_CAP,
    depth_refusal,
    evaluate_tree,
    largest_tree,
    refused_before_run,
    tree_cap,
    tree_cost,
)
from spectre.web.decision_record import Operator, new_record, recorded_of, replay_record, stored_of
from tests.unit import _decision_tree_cases as cases
from tests.unit._decision_reference import COPLANAR_LEO, EPOCH
from tests.unit.test_decision_elset_error import _V3, _records
from tests.unit.test_decision_replay import _alone
from tests.unit.test_decision_sampled import _Fake
from tests.unit.test_lookup_register import entries

#: The slowest rate the measurement gave, sample-hours a second, and the margin taken off it.
_MEASURED = 90.8
_MARGIN = 0.8


def _never(*_: Any, **__: Any) -> NoReturn:
    raise AssertionError("a later turn ran")


def _two_by_two(n: int, turns: int, turn_h: float) -> Scenario:
    """coplanar_leo, Hold course and Evasive (burning 0.1 of a turn in), against Hold and Avoid at 20 km."""
    rows = [cases.still(), cases.evasive(COPLANAR_LEO, n=n, offset_h=0.1 * turn_h)]
    return cases.scenario(
        rows, [cases.hold(), cases.avoid(20.0, hours=0.1 * turn_h)], turns=turns, horizon_h=turns * turn_h,
        bind=COPLANAR_LEO,
    )


#: 200 samples over three 2 h turns: about 19,777 sample-hours, over the shared cap and under the tree's own.
_BETWEEN = functools.partial(_two_by_two, 200, 3, 2.0)
#: 250 samples over three 2 h turns: about 24,144 sample-hours, over the tree's own cap.
_OVER = functools.partial(_two_by_two, 250, 3, 2.0)


class TestTheCapIsMeasured:
    def test_it_is_the_budget_at_a_fifth_under_the_slowest_tree_measured(self) -> None:
        assert _SLOWEST_TREE_SAMPLE_HOURS_PER_S == 70.0
        assert _SLOWEST_TREE_SAMPLE_HOURS_PER_S <= _MEASURED * _MARGIN < _SLOWEST_TREE_SAMPLE_HOURS_PER_S + 5.0
        assert MAX_TREE_SAMPLE_HOURS == EVALUATION_BUDGET_S * _SLOWEST_TREE_SAMPLE_HOURS_PER_S == 21_000.0

    def test_a_tree_at_the_cap_takes_the_budget_less_a_margin_at_the_slowest_rate(self) -> None:
        assert round(MAX_TREE_SAMPLE_HOURS / _MEASURED) == 231
        assert MAX_TREE_SAMPLE_HOURS / _MEASURED < EVALUATION_BUDGET_S

    def test_the_register_states_its_basis_and_where_it_was_measured(self) -> None:
        register = entries(_register_text())
        (cap,) = [e for e in register if e.name == "MAX_TREE_SAMPLE_HOURS"]
        (rate,) = [e for e in register if e.name == "_SLOWEST_TREE_SAMPLE_HOURS_PER_S"]
        assert "derived" in cap.source and "the owner: ruling of 2026-11-05" in cap.owner
        for said in ("measured", "90.8", "4 cores", "scripts/measure_tree_cost.py", "deployment target"):
            assert said in rate.source, said


def _register_text() -> str:
    from tests.unit.test_lookup_register import _REGISTER

    return _REGISTER.read_text(encoding="utf-8")


class TestATreeIsCheckedAgainstItsOwnCap:
    def test_a_tree_between_the_two_caps_now_fits(self) -> None:
        scenario = _BETWEEN()
        assert MAX_SAMPLE_HOURS < tree_cost(scenario) < MAX_TREE_SAMPLE_HOURS
        assert tree_cap(scenario) == MAX_TREE_SAMPLE_HOURS
        assert refused_before_run(scenario) is None
        assert depth_refusal(scenario) is None
        assert largest_tree(scenario) == 3

    def test_a_tree_over_its_own_cap_is_refused_naming_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(decision_tree, "continue_series", _never)
        scenario = _OVER()
        total = tree_cost(scenario)
        assert total > MAX_TREE_SAMPLE_HOURS
        refusal = TREE_OVER_CAP.format(
            turns=3, total=math.ceil(total), cap=MAX_TREE_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
            fits="At these sizes, 2 turns fit.",
        )
        assert "against a cap of 21,000" in refusal
        result = evaluate_tree(scenario, sampler=_Fake())
        assert result.tree is not None
        assert (result.tree.refusal, result.tree.roots) == (refusal, ())

    def test_the_panel_refuses_the_depth_naming_the_trees_own_cap(self) -> None:
        scenario = _OVER()
        assert depth_refusal(scenario) == TREE_DEPTH_COST.format(
            turns=3, total=math.ceil(tree_cost(scenario)), cap=MAX_TREE_SAMPLE_HOURS, budget=EVALUATION_BUDGET_S,
            largest="The largest turn depth that fits at these sizes is 2.",
        )


class TestARecordFromBeforeKeepsTheSharedCap:
    def test_this_code_writes_version_6_holding_the_trees_own_cap(self) -> None:
        assert (VERSION, VERSIONS) == (6, (1, 2, 3, 4, 5, 6))
        document = json.loads(store_inputs(evaluate_scenario(cases.scenario([cases.still()], [cases.hold()],
                                                                             turns=1)))[0])
        assert (document["version"], document["scenario"]["tree_cap"]) == (6, "own")

    def test_versions_1_to_5_read_under_the_shared_cap(self) -> None:
        stored = stored_of(_records(_V3)["tree"])
        assert (stored.scenario.turns, stored.scenario.tree_cap) == (2, TreeCap.SHARED)
        assert tree_cap(stored.scenario) == MAX_SAMPLE_HOURS

    def test_under_the_shared_cap_the_tree_between_is_refused_as_it_was(self) -> None:
        shared = dataclasses.replace(_BETWEEN(), tree_cap=TreeCap.SHARED)
        refusal = refused_before_run(shared)
        assert refusal is not None and "against a cap of 12,000" in refusal
        assert largest_tree(shared) == 2

    def test_the_0310_tree_replays_exactly_and_says_which_cap(self) -> None:
        done = replay_record(_records(_V3)["tree"])
        assert done.matches, done.lines
        assert LEGACY_CAP in done.preamble

    def test_a_0370_tree_refused_for_its_cost_replays_refused_and_exactly(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A record as 0.37.0 wrote it, stored inputs version 5 and no tree cap, of a tree that cost more than the
        shared cap: refused then, one turn shown. Replayed, it is refused again under the shared cap and matches;
        checked against the tree's own cap the same scenario would be built, and the tree's pick would differ."""
        monkeypatch.setattr(decision_tree, "continue_series", _never)
        shared = dataclasses.replace(_BETWEEN(), tree_cap=TreeCap.SHARED)
        result = evaluate_tree(shared, SelectorStrategy.MINIMAX, sampler=_Fake())
        assert result.tree is not None and result.tree.roots == () and result.tree.selection is None
        own = dataclasses.replace(result, scenario=dataclasses.replace(result.scenario, tree_cap=TreeCap.OWN))
        row = new_record(own, Operator(7, "alice"), EPOCH, primary=SelectorStrategy.MINIMAX)
        document = json.loads(row.inputs or "")
        del document["scenario"]["tree_cap"]
        document["version"] = 5
        row.inputs = canonical_json(document)
        row.inputs_sha256 = sha256_of(row.inputs)
        row.id = 1
        row = _alone(row)
        assert row.tree_pick_id is None
        stored = stored_of(row)
        assert stored.scenario.tree_cap is TreeCap.SHARED
        assert LEGACY_CAP in said_first(stored, "0.38.0")
        done = replay(stored, recorded_of(row), evaluate=functools.partial(evaluate_tree, sampler=_Fake()))
        assert done.matches, done.lines
        assert LEGACY_CAP in done.preamble
        assert refused_before_run(dataclasses.replace(stored.scenario, tree_cap=TreeCap.OWN)) is None

    def test_a_one_turn_record_says_nothing_of_the_cap(self) -> None:
        stored = stored_of(_records(_V3)["sampled_and_computed"])
        assert stored.scenario.turns == 1
        assert LEGACY_CAP not in said_first(stored, "0.38.0")

    def test_a_result_under_the_shared_cap_is_never_stored_again(self) -> None:
        one = cases.scenario([cases.still()], [cases.hold()], turns=1)
        scenario = dataclasses.replace(one, tree_cap=TreeCap.SHARED)
        with pytest.raises(ValueError, match="never stored again"):
            store_inputs(evaluate_scenario(scenario))

    def test_a_version_6_document_under_the_shared_cap_is_refused(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(cases.scenario([cases.still()], [cases.hold()],
                                                                             turns=1)))[0])
        document["scenario"]["tree_cap"] = TreeCap.SHARED.value
        text = canonical_json(document)
        with pytest.raises(InputsRefusedError, match=r"refused at scenario\.tree_cap: version 6 holds"):
            read_inputs(text, sha256_of(text))

    def test_a_version_5_document_holding_the_cap_is_refused(self) -> None:
        document = json.loads(store_inputs(evaluate_scenario(cases.scenario([cases.still()], [cases.hold()],
                                                                             turns=1)))[0])
        text = canonical_json({**document, "version": 5})
        with pytest.raises(InputsRefusedError, match="unknown field tree_cap"):
            read_inputs(text, sha256_of(text))

    def test_the_hash_leaves_the_cap_out_where_it_sets_nothing_or_is_the_shared_one(self) -> None:
        tree = _BETWEEN()
        assert _hashed(tree)["tree_cap"] == TreeCap.OWN
        assert "tree_cap" not in _hashed(dataclasses.replace(tree, tree_cap=TreeCap.SHARED))
        assert "tree_cap" not in _hashed(dataclasses.replace(tree, turns=1))
