"""Decide-by: the earliest decide-at across the targets in reach (SPC-008, output 3; SPC-022).

Each target's decide-at is its fastest credible arrival minus the response
time for it: its own where the operator set one, else the sign-in's. With
neither set for a target in reach there is no decide-by: it says it needs a
response time and shows no time (SPC-211, evaluation F-23, the lead's ruling;
until 0.38.0 a 12 h default chosen by the developer, "tuned, not sourced",
stood in). Hand cases: arrivals placed by construction so every expected time
can be read off the input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from spectre.domain import decide_by as decide_by_module
from spectre.domain.decide_by import (
    NEEDS_TIME,
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
        result = decide_by([_entry("BLUE-1", 0.0, 1.0, dv=600.0)], _SET_12, _NOW, 500.0)
        assert result.due is Due.NONE
        assert result.sentence == "No decide-by: no target is in reach within 500 m/s."

    def test_withheld_says_why(self) -> None:
        assert withheld("custody is lost").sentence == "No decide-by: custody is lost."


class TestItNeedsAnOperatorSetResponseTime:
    """SPC-211 (evaluation F-23): with no response time set, decide-by says it needs one and shows no time."""

    def test_with_none_set_it_says_it_needs_one_and_shows_no_time(self) -> None:
        result = decide_by([_entry("BLUE-1", 0.0, 23.0)], ResponseTimes(), _NOW, 500.0)
        assert result.due is Due.NEEDS_TIME
        assert (result.decide_at, result.arrival) == (None, None)
        assert result.target == "BLUE-1"
        assert result.sentence == (
            "No decide-by: it needs your response time, the hours you need to plan, approve and carry out a "
            "response, and none is set for BLUE-1. Set it on the sweep form, for every target or for one, and sweep "
            "again."
        )
        assert result.sentence == NEEDS_TIME.format(targets="BLUE-1")
        assert "UTC" not in result.sentence and "12 h" not in result.sentence

    def test_a_target_in_reach_with_none_set_holds_it_back_and_is_named(self) -> None:
        """BLUE-1 set to 1 h arrives at +6 h; BLUE-2, nothing set, at +16 h could need deciding first on any time,
        so no time is shown, and BLUE-2 is named as the one that needs one."""
        times = ResponseTimes(by_target={"BLUE-1": 1.0})
        result = decide_by([_entry("BLUE-1", 0.0, 6.0), _entry("BLUE-2", 0.0, 16.0)], times, _NOW, 500.0)
        assert (result.due, result.decide_at, result.target) == (Due.NEEDS_TIME, None, "BLUE-2")
        assert result.sentence == NEEDS_TIME.format(targets="BLUE-2")

    def test_every_target_with_none_set_is_named_in_the_order_they_arrive(self) -> None:
        entries = [_entry("BLUE-2", 0.0, 9.0), _entry("BLUE-1", 0.0, 4.0), _entry("BLUE-3", 0.0, 7.0),
                   _entry("BLUE-1", 1.0, 9.0)]
        result = decide_by(entries, ResponseTimes(), _NOW, 500.0)
        assert result.sentence == NEEDS_TIME.format(targets="BLUE-1, BLUE-3 and BLUE-2")

    def test_a_target_out_of_reach_needs_none(self) -> None:
        times = ResponseTimes(by_target={"BLUE-1": 1.0})
        result = decide_by([_entry("BLUE-1", 0.0, 6.0), _entry("BLUE-2", 0.0, 3.0, dv=600.0)], times, _NOW, 500.0)
        assert (result.due, result.target, result.decide_at) == (Due.SET, "BLUE-1", _NOW + timedelta(hours=5))

    def test_with_nothing_in_reach_it_says_so_whatever_is_set(self) -> None:
        result = decide_by([_entry("BLUE-1", 0.0, 1.0, dv=600.0)], ResponseTimes(), _NOW, 500.0)
        assert result.due is Due.NONE
        assert result.sentence == "No decide-by: no target is in reach within 500 m/s."

    def test_no_default_is_left_to_stand_in(self) -> None:
        assert not hasattr(decide_by_module, "DEFAULT_RESPONSE_H")
        assert ResponseTimes().for_target("BLUE-1") is None
        assert ResponseTimes(sign_in=3.0).for_target("BLUE-1") == (3.0, "your response time of 3 h")


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
    """The route's rule (SPC-167): capability MINIMAL alone no longer silences the clock.

    Only an earned MINIMAL Threat ceiling withholds it, which
    test_threat_understanding_sweep pins; a legacy MINIMAL with no Threat
    Understanding behind it keeps decide-by and says why.
    """

    def test_capability_minimal_alone_keeps_it(self) -> None:
        from spectre.domain.custody import Custody, CustodyStatus
        from spectre.web.routes import threat

        basis = SimpleNamespace(max_dv_m_s=500.0, now=_NOW)
        state = SimpleNamespace(response_time_h=12.0, response_time_by_target={})
        held = CustodyStatus(Custody.HELD, "Custody held.")
        entries = [_entry("BLUE-1", 0.0, 23.0)]
        minimal = {"capability_level": "MINIMAL", "incapacity": "the recorded status 'Degraded', declared, not observed"}
        result = threat._sweep_decide_by(state, entries, held, (minimal, None), basis)  # type: ignore[arg-type]
        assert result.due is Due.SET
        assert result.sentence.endswith(
            "Capability reads MINIMAL on the recorded status 'Degraded', declared, not observed, but the evidence "
            "behind it could not be assessed, so decide-by stands.")
        high = threat._sweep_decide_by(state, entries, held, ({"capability_level": "HIGH"}, None), basis)  # type: ignore[arg-type]
        assert high.due is Due.SET and "Capability reads" not in high.sentence


class TestARecordStoredWithTheDefaultReplaysAsStored:
    """SPC-211: a decision record keeps the sweep's decide-by in its stored Threat picture, the time and the sentence
    as the sweep set them, and a replay reads them back as stored; decide_by is never run again. So a record whose
    decide-by rested on the old 12 h default replays exactly, and still says it was the default."""

    _DEFAULT = (
        "Decide by 18:00 UTC on 17 Oct for BLUE_1: its fastest intercept within 500 m/s could arrive at 06:00 UTC "
        "on 18 Oct, and that is the default response time of 12 h, which you have not set."
    )

    def test_it_replays_exactly_with_the_decide_by_it_was_shown(self) -> None:
        import dataclasses

        from spectre.domain.decision import SelectorStrategy
        from spectre.domain.decision_tree import evaluate_tree
        from spectre.web.decision_record import Operator, new_record, replay_record, stored_of
        from tests.unit.test_decision_inputs import _with_picture
        from tests.unit.test_decision_replay import _alone

        scenario = _with_picture()
        assert scenario.threat is not None
        old = dataclasses.replace(scenario, threat=dataclasses.replace(scenario.threat, decide_by=self._DEFAULT))
        result = evaluate_tree(old, SelectorStrategy.MINIMAX)
        row = new_record(result, Operator(7, "alice"), _NOW, primary=SelectorStrategy.MINIMAX)
        row.id = 1
        row = _alone(row)
        stored = stored_of(row).scenario.threat
        assert stored is not None
        assert (stored.decide_by, stored.decide_at) == (self._DEFAULT, scenario.threat.decide_at)
        done = replay_record(row)
        assert done.matches, done.lines


class TestTheFormsOfferNoDefault:
    """SPC-211: the sweep form's response time fields neither promise a 12 h default nor show one as a placeholder."""

    _TEMPLATES = ("operator.html", "partials/sweep_target_config.html")

    @pytest.mark.parametrize("name", _TEMPLATES)
    def test_no_default_is_promised_or_shown(self, name: str) -> None:
        from pathlib import Path

        text = (Path(__file__).resolve().parents[2] / "spectre" / "web" / "templates" / name).read_text("utf-8")
        assert "12 hours" not in text and "12 h default" not in text
        assert 'placeholder="12"' not in text
        assert "decide-by says it needs one" in " ".join(text.split())


class TestNoDefaultIsImpliedAnywhere:
    """Review of 0.38.0 (SPC-211): with no response time set, nothing on the sweep says decide-by stands, and no
    sentence or note says a default is used."""

    def test_a_capability_minimal_note_is_not_added_to_a_decide_by_that_needs_a_time(self) -> None:
        from spectre.domain.custody import Custody, CustodyStatus
        from spectre.web.routes import threat

        basis = SimpleNamespace(max_dv_m_s=500.0, now=_NOW)
        state = SimpleNamespace(response_time_h=None, response_time_by_target={})
        held = CustodyStatus(Custody.HELD, "Custody held.")
        minimal = {"capability_level": "MINIMAL", "incapacity": "the recorded status 'Degraded'"}
        args = (state, [_entry("BLUE-1", 0.0, 23.0)], held, (minimal, None), basis)
        result = threat._sweep_decide_by(*args)  # type: ignore[arg-type]
        assert result.due is Due.NEEDS_TIME
        assert result.sentence == NEEDS_TIME.format(targets="BLUE-1")

    def test_a_refused_response_time_does_not_claim_one_is_set(self) -> None:
        from spectre.web.routes import threat

        errors: list[str] = []
        state = SimpleNamespace(response_time_h=None)
        threat._take_response_time(state, "500", errors)
        assert errors == [
            "Response time must be more than 0 and at most 168 hours. The response time held, if any, is unchanged; "
            "with none set, decide-by says it needs one."
        ]
        assert state.response_time_h is None

    def test_the_session_and_the_picture_describe_no_default(self) -> None:
        import inspect
        from pathlib import Path

        from spectre.domain.decision import ThreatPicture

        root = Path(__file__).resolve().parents[2]
        state = " ".join((root / "spectre" / "web" / "planning_state.py").read_text("utf-8").split())
        assert "the default is used" not in state and "else the default" not in state
        assert "decide-by says it needs one" in state
        doc = " ".join((inspect.getdoc(ThreatPicture) or "").split())
        assert "the first target in reach with no response time set" in doc
