"""A database made by 0.27.0 is upgraded in place (SPC-194, SPC-193, SPC-205).

0.27.0 created decision_records without the primary rule, whether the chosen rule differed, or the stored inputs.
init_db adds each missing column to the table already there, keeping every record it holds, and a record from
before reads as one that recorded none of them. Nothing else is touched, and a second boot changes nothing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from spectre.domain.decision_inputs import InputsRefusedError
from spectre.web import database
from spectre.web.decision_record import Operator, listed, replay_record
from spectre.web.models import DecisionRecord

#: decision_records exactly as 0.27.0 created it on SQLite, with its two indexes.
_TABLE_0_27_0 = """
CREATE TABLE decision_records (
    id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    user_id INTEGER,
    username VARCHAR(64) NOT NULL,
    scenario_name TEXT NOT NULL,
    rule VARCHAR(32) NOT NULL,
    recommended_id TEXT NOT NULL,
    recommended_name TEXT NOT NULL,
    minimax_id TEXT NOT NULL,
    minimax_name TEXT NOT NULL,
    minimin_id TEXT NOT NULL,
    minimin_name TEXT NOT NULL,
    expected_value_id TEXT NOT NULL,
    expected_value_name TEXT NOT NULL,
    expected_value_caveat TEXT,
    tree_pick_id TEXT,
    tree_pick_name TEXT,
    tree_recommendation TEXT NOT NULL,
    code_version VARCHAR(64) NOT NULL,
    calibration_source TEXT NOT NULL,
    input_hashes TEXT NOT NULL,
    responses TEXT NOT NULL,
    turns INTEGER NOT NULL,
    keep_out_km FLOAT NOT NULL,
    decision VARCHAR(32),
    decision_name TEXT,
    rationale TEXT,
    decided_at DATETIME,
    PRIMARY KEY (id)
)
"""
_INDEXES_0_27_0 = (
    "CREATE INDEX ix_decision_records_user_id ON decision_records (user_id)",
    "CREATE INDEX ix_decision_records_created_at ON decision_records (created_at)",
)
_ROW_0_27_0 = """
INSERT INTO decision_records (
    id, created_at, user_id, username, scenario_name, rule, recommended_id, recommended_name, minimax_id,
    minimax_name, minimin_id, minimin_name, expected_value_id, expected_value_name, tree_recommendation,
    code_version, calibration_source, input_hashes, responses, turns, keep_out_km, decision, decision_name,
    rationale, decided_at
) VALUES (
    7, '2026-11-09 10:00:00', 3, 'veteran', 'Before the upgrade', 'expected_value', 'R2', 'Avoid', 'R1', 'Hold',
    'R1', 'Hold', 'R2', 'Avoid', '[]', '0.27.0', 'table', '[]',
    '[{"id": "R1", "name": "Hold"}, {"id": "R2", "name": "Avoid"}]', 1, 10.0, 'response-1', 'Avoid (R2)',
    'Held to it', '2026-11-09 10:05:00'
)
"""
#: The columns 0.28.0 adds to decision_records, and the weight stability's (SPC-205).
_ADDED = {"primary_rule", "rule_differed", "inputs", "inputs_sha256", "weight_stability"}


def _columns(sync_conn: Any) -> set[str]:
    return {c["name"] for c in inspect(sync_conn).get_columns("decision_records")}


@pytest.fixture
def old_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A SQLite file holding 0.27.0's decision_records and one decided record, set as the application's database."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'spectre-0.27.0.db'}")

    async def make() -> None:
        async with engine.begin() as conn:
            await conn.execute(text(_TABLE_0_27_0))
            for index in _INDEXES_0_27_0:
                await conn.execute(text(index))
            await conn.execute(text(_ROW_0_27_0))

    asyncio.run(make())
    monkeypatch.setattr(database, "engine", engine)

    async def no_admin() -> None:
        return None

    monkeypatch.setattr(database, "_bootstrap_admin", no_admin)
    yield engine
    asyncio.run(engine.dispose())


def _boot_and_read(engine: Any) -> tuple[set[str], DecisionRecord, int]:
    async def run() -> tuple[set[str], DecisionRecord, int]:
        await database.init_db()
        async with engine.connect() as conn:
            columns = await conn.run_sync(_columns)
            count = (await conn.execute(text("SELECT COUNT(*) FROM decision_records"))).scalar_one()
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await session.get(DecisionRecord, 7)
        assert row is not None
        return columns, row, int(count)

    return asyncio.run(run())


class TestA0270DatabaseIsUpgradedInPlace:
    def test_the_new_columns_are_added_and_the_old_record_is_kept(self, old_database: Any) -> None:
        columns, row, count = _boot_and_read(old_database)
        assert columns >= _ADDED
        assert count == 1
        assert (row.scenario_name, row.rule, row.recommended_id, row.decision_name, row.rationale) == (
            "Before the upgrade", "expected_value", "R2", "Avoid (R2)", "Held to it",
        )

    def test_the_old_record_reads_as_one_that_recorded_no_primary_rule(self, old_database: Any) -> None:
        _columns_, row, _count = _boot_and_read(old_database)
        assert (row.primary_rule, row.rule_differed) == ("", None)
        shown = listed(row, Operator(3, "veteran"))
        assert shown.primary == (
            "Primary rule: not recorded; this record was written by a version of SPECTRE that did not record one."
        )
        assert shown.used == "Rule used: expected value. Recommended: Avoid (R2)."
        assert shown.decision.decided

    def test_the_old_record_holds_no_weight_stability_and_says_so(self, old_database: Any) -> None:
        """SPC-205: a record written before the weight stability was recorded reads as one that recorded none."""
        _columns_, row, _count = _boot_and_read(old_database)
        assert row.weight_stability is None
        assert listed(row, Operator(3, "veteran")).stability == (
            "Weight stability: not recorded; this record was written by a version of SPECTRE that did not record it."
        )

    def test_the_old_record_holds_no_inputs_and_replay_says_why(self, old_database: Any) -> None:
        _columns_, row, _count = _boot_and_read(old_database)
        assert (row.inputs, row.inputs_sha256) == (None, None)
        with pytest.raises(InputsRefusedError, match="no stored inputs"):
            replay_record(row)

    def test_a_second_boot_changes_nothing(self, old_database: Any) -> None:
        first = _boot_and_read(old_database)
        second = _boot_and_read(old_database)
        assert first[0] == second[0] and first[2] == second[2] == 1

    def test_a_record_written_after_the_upgrade_holds_them(self, old_database: Any) -> None:
        _boot_and_read(old_database)

        async def write() -> DecisionRecord | None:
            async with async_sessionmaker(old_database, expire_on_commit=False)() as session:
                session.add(DecisionRecord(
                    created_at=datetime(2026, 11, 10, 9, 0, tzinfo=UTC), user_id=3, username="veteran",
                    scenario_name="After", rule="minimin", recommended_id="R1", recommended_name="Hold",
                    minimax_id="R2", minimax_name="Avoid", minimin_id="R1", minimin_name="Hold",
                    expected_value_id="R2", expected_value_name="Avoid", tree_recommendation="[]",
                    code_version="0.28.0", calibration_source="table", input_hashes="[]",
                    responses='[{"id": "R1", "name": "Hold"}]', turns=1, keep_out_km=10.0,
                    primary_rule="minimax", rule_differed=True, inputs="{}", inputs_sha256="0" * 64,
                ))
                await session.commit()
            async with async_sessionmaker(old_database, expire_on_commit=False)() as session:
                return await session.get(DecisionRecord, 8)

        row = asyncio.run(write())
        assert row is not None
        assert (row.primary_rule, row.rule_differed, row.inputs, row.inputs_sha256) == ("minimax", True, "{}", "0" * 64)
