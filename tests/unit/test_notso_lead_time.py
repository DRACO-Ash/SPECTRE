"""NOTSO lead time is how long before the burn the notice was issued.

Audit F-091. "Lead time" on the page was the window start minus the burn,
which ignores when the notice was issued and is negative when the notice
precedes the burn. Lead time is now burn minus issue date, positive when the
notice came first; the window offset is kept under its own name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.notso import NOTSORecord, NOTSOType, correlate_notsos_with_manoeuvres
from tests.unit.test_notso import _FakeManoeuvre

_ISSUE = datetime(2025, 3, 14, 0, 0, tzinfo=UTC)


def test_a_notice_issued_before_the_burn_has_a_positive_lead_time() -> None:
    notso = NOTSORecord(
        message_id="N1", norad_id=43689, international_designator=None, object_name=None,
        issuing_entity="TEST", issue_date_utc=_ISSUE,
        effective_start_utc=_ISSUE + timedelta(hours=12), effective_end_utc=_ISSUE + timedelta(hours=18),
        notso_type=NOTSOType.MANOEUVRE, description="burn", predicted_delta_v_km_s=None,
        predicted_direction=None, raw_message="",
    )
    (corr,) = correlate_notsos_with_manoeuvres([notso], [_FakeManoeuvre(_ISSUE + timedelta(hours=14))], 43689)
    assert corr.lead_time_hours == pytest.approx(14.0)
    assert corr.time_offset_hours == pytest.approx(-2.0), "the window offset is kept, separately"
