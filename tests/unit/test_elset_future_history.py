"""A set dated in the future never reads as current on the history and custody paths either (SPC-226, F-38, review).

The V0.42 review found three places the acceptance check's clock did not reach. The Pattern of Life history parse,
pattern_of_life.parse_tle_history_counted, ran the check with no clock, so a set 3 d ahead was kept in the history
the panel, custody and the sweep read. custody_from_history read the clamped 0.0 h of such a set and said "its orbit
is current (0.0 h old ...)". And interaction_graph._out_of_date read a negative age as within the limit, so a set
dated after now earned an approach window. Each now refuses it: the parse counts and names it with the other
refusals, custody is lost and says the set is dated in the future, and the interaction graph refuses the window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spectre.astro.elset_check import FUTURE_EPOCH_TOLERANCE
from spectre.astro.pattern_of_life import parse_tle_history, parse_tle_history_counted
from spectre.domain import interaction_graph as ig
from spectre.domain.custody import Custody
from spectre.web.elsets import elset_age
from spectre.web.routes import pol
from spectre.web.routes.pol import custody_from_history
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _history(now: datetime, *, ahead: timedelta) -> str:
    """Five daily LEO sets before *now*, and one dated *ahead* of it."""
    sets = [_tle(now - timedelta(days=d, hours=1), leo=True) for d in range(5, 0, -1)]
    sets.append(_tle(now + ahead, leo=True))
    return "\n".join(sets)


class TestTheHistoryParse:
    def test_a_set_dated_in_the_future_is_refused_counted_and_named(self) -> None:
        records, counts = parse_tle_history_counted(_history(_NOW, ahead=timedelta(days=3)), now=_NOW)
        assert len(records) == 5
        assert all(r.epoch <= _NOW for r in records)
        assert counts.refused == 1
        assert counts.refusals == (
            "its epoch, 2026-11-16 12:00 UTC, is 3.0 d after the time it was checked, 2026-11-13 12:00 UTC, more "
            "than the 5 minutes allowed for clock skew: a set dated in the future would read as current, so check its "
            "epoch and this server's clock",
        )

    def test_within_the_tolerance_it_is_kept(self) -> None:
        records, counts = parse_tle_history_counted(_history(_NOW, ahead=FUTURE_EPOCH_TOLERANCE), now=_NOW)
        assert (len(records), counts.refused) == (6, 0)

    def test_the_uncounted_parse_takes_the_clock_too(self) -> None:
        assert len(parse_tle_history(_history(_NOW, ahead=timedelta(days=3)), now=_NOW)) == 5

    def test_with_no_clock_the_parse_reads_no_date(self) -> None:
        assert len(parse_tle_history(_history(_NOW, ahead=timedelta(days=3)))) == 6

    def test_the_pol_route_reads_the_history_by_the_wall_clock(self) -> None:
        """_analyse_merged, which the panel and the sweep's held history share, refuses the set and counts it."""
        now = datetime.now(UTC)
        text = _history(now, ahead=timedelta(days=3))
        history = pol._MergedHistory(archive_text=text, merged_text=text, metadata={}, rms_metadata={}, name="RX")
        analysed = pol._analyse_merged(history, 50322, 0.001, apply_filter=False)
        assert analysed is not None
        found, _flags = analysed
        assert found.tle_count == 5
        assert found.refused_element_sets == 1
        assert "a set dated in the future would read as current" in found.refused_failures[0]


class TestCustody:
    def test_a_newest_set_dated_in_the_future_loses_custody_and_says_why(self) -> None:
        status = custody_from_history(
            _tle(_NOW + timedelta(days=3), leo=True), _NOW, pol=None, normality=None, problem="no history",
        )
        assert status.state is Custody.LOST
        assert status.sentence == (
            "Custody lost: its newest element set is dated 3.0 d in the future, so it cannot be read as current, and "
            "its warning time and its burns cannot be judged. Check the set's epoch and this server's clock."
        )
        assert "current (0.0 h old" not in status.sentence

    def test_a_set_within_the_tolerance_reads_as_now(self) -> None:
        status = custody_from_history(
            _tle(_NOW + timedelta(minutes=4), leo=True), _NOW, pol=None, normality=None, problem="no history",
        )
        assert status.state is Custody.DEGRADED
        assert "its orbit is current (0.0 h old" in status.sentence


class TestTheInteractionGraph:
    def test_a_set_dated_in_the_future_earns_no_window(self) -> None:
        age = elset_age(_tle(_NOW + timedelta(days=3), leo=True), _NOW)
        assert age is not None
        found = ig._out_of_date(ig.SetAge("red", age.epoch, age.limit_hours), _NOW)
        assert found == "the red element set is dated 3.0 d in the future, so it cannot be read as current"

    def test_exactly_at_the_tolerance_it_reads_as_now(self) -> None:
        at = ig.SetAge("red", _NOW + FUTURE_EPOCH_TOLERANCE, 24.0)
        assert ig._out_of_date(at, _NOW) is None
        past = ig.SetAge("red", _NOW + FUTURE_EPOCH_TOLERANCE + timedelta(microseconds=1), 24.0)
        assert ig._out_of_date(past, _NOW) is not None
