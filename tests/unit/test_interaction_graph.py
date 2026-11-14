"""Interactions v1 (SPC-172): an edge only where a burn of the object's own explains the approach.

Concept section 4.9: an edge v to x exists only when it is
manoeuvre-attributable, a confirmed burn by v preceded the approach within
7 days and the approach is closer than before the burn. The first source is
the warning change the sweep already flies (``domain/warning_change.py``):
there, closer means in reach sooner than before the burn, beyond the
tolerance ``classify`` reads a change with.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain import interaction_graph as ig
from spectre.domain.interaction_graph import Burn, Edge, warning_edges
from spectre.domain.warning_change import Change, TargetWarning

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_BURN = datetime(2026, 11, 2, 3, 10, tzinfo=UTC)


def _burn(epoch: datetime = _BURN, *, confirmed: bool = True, earliest: datetime | None = None) -> Burn:
    return Burn(epoch=epoch, earliest=earliest or epoch, latest=epoch, confirmed=confirmed, detection="HIGH",
                provider="18SDS")


def _row(name: str, before: float | None, after: float | None, *, ours: bool = True) -> TargetWarning:
    from spectre.domain.warning_change import classify

    return TargetWarning(name, ours, before, after, classify(before, after))


_NEWLY = _row("BLUE-COMSAT", None, 31.0)


class TestAnEdgeNeedsABurnOfItsOwn:
    def test_newly_in_reach_after_a_confirmed_burn_is_an_edge(self) -> None:
        (edge,) = warning_edges("RED-GEO-1", [_NEWLY], [_burn()], _NOW)
        assert (edge.actor, edge.target, edge.ours, edge.change) == (
            "RED-GEO-1", "BLUE-COMSAT", True, Change.NEWLY_IN_REACH)
        assert (edge.before_h, edge.after_h, edge.approach_at, edge.burns) == (None, 31.0, _NOW, (_burn(),))

    def test_a_pass_with_no_prior_burn_adds_nothing(self) -> None:
        assert warning_edges("RED-GEO-1", [_NEWLY], [], _NOW) == ()

    def test_a_burn_after_the_approach_explains_nothing(self) -> None:
        assert warning_edges("RED-GEO-1", [_NEWLY], [_burn(_NOW + timedelta(minutes=1))], _NOW) == ()

    def test_a_burn_at_the_moment_of_the_approach_precedes_it(self) -> None:
        assert len(warning_edges("RED-GEO-1", [_NEWLY], [_burn(_NOW)], _NOW)) == 1

    def test_a_burn_more_than_7_days_before_explains_nothing(self) -> None:
        week = timedelta(days=7)
        assert len(warning_edges("RED-GEO-1", [_NEWLY], [_burn(_NOW - week)], _NOW)) == 1
        assert warning_edges("RED-GEO-1", [_NEWLY], [_burn(_NOW - week - timedelta(minutes=1))], _NOW) == ()

    def test_an_undated_burn_whose_bracket_starts_more_than_7_days_before_explains_nothing(self) -> None:
        """Its earliest possible time governs: the burn may have been that old."""
        early = _NOW - timedelta(days=8)
        assert warning_edges("RED-GEO-1", [_NEWLY], [_burn(_BURN, earliest=early)], _NOW) == ()

    def test_an_unconfirmed_detection_explains_nothing(self) -> None:
        assert warning_edges("RED-GEO-1", [_NEWLY], [_burn(confirmed=False)], _NOW) == ()

    def test_every_burn_flown_across_must_qualify(self) -> None:
        """The before orbit predates the first burn, so the change rests on all of them."""
        old = _burn(_NOW - timedelta(days=9))
        assert warning_edges("RED-GEO-1", [_NEWLY], [old, _burn()], _NOW) == ()
        assert warning_edges("RED-GEO-1", [_NEWLY], [_burn(), _burn(confirmed=False)], _NOW) == ()


class TestOnlyACloserApproachIsAnEdge:
    def test_a_cut_is_an_edge(self) -> None:
        (edge,) = warning_edges("RED-GEO-1", [_row("BLUE-1", 14.0, 3.0)], [_burn()], _NOW)
        assert edge.change is Change.CUT

    @pytest.mark.parametrize(("before", "after"), [
        (3.0, 14.0),                 # lengthened
        (14.0, 14.0 - 0.2),          # within the tolerance: unchanged
        (14.0, None),                # no longer in reach
        (None, None),                # out of reach either side
    ])
    def test_anything_else_is_not(self, before: float | None, after: float | None) -> None:
        assert warning_edges("RED-GEO-1", [_row("BLUE-1", before, after)], [_burn()], _NOW) == ()

    def test_the_change_is_read_by_the_warning_changes_own_rule_not_taken_on_trust(self) -> None:
        mislabelled = TargetWarning("BLUE-1", True, 3.0, 14.0, Change.CUT)
        assert warning_edges("RED-GEO-1", [mislabelled], [_burn()], _NOW) == ()

    def test_a_target_not_ours_is_an_edge_and_says_so(self) -> None:
        (edge,) = warning_edges("RED-GEO-1", [_row("OTHER-1", None, 5.0, ours=False)], [_burn()], _NOW)
        assert edge.ours is False


class TestAnEdgeRestsOnABurn:
    def test_an_edge_with_no_burn_is_refused(self) -> None:
        with pytest.raises(ValueError, match="rests on at least one burn"):
            Edge("RED-GEO-1", "BLUE-COMSAT", True, Change.NEWLY_IN_REACH, None, 31.0, _NOW, ())

    def test_it_is_dated_by_its_latest_burn(self) -> None:
        """The approach exists only once the orbit after the last burn it rests on is held."""
        later = _burn(_BURN + timedelta(hours=5))
        (edge,) = warning_edges("RED-GEO-1", [_NEWLY], [later, _burn()], _NOW)
        assert edge.burn_at == _BURN + timedelta(hours=5)


class TestTheModuleIsPure:
    def test_the_domain_does_not_import_the_web_layer(self) -> None:
        assert "spectre.web" not in inspect.getsource(ig)
