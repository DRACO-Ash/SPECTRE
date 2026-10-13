"""The composite threat verdict, and the contradiction it exists to remove.

The sweep used to score a satellite assessed LOW and Degraded as CRITICAL,
because its verdict was four thresholds on a delta-V number and nothing else.
The intelligence panel beside it said the opposite. These cases pin the
behaviours that stop that happening, and the ones that stop the fix
over-correcting into silence.
"""

from __future__ import annotations

import pytest

from spectre.domain.threat_assessment import (
    AccessEvidence,
    Band,
    CapabilityEvidence,
    assess_threat,
    warning_time_rank,
)

# Delta-v is in m/s throughout, and a cost only means something against a
# regime and a kind of manoeuvre: 50 m/s is one routine year at GEO and fifty
# years of it at MEO. A GEO proximity operation is used as the running example
# because that is the shape of every observed counterspace event on record.
_GEO_PROX = {"method": "vbar_hop", "regime": "GEO"}


class TestTheContradictionIsGone:
    """The worked example from the red team, asserted."""

    def test_a_degraded_object_is_not_critical_however_close_the_geometry(self) -> None:
        """Kowsar: assessed LOW / Degraded, cheap geometric path."""
        access = AccessEvidence(
            best_delta_v_m_s=8.0, time_to_arrival_hours=3.0, **_GEO_PROX,
        )
        assert access.band() is Band.CRITICAL, (
            "8 m/s of proximity work is inside what this object already spends "
            "on routine operations, which is as permissive as geometry gets"
        )

        capability = CapabilityEvidence(
            intel_threat_level="LOW", operational_status="Degraded",
        )
        result = assess_threat(access, capability)

        assert result.verdict is Band.MINIMAL, (
            "a satellite recorded as Degraded cannot fly the intercept the geometry "
            f"permits; verdict was {result.verdict_label}"
        )
        assert result.access is Band.CRITICAL, "the geometric finding is not erased"
        assert "Degraded" in result.rationale

    def test_the_two_findings_stay_separately_visible(self) -> None:
        """One word cannot carry both, which is how they contradicted."""
        result = assess_threat(
            AccessEvidence(best_delta_v_m_s=8.0, time_to_arrival_hours=3.0, **_GEO_PROX),
            CapabilityEvidence(intel_threat_level="LOW", operational_status="Degraded"),
        )
        assert result.access_label == "CRITICAL"
        assert result.capability_label == "MINIMAL"
        assert result.verdict_label == "MINIMAL"


class TestAnUnknownObjectIsNotTreatedAsHarmless:
    """The failure mode the fix could easily introduce."""

    def test_no_capability_evidence_falls_back_to_geometry(self) -> None:
        result = assess_threat(
            AccessEvidence(best_delta_v_m_s=8.0, time_to_arrival_hours=1.0, **_GEO_PROX),
            CapabilityEvidence(),
        )
        assert result.verdict is Band.CRITICAL, (
            "an unassessed object must not be scored as incapable"
        )
        assert result.capability is None
        assert result.capability_label == "UNASSESSED"
        assert result.confidence == "LOW"
        assert "may" in result.rationale and "overstate" in result.rationale

    def test_confidence_reflects_how_much_evidence_was_actually_had(self) -> None:
        thin = assess_threat(
            AccessEvidence(30.0, 6.0, **_GEO_PROX),
            CapabilityEvidence(intel_threat_level="HIGH"),
        )
        thick = assess_threat(
            AccessEvidence(30.0, 6.0, **_GEO_PROX),
            CapabilityEvidence(
                intel_threat_level="HIGH", operational_status="Operational",
                propellant_used_pct=20.0, anomaly_score=75.0, manoeuvres_observed=4,
            ),
        )
        assert thin.confidence == "MEDIUM"
        assert thick.confidence == "HIGH"
        assert "propellant budget" in thick.inputs_used
        assert "propellant budget" in thin.inputs_missing


class TestTheWeakerSideGoverns:
    @pytest.mark.parametrize(
        ("dv", "intel", "status", "expected"),
        [
            # Capable object, a manoeuvre inside its routine budget: the real thing.
            (8.0, "CRITICAL", "Operational", Band.CRITICAL),
            # Capable object, a cost beyond any flown platform's reserve.
            (3500.0, "CRITICAL", "Operational", Band.MINIMAL),
            # Weakly assessed object, routine-cost geometry.
            (8.0, "MEDIUM", "Operational", Band.MEDIUM),
            # Both moderate: an observed-campaign cost against a HIGH object.
            (40.0, "HIGH", "Operational", Band.HIGH),
        ],
    )
    def test_verdict_is_the_weaker_of_access_and_capability(
        self, dv: float, intel: str, status: str, expected: Band
    ) -> None:
        result = assess_threat(
            AccessEvidence(
                best_delta_v_m_s=dv, time_to_arrival_hours=48.0, **_GEO_PROX,
            ),
            CapabilityEvidence(intel_threat_level=intel, operational_status=status),
        )
        assert result.verdict is expected

    def test_a_spent_object_cannot_act_whatever_the_intel_says(self) -> None:
        result = assess_threat(
            AccessEvidence(8.0, 2.0, **_GEO_PROX),
            CapabilityEvidence(
                intel_threat_level="CRITICAL", operational_status="Operational",
                propellant_used_pct=99.0,
            ),
        )
        assert result.verdict is Band.MINIMAL, (
            "propellant spent means the intercept cannot be flown"
        )


class TestCapabilityEvidenceReadsTheRealData:
    """Status strings come from the shipped intelligence file, not a schema."""

    @pytest.mark.parametrize(
        "status",
        [
            "Degraded",
            "Inactive - Retired / Not Manoeuverable",
            "Non-operational",
            "DECAYED",
        ],
    )
    def test_impaired_statuses_are_recognised(self, status: str) -> None:
        assert CapabilityEvidence(operational_status=status).is_impaired()

    @pytest.mark.parametrize("status", ["Operational", "Active - Inclined (aged) / Manoeuverable"])
    def test_working_statuses_are_not_flagged(self, status: str) -> None:
        assert not CapabilityEvidence(operational_status=status).is_impaired()

    def test_an_unrecognised_threat_label_is_no_evidence_not_low_evidence(self) -> None:
        """A typo or a new label must not silently downgrade an object."""
        capability = CapabilityEvidence(intel_threat_level="SEVERE")
        assert capability.band() is None, (
            "an unparseable label should contribute nothing, not MINIMAL"
        )

    def test_a_high_anomaly_score_raises_capability_on_its_own(self) -> None:
        quiet = CapabilityEvidence(anomaly_score=20.0).band()
        loud = CapabilityEvidence(anomaly_score=85.0).band()
        assert loud is not None and quiet is not None and loud > quiet


class TestWarningTimeRanking:
    """Delta-V is the filter; time is the ranking."""

    def test_a_faster_intercept_outranks_a_cheaper_slower_one(self) -> None:
        cheap_and_slow = warning_time_rank(120.0, 40.0, budget_m_s=500.0)
        dear_and_fast = warning_time_rank(450.0, 0.6, budget_m_s=500.0)
        assert dear_and_fast < cheap_and_slow, (
            "35 minutes of warning is a harder problem than 40 hours, whatever it costs"
        )

    def test_an_unaffordable_intercept_sorts_last_however_fast(self) -> None:
        unaffordable = warning_time_rank(9000.0, 0.1, budget_m_s=500.0)
        affordable = warning_time_rank(500.0, 47.0, budget_m_s=500.0)
        assert affordable < unaffordable, (
            "an intercept that cannot be flown buys no warning at all"
        )

    def test_ordering_a_realistic_set(self) -> None:
        entries = [
            ("cheap, two days", 100.0, 48.0),
            ("moderate, six hours", 400.0, 6.0),
            ("dear, thirty minutes", 800.0, 0.5),
            ("unaffordable, instant", 12000.0, 0.1),
        ]
        ordered = sorted(entries, key=lambda e: warning_time_rank(e[1], e[2], 1000.0))
        assert [name for name, _, _ in ordered] == [
            "dear, thirty minutes",
            "moderate, six hours",
            "cheap, two days",
            "unaffordable, instant",
        ]
