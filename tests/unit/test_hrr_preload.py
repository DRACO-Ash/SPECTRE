"""Tests for the startup HRR pre-load.

This runs during boot, so its failure behaviour matters more than its happy
path: a malformed or unreadable cache must degrade to "threat sweep needs a UDL
login", never stop the container from starting.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from spectre.web import app as app_module


@pytest.fixture()
def hrr_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader at a temporary data directory."""
    monkeypatch.setattr(
        app_module, "_hrr_candidate_paths", lambda: [tmp_path / "HRR_List.json"]
    )
    return tmp_path


@pytest.fixture()
def store_writes(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record what the loader writes to the default HRR store, without writing it."""
    writes: list[object] = []
    monkeypatch.setattr(app_module, "set_default_hrr_objects", writes.append)
    monkeypatch.setattr(app_module, "set_default_hrr_tles", lambda *a, **k: None)
    return writes


_NOTIFICATION = [
    {
        "createdAt": "2026-03-04T12:00:00.000Z",
        "msgBody": [
            {"satNo": "25544", "commonName": "ALPHA", "country": "US", "rank": 1,
             "orbitRegime": "LEO"},
            {"satNo": "40000", "commonName": "BRAVO", "country": "CN", "rank": 2,
             "orbitRegime": "GEO"},
        ],
    }
]


class TestHrrPreload:
    def test_loads_satellites_from_the_data_directory(
        self, hrr_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (hrr_dir / "HRR_List.json").write_text(json.dumps(_NOTIFICATION), encoding="utf-8")
        with caplog.at_level(logging.INFO):
            app_module._load_hrr_from_disk()
        assert "HRR pre-load" in caplog.text

    def test_absent_file_warns_and_does_not_raise(
        self, hrr_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            app_module._load_hrr_from_disk()
        assert "not found" in caplog.text

    def test_empty_notification_list_is_a_no_op(
        self, hrr_dir: Path, store_writes: list[object]
    ) -> None:
        (hrr_dir / "HRR_List.json").write_text("[]", encoding="utf-8")
        app_module._load_hrr_from_disk()
        assert store_writes == [], "an empty list must leave the default HRR store alone"

    def test_malformed_json_is_logged_and_swallowed(
        self, hrr_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A corrupt cache must not stop the boot."""
        (hrr_dir / "HRR_List.json").write_text("{not json at all", encoding="utf-8")
        with caplog.at_level(logging.ERROR):
            app_module._load_hrr_from_disk()
        assert "Failed to pre-load" in caplog.text

    def test_an_object_instead_of_a_list_is_rejected_at_the_boundary(
        self, hrr_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Valid JSON of the wrong shape must degrade, not crash the boot."""
        (hrr_dir / "HRR_List.json").write_text('{"unexpected": "object"}', encoding="utf-8")
        with caplog.at_level(logging.ERROR):
            app_module._load_hrr_from_disk()
        assert "expected a list of notifications" in caplog.text

    def test_non_dict_entries_are_discarded(
        self, hrr_dir: Path, store_writes: list[object]
    ) -> None:
        """A list containing junk entries must not reach the parser."""
        (hrr_dir / "HRR_List.json").write_text('["junk", 42, null]', encoding="utf-8")
        app_module._load_hrr_from_disk()
        assert store_writes == [], "junk entries must not replace the default HRR store"

    def test_a_good_entry_survives_junk_beside_it(
        self, hrr_dir: Path, store_writes: list[object]
    ) -> None:
        """Discarding junk keeps the real notification next to it."""
        (hrr_dir / "HRR_List.json").write_text(
            json.dumps(["junk", *_NOTIFICATION, 42]), encoding="utf-8",
        )
        app_module._load_hrr_from_disk()
        assert len(store_writes) == 1
        assert {o["satno"] for o in store_writes[0]} == {"25544", "40000"}  # type: ignore[attr-defined]
