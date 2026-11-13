"""Threat Understanding on the sweep: the evidence gathered, decide-by, and the shadow display.

SPC-165: the sweep gathers what it holds about the red object (its intel
record, its GCAT entry, its element-set history) into evidence items, and
the record's date reaches ``CapabilityEvidence.intel_record_dated``.
SPC-167: a recorded status is evidence, and decide-by is withheld only on an
earned MINIMAL ceiling. SPC-166: the model runs beside the legacy verdict, in
shadow, with a ledger hash, and the legacy verdict does not move.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from spectre.astro.pattern_of_life import analyse_pattern_of_life
from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decide_by import DecideBy, Due
from spectre.domain.models import ThreatSweepEntry, ThreatTarget
from spectre.domain.normality import Normality
from spectre.domain.provenance import ledger_input
from spectre.domain.threat_assessment import AccessEvidence, Band, CapabilityEvidence, assess_threat
from spectre.domain.threat_understanding import Dimension, ThreatUnderstanding
from spectre.domain.warning_change import Change, TargetWarning, WarningChange
from spectre.domain.warning_change import Status as WarningStatus
from spectre.web.routes import gcat, threat
from spectre.web.routes.pol import history_evidence
from tests.unit.test_dv_estimation import _AP0, _E0, _I0, _MA0, _N0, _RA0, _burn, _coast, _Elements, _rec, _tle

_SATNO = "62902"
_STEP_DAYS = 0.25
_START_EPOCH = 26100.0
_HELD = CustodyStatus(Custody.HELD, "Custody held.")


def _history_records(events: list[tuple[int, float]], source: str = "18SDS") -> list[Any]:
    """An object coasting ``n`` element sets, then raising its orbit by ``d_alt_km``, for each event."""
    recs, tle = [], _tle(_Elements(_N0, _E0, _I0, _RA0, _AP0, _MA0, _START_EPOCH))
    for n_sets, d_alt_km in events:
        for _ in range(n_sets):
            recs.append(_rec(tle, source=source))
            tle = _coast(tle, _STEP_DAYS)
        tle = _burn(tle, d_alt_km=d_alt_km)
    for _ in range(2):
        recs.append(_rec(tle, source=source))
        tle = _coast(tle, _STEP_DAYS)
    return recs


def _held_history(events: list[tuple[int, float]]) -> Any:
    records = _history_records(events)
    pol = analyse_pattern_of_life(records, satno=int(_SATNO), name="RED-LEO", dv_threshold=0.002)
    assessment, normality = history_evidence(pol)
    return threat._RedHistory(pol, assessment, normality, "", records[-1].epoch)


_NO_HISTORY = threat._RedHistory(None, None, None, "UDL is not connected.", None)
_RAISES = [(40, 25.0)] * 7 + [(40, 150.0)]


@pytest.fixture
def cache() -> Any:
    saved = dict(gcat._CACHE)
    gcat._CACHE.clear()
    yield gcat._CACHE
    gcat._CACHE.clear()
    gcat._CACHE.update(saved)


def _satcat(rows: list[dict[str, str]], fetched_at: datetime) -> dict[str, Any]:
    df = pd.DataFrame(rows)
    return {"df": df, "fetched_at": fetched_at, "rows": len(df), "cols": len(df.columns), "columns": list(df.columns)}


_FETCHED = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


class TestTheCatalogueEntry:
    def test_a_cached_satcat_row_is_read_with_its_refresh_time(self, cache: Any) -> None:
        cache["satcat"] = _satcat([{"Satcat": "40258", "Bus": "Luch", "Owner": "RVSN"},
                                   {"Satcat": "62902", "Bus": "-", "Owner": "X"}], _FETCHED)
        assert gcat.catalogue_entry("40258") == ({"Satcat": "40258", "Bus": "Luch", "Owner": "RVSN"}, _FETCHED)

    def test_an_object_not_in_it_or_no_cache_reads_none_and_nothing_is_fetched(
            self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gcat, "_fetch_one", lambda *_a: pytest.fail("the catalogue was fetched"))
        assert gcat.catalogue_entry("40258") is None
        cache["satcat"] = _satcat([{"Satcat": "1"}], _FETCHED)
        assert gcat.catalogue_entry("40258") is None
        assert gcat.catalogue_entry(None) is None

    def test_a_table_without_a_satcat_column_reads_none(self, cache: Any) -> None:
        cache["satcat"] = _satcat([{"Name": "X"}], _FETCHED)
        assert gcat.catalogue_entry("1") is None


class TestTheRecordDateReachesCapability:
    def test_a_dated_record_sets_intel_record_dated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: {"threat_level": "HIGH", "assessed_at": "2026-09-01"})
        assert threat._red_capability("1").intel_record_dated is True

    def test_an_undated_record_does_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: {"threat_level": "HIGH"})
        assert threat._red_capability("1").intel_record_dated is False


class TestTheSweepGathersTheEvidence:
    def test_the_record_the_catalogue_and_the_history(self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: {"assessed_threat": "Inspector", "threat_level": "HIGH",
                                                             "status": "Degraded", "source": "CSIS 2025"})
        cache["satcat"] = _satcat([{"Satcat": _SATNO, "Bus": "Luch"}], _FETCHED)
        history = _held_history(_RAISES)
        held = threat._red_evidence(_SATNO, history, _HELD)
        assert held is not None
        items, signals = held.items(history.pol.records[-1].epoch, "LEO", 500.0), held.signals
        assert signals is not None and signals.provider == "18SDS"
        assert sorted({(i.dimension, i.derived_from) for i in items}, key=str) == sorted({
            (Dimension.IDENTITY, f"intel-record:{_SATNO}"), (Dimension.CAPABILITY, f"status:{_SATNO}"),
            (Dimension.IDENTITY, f"gcat:{_SATNO}"), (Dimension.CAPABILITY, "elset-history:18SDS"),
            (Dimension.BEHAVIOUR, "elset-history:18SDS")}, key=str)
        latest = next(i for i in items if i.label.startswith("latest burn"))
        assert latest.observed_at == signals.burns[-1].epoch

    def test_without_a_history_only_the_record_and_catalogue_are_held(self, cache: Any) -> None:
        held = threat._red_evidence("40258", _NO_HISTORY, _HELD)
        assert held is not None and held.signals is None
        assert {i.derived_from for i in held.items(_NOW, "GEO", 9.0)} == {"intel-record:40258", "status:40258"}

    def test_an_object_with_no_number_has_nothing_to_look_up(self, cache: Any) -> None:
        assert threat._red_evidence(None, _NO_HISTORY, _HELD) is None


# ── SPC-167: a recorded status is evidence; decide-by is withheld only on an earned MINIMAL ceiling ──

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)


def _sweep_entry(dv: float = 9.0, target: str = "BLUE-COMSAT", tof: float = 31.0) -> ThreatSweepEntry:
    return ThreatSweepEntry(target=ThreatTarget(target, "30793", "blue", None), burn_epoch=_NOW,
                            burn_location="now", delta_v_m_s=dv, tof_hours=tof, dv_prograde=dv, dv_normal=0.0,
                            dv_radial=0.0, method="lambert", regime="GEO")


def _decide(worst: dict[str, Any] | None, understanding: ThreatUnderstanding | None,
            custody: CustodyStatus = _HELD) -> DecideBy:
    basis = SimpleNamespace(max_dv_m_s=500.0, now=_NOW)
    state = SimpleNamespace(response_time_h=12.0, response_time_by_target={})
    return threat._sweep_decide_by(state, [_sweep_entry()], custody, (worst, understanding), basis)  # type: ignore[arg-type]


def _situation(**kw: Any) -> tu.Situation:
    args: dict[str, Any] = {"now": _NOW, "access": Band.CRITICAL, "legacy": Band.MINIMAL, "regime": "GEO",
                            "data_mode": "REAL", "custody": Custody.HELD, "history_truncated": False}
    args.update(kw)
    return tu.Situation(**args)


def _udl(**kw: Any) -> tu.HistorySignals:
    """An 18 SDS history whose discretionary reserve the latest burn, a routine one, emptied."""
    args: dict[str, Any] = {
        "provider": "18SDS", "newest_at": _NOW - timedelta(hours=6), "span_days": 400.0,
        "burns": (tu.BurnSignal(epoch=_BURN, normality=Normality.ROUTINE, detection="HIGH", source="18SDS"),),
        "reserve_remaining_m_s": 0.0, "reserve_max_m_s": 120.0, "tank_spent": True,
        "detection_floor_m_s": 0.4, "sees_routine_station_keeping": True,
    }
    args.update(kw)
    return tu.HistorySignals(**args)


def _spent_tank(*, later_burn: bool = False, second_provider: bool = True, mode: str = "REAL",
                access: Band = Band.CRITICAL) -> ThreatUnderstanding:
    """A spent tank read from the 18 SDS history and, when *second_provider*, from a commercial one too."""
    udl = _udl(burn_after_spent=later_burn)
    items = [*tu.gcat_items({"Bus": "DFH-3"}, _NOW - timedelta(days=30), _SATNO),
             *tu.history_items(udl, access_delta_v_m_s=9.0, custody=Custody.HELD)]
    if second_provider:
        commercial = tu.HistorySignals(provider="COMMERCIALCO", newest_at=_NOW, span_days=200.0,
                                       reserve_remaining_m_s=0.0, reserve_max_m_s=120.0, tank_spent=True,
                                       burn_after_spent=later_burn)
        items.extend(tu.history_items(commercial, access_delta_v_m_s=9.0, custody=Custody.HELD))
    return tu.assess(items, tu.with_history(_situation(data_mode=mode, access=access), udl))


def _degraded_with_newer_burn() -> ThreatUnderstanding:
    udl = _udl(burns=(tu.BurnSignal(epoch=_BURN, normality=Normality.UNPRECEDENTED, detection="HIGH",
                                    source="18SDS"),),
               reserve_remaining_m_s=72.0, tank_spent=False)
    items = [*tu.intel_items({"assessed_threat": "Inspector", "threat_level": "LOW", "status": "Degraded"}, _SATNO),
             *tu.history_items(udl, access_delta_v_m_s=9.0, custody=Custody.HELD)]
    return tu.assess(items, tu.with_history(_situation(), udl))


_DEGRADED = {"capability_level": "MINIMAL", "incapacity": "the recorded status 'Degraded', declared, not observed"}
_SPENT = {"capability_level": "MINIMAL", "incapacity": "a spent discretionary reserve, computed from its history"}


class TestAStatusNoLongerSilencesTheClock:
    def test_degraded_with_a_newer_burn_keeps_decide_by_and_names_the_deception(self) -> None:
        result = _decide(_DEGRADED, _degraded_with_newer_burn())
        assert result.due is Due.SET
        assert result.sentence.endswith(
            "Capability reads MINIMAL on the recorded status 'Degraded', declared, not observed, but that has not "
            "earned a MINIMAL Threat ceiling, and recorded status Degraded is voided: possible deception, so "
            "decide-by stands.")

    def test_degraded_with_no_history_keeps_decide_by(self) -> None:
        items = tu.intel_items({"threat_level": "LOW", "status": "Degraded"}, _SATNO)
        assert _decide(_DEGRADED, tu.assess(items, _situation())).due is Due.SET


class TestAnEarnedSpentTankStillWithholds:
    def test_a_computed_spent_tank_with_no_later_burn_withholds_and_names_the_evidence(self) -> None:
        result = _decide(_SPENT, _spent_tank())
        assert result.due is Due.NONE
        assert result.sentence == (
            "No decide-by: the evidence has earned a MINIMAL Threat ceiling, tank spent: reserve 0 of 120 m/s, "
            "computed from elset-history:18SDS, at Understanding HIGH.")

    def test_a_spent_tank_with_a_later_burn_keeps_it(self) -> None:
        assert _decide(_SPENT, _spent_tank(later_burn=True)).due is Due.SET

    def test_one_provider_alone_has_not_earned_it(self) -> None:
        """q 0.34 from one 18 SDS history is below EARNED: the clock stays, unlike before SPC-167."""
        assert _decide(_SPENT, _spent_tank(second_provider=False)).due is Due.SET

    def test_at_understanding_low_it_is_not_withheld(self) -> None:
        understanding = _spent_tank(mode="SYNTHETIC")
        assert understanding.range.ceiling is Band.MINIMAL
        assert _decide(_SPENT, understanding).due is Due.SET

    def test_one_provider_alone_says_what_it_has_not_earned(self) -> None:
        assert _decide(_SPENT, _spent_tank(second_provider=False)).sentence.endswith(
            "Capability reads MINIMAL on a spent discretionary reserve, computed from its history, but that has "
            "not earned a MINIMAL Threat ceiling (Capability not earned), so decide-by stands.")

    def test_at_understanding_low_the_sentence_says_that_is_why(self) -> None:
        """The ceiling was set, so the sentence must not say it was not; Understanding LOW is the reason."""
        assert _decide(_SPENT, _spent_tank(mode="SYNTHETIC")).sentence.endswith(
            "Capability reads MINIMAL on a spent discretionary reserve, computed from its history, and the "
            "evidence has set a MINIMAL Threat ceiling, but only at Understanding LOW, so decide-by stands.")

    def test_no_understanding_says_the_evidence_could_not_be_assessed(self) -> None:
        assert _decide(_SPENT, None).sentence.endswith(
            "Capability reads MINIMAL on a spent discretionary reserve, computed from its history, but the "
            "evidence behind it could not be assessed, so decide-by stands.")

    def test_access_setting_the_ceiling_minimal_does_not_earn_an_unapplied_tank(self) -> None:
        """The ceiling is MINIMAL and Understanding is not LOW, but from ACCESS: the tank itself is not applied."""
        understanding = _spent_tank(second_provider=False, access=Band.MINIMAL)
        tank = next(r for r in understanding.range.ledger if r.item.label.startswith("tank spent"))
        assert understanding.range.ceiling is Band.MINIMAL
        assert understanding.understanding.level is not tu.Understanding.LOW
        assert not tank.applied
        assert tu.earned_incapacity(understanding) is None
        assert _decide(_SPENT, understanding).due is Due.SET

    def test_custody_lost_still_withholds_first(self) -> None:
        lost = CustodyStatus(Custody.LOST, "Custody lost.")
        assert _decide(_SPENT, _spent_tank(), lost).sentence.startswith("No decide-by: custody is lost")

    def test_the_domain_rule_names_the_reading(self) -> None:
        row = tu.earned_incapacity(_spent_tank())
        assert row is not None and row.item.label == "tank spent: reserve 0 of 120 m/s"
        assert tu.earned_incapacity(_spent_tank(second_provider=False)) is None
        assert tu.earned_incapacity(_spent_tank(mode="SYNTHETIC")) is None


class TestTheModelIsGivenWhatTheSweepHolds:
    """Section 7.1: ACCESS, the legacy verdict, custody, data mode and the intercept's cost reach the model."""

    def _spy(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        assess, history_items = tu.assess, tu.history_items

        def spy_assess(items: Any, situation: tu.Situation, **kw: Any) -> ThreatUnderstanding:
            seen["situation"] = situation
            return assess(items, situation, **kw)

        def spy_history(signals: tu.HistorySignals, **kw: Any) -> tuple[tu.EvidenceItem, ...]:
            seen["history"] = kw
            return history_items(signals, **kw)

        monkeypatch.setattr(threat.tu, "assess", spy_assess)
        monkeypatch.setattr(threat.tu, "history_items", spy_history)
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        return seen

    def test_the_worst_case_custody_and_the_operators_element_set_reach_it(
            self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        degraded = CustodyStatus(Custody.DEGRADED, "Custody degraded.")
        context = threat.ConfidenceContext(data_mode="MANUAL", custody=Custody.DEGRADED, manual_confidence="MEDIUM")
        worst = {"dv": 7.5, "access_level": "HIGH", "threat_level": "MEDIUM", "capability_level": "MEDIUM"}
        red = threat._Red(_SATNO, "", "LEO", _held_history(_RAISES), degraded, context)
        assert threat._red_understanding(red, worst, _NOW) is not None
        situation = seen["situation"]
        assert (situation.now, situation.access, situation.legacy, situation.custody, situation.regime) == (
            _NOW, Band.HIGH, Band.MEDIUM, Custody.DEGRADED, "LEO")
        assert (situation.data_mode, situation.manual_confidence) == ("MANUAL", "MEDIUM")
        assert situation.burns
        # "No burns" is judged on the history's own window, not on the worst case's custody (section 5.3).
        history = red.history
        signals = tu.history_signals(history.pol, history.assessment)
        assert seen["history"] == {"access_delta_v_m_s": 7.5,
                                   "custody": tu.window_custody(signals, _NOW, threat.limit_hours_for_regime("LEO"))}

    def test_an_unassessed_capability_gives_the_model_no_legacy_verdict(
            self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        worst = {"dv": 9.0, "access_level": "CRITICAL", "threat_level": "CRITICAL", "capability_level": "UNASSESSED"}
        red = threat._Red(_SATNO, "", "GEO", _NO_HISTORY, _HELD, threat.ConfidenceContext())
        assert threat._red_understanding(red, worst, _NOW) is not None
        assert seen["situation"].legacy is None


class TestTheLiveSweepOnOneProvider:
    """The consequence of SPC-167 the owner is asked to rule on (concept section 9, decision 8).

    The sweep holds one merged history, so a tank it reads as spent rests on
    one provider's chain at q 0.34, below what earns Capability: decide-by
    stays, and the sentence says why.
    """

    def test_a_tank_spent_on_one_providers_history_keeps_decide_by(
            self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        history = _held_history([(40, 900.0)] * 5)
        context = threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD)
        worst = threat._compute_worst_coa([_sweep_entry()], threat._red_capability_from(_SATNO, history), 500.0,
                                          context)
        assert worst is not None and worst["capability_level"] == "MINIMAL"
        now = history.pol.records[-1].epoch + timedelta(hours=1)
        understanding = threat._red_understanding(
            threat._Red(_SATNO, "", "LEO", history, _HELD, context), worst, now)
        assert understanding is not None
        tank = next(r for r in understanding.range.ledger if r.item.label.startswith("tank spent"))
        assert (round(tank.q, 2), tank.applied) == (0.34, False)
        result = _decide(worst, understanding)
        assert result.due is Due.SET
        assert "but that has not earned a MINIMAL Threat ceiling (Capability not earned)" in result.sentence


class TestTheIncapacityIsNamed:
    def test_a_status_and_a_spent_tank_are_told_apart(self) -> None:
        access = AccessEvidence(best_delta_v_m_s=9.0, time_to_arrival_hours=31.0, method="lambert", regime="GEO")
        status = assess_threat(access, CapabilityEvidence(operational_status="Degraded"))
        tank = assess_threat(access, CapabilityEvidence(discretionary_remaining_m_s=0.0, discretionary_max_m_s=120.0))
        used = assess_threat(access, CapabilityEvidence(propellant_used_pct=97.0))
        able = assess_threat(access, CapabilityEvidence(intel_threat_level="HIGH"))
        assert status.incapacity == "the recorded status 'Degraded', declared, not observed"
        assert tank.incapacity == "a spent discretionary reserve, computed from its history"
        assert used.incapacity == "a spent tank, 97 per cent of the propellant load used, computed from its history"
        assert able.incapacity == ""
        # The verdict itself is the legacy one until SPC-175.
        assert (status.verdict, tank.verdict, used.verdict) == (Band.MINIMAL, Band.MINIMAL, Band.MINIMAL)

    def test_the_worst_case_carries_it(self) -> None:
        worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(operational_status="Degraded"))
        assert worst is not None and worst["incapacity"] == "the recorded status 'Degraded', declared, not observed"


# ── SPC-166: the model in shadow beside the legacy verdict, with a ledger hash ──

def _row(k: int) -> ThreatUnderstanding:
    """Row *k* of the worked example of section 4.12, from the adapters."""
    from tests.unit.test_threat_understanding_adapters import _UDL, _base, _rows

    return tu.assess(_rows()[k - 1], tu.with_history(_base(), _UDL) if k >= 3 else _base())


class TestTheLedgerHash:
    """I10: the same inputs give the same ledger and the same provenance hash."""

    def test_the_same_inputs_in_any_order_give_the_same_hash(self) -> None:
        from tests.unit.test_threat_understanding_adapters import _UDL, _base, _rows

        items, situation = _rows()[5], tu.with_history(_base(), _UDL)
        forward = tu.assess(items, situation).range.ledger
        backward = tu.assess(tuple(reversed(items)), situation).range.ledger
        assert ledger_input("ledger", forward) == ledger_input("ledger", backward)

    def test_different_evidence_gives_a_different_hash(self) -> None:
        assert ledger_input("ledger", _row(5).range.ledger).sha256 != ledger_input("ledger", _row(6).range.ledger).sha256

    @pytest.mark.parametrize("change", [
        lambda r: replace(r, q=r.q + 0.01),
        lambda r: replace(r, status=tu.Status.DECAYED if r.status is not tu.Status.DECAYED else tu.Status.COUNTED),
        lambda r: replace(r, applied=not r.applied),
        lambda r: replace(r, counted=not r.counted),
        lambda r: replace(r, note=r.note + " changed"),
        lambda r: replace(r, age_days=(r.age_days or 0.0) + 1.0),
        lambda r: replace(r, item=replace(r.item, extraction=r.item.extraction / 2)),
    ])
    def test_a_ledger_of_the_same_length_with_one_row_changed_gives_a_different_hash(
            self, change: Callable[[tu.LedgerRow], tu.LedgerRow]) -> None:
        ledger = _row(4).range.ledger
        for k in range(len(ledger)):
            changed = (*ledger[:k], change(ledger[k]), *ledger[k + 1:])
            assert len(changed) == len(ledger)
            assert ledger_input("ledger", changed).sha256 != ledger_input("ledger", ledger).sha256

    def test_the_hash_is_of_the_rows_only(self) -> None:
        ref = ledger_input("threat understanding ledger", _row(4).range.ledger)
        assert (ref.label, len(ref.sha256), ref.epoch) == ("threat understanding ledger", 64, None)


class TestTheThreatSentence:
    def test_a_narrow_range_reads_the_assessed_point_and_how_low_it_could_be(self) -> None:
        assert tu.threat_sentence(_row(4)) == "Threat: assessed CRITICAL. Threat could be as low as HIGH."

    def test_a_point_inside_the_range_says_both_ways(self) -> None:
        result = tu.assess(_rows_for_point(), _situation(legacy=Band.HIGH, access=Band.CRITICAL))
        assert tu.threat_sentence(result) == (
            "Threat: assessed HIGH. Threat could be as low as MEDIUM. Threat could be as high as CRITICAL.")

    def test_understanding_low_reads_the_access_ceiling(self) -> None:
        assert tu.threat_sentence(_row(3)) == "Threat: cannot assess beyond access (CRITICAL)."

    def test_a_ceiling_the_evidence_lowered_is_named_as_such(self) -> None:
        assert tu.threat_sentence(_spent_tank(mode="SYNTHETIC")) == (
            "Threat: cannot assess beyond the ceiling the evidence allows (MINIMAL).")

    def test_a_range_of_one_band_reads_the_point_alone(self) -> None:
        result = tu.assess(_rows_for_point(), _situation(legacy=Band.MEDIUM, access=Band.MEDIUM))
        assert tu.threat_sentence(result) == "Threat: assessed MEDIUM."

    @pytest.mark.parametrize(("floor", "ceiling", "text"), [
        (Band.HIGH, None, "Threat floor HIGH"), (None, Band.MEDIUM, "Threat ceiling MEDIUM"),
        (None, None, "coverage only"),
    ])
    def test_each_reading_is_labelled_threat(self, floor: Band | None, ceiling: Band | None, text: str) -> None:
        dimension = Dimension.CAPABILITY if ceiling is not None else Dimension.BEHAVIOUR
        item = tu.EvidenceItem(dimension=dimension, label="x", derived_from="y", source_grade="B", credibility=2,
                               extraction=0.9, basis=tu.Basis.COMPUTED, observed_at=None, floor_to=floor,
                               ceiling_to=ceiling)
        assert tu.reading_text(item) == text


def _rows_for_point() -> tuple[tu.EvidenceItem, ...]:
    """Behaviour earned on an unusual burn (floor MEDIUM), Identity earned, Capability partial."""
    burn = tu.BurnSignal(epoch=_BURN, normality=Normality.UNUSUAL, detection="HIGH", source="18SDS")
    udl = _udl(burns=(burn,), reserve_remaining_m_s=72.0, tank_spent=False)
    return (*tu.gcat_items({"Bus": "Luch"}, _NOW - timedelta(days=30), _SATNO),
            *tu.history_items(udl, access_delta_v_m_s=9.0, custody=Custody.HELD))


class TestTheShadowView:
    def test_it_carries_the_two_lines_the_strip_the_ledger_and_the_hash(self) -> None:
        understanding = _row(4)
        view = threat._understanding_view(understanding)
        assert view["threat"] == "Threat: assessed CRITICAL. Threat could be as low as HIGH."
        assert view["understanding"] == understanding.understanding.statement
        assert view["band"] == "critical"
        assert [(c["name"], c["depth"], c["fill"]) for c in view["strip"]] == [
            ("Identity", "earned", "full"), ("Capability", "partial", "half"), ("Manoeuvres", "earned", "full"),
            ("Interactions", "not earned", "empty")]
        assert view["strip"][0]["detail"] == (
            "GCAT entry: bus Luch, launched 2014 Sep 27, owner RVSN: B2, 30.0 d, lookup; "
            "intel record, role Inspector: C3, undated, lookup")
        assert view["ledger_hash"] == ledger_input("threat understanding ledger", understanding.range.ledger).sha256

    def test_each_ledger_row_says_what_it_is_and_what_became_of_it(self) -> None:
        rows = {r["claim"]: r for r in threat._understanding_view(_row(4))["ledger"]}
        burn = rows["latest burn, unprecedented"]
        assert burn == {"dimension": "Manoeuvres", "claim": "latest burn, unprecedented", "reading": "Threat floor HIGH",
                        "grade": "B2", "age": "1.4 d", "basis": "computed", "q": "0.60", "status": "counted",
                        "note": ""}
        anomaly = rows["anomaly index 90"]
        assert (anomaly["reading"], anomaly["status"], anomaly["basis"]) == ("Threat floor MEDIUM", "folded", "lookup")
        assert anomaly["note"] == (
            "an uncalibrated heuristic index; same source chain as latest burn, unprecedented; not counted again")
        assert rows["intel record, role Inspector"]["note"] == "undated, single open source"

    def test_a_declared_item_says_so_on_screen(self) -> None:
        items = (*tu.intel_items({"status": "Operational", "threat_level": "LOW", "source": "CSIS 2025",
                                  "assessed_at": "2026-09-01"}, _SATNO),
                 *tu.gcat_items({"Bus": "Luch"}, _NOW - timedelta(days=30), _SATNO))
        rows = {r["claim"]: r for r in threat._understanding_view(tu.assess(items, _situation()))["ledger"]}
        assert (rows["recorded status Operational"]["status"], rows["recorded status Operational"]["note"]) == (
            "counted", "declared, not observed")
        assert rows["GCAT entry: bus Luch"]["note"] == "declared fields: recorded, never move a band"

    def test_it_joins_the_worst_case_and_nothing_else_there_changes(self) -> None:
        worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(intel_threat_level="HIGH"))
        assert worst is not None
        before = dict(worst)
        joined = threat._with_understanding(worst, _row(4))
        assert joined is not None and joined.pop("understanding")["threat"].startswith("Threat:")
        assert joined == before
        assert threat._with_understanding(None, _row(4)) is None
        assert "understanding" not in (threat._with_understanding(dict(before), None) or {})


# ── All 20 bundled red objects: the legacy verdict does not move ──

_HRR = json.loads((Path(__file__).resolve().parents[2] / "spectre" / "data" / "hrr_default.json").read_text())
_RED = {o["satNo"]: o for o in _HRR[0]["msgBody"] if o["country"] in {"CHN", "RUS", "IRN", "PRK"}}
#: The legacy verdict at base 9296f9d, against a deliverable 9 m/s GEO intercept (ACCESS CRITICAL): each
#: object's assessed threat level, and MINIMAL for the two recorded Degraded.
_LEGACY = {
    "41838": "CRITICAL", "49330": "CRITICAL", "62485": "CRITICAL", "43874": "CRITICAL", "58204": "CRITICAL",
    "50321": "CRITICAL", "50322": "CRITICAL", "40892": "HIGH", "41911": "HIGH", "63157": "MEDIUM",
    "40258": "HIGH", "55841": "CRITICAL", "62188": "HIGH", "64467": "CRITICAL", "65563": "HIGH",
    "65590": "MEDIUM", "61769": "MINIMAL", "61768": "MINIMAL", "53370": "HIGH", "59065": "MEDIUM",
}


#: Each object's worst case at base 9296f9d, as the sha256 of its JSON (keys sorted), and its badge as rendered
#: there. Generated by running the base commit's own ``_compute_worst_coa`` and template.
_HIGH_DIGEST = "fd2dee3c949904de0a016fb1ff09621267d109ba5b2412cd74601c86959b5091"
_CRITICAL_DIGEST = "c4198a259e95b89dfb0915acab9ac5bd5e1d3d106f64d6eac7ef5aafe1ea82bb"
_MEDIUM_DIGEST = "76c57318ce40a8efba9bf3f6933a170df730f8a71e552a2ecc3df745d4479d27"
_MINIMAL_DIGEST = "ec2b5c694d480ac0674a09ab49f1c66aa7c9f6705582780b48fc3ed75d9cc78e"
_BASE_DIGEST = {"CRITICAL": _CRITICAL_DIGEST, "HIGH": _HIGH_DIGEST, "MEDIUM": _MEDIUM_DIGEST,
                "MINIMAL": _MINIMAL_DIGEST}
#: Keys this build adds to the worst case: neither existed at base.
_NEW_KEYS = frozenset({"understanding", "incapacity"})


def _base_badge(level: str) -> str:
    return f'<span class="spectre-band-badge spectre-band-{level.lower()}">&#9888; {level} THREAT</span>'


def _outlined_badge(level: str) -> str:
    return _base_badge(level).replace(f"spectre-band-{level.lower()}", f"spectre-band-{level.lower()} spectre-band-outline")


def _digest(worst: dict[str, Any]) -> str:
    plain = {k: v for k, v in worst.items() if k not in _NEW_KEYS}
    return hashlib.sha256(json.dumps(plain, sort_keys=True, default=str).encode()).hexdigest()


def _badge(worst: dict[str, Any]) -> str:
    from tests.unit.test_threat_sweep_template import _context, _render

    page = _render(_context(worst_coa=worst))
    start = page.index('<span class="spectre-band-badge')
    return page[start:page.index("</span>", start) + len("</span>")]


class TestTheTwentyBundledRedObjects:
    def test_the_pin_covers_all_twenty(self) -> None:
        assert sorted(_RED) == sorted(_LEGACY)
        assert len(_LEGACY) == 20

    @pytest.mark.parametrize("satno", sorted(_LEGACY))
    def test_the_legacy_verdict_badge_and_sentence_are_unchanged(self, satno: str) -> None:
        obj = _RED[satno]
        red_tle = f"{obj['line1']}\n{obj['line2']}"
        context = threat.ConfidenceContext(data_mode=obj["tleDataMode"], custody=Custody.HELD)
        worst = threat._compute_worst_coa([_sweep_entry()], threat._red_capability(satno), 500.0, context)
        assert worst is not None
        before = dict(worst)
        red = threat._Red(satno, red_tle, obj["orbitRegime"], _NO_HISTORY, _HELD, context)
        understanding = threat._red_understanding(red, worst, _NOW)
        assert understanding is not None
        shadowed = threat._with_understanding(dict(worst), understanding)
        assert shadowed is not None
        assert (before["access_level"], before["threat_level"]) == ("CRITICAL", _LEGACY[satno])
        assert {k: v for k, v in shadowed.items() if k != "understanding"} == before
        # The verdict word and band are the legacy ones. Understanding LOW outlines the badge (SPC-168), no
        # more; with no Understanding computed it is outlined too, because the fill is earned.
        assert _badge(before).replace(" spectre-band-outline", "") == _base_badge(_LEGACY[satno])
        assert _badge(before) == _badge(shadowed) == _outlined_badge(_LEGACY[satno])
        assert _digest(shadowed) == _BASE_DIGEST[_LEGACY[satno]]
        # Every bundled set is SYNTHETIC, so the shadow reads Understanding LOW and the access ceiling.
        assert understanding.understanding.level is tu.Understanding.LOW
        assert shadowed["understanding"]["threat"] == "Threat: cannot assess beyond access (CRITICAL)."

    def test_a_model_failure_leaves_the_sweep_standing_and_stays_in_the_log(
            self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("internal detail\nforged line")

        monkeypatch.setattr(threat.tu, "assess", broken)
        worst = threat._compute_worst_coa([_sweep_entry()], threat._red_capability("40258"))
        red = threat._Red("40258", "", "GEO", _NO_HISTORY, _HELD, threat.ConfidenceContext())
        with caplog.at_level("WARNING", logger=threat.logger.name):
            assert threat._red_understanding(red, worst, _NOW) is None
        (record,) = [r for r in caplog.records if "Threat Understanding" in r.getMessage()]
        assert "\nforged line" not in record.getMessage()

    def test_no_worst_case_means_no_understanding(self) -> None:
        red = threat._Red("40258", "", "GEO", _NO_HISTORY, _HELD, threat.ConfidenceContext())
        assert threat._red_understanding(red, None, _NOW) is None


# ── The rendered section: section 6.4 and I13 ──

_BANDS = re.compile(r"\b(MINIMAL|LOW|MEDIUM|HIGH|CRITICAL|MODERATE)\b")


def _section(worst: dict[str, Any]) -> str:
    from tests.unit.test_threat_sweep_template import _context, _render

    page = _render(_context(worst_coa=worst))
    start = page.index('<section class="threat-understanding"')
    return page[start:page.index("</section>", start)]


def _text(fragment: str) -> list[str]:
    """The section's text, one entry per cell or sentence, tags and entities gone."""
    plain = html.unescape(re.sub(r"<[^>]+>", "\n", fragment))
    return [s.strip() for line in plain.splitlines() for s in re.split(r"(?<=\.)\s+", line) if s.strip()]


def _shadowed(k: int) -> dict[str, Any]:
    worst = threat._compute_worst_coa([_sweep_entry()], CapabilityEvidence(intel_threat_level="CRITICAL"))
    assert worst is not None
    shadowed = threat._with_understanding(worst, _row(k))
    assert shadowed is not None
    return shadowed


class TestTheRenderedSection:
    @pytest.mark.parametrize("k", [1, 3, 4, 6])
    def test_no_bare_band_no_shared_sentence_and_no_percentage(self, k: int) -> None:
        section = _section(_shadowed(k))
        # What the operator reads: the text and the tooltips, not the style sheet's widths.
        read = " ".join([*_text(section), *re.findall(r'title="([^"]*)"', section)])
        assert "%" not in read and "per cent" not in read
        for sentence in _text(section):
            assert not ("Threat" in sentence and "Understanding" in sentence), sentence
            for match in _BANDS.finditer(sentence):
                before = sentence[:match.start()]
                assert "Threat" in before or "Understanding" in before, sentence

    def test_the_threat_line_comes_first_then_the_understanding_line(self) -> None:
        lines = _text(_section(_shadowed(4)))
        threat_at = lines.index("Threat: assessed CRITICAL.")
        understanding_at = next(i for i, s in enumerate(lines) if s.startswith("Understanding MODERATE."))
        assert threat_at < understanding_at

    def test_the_ledger_is_collapsed_by_default_and_carries_its_hash(self) -> None:
        section = _section(_shadowed(4))
        details = re.search(r"<details[^>]*>", section)
        assert details is not None and "open" not in details.group(0)
        assert "What it rests on (5 items)" in section
        assert ledger_input("threat understanding ledger", _row(4).range.ledger).sha256[:16] in section

    def test_band_colours_come_from_the_status_tokens(self) -> None:
        assert "var(--spectre-status-critical)" in _section(_shadowed(4))

    def test_without_it_the_page_renders_as_before(self) -> None:
        from tests.unit.test_threat_sweep_template import _context, _render

        assert 'class="threat-understanding"' not in _render(_context())


# ── SPC-172: the warning change the sweep flies becomes Interactions evidence ──

def _basis(now: datetime, *, regime: str = "LEO") -> Any:
    return threat._SweepBasis(targets=[], manual_tle_by_name={}, frozen=threat._FrozenTargets({}), red_regime=regime,
                              max_dv_m_s=500.0, blue_satnos=frozenset(), now=now)


def _figures(*rows: TargetWarning) -> WarningChange:
    return WarningChange(WarningStatus.FIGURES, "That burn put BLUE-1 in reach with 3h warning.", rows=rows)


_IN_REACH = TargetWarning("BLUE-1", True, None, 3.0, Change.NEWLY_IN_REACH)
_ALL_CRITICAL = {"dv": 120.0, "access_level": "CRITICAL", "threat_level": "CRITICAL", "capability_level": "CRITICAL"}


def _after_raises() -> tuple[threat._RedHistory, datetime]:
    history = _held_history(_RAISES)
    return history, history.pol.records[-1].epoch + timedelta(hours=1)


class TestTheSweepReadsInteractionsFromItsWarningChange:
    def test_a_burn_that_put_one_of_ours_in_reach_is_an_edge_resting_on_the_flown_burns(self) -> None:
        history, now = _after_raises()
        flown = threat._window_burns(history.pol, _basis(now))
        assert flown
        (edge,) = threat._interactions(_figures(_IN_REACH), history, _basis(now), _SATNO)
        assert (edge.actor, edge.target, edge.ours, edge.approach_at) == (_SATNO, "BLUE-1", True, now)
        assert [(b.epoch, b.earliest, b.latest, b.detection, b.provider, b.long_gap, b.confirmed)
                for b in edge.burns] == [
            (m.burn_epoch, *m.burn_window, str(m.confidence), "18SDS", m.long_gap, True) for m in flown]

    @pytest.mark.parametrize("change", [
        WarningChange(WarningStatus.NO_BURN, "No confirmed burn in its element sets."),
        WarningChange(WarningStatus.NOT_COMPUTED, "What the burn changed is not shown: custody is lost."),
        WarningChange(WarningStatus.CANNOT_SAY, "What the burn changed: cannot say."),
    ])
    def test_no_figures_no_edge(self, change: WarningChange) -> None:
        history, now = _after_raises()
        assert threat._interactions(change, history, _basis(now), _SATNO) == ()

    def test_each_flown_burn_maps_onto_the_edge_rule_field_by_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every burn in the window, its own detection, gap and after-burn provider: nothing read as a constant."""
        history, now = _after_raises()

        def flown(epoch: datetime, confidence: str, long_gap: bool, before: str, after: str) -> Any:
            return SimpleNamespace(burn_epoch=epoch, burn_window=(epoch - timedelta(hours=2), epoch),
                                   confidence=confidence, long_gap=long_gap,
                                   tle_before=SimpleNamespace(source=before), tle_after=SimpleNamespace(source=after))

        first = flown(now - timedelta(hours=10), "MODERATE", True, "18SDS", "LEO LABS")
        second = flown(now - timedelta(hours=4), "HIGH", False, "LEO LABS", "18 SDS")
        monkeypatch.setattr(threat, "_window_burns", lambda _pol, _basis: [first, second])
        (edge,) = threat._interactions(_figures(_IN_REACH), history, _basis(now), _SATNO)
        assert [(b.epoch, b.earliest, b.latest, b.detection, b.provider, b.long_gap) for b in edge.burns] == [
            (first.burn_epoch, *first.burn_window, "MODERATE", "LEOLABS", True),
            (second.burn_epoch, *second.burn_window, "HIGH", "18SDS", False),
        ]
        (item,) = tu.interaction_items((edge,))
        # The weakest burn governs: MODERATE, halved for its long gap, so it cannot earn the dimension alone.
        assert (item.extraction, item.source_grade) == (0.3, "C")

    @pytest.mark.parametrize("change", [
        WarningChange(WarningStatus.NOT_COMPUTED, "What the burn changed is not shown: custody is lost.",
                      rows=(_IN_REACH,)),
        WarningChange(WarningStatus.CANNOT_SAY, "What the burn changed: cannot say.", rows=(_IN_REACH,)),
    ])
    def test_rows_without_figures_make_no_edge(self, change: WarningChange,
                                               caplog: pytest.LogCaptureFixture) -> None:
        """Only figures the operator was shown carry an approach, whatever rows a refusal holds."""
        history, now = _after_raises()
        with caplog.at_level("WARNING", logger=threat.logger.name):
            assert threat._interactions(change, history, _basis(now), _SATNO) == ()
        assert caplog.records == []

    def test_no_history_is_refused_before_it_is_read(self, caplog: pytest.LogCaptureFixture) -> None:
        """No held history is no approach, said by the guard, not by a failure swallowed in the log."""
        _history, now = _after_raises()
        with caplog.at_level("WARNING", logger=threat.logger.name):
            assert threat._interactions(_figures(_IN_REACH), _NO_HISTORY, _basis(now), _SATNO) == ()
        assert caplog.records == []

    def test_no_history_or_no_number_no_edge(self) -> None:
        history, now = _after_raises()
        assert threat._interactions(_figures(_IN_REACH), _NO_HISTORY, _basis(now), _SATNO) == ()
        assert threat._interactions(_figures(_IN_REACH), history, _basis(now), None) == ()

    def test_the_model_is_given_the_edges(self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        history, now = _after_raises()
        edges = threat._interactions(_figures(_IN_REACH), history, _basis(now), _SATNO)
        context = threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD)
        understanding = threat._red_understanding(
            threat._Red(_SATNO, "", "LEO", history, _HELD, context, edges), _ALL_CRITICAL, now)
        assert understanding is not None
        (row,) = [r for r in understanding.range.ledger if r.item.dimension is Dimension.INTERACTIONS]
        assert row.item.label == "BLUE-1 put in reach by its burn, 3h warning"
        assert row.item.derived_from == f"approach:{_SATNO}:18SDS"

    def test_without_edges_the_model_holds_no_interaction(self, cache: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(threat, "get_intel", lambda _s: None)
        history, now = _after_raises()
        context = threat.ConfidenceContext(data_mode="REAL", custody=Custody.HELD)
        understanding = threat._red_understanding(
            threat._Red(_SATNO, "", "LEO", history, _HELD, context), _ALL_CRITICAL, now)
        assert understanding is not None
        assert not [r for r in understanding.range.ledger if r.item.dimension is Dimension.INTERACTIONS]

    def test_a_failure_reading_them_leaves_the_sweep_standing_and_stays_in_the_log(
            self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("internal detail\nforged line")

        monkeypatch.setattr(threat.ig, "warning_edges", broken)
        history, now = _after_raises()
        with caplog.at_level("WARNING", logger=threat.logger.name):
            assert threat._interactions(_figures(_IN_REACH), history, _basis(now), _SATNO) == ()
        (record,) = [r for r in caplog.records if "Interactions" in r.getMessage()]
        assert "\nforged line" not in record.getMessage()
