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
    records, malformed = parse_tle_history_counted("\n".join([_GOOD_A, _CORRUPT_EPOCH, _GOOD_B]))
    assert len(records) == 2
    assert malformed == 1


def test_the_plain_parser_still_returns_the_good_records() -> None:
    assert len(parse_tle_history("\n".join([_GOOD_A, _CORRUPT_EPOCH, _GOOD_B]))) == 2
