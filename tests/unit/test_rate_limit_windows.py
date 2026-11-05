"""The sliding window's edges, on a clock the test holds (SPC-071).

The mutation run over spectre/web/rate_limit.py found that no test ever let a
window elapse: deleting the line that forgets an old call, in either
is_allowed or is_blocked, left the suite green, and so did evicting a key whose
newest call sat exactly on the window's edge. The clock here is the module's
own ``time``, replaced, so nothing waits and nothing depends on the wall clock.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from spectre.web import rate_limit
from spectre.web.rate_limit import SlidingWindowLimiter


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    held = _Clock(1_000.0)
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(monotonic=held.monotonic))
    return held


def _allowed(limiter: SlidingWindowLimiter, key: str) -> bool:
    return asyncio.run(limiter.is_allowed(key))


def _blocked(limiter: SlidingWindowLimiter, key: str) -> bool:
    return asyncio.run(limiter.is_blocked(key))


class TestAnElapsedCallIsForgotten:
    def test_is_allowed_drops_calls_older_than_the_window_and_keeps_newer_ones(self, clock: _Clock) -> None:
        limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0)
        assert _allowed(limiter, "k")          # t = 1000
        clock.now += 8.0
        assert _allowed(limiter, "k")          # t = 1008, budget spent
        assert not _allowed(limiter, "k")
        clock.now += 4.0                       # t = 1012: the first call has left the window, the second has not
        assert _allowed(limiter, "k")
        assert not _allowed(limiter, "k"), "the call at 1008 still counts, so the budget is spent again"

    def test_is_blocked_forgets_an_elapsed_call_without_charging(self, clock: _Clock) -> None:
        limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10.0)
        assert _allowed(limiter, "k")
        clock.now += 8.0
        assert _allowed(limiter, "k")
        assert _blocked(limiter, "k")
        clock.now += 4.0
        assert not _blocked(limiter, "k")
        assert not _blocked(limiter, "k"), "asking whether a key is blocked must not charge it"

    def test_a_call_exactly_one_window_old_still_counts(self, clock: _Clock) -> None:
        """The window is closed at its far edge: older than the window is forgotten, as old as it is not.

        The sweep that drops whole keys must agree with the per-call prune. Here
        the sweep is due at the same moment, and a sweep that dropped the key at
        the edge would hand back a fresh budget the prune would have refused.
        """
        limiter = SlidingWindowLimiter(max_calls=1, window_seconds=10.0)
        assert _allowed(limiter, "k")
        clock.now += 10.0
        assert not _allowed(limiter, "k")
        clock.now += 0.5
        assert _allowed(limiter, "k")


class TestTheSweep:
    def test_the_sweep_runs_once_a_window_to_the_moment(self, clock: _Clock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Whole keys are swept once per window: due exactly one window after the last sweep, not before.

        Each sweep walks every key, so it is held to one a window; a key gone
        quiet for over a window is dropped by the first sweep due.
        """
        limiter = SlidingWindowLimiter(max_calls=5, window_seconds=10.0)
        monkeypatch.setattr(limiter, "_last_sweep", clock.now - 0.5)
        assert _allowed(limiter, "quiet")
        clock.now += 9.5
        assert _allowed(limiter, "busy")  # due to the moment: swept, but "quiet" is only 9.5 s old
        assert limiter._last_sweep == clock.now
        clock.now += 1.0
        assert _allowed(limiter, "busy")  # "quiet" is now 10.5 s old, but no sweep is due for 9 s
        assert "quiet" in limiter._calls
        clock.now += 9.0
        assert _allowed(limiter, "busy")  # due again, to the moment
        assert "quiet" not in limiter._calls


class TestALongKeyIsClamped:
    def test_keys_that_agree_for_64_characters_share_one_budget(self, clock: _Clock) -> None:
        """64 is the username column's width; a longer key cannot buy a fresh budget by varying its tail."""
        limiter = SlidingWindowLimiter(max_calls=1, window_seconds=10.0)
        assert _allowed(limiter, "a" * 64 + "first-tail")
        assert not _allowed(limiter, "a" * 64 + "second-tail")
        assert _allowed(limiter, "a" * 63 + "b")


class TestEachTierHoldsItsDocumentedBudget:
    """The module's own limiters, at the figures the module docstring states, and named when they refuse."""

    @pytest.mark.parametrize("tier", [
        (rate_limit.udl_auth_rate_limit, rate_limit._udl_auth_limiter, "UDL authentication", 5, 60.0),
        (rate_limit.udl_data_rate_limit, rate_limit._udl_data_limiter, "UDL data", 60, 60.0),
        (rate_limit.udl_sync_rate_limit, rate_limit._udl_sync_limiter, "UDL sync", 3, 600.0),
        (rate_limit.pol_compute_rate_limit, rate_limit._pol_compute_limiter, "PoL computation", 10, 60.0),
    ], ids=["udl-auth", "udl-data", "udl-sync", "pol-compute"])
    def test_the_budget_the_window_and_the_refusal(
        self, clock: _Clock, monkeypatch: pytest.MonkeyPatch,
        tier: tuple[Any, SlidingWindowLimiter, str, int, float],
    ) -> None:
        dependency, limiter, label, budget, window = tier
        # The module's own limiter keeps its budget and window; only its record of calls is this test's.
        monkeypatch.setattr(limiter, "_calls", type(limiter._calls)(limiter._calls.default_factory))
        monkeypatch.setattr(limiter, "_last_sweep", clock.now)
        user = SimpleNamespace(username="tier-budget-operator")

        async def refused() -> HTTPException | None:
            try:
                await dependency(current_user=user)
            except HTTPException as exc:
                return exc
            return None

        async def spend() -> list[HTTPException | None]:
            return [await refused() for _ in range(budget + 1)]

        outcomes = asyncio.run(spend())
        assert outcomes[:budget] == [None] * budget, f"the {label} tier refused inside its budget of {budget}"
        refusal = outcomes[budget]
        assert refusal is not None and refusal.status_code == 429
        assert refusal.detail == f"Rate limit exceeded for {label}. Please wait before retrying."
        clock.now += window
        assert asyncio.run(refused()) is not None, "a call exactly one window old still counts"
        clock.now += 0.5
        assert asyncio.run(refused()) is None, f"the {label} tier's window is longer than {window:g} s"
