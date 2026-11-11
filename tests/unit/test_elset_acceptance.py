"""One acceptance check for an element set, before anything stores it (SPC-201, evaluation F-25 and F-34).

Element sets from UDL reached the engine with no checksum or range check: evaluation probe P-14 changed one digit of
a set's inclination, 97.4 to 98.4 degrees, leaving the old checksum, and the computed miss moved from 10.4 to 13.4 km
with no flag; an inclination of 597.4 degrees was accepted. spectre.astro.elset_check.check_elset is the one check
every ingest path now runs: both line checksums, both line numbers, one catalogue number on both lines, and every
field the engine reads inside its range. These tests hold the check itself; each ingest path has its own test in
test_elset_ingest_paths.py.
"""

from __future__ import annotations

import pytest

from spectre.astro.elset_check import HELD_KEPT, NOT_STORED, ElsetCheck, check_elset
from tests.unit._decision_reference import GEO_DRIFT_IN, PLANE_CHANGE, _checksum

_GOOD = PLANE_CHANGE.red_tle


def _line(tle: str, n: int) -> str:
    return tle.splitlines()[n - 1]


def _with(tle: str, n: int, start: int, text: str, *, checksum: bool = True) -> str:
    """*tle* with columns *start* onwards of line *n* (0-indexed) overwritten by *text*, its checksum made good unless
    *checksum* is False, when the old one is kept as a transmission error would leave it."""
    lines = tle.splitlines()
    line = lines[n - 1]
    body = line[:start] + text + line[start + len(text):68]
    lines[n - 1] = body + (_checksum(body) if checksum else line[68])
    return "\n".join(lines)


class TestASoundSetIsAccepted:
    @pytest.mark.parametrize("tle", [PLANE_CHANGE.red_tle, PLANE_CHANGE.blue_tle, GEO_DRIFT_IN.red_tle])
    def test_a_reference_set_passes(self, tle: str) -> None:
        check = check_elset(tle)
        assert check.accepted and check.failures == ()

    def test_a_name_line_above_the_two_lines_is_read_past(self) -> None:
        assert check_elset(f"PROBE RED\n{_GOOD}").accepted

    def test_surrounding_blank_lines_and_spaces_are_read_past(self) -> None:
        assert check_elset(f"\n  {_line(_GOOD, 1)}  \n\n{_line(_GOOD, 2)}\n").accepted


class TestTheProbeCaseIsRefused:
    def test_one_digit_changed_with_the_old_checksum_is_refused(self) -> None:
        """P-14's UDL case inverted: inclination 97.4 to 98.4 degrees, the checksum left as it was."""
        corrupted = _with(_GOOD, 2, 10, "8", checksum=False)
        assert _line(corrupted, 2)[8:16] == " 98.4000"
        check = check_elset(corrupted)
        assert not check.accepted
        assert check.failures == ("line 2 fails its checksum",)

    def test_the_inclination_of_597_degrees_is_refused_even_with_a_good_checksum(self) -> None:
        """F-34: 597.4 degrees was accepted and gave a computed miss of 356.0 km."""
        absurd = _with(_GOOD, 2, 8, "5")
        assert _line(absurd, 2)[8:16] == "597.4000"
        assert check_elset(absurd).failures == ("the inclination, 597.4 degrees, is outside 0 to 180",)

    def test_with_its_checksum_also_wrong_both_failures_are_named(self) -> None:
        absurd = _with(_GOOD, 2, 8, "5", checksum=False)
        assert check_elset(absurd).failures == (
            "line 2 fails its checksum", "the inclination, 597.4 degrees, is outside 0 to 180",
        )


class TestEachLineIsChecked:
    def test_a_line_1_checksum_is_checked(self) -> None:
        assert check_elset(_with(_GOOD, 1, 40, "9", checksum=False)).failures == ("line 1 fails its checksum",)

    def test_a_short_line_is_refused_by_its_length(self) -> None:
        line1, line2 = _GOOD.splitlines()
        assert check_elset(f"{line1}\n{line2[:60]}").failures[0] == "line 2 is 60 characters long, not 69"

    def test_one_line_alone_is_refused(self) -> None:
        assert check_elset(_line(_GOOD, 2)).failures == ("it does not hold two element lines",)

    def test_nothing_is_refused(self) -> None:
        assert check_elset("   ").failures == ("it does not hold two element lines",)

    def test_lines_in_the_wrong_order_are_refused_by_their_numbers(self) -> None:
        line1, line2 = _GOOD.splitlines()
        assert check_elset(f"{line2}\n{line1}").failures[:2] == (
            "the first line does not begin with its line number, 1",
            "the second line does not begin with its line number, 2",
        )

    def test_another_line_number_is_refused(self) -> None:
        assert "the first line does not begin with its line number, 1" in check_elset(
            _with(_GOOD, 1, 0, "3"),
        ).failures


class TestTheCatalogueNumber:
    def test_two_different_numbers_are_refused(self) -> None:
        assert check_elset(_with(_GOOD, 2, 2, "90003")).failures == (
            "the catalogue numbers on line 1 and line 2 differ",
        )

    def test_a_blank_number_is_refused(self) -> None:
        blank = _with(_with(_GOOD, 1, 2, "     "), 2, 2, "     ")
        assert check_elset(blank).failures == ("line 1 carries no catalogue number",)

    @pytest.mark.parametrize("field", ["10-02", "9 002", "I0002", "a0002"])
    def test_a_number_that_does_not_read_as_one_is_refused(self, field: str) -> None:
        """Five digits or an Alpha-5 letter and four digits (spectre.astro.catalogue); anything else is no number."""
        unread = _with(_with(_GOOD, 1, 2, field), 2, 2, field)
        assert check_elset(unread).failures == ("the catalogue number on line 1 cannot be read",)

    def test_an_alpha_5_number_is_accepted(self) -> None:
        assert check_elset(_with(_with(_GOOD, 1, 2, "A0002"), 2, 2, "A0002")).accepted


class TestEachFieldIsInItsRange:
    @pytest.mark.parametrize(
        ("start", "text", "failure"),
        [
            (8, "180.0001", "the inclination, 180.0001 degrees, is outside 0 to 180"),
            (8, " -0.0001", "the inclination, -0.0001 degrees, is outside 0 to 180"),
            (17, "360.0001", "the right ascension of the ascending node, 360.0001 degrees, is outside 0 to 360"),
            (34, "400.0000", "the argument of perigee, 400.0 degrees, is outside 0 to 360"),
            (43, " -1.0000", "the mean anomaly, -1.0 degrees, is outside 0 to 360"),
            (52, " 0.00000000", "the mean motion, 0.0 revolutions a day, is not above 0"),
            (52, "-1.00000000", "the mean motion, -1.0 revolutions a day, is not above 0"),
        ],
    )
    def test_a_field_outside_its_range_is_refused(self, start: int, text: str, failure: str) -> None:
        assert check_elset(_with(_GOOD, 2, start, text)).failures == (failure,)

    @pytest.mark.parametrize(
        ("start", "text"),
        [(8, "  0.0000"), (8, "180.0000"), (17, "360.0000"), (34, "  0.0000"), (43, "359.9999")],
    )
    def test_the_ends_of_each_range_are_accepted(self, start: int, text: str) -> None:
        assert check_elset(_with(_GOOD, 2, start, text)).accepted

    @pytest.mark.parametrize(
        ("start", "text", "failure"),
        [
            (8, "  nan   ", "the inclination cannot be read"),
            (17, "  ab.cde", "the right ascension of the ascending node cannot be read"),
            (26, "00-0001", "the eccentricity cannot be read"),
            (26, "0.00001", "the eccentricity cannot be read"),
            (34, "        ", "the argument of perigee cannot be read"),
            (43, "  1.7.00", "the mean anomaly cannot be read"),
            (52, "        inf", "the mean motion cannot be read"),
        ],
    )
    def test_a_field_that_cannot_be_read_is_refused(self, start: int, text: str, failure: str) -> None:
        assert check_elset(_with(_GOOD, 2, start, text)).failures == (failure,)

    def test_an_eccentricity_inside_the_range_is_accepted(self) -> None:
        assert check_elset(_with(_GOOD, 2, 26, "0500000")).accepted


class TestSgp4MustBeAbleToStart:
    """Fields each inside their range can still describe no orbit SGP4 can start from; its own error code says so."""

    @pytest.mark.parametrize(
        ("start", "text", "failure"),
        [
            (26, "9999999", "SGP4 cannot start from it: its error 4, the orbit's semi-latus rectum is below 0"),
            (52, "20.00000000", "SGP4 cannot start from it: its error 6, the orbit lies inside the Earth"),
        ],
    )
    def test_an_orbit_sgp4_refuses_is_refused(self, start: int, text: str, failure: str) -> None:
        assert check_elset(_with(_GOOD, 2, start, text)).failures == (failure,)

    @pytest.mark.parametrize("epoch", ["26400.50000000", "26000.50000000", "2629x.50000000", "              "])
    def test_an_epoch_that_cannot_be_read_is_refused(self, epoch: str) -> None:
        assert check_elset(_with(_GOOD, 1, 18, epoch)).failures == ("the epoch cannot be read",)


class TestTheRefusalSentence:
    def test_it_names_the_object_and_what_failed_and_says_it_was_not_stored(self) -> None:
        check = check_elset(_with(_GOOD, 2, 10, "8", checksum=False))
        assert check.refusal("SY-12 (90002)") == (
            "The element set for SY-12 (90002) was refused: line 2 fails its checksum. " + NOT_STORED
        )

    def test_a_refresh_says_the_set_held_was_kept(self) -> None:
        check = check_elset(_with(_GOOD, 2, 8, "5"))
        sentence = check.refusal("red SY-12", outcome=HELD_KEPT)
        assert sentence.endswith("is outside 0 to 180. " + HELD_KEPT)

    def test_it_never_carries_the_sets_text(self) -> None:
        corrupted = _with(_GOOD, 2, 10, "8", checksum=False)
        sentence = check_elset(corrupted).refusal("X")
        assert not any(part in sentence for line in corrupted.splitlines() for part in line.split() if len(part) > 4)

    def test_an_accepted_set_has_no_refusal(self) -> None:
        with pytest.raises(ValueError, match="accepted"):
            ElsetCheck(()).refusal("X")


class TestCorruptionsTheChecksumCannotSee:
    """The modulo-10 checksum counts every letter as 0, so a '0' changed to a letter keeps it good: each field must
    read in the published format's own characters, not as whatever float() makes of it (review of SPC-201)."""

    @pytest.mark.parametrize(
        ("column", "failure"),
        [
            (55, "the drag term B* cannot be read"),
            (36, "the first derivative of the mean motion cannot be read"),
            (47, "the second derivative of the mean motion cannot be read"),
        ],
    )
    def test_a_drag_field_with_a_0_changed_to_a_letter_is_refused(self, column: int, failure: str) -> None:
        """B* read as inf or nan and SGP4 still started, propagating every position to NaN."""
        assert _line(_GOOD, 1)[column] == "0"
        corrupted = _with(_GOOD, 1, column, "X", checksum=False)
        assert check_elset(corrupted).failures == (failure,)

    def test_a_0_changed_to_e_in_a_line_2_field_is_refused(self) -> None:
        """'  1.0002' read as 1.0002 degrees; '  1.e002', its checksum unchanged, read as 100.0."""
        sound = _with(_GOOD, 2, 43, "  1.0002")
        assert check_elset(sound).accepted
        corrupted = _with(sound, 2, 47, "e", checksum=False)
        assert _line(corrupted, 2)[43:51] == "  1.e002"
        assert check_elset(corrupted).failures == ("the mean anomaly cannot be read",)

    @pytest.mark.parametrize(
        ("start", "text", "failure"),
        [
            (8, "     1e1", "the inclination cannot be read"),
            (8, " 9_7.400", "the inclination cannot be read"),
            (52, "1.5e+01    ", "the mean motion cannot be read"),
        ],
    )
    def test_an_exponent_or_an_underscore_is_refused(self, start: int, text: str, failure: str) -> None:
        assert check_elset(_with(_GOOD, 2, start, text)).failures == (failure,)

    def test_the_drag_fields_as_published_are_accepted(self) -> None:
        signed = _with(_with(_with(_GOOD, 1, 33, "-.00002182"), 1, 44, " 12345-5"), 1, 53, "-11606-4")
        assert check_elset(signed).accepted


class TestOnlyAsciiIsRead:
    @pytest.mark.parametrize("character", ["\N{SUPERSCRIPT TWO}", "\N{FULLWIDTH DIGIT FIVE}"])
    def test_a_unicode_digit_is_refused_not_raised(self, character: str) -> None:
        """'²'.isdigit() is True and int('²') raises: the check crashed the route that ran it."""
        corrupted = _with(_GOOD, 2, 27, character, checksum=False)
        assert check_elset(corrupted).failures == ("line 2 holds a character that is not plain ASCII",)

    def test_the_checksum_counts_a_unicode_digit_as_0_and_never_raises(self) -> None:
        """Like any character but an ASCII digit or a minus sign, it counts 0: in place of a 7 the sum is out."""
        from spectre.astro.propagator import tle_checksum_valid

        assert tle_checksum_valid(_line(_with(_GOOD, 2, 10, "\N{SUPERSCRIPT TWO}", checksum=False), 2)) is False
        assert tle_checksum_valid(_line(_with(_GOOD, 2, 27, "\N{SUPERSCRIPT TWO}", checksum=False), 2)) is True


class TestRulesNoTestHeld:
    """Three rules of the check no test pinned: a mutation of each survived (review of SPC-201)."""

    def test_a_line_number_must_be_followed_by_a_space(self) -> None:
        assert check_elset(_with(_GOOD, 1, 1, "X", checksum=False)).failures == (
            "the first line does not begin with its line number, 1",
        )
        assert check_elset(_with(_GOOD, 2, 1, "X", checksum=False)).failures == (
            "the second line does not begin with its line number, 2",
        )

    def test_a_letter_in_the_first_column_of_the_eccentricity_is_refused(self) -> None:
        assert check_elset(_with(_GOOD, 2, 26, "X", checksum=False)).failures == ("the eccentricity cannot be read",)

    @pytest.mark.parametrize("epoch", ["26     inf    ", "26nan         ", "26  infinity  "])
    def test_an_epoch_day_that_is_not_finite_is_refused_not_raised(self, epoch: str) -> None:
        assert check_elset(_with(_GOOD, 1, 18, epoch)).failures == ("the epoch cannot be read",)


class TestTheEpochDayFitsItsYear:
    def test_day_366_of_a_year_of_365_is_refused(self) -> None:
        """2026 has 365 days: day 366 rolled into 1 January 2027."""
        assert check_elset(_with(_GOOD, 1, 18, "26366.50000000")).failures == ("the epoch cannot be read",)

    @pytest.mark.parametrize("epoch", ["24366.50000000", "26365.99999999", "26001.00000000"])
    def test_the_last_and_first_days_of_a_year_are_accepted(self, epoch: str) -> None:
        assert check_elset(_with(_GOOD, 1, 18, epoch)).accepted

    def test_the_epoch_is_read_as_before(self) -> None:
        from datetime import UTC, datetime

        from spectre.astro.elset_check import tle_epoch

        assert tle_epoch(_line(_with(_GOOD, 1, 18, "24366.50000000"), 1)) == datetime(2024, 12, 31, 12, tzinfo=UTC)
        assert tle_epoch(_line(_with(_GOOD, 1, 18, "57001.00000000"), 1)) == datetime(1957, 1, 1, tzinfo=UTC)


class TestTheNumberAskedFor:
    """A set that passes the check but belongs to another object is not the set asked for (review of SPC-201)."""

    def test_a_set_for_another_number_is_refused(self) -> None:
        assert check_elset(_GOOD, satno=11111).failures == (
            "it carries catalogue number 90002, not 11111, the number asked for",
        )

    def test_the_number_asked_for_is_accepted(self) -> None:
        assert check_elset(_GOOD, satno=90002).accepted

    def test_an_alpha_5_number_matches_its_value(self) -> None:
        from spectre.astro.catalogue import catalogue_number

        alpha = _with(_with(_GOOD, 1, 2, "A0002"), 2, 2, "A0002")
        assert check_elset(alpha, satno=catalogue_number("A0002")).accepted


class TestTheHistorySentence:
    def test_it_counts_the_sets_and_names_each_failure_once(self) -> None:
        from spectre.astro.elset_check import history_refusal

        assert history_refusal("SY-12 (90002)", 3, ["line 2 fails its checksum", "the epoch cannot be read",
                                                     "line 2 fails its checksum"]) == (
            "3 element sets in the history for SY-12 (90002) were refused: line 2 fails its checksum; the epoch "
            "cannot be read. They were left out."
        )

    def test_one_set_is_said_as_one(self) -> None:
        from spectre.astro.elset_check import history_refusal

        assert history_refusal("X", 1, ["line 1 fails its checksum"]) == (
            "1 element set in the history for X was refused: line 1 fails its checksum. It was left out."
        )
