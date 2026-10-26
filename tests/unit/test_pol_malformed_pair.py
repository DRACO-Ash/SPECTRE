"""A malformed element set drops out of the history; it does not end the parse.

Audit F-083. The docstring said a malformed pair drops out, but nothing
caught the ValueError a corrupt epoch raises (or the ZeroDivisionError of a
zero mean motion), so one bad element set lost the whole analysis. Drops are
now counted so the operator can see them, as the noise-floor rejections are.
"""

from __future__ import annotations

from spectre.astro.pattern_of_life import parse_tle_history, parse_tle_history_counted

_GOOD_A = (
    "1 25544U 98067A   24001.00000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 25544  51.6400 100.0000 0001000  90.0000 270.0000 15.49000000 00001"
)
_GOOD_B = (
    "1 25544U 98067A   24003.00000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 25544  51.6400  90.0000 0001000  90.0000 270.0000 15.49000000 00002"
)
# Columns 19-32 of line 1 hold the epoch; letters there cannot be a year.
_CORRUPT_EPOCH = (
    "1 25544U 98067A   XX002.00000000  .00001000  00000-0  10000-3 0  9990\n"
    "2 25544  51.6400  95.0000 0001000  90.0000 270.0000 15.49000000 00003"
)


def test_a_corrupt_epoch_drops_one_pair_and_is_counted() -> None:
    records, counts = parse_tle_history_counted("\n".join([_GOOD_A, _CORRUPT_EPOCH, _GOOD_B]))
    assert len(records) == 2
    assert counts.malformed == 1


def test_the_plain_parser_still_returns_the_good_records() -> None:
    assert len(parse_tle_history("\n".join([_GOOD_A, _CORRUPT_EPOCH, _GOOD_B]))) == 2


class TestEveryDropIsCounted:
    """Duplicates, unusable provenance and other objects' sets dropped uncounted (audits F-205, F-206)."""

    def test_a_duplicate_epoch_is_counted(self) -> None:
        records, counts = parse_tle_history_counted("\n".join([_GOOD_A, _GOOD_A, _GOOD_B]))
        assert (len(records), counts.duplicate_epoch) == (2, 1)

    def test_unusable_provenance_is_counted(self) -> None:
        line1 = _GOOD_A.splitlines()[0]
        records, counts = parse_tle_history_counted(
            "\n".join([_GOOD_A, _GOOD_B]), metadata={line1: ("REAL",)},  # type: ignore[dict-item]
        )
        assert (len(records), counts.bad_provenance) == (1, 1)

    def test_another_objects_element_set_is_skipped_and_counted(self) -> None:
        other = _GOOD_B.replace("25544", "43013")
        records, counts = parse_tle_history_counted("\n".join([_GOOD_A, other]), satno=25544)
        assert (len(records), counts.other_object) == (1, 1)

    def test_without_a_satno_nothing_is_filtered(self) -> None:
        other = _GOOD_B.replace("25544", "43013")
        records, counts = parse_tle_history_counted("\n".join([_GOOD_A, other]))
        assert (len(records), counts.other_object) == (2, 0)

    def test_an_alpha_5_catalogue_number_is_read(self) -> None:
        from spectre.astro.pattern_of_life import _catalogue_number

        assert _catalogue_number("1 A0001U") == 100001
        assert _catalogue_number("1 Z9999U") == 339999
        assert _catalogue_number("1 25544U") == 25544
