"""Which of these objects threatens my asset, and would I know if I were wrong?

Screening a blue asset inverts the sweep: instead of one red object against
many targets, it is many candidate actors against one asset. That makes
ranking the whole problem, because the analyst is being told which object to
brief.

Two ways to get it wrong, and the ranking rule has to avoid both:

  * rank on warning time alone and a derelict tops the list, undoing the
    composite verdict entirely;
  * rank on verdict alone and a fast approach is buried behind a capability
    assessment that might simply be out of date.

So both are computed, and where they disagree the disagreement is the finding.
"""

from __future__ import annotations

import pytest

from spectre.domain.threat_assessment import (
    AccessEvidence,
    ActorVerdict,
    Band,
    CapabilityEvidence,
    assess_threat,
    rank_actors,
)


def _verdict(
    name: str,
    satno: str,
    *,
    delta_v_m_s: float,
    warning_hours: float,
    intel: str | None = None,
    status: str | None = None,
    method: str = "vbar_hop",
    regime: str = "GEO",
) -> ActorVerdict:
    """An actor verdict built through the real assessment, not hand-set."""
    assessment = assess_threat(
        AccessEvidence(
            best_delta_v_m_s=delta_v_m_s,
            time_to_arrival_hours=warning_hours,
            method=method,
            regime=regime,
        ),
        CapabilityEvidence(intel_threat_level=intel, operational_status=status),
    )
    return ActorVerdict(
        actor_name=name,
        actor_satno=satno,
        assessment=assessment,
        warning_hours=warning_hours,
        delta_v_m_s=delta_v_m_s,
        method=method,
    )


class TestTheDisagreementIsTheFinding:
    """The case the whole design exists for."""

    def test_a_capable_slow_actor_outranks_a_derelict_fast_one(self) -> None:
        capable = _verdict(
            "TJS-3", "43874", delta_v_m_s=8.0, warning_hours=6.2,
            intel="CRITICAL", status="Operational",
        )
        derelict = _verdict(
            "COSMOS 2535", "44797", delta_v_m_s=9.0, warning_hours=0.68,
            intel="LOW", status="Inactive - Retired / Not Manoeuverable",
        )
        result = rank_actors([derelict, capable])

        assert result.most_dangerous is not None
        assert result.most_dangerous.actor_name == "TJS-3", (
            "ranking on warning time alone would put a retired object top"
        )
        assert result.earliest_arrival is not None
        assert result.earliest_arrival.actor_name == "COSMOS 2535"

    def test_the_disagreement_is_stated_in_words(self) -> None:
        capable = _verdict(
            "TJS-3", "43874", delta_v_m_s=8.0, warning_hours=6.2,
            intel="CRITICAL", status="Operational",
        )
        derelict = _verdict(
            "COSMOS 2535", "44797", delta_v_m_s=9.0, warning_hours=0.68,
            intel="LOW", status="Inactive - Retired / Not Manoeuverable",
        )
        result = rank_actors([derelict, capable])

        assert result.disagreement, (
            "when the most capable object and the soonest arrival are "
            "different objects, an analyst has to be told"
        )
        assert "COSMOS 2535" in result.disagreement
        assert "TJS-3" in result.disagreement
        assert "0.7 h" in result.disagreement
        assert "If that assessment is wrong" in result.disagreement

    def test_no_disagreement_is_reported_when_they_are_the_same_object(self) -> None:
        worst = _verdict(
            "TJS-3", "43874", delta_v_m_s=8.0, warning_hours=1.0,
            intel="CRITICAL", status="Operational",
        )
        other = _verdict(
            "SL-12 R/B", "27051", delta_v_m_s=300.0, warning_hours=40.0,
            intel="LOW", status="Operational",
        )
        result = rank_actors([worst, other])
        assert result.most_dangerous is not None
        assert result.earliest_arrival is not None
        assert result.most_dangerous.actor_satno == result.earliest_arrival.actor_satno
        assert result.disagreement == "", "nothing disagrees, so say nothing"


class TestNothingIsEverDropped:
    """"Nothing listed" and "nothing can reach you" must not look the same."""

    def test_a_minimal_actor_is_ranked_last_not_removed(self) -> None:
        derelict = _verdict(
            "COSMOS 2535", "44797", delta_v_m_s=9.0, warning_hours=0.5,
            intel="LOW", status="Decayed",
        )
        capable = _verdict(
            "TJS-3", "43874", delta_v_m_s=8.0, warning_hours=20.0,
            intel="HIGH", status="Operational",
        )
        result = rank_actors([derelict, capable])

        assert len(result.ranked) == 2, "the derelict is still on the list"
        assert result.ranked[-1].actor_name == "COSMOS 2535"
        assert result.ranked[-1].verdict is Band.MINIMAL

    def test_an_unassessed_actor_is_ranked_on_its_geometry(self) -> None:
        """No intelligence record is not evidence of harmlessness."""
        unknown = _verdict("UNKNOWN OBJECT", "99999", delta_v_m_s=8.0, warning_hours=2.0)
        known_weak = _verdict(
            "KOWSAR", "55555", delta_v_m_s=8.0, warning_hours=1.0,
            intel="LOW", status="Degraded",
        )
        result = rank_actors([known_weak, unknown])

        assert result.most_dangerous is not None
        assert result.most_dangerous.actor_name == "UNKNOWN OBJECT", (
            "an object nobody has assessed must not sort below one assessed "
            "incapable, however much sooner the latter could arrive"
        )
        assert result.most_dangerous.assessment.confidence == "LOW"
        assert "may" in result.most_dangerous.assessment.rationale

    def test_an_empty_actor_list_returns_empty_rather_than_raising(self) -> None:
        result = rank_actors([])
        assert result.ranked == []
        assert result.most_dangerous is None
        assert result.earliest_arrival is None
        assert result.disagreement == ""


class TestTheRankingOrder:
    def test_verdict_leads_then_warning_time_then_cost(self) -> None:
        actors = [
            _verdict("slow but critical", "1", delta_v_m_s=8.0, warning_hours=30.0,
                     intel="CRITICAL", status="Operational"),
            _verdict("fast and critical", "2", delta_v_m_s=8.0, warning_hours=2.0,
                     intel="CRITICAL", status="Operational"),
            _verdict("fast but degraded", "3", delta_v_m_s=8.0, warning_hours=0.3,
                     intel="HIGH", status="Degraded"),
            _verdict("moderate", "4", delta_v_m_s=55.0, warning_hours=10.0,
                     intel="MEDIUM", status="Operational"),
        ]
        ordered = [v.actor_name for v in rank_actors(actors).ranked]
        assert ordered[0] == "fast and critical"
        assert ordered[1] == "slow but critical"
        assert ordered[-1] == "fast but degraded", (
            "a degraded object sorts last however quickly it could arrive"
        )

    def test_cost_breaks_a_tie_on_verdict_and_warning_time(self) -> None:
        cheap = _verdict("cheap", "1", delta_v_m_s=8.0, warning_hours=4.0,
                         intel="HIGH", status="Operational")
        dear = _verdict("dear", "2", delta_v_m_s=45.0, warning_hours=4.0,
                        intel="HIGH", status="Operational")
        ordered = [v.actor_name for v in rank_actors([dear, cheap]).ranked]
        assert ordered == ["cheap", "dear"]


class TestTheVerdictCarriesItsWorking:
    def test_each_actor_keeps_the_figures_behind_its_verdict(self) -> None:
        v = _verdict("TJS-3", "43874", delta_v_m_s=8.0, warning_hours=6.2,
                     intel="CRITICAL", status="Operational")
        assert v.delta_v_m_s == pytest.approx(8.0)
        assert v.warning_hours == pytest.approx(6.2)
        assert v.verdict_label == v.assessment.verdict_label
        assert v.assessment.posture_label == "BENIGN", (
            "8 m/s of GEO proximity work is inside routine operations"
        )
