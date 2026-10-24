"""NOTSO correlation dates a manoeuvre by its burn, not its next element set.

Audit F-027. Matching used Manoeuvre.epoch, the epoch of the element set
after the burn, which the class itself documents as able to be wrong by the
whole gap. Gaps run to 30 days and the tolerance is 24 h, so a notified burn
whose next element set arrived three days later was reported "notso_only",
and the same burn was counted as silent: the operator was blamed for a
notification it had made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectre.astro.notso import NOTSORecord, NOTSOType, correlate_notsos_with_manoeuvres
from spectre.astro.pattern_of_life import Manoeuvre
from tests.unit.test_pol_status_ladder import _make_record

_START = datetime(2025, 3, 14, 12, 0, tzinfo=UTC)


def _notso() -> NOTSORecord:
    return NOTSORecord(
        message_id="N1", norad_id=43689, international_designator="", object_name="", issuing_entity="",
        issue_date_utc=_START - timedelta(hours=18),
        effective_start_utc=_START, effective_end_utc=_START + timedelta(hours=6),
        notso_type=NOTSOType.MANOEUVRE, description="test",
        predicted_delta_v_km_s=0.010, predicted_direction=None, raw_message="",
    )


def _bracketed(before: datetime, after: datetime) -> Manoeuvre:
    """A manoeuvre the estimator could not date: only the bracket is known."""
    rec_before, rec_after = _make_record(), _make_record()
    rec_before.epoch, rec_after.epoch = before, after
    return Manoeuvre(
        epoch=after, gap_days=(after - before).total_seconds() / 86400.0, delta_v_km_s=0.010,
        delta_alt_km=0.0, delta_inc_deg=0.0, delta_ecc=0.0,
        delta_raan_corrected_deg=0.0, delta_argp_corrected_deg=0.0,
        delta_period_s=0.0, delta_drift_deg_day=None,
        dominant_element="altitude", tle_before=rec_before, tle_after=rec_after,
    )


def test_a_bracket_spanning_the_window_is_matched() -> None:
    # Element sets the day before the window and three days after it.
    mnv = _bracketed(_START - timedelta(days=1), _START + timedelta(days=3))
    corrs = correlate_notsos_with_manoeuvres([_notso()], [mnv], norad_id=43689)
    assert [c.correlation_type for c in corrs] == ["matched"]


def test_a_bracket_wholly_after_the_window_is_not() -> None:
    mnv = _bracketed(_START + timedelta(days=2), _START + timedelta(days=5))
    types = {c.correlation_type for c in correlate_notsos_with_manoeuvres([_notso()], [mnv], norad_id=43689)}
    assert types == {"notso_only", "manoeuvre_only"}


def test_the_burn_window_is_the_bracket_when_the_burn_is_undated() -> None:
    mnv = _bracketed(_START - timedelta(days=1), _START + timedelta(days=3))
    assert mnv.burn_window == (_START - timedelta(days=1), _START + timedelta(days=3))
