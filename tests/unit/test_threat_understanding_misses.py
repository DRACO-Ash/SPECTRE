"""Threat Understanding, SPC-173: a close approach after a burn becomes Interactions evidence.

Concept section 4.6 and 5.4: an attributable closest approach under 50 km
reads floor MEDIUM. A computed one is graded as a warning change is, by the
provider's grade and the burn's detection grade, and shares its source chain
(the burns it rests on), so the two count once. A UDL conjunction reads the
same rule but is a probe: its field names are inferred and unverified
(SPC-033) and its originator is not read, so it is graded C3 with half
extraction, below what a reading needs, and the ledger says why.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.interaction_graph import Burn, Miss, MissEdge, MissSource, miss_edges, warning_edges
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Dimension, HeldBurn, Situation, Status
from spectre.domain.warning_change import TargetWarning, classify
from spectre.web.understanding_view import ledger_view
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)
_TCA = _BURN + timedelta(hours=20)


def _burn(*, detection: str = "HIGH", provider: str = "18SDS") -> Burn:
    return Burn(epoch=_BURN, earliest=_BURN, latest=_BURN, confirmed=True, detection=detection, provider=provider)


def _edge(source: MissSource = MissSource.COMPUTED, *, ours: bool = True, burn: Burn | None = None,
          target: str = "BLUE-COMSAT") -> MissEdge:
    miss = Miss(target=target, target_satno="40000", ours=ours, source=source, tca=_TCA, after_km=12.0,
                before_km=140.0, before_at=_BURN - timedelta(days=1))
    (edge,), _ = miss_edges("RED-GEO-1", [miss], [burn or _burn()])
    return edge


def _situation(**kw: object) -> Situation:
    args: dict[str, object] = {"now": _NOW, "access": Band.CRITICAL, "legacy": Band.CRITICAL, "regime": "GEO",
                               "data_mode": "REAL", "custody": Custody.HELD, "history_truncated": False,
                               "burns": (HeldBurn(_BURN, Normality.UNPRECEDENTED),)}
    args.update(kw)
    return Situation(**args)  # type: ignore[arg-type]


class TestAComputedClosestApproach:
    def test_it_reads_floor_medium_graded_by_its_provider_and_burn(self) -> None:
        (item,) = tu.interaction_items([_edge()])
        assert (item.dimension, item.floor_to, item.basis, item.grade, item.extraction) == (
            Dimension.INTERACTIONS, Band.MEDIUM, Basis.COMPUTED, "B2", 0.9)
        assert (item.observed_at, item.derived_from, item.controlled) == (_BURN, "approach:RED-GEO-1:18SDS", True)
        assert item.label == "closest approach to BLUE-COMSAT 12.0 km after its burn, 140.0 km before"
        assert item.note == "one of yours: a confirmed burn within 7 days brought it closer than before"

    def test_it_raises_the_floor_to_medium_once_interactions_is_earned(self) -> None:
        result = tu.assess(tu.interaction_items([_edge()]), _situation())
        assert result.range.floor is Band.MEDIUM
        (row,) = result.range.ledger
        assert (row.status, row.applied) == (Status.COUNTED, True)

    def test_a_target_not_ours_still_reads_section_4_6_does_not_restrict_it(self) -> None:
        (item,) = tu.interaction_items([_edge(ours=False)])
        assert item.floor_to is Band.MEDIUM
        assert item.note == "not one of yours: a confirmed burn within 7 days brought it closer than before"

    def test_resting_only_on_routine_burns_it_is_coverage_only(self) -> None:
        (item,) = tu.interaction_items([_edge()], judged=(HeldBurn(_BURN, Normality.ROUTINE),))
        assert (item.floor_to, item.routine) == (None, True)
        assert item.note == "every burn it rests on was judged routine: coverage only"

    def test_it_shares_the_warning_changes_source_chain_so_the_stronger_reading_counts_once(self) -> None:
        row = TargetWarning("BLUE-COMSAT", True, None, 31.0, classify(None, 31.0))
        warning = warning_edges("RED-GEO-1", [row], [_burn()], _NOW)
        result = tu.assess(tu.interaction_items([*warning, _edge()]), _situation())
        assert result.range.floor is Band.HIGH
        assert sorted(r.status.value for r in result.range.ledger) == ["counted", "folded"]


class TestAUdlConjunctionIsAProbe:
    def test_it_is_graded_c3_at_half_extraction_and_says_why(self) -> None:
        (item,) = tu.interaction_items([_edge(MissSource.UDL)])
        assert (item.grade, item.extraction, item.basis, item.floor_to) == ("C3", 0.5, Basis.LOOKUP, Band.MEDIUM)
        assert (item.derived_from, item.controlled) == ("conjunction:RED-GEO-1", False)
        assert item.label == "UDL conjunction with BLUE-COMSAT 12.0 km after its burn, 140.0 km before"
        assert item.note == ("one of yours; a UDL conjunction probe: its field names are inferred and unverified "
                             "(SPC-033), so it is graded as a probe")

    def test_alone_it_cannot_move_a_band_even_with_interactions_earned(self) -> None:
        row = TargetWarning("OTHER-1", False, None, 31.0, classify(None, 31.0))
        earned = warning_edges("RED-GEO-1", [row], [_burn()], _NOW)
        result = tu.assess(tu.interaction_items([*earned, _edge(MissSource.UDL)]), _situation())
        assert tu.depth(result.range.coverage[Dimension.INTERACTIONS]) is tu.Depth.EARNED
        assert result.range.floor is Band.MINIMAL
        (udl,) = [r for r in result.range.ledger if r.item.derived_from.startswith("conjunction:")]
        # C3 at half extraction is 0.18 fresh; the burn is a day and a half old here.
        assert (udl.status, round(udl.q, 2)) == (Status.BELOW_THRESHOLD, 0.17)

    def test_a_weaker_burn_provider_than_c_governs(self) -> None:
        (item,) = tu.interaction_items([_edge(MissSource.UDL, burn=_burn(provider="OPERATOR"))],
                                       {**tu.PROVIDER_GRADES, "OPERATOR": "D"})
        assert item.grade == "D3"

    def test_a_weaker_burn_detection_than_the_probe_governs(self) -> None:
        (item,) = tu.interaction_items([_edge(MissSource.UDL, burn=_burn(detection="LOW"))])
        assert item.extraction == 0.3

    def test_several_conjunctions_from_one_lookup_count_once(self) -> None:
        items = tu.interaction_items([_edge(MissSource.UDL), _edge(MissSource.UDL, target="OTHER-2")])
        assert {i.derived_from for i in items} == {"conjunction:RED-GEO-1"}


class TestTheWordsPassI13:
    @pytest.mark.parametrize("edge", [_edge(), _edge(ours=False), _edge(MissSource.UDL),
                                      _edge(MissSource.UDL, ours=False)])
    def test_the_ledger_row(self, edge: MissEdge) -> None:
        for row in tu.assess(tu.interaction_items([edge]), _situation()).range.ledger:
            for text in ledger_view(row).values():
                assert i13_problems(text) == [], text

    def test_the_routine_row(self) -> None:
        items = tu.interaction_items([_edge()], judged=(HeldBurn(_BURN, Normality.ROUTINE),))
        for row in tu.assess(items, _situation(burns=())).range.ledger:
            for text in ledger_view(row).values():
                assert i13_problems(text) == [], text
