"""A predicted ΔV in its own field is read, not lost.

Audit F-086. The field parser strips the key, so "PREDICTED DV: 1.5 m/s"
reached the ΔV extractor as "1.5 m/s", which neither of its patterns matches
(one wants a "dv" prefix, the other a trailing "burn"). Because the field was
present, the message text was never tried either, and the ΔV was lost.
"""

from __future__ import annotations

import pytest

from spectre.astro.notso import parse_notso_text

_HEAD = "MSGID: N1\nSATNO: 43689\nEFFECTIVE START: 2025-03-14T12:00:00Z\nEFFECTIVE END: 2025-03-14T18:00:00Z\n"


@pytest.mark.parametrize(
    ("line", "km_s"),
    [("PREDICTED DV: 1.5 m/s", 0.0015), ("DELTA-V: 0.005 km/s", 0.005)],
)
def test_a_dedicated_field_is_parsed(line: str, km_s: float) -> None:
    (record,) = parse_notso_text(_HEAD + line)
    assert record.predicted_delta_v_km_s == pytest.approx(km_s)


def test_an_unparseable_field_falls_back_to_the_text() -> None:
    (record,) = parse_notso_text(_HEAD + "PREDICTED DV: TBC\nDESCRIPTION: a 2.0 m/s burn")
    assert record.predicted_delta_v_km_s == pytest.approx(0.002)
