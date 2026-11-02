"""Decide-by: the fastest credible arrival minus the response time (SPC-008, output 3).

Hand cases: arrivals placed by construction so every expected time can be read
off the input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.domain.decide_by import (
    DEFAULT_RESPONSE_H,
    Due,
    decide_by,
    earliest_arrival,
    parse_response_hours,
    withheld,
)

_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


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
        result = decide_by(earliest_arrival([_entry("BLUE-1", 0.0, 23.0)], 500.0), 12.0, False, _NOW, 500.0)
        assert result.due is Due.SET
        assert result.decide_at == _NOW + timedelta(hours=11)
        assert result.sentence == (
            "Decide by 21:00 UTC on 2 Nov for BLUE-1: its fastest intercept within 500 m/s could arrive at "
            "09:00 UTC on 3 Nov, and that is your response time of 12 h."
        )

    def test_the_default_says_it_is_the_default(self) -> None:
        result = decide_by(earliest_arrival([_entry("BLUE-1", 0.0, 23.0)], 500.0), DEFAULT_RESPONSE_H, True, _NOW, 500.0)
        assert "the default response time of 12 h, which you have not set" in result.sentence

    def test_inside_the_response_time_it_has_passed(self) -> None:
        result = decide_by(earliest_arrival([_entry("BLUE-1", 0.0, 4.0)], 500.0), 12.0, False, _NOW, 500.0)
        assert result.due is Due.PASSED
        assert result.sentence == (
            "Decide-by has passed for BLUE-1: an intercept could arrive at 14:00 UTC on 2 Nov, 4.0 h from now, "
            "inside your response time of 12 h."
        )

    def test_exactly_at_the_response_time_has_passed(self) -> None:
        assert decide_by(earliest_arrival([_entry("A", 0.0, 12.0)], 500.0), 12.0, False, _NOW, 500.0).due is Due.PASSED

    def test_nothing_in_reach(self) -> None:
        result = decide_by(None, 12.0, True, _NOW, 500.0)
        assert result.due is Due.NONE
        assert result.sentence == "No decide-by: no target is in reach within 500 m/s."

    def test_withheld_says_why(self) -> None:
        assert withheld("custody is lost").sentence == "No decide-by: custody is lost."


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
        state = SimpleNamespace(response_time_h=None)
        held = CustodyStatus(Custody.HELD, "Custody held.")
        entries = [_entry("BLUE-1", 0.0, 23.0)]
        result = threat._sweep_decide_by(state, entries, held, {"capability_level": "MINIMAL"}, basis)  # type: ignore[arg-type]
        assert result.sentence == "No decide-by: the interceptor is assessed unable to fly the intercept (capability MINIMAL)."
        assert threat._sweep_decide_by(state, entries, held, {"capability_level": "HIGH"}, basis).due is Due.SET  # type: ignore[arg-type]
