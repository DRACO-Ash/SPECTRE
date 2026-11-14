"""The hostile seed list is owner data, read from a configured path, never bundled (SPC-174).

Concept section 9, decision 5: the seed list never becomes classified; it is
deployment data, an analyst's list for one deployment, so it is not a bundled
file and a propagated path names each seed (decision 15, SPC-180). The path is
set in configuration (SPECTRE_HOSTILE_SEEDS); none is shipped, and with none
configured propagation adds nothing and the ledger says so. A file that
cannot be read, or is malformed, is refused and the refusal stated; its
contents never reach the page or the log.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.config.settings import Settings
from spectre.domain.custody import Custody
from spectre.domain.interaction_graph import NO_SEED_LIST, Burn, Edge
from spectre.domain.warning_change import Change
from spectre.web import interaction_store as store
from spectre.web.understanding_view import HeldObject

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = Burn(epoch=_NOW, earliest=_NOW, latest=_NOW, confirmed=True, detection="HIGH", provider="18SDS")
_ENV = "SPECTRE_HOSTILE_SEEDS"
_REFUSED = "hostile seed list refused, so propagation adds nothing: "


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _edge(actor: str, target: str) -> Edge:
    return Edge(actor, f"OBJ-{target}", False, Change.NEWLY_IN_REACH, None, 3.0, _NOW, (_BURN,), target_satno=target)


class TestThePathIsConfigured:
    def test_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, " /secure/seeds.json ")
        assert Settings().hostile_seeds_path == "/secure/seeds.json"

    def test_with_none_set_there_is_no_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV, raising=False)
        assert Settings().hostile_seeds_path == ""

    def test_no_seed_list_is_shipped(self) -> None:
        shipped = [p for p in (_ROOT / "spectre").rglob("*") if "seed" in p.name.lower() and p.suffix != ".pyc"]
        assert shipped == []


class TestTheFileIsReadStrictly:
    def test_none_configured_reads_no_list(self) -> None:
        assert store.load_seed_list("") is NO_SEED_LIST
        assert store.load_seed_list("   ") is NO_SEED_LIST

    def test_a_valid_file_is_read(self, tmp_path: Path) -> None:
        path = _write(tmp_path, {"seeds": [{"satno": 41838, "disposition": "hostile"}]})
        assert store.load_seed_list(str(path)).hostile == frozenset({"41838"})

    def test_a_file_that_cannot_be_read_is_refused_and_its_path_stays_in_the_log(
            self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        missing = tmp_path / "absent\nforged.json"
        with caplog.at_level(logging.WARNING, logger=store.logger.name):
            seeds = store.load_seed_list(str(missing))
        assert seeds.statement == _REFUSED + "the configured file cannot be read"
        assert "absent" not in seeds.statement
        (record,) = caplog.records
        assert "\nforged" not in record.getMessage()

    def test_a_file_over_1_mib_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "seeds.json"
        path.write_bytes(b" " * (store.SEED_FILE_LIMIT + 1))
        assert store.load_seed_list(str(path)).statement == _REFUSED + "the configured file is larger than 1 MiB"

    def test_a_path_that_is_not_a_regular_file_is_refused_without_reading_it(self, tmp_path: Path) -> None:
        """Review finding 8: a FIFO reports size 0, so a size check alone would read it without bound."""
        fifo = tmp_path / "seeds.fifo"
        os.mkfifo(fifo)
        body = '{"seeds": [{"satno": 900, "disposition": "hostile"}]}' + " " * (store.SEED_FILE_LIMIT + 1)

        def feed() -> None:
            # Blocks until a reader opens the pipe; a correct loader never does, and cleanup releases it.
            with contextlib.suppress(OSError), fifo.open("w", encoding="utf-8") as pipe:
                pipe.write(body)

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        try:
            seeds = store.load_seed_list(str(fifo))
        finally:
            release = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            os.close(release)
            writer.join(timeout=5)
        assert (seeds.hostile, seeds.refused) == (frozenset(), True)
        assert seeds.statement == _REFUSED + "the configured path is not a regular file"

    def test_a_directory_is_refused_as_not_a_regular_file(self, tmp_path: Path) -> None:
        assert store.load_seed_list(str(tmp_path)).statement == _REFUSED + "the configured path is not a regular file"

    def test_a_file_that_is_not_utf_8_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "seeds.json"
        path.write_bytes(b'{"seeds": ["\xff"]}')
        assert store.load_seed_list(str(path)).statement == _REFUSED + "the configured file is not UTF-8 text"

    def test_a_malformed_file_is_refused_with_its_reason_and_not_its_contents(
            self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = _write(tmp_path, {"seeds": [{"satno": "TOP-SECRET", "disposition": "hostile"}]})
        with caplog.at_level(logging.INFO, logger=store.logger.name):
            seeds = store.load_seed_list(str(path))
        assert seeds.statement == _REFUSED + "entry 1's satno is not a catalogue number"
        assert all("TOP-SECRET" not in r.getMessage() for r in caplog.records)

    def test_the_configured_list_is_the_one_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, str(_write(tmp_path, {"seeds": [{"satno": 900, "disposition": "hostile"}]})))
        assert store.configured_seed_list().hostile == frozenset({"900"})
        monkeypatch.delenv(_ENV)
        assert store.configured_seed_list() is NO_SEED_LIST

    def test_an_unchanged_file_is_not_parsed_again(self, tmp_path: Path) -> None:
        path = str(_write(tmp_path, {"seeds": [{"satno": 900, "disposition": "hostile"}]}))
        assert store.load_seed_list(path) is store.load_seed_list(path)

    def test_a_changed_file_is_read_again(self, tmp_path: Path) -> None:
        path = _write(tmp_path, {"seeds": [{"satno": 900, "disposition": "hostile"}]})
        assert store.load_seed_list(str(path)).hostile == frozenset({"900"})
        path.write_text(json.dumps({"seeds": [{"satno": 901, "disposition": "hostile"},
                                              {"satno": 902, "disposition": "hostile"}]}), encoding="utf-8")
        assert store.load_seed_list(str(path)).hostile == frozenset({"901", "902"})


class TestTheSessionReadsThePaths:
    def test_paths_run_through_every_objects_held_edges_and_the_ledger_states_the_list(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, str(_write(tmp_path, {"seeds": [{"satno": 900, "disposition": "hostile"}]})))
        state = SimpleNamespace(interaction_store=None)
        store.hold_edges(state, "100", (_edge("100", "200"),), _NOW, store.Evaluated((_BURN,), store.SWEPT_KINDS))
        store.hold_edges(state, "200", (_edge("200", "900"),), _NOW, store.Evaluated((_BURN,), store.SWEPT_KINDS))
        held = store.held_interactions(state, "100", _NOW)
        (path,) = held.paths
        assert (path.seed, path.hops) == ("900", 2)
        assert held.notes[-1] == "hostile seed list held: 1 hostile seed; a benign entry propagates nothing"

    def test_with_none_configured_propagation_adds_nothing_and_the_ledger_says_so(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV, raising=False)
        state = SimpleNamespace(interaction_store=None)
        store.hold_edges(state, "100", (_edge("100", "900"),), _NOW, store.Evaluated((_BURN,), store.SWEPT_KINDS))
        held = store.held_interactions(state, "100", _NOW)
        assert held.paths == ()
        assert held.notes == ("no hostile seed list configured",)
        assert store.held_interactions(SimpleNamespace(), "100", _NOW).notes == ("no hostile seed list configured",)

    def test_the_held_object_grades_the_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_ENV, str(_write(tmp_path, {"seeds": [{"satno": 900, "disposition": "hostile"}]})))
        state = SimpleNamespace(interaction_store=None)
        store.hold_edges(state, "100", (_edge("100", "900"),), _NOW, store.Evaluated((_BURN,), store.SWEPT_KINDS))
        held = store.held_interactions(state, "100", _NOW)
        obj = HeldObject("100", None, None, None, Custody.HELD, interactions=held.edges, seed_paths=held.paths)
        labels = [i.label for i in obj.items(_NOW, "GEO")]
        assert "1 hop from hostile seed OBJ-900 (900)" in labels

