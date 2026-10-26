"""A quiet signal does not raise an assessed threat level (audit F-120).

Any anomaly score, 0 included, graded capability at least MEDIUM, and any
propellant figure did the same; the strongest signal governs, so an object
assessed LOW with a quiet anomaly score of 5 was graded MEDIUM. The anomaly
cut-offs, 60 and 80, also disagreed with the Pattern of Life ladder that
calls 55 HIGH, so one score read HIGH in one panel and MEDIUM in the other.
"""

from __future__ import annotations

import pytest

from spectre.domain.pol_assessment import _RISK_LADDER, anomaly_risk_level
from spectre.domain.threat_assessment import Band, CapabilityEvidence


def test_low_intel_with_a_quiet_anomaly_score_stays_low() -> None:
    evidence = CapabilityEvidence(intel_threat_level="LOW", anomaly_score=5.0)
    assert evidence.band() == Band.LOW


def test_low_intel_with_a_scarce_reserve_stays_low() -> None:
    evidence = CapabilityEvidence(intel_threat_level="LOW", discretionary_remaining_m_s=20.0, discretionary_max_m_s=200.0)
    assert evidence.band() == Band.LOW


@pytest.mark.parametrize("score", [0.0, 14.9, 15.0, 34.9, 35.0, 54.9, 55.0, 74.9, 75.0, 100.0])
def test_the_anomaly_score_reads_the_same_band_in_both_panels(score: float) -> None:
    assert CapabilityEvidence(anomaly_score=score).band() == Band[anomaly_risk_level(score)]


def test_55_is_high_in_both() -> None:
    assert {level: t for t, level in _RISK_LADDER}["HIGH"] == 55.0
    assert CapabilityEvidence(anomaly_score=57.0).band() == Band.HIGH
