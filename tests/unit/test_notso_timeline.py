"""The NOTSO timeline behind an applied suggestion (SPC-131).

A suggestion rests on the notices it counted in the periods the cache covers,
less the gaps and any time before the object's launch year. The timeline lists
them in date order, each entry named by its kind in words (covered, gap,
notice, not counted), so it reads without colour, and places each on a bar
across the span from its first covered moment to the moment it was asked
for. The time from the cache's last covered moment to then is uncovered too,
and is named as such. A notice that copies an event already counted says so. No test reads the wall clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectre.astro.notso import NOTSORecord, NOTSOType
from spectre.domain.decision import ActionType
from spectre.domain.notso_prior import NotsoPrior, notso_prior
from tests.unit._i13 import i13_problems

_START = datetime(2025, 1, 1, tzinfo=UTC)
_END = _START + timedelta(days=100)


def _notice(day: float, kind: NOTSOType = NOTSOType.MANOEUVRE) -> NOTSORecord:
    at = _START + timedelta(days=day)
    return NOTSORecord(
        message_id=f"N{day}", norad_id=50322, international_designator=None, object_name=None,
        issuing_entity="JCO", issue_date_utc=at, effective_start_utc=at, effective_end_utc=at + timedelta(hours=24),
        notso_type=kind, description="", predicted_delta_v_km_s=None, predicted_direction=None, raw_message="",
    )


_FIVE = [_notice(d) for d in (5, 20, 40, 60, 80)]
_GAPPED = ((_START, _START + timedelta(days=45)), (_START + timedelta(days=55), _END))
#: The same periods, the first starting a month before the launch year RX was launched in.
_EARLY = ((_START - timedelta(days=30), _START + timedelta(days=45)), (_START + timedelta(days=55), _END))


def _offered(notices: list[NOTSORecord], **kw: object) -> NotsoPrior:
    prior = notso_prior("RX", ActionType.MANOEUVRE, notices, cover=kw.pop("cover", ((_START, _END),)),
                        horizon_hours=72.0, **kw)  # type: ignore[arg-type]
    assert isinstance(prior, NotsoPrior), prior
    return prior


class TestWhatThePriorKeeps:
    def test_it_keeps_the_periods_it_counted_and_the_notices_behind_it(self) -> None:
        prior = _offered([*_FIVE, _notice(90, NOTSOType.LAUNCH)], cover=_EARLY, launched=2025)
        assert prior.cover == _GAPPED
        assert [n.start for n in prior.counted] == [_START + timedelta(days=d) for d in (5, 20, 40, 60, 80)]
        assert {n.kind for n in prior.counted} == {NOTSOType.MANOEUVRE}


class TestTheTimeline:
    def test_it_lists_covered_periods_gaps_and_notices_in_date_order(self) -> None:
        timeline = _offered(_FIVE, cover=_GAPPED).timeline
        assert [e.kind for e in timeline] == [
            "covered", "notice", "notice", "notice", "gap", "covered", "notice", "notice",
        ]
        assert [e.start for e in timeline] == sorted(e.start for e in timeline)

    def test_each_entry_names_its_kind_and_dates_in_words(self) -> None:
        covered, first, *_, gap, _, _, last = _offered(_FIVE, cover=_GAPPED).timeline
        assert covered.text == ("Covered: 01 Jan 2025 00:00 to 15 Feb 2025 00:00 UTC, 45.0 days; notices for any "
                                "object were synced, so this time is counted.")
        assert first.text == "Notice: 06 Jan 2025 00:00 UTC, manoeuvre; event 1."
        assert gap.text == ("Gap: 15 Feb 2025 00:00 to 25 Feb 2025 00:00 UTC, 10.0 days with no notice for any "
                            "object; a gap in the cache, not quiet, so it is not counted.")
        assert last.text == "Notice: 22 Mar 2025 00:00 UTC, manoeuvre; event 5."

    def test_a_copy_of_an_event_says_it_was_counted_once(self) -> None:
        timeline = _offered([*_FIVE, _notice(5.5, NOTSOType.PROXIMITY_OPS)]).timeline
        assert [e.text for e in timeline if e.kind == "notice"][1] == (
            "Notice: 06 Jan 2025 12:00 UTC, proximity operations; a copy of event 1, counted once."
        )

    def test_time_before_the_launch_year_is_listed_as_not_counted(self) -> None:
        first = _offered(_FIVE, cover=_EARLY, launched=2025).timeline[0]
        assert first.kind == "not counted"
        assert first.text == ("Not counted: time before 01 Jan 2025, the start of RX's launch year, when it did not "
                              "exist to be reported on.")

    def test_entries_sit_on_a_bar_across_the_span(self) -> None:
        timeline = _offered(_FIVE, cover=_GAPPED).timeline
        covered, gap = timeline[0], timeline[4]
        # The bar is BAR_UNITS, 1000, wide across the 100 days from the first covered moment to the last.
        assert (covered.left, covered.width) == (0.0, 450.0)
        assert (gap.left, gap.width) == (450.0, 100.0)
        assert [e.left for e in timeline if e.kind == "notice"][0] == 50.0
        assert all(e.width == 0.0 for e in timeline if e.kind == "notice")

    def test_the_time_from_the_last_covered_moment_to_the_moment_asked_for_is_named_and_not_counted(self) -> None:
        prior = _offered(_FIVE, until=_END + timedelta(days=25, hours=12))
        assert prior.until == _END + timedelta(days=25, hours=12)
        last = prior.timeline[-1]
        assert last.kind == "gap"
        assert last.text == ("Not covered: 11 Apr 2025 00:00 to 06 May 2025 12:00 UTC, 25.5 days from the cache's "
                             "last covered moment to the time evaluated, with no notice for any object; not quiet, so "
                             "it is not counted.")

    def test_the_bar_runs_to_the_moment_asked_for(self) -> None:
        # 100 days covered and 25 not, after: the bar's 1000 units span all 125.
        timeline = _offered(_FIVE, until=_END + timedelta(days=25)).timeline
        assert (timeline[0].left, timeline[0].width) == (0.0, 800.0)
        assert (timeline[-1].left, timeline[-1].width) == (800.0, 200.0)

    def test_a_cache_covered_to_the_moment_asked_for_has_nothing_after_it(self) -> None:
        assert [e.kind for e in _offered(_FIVE, until=_END).timeline][-1] == "notice"

    def test_a_prior_built_without_its_periods_has_no_timeline(self) -> None:
        prior = _offered(_FIVE)
        bare = NotsoPrior(
            red="RX", action_type=ActionType.MANOEUVRE, probability=prior.probability, confidence=None, events=5,
            notices=5, span_start=_START, span_end=_END, covered_days=100.0, gaps=0, horizon_hours=72.0,
            mapped=prior.mapped, confidence_line="",
        )
        assert bare.timeline == ()

    def test_no_entry_breaks_i13(self) -> None:
        timeline = _offered([*_FIVE, _notice(5.5)], cover=_EARLY, launched=2025, until=_END + timedelta(days=9)).timeline
        assert [e.text for e in timeline if i13_problems(e.text)] == []
