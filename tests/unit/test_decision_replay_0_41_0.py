"""Records SPECTRE 0.41.0 wrote replay exactly after SPC-224, which checks convergence on two seeds (inputs version 7).

SPC-224 draws every sampled row again on a second seed and refuses the row when the two disagree, and charges each
sampled row twice against the sample-hour cap; both would move what a 0.41.0 record replays to. So the stored inputs
go to version 7, which holds the convergence rule, and versions 1 to 6 read as the one seed 0.28.0 to 0.41.0 judged
convergence on, ConvergenceRule.ONE_SEED.

_decision_records_0_41_0.json holds four records exactly as 0.41.0 (602c963) wrote them, by that release's own
new_record and evaluate_tree, run from an export of 602c963: the three scenarios of the 0.39.0 records (a sampled
scenario under expected value, a sampled row beside a computed row, both holding element-set error, under minimax,
and a two-turn sampled tree under minimax), and "seeds_differ", the tree's scenario over one turn at 59 samples, whose
row converges at seed 42 (half-width 0.66 km) and not at seed 43. Each must replay here with every pick and every
composite score equal at full precision; seeds_differ must still be sampled on replay, and be refused when the same
scenario is evaluated now, on two seeds.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path

import pytest

from spectre.domain.decision import ConvergenceRule
from spectre.domain.decision_tree import evaluate_tree
from spectre.web.decision_record import replay_record, stored_of
from spectre.web.models import DecisionRecord

_RECORDS = Path(__file__).with_name("_decision_records_0_41_0.json")
_NAMES = sorted(json.loads(_RECORDS.read_text(encoding="utf-8")))


def _record(name: str) -> DecisionRecord:
    columns = json.loads(_RECORDS.read_text(encoding="utf-8"))[name]
    return DecisionRecord(**{**columns, "id": 1, "created_at": datetime.fromisoformat(columns["created_at"])})


def test_the_records_were_written_by_0410_at_version_6() -> None:
    assert _NAMES == ["sampled", "sampled_and_computed", "seeds_differ", "tree"]
    for name in _NAMES:
        row = _record(name)
        assert row.code_version == "0.41.0"
        assert json.loads(row.inputs or "")["version"] == 6


@pytest.mark.parametrize("name", _NAMES)
def test_each_reads_as_one_seed(name: str) -> None:
    assert stored_of(_record(name)).scenario.convergence_rule is ConvergenceRule.ONE_SEED


@pytest.mark.parametrize("name", _NAMES)
def test_each_replays_exactly(name: str) -> None:
    done = replay_record(_record(name))
    assert done.matches, done.lines


@pytest.mark.parametrize("name", _NAMES)
def test_each_sampled_cell_names_its_one_seed_and_the_constants_handover(name: str) -> None:
    stored = stored_of(_record(name))
    result = evaluate_tree(dataclasses.replace(stored.scenario, turns=1), stored.rule)
    sampled = [cell for row in result.outcome_matrix for cell in row if cell.ca_percentiles is not None]
    assert sampled, name
    for cell in sampled:
        note = cell.figure_bases.closest_approach_km.note
        assert note.endswith("; drawn on seed 42, its convergence judged on that draw alone, as before 0.42.0")
        assert "constants handover, not in the spread: RK45 starts from SGP4's states" in note


def test_seeds_differ_is_sampled_on_replay_and_refused_on_two_seeds() -> None:
    stored = stored_of(_record("seeds_differ"))
    replayed = evaluate_tree(stored.scenario, stored.rule)
    row = next(i for i, a in enumerate(replayed.scenario.adversary_actions) if a.hypothesis is not None)
    assert replayed.outcome_matrix[row][0].ca_half_width_km == pytest.approx(0.657140495886722, abs=1e-12)
    now = evaluate_tree(dataclasses.replace(stored.scenario, convergence_rule=ConvergenceRule.TWO_SEEDS), stored.rule)
    refusals = {cell.ca_refusal for cell in now.outcome_matrix[row]}
    assert len(refusals) == 1
    refusal = str(refusals.pop())
    assert refusal.startswith("Not sampled: the samples converged on seed 42, known to within 0.66 km against the ")
    assert "but not on seed 43, the second its convergence is checked on" in refusal
    assert all(cell.ca_percentiles is None for cell in now.outcome_matrix[row])
