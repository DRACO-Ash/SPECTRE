"""Interactions v2 (SPC-173): close approaches, computed or filed by UDL, as edges.

Concept section 4.9 and 5.4: an approach is an edge only when it is
manoeuvre-attributable, a confirmed burn by the object within 7 days before
it, and closer than before the burn. For a miss distance that means under
50 km and closer than the figure from before the burn by more than the
position error both figures carry. A computed closest approach is refused on
an out-of-date element set, as the Decision Engine refuses one; a UDL miss
distance that cannot be read is refused, and both refusals are stated.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from spectre.domain.interaction_graph import (
    MISS_FLOOR_KM,
    Burn,
    Edge,
    Miss,
    MissEdge,
    MissSource,
    SetAge,
    approach_window,
    miss_edges,
)
from spectre.domain.warning_change import Change
from tests.unit._i13 import i13_problems

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)
_BEFORE_AT = _BURN - timedelta(days=1)
_TCA = _BURN + timedelta(days=2)


def _burn(epoch: datetime = _BURN, *, confirmed: bool = True, earliest: datetime | None = None) -> Burn:
    return Burn(epoch=epoch, earliest=earliest or epoch, latest=epoch, confirmed=confirmed, detection="HIGH",
                provider="18SDS")


_BASE_MISS = Miss(target="BLUE-COMSAT", target_satno="40000", ours=True, source=MissSource.COMPUTED, tca=_TCA,
                  after_km=12.0, before_km=140.0, before_at=_BEFORE_AT, margin_km=6.0)


def _miss(after: float | None = 12.0, before: float | None = 140.0, **changes: Any) -> Miss:
    """A computed approach to one of ours, 140 km before the burn and 12 km after, with *changes* made."""
    return replace(_BASE_MISS, after_km=after, before_km=before, **changes)


def _edges(*misses: Miss, burns: list[Burn] | None = None) -> tuple[tuple[MissEdge, ...], tuple[str, ...]]:
    return miss_edges("RED-GEO-1", misses, [_burn()] if burns is None else burns)


class TestACloserApproachAfterABurnIsAnEdge:
    def test_under_50_km_and_closer_than_before_the_burn(self) -> None:
        (edge,), refused = _edges(_miss())
        assert refused == ()
        assert (edge.actor, edge.target, edge.target_satno, edge.ours, edge.source) == (
            "RED-GEO-1", "BLUE-COMSAT", "40000", True, MissSource.COMPUTED)
        assert (edge.before_km, edge.after_km, edge.approach_at, edge.burns, edge.burn_at) == (
            140.0, 12.0, _TCA, (_burn(),), _BURN)

    def test_the_floor_is_50_km(self) -> None:
        assert MISS_FLOOR_KM == 50.0
        assert len(_edges(_miss(after=49.9))[0]) == 1
        assert _edges(_miss(after=50.0)) == ((), ())

    def test_no_closer_than_before_the_burn_is_no_edge(self) -> None:
        """The pass orbital mechanics would have brought anyway adds nothing."""
        assert _edges(_miss(after=12.0, before=12.0)) == ((), ())
        assert _edges(_miss(after=30.0, before=20.0)) == ((), ())

    def test_closer_only_by_less_than_the_position_error_is_no_edge(self) -> None:
        """Both figures carry the error the sweep assumes for their sets, so a smaller change is not closer."""
        assert _edges(_miss(after=12.0, before=18.0, margin_km=6.0)) == ((), ())
        assert len(_edges(_miss(after=12.0, before=18.1, margin_km=6.0))[0]) == 1

    def test_a_target_not_ours_is_an_edge_and_says_so(self) -> None:
        (edge,), _ = _edges(_miss(ours=False))
        assert edge.ours is False


class TestTheBurnMustExplainIt:
    def test_no_burn_no_edge_and_nothing_to_state(self) -> None:
        """An accidental pass adds nothing, and is not a refusal."""
        assert _edges(_miss(), burns=[]) == ((), ())

    def test_an_approach_more_than_7_days_after_the_burn_is_not_explained(self) -> None:
        assert len(_edges(_miss(tca=_BURN + timedelta(days=7)))[0]) == 1
        assert _edges(_miss(tca=_BURN + timedelta(days=7, minutes=1))) == ((), ())

    def test_an_approach_before_the_burn_is_not_explained(self) -> None:
        assert _edges(_miss(tca=_BURN - timedelta(minutes=1))) == ((), ())

    def test_an_unconfirmed_detection_explains_nothing(self) -> None:
        assert _edges(_miss(), burns=[_burn(confirmed=False)]) == ((), ())

    def test_every_burn_since_the_figure_before_must_explain_it(self) -> None:
        """A burn between the two figures that is too old, or unconfirmed, leaves the change unexplained."""
        old = _burn(_TCA - timedelta(days=8))
        early = _miss(before_at=old.epoch - timedelta(hours=1))
        assert _edges(early, burns=[old, _burn()]) == ((), ())
        assert _edges(_miss(), burns=[_burn(), _burn(_BURN + timedelta(hours=3), confirmed=False)]) == ((), ())

    def test_a_burn_before_the_figure_before_is_not_one_it_rests_on(self) -> None:
        older = _burn(_BEFORE_AT - timedelta(days=2))
        (edge,), _ = _edges(_miss(), burns=[older, _burn()])
        assert edge.burns == (_burn(),)

    def test_a_burn_after_the_approach_is_not_one_it_rests_on(self) -> None:
        later = _burn(_TCA + timedelta(hours=1))
        (edge,), _ = _edges(_miss(), burns=[_burn(), later])
        assert edge.burns == (_burn(),)

    def test_no_burn_between_the_two_figures_is_no_edge(self) -> None:
        """A figure from before that already follows the burn: the change is not the burn's."""
        assert _edges(_miss(before_at=_BURN + timedelta(hours=1))) == ((), ())


class TestARefusalIsStated:
    def test_a_miss_distance_that_cannot_be_read_is_refused_and_says_why(self) -> None:
        edges, (sentence,) = _edges(_miss(after=None, problem="the miss distance is not a number",
                                          source=MissSource.UDL))
        assert edges == ()
        assert sentence == "UDL conjunction with BLUE-COMSAT not counted: the miss distance is not a number."
        assert i13_problems(sentence) == []

    def test_one_with_no_figure_from_before_the_burn_is_refused_and_says_why(self) -> None:
        edges, (sentence,) = _edges(_miss(before=None, before_at=None, source=MissSource.UDL))
        assert edges == ()
        assert sentence == ("UDL conjunction with BLUE-COMSAT not counted: no close approach to it from before "
                            "the burn is held, so closer cannot be shown.")

    def test_an_unreadable_figure_no_burn_explains_is_an_accidental_pass_and_not_stated(self) -> None:
        assert _edges(_miss(after=None, problem="unreadable", tca=_BURN - timedelta(days=1))) == ((), ())

    def test_an_unreadable_figure_with_a_problem_unstated_still_says_it_was_refused(self) -> None:
        _, (sentence,) = _edges(_miss(after=None))
        assert sentence == "computed closest approach with BLUE-COMSAT not counted: its miss distance was not read."

    def test_a_figure_at_or_over_50_km_with_no_figure_before_is_not_stated(self) -> None:
        assert _edges(_miss(after=60.0, before=None, before_at=None)) == ((), ())


class TestAMissEdgeIsCloserByConstruction:
    def test_with_no_burn_it_is_refused(self) -> None:
        with pytest.raises(ValueError, match="rests on at least one burn"):
            MissEdge("RED-GEO-1", "BLUE-COMSAT", "40000", True, MissSource.COMPUTED, 140.0, 12.0, _TCA, ())

    @pytest.mark.parametrize(("before", "after"), [(12.0, 12.0), (140.0, 50.0), (140.0, -1.0)])
    def test_one_not_closer_or_not_under_50_km_is_refused(self, before: float, after: float) -> None:
        with pytest.raises(ValueError, match="under 50 km and closer than before the burn"):
            MissEdge("RED-GEO-1", "BLUE-COMSAT", "40000", True, MissSource.COMPUTED, before, after, _TCA,
                     (_burn(),))


class TestAWarningEdgeCarriesItsTargetsNumber:
    def test_it_defaults_to_none_held(self) -> None:
        edge = Edge("RED-GEO-1", "BLUE-COMSAT", True, Change.NEWLY_IN_REACH, None, 31.0, _NOW, (_burn(),))
        assert edge.target_satno == ""
        assert Edge("RED-GEO-1", "BLUE-COMSAT", True, Change.NEWLY_IN_REACH, None, 31.0, _NOW, (_burn(),),
                    target_satno="40000").target_satno == "40000"


_RED_AFTER = SetAge("red", _BURN + timedelta(hours=6), 72.0)
_BLUE = SetAge("BLUE-COMSAT", _NOW - timedelta(hours=10), 72.0)


class TestTheWindowAComputedApproachIsSearchedIn:
    def test_from_the_latest_burn_to_7_days_after_the_earliest_within_both_sets_limits(self) -> None:
        start, end = approach_window([_burn()], _RED_AFTER, _BLUE, _NOW)  # type: ignore[misc]
        assert start == _BURN
        # The red set's limit, 72 h from its epoch, comes before 7 days after the burn.
        assert end == _RED_AFTER.epoch + timedelta(hours=72)

    def test_7_days_after_the_earliest_burn_ends_it_when_that_comes_first(self) -> None:
        long_limit = SetAge("red", _BURN + timedelta(hours=6), 24.0 * 30)
        blue = SetAge("BLUE-COMSAT", _NOW - timedelta(hours=10), 24.0 * 30)
        two = [_burn(_BURN - timedelta(hours=5)), _burn()]
        assert approach_window(two, long_limit, blue, _NOW) == (_BURN, _BURN - timedelta(hours=5) + timedelta(days=7))

    def test_an_out_of_date_red_set_is_refused_and_says_so(self) -> None:
        stale = SetAge("red", _NOW - timedelta(hours=73), 72.0)
        sentence = approach_window([_burn()], stale, _BLUE, _NOW)
        assert sentence == "the red element set is out of date, 3.0 d old against a 72 h limit"

    def test_an_out_of_date_blue_set_is_refused_and_names_it(self) -> None:
        stale = SetAge("BLUE-COMSAT", _NOW - timedelta(hours=25), 24.0)
        assert approach_window([_burn()], _RED_AFTER, stale, _NOW) == (
            "the BLUE-COMSAT element set is out of date, 1.0 d old against a 24 h limit")

    def test_a_set_at_its_limit_is_still_current(self) -> None:
        """The sweep's staleness rule: out of date only past the limit."""
        at_limit = SetAge("BLUE-COMSAT", _NOW - timedelta(hours=72), 72.0)
        assert approach_window([_burn()], _RED_AFTER, at_limit, _NOW) == (_BURN, _NOW)

    def test_a_set_whose_epoch_cannot_be_read_is_refused(self) -> None:
        assert approach_window([_burn()], SetAge("red", None, 72.0), _BLUE, _NOW) == (
            "the red element set's epoch cannot be read, so its age is unknown")

    def test_no_burn_is_refused(self) -> None:
        assert approach_window([], _RED_AFTER, _BLUE, _NOW) == "no confirmed burn to compare across"

    def test_no_time_left_inside_both_limits_is_refused(self) -> None:
        """A burn bracketed across more than 7 days leaves no span after it that it could explain."""
        wide = _burn(_BURN, earliest=_BURN - timedelta(days=8))
        assert approach_window([wide], _RED_AFTER, _BLUE, _NOW) == (
            "no time within 7 days after the burn falls inside both element sets' limits")
