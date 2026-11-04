"""The periods of time the NOTSO cache covers, which a NOTSO prior counts its rate over (SPC-130).

From the first record's creation to the last sync, never past the moment asked
about, and less every spell of more than a week with no record for any object:
a rate over time the cache did not cover would read the gap as quiet. No test
reads the wall clock.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from spectre.data.notso_cache import COVER_REACH, NotsoCache

_NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _cache(tmp_path: Path, created: list[str], last_sync: str | None) -> NotsoCache:
    path = tmp_path / "notso_cache.json"
    records = [{"id": f"n{i}", "createdAt": c, "msgBody": {"SatIds": ["50322"]}} for i, c in enumerate(created)]
    path.write_text(json.dumps({"metadata": {"last_sync_utc": last_sync, "total_records": len(records)},
                                "records": records}), encoding="utf-8")
    return NotsoCache(path)


def test_an_empty_cache_covers_no_period(tmp_path: Path) -> None:
    assert _cache(tmp_path, [], None).covered_periods(_NOW) == ()


def test_a_record_covers_the_reach_either_side_of_it_from_the_first_record_to_the_last_sync(tmp_path: Path) -> None:
    created = ["2025-01-02T00:00:00.000Z", "2025-01-08T00:00:00.000Z", "2025-01-14T00:00:00.000Z"]
    cache = _cache(tmp_path, created, "2025-01-16T00:00:00Z")
    assert timedelta(days=3.5) == COVER_REACH
    assert cache.covered_periods(_NOW) == ((datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 16, tzinfo=UTC)),)


def test_with_no_sync_recorded_it_ends_at_the_newest_record(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ["2025-01-02T00:00:00.000Z", "2025-01-06T00:00:00.000Z"], None)
    assert cache.covered_periods(_NOW) == ((datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 6, tzinfo=UTC)),)


def test_it_never_runs_past_the_moment_asked_about(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ["2026-11-01T00:00:00.000Z", "2026-11-03T00:00:00.000Z"], "2027-01-01T00:00:00Z")
    assert cache.covered_periods(_NOW) == ((datetime(2026, 11, 1, tzinfo=UTC), _NOW),)


def test_records_after_the_moment_asked_about_cover_nothing(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ["2025-01-02T00:00:00.000Z", "2026-12-25T00:00:00.000Z"], "2026-12-25T00:00:00Z")
    assert cache.covered_periods(_NOW) == ((datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 5, 12, tzinfo=UTC)),)


def test_a_week_with_no_record_for_any_object_is_a_gap_in_the_cache_not_a_quiet_week(tmp_path: Path) -> None:
    # The JCO files several notices a day across all objects, so more than 7 days with none is a gap in what was
    # synced (a sync stopped part way, a page never fetched), not a quiet week: it is left out of the cover, and a
    # rate counted over the cover never reads it as inactivity. Each record covers the 3.5 days either side of it.
    created = ["2025-01-02T00:00:00.000Z", "2025-01-05T00:00:00.000Z", "2025-03-01T00:00:00.000Z"]
    cache = _cache(tmp_path, created, "2025-03-02T00:00:00Z")
    assert cache.covered_periods(_NOW) == (
        (datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 8, 12, tzinfo=UTC)),
        (datetime(2025, 2, 25, 12, tzinfo=UTC), datetime(2025, 3, 2, tzinfo=UTC)),
    )


def test_a_last_sync_long_after_the_newest_record_does_not_cover_the_months_between(tmp_path: Path) -> None:
    # The sync stamps its time on any append, so a sync that stopped after one page still dates the whole cache to
    # that moment; the months after the newest record hold nothing and are not covered.
    cache = _cache(tmp_path, ["2025-11-10T00:00:00.000Z", "2025-11-13T00:00:00.000Z"], "2026-04-07T15:46:29Z")
    assert cache.covered_periods(_NOW) == ((datetime(2025, 11, 10, tzinfo=UTC), datetime(2025, 11, 16, 12, tzinfo=UTC)),)


def test_a_record_with_no_creation_time_does_not_hide_the_rest(tmp_path: Path) -> None:
    # append sorts a record with no createdAt first; it says nothing of when the cache was filled, so it is passed
    # over rather than read as an empty cache.
    cache = _cache(tmp_path, ["", "2025-01-02T00:00:00.000Z", "2025-01-04T00:00:00.000Z"], "2025-01-04T00:00:00Z")
    assert cache.covered_periods(_NOW) == ((datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 4, tzinfo=UTC)),)


def test_a_last_sync_stamped_before_the_newest_record_does_not_cut_the_cover_short(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ["2025-01-02T00:00:00.000Z", "2025-01-06T00:00:00.000Z"], "2025-01-03T00:00:00Z")
    assert cache.covered_periods(_NOW) == ((datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 6, tzinfo=UTC)),)
