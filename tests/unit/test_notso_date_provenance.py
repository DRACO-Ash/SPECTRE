"""NOTSO dates say where they came from, and real ISO values parse.

Audit F-087. A missing or unparseable date was replaced without trace: the
issue date by the wall clock, the window start by the first date anywhere in
the text, the end by start plus 24 h. And the parser rejected fractional
seconds and numeric offsets, pushing real values onto those fallbacks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectre.astro.notso import _parse_dt, parse_notso_text


def test_fractional_seconds_and_offsets_parse() -> None:
    assert _parse_dt("2025-03-14T12:00:00.123Z") == datetime(2025, 3, 14, 12, 0, 0, 123000, tzinfo=UTC)
    assert _parse_dt("2025-03-14T13:00:00+01:00") == datetime(2025, 3, 14, 12, 0, tzinfo=UTC)


def test_a_message_without_a_window_says_its_window_was_inferred() -> None:
    (record,) = parse_notso_text("MSGID: N1\nSATNO: 43689\nISSUE DATE: 2025-03-13T18:00:00Z\nTYPE: MANOEUVRE")
    assert "effective start" in record.inferred_fields
    assert "effective end" in record.inferred_fields
    assert "issue date" not in record.inferred_fields
    assert record.effective_end_utc - record.effective_start_utc == timedelta(hours=24)


def test_a_fully_stated_message_has_nothing_inferred() -> None:
    (record,) = parse_notso_text(
        "MSGID: N1\nSATNO: 43689\nISSUE DATE: 2025-03-13T18:00:00Z\n"
        "EFFECTIVE START: 2025-03-14T12:00:00.500Z\nEFFECTIVE END: 2025-03-14T18:00:00Z"
    )
    assert record.inferred_fields == ()
