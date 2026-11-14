"""A NOTSO's SATNO field is read as the TLE reader reads it (SPC-026).

``_norad_id_of`` took the first run of digits in the field, so "SATNO: A0001"
was filed against object 1, "SATNO: I0001" too, and "SATNO: USA 270" against
object 270. Object 100001's NOTSO then never met its manoeuvres, and another
object's history gained a notice it was never sent. The field's first word is
now read with ``spectre.astro.catalogue``: five or more digits, or an Alpha-5
letter and 4 digits. Anything else is unreadable, and the operator is told so
in the reject list rather than shown a guessed number.
"""

from __future__ import annotations

import pytest

from spectre.astro.notso import correlate_notsos_with_manoeuvres, parse_notso_text_with_rejects


def _message(satno: str) -> str:
    return (
        f"MSGID: N1\nSATNO: {satno}\nEFFECTIVE START: 2025-03-14T12:00:00Z\n"
        "EFFECTIVE END: 2025-03-14T18:00:00Z\nTYPE: MANOEUVRE"
    )


@pytest.mark.parametrize(
    ("field", "number"),
    [
        ("A0001", 100001),
        ("Z9999", 339999),
        ("J0000", 180000),
        ("100001", 100001),
        ("43689", 43689),
        ("43689 (USA 270)", 43689),
        ("#43689", 43689),
    ],
)
def test_a_satno_field_is_read_as_the_tle_reader_reads_it(field: str, number: int) -> None:
    records, rejects = parse_notso_text_with_rejects(_message(field))
    assert ([r.norad_id for r in records], rejects) == ([number], [])


@pytest.mark.parametrize("field", ["I0001", "O0001", "a0001", "A001", "A0001X", "USA 270", "NORAD-43689"])
def test_a_satno_field_that_is_not_a_catalogue_number_is_refused_plainly(field: str) -> None:
    records, rejects = parse_notso_text_with_rejects(_message(field))
    assert records == []
    assert rejects == ["message 1: NORAD ID cannot be read as a catalogue number"]


def test_a_message_with_no_satno_still_says_it_has_none() -> None:
    _, rejects = parse_notso_text_with_rejects("MSGID: N2\nEFFECTIVE START: 2025-03-15T12:00:00Z\nTYPE: MANOEUVRE")
    assert rejects == ["message 1: no labelled NORAD ID"]


def test_an_alpha5_notso_is_correlated_with_its_own_object() -> None:
    records, _ = parse_notso_text_with_rejects(_message("A0001"))
    mine = correlate_notsos_with_manoeuvres(records, [], norad_id=100001)
    object_1 = correlate_notsos_with_manoeuvres(records, [], norad_id=1)
    assert ([c.correlation_type for c in mine], object_1) == (["notso_only"], [])
