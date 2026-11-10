"""Custody carried over a scenario's horizon, from SPC-018's status at its epoch (SPC-123).

Custody describes our information about red: the newest element set's age
against its limit, and its history. At the scenario epoch it is SPC-018's
status. Over the horizon it is carried on the assumption that no newer
element set arrives, so it is lost from the earliest of: the epoch, if it is
lost already; the moment the newest element set passes its limit (strictly
past, as the sweep's rule is); and a hypothesised burn newer than the newest
element set, which would not be seen. Each gap is therefore an upper bound.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from spectre.domain.custody import (
    Custody,
    CustodyOverHorizon,
    CustodyStatus,
    Horizon,
    LossCause,
    custody_over_horizon,
)

_START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_HELD = CustodyStatus(Custody.HELD, "Custody held: its orbit is 5.0 h old (limit 72 h).")
_DEGRADED = CustodyStatus(Custody.DEGRADED, "Custody degraded: its orbit is current, but its burns cannot be judged.")
_LOST = CustodyStatus(Custody.LOST, "Custody lost: its newest element set is out of date.")


def _over(
    status: CustodyStatus = _HELD, *, elset: float | None = 5.0, limit: float | None = 72.0, hours: float = 10.0,
    burn: datetime | None = None,
) -> CustodyOverHorizon:
    return custody_over_horizon(
        status, elset_hours=elset, limit_hours=limit, horizon=Horizon(_START, hours, burn),
    )


def _at(hours: float) -> datetime:
    return _START + timedelta(hours=hours)


class TestHeldThrough:
    def test_held_through_the_horizon(self) -> None:
        over = _over()
        assert (over.at_epoch, over.lost_from_h, over.lost_hours, over.cause) == (Custody.HELD, None, 0.0, None)
        assert over.maintained
        assert over.sentence == (
            "Custody held through the 10 h horizon: its newest element set stays within its 72 h limit until "
            "2026-11-01 07:00 UTC, after the horizon ends."
        )

    def test_held_through_is_not_lost_from_the_epoch(self) -> None:
        assert not _over().lost_from_epoch

    def test_exactly_at_the_limit_when_the_horizon_ends_is_not_lost(self) -> None:
        """The sweep's rule is strictly past the limit, so an element set at its limit is still within it."""
        over = _over(elset=14.0, limit=24.0)
        assert over.maintained and over.lost_hours == 0.0 and over.cause is None


class TestLost:
    def test_ages_out_part_way_through(self) -> None:
        over = _over(elset=20.0, limit=24.0)
        assert (over.lost_from_h, over.lost_hours, over.cause) == (4.0, 6.0, LossCause.AGES_OUT)
        assert not over.maintained and not over.lost_from_epoch
        assert over.sentence == (
            "Custody lost from 2026-10-29 16:00 UTC, 4.0 h into the horizon, for up to 6.0 h: its newest element set "
            "then passes its 24 h limit, so unless a newer one arrives, whether a burn is normal and how it changes "
            "your warning time cannot be judged."
        )

    @pytest.mark.parametrize(("status", "elset", "limit"), [
        (_LOST, 30.0, 24.0),     # past its limit already
        (_LOST, None, None),     # no readable epoch
        (_HELD, 30.0, 24.0),     # a status that disagrees with the age is not believed over it
    ])
    def test_already_lost_is_lost_for_the_whole_horizon(
        self, status: CustodyStatus, elset: float | None, limit: float | None,
    ) -> None:
        over = _over(status, elset=elset, limit=limit)
        assert (over.lost_from_h, over.lost_hours, over.cause) == (0.0, 10.0, LossCause.ALREADY_LOST)
        assert over.lost_from_epoch
        assert over.sentence == (
            "Custody lost for the whole 10 h horizon: its newest element set is already past its limit or has no "
            "readable epoch, so whether a burn is normal and how it changes your warning time cannot be judged "
            "until a newer one arrives."
        )

    def test_at_its_limit_at_the_epoch_ages_out_from_the_epoch(self) -> None:
        """Strictly past the limit is lost already; exactly at it, the element set passes its limit from the epoch."""
        over = _over(elset=24.0, limit=24.0)
        assert (over.lost_from_h, over.lost_hours, over.cause) == (0.0, 10.0, LossCause.AGES_OUT)
        assert over.lost_from_epoch
        assert over.sentence.startswith(
            "Custody lost from 2026-10-29 12:00 UTC, 0.0 h into the horizon, for up to 10.0 h: its newest element set "
            "then passes its 24 h limit,"
        )

    def test_a_burn_at_the_epoch_is_in_the_horizon_not_before_it(self) -> None:
        """A 0 h burn offset, which the hypothesis panel allows, burns at the epoch, not before it."""
        over = _over(burn=_START)
        assert (over.lost_from_h, over.lost_hours, over.cause) == (0.0, 10.0, LossCause.BURN)
        assert over.sentence.startswith("Custody lost from the burn at 2026-10-29 12:00 UTC, 0.0 h into the horizon,")
        assert "before the scenario epoch" not in over.sentence

    def test_a_burn_in_the_horizon_newer_than_the_element_set(self) -> None:
        over = _over(burn=_at(2.0))
        assert (over.at_epoch, over.lost_from_h, over.lost_hours, over.cause) == (Custody.HELD, 2.0, 8.0, LossCause.BURN)
        assert over.sentence == (
            "Custody lost from the burn at 2026-10-29 14:00 UTC, 2.0 h into the horizon, for up to 8.0 h: the burn "
            "is newer than the newest element set, so whether it is normal and how it changes your warning time "
            "cannot be judged until a newer element set arrives."
        )

    def test_a_burn_already_made_counts_from_the_epoch(self) -> None:
        over = _over(burn=_at(-1.0))
        assert (over.lost_from_h, over.lost_hours, over.cause) == (0.0, 10.0, LossCause.BURN)
        assert over.lost_from_epoch
        assert over.sentence == (
            "Custody lost for the whole 10 h horizon: the burn at 2026-10-29 11:00 UTC, before the scenario epoch, "
            "is newer than the newest element set, so whether it was normal and how it changed your warning time "
            "cannot be judged until a newer element set arrives."
        )

    @pytest.mark.parametrize(("burn_h", "expected"), [
        (2.0, (2.0, LossCause.BURN)),       # the burn comes first
        (6.0, (4.0, LossCause.AGES_OUT)),   # the element set ages out first
    ])
    def test_the_earliest_cause_wins(self, burn_h: float, expected: tuple[float, LossCause]) -> None:
        over = _over(elset=20.0, limit=24.0, burn=_at(burn_h))
        assert (over.lost_from_h, over.cause) == expected
        assert over.lost_hours == 10.0 - expected[0]


class TestBurnsThatDoNotCount:
    @pytest.mark.parametrize("burn_h", [-6.0, -5.0])
    def test_a_burn_no_newer_than_the_element_set_is_in_it(self, burn_h: float) -> None:
        """The element set is 5 h old: a burn at or before its epoch is already in the orbit it holds."""
        assert _over(burn=_at(burn_h)).maintained

    @pytest.mark.parametrize("burn_h", [10.0, 11.0])
    def test_a_burn_at_or_after_the_horizon_ends_loses_nothing_within_it(self, burn_h: float) -> None:
        over = _over(burn=_at(burn_h))
        assert over.maintained and over.lost_hours == 0.0


class TestDegraded:
    """Degraded: the orbit is current, but whether a burn is normal cannot be judged (SPC-018).

    The operator's custody is information to judge both whether a burn is normal and how the warning time
    changed, so custody that can judge only one is neither held nor lost: it is degraded, and the owner ruled on
    2026-11-05 (SPC-179) that it scores between the two. It stays degraded until it would be lost by the rules
    held custody is lost by: the newest element set passing its limit, or a hypothesised burn newer than it.
    """

    _WHY = (
        "Degraded, neither held nor lost: how a burn changes your warning time can be judged, but whether it is "
        "normal cannot."
    )

    def test_degraded_through_the_horizon_is_neither_held_nor_lost(self) -> None:
        over = _over(_DEGRADED)
        assert (over.at_epoch, over.lost_from_h, over.lost_hours, over.degraded_hours, over.cause) == (
            Custody.DEGRADED, None, 0.0, 10.0, None,
        )
        assert not over.maintained and not over.lost_from_epoch
        assert over.sentence == (
            "Custody degraded through the 10 h horizon: its newest element set stays within its 72 h limit until "
            "2026-11-01 07:00 UTC, after the horizon ends. " + self._WHY
        )

    def test_degraded_until_the_element_set_ages_out_then_lost(self) -> None:
        over = _over(_DEGRADED, elset=20.0, limit=24.0)
        assert (over.lost_from_h, over.lost_hours, over.degraded_hours, over.cause) == (4.0, 6.0, 4.0, LossCause.AGES_OUT)
        assert not over.maintained and not over.lost_from_epoch
        assert over.sentence == (
            "Custody degraded for 4.0 h from the start of the horizon. " + self._WHY + " Custody lost from 2026-10-29 "
            "16:00 UTC, 4.0 h into the horizon, for up to 6.0 h: its newest element set then passes its 24 h limit, "
            "so unless a newer one arrives, whether a burn is normal and how it changes your warning time cannot be "
            "judged."
        )

    def test_degraded_until_a_burn_newer_than_the_element_set_then_lost(self) -> None:
        over = _over(_DEGRADED, burn=_at(2.0))
        assert (over.lost_from_h, over.lost_hours, over.degraded_hours, over.cause) == (2.0, 8.0, 2.0, LossCause.BURN)
        assert over.sentence.startswith("Custody degraded for 2.0 h from the start of the horizon. " + self._WHY)
        assert over.sentence.endswith("Custody lost from the burn at 2026-10-29 14:00 UTC, 2.0 h into the horizon, "
                                      "for up to 8.0 h: the burn is newer than the newest element set, so whether it "
                                      "is normal and how it changes your warning time cannot be judged until a newer "
                                      "element set arrives.")

    @pytest.mark.parametrize("burn_h", [0.004, 0.03])
    def test_a_degraded_span_under_a_tenth_of_an_hour_is_never_shown_as_none(self, burn_h: float) -> None:
        """A burn 14 s or 108 s in leaves a degraded span that reads 0.0 h to one decimal: it says under 0.1 h."""
        over = _over(_DEGRADED, burn=_at(burn_h))
        assert over.degraded_hours == pytest.approx(burn_h)
        assert over.sentence.startswith("Custody degraded for under 0.1 h from the start of the horizon. " + self._WHY)
        assert "0.0 h of" not in over.sentence

    def test_a_burn_before_the_epoch_newer_than_the_element_set_loses_it_for_the_whole_horizon(self) -> None:
        """Degraded hours run only until custody is lost; a burn already made leaves none."""
        over = _over(_DEGRADED, burn=_at(-1.0))
        assert (over.lost_from_h, over.lost_hours, over.degraded_hours, over.cause) == (0.0, 10.0, 0.0, LossCause.BURN)
        assert over.lost_from_epoch

    def test_a_burn_in_the_element_set_leaves_it_degraded(self) -> None:
        over = _over(_DEGRADED, burn=_at(-6.0))
        assert (over.lost_from_h, over.degraded_hours) == (None, 10.0)

    def test_degraded_past_its_limit_is_lost_already(self) -> None:
        """An element set past its limit cannot judge the warning time either: lost, not degraded."""
        over = _over(_DEGRADED, elset=30.0, limit=24.0)
        assert (over.cause, over.degraded_hours, over.lost_hours) == (LossCause.ALREADY_LOST, 0.0, 10.0)

    def test_held_custody_has_no_degraded_hours(self) -> None:
        assert _over().degraded_hours == 0.0
        assert _over(elset=20.0, limit=24.0).degraded_hours == 0.0


def test_a_horizon_of_no_length_is_refused() -> None:
    with pytest.raises(ValueError, match="horizon"):
        _over(hours=0.0)
