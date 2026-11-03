"""Threat Understanding, SPC-165: the held signals become evidence items.

Each adapter reads what SPECTRE already holds (the intel record, the GCAT
entry, the element-set history and its Pattern of Life reading) and builds
the items of sections 5.1 to 5.3 of docs/threat_confidence_concept.md. The
worked example of section 4.12, rows 1 to 6, is rebuilt here from these
adapters, not from hand-built items, and must give the concept's figures.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.manoeuvre_calibration import Posture
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import (
    BurnSignal,
    Dimension,
    EvidenceItem,
    HeldBurn,
    HistorySignals,
    Situation,
    Status,
    Understanding,
)

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)
_SIX_HOURS = timedelta(hours=6)
#: The intercept the sweep found costs 9 m/s (section 4.12).
_ACCESS_DV = 9.0


def _signals(**kw: Any) -> HistorySignals:
    """A 400-day 18 SDS history through UDL, newest set 6 hours old, reserve 72 of 120 m/s."""
    args: dict[str, Any] = {
        "provider": "18SDS", "newest_at": _NOW - _SIX_HOURS, "span_days": 400.0,
        "burns": (BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS"),),
        "reserve_remaining_m_s": 72.0, "reserve_max_m_s": 120.0,
        "detection_floor_m_s": 0.4, "sees_routine_station_keeping": True,
    }
    args.update(kw)
    return HistorySignals(**args)


def _items(signals: HistorySignals, custody: Custody = Custody.HELD, dv: float = _ACCESS_DV,
           grades: dict[str, str] | None = None) -> tuple[EvidenceItem, ...]:
    if grades is None:
        return tu.history_items(signals, access_delta_v_m_s=dv, custody=custody)
    return tu.history_items(signals, access_delta_v_m_s=dv, custody=custody, grades=grades)


def _base(**kw: Any) -> Situation:
    args: dict[str, Any] = {"now": _NOW, "access": Band.CRITICAL, "legacy": Band.CRITICAL, "regime": "GEO",
                            "data_mode": "REAL", "custody": Custody.HELD, "history_truncated": False}
    args.update(kw)
    return Situation(**args)


def _one(items: tuple[EvidenceItem, ...], dimension: Dimension) -> EvidenceItem:
    (found,) = [i for i in items if i.dimension is dimension]
    return found


class TestTheIntelRecord:
    def test_an_undated_single_source_record_is_c3_identity_with_no_reading(self) -> None:
        record = {"name": "RED-GEO-1", "assessed_threat": "Inspector", "threat_level": "CRITICAL",
                  "status": "Operational", "source": "CSIS 2025"}
        identity = _one(tu.intel_items(record, "90001"), Dimension.IDENTITY)
        assert (identity.grade, identity.extraction, identity.basis, identity.observed_at) == (
            "C3", tu.ASSESSED_LABEL_EXTRACTION, Basis.LOOKUP, None)
        assert identity.derived_from == "intel-record:90001"
        assert identity.note == "undated, single open source"
        # A prior raises the floor only from a dated, sourced record.
        assert identity.floor_to is None
        assert tu.reliability(identity, _NOW) == pytest.approx(0.09)

    @pytest.mark.parametrize("level", ["CRITICAL", "HIGH"])
    def test_a_dated_sourced_record_assessed_high_or_critical_raises_the_floor_to_medium_and_no_higher(
            self, level: str) -> None:
        record = {"name": "RED-GEO-1", "threat_level": level, "source": "CSIS 2025",
                  "assessed_at": "2026-09-01"}
        identity = _one(tu.intel_items(record, "90001"), Dimension.IDENTITY)
        assert (identity.grade, identity.floor_to, identity.note) == ("C2", Band.MEDIUM, "single open source")
        assert identity.observed_at == datetime(2026, 9, 1, tzinfo=UTC)

    @pytest.mark.parametrize("source", ["McDowell 2025 / CSIS 2025", "McDowell 2025; CSIS 2025",
                                        "McDowell 2025 and CSIS 2025"])
    def test_a_record_with_two_sources_is_credibility_2_even_undated(self, source: str) -> None:
        identity = _one(tu.intel_items({"threat_level": "HIGH", "source": source}, "1"), Dimension.IDENTITY)
        assert (identity.credibility, identity.note) == (2, "undated")

    @pytest.mark.parametrize("level", ["MEDIUM", "LOW", "HIHG", ""])
    def test_a_lower_or_unrecognised_level_raises_nothing(self, level: str) -> None:
        record = {"threat_level": level, "source": "x", "assessed_at": "2026-09-01T00:00:00Z"}
        identity = _one(tu.intel_items(record, "1"), Dimension.IDENTITY)
        assert identity.floor_to is None

    def test_an_unrecognised_level_is_named_in_the_note(self) -> None:
        identity = _one(tu.intel_items({"threat_level": "HIHG"}, "1"), Dimension.IDENTITY)
        assert identity.note == (
            "undated, unsourced; its threat level 'HIHG' is not a recognised band, so it carries no reading")

    def test_an_unsourced_dated_record_raises_nothing(self) -> None:
        record = {"threat_level": "CRITICAL", "assessed_at": "2026-09-01"}
        assert _one(tu.intel_items(record, "1"), Dimension.IDENTITY).floor_to is None

    def test_an_impaired_status_is_capped_capability_evidence_with_a_medium_ceiling(self) -> None:
        status = _one(tu.intel_items({"status": "Degraded"}, "61769"), Dimension.CAPABILITY)
        assert (status.manufacturable, status.impaired_status, status.ceiling_to) == (True, True, Band.MEDIUM)
        assert (status.grade, status.basis, status.derived_from) == ("D3", Basis.LOOKUP, "status:61769")
        assert tu.reliability(status, _NOW) <= tu.MANUFACTURABLE_CAP

    def test_an_operational_status_is_coverage_only(self) -> None:
        status = _one(tu.intel_items({"status": "Operational"}, "1"), Dimension.CAPABILITY)
        assert (status.impaired_status, status.has_reading, status.manufacturable) == (False, False, True)

    def test_no_record_gives_no_items(self) -> None:
        assert tu.intel_items(None, "1") == ()

    @pytest.mark.parametrize(("raw", "expected"), [
        ("2026-09-01", datetime(2026, 9, 1, tzinfo=UTC)),
        ("2026-09-01T06:30:00Z", datetime(2026, 9, 1, 6, 30, tzinfo=UTC)),
        ("2026-09-01T06:30:00+01:00", datetime(2026, 9, 1, 5, 30, tzinfo=UTC)),
        ("last spring", None),
        ("", None),
        (None, None),
        (20260901, None),
    ])
    def test_the_record_date(self, raw: object, expected: datetime | None) -> None:
        assert tu.record_date({"assessed_at": raw}) == expected
        assert tu.record_date(None) is None


class TestTheGcatEntry:
    def test_a_catalogue_entry_is_b2_identity_dated_from_its_refresh(self) -> None:
        fetched = _NOW - timedelta(days=30)
        (entry,) = tu.gcat_items({"Bus": "Luch", "LDate": "2014 Sep 27", "Owner": "RVSN"}, fetched, "40258")
        assert (entry.dimension, entry.grade, entry.extraction, entry.observed_at) == (
            Dimension.IDENTITY, "B2", tu.CATALOGUE_FIELD_EXTRACTION, fetched)
        assert (entry.derived_from, entry.has_reading) == ("gcat:40258", False)
        assert entry.label == "GCAT entry: bus Luch, launched 2014 Sep 27, owner RVSN"
        assert tu.reliability(entry, _NOW) == pytest.approx(0.64, abs=0.005)

    def test_an_entry_with_no_fields_named_still_counts_and_no_entry_gives_nothing(self) -> None:
        (entry,) = tu.gcat_items({"Bus": "-", "Owner": ""}, _NOW, "1")
        assert entry.label == "GCAT entry"
        assert tu.gcat_items(None, _NOW, "1") == ()


class TestTheHistoryCapability:
    def test_the_reserve_is_computed_capability_from_the_providers_chain(self) -> None:
        reserve = _one(_items(_signals()), Dimension.CAPABILITY)
        assert (reserve.grade, reserve.extraction, reserve.basis) == ("B2", tu.ASSUMED_FIGURE_EXTRACTION,
                                                                       Basis.COMPUTED)
        assert (reserve.derived_from, reserve.observed_at, reserve.controlled) == (
            "elset-history:18SDS", _NOW - _SIX_HOURS, True)
        assert (reserve.label, reserve.ceiling_to) == ("reserve 72 of 120 m/s", None)

    def test_a_reserve_below_half_lowers_the_ceiling_to_medium(self) -> None:
        reserve = _one(_items(_signals(reserve_remaining_m_s=50.0)), Dimension.CAPABILITY)
        assert reserve.ceiling_to is Band.MEDIUM

    def test_a_reserve_at_exactly_half_lowers_nothing(self) -> None:
        assert _one(_items(_signals(reserve_remaining_m_s=60.0)), Dimension.CAPABILITY).ceiling_to is None

    def test_a_spent_tank_with_no_later_burn_lowers_the_ceiling_to_minimal(self) -> None:
        reserve = _one(_items(_signals(reserve_remaining_m_s=0.0, tank_spent=True)), Dimension.CAPABILITY)
        assert (reserve.ceiling_to, reserve.label) == (Band.MINIMAL, "tank spent: reserve 0 of 120 m/s")

    def test_a_spent_tank_followed_by_a_burn_carries_no_reading(self) -> None:
        signals = _signals(reserve_remaining_m_s=0.0, tank_spent=True, burn_after_spent=True)
        reserve = _one(_items(signals), Dimension.CAPABILITY)
        assert reserve.ceiling_to is None
        assert reserve.note == "a confirmed burn followed the moment the tank read spent, so the tank model does not hold"

    def test_no_reserve_figure_gives_no_capability_item(self) -> None:
        assert not [i for i in _items(_signals(reserve_max_m_s=None)) if i.dimension is Dimension.CAPABILITY]

    def test_a_zero_maximum_reserve_reads_no_share(self) -> None:
        reserve = _one(_items(_signals(reserve_remaining_m_s=0.0, reserve_max_m_s=0.0)), Dimension.CAPABILITY)
        assert reserve.ceiling_to is None


class TestTheLatestBurn:
    @pytest.mark.parametrize(("normality", "floor"), [
        (Normality.UNPRECEDENTED, Band.HIGH), (Normality.UNUSUAL, Band.MEDIUM),
    ])
    def test_a_hostile_burn_raises_the_floor(self, normality: Normality, floor: Band) -> None:
        burn = BurnSignal(epoch=_BURN, normality=normality, detection="HIGH", source="18SDS")
        (item,) = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert (item.floor_to, item.extraction, item.observed_at, item.basis) == (floor, 0.9, _BURN, Basis.COMPUTED)
        assert (item.label, item.derived_from) == (f"latest burn, {normality.value}", "elset-history:18SDS")

    def test_a_routine_burn_is_coverage_only_and_capped(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.ROUTINE, detection="HIGH", source="18SDS")
        (item,) = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert (item.routine, item.has_reading) == (True, False)
        assert tu.reliability(item, _NOW) == tu.ROUTINE_CAP

    def test_a_burn_too_soon_to_judge_is_listed_as_missing_and_carries_no_weight(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.NOT_ENOUGH_HISTORY, detection="HIGH", source="18SDS",
                          corroborated_by=("LEOLABS",))
        behaviour = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert len(behaviour) == 2
        for item in behaviour:
            assert (item.routine, item.has_reading, item.extraction) == (False, False, 0.0)
            assert tu.reliability(item, _NOW) == 0.0
            assert item.note == "too little history to judge whether it is normal: listed as missing"

    def test_a_burn_too_soon_to_judge_earns_no_behaviour(self) -> None:
        """Section 5.3: NOT_ENOUGH_HISTORY is missing, so it cannot lift Understanding to MODERATE."""
        burn = BurnSignal(epoch=_NOW - timedelta(days=10), normality=Normality.NOT_ENOUGH_HISTORY,
                          detection="HIGH", source="18SDS")
        signals = _signals(burns=(burn,))
        result = tu.assess((*tu.gcat_items(*_GCAT, "1"), *_items(signals)), tu.with_history(_base(), signals))
        assert result.range.coverage[Dimension.BEHAVIOUR] == 0.0
        assert result.understanding.level is Understanding.LOW

    def test_an_aggressive_posture_still_counts_on_a_burn_too_soon_to_judge(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.NOT_ENOUGH_HISTORY, detection="HIGH", source="18SDS",
                          posture=Posture.AGGRESSIVE)
        (posture,) = [i for i in _items(_signals(burns=(burn,))) if i.floor_to is not None]
        assert (posture.floor_to, posture.extraction) == (Band.MEDIUM, 0.9)

    def test_only_the_latest_burn_is_read(self) -> None:
        older = BurnSignal(epoch=_BURN - timedelta(days=40), normality=Normality.UNPRECEDENTED, detection="HIGH",
                           source="18SDS")
        latest = BurnSignal(epoch=_BURN, normality=Normality.ROUTINE, detection="HIGH", source="18SDS")
        behaviour = [i for i in _items(_signals(burns=(latest, older))) if i.dimension is Dimension.BEHAVIOUR]
        assert [i.label for i in behaviour] == ["latest burn, routine"]

    def test_a_burn_across_a_long_gap_is_read_at_half_the_extraction(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS",
                          long_gap=True)
        (item,) = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert item.extraction == pytest.approx(0.45)
        assert tu.reliability(item, _NOW, burns=()) == pytest.approx(
            tu.reliability(replace(item, extraction=0.9), _NOW) / 2)

    def test_an_unassessed_detection_is_read_as_low(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNUSUAL, detection="UNASSESSED", source="18SDS")
        (item,) = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert item.extraction == tu.DETECTION_EXTRACTION["LOW"]

    @pytest.mark.parametrize("posture", [Posture.AGGRESSIVE, Posture.BEYOND_PLATFORM])
    def test_an_aggressive_posture_raises_the_floor_to_medium_from_the_same_chain(self, posture: Posture) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.ROUTINE, detection="HIGH", source="18SDS",
                          posture=posture)
        items = [i for i in _items(_signals(burns=(burn,))) if i.floor_to is not None]
        (item,) = items
        assert (item.floor_to, item.group, item.label) == (
            Band.MEDIUM, (Dimension.BEHAVIOUR, "elset-history:18SDS"), f"latest burn posture {posture.value.lower()}")

    @pytest.mark.parametrize("posture", [Posture.BENIGN, Posture.ANNOYANCE, None])
    def test_a_benign_posture_adds_nothing(self, posture: Posture | None) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.ROUTINE, detection="HIGH", source="18SDS",
                          posture=posture)
        assert not [i for i in _items(_signals(burns=(burn,))) if "posture" in i.label]


class TestCorroboration:
    def test_each_corroborating_provider_opens_its_own_group_at_credibility_1(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS",
                          corroborated_by=("EXOANALYTIC", "LEOLABS"))
        behaviour = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert sorted((i.derived_from, i.grade, i.floor_to) for i in behaviour) == [
            ("elset-history:18SDS", "B2", Band.HIGH),
            ("elset-history:EXOANALYTIC", "C1", Band.HIGH),
            ("elset-history:LEOLABS", "C1", Band.HIGH),
        ]
        assert len({i.group for i in behaviour}) == 3

    def test_three_groups_cover_more_than_one(self) -> None:
        alone = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS")
        seen = replace(alone, corroborated_by=("EXOANALYTIC", "LEOLABS"))
        cover = [tu.coverage(_items(_signals(burns=(b,))), _NOW)[Dimension.BEHAVIOUR] for b in (alone, seen)]
        assert cover[1] > cover[0]

    def test_a_copy_of_its_own_provider_is_not_a_second_group(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS",
                          corroborated_by=("18SDS", "LEOLABS", "LEOLABS"))
        behaviour = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert sorted(i.derived_from for i in behaviour) == ["elset-history:18SDS", "elset-history:LEOLABS"]

    def test_copies_of_the_18_sds_catalogue_count_once(self) -> None:
        """Section 5.3: "Copies of one catalogue count once", whichever name each copy arrives under."""
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS",
                          corroborated_by=("SPACETRACK", "18 SDS", "CSPOC", "Space-Track", "LEOLABS"))
        behaviour = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert sorted((i.derived_from, i.grade) for i in behaviour) == [
            ("elset-history:18SDS", "B2"), ("elset-history:LEOLABS", "C1")]

    def test_a_burn_detected_under_an_alias_is_its_catalogues_own_report(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="SPACE-TRACK",
                          corroborated_by=("18SDS",))
        items = _items(_signals(provider="18 SDS", burns=(burn,)))
        assert {i.derived_from for i in items} == {"elset-history:18SDS"}
        assert {i.grade for i in items if i.dimension is Dimension.BEHAVIOUR} == {"B2"}

    def test_spellings_of_one_provider_are_one_group(self) -> None:
        burn = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS",
                          corroborated_by=("LEO LABS", "LeoLabs"))
        behaviour = [i for i in _items(_signals(burns=(burn,))) if i.dimension is Dimension.BEHAVIOUR]
        assert sorted(i.derived_from for i in behaviour) == ["elset-history:18SDS", "elset-history:LEOLABS"]
        assert [i.label for i in behaviour if i.credibility == 1] == [
            "latest burn, unprecedented, corroborated by LEO LABS"]

    @pytest.mark.parametrize(("provider", "grade"), [
        ("18SDS", "B"), ("18 SDS", "B"), ("18th SPCS", "B"), ("LEOLABS", "C"), ("UNATTRIBUTED", "C"), ("", "C"),
    ])
    def test_provider_grades(self, provider: str, grade: str) -> None:
        assert tu.provider_grade(provider) == grade

    def test_the_grade_table_can_name_an_allied_sensor(self) -> None:
        assert tu.provider_grade("allied optical", {"ALLIEDOPTICAL": "A"}) == "A"


class TestTheAnomalyIndex:
    def test_it_is_a_lookup_whose_floor_is_capped_at_medium(self) -> None:
        anomaly = next(i for i in _items(_signals(anomaly_score=90.0)) if i.label.startswith("anomaly"))
        assert (anomaly.basis, anomaly.floor_to, anomaly.label) == (Basis.LOOKUP, Band.MEDIUM, "anomaly index 90")
        assert anomaly.group == (Dimension.BEHAVIOUR, "elset-history:18SDS")

    def test_a_low_rung_floors_at_low_and_the_lowest_raises_nothing(self) -> None:
        low = next(i for i in _items(_signals(anomaly_score=20.0)) if i.label.startswith("anomaly"))
        minimal = next(i for i in _items(_signals(anomaly_score=5.0)) if i.label.startswith("anomaly"))
        assert (low.floor_to, minimal.floor_to) == (Band.LOW, None)

    def test_it_is_folded_under_a_stronger_burn_from_the_same_chain(self) -> None:
        result = tu.assess(_items(_signals(anomaly_score=90.0)), tu.with_history(_base(), _signals()))
        row = next(r for r in result.range.ledger if r.item.label == "anomaly index 90")
        assert row.status is Status.FOLDED


class TestTheAbsenceRule:
    """Section 5.3: "no burns" counts only under the absence rule, and never moves a band (I8)."""

    def _quiet(self, **kw: Any) -> HistorySignals:
        return _signals(burns=(), **kw)

    def test_a_quiet_history_held_under_the_rule_adds_behaviour_coverage_only(self) -> None:
        absence = _one(_items(self._quiet()), Dimension.BEHAVIOUR)
        assert (absence.label, absence.routine, absence.has_reading, absence.extraction) == (
            "no burns in 400 days", True, False, 0.5)
        assert tu.reliability(absence, _NOW) == pytest.approx(0.34, abs=0.005)

    @pytest.mark.parametrize("floor", [9.0, 12.0])
    def test_the_delta_v_test_a_floor_at_or_above_the_intercept_counts_nothing(self, floor: float) -> None:
        assert not [i for i in _items(self._quiet(detection_floor_m_s=floor)) if i.dimension is Dimension.BEHAVIOUR]

    def test_a_span_of_exactly_30_days_counts(self) -> None:
        assert _one(_items(self._quiet(span_days=30.0)), Dimension.BEHAVIOUR).routine

    def test_a_floor_below_the_intercept_counts(self) -> None:
        assert _one(_items(self._quiet(detection_floor_m_s=8.9)), Dimension.BEHAVIOUR).routine

    @pytest.mark.parametrize(("kw", "custody"), [
        ({"detection_floor_m_s": None}, Custody.HELD),
        ({"span_days": 29.0}, Custody.HELD),
        ({"long_gap_open": True}, Custody.HELD),
        ({}, Custody.DEGRADED),
        ({}, Custody.LOST),
    ])
    def test_each_condition_of_the_rule_is_needed(self, kw: dict[str, Any], custody: Custody) -> None:
        assert not [i for i in _items(self._quiet(**kw), custody) if i.dimension is Dimension.BEHAVIOUR]

    def test_it_moves_no_band(self) -> None:
        result = tu.assess(_items(self._quiet()), tu.with_history(_base(legacy=Band.HIGH), self._quiet()))
        assert (result.range.floor, result.range.ceiling) == (Band.MINIMAL, Band.CRITICAL)
        assert result.understanding.level is Understanding.LOW


class TestTheSituation:
    def test_the_history_sets_the_burns_the_newest_set_detection_and_truncation(self) -> None:
        signals = _signals(truncated=True)
        situation = tu.with_history(_base(), signals)
        assert situation.burns == (HeldBurn(_BURN, Normality.UNPRECEDENTED),)
        assert (situation.newest_elset_at, situation.sees_routine_station_keeping,
                situation.history_truncated) == (_NOW - _SIX_HOURS, True, True)

    def test_no_history_leaves_it_as_it_was(self) -> None:
        assert tu.with_history(_base(), None) == _base()


# ── The converter from a held history (pol and its Pattern of Life reading) ──

def _view(epoch: datetime, dv: float, *, routine: bool = False, **m: Any) -> SimpleNamespace:
    manoeuvre = SimpleNamespace(
        epoch=epoch, burn_epoch=m.pop("burn_epoch", epoch), confidence=m.pop("confidence", "HIGH"),
        tle_after=SimpleNamespace(source=m.pop("source", "18SDS")), corroborated_by=m.pop("corroborated_by", ()),
        long_gap=m.pop("long_gap", False))
    label = "station keeping" if routine else "relocation"
    return SimpleNamespace(manoeuvre=manoeuvre, delta_v_m_s=dv, is_routine=routine, classification=label,
                           posture=SimpleNamespace(posture=m.pop("posture", Posture.BENIGN)))


def _records(start: datetime, days: int, sources: tuple[str, ...] = ("18SDS",), step: float = 1.0) -> list[Any]:
    count = int(days / step) + 1
    return [SimpleNamespace(epoch=start + timedelta(days=k * step), source=sources[k % len(sources)])
            for k in range(count)]


def _propellant(**kw: Any) -> SimpleNamespace:
    args: dict[str, Any] = {"reserve_reset": None, "assumed_isp_s": 300.0, "propellant_fraction": 0.4,
                            "discretionary_max_m_s": 120.0, "discretionary_remaining_m_s": 72.0}
    args.update(kw)
    return SimpleNamespace(**args)


def _held(views: list[Any], records: list[Any], **kw: Any) -> tuple[Any, Any]:
    pol = SimpleNamespace(records=records, span_days=kw.pop("span_days", 400.0),
                          skipped_long_gap=kw.pop("skipped_long_gap", 0),
                          history_truncated_at=kw.pop("truncated_at", None))
    assessment = SimpleNamespace(
        manoeuvres=views, propellant=kw.pop("propellant", _propellant()),
        anomaly=kw.pop("anomaly", None),
        detection=kw.pop("detection", SimpleNamespace(floor_m_s=0.4, sees_routine_station_keeping=True)))
    return pol, assessment


_START = _NOW - timedelta(days=400)


class TestTheConverter:
    def test_a_quiet_history(self) -> None:
        signals = tu.history_signals(*_held([], _records(_START, 400)))
        assert (signals.provider, signals.newest_at, signals.span_days, signals.burns) == (
            "18SDS", _START + timedelta(days=400), 400.0, ())
        assert (signals.reserve_remaining_m_s, signals.reserve_max_m_s, signals.tank_spent) == (72.0, 120.0, False)
        assert (signals.detection_floor_m_s, signals.sees_routine_station_keeping) == (0.4, True)
        assert (signals.anomaly_score, signals.long_gap_open, signals.truncated) == (None, False, False)

    def test_the_provider_is_the_one_with_most_sets_and_unattributed_sets_are_grouped(self) -> None:
        records = _records(_START, 10, sources=("leolabs", "", ""))
        assert tu.history_signals(*_held([], records)).provider == "UNATTRIBUTED"

    def test_copies_of_one_catalogue_are_one_provider(self) -> None:
        records = _records(_START, 10, sources=("SPACETRACK", "18 SDS", "CSPOC", "LEOLABS", "LEOLABS"))
        views = [_view(_BURN, 11.0, source="Space-Track", corroborated_by=("18SDS", "LEOLABS"))]
        signals = tu.history_signals(*_held(views, records))
        assert (signals.provider, signals.burns[-1].source) == ("18SDS", "18SDS")

    def test_each_burn_is_judged_against_those_before_it_and_carries_its_detection(self) -> None:
        views = [_view(_START + timedelta(days=40 + 30 * k), 2.0, routine=True) for k in range(8)]
        views.append(_view(_BURN, 11.0, burn_epoch=_BURN, confidence="MODERATE", source="18SDS",
                           corroborated_by=("LEOLABS",), long_gap=True, posture=Posture.AGGRESSIVE))
        signals = tu.history_signals(*_held(views, _records(_START, 400)))
        latest = signals.burns[-1]
        assert [b.normality for b in signals.burns[:5]] == [Normality.NOT_ENOUGH_HISTORY] * 5
        assert latest.normality is Normality.UNPRECEDENTED
        assert (latest.epoch, latest.detection, latest.source, latest.corroborated_by, latest.long_gap,
                latest.posture) == (_BURN, "MODERATE", "18SDS", ("LEOLABS",), True, Posture.AGGRESSIVE)

    def test_the_anomaly_index_detection_floor_and_truncation_are_read(self) -> None:
        pol, assessment = _held([], _records(_START, 400), anomaly=SimpleNamespace(overall=62.0), detection=None,
                                truncated_at=_START)
        signals = tu.history_signals(pol, assessment)
        assert (signals.anomaly_score, signals.detection_floor_m_s, signals.sees_routine_station_keeping,
                signals.truncated) == (62.0, None, False, True)

    def test_a_gap_longer_than_ten_days_or_a_skipped_pair_is_open(self) -> None:
        gapped = _records(_START, 400, step=11.0)
        assert tu.history_signals(*_held([], gapped)).long_gap_open
        assert not tu.history_signals(*_held([], _records(_START, 400, step=10.0))).long_gap_open
        assert tu.history_signals(*_held([], _records(_START, 400), skipped_long_gap=1)).long_gap_open


class TestTheTankWalk:
    """When the tank first read spent, and whether any confirmed burn followed it."""

    def test_a_reserve_emptied_by_the_latest_burn_is_spent_with_no_later_burn(self) -> None:
        views = [_view(_START + timedelta(days=d), 60.0) for d in (100, 200)]
        signals = tu.history_signals(*_held(views, _records(_START, 400),
                                            propellant=_propellant(discretionary_remaining_m_s=0.0)))
        assert (signals.tank_spent, signals.burn_after_spent) == (True, False)

    def test_a_burn_after_the_reserve_emptied_is_held_against_it(self) -> None:
        views = [_view(_START + timedelta(days=d), 60.0) for d in (100, 200)]
        views.append(_view(_START + timedelta(days=300), 1.0, routine=True))
        signals = tu.history_signals(*_held(views, _records(_START, 400),
                                            propellant=_propellant(discretionary_remaining_m_s=0.0)))
        assert (signals.tank_spent, signals.burn_after_spent) == (True, True)

    def test_routine_burns_do_not_empty_the_reserve(self) -> None:
        views = [_view(_START + timedelta(days=d), 60.0, routine=True) for d in (100, 200)]
        assert not tu.history_signals(*_held(views, _records(_START, 400))).tank_spent

    def test_a_tank_used_past_95_per_cent_is_spent(self) -> None:
        # 300 s Isp, 0.4 of mass propellant: 95 per cent of the load is about 1,439 m/s.
        views = [_view(_START + timedelta(days=d), 750.0, routine=True) for d in (100, 200)]
        signals = tu.history_signals(*_held(views, _records(_START, 400)))
        assert (signals.tank_spent, signals.burn_after_spent) == (True, False)

    @pytest.mark.parametrize(("used_pct", "spent"), [(94.9, False), (95.1, True)])
    def test_the_spent_line_is_95_per_cent_of_the_load_at_standard_gravity(self, used_pct: float, spent: bool) -> None:
        # The rocket equation at 300 s Isp and standard gravity, 9.80665 m/s^2, 0.4 of mass propellant.
        dv = -300.0 * 9.80665 * math.log(1.0 - 0.4 * used_pct / 100.0)
        views = [_view(_START + timedelta(days=100), dv, routine=True)]
        assert tu.history_signals(*_held(views, _records(_START, 400))).tank_spent is spent

    def test_a_burn_on_the_reset_epoch_is_counted(self) -> None:
        views = [_view(_START + timedelta(days=d), 60.0) for d in (100, 200)]
        reset = _START + timedelta(days=100)
        assert tu.history_signals(*_held(views, _records(_START, 400),
                                         propellant=_propellant(reserve_reset=reset))).tank_spent

    def test_burns_before_a_refuelling_are_not_counted(self) -> None:
        views = [_view(_START + timedelta(days=d), 60.0) for d in (100, 200)]
        reset = _START + timedelta(days=150)
        assert not tu.history_signals(*_held(views, _records(_START, 400),
                                             propellant=_propellant(reserve_reset=reset))).tank_spent


# ── The worked example of section 4.12, rows 1 to 6, from the adapters ──

_RECORD = {"name": "RED-GEO-1", "assessed_threat": "Inspector", "threat_level": "CRITICAL",
           "source": "Secure World Foundation 2025"}
_GCAT = ({"Bus": "Luch", "LDate": "2014 Sep 27", "Owner": "RVSN"}, _NOW - timedelta(days=30))
_ALLIED = "ALLIED OPTICAL"
_GRADES = {**tu.PROVIDER_GRADES, "ALLIEDOPTICAL": "A"}
_LATEST = BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH", source="18SDS")
_EARLIER = tuple(BurnSignal(epoch=_BURN - timedelta(days=15 * k), normality=Normality.ROUTINE, detection="HIGH",
                            source="18SDS") for k in range(22, 0, -1))
_UDL = _signals(burns=(*_EARLIER, replace(_LATEST, corroborated_by=(_ALLIED,))), anomaly_score=90.0)
_COMMERCIAL = HistorySignals(provider="COMMERCIALCO", newest_at=_NOW, span_days=200.0,
                             reserve_remaining_m_s=66.0, reserve_max_m_s=120.0)


def _rows() -> list[tuple[EvidenceItem, ...]]:
    udl = _items(_UDL, grades=_GRADES)
    capability = tuple(i for i in udl if i.dimension is Dimension.CAPABILITY)
    own = tuple(i for i in udl if i.dimension is Dimension.BEHAVIOUR and i.derived_from == "elset-history:18SDS")
    allied = tuple(i for i in udl if i.derived_from == "elset-history:ALLIEDOPTICAL")
    rows = [tu.intel_items(_RECORD, "RED-GEO-1")]
    for added in (tu.gcat_items(*_GCAT, "RED-GEO-1"), capability, own, allied, _items(_COMMERCIAL)):
        rows.append(rows[-1] + added)
    return rows


#: Row: (coverage I C B X, floor, ceiling, Understanding, governing categories), as in section 4.12.
_EXPECTED = {
    1: ((0.09, 0, 0, 0), Band.MINIMAL, Understanding.LOW, ("information base",)),
    2: ((0.67, 0, 0, 0), Band.MINIMAL, Understanding.LOW, ("information base",)),
    3: ((0.67, 0.34, 0, 0), Band.MINIMAL, Understanding.LOW, ("information base",)),
    4: ((0.67, 0.34, 0.60, 0), Band.HIGH, Understanding.MODERATE, ("information base", "volatility")),
    5: ((0.67, 0.34, 0.92, 0), Band.HIGH, Understanding.MODERATE, ("information base", "volatility")),
    6: ((0.67, 0.51, 0.92, 0), Band.HIGH, Understanding.MODERATE, ("volatility",)),
}


class TestTheWorkedExampleFromTheAdapters:
    @pytest.mark.parametrize("row", sorted(_EXPECTED))
    def test_each_row(self, row: int) -> None:
        cover, floor, level, governing = _EXPECTED[row]
        situation = tu.with_history(_base(), _UDL) if row >= 3 else _base()
        result = tu.assess(_rows()[row - 1], situation)
        c = result.range.coverage
        assert tuple(round(c[d], 2) for d in Dimension) == pytest.approx(cover)
        assert (result.range.floor, result.range.ceiling) == (floor, Band.CRITICAL)
        assert (result.understanding.level, result.understanding.governing) == (level, governing)
        assert result.verdict.assessed is Band.CRITICAL

    def test_the_q_of_each_item_added(self) -> None:
        ledger = {r.item.label: r.q for r in tu.assess(_rows()[5], _base()).range.ledger}
        labels = ["intel record, role Inspector", "GCAT entry: bus Luch, launched 2014 Sep 27, owner RVSN",
                  "reserve 72 of 120 m/s", "latest burn, unprecedented",
                  "latest burn, unprecedented, corroborated by ALLIED OPTICAL", "reserve 66 of 120 m/s"]
        # The concept prints 0.255 rounded half up as 0.26.
        assert [ledger[label] for label in labels] == pytest.approx([0.09, 0.64, 0.34, 0.60, 0.80, 0.255], abs=0.005)

    def test_the_anomaly_index_rides_in_the_burns_group_and_is_folded(self) -> None:
        result = tu.assess(_rows()[3], tu.with_history(_base(), _UDL))
        row = next(r for r in result.range.ledger if r.item.label == "anomaly index 90")
        assert (row.item.basis, row.status) == (Basis.LOOKUP, Status.FOLDED)
