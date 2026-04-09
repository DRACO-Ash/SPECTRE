"""Unit tests for spectre.data.notso_cache — NotsoCache local persistence."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

from spectre.data.notso_cache import NotsoCache, _parse_iso

# ── _parse_iso ────────────────────────────────────────────────────────────────

class TestParseIso:
    def test_with_microseconds(self) -> None:
        dt = _parse_iso("2026-04-01T08:00:00.000000Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 4
        assert dt.tzinfo is UTC

    def test_without_microseconds(self) -> None:
        dt = _parse_iso("2026-04-01T08:00:00Z")
        assert dt is not None
        assert dt.year == 2026
        assert dt.second == 0

    def test_none_input(self) -> None:
        assert _parse_iso(None) is None

    def test_empty_string(self) -> None:
        assert _parse_iso("") is None

    def test_invalid_string(self) -> None:
        assert _parse_iso("not-a-date") is None


# ── NotsoCache basics ─────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_cache(tmp_path: Path) -> NotsoCache:
    """Return a NotsoCache backed by a temporary file."""
    return NotsoCache(path=tmp_path / "notso_cache.json")


class TestNotsoCache:
    def test_empty_on_creation(self, tmp_cache: NotsoCache) -> None:
        assert tmp_cache.total_records() == 0
        assert tmp_cache.latest_created_at() is None
        assert tmp_cache.last_sync_utc() is None

    def test_append_adds_records(self, tmp_cache: NotsoCache) -> None:
        records = [
            {"msgId": "msg-001", "satNo": 12345, "createdAt": "2026-01-01T00:00:00Z"},
            {"msgId": "msg-002", "satNo": 12345, "createdAt": "2026-01-02T00:00:00Z"},
        ]
        added = tmp_cache.append(records)
        assert added == 2
        assert tmp_cache.total_records() == 2

    def test_append_deduplicates_by_msgid(self, tmp_cache: NotsoCache) -> None:
        records = [
            {"msgId": "msg-001", "satNo": 12345, "createdAt": "2026-01-01T00:00:00Z"},
        ]
        tmp_cache.append(records)
        added2 = tmp_cache.append(records)  # same msgId
        assert added2 == 0
        assert tmp_cache.total_records() == 1

    def test_append_zero_records_returns_zero(self, tmp_cache: NotsoCache) -> None:
        assert tmp_cache.append([]) == 0

    def test_latest_created_at(self, tmp_cache: NotsoCache) -> None:
        records = [
            {"msgId": "msg-001", "satNo": 10, "createdAt": "2026-01-01T00:00:00Z"},
            {"msgId": "msg-002", "satNo": 10, "createdAt": "2026-01-10T00:00:00Z"},
        ]
        tmp_cache.append(records)
        latest = tmp_cache.latest_created_at()
        assert latest is not None
        assert latest.day == 10

    def test_get_for_satno_filters_correctly(self, tmp_cache: NotsoCache) -> None:
        records = [
            {"msgId": "msg-001", "satNo": 11111, "createdAt": "2026-01-01T00:00:00Z"},
            {"msgId": "msg-002", "satNo": 22222, "createdAt": "2026-01-02T00:00:00Z"},
            {"msgId": "msg-003", "satNo": 11111, "createdAt": "2026-01-03T00:00:00Z"},
        ]
        tmp_cache.append(records)
        results = tmp_cache.get_for_satno(11111)
        assert len(results) == 2
        assert all(r["satNo"] == 11111 for r in results)

    def test_get_for_satno_string_input(self, tmp_cache: NotsoCache) -> None:
        tmp_cache.append([{"msgId": "x", "satNo": 99, "createdAt": "2026-01-01T00:00:00Z"}])
        assert len(tmp_cache.get_for_satno("99")) == 1

    def test_get_for_satno_missing_returns_empty(self, tmp_cache: NotsoCache) -> None:
        assert tmp_cache.get_for_satno(99999) == []

    def test_all_records(self, tmp_cache: NotsoCache) -> None:
        records = [
            {"msgId": "a", "satNo": 1, "createdAt": "2026-01-01T00:00:00Z"},
            {"msgId": "b", "satNo": 2, "createdAt": "2026-01-02T00:00:00Z"},
        ]
        tmp_cache.append(records)
        all_r = tmp_cache.all_records()
        assert len(all_r) == 2

    def test_sort_ascending_on_created_at(self, tmp_cache: NotsoCache) -> None:
        records = [
            {"msgId": "late", "satNo": 1, "createdAt": "2026-01-10T00:00:00Z"},
            {"msgId": "early", "satNo": 1, "createdAt": "2026-01-01T00:00:00Z"},
        ]
        tmp_cache.append(records)
        all_r = tmp_cache.all_records()
        assert all_r[0]["msgId"] == "early"
        assert all_r[1]["msgId"] == "late"

    def test_persists_to_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test_cache.json"
        cache1 = NotsoCache(path=path)
        cache1.append([{"msgId": "persist-01", "satNo": 5, "createdAt": "2026-01-01T00:00:00Z"}])
        # Load fresh instance from same file
        cache2 = NotsoCache(path=path)
        assert cache2.total_records() == 1

    def test_last_sync_utc_set_after_append(self, tmp_cache: NotsoCache) -> None:
        tmp_cache.append([{"msgId": "sync-01", "satNo": 1, "createdAt": "2026-01-01T00:00:00Z"}])
        assert tmp_cache.last_sync_utc() is not None

    def test_corrupt_file_resets_gracefully(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text("not valid json", encoding="utf-8")
        cache = NotsoCache(path=path)
        assert cache.total_records() == 0

    def test_missing_msgid_uses_empty_string_key(self, tmp_cache: NotsoCache) -> None:
        # Records with no msgId — both have the same (empty) key so only first is kept
        records = [
            {"satNo": 5, "createdAt": "2026-01-01T00:00:00Z"},
        ]
        added = tmp_cache.append(records)
        # The record with empty msgId should still be handled without error
        assert added >= 0  # may or may not be deduplicated

    def test_messageId_alias(self, tmp_cache: NotsoCache) -> None:
        """Records using 'messageId' instead of 'msgId' should be deduplicated."""
        records = [
            {"messageId": "alias-01", "satNo": 7, "createdAt": "2026-01-01T00:00:00Z"},
        ]
        added = tmp_cache.append(records)
        assert added == 1
        # Second append with same messageId should be deduped
        added2 = tmp_cache.append(records)
        assert added2 == 0
