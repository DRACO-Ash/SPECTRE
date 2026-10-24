"""The NOTSO cache reads the records UDL actually returns.

Audit F-046: the cache read ``msgId``, a top-level ``satNo`` and ``msgText``,
but the 500 TACREP_NOTSO records in the committed file carry ``id``,
``msgBody`` and ``msgBody.SatIds`` and none of those three keys. Deduplication
never fired, ``get_for_satno`` returned nothing for every object, and the cache
path of /pol/notso-correlate always answered "No NOTSOs in local cache".

Audit F-062 and F-141: the file lived inside the installed package, outside
the configured data directory, and every sync page rewrote it in place on the
event loop, so a crash mid-write left a corrupt file that was silently reset.

The record below is redacted: same shape as a real one, invented values.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from spectre.astro.notso import NOTSOType, parse_notso_text
from spectre.data import notso_cache
from spectre.data.notso_cache import NotsoCache, message_text, record_satnos


def _record(**body: Any) -> dict[str, Any]:
    msg_body = {
        "Event_Class": "Maneuver / TEST-SAT (99001) / GEO",
        "Event_Type": "Other",
        "Event_Description": "Jday 002 1934z\n\nProviders report a change on TEST-SAT, 99001.",
        "Date_Time": None,
        "Publish_Date": "2024-01-02T19:52:06.160Z",
        "NOTSO": "x000_02Jan-1952Z",
        "SatIds": ["99001", "99002"],
    }
    msg_body.update(body)
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "createdAt": "2024-01-02T19:52:06.160Z",
        "msgType": "TACREP_NOTSO",
        "source": "JCO",
        "dataMode": "REAL",
        "msgBody": msg_body,
    }


class TestTheRealShape:
    def test_a_record_is_deduplicated_on_its_id(self, tmp_path: Path) -> None:
        cache = NotsoCache(path=tmp_path / "c.json")
        assert cache.append([_record()]) == 1
        assert cache.append([_record()]) == 0

    def test_every_listed_satellite_finds_it(self, tmp_path: Path) -> None:
        cache = NotsoCache(path=tmp_path / "c.json")
        cache.append([_record()])
        assert len(cache.get_for_satno(99001)) == 1
        assert len(cache.get_for_satno("99002")) == 1
        assert cache.get_for_satno(12345) == []

    @pytest.mark.parametrize(("sat_ids", "expected"), [
        (["99001", "-"], {"99001"}),
        (None, set()),
        ("['99001', '99002']", {"99001", "99002"}),
    ])
    def test_sat_ids_in_their_observed_forms(self, sat_ids: Any, expected: set[str]) -> None:
        assert record_satnos(_record(SatIds=sat_ids)) == expected


class TestTheParseText:
    def test_the_event_time_type_and_satellite_are_read(self) -> None:
        [notso] = parse_notso_text(message_text(_record(), "99002"))
        assert notso.norad_id == 99002
        assert notso.notso_type is NOTSOType.MANOEUVRE
        assert notso.effective_start_utc == datetime(2024, 1, 2, 19, 34, tzinfo=UTC)
        assert "effective start" not in notso.inferred_fields

    def test_a_julian_day_across_new_year_takes_the_earlier_year(self) -> None:
        rec = _record(Event_Description="Jday 365 2300z\nlate in the year")
        rec["createdAt"] = "2025-01-01T01:00:00.000Z"
        [notso] = parse_notso_text(message_text(rec, "99001"))
        assert notso.effective_start_utc == datetime(2024, 12, 30, 23, 0, tzinfo=UTC)

    def test_no_event_time_is_flagged_as_inferred(self) -> None:
        [notso] = parse_notso_text(message_text(_record(Event_Description="no time given"), "99001"))
        assert "effective start" in notso.inferred_fields

    def test_a_launch_is_not_read_as_a_manoeuvre(self) -> None:
        rec = _record(Event_Class="Launch / TEST-LV (99003) / Payload (99004) / LEO")
        [notso] = parse_notso_text(message_text(rec, "99001"))
        assert notso.notso_type is NOTSOType.LAUNCH


def test_the_committed_records_are_now_usable() -> None:
    """Against the bundled file: 0 of 500 were reachable by satellite before."""
    bundled = Path(notso_cache.__file__).with_name("notso_cache.json")
    records = json.loads(bundled.read_text(encoding="utf-8"))["records"]
    reachable = [r for r in records if record_satnos(r)]
    assert len(reachable) > 400
    parsed = sum(1 for r in reachable if parse_notso_text(message_text(r, sorted(record_satnos(r))[0])))
    assert parsed == len(reachable)


class TestWhereAndHowItIsWritten:
    def test_the_cache_lives_in_the_configured_data_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SPECTRE_DATA_DIR", str(tmp_path))
        path = notso_cache.default_cache_path()
        assert path.parent == tmp_path

    def test_a_new_data_directory_is_seeded_from_the_bundled_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SPECTRE_DATA_DIR", str(tmp_path))
        cache = NotsoCache()
        assert cache.total_records() == 500

    def test_a_failed_write_leaves_the_previous_file_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "c.json"
        cache = NotsoCache(path=path)
        cache.append([_record()])
        before = path.read_text(encoding="utf-8")

        def _half_written(_obj: Any, fh: Any, **_k: Any) -> None:
            fh.write('{"metadata": {"truncated')
            raise OSError("disk full")

        monkeypatch.setattr(notso_cache.json, "dump", _half_written)
        second = _record()
        second["id"] = "00000000-0000-0000-0000-000000000002"
        with pytest.raises(OSError):
            cache.append([second])
        assert path.read_text(encoding="utf-8") == before
        assert not list(tmp_path.glob("*.tmp")), "the temporary file is cleaned up"

    def test_a_corrupt_file_is_kept_aside_not_discarded(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{not json", encoding="utf-8")
        cache = NotsoCache(path=path)
        assert cache.total_records() == 0
        kept = list(tmp_path.glob("c.json.corrupt-*"))
        assert len(kept) == 1
        assert kept[0].read_text(encoding="utf-8") == "{not json"
