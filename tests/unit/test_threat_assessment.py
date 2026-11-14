"""The composite threat verdict, and the contradiction it exists to remove.

The sweep used to score a satellite assessed LOW and Degraded as CRITICAL,
because its verdict was four thresholds on a delta-V number and nothing else.
The intelligence panel beside it said the opposite. These cases pin the
behaviours that stop that happening, and the ones that stop the fix
over-correcting into silence.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from spectre.domain.custody import Custody
from spectre.domain.threat_assessment import (
    AccessEvidence,
    Band,
    CapabilityEvidence,
    ConfidenceContext,
    ThreatAssessment,
    assess_threat,
    warning_time_rank,
)

# Delta-v is in m/s throughout, and a cost only means something against a
# regime and a kind of manoeuvre: 50 m/s is one routine year at GEO and fifty
# years of it at MEO. A GEO proximity operation is used as the running example
# because that is the shape of every observed counterspace event on record.
_GEO_PROX = {"method": "vbar_hop", "regime": "GEO"}

# Live tracking and the interceptor in custody: nothing outside the evidence
# holds confidence down, so a level is the evidence's own.
_HELD_REAL = ConfidenceContext(data_mode="REAL", custody=Custody.HELD)


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

    def test_confidence_reflects_how_much_independent_evidence_was_had(self) -> None:
        """SPC-160: an assessed label alone is one source and reads LOW, not MEDIUM."""
        thin = assess_threat(
            AccessEvidence(30.0, 6.0, **_GEO_PROX),
            CapabilityEvidence(intel_threat_level="HIGH"),
            _HELD_REAL,
        )
        thick = assess_threat(
            AccessEvidence(30.0, 6.0, **_GEO_PROX),
            CapabilityEvidence(
                intel_threat_level="HIGH", intel_record_dated=True, operational_status="Operational",
                propellant_used_pct=20.0, anomaly_score=75.0, manoeuvres_observed=4,
            ),
            _HELD_REAL,
        )
        assert thin.confidence == "LOW"
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


# ─────────────────────────────────────────────────────────────────────────────
# SPC-160: confidence stops counting copies and geometry
# ─────────────────────────────────────────────────────────────────────────────

#: The order the three levels rise in.
_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2}

#: A GEO proximity approach in 31 hours: as permissive as geometry gets.
_CRITICAL_ACCESS = AccessEvidence(8.0, 31.0, **_GEO_PROX)

#: The six capability inputs ``assess_threat`` lists, each as the fields it
#: sets. The discretionary reserve brings its maximum with it, as the route
#: always supplies the two together.
_SIX_INPUTS: dict[str, dict[str, Any]] = {
    # Dated, so it can establish identity: none of the bundled records is.
    "assessed threat level": {"intel_threat_level": "HIGH", "intel_record_dated": True},
    "operational status": {"operational_status": "Operational"},
    "propellant budget": {"propellant_used_pct": 20.0},
    "discretionary reserve": {"discretionary_remaining_m_s": 80.0, "discretionary_max_m_s": 120.0},
    "behavioural anomaly score": {"anomaly_score": 75.0},
    "observed manoeuvre history": {"manoeuvres_observed": 4},
}

#: The four figures derived from one element-set history.
_HISTORY_FIGURES = (
    "propellant budget", "discretionary reserve", "behavioural anomaly score", "observed manoeuvre history",
)


def _assess(names: tuple[str, ...], context: ConfidenceContext | None = _HELD_REAL,
            inputs: dict[str, dict[str, Any]] | None = None) -> ThreatAssessment:
    table = inputs or _SIX_INPUTS
    fields: dict[str, Any] = {}
    for name in names:
        fields.update(table[name])
    return assess_threat(_CRITICAL_ACCESS, CapabilityEvidence(**fields), context)


def _full(**overrides: Any) -> CapabilityEvidence:
    """All six inputs held, a capable object with observed burns."""
    fields: dict[str, Any] = {}
    for value in _SIX_INPUTS.values():
        fields.update(value)
    fields.update(overrides)
    return CapabilityEvidence(**fields)


class TestTheFourMeasuredCases:
    """I12: the cases measured at f8c40c7, held as fixed regression cases.

    The verdict band does not change in this item; only the confidence does.
    """

    def test_no_intel_record_and_a_history_with_no_burns_reads_low(self) -> None:
        """Was capability HIGH at confidence HIGH, on geometry, a full tank counted twice and "0 burns"."""
        result = assess_threat(_CRITICAL_ACCESS, CapabilityEvidence(
            propellant_used_pct=0.0, discretionary_remaining_m_s=120.0, discretionary_max_m_s=120.0,
            manoeuvres_observed=0, history_span_days=400.0,
        ), _HELD_REAL)
        assert result.confidence == "LOW", "one history, and an absence of burns, is not a well-founded picture"
        assert result.capability is Band.HIGH, "the verdict band is not this item's to change"
        assert result.verdict is Band.HIGH

    def test_an_intel_record_alone_reads_low(self) -> None:
        """Was MEDIUM: one undated analyst label, one source."""
        result = assess_threat(
            _CRITICAL_ACCESS, CapabilityEvidence(intel_threat_level="HIGH", operational_status="Operational"),
            _HELD_REAL,
        )
        assert result.confidence == "LOW"
        assert result.verdict is Band.HIGH

    def test_an_unrecognised_label_is_listed_as_missing_with_the_reason(self) -> None:
        """Was listed as "used" while adding nothing."""
        result = assess_threat(_CRITICAL_ACCESS, CapabilityEvidence(intel_threat_level="SEVERE"), _HELD_REAL)
        assert result.confidence == "LOW"
        assert "assessed threat level" not in result.inputs_used
        missing = [m for m in result.inputs_missing if m.startswith("assessed threat level")]
        assert missing, result.inputs_missing
        assert "SEVERE" in missing[0] and "not a recognised band" in missing[0]

    def test_geometry_alone_reads_low(self) -> None:
        result = assess_threat(_CRITICAL_ACCESS, CapabilityEvidence(), _HELD_REAL)
        assert result.confidence == "LOW"
        assert result.verdict is Band.CRITICAL


class TestAddingEvidenceNeverLowersConfidence:
    """Across all 64 subsets of the six inputs, adding one never lowers the level unless it adds a conflict."""

    _CONTEXTS = (
        _HELD_REAL,
        ConfidenceContext(data_mode="REAL", custody=Custody.DEGRADED),
        ConfidenceContext(data_mode="MANUAL", custody=Custody.HELD, manual_confidence="HIGH"),
        ConfidenceContext(),
    )

    def test_there_are_sixty_four_subsets(self) -> None:
        subsets = [s for r in range(len(_SIX_INPUTS) + 1) for s in itertools.combinations(_SIX_INPUTS, r)]
        assert len(subsets) == 64

    @pytest.mark.parametrize("status", ["Operational", "Degraded"])
    @pytest.mark.parametrize("burns", [0, 1, 4])
    @pytest.mark.parametrize("context", _CONTEXTS)
    def test_adding_one_input_never_lowers_the_level_unless_it_adds_a_conflict(
        self, status: str, burns: int, context: ConfidenceContext,
    ) -> None:
        inputs = {**_SIX_INPUTS, "operational status": {"operational_status": status},
                  "observed manoeuvre history": {"manoeuvres_observed": burns}}
        names = tuple(inputs)
        for size in range(len(names) + 1):
            for subset in itertools.combinations(names, size):
                before = _assess(subset, context, inputs)
                assert before.confidence in _RANK, before.confidence
                for extra in (n for n in names if n not in subset):
                    after = _assess((*subset, extra), context, inputs)
                    added_conflict = bool(after.confidence_conflict) and not before.confidence_conflict
                    assert added_conflict or _RANK[after.confidence] >= _RANK[before.confidence], (
                        f"adding {extra} to {subset} lowered {before.confidence} to {after.confidence}"
                    )

    def test_the_conflict_exception_is_real(self) -> None:
        """Proof the exception has teeth: a status the burns contradict does lower the level."""
        inputs = {**_SIX_INPUTS, "operational status": {"operational_status": "Degraded"}}
        without = _assess(tuple(n for n in inputs if n != "operational status"), _HELD_REAL, inputs)
        with_it = _assess(tuple(inputs), _HELD_REAL, inputs)
        assert without.confidence == "HIGH"
        assert with_it.confidence == "MODERATE"
        assert with_it.confidence_conflict


class TestAConflictIsNamedAndCapped:
    def test_a_status_the_burns_contradict_is_named_as_possible_deception(self) -> None:
        result = assess_threat(_CRITICAL_ACCESS, _full(operational_status="Degraded"), _HELD_REAL)
        assert result.confidence == "MODERATE"
        assert "Degraded" in result.confidence_conflict
        assert "4 burns" in result.confidence_conflict
        assert "possible deception" in result.confidence_conflict
        assert result.confidence_conflict in result.confidence_basis
        assert result.verdict is Band.MINIMAL, "the status still sets the verdict until SPC-167"

    def test_a_single_burn_against_an_impaired_status_is_a_conflict(self) -> None:
        """One confirmed burn is enough to contradict a status saying the object cannot manoeuvre."""
        result = assess_threat(
            _CRITICAL_ACCESS, _full(operational_status="Degraded", manoeuvres_observed=1), _HELD_REAL,
        )
        assert result.confidence == "MODERATE"
        assert result.confidence_conflict == (
            "the record says Degraded, but the history shows 1 burn: possible deception"
        )

    def test_a_working_status_is_no_conflict(self) -> None:
        assert assess_threat(_CRITICAL_ACCESS, _full(), _HELD_REAL).confidence_conflict == ""

    def test_an_impaired_status_with_no_burns_is_no_conflict(self) -> None:
        result = assess_threat(
            _CRITICAL_ACCESS, _full(operational_status="Degraded", manoeuvres_observed=0), _HELD_REAL,
        )
        assert result.confidence_conflict == ""


class TestTheDataModeCapsConfidence:
    @pytest.mark.parametrize("mode", ["SYNTHETIC", "TEST", "EXERCISE", "SIMULATED", "synthetic"])
    def test_a_set_that_is_not_live_tracking_reads_low(self, mode: str) -> None:
        result = assess_threat(_CRITICAL_ACCESS, _full(), ConfidenceContext(data_mode=mode, custody=Custody.HELD))
        assert result.confidence == "LOW"
        assert f"computed from {mode.upper()} element sets: describes the exercise, not the satellite" in (
            result.confidence_basis
        )

    def test_live_tracking_does_not_cap(self) -> None:
        assert assess_threat(_CRITICAL_ACCESS, _full(), _HELD_REAL).confidence == "HIGH"

    @pytest.mark.parametrize(("stated", "expected"), [
        ("CONFIRMED", "HIGH"), ("HIGH", "HIGH"), ("MEDIUM", "MODERATE"), ("LOW", "LOW"),
        ("UNCONFIRMED", "LOW"), (None, "MODERATE"),
    ])
    def test_a_hand_entered_set_caps_at_the_operators_stated_confidence(
        self, stated: str | None, expected: str,
    ) -> None:
        context = ConfidenceContext(data_mode="MANUAL", custody=Custody.HELD, manual_confidence=stated)
        result = assess_threat(_CRITICAL_ACCESS, _full(), context)
        assert result.confidence == expected
        assert ("entered by hand" in result.confidence_basis) is (expected != "HIGH")

    @pytest.mark.parametrize("mode", [None, "UNKNOWN", ""])
    def test_an_unrecorded_mode_caps_at_moderate(self, mode: str | None) -> None:
        result = assess_threat(_CRITICAL_ACCESS, _full(), ConfidenceContext(data_mode=mode, custody=Custody.HELD))
        assert result.confidence == "MODERATE"
        assert "data mode is not recorded" in result.confidence_basis


class TestCustodyCapsConfidence:
    def test_custody_lost_reads_low(self) -> None:
        result = assess_threat(_CRITICAL_ACCESS, _full(), ConfidenceContext(data_mode="REAL", custody=Custody.LOST))
        assert result.confidence == "LOW"
        assert "custody of the interceptor is lost" in result.confidence_basis

    def test_custody_degraded_reads_at_most_moderate(self) -> None:
        context = ConfidenceContext(data_mode="REAL", custody=Custody.DEGRADED)
        result = assess_threat(_CRITICAL_ACCESS, _full(), context)
        assert result.confidence == "MODERATE"
        assert "custody of the interceptor is degraded" in result.confidence_basis

    def test_custody_not_assessed_reads_at_most_moderate(self) -> None:
        """The screen does not assess custody yet (SPC-169), so it cannot claim HIGH."""
        result = assess_threat(_CRITICAL_ACCESS, _full(), ConfidenceContext(data_mode="REAL"))
        assert result.confidence == "MODERATE"
        assert "custody was not assessed" in result.confidence_basis

    def test_no_context_at_all_reads_at_most_moderate(self) -> None:
        assert assess_threat(_CRITICAL_ACCESS, _full()).confidence == "MODERATE"


class TestOneHistoryCountsOnce:
    """Propellant used, discretionary reserve, anomaly index and burn count come from one element-set history."""

    @pytest.mark.parametrize("figures", [
        s for r in range(1, len(_HISTORY_FIGURES) + 1) for s in itertools.combinations(_HISTORY_FIGURES, r)
    ])
    def test_however_many_figures_one_history_gives_it_is_one_source(self, figures: tuple[str, ...]) -> None:
        result = _assess(figures)
        assert result.confidence != "HIGH", "one history is one source, not four"
        assert result.confidence_basis.count("the element-set history") == 1
        assert "1 independent source" in result.confidence_basis

    def test_a_second_figure_on_the_same_reading_changes_nothing(self) -> None:
        reserve = _assess(("discretionary reserve",))
        both = _assess(("discretionary reserve", "propellant budget"))
        assert (both.confidence, both.confidence_basis) == (reserve.confidence, reserve.confidence_basis)
        burns = _assess(("observed manoeuvre history",))
        burns_and_index = _assess(("observed manoeuvre history", "behavioural anomaly score"))
        assert (burns_and_index.confidence, burns_and_index.confidence_basis) == (
            burns.confidence, burns.confidence_basis,
        )

    def test_the_record_and_the_history_are_two_sources(self) -> None:
        result = _assess(tuple(_SIX_INPUTS))
        assert result.confidence == "HIGH"
        assert "2 independent sources" in result.confidence_basis
        assert "the assessed record" in result.confidence_basis


class TestGeometryNoLongerCounts:
    @pytest.mark.parametrize("access", [
        AccessEvidence(8.0, 31.0, **_GEO_PROX),      # CRITICAL
        AccessEvidence(401.0, 31.0, **_GEO_PROX),    # MEDIUM
        AccessEvidence(3500.0, 31.0, **_GEO_PROX),   # MINIMAL
    ])
    @pytest.mark.parametrize("names", [(), ("assessed threat level",), tuple(_SIX_INPUTS)])
    def test_the_level_is_the_same_whatever_the_geometry(
        self, access: AccessEvidence, names: tuple[str, ...],
    ) -> None:
        baseline = _assess(names)
        fields: dict[str, Any] = {}
        for name in names:
            fields.update(_SIX_INPUTS[name])
        result = assess_threat(access, CapabilityEvidence(**fields), _HELD_REAL)
        assert result.confidence == baseline.confidence
        assert "Orbital geometry is not counted" in result.confidence_basis

    def test_nothing_but_geometry_says_so(self) -> None:
        result = _assess(())
        assert "0 independent sources" in result.confidence_basis


class TestAnUndatedRecordDoesNotEstablishIdentity:
    """Concept 4.3 and 4.12 row 1: an undated, single-source record scores 0.09, below the 0.25 an item needs.

    All 44 bundled intel records are undated, so on today's data identity is not
    held and confidence stops at MODERATE. The verdict still reads the label.
    """

    @staticmethod
    def _worked_example_row_three(**overrides: Any) -> ThreatAssessment:
        """Concept 4.12: a GEO approach at 9 m/s in 31 h, the undated record and a 400-day history."""
        fields: dict[str, Any] = {
            "intel_threat_level": "HIGH", "operational_status": "Operational",
            "propellant_used_pct": 40.0, "discretionary_remaining_m_s": 72.0, "discretionary_max_m_s": 120.0,
            "anomaly_score": 60.0, "manoeuvres_observed": 23, "history_span_days": 400.0,
        }
        fields.update(overrides)
        return assess_threat(AccessEvidence(9.0, 31.0, **_GEO_PROX), CapabilityEvidence(**fields), _HELD_REAL)

    def test_the_worked_example_at_row_three_does_not_read_high(self) -> None:
        """Was HIGH: "Today's HIGH confidence on row 3's evidence was not earned"."""
        result = self._worked_example_row_three()
        assert result.confidence == "MODERATE"
        assert "Rests on 1 independent source" in result.confidence_basis
        assert "the assessed record, which carries no date, so cannot establish identity" in (
            result.confidence_basis
        )
        assert "identity not held" in result.confidence_basis
        assert result.verdict is Band.HIGH, "the verdict band is not this item's to change"
        assert "assessed threat level" in result.inputs_used, "the verdict still reads the label"

    def test_a_dated_record_establishes_identity(self) -> None:
        result = self._worked_example_row_three(intel_record_dated=True)
        assert result.confidence == "HIGH"
        assert "2 independent sources" in result.confidence_basis
        assert "carries no date" not in result.confidence_basis

    def test_an_undated_record_alone_reads_low_and_counts_nothing(self) -> None:
        result = assess_threat(_CRITICAL_ACCESS, CapabilityEvidence(intel_threat_level="CRITICAL"), _HELD_REAL)
        assert result.confidence == "LOW"
        assert "0 independent sources" in result.confidence_basis

    def test_an_unrecognised_label_does_not_count_beside_a_full_history(self) -> None:
        """I12 case 3 in confidence form: a typo with a full history must not read HIGH."""
        result = assess_threat(_CRITICAL_ACCESS, _full(intel_threat_level="SEVERE"), _HELD_REAL)
        assert result.confidence == "MODERATE"
        assert "Rests on 1 independent source" in result.confidence_basis
        assert "the assessed record (identity)" not in result.confidence_basis


class TestTheBasisSaysWhatIsNotCountedAndWhatIsMissing:
    """Concept 6.3: the statement names what is missing; I12 case 1 shows "0 burns" as an absence."""

    def test_a_declared_status_is_named_as_not_counted(self) -> None:
        result = assess_threat(_CRITICAL_ACCESS, _full(operational_status="Operational"), _HELD_REAL)
        assert "Not counted: the recorded status 'Operational', which is declared, not observed." in (
            result.confidence_basis
        )

    def test_no_burns_is_named_as_an_absence(self) -> None:
        result = assess_threat(_CRITICAL_ACCESS, CapabilityEvidence(
            propellant_used_pct=0.0, discretionary_remaining_m_s=120.0, discretionary_max_m_s=120.0,
            manoeuvres_observed=0, history_span_days=400.0,
        ), _HELD_REAL)
        assert "no burns observed, an absence rather than a reading" in result.confidence_basis

    def test_a_moderate_level_names_the_one_dimension_missing(self) -> None:
        result = _assess(("propellant budget", "behavioural anomaly score"))
        assert result.confidence == "MODERATE"
        assert "Not higher because: identity not held." in result.confidence_basis

    def test_a_low_level_names_the_dimensions_missing(self) -> None:
        result = _assess(("assessed threat level",))
        assert result.confidence == "LOW"
        assert "Not higher because: capability, behaviour not held." in result.confidence_basis
