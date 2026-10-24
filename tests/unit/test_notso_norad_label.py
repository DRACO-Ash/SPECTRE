"""A NOTSO's object is its labelled catalogue number, never a stray number.

Audit F-090. With no labelled ID the object was taken from the first five
digit number anywhere in the message, which may be another object, a
quantity or a reference: "close approach with 43013" filed for a different
satellite was attributed to 43013.
"""

from __future__ import annotations

from spectre.astro.notso import parse_notso_text


def test_an_unlabelled_number_is_not_taken_as_the_object() -> None:
    text = (
        "MSGID: N1\nEFFECTIVE START: 2025-03-14T12:00:00Z\n"
        "DESCRIPTION: close approach with 43013 expected"
    )
    assert parse_notso_text(text) == []


def test_a_labelled_number_in_the_text_is_still_found() -> None:
    text = "MSGID: N1\nEFFECTIVE START: 2025-03-14T12:00:00Z\nDESCRIPTION: burn for NORAD 43689"
    (record,) = parse_notso_text(text)
    assert record.norad_id == 43689
