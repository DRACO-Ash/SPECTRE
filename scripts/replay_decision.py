#!/usr/bin/env python3
"""Replay a Decision Engine recommendation from its stored decision record (SPC-193, evaluation F-02).

Reads one record from the database SPECTRE is configured to use (DATABASE_URL, or SQLite under ./data or
SPECTRE_SQLITE_DIR, as the server reads it), rebuilds the scenario from the record's stored inputs, evaluates it
again under the stored rule, and prints whether the recommendation, the three rules' picks, a tree's turn-1 pick and
every composite score match the record exactly, with the record's own rule, code version and input hash columns set
against its hashed inputs. Before replaying it says which code version wrote the hashed inputs and, when it was
another, that the comparison is across versions, and whether the evaluation recorded ran out of its time budget. It
writes nothing: a SQLite database is opened read-only, and one that is not there is not created.

    python scripts/replay_decision.py RECORD_ID

Exit codes: 0 the replay matches the record; 1 it differs; 2 a usage error; 3 nothing to replay: no record with
that id, a record written before 0.28.0 with no stored inputs, inputs the strict reader refuses, or a database
that cannot be read or is not there.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import spectre  # noqa: E402 - after the repository root is on the path
from spectre.domain.decision_inputs import InputsRefusedError  # noqa: E402
from spectre.domain.decision_replay import said_first  # noqa: E402
from spectre.web.decision_record import replay_record, stored_of  # noqa: E402
from spectre.web.models import DecisionRecord  # noqa: E402

MATCHES, DIFFERS, USAGE, NOTHING = 0, 1, 2, 3
#: The largest id a record can carry: PostgreSQL's INTEGER.
_MAX_ID = 2**31 - 1
_SQLITE = "sqlite+aiosqlite:///"


class NoDatabaseError(Exception):
    """No SQLite database is at the configured path, so there is nothing to read and nothing is created."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"No database is at the configured SQLite path {path}; nothing was created.")


def read_only(url: str) -> str:
    """*url* opened read-only when it names a SQLite file, through SQLite's URI form; any other URL as it stands."""
    if not url.startswith(_SQLITE):
        return url
    return f"{_SQLITE}file:{url.removeprefix(_SQLITE)}?mode=ro&uri=true"


def _missing_sqlite(url: str) -> Path | None:
    """The SQLite file *url* names when it is not there, which connecting would create; None otherwise."""
    if not url.startswith(_SQLITE):
        return None
    path = Path(url.removeprefix(_SQLITE))
    return None if path.is_file() else path


def _record_id(raw: str) -> int:
    try:
        number = int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a record id") from error
    if not 1 <= number <= _MAX_ID:
        raise argparse.ArgumentTypeError(f"a record id is from 1 to {_MAX_ID}")
    return number


async def _read(record_id: int) -> DecisionRecord | None:
    """Record *record_id* from the configured database, or None when there is none, on an engine of its own that is
    closed before the command ends."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from spectre.config.settings import get_settings, split_database_url

    url, connect_args = split_database_url(get_settings().database_url)
    missing = _missing_sqlite(url)
    if missing is not None:
        raise NoDatabaseError(missing)
    engine = create_async_engine(read_only(url), connect_args=connect_args)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await session.get(DecisionRecord, record_id)
    finally:
        await engine.dispose()


def _say(*lines: str) -> None:
    for line in lines:
        print(line)


def _replayed(row: DecisionRecord) -> int:
    """Say what the record is; read its stored inputs, and say which version wrote them and whether the budget ran
    out, from the hashed inputs alone; then replay it and say how it compares."""
    _say(f"Record {row.id}: {row.scenario_name!r}, run by {row.username}, rule used {row.rule.replace('_', ' ')}.")
    try:
        stored = stored_of(row)
    except InputsRefusedError as refused:
        _say(str(refused))
        return NOTHING
    _say(*said_first(stored, spectre.__version__))
    done = replay_record(row, stored=stored, running=spectre.__version__)
    _say(*done.report)
    return MATCHES if done.matches else DIFFERS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a decision record from its stored inputs (SPC-193).")
    parser.add_argument("record_id", type=_record_id, help="the decision record's number")
    args: Any = parser.parse_args(argv)
    try:
        row = asyncio.run(_read(args.record_id))
    except NoDatabaseError as missing:
        _say(str(missing))
        return NOTHING
    except Exception as error:  # noqa: BLE001 - any failure to read is said in one line, with no detail of the data
        _say(f"The configured database could not be read; the error was {type(error).__name__}.")
        return NOTHING
    if row is None:
        _say(f"No decision record has id {args.record_id}.")
        return NOTHING
    return _replayed(row)


if __name__ == "__main__":
    sys.exit(main())
