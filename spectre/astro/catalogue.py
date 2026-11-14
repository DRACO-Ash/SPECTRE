"""The catalogue number written in columns 3 to 7 of a TLE line (SPC-026).

One reader for every caller, so an object cannot be numbered in one place and
unreadable in another. Five digits carry numbers up to 99,999. From 100,000
the field is an Alpha-5 number: a capital letter for the leading digits and
four digits after it. The letters run A for 10 to Z for 33 with I and O left
out, as they read too like 1 and 0, so A0001 is 100001 and Z9999 is 339999.

Anything else is unreadable and answers None: I or O, a lower-case letter, a
sign, an underscore, a blank field. A number is never guessed from a field
that is not one.
"""

from __future__ import annotations

#: The Alpha-5 letters in order; the letter at index k stands for 10 + k.
ALPHA5_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

_DIGITS = frozenset("0123456789")

#: Columns 3 to 7 of line 1: an Alpha-5 field is all five, a letter and 4 digits.
_FIELD_WIDTH = 5


def _digits(text: str) -> bool:
    return bool(text) and set(text) <= _DIGITS


def catalogue_number(field: str) -> int | None:
    """The catalogue number in a five-column TLE field, or None when it is not one.

    Leading and trailing spaces are allowed around a numeric field, as older
    sets padded with them; an Alpha-5 field is exactly a letter and 4 digits.
    """
    text = field.strip()
    if _digits(text):
        return int(text)
    if len(text) == _FIELD_WIDTH and text[0] in ALPHA5_LETTERS and _digits(text[1:]):
        return (ALPHA5_LETTERS.index(text[0]) + 10) * 10_000 + int(text[1:])
    return None
