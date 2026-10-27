"""The calibration that makes a delta-v figure mean something.

The sweep banded every manoeuvre on four global constants, the lowest of which
was 200 m/s. Every counterspace manoeuvre on open record sits below that, so
the band returned CRITICAL for a routine commercial repositioning and CRITICAL
for a hostile rapid closure. A measurement that returns the same answer for
everything is not a measurement, and the first class below asserts exactly
that: the observed cases must come out DIFFERENT from one another.

Reference figures throughout are from "Satellite Manoeuvre Delta-v:
Feasibility Above 0.5 km/s and Budgets by Regime" (Bluestaq Limited Space
Watch, v1.0, 13 October 2026).
"""

from __future__ import annotations

import pytest

from spectre.domain.manoeuvre_calibration import (
    DEFAULT_SWEEP_BUDGET_M_S,
    PLATFORM_CLASSES,
    ManoeuvreKind,
    Posture,
    classify_posture,
    from_km_s,
    kind_for_method,
    station_keeping_m_s_per_year,
)

# (description, delta-v m/s, regime, kind, expected posture)
# Every row is an event in the assessment, not an invented number.
_OBSERVED_CASES = [
    ("Luch/Olymp-K 2 moved 62 deg in 30 days",
     11.0, "GEO", ManoeuvreKind.PHASING, Posture.BENIGN),
    ("Luch/Olymp-K 1 rose >400 km above the GEO protected region",
     15.0, "GEO", ManoeuvreKind.ALTITUDE_CHANGE, Posture.BENIGN),
    ("A 180 deg GEO relocation taken slowly, over 30 days",
     34.0, "GEO", ManoeuvreKind.PHASING, Posture.ANNOYANCE),
    ("SJ-21 raised Beidou-2 G2 into the graveyard",
     60.0, "GEO", ManoeuvreKind.PROXIMITY, Posture.ANNOYANCE),
    ("The same SJ-21 tow costed as a round trip",
     120.0, "GEO", ManoeuvreKind.PROXIMITY, Posture.AGGRESSIVE),
    ("A 90 deg GEO relocation flown in 3 days",
     170.0, "GEO", ManoeuvreKind.PHASING, Posture.AGGRESSIVE),
    ("Cosmos 2576 shadowing USA 314",
     28.0, "LEO", ManoeuvreKind.PROXIMITY, Posture.ANNOYANCE),
    ("A 180 deg LEO phasing flown in about one day",
     500.0, "LEO", ManoeuvreKind.PHASING, Posture.AGGRESSIVE),
    ("A 9.3 deg plane change at GEO",
     500.0, "GEO", ManoeuvreKind.PLANE_CHANGE, Posture.AGGRESSIVE),
]


class TestTheBandActuallyDiscriminates:
    """The defect being fixed, asserted directly."""

    def test_the_observed_cases_do_not_all_score_the_same(self) -> None:
        postures = {
            classify_posture(dv, regime, kind).posture
            for _, dv, regime, kind in [(c[0], c[1], c[2], c[3]) for c in _OBSERVED_CASES]
        }
        assert len(postures) >= 3, (
            "the whole point of the calibration is to separate these cases; "
            f"it collapsed them into {postures}"
        )

    def test_the_old_global_thresholds_would_have_collapsed_them(self) -> None:
        """Proof the old banding was saturated, kept as the reason this exists."""
        old_critical_threshold_m_s = 200.0
        collapsed = [
            desc for desc, dv, _, _, _ in _OBSERVED_CASES
            if dv < old_critical_threshold_m_s
        ]
        assert len(collapsed) >= 6, (
            "under the old 200 m/s CRITICAL threshold these all scored "
            f"identically: {collapsed}"
        )

    @pytest.mark.parametrize(
        ("description", "delta_v", "regime", "kind", "expected"), _OBSERVED_CASES,
    )
    def test_each_observed_case_lands_where_an_analyst_would_put_it(
        self, description: str, delta_v: float, regime: str,
        kind: ManoeuvreKind, expected: Posture,
    ) -> None:
        result = classify_posture(delta_v, regime, kind)
        assert result.posture is expected, (
            f"{description} ({delta_v:.0f} m/s) scored {result.posture_label}, "
            f"expected {expected.label}. {result.rationale}"
        )


class TestTheSameNumberMeansDifferentThings:
    """One global threshold cannot be right in two regimes."""

    def test_fifty_m_s_is_routine_in_geo_and_significant_in_meo(self) -> None:
        geo = classify_posture(50.0, "GEO", ManoeuvreKind.PLANE_CHANGE)
        meo = classify_posture(50.0, "MEO", ManoeuvreKind.PLANE_CHANGE)
        assert geo.posture is Posture.BENIGN, (
            "50 m/s is one year of north-south station-keeping at GEO"
        )
        assert meo.posture is Posture.ANNOYANCE
        assert geo.station_keeping_years is not None
        assert meo.station_keeping_years is not None
        assert meo.station_keeping_years > geo.station_keeping_years * 10, (
            "MEO station-keeping is about 1 m/s/yr against GEO's 48"
        )

    def test_proximity_and_plane_change_are_banded_apart_in_the_same_regime(self) -> None:
        """45 m/s is a routine year of N-S keeping, and a deliberate tow."""
        dv = 45.0
        prox = classify_posture(dv, "GEO", ManoeuvreKind.PROXIMITY)
        plane = classify_posture(dv, "GEO", ManoeuvreKind.PLANE_CHANGE)
        assert plane.posture is Posture.BENIGN, (
            "45 m/s of plane change is inside the 43-50 m/s annual N-S "
            "station-keeping budget, so it is indistinguishable from routine"
        )
        assert prox.posture is Posture.ANNOYANCE, (
            "the same 45 m/s spent closing on another object is most of an "
            "observed GEO proximity campaign"
        )


class TestTheRateConstraintTheAppNeverHad:
    """Reserve is not the same as the ability to spend it in time."""

    def test_an_all_electric_bus_cannot_deliver_500_m_s_in_six_hours(self) -> None:
        bus = next(p for p in PLATFORM_CLASSES if "all-electric" in p.name.lower())
        assert bus.discretionary_max_m_s >= 500.0, "it can afford it"
        assert not bus.can_deliver_within(500.0, hours_available=6.0), (
            "affording a burn is not the same as being able to deliver it; at "
            "millinewton thrust this takes weeks"
        )
        days = bus.minimum_burn_hours(500.0) / 24.0
        assert 50.0 < days < 80.0, f"expected about 64 days, got {days:.1f}"

    def test_a_chemical_platform_delivers_the_same_burn_in_days_not_months(self) -> None:
        chem = next(p for p in PLATFORM_CLASSES if p.name.startswith("Chemical GEO"))
        assert chem.minimum_burn_hours(150.0) < 24.0

    def test_affordability_still_binds(self) -> None:
        chem = next(p for p in PLATFORM_CLASSES if p.name.startswith("Chemical GEO"))
        assert not chem.can_deliver_within(500.0, hours_available=1e9), (
            "a chemical comsat on station holds 50-200 m/s discretionary, so "
            "500 m/s is unaffordable however long it is given"
        )


class TestBeyondAnyFlownPlatform:
    def test_a_burn_no_flown_platform_could_make_is_called_that(self) -> None:
        result = classify_posture(3500.0, "GEO", ManoeuvreKind.RENDEZVOUS)
        assert result.posture is Posture.BEYOND_PLATFORM
        assert "refuel" in result.rationale or "transfer vehicle" in result.rationale

    def test_the_heo_to_leo_case_is_aggressive_not_impossible(self) -> None:
        """2,500 m/s is within a hybrid servicer's reserve, and X-37B flew it."""
        result = classify_posture(2500.0, "HEO", ManoeuvreKind.ALTITUDE_CHANGE)
        assert result.posture is Posture.AGGRESSIVE


class TestConversionHappensExactlyOnce:
    def test_from_km_s_is_the_conversion(self) -> None:
        assert from_km_s(0.182) == pytest.approx(182.0)
        assert from_km_s(3.0) == pytest.approx(3000.0)

    def test_the_default_budget_matches_the_assessment_anomaly_threshold(self) -> None:
        """The assessment calls 500 m/s by an on-station object a strong flag."""
        assert DEFAULT_SWEEP_BUDGET_M_S == 500.0
        assert DEFAULT_SWEEP_BUDGET_M_S < 3000.0, (
            "the old 3,000 m/s budget exceeded every flown platform's reserve, "
            "so the sweep accepted intercepts nothing could fly"
        )


class TestUnknownInputsFailWide:
    """An unrecognised input must never be scored as MORE alarming."""

    def test_an_unknown_method_gets_the_most_permissive_kind(self) -> None:
        assert kind_for_method("some_new_solver") is ManoeuvreKind.UNCLASSIFIED

    def test_an_unknown_regime_uses_the_widest_band(self) -> None:
        known = classify_posture(150.0, "GEO", ManoeuvreKind.PHASING)
        unknown = classify_posture(150.0, "CISLUNAR", ManoeuvreKind.PHASING)
        assert known.posture is Posture.AGGRESSIVE, "150 m/s is harsh for GEO"
        assert unknown.posture is Posture.ANNOYANCE, (
            "an unclassified regime must not be scored as MORE alarming than "
            "the evidence supports; it falls back to the widest published band"
        )
        assert "not recognised" in unknown.basis

    def test_every_sweep_method_maps_to_a_kind(self) -> None:
        sweep_methods = [
            "hohmann", "lambert", "bielliptic", "phasing",
            "plane_change", "min_time", "vbar_hop", "hbar_hop",
        ]
        for method in sweep_methods:
            assert isinstance(kind_for_method(method), ManoeuvreKind)
        assert kind_for_method("hohmann") is ManoeuvreKind.ALTITUDE_CHANGE
        assert kind_for_method("vbar_hop") is ManoeuvreKind.PROXIMITY

    def test_station_keeping_is_none_where_unpublished(self) -> None:
        assert station_keeping_m_s_per_year("GEO") == 48.0
        assert station_keeping_m_s_per_year("DEEP") is None


class TestTheRationaleIsReadable:
    def test_it_names_the_number_the_kind_the_regime_and_the_posture(self) -> None:
        r = classify_posture(170.0, "GEO", ManoeuvreKind.PHASING).rationale
        assert "170 m/s" in r
        assert "GEO" in r
        assert "AGGRESSIVE" in r
        assert "3.5 years" in r, "the station-keeping multiple is the useful bit"

    def test_every_band_carries_its_provenance(self) -> None:
        for regime in ("GEO", "LEO", "MEO", "HEO", "GTO"):
            for kind in ManoeuvreKind:
                basis = classify_posture(50.0, regime, kind).basis
                assert len(basis) > 40, f"{regime}/{kind} has no cited basis"
                assert "Table" in basis, f"{regime}/{kind} cites no table"
                assert not basis.startswith("As above"), (
                    f"{regime}/{kind} says 'As above', which refers to nothing "
                    "when the operator reads this band on its own"
                )
