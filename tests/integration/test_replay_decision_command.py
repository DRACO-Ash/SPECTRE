"""scripts/replay_decision.py: replay a stored decision record from the configured database (SPC-193, F-02).

The command reads one record from the database the settings name, rebuilds its Scenario from the stored inputs,
evaluates it again under the stored rule and prints whether the recommendation, the three rules' picks and every
composite score match. It says first when the record was written by another code version. Exit codes: 0 when the
replay matches, 1 when it differs, 2 for a usage error, 3 when there is nothing to replay (no such record, no stored
inputs, or inputs the strict reader refuses).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

import spectre
from spectre.domain.decision import SelectorStrategy
from spectre.domain.decision_tree import evaluate_tree
from spectre.web.decision_record import NO_INPUTS, Operator, write_record
from spectre.web.models import DecisionRecord
from tests.integration.test_decision_record_route import _sign_in
from tests.integration.test_training_integrity import _db
from tests.unit.test_decision_inputs import _lookup, _sampled

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "replay_decision.py"


@pytest.fixture(scope="module")
def command() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_replay_decision", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_replay_decision"] = module
    spec.loader.exec_module(module)
    return module


def _written(client: TestClient, name: str, scenario: Any, rule: SelectorStrategy) -> int:
    """A record written by the application's own writer for a real evaluation, run by *name*; its id."""
    _sign_in(client, name)

    async def user_id(session: Any) -> int:
        from sqlalchemy import select

        from spectre.web.models import User
        return int((await session.execute(select(User.id).where(User.username == name))).scalar_one())

    operator = Operator(_db(client, user_id), name)
    result = evaluate_tree(scenario, rule)
    record_id = client.portal.call(write_record, result, operator)  # type: ignore[union-attr]
    assert record_id is not None
    return int(record_id)


def _alter(client: TestClient, record_id: int, **values: Any) -> None:
    async def change(session: Any) -> None:
        await session.execute(update(DecisionRecord).where(DecisionRecord.id == record_id).values(**values))
        await session.commit()

    _db(client, change)


def _run(command: ModuleType, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str]]:
    code = command.main(list(argv))
    return code, capsys.readouterr().out.splitlines()


class TestTheCommand:
    def test_a_lookup_record_replays_exactly_and_exits_0(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_id = _written(client, "replay_lookup", _lookup(), SelectorStrategy.MINIMIN)
        code, lines = _run(command, capsys, str(record_id))
        assert code == 0
        assert lines[0].startswith(f"Record {record_id}: ")
        assert lines[1] == f"This record was written by SPECTRE {spectre.__version__}, the version running."
        assert lines[-1].startswith("Replay matches the record exactly")

    def test_a_sampled_record_replays_exactly(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_id = _written(client, "replay_sampled", _sampled(), SelectorStrategy.EXPECTED_VALUE)
        code, lines = _run(command, capsys, str(record_id))
        assert code == 0, lines
        assert any(line.startswith("Pick of the rule used, expected value: recorded") and line.endswith("same.")
                   for line in lines)

    def test_a_record_that_no_longer_matches_exits_1_naming_the_difference(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_id = _written(client, "replay_differs", _lookup(), SelectorStrategy.MINIMAX)
        _alter(client, record_id, minimin_id="R9", minimin_name="Imagined")
        code, lines = _run(command, capsys, str(record_id))
        assert code == 1
        assert any(line.startswith("Minimin's pick: recorded Imagined (R9), replayed") for line in lines)
        assert lines[-1].startswith("Replay does not match the record: 1 of")

    def test_across_versions_it_says_so_before_replaying(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record_id = _written(client, "replay_versions", _lookup(), SelectorStrategy.MINIMAX)
        said_before: list[str] = []
        real = command.replay_record

        def watched(row: DecisionRecord, **kwargs: Any) -> Any:
            said_before.extend(capsys.readouterr().out.splitlines())
            return real(row, **kwargs)

        monkeypatch.setattr(command, "replay_record", watched)
        monkeypatch.setattr(spectre, "__version__", "9.9.9")
        code = command.main([str(record_id)])
        rest = capsys.readouterr().out.splitlines()
        assert code == 0
        assert said_before[1].startswith(f"This record was written by SPECTRE {spectre_version(record_id, client)} "
                                         "and the running code is 9.9.9: the replay is compared across versions")
        assert rest[-1].startswith("Replay across versions matches the record exactly")

    def test_the_version_said_first_is_the_one_inside_the_hashed_inputs(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The record's code version column is not hashed: an edit to it leaves the hashed inputs' version, which the
        first line names, and the column's own disagreement is a comparison that differs."""
        record_id = _written(client, "replay_column_version", _lookup(), SelectorStrategy.MINIMAX)
        _alter(client, record_id, code_version="0.26.0")
        code, lines = _run(command, capsys, str(record_id))
        assert code == 1
        assert lines[1] == f"This record was written by SPECTRE {spectre.__version__}, the version running."
        assert (f"Code version: the record says 0.26.0, its stored inputs say {spectre.__version__}: DIFFERS."
                in lines)
        assert not any("across versions" in line for line in lines)
        assert lines[-1].startswith("Replay does not match the record: 1 of")

    def test_a_rule_column_altered_from_the_stored_rule_exits_1(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_id = _written(client, "replay_column_rule", _lookup(), SelectorStrategy.MINIMIN)
        _alter(client, record_id, rule="minimax")
        code, lines = _run(command, capsys, str(record_id))
        assert code == 1
        assert "Rule used: the record says minimax, its stored inputs say minimin: DIFFERS." in lines

    def test_no_such_record_exits_3(self, command: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
        code, lines = _run(command, capsys, "2000000000")
        assert code == 3
        assert lines == ["No decision record has id 2000000000."]

    def test_a_record_without_stored_inputs_exits_3(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_id = _written(client, "replay_old", _lookup(), SelectorStrategy.MINIMAX)
        _alter(client, record_id, inputs=None, inputs_sha256=None, code_version="0.26.0")
        code, lines = _run(command, capsys, str(record_id))
        assert code == 3
        assert len(lines) == 2
        assert lines[0].startswith(f"Record {record_id}: ")
        assert lines[1] == NO_INPUTS
        assert not any("written by SPECTRE" in line or "across versions" in line for line in lines)

    def test_altered_inputs_exit_3_with_the_refusal(
        self, client: TestClient, command: ModuleType, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record_id = _written(client, "replay_tampered", _lookup(), SelectorStrategy.MINIMAX)
        _alter(client, record_id, inputs_sha256="0" * 64)
        code, lines = _run(command, capsys, str(record_id))
        assert code == 3
        assert "SHA-256" in lines[-1]

    @pytest.mark.parametrize("argv", [[], ["twelve"], ["0"], ["1", "2"]])
    def test_a_usage_error_exits_2(
        self, command: ModuleType, capsys: pytest.CaptureFixture[str], argv: list[str],
    ) -> None:
        with pytest.raises(SystemExit) as stopped:
            command.main(argv)
        assert stopped.value.code == 2
        assert "usage:" in capsys.readouterr().err

    @pytest.mark.parametrize("folder", ["empty", "absent"])
    def test_a_sqlite_database_that_is_not_there_is_not_created(
        self, command: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path, folder: str,
    ) -> None:
        """The command writes nothing: with no database at the configured SQLite path, it creates neither the file nor
        its folder, and says there is none."""
        where = tmp_path / folder
        if folder == "empty":
            where.mkdir()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("SPECTRE_SQLITE_DIR", str(where))
        code, lines = _run(command, capsys, "1")
        assert code == 3
        assert lines == [f"No database is at the configured SQLite path {where / 'spectre.db'}; nothing was created."]
        assert not (where / "spectre.db").exists()
        assert where.exists() == (folder == "empty")
        assert list(tmp_path.rglob("*")) == ([where] if folder == "empty" else [])

    def test_a_sqlite_database_is_opened_read_only(self, command: ModuleType, tmp_path: Path) -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'spectre.db'}"
        assert command.read_only(url) == f"sqlite+aiosqlite:///file:{tmp_path / 'spectre.db'}?mode=ro&uri=true"
        postgres = "postgresql+asyncpg://user@host/spectre"
        assert command.read_only(postgres) == postgres

    def test_a_database_that_cannot_be_read_exits_3(
        self, command: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def broken(_record_id: int) -> Any:
            raise OSError("disk gone")

        monkeypatch.setattr(command, "_read", broken)
        code, lines = _run(command, capsys, "5")
        assert code == 3
        assert lines == ["The configured database could not be read; the error was OSError."]


def spectre_version(record_id: int, client: TestClient) -> str:
    """The code version record *record_id* was written by."""
    async def read(session: Any) -> str:
        row = await session.get(DecisionRecord, record_id)
        return str(row.code_version)

    return str(_db(client, read))
