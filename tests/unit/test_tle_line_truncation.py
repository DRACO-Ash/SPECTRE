"""The element set parser stores element set data and nothing else.

A TLE line is 69 columns by definition, the last of them the checksum. A UDL
element set whose line 1 carried a script payload appended past column 69
parsed cleanly, and the whole line, payload included, was stored on the record
and rendered to the operator from there. The template escaping is one half of
the answer; this covers the other half, which is that the payload never
reaches the record at all.
"""

from __future__ import annotations

from spectre.astro.pattern_of_life import _TLE_LINE_COLUMNS, parse_tle_history

# A well-formed element set, both lines exactly 69 columns wide.
_LINE1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005"
_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"

_PAYLOAD = "<img src=x onerror=alert(document.cookie)>"


class TestTheParserCutsEachLineToTheDefinedWidth:
    """Column 69 is the end of the element set, so it is the end of the record."""

    def test_the_fixture_is_the_width_the_standard_defines(self) -> None:
        assert len(_LINE1) == _TLE_LINE_COLUMNS
        assert len(_LINE2) == _TLE_LINE_COLUMNS

    def test_text_appended_past_column_69_does_not_reach_the_record(self) -> None:
        records = parse_tle_history(f"{_LINE1}{_PAYLOAD}\n{_LINE2}")

        assert len(records) == 1
        assert _PAYLOAD not in records[0].tle
        assert "<img" not in records[0].tle
        for line in records[0].tle.splitlines():
            assert len(line) <= _TLE_LINE_COLUMNS

    def test_the_element_set_itself_still_parses_and_is_kept_whole(self) -> None:
        clean = parse_tle_history(f"{_LINE1}\n{_LINE2}")
        smuggled = parse_tle_history(f"{_LINE1}{_PAYLOAD}\n{_LINE2}{_PAYLOAD}")

        assert clean[0].tle == f"{_LINE1}\n{_LINE2}"
        assert smuggled[0].tle == clean[0].tle
        assert smuggled[0].epoch == clean[0].epoch
        assert smuggled[0].sma_km == clean[0].sma_km
        assert smuggled[0].inc_deg == clean[0].inc_deg
        assert smuggled[0].element_set_no == clean[0].element_set_no
