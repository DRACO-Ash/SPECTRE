"""An interval on each NOTSO-derived probability (SPC-132).

P is the chance of at least one reported event within the horizon, at the rate
of k reported events over the T hours the NOTSO cache covers. k is a count of
events over an exposure time, so its uncertainty is a Poisson one, and at the
handful of events a suggestion rests on (MIN_EVENTS is 3) a normal
approximation runs below 0. The interval is therefore the exact (Garwood) 95 in
100 interval on the Poisson mean behind k, carried over the horizon the same
way P is. Its edges are rounded outward, so the interval never reads narrower
than it is, and a lower edge under the hundredth reads "under 0.01", never 0.
No test reads the wall clock.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from scipy.stats import chi2

from spectre.astro.notso import NOTSORecord, NOTSOType
from spectre.domain.decision import ActionType
from spectre.domain.notso_prior import NoPrior, NotsoPrior, notso_prior, poisson_interval
from tests.unit._i13 import i13_problems

_START = datetime(2025, 1, 1, tzinfo=UTC)


def _notice(day: float) -> NOTSORecord:
    at = _START + timedelta(days=day)
    return NOTSORecord(
        message_id=f"N{day}", norad_id=50322, international_designator=None, object_name=None,
        issuing_entity="JCO", issue_date_utc=at, effective_start_utc=at, effective_end_utc=at + timedelta(hours=24),
        notso_type=NOTSOType.MANOEUVRE, description="", predicted_delta_v_km_s=None, predicted_direction=None,
        raw_message="",
    )


def _offered(events: int, days: float, horizon: float = 72.0) -> NotsoPrior:
    """*events* notices two days apart from day 1, over *days* of cover."""
    notices = [_notice(1 + 2 * i) for i in range(events)]
    prior = notso_prior("RX", ActionType.MANOEUVRE, notices, cover=((_START, _START + timedelta(days=days)),),
                        horizon_hours=horizon)
    assert isinstance(prior, NotsoPrior), prior
    return prior


def _chance(mean: float, prior: NotsoPrior) -> float:
    return 1.0 - math.exp(-mean * prior.horizon_hours / (prior.covered_days * 24.0))


class TestTheMethod:
    @pytest.mark.parametrize("events", [3, 5, 12, 40])
    def test_it_is_the_exact_poisson_interval_on_the_count(self, events: int) -> None:
        # Garwood: the lower limit is half the chi-square quantile at 0.025 on 2k degrees of freedom, the upper half
        # the quantile at 0.975 on 2k + 2.
        low, high = poisson_interval(events)
        assert math.isclose(low, chi2.ppf(0.025, 2 * events) / 2.0, rel_tol=1e-9)
        assert math.isclose(high, chi2.ppf(0.975, 2 * events + 2) / 2.0, rel_tol=1e-9)

    def test_its_lower_limit_never_runs_below_0_at_the_floor(self) -> None:
        # A normal interval at k = 3 is 3 - 1.96 x 1.73, below 0; the exact one stays above it.
        assert poisson_interval(3)[0] > 0.0

    def test_a_count_of_none_has_no_interval_here(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            poisson_interval(0)


class TestTheIntervalOnP:
    def test_it_is_carried_over_the_horizon_as_p_is_and_rounded_outward(self) -> None:
        # 5 events over 100 days, 72 h: P 0.139 floored to 0.13; the counts 1.62 and 11.67 give 0.048 and 0.295.
        prior = _offered(5, 100.0)
        assert prior.probability == 0.13
        assert (prior.interval.low, prior.interval.high) == (0.04, 0.30)

    @pytest.mark.parametrize(("events", "days", "horizon"), [
        (3, 100.0, 72.0), (5, 100.0, 72.0), (5, 200.0, 720.0), (12, 30.0, 24.0), (40, 365.0, 168.0), (3, 200.0, 72.0),
    ])
    def test_the_rounded_edges_hold_the_exact_interval_and_p(self, events: int, days: float, horizon: float) -> None:
        prior = _offered(events, days, horizon)
        low, high = poisson_interval(events)
        interval = prior.interval
        assert interval.low <= _chance(low, prior)
        assert interval.checked_low == (interval.low if interval.low > 0.0 else pytest.approx(_chance(low, prior)))
        assert interval.low <= prior.probability <= interval.high
        assert interval.high >= _chance(high, prior)
        assert interval.checked_low <= prior.probability

    def test_fewer_events_at_the_same_rate_give_a_wider_interval(self) -> None:
        sparse, dense = _offered(3, 60.0).interval, _offered(30, 600.0).interval
        assert sparse.high - sparse.low > dense.high - dense.low

    def test_the_upper_edge_never_passes_1(self) -> None:
        # 20 events over 100 days carried over 720 h: P 0.99, and the upper count, 30.9, gives 0.9999.
        prior = _offered(20, 100.0, 720.0)
        assert prior.probability == 0.99
        assert prior.interval.high == 1.0

    def test_a_lower_edge_under_the_hundredth_reads_under_0_01_never_0(self) -> None:
        prior = _offered(3, 200.0)
        assert prior.interval.low == 0.0
        assert 0.0 < prior.interval.checked_low < 0.01
        assert "under 0.01 to 0.13" in prior.interval_line
        assert "0.00" not in prior.interval_line


class TestWhatTheOperatorReads:
    def test_the_line_states_the_interval_the_method_and_why_it_suits(self) -> None:
        line = _offered(5, 100.0).interval_line
        assert line.startswith("P 0.13 lies in 0.04 to 0.30, an exact Poisson interval, 95 in 100, on the 5 reported "
                               "events in the 100 days covered, carried over 72 h as P is.")
        assert ("It is exact, not approximate, because a suggestion can rest on as few as 3 events, where an "
                "approximate interval runs below 0; the exact one keeps its 95 in 100 at any count and errs wide.") in line

    def test_why_it_is_exact_holds_at_a_count_where_an_approximate_interval_would_not_run_below_0(self) -> None:
        # At 40 events a normal interval is 40 +/- 1.96 x 6.3, well above 0: the reason given must not say otherwise.
        line = _offered(40, 365.0, 168.0).interval_line
        assert "at so few events" not in line
        assert "because a suggestion can rest on as few as 3 events" in line

    def test_the_line_says_only_expected_value_reads_p(self) -> None:
        assert "Only expected value reads P; minimax and minimin ignore it." in _offered(5, 100.0).interval_line

    def test_no_line_breaks_i13(self) -> None:
        lines = [_offered(*case).interval_line for case in ((5, 100.0), (3, 200.0), (20, 100.0, 720.0))]
        sentences = [s for line in lines for s in line.split(". ")]
        assert [s for s in sentences if i13_problems(s)] == []

    def test_nothing_offered_has_no_interval(self) -> None:
        refused = notso_prior("RX", ActionType.MANOEUVRE, [], cover=((_START, _START + timedelta(days=9)),),
                              horizon_hours=72.0)
        assert isinstance(refused, NoPrior)
        assert not hasattr(refused, "interval")
