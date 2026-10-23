"""Pattern of Life interpretation, against the cited open-source figures.

Source throughout: *Satellite Manoeuvre Delta-v: Feasibility Above 0.5 km/s and
Budgets by Regime* (Bluestaq Limited Space Watch, v1.0, 13 October 2026).

Every test here is a regression guard on a measured failure. Before this module
existed, Pattern of Life carried its own uncited constants and the open-source
assessment's own named counterspace events classified as routine station-keeping
against them.
"""

from __future__ import annotations

import math
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.pattern_of_life import analyse_pattern_of_life
from spectre.domain.manoeuvre_calibration import (
    DEFAULT_SWEEP_BUDGET_M_S,
    ON_STATION_ANOMALY_M_S,
    PLATFORM_CLASSES,
    ManoeuvreKind,
    classify_posture,
    per_event_station_keeping_m_s,
    platform_class_for_regime,
    platform_total_budget_m_s,
    propellant_mass_fraction,
    station_keeping_m_s_per_year,
)
from spectre.domain.pol_assessment import (
    _ASSUMED_ISP_S,
    _classify,
    _escalation_text,
    assess_pattern_of_life,
)
from tests.unit.test_dv_estimation import TestTwoTierReporting, _base, _coast, _rec


def _geo_ceiling() -> float:
    return per_event_station_keeping_m_s("GEO")[0]


def _leo_ceiling() -> float:
    return per_event_station_keeping_m_s("LEO")[0]


# ── The failure this module exists to fix ────────────────────────────────────

class TestTheAssessmentsOwnEventsAreNotCalledRoutine:
    """Four named counterspace events classified as station-keeping.

    ``_SK_DV_LIMIT`` applied Table 3's ANNUAL budgets as PER-EVENT limits: its
    GEO value was 50 m/s against a real single north-south burn of about
    1.8 m/s, and its HEO value matched Table 3's 50 to 70 m/s per YEAR exactly.
    """

    #: (description, ΔV m/s, dominant channel, regime, altitude after, Δ alt)
    _EVENTS = [
        ("GEO graveyard raise, 300 km (Table 3)",        9.0, "along_track", "GEO", 36486.0, 300.0),
        ("Luch/Olymp-K 1, raise above GEO (observed)",  15.0, "along_track", "GEO", 36200.0, 420.0),
        ("Luch/Olymp-K 2, 62° relocation (observed)",   11.0, "along_track", "GEO", 35790.0,  78.0),
        ("GEO relocation, 180° in 30 days (Table 4)",   34.0, "along_track", "GEO", 35800.0, 469.0),
        ("SJ-21 dock and tow (observed)",               60.0, "along_track", "GEO", 35790.0, 800.0),
        ("SJ-21 tow, round trip (observed)",           120.0, "along_track", "GEO", 35790.0,  10.0),
        ("Rapid GEO relocation, 90° in 3 days",        170.0, "along_track", "GEO", 35800.0, 2342.0),
    ]

    # Taken as one parameter rather than six because six trips the project's
    # argument-count rules (PLR0913 and PLR0917) on new code. The cases, the
    # order they run in and what each asserts are unchanged, and ids= keeps
    # each case named by its label.
    @pytest.mark.parametrize("event", _EVENTS, ids=[case[0] for case in _EVENTS])
    def test_a_named_counterspace_event_is_never_routine(
        self, event: tuple[str, float, str, str, float, float],
    ) -> None:
        label, dv, channel, regime, alt, d_alt = event
        classification, _, _ = _classify(dv, channel, regime, _geo_ceiling(), alt, d_alt)
        assert classification != "station keeping", (
            f"{label} at {dv} m/s classified as routine station-keeping"
        )

    def test_a_raise_out_of_the_protected_region_is_disposal(self) -> None:
        """Disposal and the start of a drift are identical in the elements.

        Only the altitude it ends at separates them, so that is what decides.
        """
        above, _, _ = _classify(9.0, "along_track", "GEO", _geo_ceiling(), 36486.0, 300.0)
        within, _, _ = _classify(9.0, "along_track", "GEO", _geo_ceiling(), 35790.0, 78.0)
        assert above == "graveyard disposal"
        assert within == "relocation"

    def test_routine_burns_are_still_called_routine(self) -> None:
        """The correction must not swing the other way."""
        for dv, channel, regime, ceiling in (
            (1.0, "along_track", "LEO", _leo_ceiling()),   # collision avoidance
            (1.8, "cross_track", "GEO", _geo_ceiling()),   # GEO north-south, one burn
        ):
            label, _, _ = _classify(dv, channel, regime, ceiling)
            assert label == "station keeping"

    def test_an_inspector_campaign_is_not_scored_against_the_permissive_band(self) -> None:
        """A mixed-channel manoeuvre is proximity work, not a rendezvous.

        Cosmos 2576's campaign against USA 314 cost 25 to 30 m/s across
        altitude and inclination together. Against the LEO rendezvous band it
        reads BENIGN; against the proximity band it belongs in, ANNOYANCE.
        """
        _, _, kind = _classify(28.0, "mixed", "LEO", _leo_ceiling())
        assert kind is ManoeuvreKind.PROXIMITY
        assert classify_posture(28.0, "LEO", kind).posture_label == "ANNOYANCE"


# ── The per-event ceiling, derived rather than asserted ──────────────────────

class TestStationKeepingCeiling:
    def test_a_geo_burn_ceiling_is_about_two_metres_per_second(self) -> None:
        """Not fifty. Fifty is Table 3's figure for a whole YEAR."""
        ceiling, basis = per_event_station_keeping_m_s("GEO")
        assert 1.5 < ceiling < 2.5
        assert "per year" in basis and "cadence" in basis

    def test_the_annual_budget_is_the_cited_one(self) -> None:
        assert station_keeping_m_s_per_year("GEO") == pytest.approx(48.0)
        assert station_keeping_m_s_per_year("LEO") == pytest.approx(25.0)
        assert station_keeping_m_s_per_year("MEO") == pytest.approx(1.0)

    def test_an_objects_own_cadence_is_used_where_there_is_one(self) -> None:
        """An object manoeuvring monthly spends its year in twelve pieces."""
        fortnightly, _ = per_event_station_keeping_m_s("GEO", 14.0)
        monthly, _ = per_event_station_keeping_m_s("GEO", 28.0)
        assert monthly == pytest.approx(fortnightly * 2.0, rel=0.01)

    def test_an_unknown_regime_does_not_invent_a_ceiling(self) -> None:
        ceiling, basis = per_event_station_keeping_m_s("CISLUNAR")
        assert ceiling == pytest.approx(0.5)
        assert "No published" in basis


# ── Propellant ───────────────────────────────────────────────────────────────

class TestPropellant:
    @staticmethod
    def _assessed(regime_records: list, reset: datetime | None = None):
        pol = analyse_pattern_of_life(regime_records, satno=1, name="T")
        return assess_pattern_of_life(pol, reset)

    def test_the_figure_is_the_tank_not_the_whole_spacecraft(self) -> None:
        """The label said propellant; the number was total mass.

        They differ by the propellant mass fraction, which is a factor of ten
        for a LEO smallsat.
        """
        a = self._assessed(TestTwoTierReporting._catalogue())
        p = a.propellant
        assert p.propellant_used_pct > p.total_mass_fraction_pct
        assert p.propellant_used_pct == pytest.approx(
            p.total_mass_fraction_pct / p.propellant_fraction, rel=0.01
        )

    def test_the_platform_is_not_a_three_tonne_geo_bus_for_every_object(self) -> None:
        """One 900 kg assumption was applied to every object in every regime."""
        assert platform_class_for_regime("LEO").name != platform_class_for_regime("GEO").name
        assert "smallsat" in platform_class_for_regime("LEO").name.lower()

    def test_specific_impulse_follows_the_platform(self) -> None:
        """An electric platform expends about a tenth the propellant mass."""
        assert _ASSUMED_ISP_S["LEO"] > _ASSUMED_ISP_S["GEO"] * 4
        assert 300.0 <= _ASSUMED_ISP_S["GEO"] <= 325.0   # Table 1 bipropellant

    def test_there_is_no_constant_dressed_as_a_remaining_budget(self) -> None:
        """The old dv_remaining divided by prop + prop and returned 1,495 m/s
        for every object in every regime."""
        leo = self._assessed(TestTwoTierReporting._catalogue())
        assert leo.propellant.discretionary_remaining_m_s != pytest.approx(1495.0, abs=5.0)
        assert leo.propellant.discretionary_max_m_s == pytest.approx(
            platform_class_for_regime("LEO").discretionary_max_m_s
        )

    def test_a_quiet_object_has_not_spent_its_tank(self) -> None:
        recs, tle = [], _base()
        for _ in range(200):
            recs.append(_rec(tle, source="18SDS"))
            tle = _coast(tle, 0.25)
        a = self._assessed(recs)
        assert a.propellant.propellant_used_pct < 0.1
        assert a.propellant.discretionary_remaining_m_s > 0

    def test_a_spend_beyond_the_lifetime_budget_is_flagged_not_reported(self) -> None:
        """36,686 m/s on a LEO smallsat is not a propellant reading."""
        from spectre.domain.pol_assessment import _assess_propellant

        p = _assess_propellant("LEO", 36686.0, 36686.0, 385.0, None)
        assert p.exceeds_lifetime_budget
        assert "lifetime budget" in p.narrative
        assert p.lifetime_budget_m_s == platform_total_budget_m_s("LEO")

    def test_the_propellant_fraction_matches_table_two(self) -> None:
        assert propellant_mass_fraction("LEO") == pytest.approx(0.10)   # 5 to 15 per cent
        assert propellant_mass_fraction("MEO") == pytest.approx(0.20)   # xenon 15 to 25


# ── Refuelling as a capability multiplier ────────────────────────────────────

class TestRefuelling:
    def test_a_reserve_reset_counts_only_the_spend_since(self) -> None:
        """Cumulative ΔV is monotonic, so without this a refuelled object reads
        as progressively more exhausted exactly as it becomes more capable."""
        records = TestTwoTierReporting._catalogue()
        pol = analyse_pattern_of_life(records, satno=1, name="T")
        assert pol.manoeuvres, "fixture must produce a confirmed manoeuvre"

        before = assess_pattern_of_life(pol)
        after = assess_pattern_of_life(
            pol, pol.manoeuvres[0].epoch + timedelta(days=1),
        )
        assert after.propellant.spent_since_reset_m_s < before.propellant.spent_since_reset_m_s
        assert after.propellant.spent_m_s == pytest.approx(before.propellant.spent_m_s)
        assert after.propellant.reserve_reset is not None

    def test_the_transferred_quantity_is_not_invented(self) -> None:
        """The one reported refuelling mass is unconfirmed secondary reporting."""
        records = TestTwoTierReporting._catalogue()
        pol = analyse_pattern_of_life(records, satno=1, name="T")
        a = assess_pattern_of_life(pol, datetime(2025, 7, 1, tzinfo=UTC))
        joined = " ".join(a.propellant.caveats)
        assert "not modelled" in joined
        assert "unconfirmed" in joined


# ── Escalation on the assessment's watchlist ─────────────────────────────────

class TestOnStationEscalation:
    def test_the_threshold_is_the_assessments_own(self) -> None:
        assert pytest.approx(500.0) == ON_STATION_ANOMALY_M_S

    def test_a_cross_track_burn_leads_with_the_plane_change_explanation(self) -> None:
        text = _escalation_text(620.0, "cross_track", "GEO")
        assert "plane change" in text.split("most consistent with")[1][:80]

    def test_an_along_track_burn_leads_with_the_tug_explanation(self) -> None:
        text = _escalation_text(620.0, "along_track", "GEO")
        assert "transfer vehicle" in text.split("most consistent with")[1][:80]

    def test_all_four_explanations_are_offered(self) -> None:
        text = _escalation_text(620.0, "cross_track", "GEO")
        for fragment in ("plane change", "cislunar", "transfer vehicle", "efuelling"):
            assert fragment in text


# ── Rate, not reserve ────────────────────────────────────────────────────────

class TestRateNotReserve:
    def test_an_all_electric_bus_needs_weeks_for_a_rapid_relocation(self) -> None:
        """The assessment's own worked case: large ΔV at millinewton thrust."""
        bus = next(p for p in PLATFORM_CLASSES if "All-electric GEO" in p.name)
        assert bus.minimum_burn_hours(170.0) / 24.0 == pytest.approx(21.9, abs=1.0)
        assert bus.minimum_burn_hours(500.0) / 24.0 == pytest.approx(64.0, abs=2.0)

    def test_the_burn_time_uses_the_objects_own_platform(self) -> None:
        """Not the fastest platform that could afford it. A LEO smallsat is not
        an orbital transfer vehicle."""
        pol = analyse_pattern_of_life(TestTwoTierReporting._catalogue(), satno=1, name="T")
        view = assess_pattern_of_life(pol).manoeuvres[0]
        assert view.burn_platform == platform_class_for_regime("LEO").name
        assert view.fastest_burn_hours is not None
        assert view.burn_hours > view.fastest_burn_hours


# ── Detection limits ─────────────────────────────────────────────────────────

class TestDetectionLimits:
    def test_the_panel_names_what_it_cannot_see(self) -> None:
        pol = analyse_pattern_of_life(TestTwoTierReporting._catalogue(), satno=1, name="T")
        limits = assess_pattern_of_life(pol).detection
        assert limits is not None
        assert limits.floor_m_s > 0
        assert "not a passive object" in limits.narrative or limits.sees_routine_station_keeping

    def test_a_high_floor_says_collision_avoidance_is_invisible(self) -> None:
        from spectre.astro.dv_estimation import calibrate_noise
        from spectre.domain.pol_assessment import _assess_detection

        noisy = calibrate_noise([0.004 + (i % 3) * 0.0002 for i in range(500)])
        limits = _assess_detection(noisy, "LEO")
        assert limits is not None
        assert any("Collision avoidance" in label for label, _ in limits.invisible)
        assert "355,000" in limits.narrative

    def test_a_quiet_result_is_never_reported_as_passive(self) -> None:
        """The old narrative asserted "Object appears passive"."""
        recs, tle = [], _base()
        for _ in range(200):
            recs.append(_rec(tle, source="18SDS"))
            tle = _coast(tle, 0.25)
        pol = analyse_pattern_of_life(recs, satno=1, name="QUIET")
        narrative = assess_pattern_of_life(pol).intel.anomaly_narrative
        assert "passive" not in narrative.lower()
        assert "what can be seen" in narrative


# ── Anomaly scoring against the object's own regime ──────────────────────────

class TestAnomalyScoring:
    def test_the_budget_term_is_measured_per_regime(self) -> None:
        """200 m/s/yr was the full-score point for every regime, so a
        navigation satellite burning twice its entire annual budget scored one
        point out of a hundred."""
        # Two burns: the anomaly score needs more than one to say anything.
        pol = analyse_pattern_of_life(
            TestTwoTierReporting._catalogue(burn_at=(100, 200)), satno=1, name="T",
        )
        anomaly = assess_pattern_of_life(pol).anomaly
        assert anomaly is not None
        assert "routine" in anomaly.basis
        assert str(int(station_keeping_m_s_per_year("LEO"))) in anomaly.basis

    def test_an_unscoreable_regime_is_not_scored_rather_than_guessed(self) -> None:
        from spectre.domain.pol_assessment import _assess_propellant

        p = _assess_propellant("OTHER", 100.0, 100.0, 365.0, None)
        assert p.routine_annual_m_s is None
        assert p.rate_multiple is None


# ── One set of numbers ───────────────────────────────────────────────────────

class TestThereIsOnlyOneSetOfNumbers:
    """Two definitions of GEO station-keeping that disagree is worse than one
    that is wrong, because only one of them ever gets updated."""

    def test_the_astro_layer_holds_no_calibration_constants(self) -> None:
        import spectre.astro.pattern_of_life as pol_module

        for gone in ("_SK_DV_LIMIT", "_GEO_SK_BASELINE", "_ISP_MONO", "_ISP_BI",
                     "_compute_propellant_budget", "_compute_anomaly_score",
                     "_intel_assessment", "_classify_manoeuvre"):
            assert not hasattr(pol_module, gone), (
                f"{gone} is back in the astro layer. Calibrated per-regime "
                "figures belong in spectre.domain.manoeuvre_calibration, where "
                "they are cited, and in m/s."
            )

    def test_the_astro_layer_still_works_in_kilometres_per_second(self) -> None:
        """Moving the interpretation out must not drag the units with it."""
        pol = analyse_pattern_of_life(TestTwoTierReporting._catalogue(), satno=1, name="T")
        assert pol.manoeuvres
        # A 13.7 m/s burn is 0.0137 in the astro layer.
        assert all(m.delta_v_km_s < 1.0 for m in pol.manoeuvres)

    def test_the_assessment_converts_exactly_once(self) -> None:
        pol = analyse_pattern_of_life(TestTwoTierReporting._catalogue(), satno=1, name="T")
        a = assess_pattern_of_life(pol)
        for view in a.manoeuvres:
            assert view.delta_v_m_s == pytest.approx(view.manoeuvre.delta_v_km_s * 1000.0)


# ── The recommendation that is to change nothing ─────────────────────────────

class TestTheSweepBudgetIsNotAnAlertThreshold:
    """The assessment says "set the GEO alert threshold at about 0.1 km/s, not
    0.5 km/s". DEFAULT_SWEEP_BUDGET_M_S is the nearest 500 in the codebase and
    is NOT that threshold: it is the ΔV an interceptor is assumed able to spend.

    Lowering it would shrink the set of intercepts the sweep considers, which
    is the opposite of what the recommendation intends. The watch floor it is
    actually about is already at 100 m/s in the GEO posture bands.

    This test exists so nobody "fixes" it later by matching on the number.
    """

    def test_the_sweep_budget_stays_at_five_hundred(self) -> None:
        assert pytest.approx(500.0) == DEFAULT_SWEEP_BUDGET_M_S, (
            "DEFAULT_SWEEP_BUDGET_M_S is a sweep BUDGET, not an alert "
            "THRESHOLD. Lowering it shrinks the intercept set rather than "
            "tightening the watch floor. See the GEO posture bands for the "
            "threshold the assessment is actually about."
        )

    def test_the_geo_watch_floor_is_already_at_one_hundred(self) -> None:
        """Where the recommendation does apply, it is already satisfied."""
        band = classify_posture(100.0, "GEO", ManoeuvreKind.PHASING)
        assert band.annoyance_max_m_s == pytest.approx(100.0)
        assert classify_posture(101.0, "GEO", ManoeuvreKind.PHASING).posture_label == "AGGRESSIVE"

    def test_a_real_counterspace_event_sits_below_five_hundred(self) -> None:
        """Which is the assessment's point: a 500 m/s threshold would miss it."""
        largest_on_record = 170.0      # rapid GEO relocation, 90° in 3 days
        assert largest_on_record < DEFAULT_SWEEP_BUDGET_M_S
        assert classify_posture(
            largest_on_record, "GEO", ManoeuvreKind.PHASING,
        ).posture_label == "AGGRESSIVE"


# ── Sanity against the assessment's own worked values ────────────────────────

class TestThePhysicsMatchesTheAssessment:
    """The estimator was built independently of these figures and reproduces
    them. Pinning that so a change to either side is visible."""

    @pytest.mark.parametrize(
        ("label", "cited", "computed"),
        [
            ("GEO plane change per degree", 54.0,
             lambda: 2 * math.sqrt(398600.4418 / 42164.0) * math.sin(math.radians(1) / 2) * 1000),
            ("LEO plane change per degree", 133.0,
             lambda: 2 * math.sqrt(398600.4418 / 6878.137) * math.sin(math.radians(1) / 2) * 1000),
            ("GEO graveyard raise, 300 km", 11.0,
             lambda: math.sqrt(398600.4418 / 42164.0 ** 3) * 300 / 2 * 1000),
            ("LEO 500 to 600 km", 55.0,
             lambda: math.sqrt(398600.4418 / 6928.137 ** 3) * 100 / 2 * 1000),
        ],
    )
    def test_a_cited_worked_value_is_reproduced(
        self, label: str, cited: float, computed: object,
    ) -> None:
        assert computed() == pytest.approx(cited, rel=0.03), label


# ── Defects found by adversarial review after 0.5.20 shipped ────────────────

class TestReviewFindings:
    """Each of these was reported by a reviewer, verified by measurement, and
    fixed. One was reported backwards and is pinned the right way round."""

    def test_a_single_large_burn_is_not_minimal_risk(self) -> None:
        """The anomaly score needs two manoeuvres, so one 450 m/s AGGRESSIVE
        relocation used to fall through to MINIMAL because it happened once."""
        pol = analyse_pattern_of_life(
            TestTwoTierReporting._catalogue(n=300, burn_at=150, d_alt_km=900.0),
            satno=1, name="ONE BIG BURN",
        )
        a = assess_pattern_of_life(pol)
        assert len(a.manoeuvres) == 1
        assert a.manoeuvres[0].posture_label == "AGGRESSIVE"
        assert a.anomaly is None, "one manoeuvre cannot produce an anomaly score"
        assert a.intel.risk_level == "HIGH", (
            "the worst observed posture is a floor under the risk level"
        )

    def test_a_single_small_burn_stays_minimal(self) -> None:
        """The floor must not become a ratchet."""
        pol = analyse_pattern_of_life(
            TestTwoTierReporting._catalogue(n=300, burn_at=150, d_alt_km=25.0),
            satno=1, name="ONE SMALL BURN",
        )
        a = assess_pattern_of_life(pol)
        assert a.manoeuvres[0].posture_label == "BENIGN"
        assert a.intel.risk_level == "MINIMAL"

    def test_a_total_standing_in_for_a_discretionary_figure_says_so(self) -> None:
        """Table 2 publishes a discretionary figure for two of six classes.

        Where it does not, the total stands in, and an unflagged total
        overstates what an object can spend manoeuvring against someone: a LEO
        smallsat's 2,500 m/s is mostly drag make-up, collision avoidance and
        deorbit.
        """
        assert platform_class_for_regime("GEO").discretionary_is_published
        assert not platform_class_for_regime("LEO").discretionary_is_published

        pol = analyse_pattern_of_life(TestTwoTierReporting._catalogue(), satno=1, name="T")
        caveats = " ".join(assess_pattern_of_life(pol).propellant.caveats)
        assert "TOTAL lifetime budget standing in" in caveats

    def test_a_campaign_does_not_collapse_into_one_burn(self) -> None:
        """Two detections can only be one burn if they came from DIFFERENT
        sources. Within a source each record is differenced against the
        previous record from that same source, so one burn gives exactly one
        detection and two detections are two burns.

        The previous clustering went on time alone and chained off the most
        recently added member, so a run of real burns a fraction of a window
        apart collapsed into a single event. Measured: six 10 m/s burns 0.9
        days apart in a one-fit-per-day catalogue produced five correct
        detections totalling 62.2 m/s and the merge reduced them to two
        totalling 31.8 m/s, in a catalogue with one provider and no duplicates
        in it at all.
        """
        from datetime import timedelta

        from spectre.astro.pattern_of_life import _merge_duplicate_detections

        class _Rec:
            def __init__(self, source: str) -> None:
                self.source = source

        class _Stub:
            def __init__(self, day: float, source: str = "18SDS") -> None:
                self.burn_epoch = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
                self.confidence = "HIGH"
                self.gap_days = 0.1
                self.tle_after = _Rec(source)
                self.corroborated_by: tuple[str, ...] = ()

        chain = [_Stub(d * 0.9) for d in range(10)]
        kept, merged = _merge_duplicate_detections(chain, 1.0)
        assert len(kept) == 10, "one provider cannot produce a duplicate"
        assert merged == 0

    def test_one_burn_seen_by_two_providers_stays_one_burn(self) -> None:
        from datetime import timedelta

        from spectre.astro.pattern_of_life import _merge_duplicate_detections

        class _Rec:
            def __init__(self, source: str) -> None:
                self.source = source

        class _Stub:
            def __init__(self, day: float, source: str) -> None:
                self.burn_epoch = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
                self.confidence = "HIGH"
                self.gap_days = 0.1
                self.tle_after = _Rec(source)
                self.corroborated_by: tuple[str, ...] = ()

        kept, merged = _merge_duplicate_detections(
            [_Stub(0.0, "18SDS"), _Stub(0.2, "COMSPOC")], 1.0,
        )
        assert len(kept) == 1
        assert merged == 1
        assert kept[0].corroborated_by == ("COMSPOC",), (
            "who else saw the burn is evidence and must survive the merge"
        )

    def test_two_providers_reporting_two_real_burns_keep_both(self) -> None:
        from datetime import timedelta

        from spectre.astro.pattern_of_life import _merge_duplicate_detections

        class _Rec:
            def __init__(self, source: str) -> None:
                self.source = source

        class _Stub:
            def __init__(self, day: float, source: str) -> None:
                self.burn_epoch = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
                self.confidence = "HIGH"
                self.gap_days = 0.1
                self.tle_after = _Rec(source)
                self.corroborated_by: tuple[str, ...] = ()

        kept, merged = _merge_duplicate_detections(
            [_Stub(0.0, "18SDS"), _Stub(0.1, "COMSPOC"),
             _Stub(0.9, "18SDS"), _Stub(1.0, "COMSPOC")], 0.5,
        )
        assert len(kept) == 2
        assert merged == 2

    def test_the_capability_signal_is_no_longer_pinned(self) -> None:
        """Before the propellant rebuild it read HIGH for every object, so
        capability could never weaken a verdict."""
        from spectre.domain.threat_assessment import CapabilityEvidence

        platform = platform_class_for_regime("GEO")
        bands = [
            CapabilityEvidence(
                discretionary_remaining_m_s=max(0.0, platform.discretionary_max_m_s - spent),
                discretionary_max_m_s=platform.discretionary_max_m_s,
            ).band()
            for spent in (0.0, 150.0, 200.0)
        ]
        assert len(set(bands)) > 1, "the signal must vary with what is left"
        assert bands[0] > bands[-1]

    def test_the_intercept_budget_label_names_its_own_denominator(self) -> None:
        """The percentage moved to a 500 m/s budget in 0.5.15; the template's
        hardcoded "3.0 m/s" did not, leaving the label 167x out."""
        template = (
            pathlib.Path("spectre/web/templates/partials/intercept_result.html")
            .read_text(encoding="utf-8")
        )
        assert "of 3.0 m/s" not in template
        assert "dv_budget_m_s" in template
