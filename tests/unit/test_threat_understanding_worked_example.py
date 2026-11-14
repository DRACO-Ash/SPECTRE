"""The worked example of section 4.12 of docs/threat_confidence_concept.md, row by row.

RED-GEO-1 is a fictional GEO inspector modelled on public reporting of
Luch/Olymp-K. At 3 November 2026, 12:00Z, the sweep finds a deliverable
approach to BLUE-COMSAT: ACCESS is CRITICAL, custody HELD, data REAL. Each
row adds one piece of evidence; the range narrows from 5 bands to 2 and the
assessed point never moves. Then contrasts A (a feigned status), B (a
routine burn) and C (the measured false HIGH).

Every figure below is the concept's, to two places. One differs: row 8's
Identity coverage is 0.66, not the 0.67 the concept prints (0.67 is row 2's
value carried down; the GCAT entry has aged 9 more days).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import (
    Dimension,
    EvidenceItem,
    HeldBurn,
    Situation,
    Status,
    ThreatUnderstanding,
    Understanding,
)

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)
_ROW8 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
_SIX_HOURS = timedelta(hours=6)

_INTEL = EvidenceItem(
    dimension=Dimension.IDENTITY, label="intel record, role assessed", derived_from="intel-record:RED-GEO-1",
    source_grade="C", credibility=3, extraction=tu.ASSESSED_LABEL_EXTRACTION, basis=Basis.LOOKUP,
    observed_at=None, floor_to=Band.MEDIUM)
_GCAT = EvidenceItem(
    dimension=Dimension.IDENTITY, label="GCAT entry", derived_from="gcat:RED-GEO-1", source_grade="B",
    credibility=2, extraction=tu.CATALOGUE_FIELD_EXTRACTION, basis=Basis.LOOKUP,
    observed_at=_NOW - timedelta(days=30))
_UDL_RESERVE = EvidenceItem(
    dimension=Dimension.CAPABILITY, label="UDL history: reserve 72 of 120 m/s", derived_from="elset-history:UDL",
    source_grade="B", credibility=2, extraction=tu.ASSUMED_FIGURE_EXTRACTION, basis=Basis.COMPUTED,
    observed_at=_NOW - _SIX_HOURS, controlled=True)
_UDL_BURN = EvidenceItem(
    dimension=Dimension.BEHAVIOUR, label="latest burn, unprecedented", derived_from="elset-history:UDL",
    source_grade="B", credibility=2, extraction=tu.burn_extraction("HIGH"), basis=Basis.COMPUTED,
    observed_at=_BURN, floor_to=Band.HIGH, controlled=True)
_ALLIED = EvidenceItem(
    dimension=Dimension.BEHAVIOUR, label="allied optical track confirms the burn", derived_from="allied:optical",
    source_grade="A", credibility=1, extraction=tu.burn_extraction("HIGH"), basis=Basis.COMPUTED,
    observed_at=_NOW - timedelta(hours=24), floor_to=Band.HIGH, controlled=True)
_COMMERCIAL = EvidenceItem(
    dimension=Dimension.CAPABILITY, label="commercial history: reserve share 0.55",
    derived_from="elset-history:COMMERCIAL", source_grade="C", credibility=2,
    extraction=tu.ASSUMED_FIGURE_EXTRACTION, basis=Basis.COMPUTED, observed_at=_NOW)
_WARNING = EvidenceItem(
    dimension=Dimension.INTERACTIONS, label="newly in reach of BLUE-COMSAT after the burn",
    derived_from="approach:RED-GEO-1:BLUE-COMSAT", source_grade="B", credibility=2,
    extraction=tu.burn_extraction("HIGH"), basis=Basis.COMPUTED, observed_at=_BURN, floor_to=Band.HIGH,
    controlled=True)

_ROWS = (_INTEL, _GCAT, _UDL_RESERVE, _UDL_BURN, _ALLIED, _COMMERCIAL, _WARNING)
_HISTORY_HELD_FROM_ROW = 3


def _situation(row: int, **kw: object) -> Situation:
    args: dict[str, object] = {
        "now": _NOW, "access": Band.CRITICAL, "legacy": Band.CRITICAL, "regime": "GEO", "data_mode": "REAL",
        "custody": Custody.HELD, "history_truncated": False,
        "newest_elset_at": _NOW - _SIX_HOURS,
        "burns": (HeldBurn(_BURN, Normality.UNPRECEDENTED),) if row >= _HISTORY_HELD_FROM_ROW else (),
    }
    args.update(kw)
    return Situation(**args)  # type: ignore[arg-type]


def _at_row(row: int) -> ThreatUnderstanding:
    return tu.assess(_ROWS[:row], _situation(row))


def _cover(result: ThreatUnderstanding) -> tuple[float, ...]:
    c = result.range.coverage
    return tuple(round(c[d], 2) for d in (Dimension.IDENTITY, Dimension.CAPABILITY, Dimension.BEHAVIOUR,
                                          Dimension.INTERACTIONS))


#: Row: (q of the item added, coverage I C B X, floor, ceiling, Understanding, governing categories).
_EXPECTED = {
    0: (None, (0, 0, 0, 0), Band.MINIMAL, Band.CRITICAL, Understanding.LOW, ("information base",)),
    1: (0.09, (0.09, 0, 0, 0), Band.MINIMAL, Band.CRITICAL, Understanding.LOW, ("information base",)),
    2: (0.64, (0.67, 0, 0, 0), Band.MINIMAL, Band.CRITICAL, Understanding.LOW, ("information base",)),
    3: (0.34, (0.67, 0.34, 0, 0), Band.MINIMAL, Band.CRITICAL, Understanding.LOW, ("information base",)),
    4: (0.60, (0.67, 0.34, 0.60, 0), Band.HIGH, Band.CRITICAL, Understanding.MODERATE,
        ("information base", "volatility")),
    5: (0.80, (0.67, 0.34, 0.92, 0), Band.HIGH, Band.CRITICAL, Understanding.MODERATE,
        ("information base", "volatility")),
    # 0.6 x 0.85 x 0.5 x 1.0 is 0.255 exactly; the concept prints it rounded half up.
    6: (0.255, (0.67, 0.51, 0.92, 0), Band.HIGH, Band.CRITICAL, Understanding.MODERATE, ("volatility",)),
    7: (0.59, (0.67, 0.51, 0.92, 0.59), Band.HIGH, Band.CRITICAL, Understanding.MODERATE, ("volatility",)),
}


class TestTheWorkedExample:
    @pytest.mark.parametrize("row", sorted(_EXPECTED))
    def test_each_row(self, row: int) -> None:
        q, cover, floor, ceiling, level, governing = _EXPECTED[row]
        result = _at_row(row)
        if q is not None:
            added = next(r for r in result.range.ledger if r.item == _ROWS[row - 1])
            assert added.q == pytest.approx(q, abs=0.005)
        assert _cover(result) == pytest.approx(cover)
        assert (result.range.floor, result.range.ceiling) == (floor, ceiling)
        assert (result.understanding.level, result.understanding.governing) == (level, governing)
        # More understanding narrowed the range. It never inflated the threat.
        assert result.verdict.assessed is Band.CRITICAL
        assert result.verdict.band is Band.CRITICAL

    def test_row_1_is_listed_below_threshold(self) -> None:
        row = next(r for r in _at_row(1).range.ledger if r.item is _INTEL)
        assert (row.status, row.applied, row.note) == (Status.BELOW_THRESHOLD, False,
                                                       "q 0.09 below 0.25; Identity not earned")

    def test_rows_0_to_3_read_the_ceiling_and_rows_4_on_the_assessed_point(self) -> None:
        assert [_at_row(r).verdict.at_ceiling for r in range(8)] == [True] * 4 + [False] * 4
        assert [_at_row(r).range.bands for r in (0, 4)] == [5, 2]

    def test_row_4_reads_moderate_and_says_why(self) -> None:
        rating = _at_row(4).understanding
        assert (rating.information_base, rating.rigour, rating.volatility) == (
            Understanding.MODERATE, Understanding.HIGH, Understanding.MODERATE)
        assert rating.statement == (
            "Understanding MODERATE. Governing: information base, Capability partial; volatility, "
            "an unprecedented burn 1.4 d ago whose new orbit is not yet settled.")

    def test_row_8_custody_held_for_9_days_after_the_burn_reads_high(self) -> None:
        # The element-set histories are refreshed (newest set 6 hours old); the burn,
        # the allied track and the warning change have aged 9 more days.
        refreshed = (_INTEL, _GCAT, replace(_UDL_RESERVE, observed_at=_ROW8 - _SIX_HOURS), _UDL_BURN, _ALLIED,
                     replace(_COMMERCIAL, observed_at=_ROW8), _WARNING)
        result = tu.assess(refreshed, _situation(8, now=_ROW8, newest_elset_at=_ROW8 - _SIX_HOURS))
        q = {r.item.label: round(r.q, 2) for r in result.range.ledger}
        assert (q[_UDL_BURN.label], q[_ALLIED.label], q[_WARNING.label], q[_GCAT.label]) == (0.54, 0.72, 0.48, 0.63)
        assert _cover(result) == pytest.approx((0.66, 0.51, 0.87, 0.48))
        assert (result.range.floor, result.range.ceiling) == (Band.HIGH, Band.CRITICAL)
        assert result.understanding.level is Understanding.HIGH
        # Interactions has decayed below earned, but suspicion persists until a later burn is judged.
        assert result.range.reobserve == (_WARNING.label,)


class TestTheContrasts:
    def test_a_a_feigned_status_is_voided_and_named(self) -> None:
        status = EvidenceItem(
            dimension=Dimension.CAPABILITY, label="intel status Degraded", derived_from="status:RED-GEO-1",
            source_grade="D", credibility=3, extraction=tu.ASSESSED_LABEL_EXTRACTION, basis=Basis.LOOKUP,
            observed_at=None, ceiling_to=Band.MINIMAL, manufacturable=True, impaired_status=True)
        result = tu.assess((*_ROWS[:4], status), _situation(4))
        assert result.range.possible_deception == ("intel status Degraded",)
        assert (result.range.floor, result.range.ceiling) == (Band.HIGH, Band.CRITICAL)
        assert result.understanding.level is Understanding.MODERATE
        assert "possible deception, intel status Degraded" in dict(result.understanding.reasons)["volatility"]

    def test_b_a_routine_burn_earns_behaviour_but_moves_nothing(self) -> None:
        routine = replace(_UDL_BURN, label="latest burn, routine", floor_to=None, routine=True)
        result = tu.assess((*_ROWS[:3], routine), _situation(4, burns=(HeldBurn(_BURN, Normality.ROUTINE),)))
        assert next(r.q for r in result.range.ledger if r.item is routine) == tu.ROUTINE_CAP
        assert _cover(result)[2] == 0.5
        assert (result.range.floor, result.range.ceiling, result.range.bands) == (Band.MINIMAL, Band.CRITICAL, 5)
        assert (result.verdict.band, result.verdict.at_ceiling) == (Band.CRITICAL, True)
        assert result.understanding.level is Understanding.MODERATE

    def test_c_the_measured_false_high_reads_understanding_low_and_the_access_ceiling(self) -> None:
        quiet = EvidenceItem(
            dimension=Dimension.BEHAVIOUR, label="no burns in 400 days", derived_from="elset-history:UDL",
            source_grade="B", credibility=2, extraction=0.5, basis=Basis.COMPUTED,
            observed_at=_NOW - _SIX_HOURS, routine=True, controlled=True)
        result = tu.assess((_UDL_RESERVE, quiet), _situation(0, legacy=Band.HIGH))
        assert _cover(result) == pytest.approx((0, 0.34, 0.34, 0))
        assert (result.range.floor, result.range.ceiling) == (Band.MINIMAL, Band.CRITICAL)
        assert result.understanding.level is Understanding.LOW
        assert result.verdict.band is Band.CRITICAL
