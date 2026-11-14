"""The acceptance check refuses an SGP4-XP element set and an uncorrelated track (charming-dirac 7ed9d0b).

Line 1 column 63 of a TLE is its ephemeris type. Every propagator here is SGP4, which assumes type 0. A type 4 set is
SGP4-XP: its line 1 fields carry different terms, and the sgp4 package propagates it without an error to a wrong orbit.
UDL also files uncorrelated tracks (UCT), sets not yet tied to the object, under a catalogue number. Neither may be
stored, so check_elset, the one check every ingest path runs (SPC-201), refuses both. The type is read from the UDL
record's ephemType when it carries one, else from column 63; UCT is the record's own flag. A refusal names the type
and never the set's text.
"""

from __future__ import annotations

import pytest

from spectre.astro.elset_check import check_elset
from tests.unit._decision_reference import PLANE_CHANGE, _checksum

_GOOD = PLANE_CHANGE.red_tle
_XP_FAILS = "it is an SGP4-XP set (ephemeris type 4), which SGP4 would propagate to a wrong orbit without an error"
_UCT_FAILS = "it is an uncorrelated track (UCT), not a set correlated to the object"


def _typed(tle: str, column_63: str) -> str:
    """*tle* with line 1 column 63 set to *column_63*, its checksum made good."""
    line1, line2 = tle.splitlines()
    body = line1[:62] + column_63 + line1[63:68]
    return f"{body}{_checksum(body)}\n{line2}"


class TestTheEphemerisType:
    def test_the_reference_set_is_type_0(self) -> None:
        assert _GOOD.splitlines()[0][62] == "0"
        assert check_elset(_GOOD).accepted

    def test_a_blank_type_is_read_as_sgp4(self) -> None:
        assert check_elset(_typed(_GOOD, " ")).accepted

    def test_an_sgp4_xp_set_is_refused_by_line_1(self) -> None:
        assert check_elset(_typed(_GOOD, "4")).failures == (_XP_FAILS,)

    def test_another_type_is_refused_and_named(self) -> None:
        assert check_elset(_typed(_GOOD, "2")).failures == (
            "its ephemeris type is 2, not 0, the SGP4 type every propagator here assumes",
        )

    def test_a_type_that_does_not_read_is_refused(self) -> None:
        assert check_elset(_typed(_GOOD, "X")).failures == ("its ephemeris type cannot be read",)

    @pytest.mark.parametrize("field", [4, "4", " 4 "])
    def test_the_records_type_is_read_before_line_1(self, field: object) -> None:
        assert check_elset(_GOOD, record={"ephemType": field}).failures == (_XP_FAILS,)

    @pytest.mark.parametrize("field", [0, "0"])
    def test_a_record_of_type_0_is_accepted(self, field: object) -> None:
        assert check_elset(_GOOD, record={"ephemType": field, "uct": False}).accepted

    def test_a_record_with_no_type_falls_back_to_line_1(self) -> None:
        assert check_elset(_typed(_GOOD, "4"), record={"ephemType": None}).failures == (_XP_FAILS,)

    @pytest.mark.parametrize("field", [0, "0", "", "  "])
    def test_a_record_cannot_hide_a_type_4_on_line_1(self, field: object) -> None:
        assert check_elset(_typed(_GOOD, "4"), record={"ephemType": field}).failures == (_XP_FAILS,)

    @pytest.mark.parametrize("field", ["", "  "])
    def test_a_blank_record_type_falls_back_to_line_1(self, field: object) -> None:
        assert check_elset(_GOOD, record={"ephemType": field}).accepted

    def test_the_type_is_named_beside_the_sets_other_failures(self) -> None:
        line1, line2 = _typed(_GOOD, "4").splitlines()
        assert check_elset(f"{line1}\n{line2[:68]}0", 90002).failures == ("line 2 fails its checksum", _XP_FAILS)

    def test_the_refusal_never_quotes_the_set(self) -> None:
        sentence = check_elset(_typed(_GOOD, "4")).refusal("SY-12 (90002)")
        assert sentence == f"The element set for SY-12 (90002) was refused: {_XP_FAILS}. It was not stored."
        assert all(line not in sentence for line in _GOOD.splitlines())


class TestUncorrelatedTracks:
    def test_a_uct_record_is_refused(self) -> None:
        assert check_elset(_GOOD, record={"uct": True}).failures == (_UCT_FAILS,)

    @pytest.mark.parametrize("flag", [False, None, "true"])
    def test_only_a_true_flag_marks_a_uct(self, flag: object) -> None:
        """UDL's uct is a JSON boolean; a string is not read as one."""
        assert check_elset(_GOOD, record={"uct": flag}).accepted

    def test_a_uct_of_type_4_names_both(self) -> None:
        assert check_elset(_GOOD, record={"uct": True, "ephemType": 4}).failures == (_XP_FAILS, _UCT_FAILS)


class TestTheTypeForTheLog:
    @pytest.mark.parametrize(("tle", "record", "named"), [
        (_GOOD, None, ""),
        (_typed(_GOOD, "4"), None, "SGP4-XP (type 4)"),
        (_GOOD, {"ephemType": 2}, "ephemeris type 2"),
        (_typed(_GOOD, "X"), None, "an unreadable ephemeris type"),
        (_GOOD, {"uct": True}, "UCT"),
        (_GOOD, {"uct": True, "ephemType": 4}, "SGP4-XP (type 4), UCT"),
    ])
    def test_what_a_set_was_refused_as_is_named_in_a_few_words(
        self, tle: str, record: dict[str, object] | None, named: str,
    ) -> None:
        from spectre.astro.elset_check import refused_type

        assert refused_type(tle, record) == named
