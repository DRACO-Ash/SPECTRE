"""One acceptance check for an element set, run before anything stores it (SPC-201, evaluation F-25 and F-34).

Element sets from UDL reached the Decision Engine with no checksum or range check: one digit of a set's inclination
changed in transit, with the old checksum left beside it, moved a computed miss from 10.4 to 13.4 km with no flag,
and the background refresh replaced a good held set with it (evaluation probe P-14). An inclination of 597.4 degrees
was accepted and gave a figure rather than a refusal.

check_elset is the one check every ingest path runs, whether the set came from UDL, from the operator's paste box or
from the bundled data:

● two element lines, the last two that are not blank, so a name line above them is read past;
● each beginning with its own line number, 1 then 2, followed by a space, each 69 characters long, and each in plain
  ASCII, so a Unicode digit is refused rather than read;
● each line's modulo-10 checksum in column 69 (propagator.tle_checksum_valid);
● one catalogue number on both lines, five digits or an Alpha-5 letter and four digits, and, when the caller asked for
  a number, that number;
● an epoch that reads as a date (day 1 to the last day of its year: 365, or 366 in a leap year);
● the first and second derivatives of the mean motion and the drag term B* each written as the published format
  writes them, so SGP4 never reads one as inf or nan;
● inclination from 0 to 180 degrees, eccentricity from 0 to under 1, mean motion above 0, and the right ascension of
  the ascending node, the argument of perigee and the mean anomaly from 0 to 360 degrees, each written in digits and
  one decimal point;
● an ephemeris type of 0, SGP4, read from the UDL record's ephemType when it carries one, else from line 1 column 63
  (a blank reads as 0): a type 4 set is SGP4-XP, whose line 1 fields carry other terms, and the sgp4 package
  propagates it without an error to a wrong orbit;
● not an uncorrelated track: a UDL record whose uct flag is true is not yet tied to the object it is filed under;
● and, once all of those pass, SGP4 starting from it without an error of its own: fields each inside their range can
  still describe an orbit inside the Earth.

Each field is read by a pattern of the format's own characters, never by float() alone: the checksum counts every
letter as 0, so a '0' changed to 'e' keeps it good, and float() would read the field as an exponent.

A set that fails is refused whole: the caller stores nothing and keeps whatever it held. The refusal names each
failure in words and never quotes the set's text, so it can be logged and shown as it is. Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from spectre.astro.catalogue import catalogue_number
from spectre.astro.propagator import TLE_LINE_LENGTH, TLEOrbit, tle_checksum_valid

__all__ = [
    "HELD_KEPT", "NOT_STORED", "TLE_LINE_LENGTH", "ElsetCheck", "check_elset", "history_refusal", "refused_type",
    "tle_epoch",
]
#: What a refusal says became of the set, when nothing was held for it.
NOT_STORED = "It was not stored."
#: The same, when a set already held for the object was kept in its place.
HELD_KEPT = "It was not stored, and the set already held for that object was kept."

_TWO_LINES = "it does not hold two element lines"
# Two-digit years from 57 are the 1900s: the first satellite flew in 1957.
_FIRST_YEAR_OF_THE_1900S = 57

#: A decimal number as the format writes one: a sign, digits and at most one decimal point, padded with spaces, as
#: in " 97.4000" or "-.00002182". No exponent, underscore or word, each of which float() reads. re.ASCII keeps \d to
#: the digits 0 to 9, as float() would also read other scripts' digits.
_DECIMAL = re.compile(r" *[+-]?\d*\.?\d+ *", re.ASCII)
#: A mantissa with an implied decimal point and a one-digit power of 10 (" 10270-3", "-11606-4", " 00000+0").
_IMPLIED_EXPONENT = re.compile(r" *[+-]?\d{1,5}[+-]\d *", re.ASCII)
#: The epoch: a two-digit year, then the day of the year and its fraction.
_EPOCH_FIELD = re.compile(r" *(\d{2})( *\d+(?:\.\d*)?) *", re.ASCII)


class _Field(NamedTuple):
    """One field of line 2: its name in words, its columns, and the range it must fall in."""

    words:  str
    start:  int
    end:    int
    low:    float
    high:   float
    unit:   str = "degrees"


#: Line 2's angles, in the columns of the published format, each with its range (inclusive at both ends).
_ANGLES: tuple[_Field, ...] = (
    _Field("the inclination", 8, 16, 0.0, 180.0),
    _Field("the right ascension of the ascending node", 17, 25, 0.0, 360.0),
    _Field("the argument of perigee", 34, 42, 0.0, 360.0),
    _Field("the mean anomaly", 43, 51, 0.0, 360.0),
)
#: SGP4's own reasons it cannot start from a set, by the error code its initialisation sets (Vallado and others,
#: 2006): fields each inside their range can still describe no orbit it can propagate.
_SGP4_ERRORS: dict[int, str] = {
    1: "the mean eccentricity or mean motion is out of its range",
    2: "the mean motion is below 0",
    3: "the perturbed eccentricity is out of its range",
    4: "the orbit's semi-latus rectum is below 0",
    5: "the epoch elements are sub-orbital",
    6: "the orbit lies inside the Earth",
}
_ECCENTRICITY = slice(26, 33)
_MEAN_MOTION = slice(52, 63)
_CATALOGUE = slice(2, 7)
_EPOCH = slice(18, 32)
#: Line 1's drag fields, in the columns of the published format, each with the pattern it must match.
#: Line 1 column 63: the ephemeris type. 0 is SGP4, the only type the propagators here read; 4 is SGP4-XP.
_EPHEMERIS_TYPE = slice(62, 63)
_SGP4_TYPE = 0
_SGP4_XP_TYPE = 4
_UCT_FAILS = "it is an uncorrelated track (UCT), not a set correlated to the object"
_DRAG: tuple[tuple[str, slice, re.Pattern[str]], ...] = (
    ("the first derivative of the mean motion", slice(33, 43), _DECIMAL),
    ("the second derivative of the mean motion", slice(44, 52), _IMPLIED_EXPONENT),
    ("the drag term B*", slice(53, 61), _IMPLIED_EXPONENT),
)


def tle_epoch(line1: str) -> datetime | None:
    """The epoch line 1 carries in its columns 19 to 32 (YYDDD.DDDDDDDD), in UTC; None when it does not read.

    Day 0, or a day past the last of its year (365, or 366 in a leap year), is a corrupt field, not a date a timedelta
    should quietly roll into the neighbouring year (audit F-255). Digits only: "inf" or "nan" is no day.
    """
    match = _EPOCH_FIELD.fullmatch(line1[_EPOCH])
    if match is None:
        return None
    two_digit = int(match.group(1))
    day = float(match.group(2))
    year = (1900 if two_digit >= _FIRST_YEAR_OF_THE_1900S else 2000) + two_digit
    last_day = date(year, 12, 31).timetuple().tm_yday  # 365, or 366 in a leap year, from the calendar
    if not 1 <= int(day) <= last_day:
        return None
    return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day - 1)


def history_refusal(name: str, count: int, failures: Sequence[str]) -> str:
    """The sentence for *count* element sets refused from the history for the object *name*, each distinct failure
    named once in the order first met; never the sets' text."""
    named = "; ".join(dict.fromkeys(failures))
    if count == 1:
        return f"1 element set in the history for {name} was refused: {named}. It was left out."
    return f"{count} element sets in the history for {name} were refused: {named}. They were left out."


@dataclass(frozen=True)
class ElsetCheck:
    """What check_elset found: each failure in words, in the order checked; none when the set is accepted."""

    failures: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.failures

    def refusal(self, name: str, *, outcome: str = NOT_STORED) -> str:
        """The sentence the operator is shown: the object named by *name*, what failed, and *outcome*.

        It names each failure and never the set's text, so it is fit for the log as well as the page.
        """
        if self.accepted:
            raise ValueError("an accepted element set has no refusal")
        return f"The element set for {name} was refused: {'; '.join(self.failures)}. {outcome}"


def _lines(tle: str) -> list[str]:
    return [line.strip() for line in tle.strip().splitlines() if line.strip()]


def _structure(line1: str, line2: str) -> list[str]:
    """Line numbers, lengths and characters: a failure here leaves no field at its column, or none that reads as the
    format means, so nothing more is read."""
    failures = []
    for n, (ordinal, line) in enumerate((("first", line1), ("second", line2)), start=1):
        if not line.startswith(f"{n} "):
            failures.append(f"the {ordinal} line does not begin with its line number, {n}")
    for n, line in enumerate((line1, line2), start=1):
        if len(line) != TLE_LINE_LENGTH:
            failures.append(f"line {n} is {len(line)} characters long, not {TLE_LINE_LENGTH}")
        if not (line.isascii() and line.isprintable()):
            failures.append(f"line {n} holds a character that is not plain ASCII")
    return failures


def _checksums(line1: str, line2: str) -> list[str]:
    return [f"line {n} fails its checksum" for n, line in enumerate((line1, line2), start=1)
            if not tle_checksum_valid(line)]


def _catalogue(line1: str, line2: str, satno: int | None) -> list[str]:
    """One catalogue number on both lines, five digits or an Alpha-5 letter and four (spectre.astro.catalogue), and
    *satno* when the caller asked for that number."""
    numbers = []
    for n, line in enumerate((line1, line2), start=1):
        if not line[_CATALOGUE].strip():
            return [f"line {n} carries no catalogue number"]
        number = catalogue_number(line[_CATALOGUE])
        if number is None:
            return [f"the catalogue number on line {n} cannot be read"]
        numbers.append(number)
    if numbers[0] != numbers[1]:
        return ["the catalogue numbers on line 1 and line 2 differ"]
    if satno is not None and numbers[0] != satno:
        return [f"it carries catalogue number {numbers[0]}, not {satno}, the number asked for"]
    return []


def _number(text: str) -> float | None:
    """*text* as a number when it is written in the format's own characters (_DECIMAL); None otherwise."""
    return float(text) if _DECIMAL.fullmatch(text) else None


def _drag(line1: str) -> list[str]:
    return [f"{words} cannot be read" for words, columns, pattern in _DRAG if not pattern.fullmatch(line1[columns])]


def _ranges(line2: str) -> list[str]:
    failures = []
    for field in _ANGLES:
        value = _number(line2[field.start:field.end])
        if value is None:
            failures.append(f"{field.words} cannot be read")
        elif not field.low <= value <= field.high:
            failures.append(f"{field.words}, {value} {field.unit}, is outside {field.low:g} to {field.high:g}")
    # The eccentricity's decimal point is implied: seven digits, so 0 to under 1 whenever it reads.
    if not line2[_ECCENTRICITY].replace(" ", "0").isdigit():
        failures.append("the eccentricity cannot be read")
    motion = _number(line2[_MEAN_MOTION])
    if motion is None:
        failures.append("the mean motion cannot be read")
    elif motion <= 0.0:
        failures.append(f"the mean motion, {motion} revolutions a day, is not above 0")
    return failures


def _read_type(text: str) -> int | None:
    """One ephemeris-type field: a blank read as 0, a number as itself, anything else None."""
    text = text.strip()
    if not text:
        return _SGP4_TYPE
    return int(text) if text.isascii() and text.isdigit() else None


def _ephemeris_type(line1: str, record: Mapping[str, object] | None) -> int | None:
    """The set's ephemeris type, from line 1 column 63 and the record's ephemType when it carries a non-blank one.
    Either source can refuse the set: None when either does not read, else the first that is not 0, else 0. A
    record's 0 never hides a type 4 written on line 1."""
    texts = [line1[_EPHEMERIS_TYPE]]
    field = (record or {}).get("ephemType")
    if field is not None and str(field).strip():
        texts.insert(0, str(field))
    kinds = [_read_type(text) for text in texts]
    if None in kinds:
        return None
    return next((kind for kind in kinds if kind != _SGP4_TYPE), _SGP4_TYPE)


def _is_uct(record: Mapping[str, object] | None) -> bool:
    """UDL's uct is a JSON boolean; only true marks a track not yet correlated to the object."""
    return (record or {}).get("uct") is True


def _kind(line1: str, record: Mapping[str, object] | None) -> list[tuple[str, str]]:
    """Each type or correlation failure as (the sentence's clause, a few words for the log): a set SGP4 would
    misread, and a track not tied to the object."""
    found = []
    kind = _ephemeris_type(line1, record)
    if kind is None:
        found.append(("its ephemeris type cannot be read", "an unreadable ephemeris type"))
    elif kind == _SGP4_XP_TYPE:
        found.append((f"it is an SGP4-XP set (ephemeris type {kind}), which SGP4 would propagate to a wrong orbit "
                       "without an error", f"SGP4-XP (type {kind})"))
    elif kind != _SGP4_TYPE:
        found.append((f"its ephemeris type is {kind}, not {_SGP4_TYPE}, the SGP4 type every propagator here assumes",
                       f"ephemeris type {kind}"))
    if _is_uct(record):
        found.append((_UCT_FAILS, "UCT"))
    return found


def refused_type(tle: str, record: Mapping[str, object] | None = None) -> str:
    """What *tle* is refused as by its type or correlation, in a few words for the log ("SGP4-XP (type 4)", "UCT");
    "" when neither refuses it. Never the set's text."""
    lines = _lines(tle)
    return ", ".join(words for _, words in _kind(lines[-2] if len(lines) > 1 else "", record))


def check_elset(tle: str, satno: int | None = None, *, record: Mapping[str, object] | None = None) -> ElsetCheck:
    """Whether *tle* may be stored, and each reason it may not (see the module's list). With *satno*, the set must
    also be for that catalogue number: an answer for another object is not the set asked for. *record* is the UDL
    record the set came in, when it came from UDL: its ephemType and uct flag are read from it."""
    lines = _lines(tle)
    # PLR2004: two element lines.
    if len(lines) < 2:  # noqa: PLR2004
        return ElsetCheck((_TWO_LINES,))
    line1, line2 = lines[-2], lines[-1]
    structure = _structure(line1, line2)
    if structure:
        return ElsetCheck(tuple(structure))
    failures = [*_checksums(line1, line2), *_catalogue(line1, line2, satno)]
    if tle_epoch(line1) is None:
        failures.append("the epoch cannot be read")
    failures += _drag(line1)
    failures += _ranges(line2)
    failures += [clause for clause, _ in _kind(line1, record)]
    if not failures:
        code = TLEOrbit(tle).init_error
        if code:
            failures.append(f"SGP4 cannot start from it: its error {code}, {_SGP4_ERRORS.get(code, 'unnamed')}")
    return ElsetCheck(tuple(failures))
