"""Decide-by: the earliest decide-at across the targets in reach (SPC-008, output 3; SPC-022).

Each target's decide-at is its fastest credible arrival minus the response
time for it: its own where the operator set one, else the sign-in's, else the
12 h default. Hand cases: arrivals placed by construction so every expected
time can be read off the input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.domain.decide_by import (
    Due,
    ResponseTimes,
    decide_by,
    earliest_arrival,
    parse_response_hours,
    withheld,
)

_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


_SET_12 = ResponseTimes(sign_in=12.0)


def _entry(name: str, burn_in_h: float, tof_h: float, dv: float = 100.0) -> SimpleNamespace:
    return SimpleNamespace(target=SimpleNamespace(target_name=name), burn_epoch=_NOW + timedelta(hours=burn_in_h),
                           tof_hours=tof_h, delta_v_m_s=dv)


class TestEarliestArrival:
    def test_a_later_burn_on_a_faster_transfer_arrives_first(self) -> None:
        slow_now, fast_later = _entry("A", 0.0, 20.0), _entry("B", 4.0, 3.0)
        at, entry = earliest_arrival([slow_now, fast_later], 500.0)  # type: ignore[misc]
        assert entry is fast_later and at == _NOW + timedelta(hours=7)

    def test_an_intercept_over_budget_is_not_credible(self) -> None:
        assert earliest_arrival([_entry("A", 0.0, 1.0, dv=600.0)], 500.0) is None


class TestDecideBy:
    def test_arrival_minus_the_response_time(self) -> None:
        result = decide_by([_entry("BLUE-1", 0.0, 23.0)], _SET_12, _NOW, 500.0)
        assert result.due is Due.SET
        assert result.decide_at == _NOW + timedelta(hours=11)
        assert result.sentence == (
            "Decide by 21:00 UTC on 2 Nov for BLUE-1: its fastest intercept within 500 m/s could arrive at "
            "09:00 UTC on 3 Nov, and that is your response time of 12 h."
        )

    def test_the_default_says_it_is_the_default(self) -> None:
        result = decide_by([_entry("BLUE-1", 0.0, 23.0)], ResponseTimes(), _NOW, 500.0)
        assert result.decide_at == _NOW + timedelta(hours=11)
        assert "the default response time of 12 h, which you have not set" in result.sentence

    def test_inside_the_response_time_it_has_passed(self) -> None:
        result = decide_by([_entry("BLUE-1", 0.0, 4.0)], _SET_12, _NOW, 500.0)
        assert result.due is Due.PASSED
        assert result.sentence == (
            "Decide-by has passed for BLUE-1: an intercept could arrive at 14:00 UTC on 2 Nov, 4.0 h from now, "
            "inside your response time of 12 h."
        )

    def test_exactly_at_the_response_time_has_passed(self) -> None:
        assert decide_by([_entry("A", 0.0, 12.0)], _SET_12, _NOW, 500.0).due is Due.PASSED

    def test_nothing_in_reach(self) -> None:
        result = decide_by([_entry("BLUE-1", 0.0, 1.0, dv=600.0)], ResponseTimes(), _NOW, 500.0)
        assert result.due is Due.NONE
        assert result.sentence == "No decide-by: no target is in reach within 500 m/s."

    def test_withheld_says_why(self) -> None:
        assert withheld("custody is lost").sentence == "No decide-by: custody is lost."


class TestEachTargetHasItsOwnResponseTime:
    """SPC-022: one response time per sign-in became one per target, so the earliest arrival is not the answer."""

    def test_a_later_arrival_with_a_longer_response_time_decides_first(self) -> None:
        """BLUE-1 arrives at +10 h with 2 h to respond (decide +8 h); BLUE-2 at +14 h with 12 h (decide +2 h)."""
        times = ResponseTimes(by_target={"BLUE-1": 2.0, "BLUE-2": 12.0})
        result = decide_by([_entry("BLUE-1", 0.0, 10.0), _entry("BLUE-2", 2.0, 12.0)], times, _NOW, 500.0)
        assert (result.due, result.target) == (Due.SET, "BLUE-2")
        assert (result.decide_at, result.arrival) == (_NOW + timedelta(hours=2), _NOW + timedelta(hours=14))
        assert result.sentence == (
            "Decide by 12:00 UTC on 2 Nov for BLUE-2: its fastest intercept within 500 m/s could arrive at "
            "00:00 UTC on 3 Nov, and that is your response time for BLUE-2 of 12 h."
        )

    def test_the_default_on_a_later_arrival_beats_a_short_time_set_for_an_earlier_one(self) -> None:
        """BLUE-1 set to 1 h arrives at +6 h (decide +5 h); BLUE-2, nothing set, at +16 h on the default (+4 h)."""
        times = ResponseTimes(by_target={"BLUE-1": 1.0})
        result = decide_by([_entry("BLUE-1", 0.0, 6.0), _entry("BLUE-2", 0.0, 16.0)], times, _NOW, 500.0)
        assert (result.target, result.decide_at) == ("BLUE-2", _NOW + timedelta(hours=4))
        assert result.sentence.endswith("and that is the default response time of 12 h, which you have not set.")

    def test_the_sign_ins_time_covers_a_target_with_none_of_its_own(self) -> None:
        """BLUE-1 set to 3 h arrives at +9 h (decide +6 h); BLUE-2 on the sign-in's 8 h arrives at +12 h (+4 h)."""
        times = ResponseTimes(sign_in=8.0, by_target={"BLUE-1": 3.0})
        result = decide_by([_entry("BLUE-1", 0.0, 9.0), _entry("BLUE-2", 1.0, 11.0)], times, _NOW, 500.0)
        assert (result.target, result.decide_at) == ("BLUE-2", _NOW + timedelta(hours=4))
        assert result.sentence.endswith("and that is your response time of 8 h.")

    def test_a_targets_own_time_outranks_the_sign_ins(self) -> None:
        """BLUE-1 alone, arriving at +10 h: its own 6 h, not the sign-in's 2 h, gives +4 h."""
        times = ResponseTimes(sign_in=2.0, by_target={"BLUE-1": 6.0})
        result = decide_by([_entry("BLUE-1", 0.0, 10.0)], times, _NOW, 500.0)
        assert result.decide_at == _NOW + timedelta(hours=4)
        assert result.sentence.endswith("and that is your response time for BLUE-1 of 6 h.")

    def test_passed_on_a_later_arrival_is_still_the_one_shown(self) -> None:
        """BLUE-1 arrives first at +5 h with 1 h (decide +4 h); BLUE-2 at +8 h with 10 h has passed."""
        times = ResponseTimes(by_target={"BLUE-1": 1.0, "BLUE-2": 10.0})
        result = decide_by([_entry("BLUE-1", 0.0, 5.0), _entry("BLUE-2", 0.0, 8.0)], times, _NOW, 500.0)
        assert (result.due, result.target) == (Due.PASSED, "BLUE-2")
        assert result.sentence == (
            "Decide-by has passed for BLUE-2: an intercept could arrive at 18:00 UTC on 2 Nov, 8.0 h from now, "
            "inside your response time for BLUE-2 of 10 h."
        )

    def test_a_tie_goes_to_the_sooner_arrival(self) -> None:
        """Both decide at +4 h: BLUE-1 arriving at +6 h is named before BLUE-2 arriving at +10 h."""
        times = ResponseTimes(by_target={"BLUE-1": 2.0, "BLUE-2": 6.0})
        result = decide_by([_entry("BLUE-2", 0.0, 10.0), _entry("BLUE-1", 0.0, 6.0)], times, _NOW, 500.0)
        assert (result.target, result.decide_at) == ("BLUE-1", _NOW + timedelta(hours=4))

    def test_a_target_out_of_budget_sets_no_deadline(self) -> None:
        """BLUE-2 would decide first on its 12 h, but only beyond the budget, so BLUE-1 is the answer."""
        times = ResponseTimes(by_target={"BLUE-1": 1.0, "BLUE-2": 12.0})
        result = decide_by([_entry("BLUE-1", 0.0, 6.0), _entry("BLUE-2", 0.0, 13.0, dv=600.0)], times, _NOW, 500.0)
        assert (result.target, result.decide_at) == ("BLUE-1", _NOW + timedelta(hours=5))


class TestTheResponseTimeField:
    @pytest.mark.parametrize(("raw", "expected"), [("", None), ("  ", None), ("6", 6.0), ("1.5", 1.5), ("168", 168.0)])
    def test_good_values(self, raw: str, expected: float | None) -> None:
        assert parse_response_hours(raw) == (expected, "")

    @pytest.mark.parametrize("raw", ["0", "-3", "169", "nan", "inf", "soon"])
    def test_bad_values_are_refused_with_a_reason(self, raw: str) -> None:
        hours, problem = parse_response_hours(raw)
        assert hours is None and problem.startswith("Response time must be")


class TestTheSweepWithholdsIt:
    """The route's rule: no decide-by for an object assessed unable to fly the intercept."""

    def test_capability_minimal_withholds_it(self) -> None:
        from spectre.domain.custody import Custody, CustodyStatus
        from spectre.web.routes import threat

        basis = SimpleNamespace(max_dv_m_s=500.0, now=_NOW)
        state = SimpleNamespace(response_time_h=None, response_time_by_target={})
        held = CustodyStatus(Custody.HELD, "Custody held.")
        entries = [_entry("BLUE-1", 0.0, 23.0)]
        result = threat._sweep_decide_by(state, entries, held, {"capability_level": "MINIMAL"}, basis)  # type: ignore[arg-type]
        assert result.sentence == "No decide-by: the interceptor is assessed unable to fly the intercept (capability MINIMAL)."
        assert threat._sweep_decide_by(state, entries, held, {"capability_level": "HIGH"}, basis).due is Due.SET  # type: ignore[arg-type]
