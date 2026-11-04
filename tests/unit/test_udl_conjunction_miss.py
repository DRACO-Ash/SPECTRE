"""A UDL conjunction's miss distance as a figure Interactions can judge, or refused and why (SPC-173).

The panel keeps showing UDL's figure as filed. For an edge the figure must be
a number in a unit SPECTRE knows: the miss distance arrives as a string as
often as a number, and a malformed one (a thousands separator, a unit written
into the number, a word) is refused with a reason, never guessed. The reason
never repeats UDL's text, which reaches only the escaped panel.
"""

from __future__ import annotations

from typing import Any

import pytest

from spectre.web.udl_conjunction import read_conjunctions

_SATNO = 25544


def _row(**extra: Any) -> Any:
    rec: dict[str, Any] = {"id": "c-1", "tca": "2026-11-02T10:15:30Z", "satNo1": _SATNO, "satNo2": 48274}
    rec.update(extra)
    (row,) = read_conjunctions([("satNo1", [rec])], _SATNO, "REAL").rows
    return row


class TestAReadableFigure:
    @pytest.mark.parametrize(("raw", "km"), [(812.4, 0.8124), ("1500", 1.5), (" 12000.0 ", 12.0), (0, 0.0)])
    def test_metres_by_default_whether_a_number_or_a_string(self, raw: Any, km: float) -> None:
        row = _row(missDistance=raw)
        assert row.miss_km == pytest.approx(km)
        assert row.miss_problem == ""

    @pytest.mark.parametrize("unit", ["km", "KM", "kilometres", "kilometers", " km "])
    def test_a_stated_unit_of_kilometres_is_honoured(self, unit: str) -> None:
        assert _row(missDistance="3.5", missDistanceUnit=unit).miss_km == pytest.approx(3.5)

    @pytest.mark.parametrize("unit", ["m", "M", "metres", "meters"])
    def test_a_stated_unit_of_metres_is_honoured(self, unit: str) -> None:
        assert _row(missDistance="3500", missDistanceUnits=unit).miss_km == pytest.approx(3.5)

    @pytest.mark.parametrize("unit", ["", "   "])
    def test_a_blank_stated_unit_is_metres_as_the_panel_shows_it(self, unit: str) -> None:
        """Review finding 9: one figure, one reading; the panel already shows a blank unit as metres."""
        row = _row(missDistance="1500", missDistanceUnit=unit)
        assert (row.miss_km, row.miss_problem, row.miss_distance) == (pytest.approx(1.5), "", "1,500.0 m")


class TestAMalformedFigureIsRefused:
    @pytest.mark.parametrize("raw", ["1,234.5", "12 km", "about 40", "", "  ", "0x1F", "1e400", "nan", "-3", -3.0,
                                     True, [12.0], {"value": 12}])
    def test_it_is_not_a_figure_and_the_reason_says_so(self, raw: Any) -> None:
        row = _row(missDistance=raw)
        assert row.miss_km is None
        assert row.miss_problem == "the miss distance UDL filed is not a finite, non-negative number"

    def test_the_reason_never_repeats_udls_text(self) -> None:
        row = _row(missDistance="<script>alert(1)</script>")
        assert "script" not in row.miss_problem

    def test_none_filed_says_so(self) -> None:
        row = _row()
        assert (row.miss_km, row.miss_problem) == (None, "UDL filed no miss distance")

    @pytest.mark.parametrize("unit", ["furlongs", "nmi", "ft", "<b>km</b>"])
    def test_a_unit_it_does_not_know_is_refused(self, unit: str) -> None:
        row = _row(missDistance="12", missDistanceUnit=unit)
        assert row.miss_km is None
        assert row.miss_problem == "the miss distance UDL filed is in a unit SPECTRE does not read"

    def test_the_panel_still_shows_what_was_filed(self) -> None:
        assert _row(missDistance="1,234.5").miss_distance == "unreadable"
