"""A MSGID line inside a message does not split it in two.

Audit F-088. Any MSGID line began a new message, so "SATNO: 43689" above
"MSGID: X" formed one fragment (a generated ID, no window) and the window,
type and ΔV below it a second fragment with no SATNO, which was dropped
without a log.
"""

from __future__ import annotations

from datetime import UTC, datetime

from spectre.astro.notso import parse_notso_text


def test_a_msgid_after_the_satno_keeps_one_message() -> None:
    text = (
        "SATNO: 43689\nMSGID: X-1\nEFFECTIVE START: 2025-03-14T12:00:00Z\n"
        "EFFECTIVE END: 2025-03-14T18:00:00Z\nTYPE: MANOEUVRE"
    )
    (record,) = parse_notso_text(text)
    assert record.message_id == "X-1"
    assert record.norad_id == 43689
    assert record.effective_start_utc == datetime(2025, 3, 14, 12, 0, tzinfo=UTC)


def test_messages_led_by_msgid_and_separated_by_a_blank_line_still_split() -> None:
    a = "MSGID: A\nSATNO: 43689\nEFFECTIVE START: 2025-03-14T12:00:00Z"
    b = "MSGID: B\nSATNO: 25544\nEFFECTIVE START: 2025-03-15T12:00:00Z"
    assert [r.message_id for r in parse_notso_text(a + "\n\n" + b)] == ["A", "B"]
