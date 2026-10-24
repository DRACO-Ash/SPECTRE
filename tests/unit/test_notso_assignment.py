"""NOTSOs and manoeuvres are paired closest first, not in window order.

Audit F-092. Matching walked the NOTSOs in effective-start order and each
took its nearest free manoeuvre, so an early, wide notice claimed a burn that
a later notice's window fits exactly, and the later notice was paired with a
burn half a day away.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectre.astro.notso import NOTSORecord, NOTSOType, correlate_notsos_with_manoeuvres
from tests.unit.test_notso import _FakeManoeuvre

_T0 = datetime(2025, 3, 14, 0, 0, tzinfo=UTC)


def _notso(msg_id: str, start_h: float, end_h: float) -> NOTSORecord:
    return NOTSORecord(
        message_id=msg_id, norad_id=43689, international_designator=None, object_name=None,
        issuing_entity="TEST", issue_date_utc=_T0 - timedelta(days=1),
        effective_start_utc=_T0 + timedelta(hours=start_h), effective_end_utc=_T0 + timedelta(hours=end_h),
        notso_type=NOTSOType.MANOEUVRE, description="burn", predicted_delta_v_km_s=None,
        predicted_direction=None, raw_message="",
    )


def test_the_burn_goes_to_the_notice_whose_window_fits_it() -> None:
    wide, narrow = _notso("WIDE", 0.0, 10.0), _notso("NARROW", 6.0, 8.0)
    in_narrow, later = _FakeManoeuvre(_T0 + timedelta(hours=7)), _FakeManoeuvre(_T0 + timedelta(hours=20))
    corrs = correlate_notsos_with_manoeuvres([wide, narrow], [in_narrow, later], 43689)
    pairs = {c.notso.message_id: c.manoeuvre for c in corrs if c.correlation_type == "matched"}
    assert pairs["NARROW"] is in_narrow
    assert pairs["WIDE"] is later
