"""An adversary probability and confidence offered from NOTSO history (SPC-130).

The prior is a suggestion beside an adversary row, never a value written into
it: concept section 7.5, items 2 and 3. It maps NOTSO types to the engine's
action types, shows its sample size and span, and offers nothing below a floor.
A routine burn below the reporting threshold carries no notice, so a quiet
NOTSO record is never read as inactivity: no notices give no prior, never a
probability of 0, and no action type is ever offered 1 minus a manoeuvre's
prior. Its figure basis is LOOKUP. No test reads the wall clock.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta

import pytest

from spectre.astro.notso import NOTSORecord, NOTSOType, OperatorBehaviourProfile
from spectre.domain.decision import ActionType
from spectre.domain.notso_prior import (
    MIN_EVENTS,
    NOTSO_ACTION_TYPES,
    NoPrior,
    NotsoPrior,
    notso_prior,
)
from spectre.domain.provenance import Basis
from spectre.domain.threat_understanding import MANUFACTURABLE_CAP
from tests.unit._i13 import i13_problems

_START = datetime(2025, 1, 1, tzinfo=UTC)
_END = _START + timedelta(days=100)
_COVER = ((_START, _END),)


def _notice(day: float, kind: NOTSOType = NOTSOType.MANOEUVRE, ident: str = "") -> NOTSORecord:
    at = _START + timedelta(days=day)
    return NOTSORecord(
        message_id=ident or f"N{day}", norad_id=50322, international_designator=None, object_name=None,
        issuing_entity="JCO", issue_date_utc=at, effective_start_utc=at, effective_end_utc=at + timedelta(hours=24),
        notso_type=kind, description="", predicted_delta_v_km_s=None, predicted_direction=None, raw_message="",
    )


def _profile(reportable: int, noticed: int, *, assessable: bool = True) -> OperatorBehaviourProfile:
    return OperatorBehaviourProfile(
        norad_id=50322, analysis_period_start=_START, analysis_period_end=_END,
        total_manoeuvres=reportable, manoeuvres_with_notso=noticed, manoeuvres_without_notso=reportable - noticed,
        notification_rate=noticed / reportable if reportable else 0.0,
        mean_lead_time_h=None, std_lead_time_h=None, min_lead_time_h=None, max_lead_time_h=None,
        mean_magnitude_ratio=None, std_magnitude_ratio=None, window_accuracy_rate=0.0,
        reportable_manoeuvres=reportable, reporting_threshold_km_s=0.001, behaviour_unassessable=not assessable,
    )


def _prior(notices: list[NOTSORecord], action: ActionType = ActionType.MANOEUVRE, **kw: object) -> NotsoPrior | NoPrior:
    return notso_prior("RX", action, notices, cover=kw.pop("cover", _COVER), horizon_hours=kw.pop("horizon", 72.0),
                       **kw)  # type: ignore[arg-type]


def _offered(notices: list[NOTSORecord], **kw: object) -> NotsoPrior:
    prior = _prior(notices, **kw)
    assert isinstance(prior, NotsoPrior), prior
    return prior


_FIVE = [_notice(d) for d in (5, 20, 40, 60, 80)]


class TestTheMapping:
    def test_a_manoeuvre_or_proximity_notice_maps_to_a_manoeuvre_and_no_other_type_maps(self) -> None:
        assert NOTSO_ACTION_TYPES == {
            NOTSOType.MANOEUVRE: ActionType.MANOEUVRE,
            NOTSOType.PROXIMITY_OPS: ActionType.MANOEUVRE,
            NOTSOType.DEORBIT: None,
            NOTSOType.LAUNCH: None,
            NOTSOType.TEST: None,
            NOTSOType.OTHER: None,
        }

    def test_proximity_notices_count_towards_a_manoeuvre(self) -> None:
        notices = [_notice(d, NOTSOType.PROXIMITY_OPS) for d in (5, 30, 60)]
        assert _offered(notices).events == 3

    def test_unmapped_notices_are_not_counted(self) -> None:
        notices = [_notice(d, kind) for d, kind in ((5, NOTSOType.LAUNCH), (30, NOTSOType.OTHER), (60, NOTSOType.TEST))]
        prior = _prior(notices)
        assert isinstance(prior, NoPrior)
        assert prior.reason.startswith("0 reported manoeuvre events for RX")

    @pytest.mark.parametrize("action", [ActionType.SENSOR_RETASK, ActionType.POSTURE_CHANGE, ActionType.NO_ACTION])
    def test_an_action_no_notso_type_maps_to_is_offered_nothing(self, action: ActionType) -> None:
        prior = _prior(_FIVE, action)
        assert isinstance(prior, NoPrior)
        assert prior.reason.startswith(f"No NOTSO type maps to {action.value.replace('_', ' ')}")

    def test_no_action_is_never_offered_the_complement_of_a_quiet_record(self) -> None:
        prior = _prior([], ActionType.NO_ACTION)
        assert isinstance(prior, NoPrior)
        assert "not evidence that RX is inactive" in prior.reason


class TestTheFloor:
    def test_no_notices_offer_nothing_never_a_probability_of_0(self) -> None:
        prior = _prior([])
        assert isinstance(prior, NoPrior)
        assert "routine burns below the reporting threshold carry no notice" in prior.reason

    def test_below_the_floor_nothing_is_offered_and_the_count_is_shown(self) -> None:
        prior = _prior(_FIVE[: MIN_EVENTS - 1])
        assert isinstance(prior, NoPrior)
        assert prior.reason.startswith(f"{MIN_EVENTS - 1} reported manoeuvre events for RX")
        assert f"fewer than the {MIN_EVENTS} a suggestion needs" in prior.reason

    def test_at_the_floor_a_prior_is_offered(self) -> None:
        assert _offered(_FIVE[:MIN_EVENTS]).events == MIN_EVENTS

    def test_notices_outside_the_span_are_not_counted(self) -> None:
        prior = _prior([_notice(-10), _notice(5), _notice(30), _notice(150)])
        assert isinstance(prior, NoPrior)
        assert prior.reason.startswith("2 reported manoeuvre events")

    def test_a_span_of_no_time_offers_nothing(self) -> None:
        prior = _prior(_FIVE, cover=((_START, _START),))
        assert isinstance(prior, NoPrior)
        assert prior.reason == "The NOTSO cache covers no span of time yet, so no suggestion is offered."

    def test_a_notice_a_whole_day_after_an_events_first_is_still_a_copy_of_it(self) -> None:
        notices = [_notice(5), _notice(6, ident="copy"), _notice(30), _notice(60)]
        assert _offered(notices).events == 3

    def test_copies_of_one_event_count_once(self) -> None:
        notices = [_notice(5), _notice(5.5, ident="copy"), _notice(30), _notice(60)]
        prior = _offered(notices)
        assert (prior.events, prior.notices) == (3, 4)


class TestTheCover:
    def test_a_gap_in_the_cache_is_neither_counted_as_quiet_time_nor_mined_for_notices(self) -> None:
        # The cache covers days 0 to 40 and 70 to 100, 70 days; days 40 to 70 it holds nothing for any object.
        cover = ((_START, _START + timedelta(days=40)), (_START + timedelta(days=70), _END))
        prior = _offered([_notice(d) for d in (5, 20, 30, 50, 80, 90)], cover=cover)
        assert prior.probability == math.floor((1 - math.exp(-5 * 72.0 / (70 * 24.0))) * 100) / 100
        assert prior.probability == 0.19
        assert (prior.events, prior.covered_days, prior.gaps) == (5, 70.0, 1)
        assert "5 reported events (5 notices) in the 70 days the NOTSO cache covers from 01 Jan 2025 to 11 Apr 2025, " \
               "leaving out 1 spell with no notice for any object, which is a gap in the cache, not quiet," in prior.lines[1]

    def test_cover_before_the_objects_launch_year_is_not_counted_as_quiet_time(self) -> None:
        # The cache covers 2024 and 2025, but RX was launched in 2025: a year it did not exist is not a quiet year.
        cover = ((datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC)),
                 (datetime(2025, 1, 1, tzinfo=UTC), _END))
        prior = _offered(_FIVE, cover=cover, launched=2025)
        assert prior.probability == 0.13
        assert (prior.covered_days, prior.gaps, prior.launched) == (100.0, 0, 2025)
        assert "in the 100 days the NOTSO cache covers from 01 Jan 2025 to 11 Apr 2025, none of them before the start " \
               "of RX's launch year, 2025, where" in prior.lines[1]

    def test_a_launch_year_before_the_cover_changes_nothing(self) -> None:
        prior = _offered(_FIVE, launched=2020)
        assert (prior.probability, prior.launched) == (0.13, None)
        assert "launch year" not in prior.lines[1]

    def test_with_no_cover_since_the_launch_year_nothing_is_offered(self) -> None:
        prior = _prior(_FIVE, launched=2026)
        assert isinstance(prior, NoPrior)
        assert prior.reason == (
            "The NOTSO cache covers no time since the start of RX's launch year, 2026, so no suggestion is offered."
        )

    def test_no_cover_offers_nothing(self) -> None:
        prior = _prior(_FIVE, cover=())
        assert isinstance(prior, NoPrior)
        assert prior.reason == "The NOTSO cache covers no span of time yet, so no suggestion is offered."


class TestTheProbability:
    def test_it_is_the_chance_of_at_least_one_reported_event_in_the_horizon_at_the_history_rate(self) -> None:
        prior = _offered(_FIVE, horizon=72.0)
        rate = 5 / (100 * 24.0)
        assert prior.probability == math.floor((1 - math.exp(-rate * 72.0)) * 100) / 100
        assert prior.probability == 0.13

    def test_a_longer_horizon_offers_a_higher_probability(self) -> None:
        assert _offered(_FIVE, horizon=240.0).probability > _offered(_FIVE, horizon=72.0).probability

    def test_it_is_rounded_down_so_it_never_reads_certain(self) -> None:
        dense = [_notice(d) for d in range(0, 100, 2)]
        assert _offered(dense, horizon=720.0).probability == 0.99

    def test_a_chance_below_the_hundredth_is_not_offered_as_0(self) -> None:
        # 3 events in 700 days carried over 24 h is a chance of 0.004: rounded down it would read 0.00, which an
        # operator applying it to a row would take as no chance at all. None is offered, and the reason says why.
        notices = [_notice(d) for d in (100, 300, 500)]
        prior = _prior(notices, cover=((_START, _START + timedelta(days=700)),), horizon=24.0)
        assert isinstance(prior, NoPrior)
        assert prior.reason == (
            "3 reported manoeuvre events for RX in the 700 days the NOTSO cache covers put the chance of a reported "
            "one within 24 h below 0.01, too small to offer as a figure, so none is offered. That is not evidence "
            "that RX is inactive: routine burns below the reporting threshold carry no notice."
        )

    def test_a_prior_cannot_be_built_with_a_probability_of_0(self) -> None:
        with pytest.raises(ValueError, match="probability"):
            dataclasses.replace(_offered(_FIVE), probability=0.0)

    def test_its_basis_is_a_lookup(self) -> None:
        assert _offered(_FIVE).basis.kind is Basis.LOOKUP

    def test_a_horizon_of_0_is_refused(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            _prior(_FIVE, horizon=0.0)


class TestTheConfidence:
    def test_without_a_profile_no_confidence_is_offered_and_it_says_why(self) -> None:
        prior = _offered(_FIVE)
        assert prior.confidence is None
        assert prior.confidence_line == (
            "No Conf is offered: no element-set history is held for RX, so how fully its NOTSO record covers its "
            "manoeuvres is not measured."
        )

    def test_an_unassessable_profile_offers_no_confidence(self) -> None:
        prior = _offered(_FIVE, profile=_profile(2, 2, assessable=False))
        assert prior.confidence is None
        assert prior.confidence_line.startswith("No Conf is offered: only 2 of RX's detected manoeuvres")

    def test_an_assessable_profile_offers_the_lower_edge_of_its_notice_share(self) -> None:
        prior = _offered(_FIVE, profile=_profile(10, 4))
        n, p, z = 10, 0.4, 1.96
        wilson = (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
        assert prior.confidence == math.floor(wilson * 100) / 100
        assert prior.confidence == 0.16

    def test_a_small_sample_earns_less_confidence_than_a_large_one_at_the_same_share(self) -> None:
        small = _offered(_FIVE, profile=_profile(5, 2)).confidence
        large = _offered(_FIVE, profile=_profile(50, 20)).confidence
        assert small is not None
        assert large is not None
        assert small < large < MANUFACTURABLE_CAP

    def test_confidence_never_exceeds_what_a_notso_filing_can_be_worth(self) -> None:
        # Whether to file is the adversary's choice, so a record however full is capped as Threat Understanding caps
        # every manufacturable item; the line shows the measured edge and the cap.
        prior = _offered(_FIVE, profile=_profile(10, 9))
        assert prior.confidence == MANUFACTURABLE_CAP
        assert prior.confidence_line == (
            "Conf 0.30: the lower edge of a 95 in 100 interval on the share of RX's reportable manoeuvres its NOTSO "
            "record covered, 9 of 10, is 0.59, capped at 0.30, the most SPECTRE gives a NOTSO filing, since whether "
            "to file is the adversary's choice; a lookup."
        )

    def test_a_prior_cannot_be_built_showing_more_confidence_than_a_filing_earns(self) -> None:
        offered = _offered(_FIVE)
        with pytest.raises(ValueError, match="confidence"):
            dataclasses.replace(offered, confidence=MANUFACTURABLE_CAP + 0.01)

    def test_a_prior_cannot_be_built_with_a_confidence_below_0(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            dataclasses.replace(_offered(_FIVE), confidence=-0.01)

    def test_a_prior_cannot_be_built_from_fewer_events_than_the_floor(self) -> None:
        offered = _offered(_FIVE)
        with pytest.raises(ValueError, match="events"):
            dataclasses.replace(offered, events=MIN_EVENTS - 1)

    def test_confidence_never_exceeds_the_share_measured(self) -> None:
        prior = _offered(_FIVE, profile=_profile(5, 1))
        assert prior.confidence is not None
        assert prior.confidence <= 0.2


class TestWhatTheOperatorReads:
    def test_the_lines_show_the_count_the_span_and_the_mapping(self) -> None:
        lines = _offered(_FIVE, profile=_profile(10, 4)).lines
        assert lines[0] == "NOTSO suggestion for RX: P 0.13, Conf 0.16."
        assert "5 reported events (5 notices) in the 100 days the NOTSO cache covers from 01 Jan 2025 to 11 Apr 2025, " \
               "where" in lines[1]
        assert "manoeuvre and proximity operations notices count as a manoeuvre" in lines[1]
        assert "a lookup" in lines[1]
        assert lines[2].startswith("Conf 0.16 is the lower edge")

    def test_the_basis_says_it_is_a_floor_on_any_burn(self) -> None:
        assert "routine burns below the reporting threshold carry no notice" in _offered(_FIVE).lines[1]

    def test_no_line_breaks_i13(self) -> None:
        capped, prior = _offered(_FIVE, profile=_profile(10, 9)), _offered(_FIVE, profile=_profile(10, 4))
        refusals = [_prior([]), _prior(_FIVE, ActionType.NO_ACTION), _prior(_FIVE, cover=((_START, _START),)),
                    _prior(_FIVE, launched=2026),
                    _prior(_FIVE[:3], cover=((_START, _START + timedelta(days=700)),), horizon=1.0)]
        gapped = _offered(_FIVE, cover=((_START - timedelta(days=30), _START + timedelta(days=45)),
                                        (_START + timedelta(days=55), _END)), launched=2025)
        sentences = [*capped.lines, *prior.lines, *gapped.lines, *(r.reason for r in refusals if isinstance(r, NoPrior))]
        assert len(sentences) == 14
        assert [s for s in sentences if i13_problems(s)] == []

    def test_the_token_carries_the_values_shown(self) -> None:
        assert _offered(_FIVE).token == "0.13|"
        assert _offered(_FIVE, profile=_profile(10, 4)).token == "0.13|0.16"
