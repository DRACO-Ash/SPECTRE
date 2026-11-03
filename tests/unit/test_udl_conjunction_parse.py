"""UDL conjunction records are read tolerantly, or not at all (SPC-031).

The field names come from UDL's published API, not from a live reply: this
environment cannot reach UDL. So the reader accepts the plausible spellings,
skips a record with no time of closest approach, never raises on an
unexpected shape, and states the unit of a miss distance as UDL gives it.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest

from spectre.web.udl_conjunction import MAX_CONJUNCTIONS, read_conjunctions

_SATNO = 25544


def _as_sat1(**extra: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": "c-1", "tca": "2026-11-02T10:15:30.123456Z", "missDistance": 812.4,
        "collisionProb": 1.2e-5, "dataMode": "REAL",
        "satNo1": _SATNO, "satNo2": 48274,
        "sat1": {"satNo": _SATNO, "objectName": "ISS (ZARYA)"},
        "sat2": {"satNo": 48274, "objectName": "CSS (TIANHE)"},
    }
    rec.update(extra)
    return rec


def _as_sat2(**extra: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": "c-2", "tca": "2026-11-03T04:00:00Z", "missDistance": "1500",
        "dataMode": "EXERCISE", "satNo1": 33591, "satNo2": _SATNO,
        "sat1": {"satNo": 33591, "OBJECT_NAME": "NOAA 19"},
    }
    rec.update(extra)
    return rec


def _read(*pages: tuple[str, Any], fallback: str = "REAL") -> Any:
    return read_conjunctions(list(pages), _SATNO, fallback)


class TestTheOtherObject:
    def test_the_object_as_sat_1_names_sat_2(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1()])).rows
        assert (row.other_satno, row.other_name) == ("48274", "CSS (TIANHE)")

    def test_the_object_as_sat_2_names_sat_1(self) -> None:
        (row,) = _read(("satNo2", [_as_sat2()])).rows
        assert (row.other_satno, row.other_name) == ("33591", "NOAA 19")

    def test_a_record_with_no_side_numbers_falls_back_to_the_query_that_found_it(self) -> None:
        rec = {"tca": "2026-11-02T00:00:00Z", "sat1": {"objectName": "A"}, "sat2": {"objectName": "B"}}
        (row,) = _read(("satNo2", [rec])).rows
        assert (row.other_satno, row.other_name) == ("", "A")

    def test_a_record_with_one_side_number_falls_back_to_the_query_that_found_it(self) -> None:
        rec = {"tca": "2026-11-02T00:00:00Z", "satNo1": 11, "sat1": {"objectName": "A"}}
        (row,) = _read(("satNo2", [rec])).rows
        assert (row.other_satno, row.other_name) == ("11", "A")

    @pytest.mark.parametrize("found_by", ["satNo1", "satNo2"])
    def test_a_record_naming_two_other_objects_is_skipped_and_counted(self, found_by: str) -> None:
        """Two numbers, neither this object: UDL's figures for another pair, not this one."""
        rec = {"tca": "2026-11-02T00:00:00Z", "satNo1": 11, "satNo2": 22,
               "sat2": {"objectName": "UNRELATED"}, "missDistance": 5}
        reading = _read((found_by, [rec, _as_sat1()]))
        assert [r.other_satno for r in reading.rows] == ["48274"]
        assert (reading.usable, reading.unrelated, reading.skipped) == (1, 1, 0)

    def test_the_records_own_numbers_outrank_the_query_that_found_it(self) -> None:
        """Should UDL match either side on a satNo1 query, the record still says which is which."""
        (row,) = _read(("satNo1", [_as_sat2()])).rows
        assert row.other_satno == "33591"

    def test_a_state_vector_pair_is_read_when_sat_objects_are_absent(self) -> None:
        rec = {"tca": "2026-11-02T00:00:00Z", "stateVector1": {"satNo": _SATNO},
               "stateVector2": {"satNo": 40000, "objectName": "DEBRIS"}}
        (row,) = _read(("satNo1", [rec])).rows
        assert (row.other_satno, row.other_name) == ("40000", "DEBRIS")

    @pytest.mark.parametrize("spelling", [25544.0, "025544", " 25544 "])
    def test_a_number_spelt_another_way_still_finds_the_object(self, spelling: Any) -> None:
        """A float or zero-padded satNo1 is still the object, so the other side is sat 2."""
        (row,) = _read(("satNo2", [_as_sat1(satNo1=spelling, sat1={"satNo": spelling})])).rows
        assert row.other_satno == "48274"

    def test_an_other_object_number_is_shown_without_padding_or_a_decimal_point(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1(satNo2=48274.0, sat2={"satNo": "048274"})])).rows
        assert row.other_satno == "48274"

    def test_an_unnamed_other_object_has_no_name_rather_than_a_guess(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1(sat2="not an object")])).rows
        assert (row.other_satno, row.other_name) == ("48274", "")


class TestTimeOfClosestApproach:
    def test_a_record_with_no_tca_is_skipped_and_counted(self) -> None:
        no_tca = _as_sat1(id="c-3")
        del no_tca["tca"]
        reading = _read(("satNo1", [_as_sat1(), no_tca, _as_sat1(id="c-4", tca="not a time")]))
        assert [r.tca for r in reading.rows] == [datetime(2026, 11, 2, 10, 15, 30, 123456, tzinfo=UTC)]
        assert reading.skipped == 2

    def test_a_tca_with_no_offset_is_utc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """UTC, not the server's own zone: run here under Tokyo time to tell the two apart."""
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        time.tzset()
        try:
            (row,) = _read(("satNo1", [_as_sat1(tca="2026-11-02T10:15:30")])).rows
        finally:
            monkeypatch.undo()
            time.tzset()
        assert row.tca == datetime(2026, 11, 2, 10, 15, 30, tzinfo=UTC)
        assert row.tca_text == "2026-11-02 10:15:30 UTC"

    @pytest.mark.parametrize("edge", ["9999-12-31T23:59:59-01:00", "0001-01-01T00:30:00+01:00"])
    def test_a_tca_past_the_calendar_limits_is_skipped_not_raised(self, edge: str) -> None:
        reading = _read(("satNo1", [_as_sat1(), _as_sat1(id="edge", tca=edge)]))
        assert (len(reading.rows), reading.skipped) == (1, 1)

    @pytest.mark.parametrize("date_only", ["2026-11-02", "20261102", "2026-W44-1"])
    def test_a_date_with_no_time_is_not_a_time_of_closest_approach(self, date_only: str) -> None:
        """Midnight would claim a precision UDL never gave, so the record is skipped."""
        reading = _read(("satNo1", [_as_sat1(tca=date_only)]))
        assert (reading.rows, reading.skipped) == ([], 1)

    def test_an_offset_tca_is_converted_to_utc(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1(tca="2026-11-02T12:15:30+02:00")])).rows
        assert row.tca_text == "2026-11-02 10:15:30 UTC"

    def test_newest_tca_first_and_at_most_fifty(self) -> None:
        records = [_as_sat1(id=f"r{i}", tca=f"2026-10-{1 + i % 28:02d}T{i % 24:02d}:00:00Z") for i in range(70)]
        reading = _read(("satNo1", records))
        assert len(reading.rows) == MAX_CONJUNCTIONS == 50
        assert reading.usable == 70
        tcas = [r.tca for r in reading.rows]
        assert tcas == sorted(tcas, reverse=True)
        assert tcas[0] == max(datetime.fromisoformat(r["tca"]) for r in records)

    def test_the_same_record_from_both_queries_is_listed_once(self) -> None:
        reading = _read(("satNo1", [_as_sat1()]), ("satNo2", [_as_sat1()]))
        assert len(reading.rows) == 1

    def test_records_without_an_id_are_told_apart_by_their_tca(self) -> None:
        first = _as_sat1(tca="2026-11-02T01:00:00Z")
        second = _as_sat1(tca="2026-11-02T02:00:00Z")
        del first["id"], second["id"]
        reading = _read(("satNo1", [first, second]))
        assert [r.tca_text for r in reading.rows] == ["2026-11-02 02:00:00 UTC", "2026-11-02 01:00:00 UTC"]

    def test_the_same_record_without_an_id_from_both_queries_is_listed_once(self) -> None:
        rec = _as_sat1()
        del rec["id"]
        reading = _read(("satNo1", [rec]), ("satNo2", [dict(rec)]))
        assert (len(reading.rows), reading.usable) == (1, 1)


class TestMissDistance:
    def test_udl_missdistance_is_stated_in_metres(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1()])).rows
        assert row.miss_distance == "812.4 m"

    def test_a_unit_the_record_states_is_the_unit_shown(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1(missDistance=1.25, missDistanceUnit="km")])).rows
        assert row.miss_distance == "1.250 km"

    @pytest.mark.parametrize("blank", [" ", "", "\t"])
    def test_a_blank_unit_falls_back_to_metres(self, blank: str) -> None:
        (row,) = _read(("satNo1", [_as_sat1(missDistance=5, missDistanceUnit=blank)])).rows
        assert row.miss_distance == "5.0 m"

    def test_a_long_unit_is_cut_to_sixteen_characters(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1(missDistance=5, missDistanceUnit="m" * 40)])).rows
        assert row.miss_distance == "5.0 " + "m" * 16

    def test_a_miss_distance_of_zero_is_shown_as_zero(self) -> None:
        """Zero is a collision figure, not an unreadable one."""
        (row,) = _read(("satNo1", [_as_sat1(missDistance=0)])).rows
        assert row.miss_distance == "0.0 m"

    @pytest.mark.parametrize(("raw", "unit", "shown"), [
        (0.0004, "km", "0.0004 km"),
        (0.04, "m", "0.04 m"),
        (0.000012345, "km", "1.234e-05 km"),
    ])
    def test_a_small_figure_is_never_rounded_to_zero(self, raw: float, unit: str, shown: str) -> None:
        (row,) = _read(("satNo1", [_as_sat1(missDistance=raw, missDistanceUnit=unit)])).rows
        assert row.miss_distance == shown

    def test_a_numeric_string_is_read(self) -> None:
        (row,) = _read(("satNo2", [_as_sat2()])).rows
        assert row.miss_distance == "1,500.0 m"

    def test_the_cdm_keyword_spelling_is_read(self) -> None:
        rec = _as_sat1()
        del rec["missDistance"]
        rec["MISS_DISTANCE"] = 90
        (row,) = _read(("satNo1", [rec])).rows
        assert row.miss_distance == "90.0 m"

    @pytest.mark.parametrize("bad", ["far", -3, float("nan"), True, {"value": 1}])
    def test_an_unreadable_figure_says_so(self, bad: Any) -> None:
        (row,) = _read(("satNo1", [_as_sat1(missDistance=bad)])).rows
        assert row.miss_distance == "unreadable"

    def test_an_absent_figure_says_so(self) -> None:
        rec = _as_sat1()
        del rec["missDistance"]
        (row,) = _read(("satNo1", [rec])).rows
        assert row.miss_distance == "not given"


class TestCollisionProbability:
    def test_a_probability_is_shown(self) -> None:
        (row,) = _read(("satNo1", [_as_sat1()])).rows
        assert row.collision_prob == "1.20e-05"

    def test_an_absent_probability_says_so(self) -> None:
        (row,) = _read(("satNo2", [_as_sat2()])).rows
        assert row.collision_prob == "not given"

    @pytest.mark.parametrize(("raw", "shown"), [(0, "0"), (0.0, "0"), (1, "1.00e+00"), (1.0, "1.00e+00")])
    def test_the_ends_of_the_range_are_shown(self, raw: float, shown: str) -> None:
        (row,) = _read(("satNo1", [_as_sat1(collisionProb=raw)])).rows
        assert row.collision_prob == shown

    @pytest.mark.parametrize("bad", [1.5, -0.1, "high"])
    def test_a_probability_outside_zero_to_one_is_unreadable(self, bad: Any) -> None:
        (row,) = _read(("satNo1", [_as_sat1(collisionProb=bad)])).rows
        assert row.collision_prob == "unreadable"


class TestDataMode:
    def test_each_record_keeps_its_own_mode(self) -> None:
        reading = _read(("satNo1", [_as_sat1()]), ("satNo2", [_as_sat2()]), fallback="TEST")
        assert sorted(r.data_mode for r in reading.rows) == ["EXERCISE", "REAL"]

    def test_a_record_with_no_mode_takes_the_mode_the_fetch_asked_for(self) -> None:
        rec = _as_sat1()
        del rec["dataMode"]
        (row,) = _read(("satNo1", [rec]), fallback="SIMULATED").rows
        assert row.data_mode == "SIMULATED"


class TestUnexpectedShapes:
    @pytest.mark.parametrize("payload", [None, "text", 42, [], [1, "x", None], {"error": "x"}])
    def test_nothing_usable_never_raises(self, payload: Any) -> None:
        assert _read(("satNo1", payload)).rows == []

    def test_a_single_object_reply_is_one_record(self) -> None:
        assert len(_read(("satNo1", _as_sat1())).rows) == 1

    def test_non_object_entries_are_counted_as_skipped(self) -> None:
        assert _read(("satNo1", [_as_sat1(), "junk", 7])).skipped == 2
