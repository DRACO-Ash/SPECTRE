"""Threat Understanding, SPC-172: a manoeuvre-attributable approach becomes Interactions evidence.

Concept section 5.4: a warning change caused by a burn, NEWLY_IN_REACH or
CUT against one of ours, reads floor HIGH. Its reliability is the provider's
grade times the burn's detection grade, it ages with a 30-day half-life
from the last burn it rests on, and it is a reading only once Interactions
is earned, as any reading is (section 4.6). One resting only on ROUTINE
burns is coverage only (I9). The edge rule itself is
``domain/interaction_graph.py``'s, tested in test_interaction_graph.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import threat_understanding as tu
from spectre.domain.custody import Custody
from spectre.domain.interaction_graph import Burn, Edge, warning_edges
from spectre.domain.normality import Normality
from spectre.domain.provenance import Basis
from spectre.domain.threat_assessment import Band
from spectre.domain.threat_understanding import Dimension, HeldBurn, Situation, Status
from spectre.domain.warning_change import TargetWarning, classify
from spectre.web.format_units import format_tof_label
from spectre.web.understanding_view import HeldObject, ledger_view
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)


def _burn(epoch: datetime = _BURN, *, detection: str = "HIGH", provider: str = "18SDS",
          long_gap: bool = False) -> Burn:
    return Burn(epoch=epoch, earliest=epoch, latest=epoch, confirmed=True, detection=detection, provider=provider,
                long_gap=long_gap)


def _row(name: str = "BLUE-COMSAT", before: float | None = None, after: float | None = 31.0, *,
         ours: bool = True) -> TargetWarning:
    return TargetWarning(name, ours, before, after, classify(before, after))


def _edges(rows: list[TargetWarning] | None = None, burns: list[Burn] | None = None) -> tuple[Edge, ...]:
    return warning_edges("RED-GEO-1", rows or [_row()], [_burn()] if burns is None else burns, _NOW)


def _items(rows: list[TargetWarning] | None = None, burns: list[Burn] | None = None,
           grades: dict[str, str] | None = None) -> tuple[tu.EvidenceItem, ...]:
    edges = _edges(rows, burns)
    return tu.interaction_items(edges) if grades is None else tu.interaction_items(edges, grades)


def _situation(**kw: object) -> Situation:
    args: dict[str, object] = {"now": _NOW, "access": Band.CRITICAL, "legacy": Band.CRITICAL, "regime": "GEO",
                               "data_mode": "REAL", "custody": Custody.HELD, "history_truncated": False,
                               "burns": (HeldBurn(_BURN, Normality.UNPRECEDENTED),)}
    args.update(kw)
    return Situation(**args)  # type: ignore[arg-type]


class TestTheItem:
    def test_an_approach_to_one_of_ours_after_a_burn(self) -> None:
        (item,) = _items()
        assert (item.dimension, item.floor_to, item.ceiling_to, item.basis) == (
            Dimension.INTERACTIONS, Band.HIGH, None, Basis.COMPUTED)
        # Provider grade times burn grade (section 5.4): the 18 SDS catalogue is B, a provider's own fit 2.
        assert (item.grade, item.extraction, item.observed_at, item.controlled) == ("B2", 0.9, _BURN, True)
        assert item.label == "BLUE-COMSAT put in reach by its burn, 1.3 d warning"
        assert not item.manufacturable

    def test_a_cut_names_its_size_and_the_warning_before_and_after(self) -> None:
        (item,) = _items([_row(before=14.0, after=3.0)])
        assert item.label == "warning on BLUE-COMSAT cut 11.0 h by its burn, 14.0 h to 3.0 h"

    def test_a_cut_the_figures_round_away_still_says_how_much(self) -> None:
        """Past a day the operator's format drops the minutes, so the size of the cut is always stated."""
        (item,) = tu.interaction_items(_edges([_row("BLUE-1", before=30.8, after=30.5)]), hours=format_tof_label)
        assert item.label == "warning on BLUE-1 cut 18m by its burn, 1d 6h to 1d 6h"

    def test_the_panel_writes_hours_as_the_warning_section_does(self) -> None:
        held = HeldObject("RED-GEO-1", None, None, None, Custody.HELD,
                          interactions=_edges([_row("BLUE-1", before=14.0, after=3.0)]))
        (item,) = held.items(_NOW, "GEO")
        assert item.label == "warning on BLUE-1 cut 11h by its burn, 14h to 3h"


class TestNewlyInReachAfterABurnRaisesTheFloorToHigh:
    def test_the_floor_is_high(self) -> None:
        result = tu.assess(_items(), _situation())
        assert (result.range.floor, result.range.ceiling) == (Band.HIGH, Band.CRITICAL)
        (row,) = result.range.ledger
        assert (row.status, row.applied, round(row.q, 2)) == (Status.COUNTED, True, 0.59)
        assert tu.depth(result.range.coverage[Dimension.INTERACTIONS]) is tu.Depth.EARNED

    def test_a_pass_with_no_prior_burn_adds_nothing(self) -> None:
        bare = tu.assess((), _situation())
        passed = tu.assess(_items(burns=[]), _situation())
        assert passed.range == bare.range
        assert "no approaches or conjunctions held" in tu.missing(passed.range)

    def test_a_held_approach_is_no_longer_named_missing(self) -> None:
        assert "no approaches or conjunctions held" not in tu.missing(tu.assess(_items(), _situation()).range)


class TestOneApproachMustEarnItsDimension:
    """Section 4.6: a reading applies only in an earned dimension. One weak source cannot earn it alone."""

    @pytest.mark.parametrize(("burn", "grades", "q"), [
        (_burn(detection="MODERATE"), None, 0.40),        # B2 x 0.6
        (_burn(provider="COMMERCIALCO"), None, 0.44),     # C2 x 0.9
        (_burn(long_gap=True), None, 0.30),               # B2 x 0.9, halved for a long gap
    ])
    def test_it_is_listed_and_moves_no_band(self, burn: Burn, grades: dict[str, str] | None, q: float) -> None:
        result = tu.assess(_items(burns=[burn], grades=grades), _situation())
        assert result.range.floor is Band.MINIMAL
        (row,) = result.range.ledger
        assert (row.status, row.applied, round(row.q, 2)) == (Status.BELOW_THRESHOLD, False, q)
        assert row.note == "Interactions not earned"

    def test_an_own_or_allied_sensor_grade_carries_through(self) -> None:
        (item,) = _items(burns=[_burn(provider="ALLIED OPTICAL")], grades={**tu.PROVIDER_GRADES, "ALLIEDOPTICAL": "A"})
        assert (item.grade, item.controlled, item.derived_from) == ("A2", True, "approach:RED-GEO-1:ALLIEDOPTICAL")


class TestTheWordsPassI13:
    @pytest.mark.parametrize("rows", [[_row()], [_row(before=14.0, after=3.0)], [_row(ours=False)]])
    def test_the_ledger_row(self, rows: list[TargetWarning]) -> None:
        for row in tu.assess(_items(rows), _situation()).range.ledger:
            for text in ledger_view(row).values():
                assert i13_problems(text) == [], text

    def test_the_routine_row_and_a_cut_in_the_panel_format(self) -> None:
        edges = _edges([_row("BLUE-1", before=30.8, after=30.5)])
        items = tu.interaction_items(edges, judged=(HeldBurn(_BURN, Normality.ROUTINE),), hours=format_tof_label)
        for row in tu.assess(items, _situation(burns=())).range.ledger:
            for text in ledger_view(row).values():
                assert i13_problems(text) == [], text


class TestSuspicionPersists:
    def test_the_floor_outlives_the_dimension_until_a_later_hostile_burn(self) -> None:
        """I4 and section 4.4: Interactions decays below earned, the floor stays and asks to be re-observed."""
        later = _NOW + timedelta(days=9)
        result = tu.assess(_items(), _situation(now=later))
        assert result.range.floor is Band.HIGH
        assert result.range.reobserve == ("BLUE-COMSAT put in reach by its burn, 1.3 d warning",)

    def test_a_burn_the_edge_rests_on_does_not_end_its_floor(self) -> None:
        """Only a hostile burn judged after the approach ends its floor; the burns it rests on are not later."""
        second = _BURN + timedelta(hours=2)
        later = _NOW + timedelta(days=9)
        burns = (HeldBurn(_BURN, Normality.UNPRECEDENTED), HeldBurn(second, Normality.UNPRECEDENTED))
        result = tu.assess(_items(burns=[_burn(), _burn(second)]), _situation(now=later, burns=burns))
        (row,) = result.range.ledger
        assert row.q < tu.EARNED
        assert result.range.floor is Band.HIGH


class TestOnlyOneOfOursSetsTheFloor:
    def test_an_approach_to_a_target_not_ours_is_coverage_only(self) -> None:
        """Section 4.6 reads floor HIGH for a change against our asset; any other approach is still an interaction."""
        (item,) = _items([_row("OTHER-1", ours=False)])
        assert (item.dimension, item.floor_to) == (Dimension.INTERACTIONS, None)
        assert item.note == "not one of yours: coverage only"
        result = tu.assess((item,), _situation())
        assert result.range.floor is Band.MINIMAL
        assert tu.depth(result.range.coverage[Dimension.INTERACTIONS]) is tu.Depth.EARNED

    def test_one_of_ours_says_why_it_counts(self) -> None:
        (item,) = _items()
        assert item.note == "one of yours: a confirmed burn within 7 days brought it in reach sooner"


class TestOneBurnIsOneSourceChain:
    """Section 2.4 and 4.5: copies are not corroboration. One burn flown once is one piece of evidence."""

    def test_several_targets_from_one_burn_count_once(self) -> None:
        rows = [_row("BLUE-1"), _row("BLUE-2", before=14.0, after=3.0), _row("OTHER-1", ours=False)]
        items = _items(rows)
        assert {i.derived_from for i in items} == {"approach:RED-GEO-1:18SDS"}
        result = tu.assess(items, _situation())
        single = tu.assess(_items(), _situation())
        assert result.range.coverage == single.range.coverage
        assert result.range.floor is Band.HIGH
        assert sorted(r.status.value for r in result.range.ledger) == ["counted", "folded", "folded"]


class TestTheWeakestBurnGoverns:
    """Nothing shows confidence it has not earned: the change rests on every burn it was flown across."""

    def test_the_weakest_detection_and_any_long_gap(self) -> None:
        (item,) = _items(burns=[_burn(), _burn(_BURN + timedelta(hours=2), detection="MODERATE")])
        assert item.extraction == 0.6
        (gapped,) = _items(burns=[_burn(), _burn(_BURN + timedelta(hours=2), long_gap=True)])
        assert gapped.extraction == 0.45

    def test_a_detection_the_forensic_budget_never_graded_reads_low(self) -> None:
        (item,) = _items(burns=[_burn(detection="UNASSESSED")])
        assert item.extraction == 0.3

    def test_the_weakest_provider(self) -> None:
        (item,) = _items(burns=[_burn(), _burn(_BURN + timedelta(hours=2), provider="COMMERCIALCO")])
        assert (item.grade, item.controlled, item.derived_from) == ("C2", False, "approach:RED-GEO-1:COMMERCIALCO")

    def test_it_is_dated_by_the_latest_burn(self) -> None:
        (item,) = _items(burns=[_burn(_BURN + timedelta(hours=2)), _burn()])
        assert item.observed_at == _BURN + timedelta(hours=2)


class TestARoutineBurnMovesNoBand:
    """I9: ROUTINE moves no band. A station-keeping burn that shifts a warning is not a hostile approach."""

    _ROUTINE = (HeldBurn(_BURN, Normality.ROUTINE),)

    def test_an_approach_resting_only_on_routine_burns_is_coverage_only(self) -> None:
        (item,) = tu.interaction_items(_edges([_row(before=30.0, after=29.7)]), judged=self._ROUTINE)
        assert (item.routine, item.floor_to) == (True, None)
        assert item.note == "one of yours, but every burn it rests on was judged routine: coverage only"
        result = tu.assess((item,), _situation(burns=self._ROUTINE))
        assert result.range.floor is Band.MINIMAL
        (row,) = result.range.ledger
        assert row.applied is False

    def test_a_routine_burn_beside_a_hostile_one_lowers_nothing(self) -> None:
        second = _BURN + timedelta(hours=2)
        judged = (HeldBurn(_BURN, Normality.ROUTINE), HeldBurn(second, Normality.UNPRECEDENTED))
        (item,) = tu.interaction_items(_edges(burns=[_burn(), _burn(second)]), judged=judged)
        assert (item.routine, item.floor_to) == (False, Band.HIGH)

    def test_a_burn_too_soon_to_judge_is_not_routine(self) -> None:
        (item,) = tu.interaction_items(_edges(), judged=(HeldBurn(_BURN, Normality.NOT_ENOUGH_HISTORY),))
        assert (item.routine, item.floor_to) == (False, Band.HIGH)

    def test_the_panel_reads_the_verdict_from_the_held_history(self) -> None:
        """The reviewer's probe: a ROUTINE burn and a warning cut by 18 minutes leave the floor MINIMAL."""
        signals = tu.HistorySignals(provider="18SDS", newest_at=_NOW - timedelta(hours=6), span_days=400.0,
                                    burns=(tu.BurnSignal(_BURN, Normality.ROUTINE, detection="HIGH",
                                                         source="18SDS"),))
        held = HeldObject("RED-GEO-1", None, None, signals, Custody.HELD,
                          interactions=_edges([_row("BLUE-1", before=30.0, after=29.7)]))
        items = held.items(_NOW, "GEO", 9.0)
        (approach,) = [i for i in items if i.dimension is Dimension.INTERACTIONS]
        assert (approach.routine, approach.floor_to) == (True, None)
        assert tu.assess(items, held.situate(_situation(burns=()))).range.floor is Band.MINIMAL
