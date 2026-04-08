"""Unit tests for spectre.astro.notso — NOTSO parsing, correlation, behaviour profile."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.notso import (
    NOTSOManoeuvreCorrelation,
    NOTSORecord,
    NOTSOType,
    OperatorBehaviourProfile,
    _extract_delta_v,
    _extract_norad_id,
    _infer_notso_type,
    _parse_dt,
    _split_messages,
    correlate_notsos_with_manoeuvres,
    extract_behaviour_profile,
    parse_notso_text,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


class _FakeTLERecord:
    sma_km = 6778.0


class _FakeManoeuvre:
    """Minimal stub matching what correlate_notsos_with_manoeuvres expects."""

    def __init__(self, epoch: datetime, dv_km_s: float = 0.010):
        self.epoch = epoch
        self.delta_v_km_s = dv_km_s
        self.tle_before = _FakeTLERecord()
        self.tle_after  = _FakeTLERecord()


_SAMPLE_NOTSO = """\
MSGID: 2025-001-0042
SATNO: 43689
ISSUE DATE: 2025-03-13T18:00:00Z
EFFECTIVE START: 2025-03-14T12:00:00Z
EFFECTIVE END: 2025-03-14T18:00:00Z
TYPE: MANOEUVRE
DESCRIPTION: Planned north-south station keeping burn.
"""

_SAMPLE_NOTSO_2 = """\
MSGID: 2025-001-0043
SATNO: 43689
ISSUE DATE: 2025-03-20T09:00:00Z
EFFECTIVE START: 2025-03-21T06:00:00Z
EFFECTIVE END: 2025-03-21T14:00:00Z
TYPE: MANOEUVRE
DESCRIPTION: East-west station keeping manoeuvre. Delta-V: 0.005 km/s burn expected.
"""

_MULTI_NOTSO = _SAMPLE_NOTSO.strip() + "\n---\n" + _SAMPLE_NOTSO_2.strip()


# ── Datetime parsing ──────────────────────────────────────────────────────────

class TestParseDt:
    def test_iso8601_with_z(self):
        dt = _parse_dt("2025-03-14T12:00:00Z")
        assert dt == _dt("2025-03-14T12:00:00")

    def test_iso8601_without_z(self):
        dt = _parse_dt("2025-03-14T12:00:00")
        assert dt is not None
        assert dt.year == 2025

    def test_date_time_utc(self):
        dt = _parse_dt("2025-03-14 12:00 UTC")
        assert dt is not None  # format may not match exactly but shouldn't crash

    def test_invalid_returns_none(self):
        assert _parse_dt("not a date") is None

    def test_empty_string_returns_none(self):
        assert _parse_dt("") is None


# ── Type inference ────────────────────────────────────────────────────────────

class TestInferNotsoType:
    def test_manoeuvre(self):
        assert _infer_notso_type("planned thruster burn") == NOTSOType.MANOEUVRE

    def test_deorbit(self):
        assert _infer_notso_type("deorbit burn scheduled") == NOTSOType.DEORBIT

    def test_proximity_ops(self):
        assert _infer_notso_type("RPO manoeuvre approaching target") == NOTSOType.PROXIMITY_OPS

    def test_launch(self):
        assert _infer_notso_type("deployment of secondary payload") == NOTSOType.LAUNCH

    def test_test(self):
        assert _infer_notso_type("calibration test sequence") == NOTSOType.TEST

    def test_other(self):
        assert _infer_notso_type("unrelated administrative message") == NOTSOType.OTHER


# ── NORAD ID extraction ───────────────────────────────────────────────────────

class TestExtractNoradId:
    def test_satno_prefix(self):
        assert _extract_norad_id("SATNO: 43689") == 43689

    def test_norad_id_prefix(self):
        assert _extract_norad_id("NORAD ID: 25544") == 25544

    def test_five_digit_fallback(self):
        assert _extract_norad_id("Object 43689 in LEO") == 43689

    def test_no_id_returns_none(self):
        assert _extract_norad_id("no numbers here") is None


# ── Delta-V extraction ────────────────────────────────────────────────────────

class TestExtractDeltaV:
    def test_km_s(self):
        dv = _extract_delta_v("delta-v: 0.015 km/s")
        assert dv == pytest.approx(0.015, rel=1e-4)

    def test_m_s_converted(self):
        dv = _extract_delta_v("15 m/s burn")
        assert dv == pytest.approx(0.015, rel=1e-4)

    def test_no_dv_returns_none(self):
        assert _extract_delta_v("station keeping burn") is None


# ── Message splitting ─────────────────────────────────────────────────────────

class TestSplitMessages:
    def test_single_message(self):
        msgs = _split_messages(_SAMPLE_NOTSO)
        assert len(msgs) == 1

    def test_triple_dash_separator(self):
        msgs = _split_messages(_MULTI_NOTSO)
        assert len(msgs) == 2

    def test_equals_separator(self):
        text = "MSGID: A\nSATNO: 43689\n===\nMSGID: B\nSATNO: 43689"
        msgs = _split_messages(text)
        assert len(msgs) == 2

    def test_msgid_implicit_separator(self):
        text = "MSGID: 001\nSATNO: 43689\nMSGID: 002\nSATNO: 43689"
        msgs = _split_messages(text)
        # Each MSGID starts a new block
        assert len(msgs) >= 2


# ── Single NOTSO parsing ──────────────────────────────────────────────────────

class TestParseNotsoText:
    def test_single_parse_returns_one_record(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert len(records) == 1

    def test_message_id_extracted(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert records[0].message_id == "2025-001-0042"

    def test_norad_id_extracted(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert records[0].norad_id == 43689

    def test_effective_start_parsed(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert records[0].effective_start_utc == _dt("2025-03-14T12:00:00")

    def test_effective_end_parsed(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert records[0].effective_end_utc == _dt("2025-03-14T18:00:00")

    def test_type_inferred_as_manoeuvre(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert records[0].notso_type == NOTSOType.MANOEUVRE

    def test_description_populated(self):
        records = parse_notso_text(_SAMPLE_NOTSO)
        assert "station keeping" in records[0].description.lower()

    def test_multi_parse_returns_two_records(self):
        records = parse_notso_text(_MULTI_NOTSO)
        assert len(records) == 2

    def test_predicted_dv_extracted(self):
        records = parse_notso_text(_SAMPLE_NOTSO_2)
        assert records[0].predicted_delta_v_km_s == pytest.approx(0.005, rel=1e-4)

    def test_empty_text_returns_empty(self):
        assert parse_notso_text("") == []

    def test_no_norad_id_skipped(self):
        text = "MSGID: X\nISSUE DATE: 2025-01-01T00:00:00Z\nDESCRIPTION: burn"
        records = parse_notso_text(text)
        assert len(records) == 0


# ── Correlation algorithm ─────────────────────────────────────────────────────

class TestCorrelateNotsos:
    """Test all four correlation outcome types."""

    def _notso(self, satno: int, start_iso: str, end_iso: str, msg_id: str = "TEST-001") -> NOTSORecord:
        start = _dt(start_iso)
        end   = _dt(end_iso)
        return NOTSORecord(
            message_id=msg_id,
            norad_id=satno,
            international_designator=None,
            object_name=None,
            issuing_entity="TEST",
            issue_date_utc=start - timedelta(hours=24),
            effective_start_utc=start,
            effective_end_utc=end,
            notso_type=NOTSOType.MANOEUVRE,
            description="test",
            predicted_delta_v_km_s=0.010,
            predicted_direction=None,
            raw_message="",
        )

    def test_matched_correlation(self):
        """NOTSO window overlaps manoeuvre epoch → matched."""
        notso = self._notso(43689, "2025-03-14T12:00:00", "2025-03-14T18:00:00")
        mnv   = _FakeManoeuvre(_dt("2025-03-14T14:00:00"))
        corrs = correlate_notsos_with_manoeuvres([notso], [mnv], norad_id=43689)
        assert len(corrs) == 1
        assert corrs[0].correlation_type == "matched"

    def test_notso_only(self):
        """NOTSO filed but no manoeuvre detected → notso_only."""
        notso = self._notso(43689, "2025-03-14T12:00:00", "2025-03-14T18:00:00")
        corrs = correlate_notsos_with_manoeuvres([notso], [], norad_id=43689)
        assert len(corrs) == 1
        assert corrs[0].correlation_type == "notso_only"

    def test_manoeuvre_only(self):
        """Manoeuvre detected with no NOTSO → manoeuvre_only."""
        mnv   = _FakeManoeuvre(_dt("2025-03-14T14:00:00"))
        corrs = correlate_notsos_with_manoeuvres([], [mnv], norad_id=43689)
        assert len(corrs) == 1
        assert corrs[0].correlation_type == "manoeuvre_only"

    def test_matched_has_time_offset(self):
        """Matched correlation includes time_offset_hours."""
        notso = self._notso(43689, "2025-03-14T12:00:00", "2025-03-14T18:00:00")
        mnv   = _FakeManoeuvre(_dt("2025-03-14T14:00:00"))
        corrs = correlate_notsos_with_manoeuvres([notso], [mnv], norad_id=43689)
        assert corrs[0].time_offset_hours is not None

    def test_matched_has_magnitude_ratio(self):
        """Matched correlation with known ΔVs includes magnitude_ratio."""
        notso = self._notso(43689, "2025-03-14T12:00:00", "2025-03-14T18:00:00")
        mnv   = _FakeManoeuvre(_dt("2025-03-14T14:00:00"), dv_km_s=0.010)
        corrs = correlate_notsos_with_manoeuvres([notso], [mnv], norad_id=43689)
        assert corrs[0].magnitude_ratio == pytest.approx(1.0, rel=0.01)

    def test_wrong_satno_excluded(self):
        """NOTSOs for a different NORAD ID are not correlated."""
        notso = self._notso(99999, "2025-03-14T12:00:00", "2025-03-14T18:00:00")
        mnv   = _FakeManoeuvre(_dt("2025-03-14T14:00:00"))
        corrs = correlate_notsos_with_manoeuvres([notso], [mnv], norad_id=43689)
        # NOTSO is excluded (wrong NORAD) → only manoeuvre_only
        assert corrs[0].correlation_type == "manoeuvre_only"

    def test_outside_tolerance_not_matched(self):
        """Manoeuvre outside tolerance window → separate entries."""
        notso = self._notso(43689, "2025-03-14T12:00:00", "2025-03-14T18:00:00")
        mnv   = _FakeManoeuvre(_dt("2025-03-17T00:00:00"))  # 3 days later
        corrs = correlate_notsos_with_manoeuvres([notso], [mnv], norad_id=43689,
                                                  time_tolerance_hours=1.0)
        types = {c.correlation_type for c in corrs}
        assert "matched" not in types

    def test_two_notsos_two_manoeuvres(self):
        """Two NOTSOs and two manoeuvres → two matched rows."""
        n1 = self._notso(43689, "2025-03-14T12:00:00", "2025-03-14T18:00:00", "N1")
        n2 = self._notso(43689, "2025-03-21T06:00:00", "2025-03-21T14:00:00", "N2")
        m1 = _FakeManoeuvre(_dt("2025-03-14T14:00:00"))
        m2 = _FakeManoeuvre(_dt("2025-03-21T10:00:00"))
        corrs = correlate_notsos_with_manoeuvres([n1, n2], [m1, m2], norad_id=43689)
        matched = [c for c in corrs if c.correlation_type == "matched"]
        assert len(matched) == 2


# ── Behaviour profile extraction ──────────────────────────────────────────────

class TestExtractBehaviourProfile:
    def _build_profile(self, n_total: int, n_matched: int) -> OperatorBehaviourProfile:
        """Build correlations with n_matched matched + (n_total-n_matched) manoeuvre-only."""
        correlations = []
        start = _dt("2025-01-01T00:00:00")
        for i in range(n_matched):
            notso = NOTSORecord(
                message_id=f"N{i:03d}",
                norad_id=43689,
                international_designator=None,
                object_name=None,
                issuing_entity="TEST",
                issue_date_utc=start + timedelta(days=i),
                effective_start_utc=start + timedelta(days=i, hours=12),
                effective_end_utc=start + timedelta(days=i, hours=18),
                notso_type=NOTSOType.MANOEUVRE,
                description="burn",
                predicted_delta_v_km_s=0.010,
                predicted_direction=None,
                raw_message="",
            )
            mnv = _FakeManoeuvre(start + timedelta(days=i, hours=14))
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=notso,
                manoeuvre=mnv,
                correlation_type="matched",
                time_offset_hours=-2.0,
                magnitude_ratio=1.0,
            ))
        for i in range(n_total - n_matched):
            mnv = _FakeManoeuvre(start + timedelta(days=100 + i))
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=None,
                manoeuvre=mnv,
                correlation_type="manoeuvre_only",
                time_offset_hours=None,
                magnitude_ratio=None,
            ))
        end = start + timedelta(days=200)
        return extract_behaviour_profile(43689, correlations, start, end)

    def test_notification_rate_all_notified(self):
        p = self._build_profile(5, 5)
        assert p.notification_rate == pytest.approx(1.0)
        assert p.consistent_notifier is True

    def test_notification_rate_none_notified(self):
        p = self._build_profile(5, 0)
        assert p.notification_rate == pytest.approx(0.0)
        assert p.stealth_operator is True

    def test_notification_rate_partial(self):
        p = self._build_profile(10, 6)
        assert p.notification_rate == pytest.approx(0.6)
        assert p.inconsistent_notifier is True

    def test_total_manoeuvres_counted(self):
        p = self._build_profile(7, 3)
        assert p.total_manoeuvres == 7
        assert p.manoeuvres_with_notso == 3
        assert p.manoeuvres_without_notso == 4

    def test_mean_lead_time_computed(self):
        """All matched rows have lead time = -2.0h."""
        p = self._build_profile(4, 4)
        assert p.mean_lead_time_h == pytest.approx(-2.0)

    def test_window_accuracy_rate(self):
        """Manoeuvre at t+14h falls inside window [t+12h, t+18h] → 100% accuracy."""
        p = self._build_profile(4, 4)
        assert p.window_accuracy_rate == pytest.approx(1.0)

    def test_phantom_notso_count(self):
        """notso_only correlations counted as phantom NOTSOs."""
        correlations = []
        start = _dt("2025-01-01T00:00:00")
        for i in range(3):
            notso = NOTSORecord(
                message_id=f"PHANTOM-{i}",
                norad_id=43689,
                international_designator=None,
                object_name=None,
                issuing_entity="TEST",
                issue_date_utc=start,
                effective_start_utc=start + timedelta(days=i),
                effective_end_utc=start + timedelta(days=i, hours=6),
                notso_type=NOTSOType.MANOEUVRE,
                description="phantom",
                predicted_delta_v_km_s=None,
                predicted_direction=None,
                raw_message="",
            )
            correlations.append(NOTSOManoeuvreCorrelation(
                notso=notso,
                manoeuvre=None,
                correlation_type="notso_only",
                time_offset_hours=None,
                magnitude_ratio=None,
            ))
        p = extract_behaviour_profile(43689, correlations, start, start + timedelta(days=100))
        assert p.phantom_notso_count == 3
