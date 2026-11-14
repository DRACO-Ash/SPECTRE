"""The bound red track's custody, read where the sweep reads it, before the evaluation runs (SPC-123).

red_custody reads the red track's element-set history through the one held
copy the sweep and the is-this-normal panel share (pol.held_history), waits a
bounded time for a first fetch as the sweep does, and judges custody with the
sweep's own rule (pol.custody_from_history, moved out of the sweep so the two
cannot drift). No test here reaches the network: UDL is either not connected
or a history is already held.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from spectre.domain.custody import Custody, CustodyStatus
from spectre.domain.decision import BoundElset, ScenarioBinding
from spectre.domain.normality import Normality
from spectre.web import decision_custody
from spectre.web.decision_custody import red_custody, with_red_custody
from spectre.web.routes import pol, threat
from spectre.web.routes.pol import HeldHistory
from tests.unit.test_elset_freshness import _tle

_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
_SATNO = 50322
#: A bound on a test that waits, so a wait that never stops fails the test rather than stalling the suite.
_GUARD_S = 5.0


def _state(**kwargs: Any) -> Any:
    return SimpleNamespace(
        udl_username="", udl_password="", elset_histories={}, pol_reserve_resets={}, **kwargs,
    )


def _red(*, hours: float = 5.0, satno: int | None = _SATNO, tle: str | None = None) -> BoundElset:
    epoch = _NOW - timedelta(hours=hours)
    return BoundElset(
        side="red", name="RX", stk_name="RX", satno=satno, tle=tle or _tle(epoch, satno=_SATNO), data_mode="REAL",
        epoch=epoch, age_hours=hours, limit_hours=72.0,
    )


def _held_pol() -> Any:
    return SimpleNamespace(tle_count=412, span_days=190.0, history_truncated_at=None)


class TestRedCustody:
    async def test_udl_not_connected_is_degraded(self) -> None:
        status = await red_custody(_state(), _red(), _NOW)
        assert status.state is Custody.DEGRADED
        assert status.sentence == (
            "Custody degraded: its orbit is current (5.0 h old, limit 72 h, the GEO figure, set for GEO), but whether "
            "its burns are normal cannot be judged. UDL is not connected, so no element-set history is held."
        )

    async def test_a_fresh_held_history_is_held(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _state()
        state.elset_histories[_SATNO] = HeldHistory(_SATNO, _NOW - timedelta(minutes=5), pol=_held_pol())
        resets: list[Any] = []

        def evidence(history: Any, reset: Any) -> tuple[None, Any]:
            resets.append((history, reset))
            return None, SimpleNamespace(verdict=Normality.ROUTINE)

        monkeypatch.setattr(decision_custody, "history_evidence", evidence)
        state.pol_reserve_resets[_SATNO] = _NOW - timedelta(days=3)
        status = await red_custody(state, _red(), _NOW)
        assert status.state is Custody.HELD
        assert status.sentence == (
            "Custody held: its orbit is 5.0 h old (limit 72 h, the GEO figure, set for GEO) and 412 element sets over "
            "190 days judge its burns."
        )
        assert resets == [(state.elset_histories[_SATNO].pol, _NOW - timedelta(days=3))]

    async def test_a_held_history_too_short_to_judge_its_burns_is_degraded(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The latest burn's verdict is read: a history too short to judge it leaves custody degraded, not held."""
        state = _state()
        state.elset_histories[_SATNO] = HeldHistory(_SATNO, _NOW - timedelta(minutes=5), pol=_held_pol())
        monkeypatch.setattr(
            decision_custody, "history_evidence",
            lambda *_: (None, SimpleNamespace(verdict=Normality.NOT_ENOUGH_HISTORY)),
        )
        status = await red_custody(state, _red(), _NOW)
        assert status.state is Custody.DEGRADED
        assert status.sentence == (
            "Custody degraded: its orbit is current (5.0 h old, limit 72 h, the GEO figure, set for GEO), but 412 "
            "element sets over 190 days is too little history to judge its burns."
        )

    async def test_no_readable_epoch_is_lost(self) -> None:
        line1, line2 = _tle(_NOW).split("\n")
        red = dataclasses.replace(_red(), tle=f"{line1[:20]}000{line1[23:]}\n{line2}", epoch=None, age_hours=None,
                                  limit_hours=None)
        status = await red_custody(_state(), red, _NOW)
        assert status.state is Custody.LOST
        assert status.sentence.startswith("Custody lost: there is no element set with a readable epoch")

    async def test_no_catalogue_number_says_so(self) -> None:
        status = await red_custody(_state(), _red(satno=None), _NOW)
        assert status.state is Custody.DEGRADED
        assert status.sentence.endswith("The red track has no catalogue number to fetch a history for.")

    async def test_a_first_fetch_past_the_wait_is_degraded_and_carries_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        release = asyncio.Event()

        async def slow(_state: Any, satno: int, now: datetime) -> HeldHistory:
            await release.wait()
            return HeldHistory(satno, now, problem="done")

        monkeypatch.setattr(decision_custody, "held_history", slow)
        try:
            status = await asyncio.wait_for(red_custody(_state(), _red(), _NOW, wait_s=0.01), timeout=_GUARD_S)
        except TimeoutError:
            release.set()
            pytest.fail(f"red_custody was still waiting after {_GUARD_S} s, so it ignored its 0.01 s wait")
        assert status.state is Custody.DEGRADED
        assert status.sentence.endswith("Its element-set history is still loading from UDL; the next evaluation will use it.")
        assert len(decision_custody._HISTORY_TASKS) == 1   # the fetch carries on, held so it is not collected
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not decision_custody._HISTORY_TASKS


class TestTheSweepAndTheEvaluationShareOneRule:
    def test_the_sweep_reads_custody_through_the_shared_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []

        def shared(red_tle: str, now: datetime, **kwargs: Any) -> CustodyStatus:
            calls.append({"tle": red_tle, "now": now, **kwargs})
            return CustodyStatus(Custody.HELD, "held")

        monkeypatch.setattr(threat, "custody_from_history", shared)
        history = threat._RedHistory(_held_pol(), None, SimpleNamespace(verdict=Normality.ROUTINE), "", None)
        assert threat._red_custody("TLE", history, _NOW).sentence == "held"
        assert calls == [{
            "tle": "TLE", "now": _NOW, "pol": history.pol, "normality": history.normality, "problem": "",
        }]

    def test_the_shared_rule_reads_age_history_and_verdict(self) -> None:
        status = pol.custody_from_history(
            _tle(_NOW - timedelta(hours=5)), _NOW, pol=_held_pol(), normality=SimpleNamespace(verdict=Normality.ROUTINE),
            problem="",
        )
        assert status.state is Custody.HELD

    def test_the_shared_rule_reads_the_gap_udls_record_cap_left(self) -> None:
        """A history UDL's record cap cut short leaves custody degraded, for the sweep and the evaluation alike."""
        capped = SimpleNamespace(tle_count=412, span_days=190.0, history_truncated_at=_NOW - timedelta(days=20))
        status = pol.custody_from_history(
            _tle(_NOW - timedelta(hours=5)), _NOW, pol=capped, normality=SimpleNamespace(verdict=Normality.ROUTINE),
            problem="",
        )
        assert status.state is Custody.DEGRADED
        assert "its history is missing after 2026-10-14, where UDL's record cap cut it" in status.sentence


class TestWithRedCustody:
    def test_it_sets_custody_on_red_only(self) -> None:
        blue = dataclasses.replace(_red(), side="blue", satno=40001)
        status = CustodyStatus(Custody.HELD, "held")
        binding = with_red_custody(ScenarioBinding(red=_red(), blue=blue), status)
        assert binding.red is not None and binding.red.custody is status
        assert binding.blue == blue

    def test_a_binding_with_no_red_is_returned_as_it_is(self) -> None:
        binding = ScenarioBinding(blue=dataclasses.replace(_red(), side="blue"))
        assert with_red_custody(binding, CustodyStatus(Custody.HELD, "held")) is binding
