"""Records SPECTRE 0.39.0 wrote replay exactly after SPC-213 to SPC-215 and SPC-237 (stored inputs version 6).

SPC-213 gives P5 its own half-width in the sampled basis note and leaves convergence on the widest of the three, from
the same bootstrap draw; SPC-214 states the integrator's error in that note and leaves the tolerances alone; SPC-215
states each set's regime and leaves every limit and rate as it was; SPC-237 changes the V-bar hop, which no stored
input holds. So no stored or replayed figure moves, and the stored inputs stay at version 6.

_decision_records_0_39_0.json holds three records exactly as 0.39.0 (292fa2c) wrote them, by that release's own
new_record and evaluate_tree, run from a checkout of 292fa2c: a sampled scenario under expected value, a two-turn
sampled tree under minimax, and a sampled row beside a computed row, both holding element-set error, under minimax.
Each must replay here with every pick and every composite score equal at full precision, and each sampled cell
must still be converged on the widest half-width, which its note names.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from spectre.astro.monte_carlo import miss_tolerance_km
from spectre.domain.decision_tree import evaluate_tree
from spectre.web.decision_record import replay_record, stored_of
from spectre.web.models import DecisionRecord

_RECORDS = Path(__file__).with_name("_decision_records_0_39_0.json")
_NAMES = sorted(json.loads(_RECORDS.read_text(encoding="utf-8")))


def _record(name: str) -> DecisionRecord:
    columns = json.loads(_RECORDS.read_text(encoding="utf-8"))[name]
    return DecisionRecord(**{**columns, "id": 1, "created_at": datetime.fromisoformat(columns["created_at"])})


def test_the_records_were_written_by_0390_at_version_6() -> None:
    assert _NAMES == ["sampled", "sampled_and_computed", "tree"]
    for name in _NAMES:
        row = _record(name)
        assert row.code_version == "0.39.0"
        assert json.loads(row.inputs or "")["version"] == 6


@pytest.mark.parametrize("name", _NAMES)
def test_each_replays_exactly(name: str) -> None:
    done = replay_record(_record(name))
    assert done.matches, done.lines


@pytest.mark.parametrize("name", _NAMES)
def test_each_sampled_cell_is_converged_on_the_widest_half_width_which_its_note_names(name: str) -> None:
    stored = stored_of(_record(name))
    result = evaluate_tree(stored.scenario, stored.rule)
    sampled = [cell for row in result.outcome_matrix for cell in row if cell.ca_percentiles is not None]
    assert sampled, name
    for cell in sampled:
        note = cell.figure_bases.closest_approach_km.note
        assert f"Convergence is judged on the widest of the P5, P50 and P95 half-widths, {cell.ca_half_width_km:.2f}" \
            in note
        assert "integrator error, not in the spread" in note
        # Converged as 0.39.0 judged it: the widest of the three half-widths within the tolerance of P5.
        assert cell.ca_half_width_km is not None and cell.ca_percentiles is not None
        assert cell.ca_half_width_km <= miss_tolerance_km(cell.ca_percentiles[5])
