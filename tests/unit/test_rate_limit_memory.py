"""The limiter's dictionary is keyed by the caller, so it must not grow forever.

``SlidingWindowLimiter`` kept a ``defaultdict`` entry for every key it had ever
been offered and evicted nothing. That was survivable while the only keys were
authenticated operator names on the UDL routes. This release pointed two new
limiters at ``POST /login`` keyed on the first ``X-Forwarded-For`` entry and on
the submitted username, both attacker-chosen, on an endpoint that is
unauthenticated AND exempt from CSRF.

Measured before the eviction existed: 200,000 distinct keys retained 200,000
entries and 168.4 MiB, roughly 883 bytes each, projecting to 303 MiB an hour at
100 requests a second. The guard written to stop a brute force was itself a way
to exhaust the process, and the rotating-address test in
tests/integration/test_login_hardening.py demonstrates exactly the traffic that
feeds it.
"""

from __future__ import annotations

import asyncio

import pytest

from spectre.web.rate_limit import SlidingWindowLimiter


def _drain(coro: object) -> object:
    """Run one coroutine to completion on a private loop."""
    return asyncio.run(coro)  # type: ignore[arg-type]


class TestKeysAreNotRetainedForever:
    def test_a_flood_of_distinct_keys_does_not_accumulate(self) -> None:
        """Retention must follow rate times window, not total keys ever seen."""
        async def exercise() -> int:
            limiter = SlidingWindowLimiter(max_calls=10, window_seconds=0.05)
            for i in range(2000):
                await limiter.is_allowed(f"10.0.0.{i}")
                if i % 500 == 0:
                    # Let the window elapse so earlier keys become evictable.
                    await asyncio.sleep(0.06)
            await asyncio.sleep(0.06)
            await limiter.is_allowed("one-more-to-trigger-the-sweep")
            return len(limiter._calls)

        retained = _drain(exercise())
        # Near the real bound, not merely "fewer than offered". The measured
        # value is a single key; "< 2000" would certify a sweep that evicted
        # only half and still grew without limit.
        assert retained <= 50, (
            f"{retained} of 2000 offered keys are still held, so the "
            "dictionary grows with every distinct value a caller sends"
        )

    def test_eviction_keeps_a_key_whose_window_is_still_live(self) -> None:
        """The predicate, tested directly, because the gate hides it.

        Eviction must never hand an attacker a fresh budget. This is why
        expiry is the right instrument and an LRU cap is not: a cap would let
        a flood of distinct keys push a victim's entry out and reopen
        unbounded guessing against that account.

        Driving this through ``is_allowed`` cannot reach the case. The sweep
        runs at most once per window, so by the time it is due again a key
        that has not been touched since the last sweep has had its own window
        elapse too: eviction and expiry coincide. That is a good property, but
        it means a flood test passes whatever the predicate says, so the
        predicate is called here with the sweep forced due. Mutating the
        condition to evict unconditionally turns this red; the flood version
        of this test stayed green, which is why it is not the one kept.
        """
        import time as _time

        limiter = SlidingWindowLimiter(max_calls=3, window_seconds=10.0)
        now = _time.monotonic()
        # SPREAD ACROSS THE WINDOW, not three identical stamps.
        #
        # Seeding [now, now, now] made calls[0] and calls[-1] the same value,
        # so the predicate could not be told apart from one reading the OLDEST
        # call instead of the newest. That is not hypothetical: it is the
        # idiom the prune loop four lines below uses, and with it the whole
        # suite stayed green while a victim whose most recent attempt was one
        # second into a ten second window was evicted and handed back three
        # fresh guesses. The oldest call here is already outside the window
        # and the newest is well inside it, so the two readings disagree.
        limiter._calls["victim"].extend([now - 11.0, now - 5.0, now - 1.0])
        limiter._calls["long-gone"].append(now - 600.0)
        limiter._calls["emptied"]  # touch, so the defaultdict holds an empty deque
        limiter._last_sweep = now - 600.0   # force the sweep due

        limiter._evict_elapsed(now)

        assert "victim" in limiter._calls, (
            "a key inside its window was evicted, so a flood of unrelated keys "
            "can restore an attacker's budget against that account"
        )
        assert len(limiter._calls["victim"]) == 3, (
            "the victim's spent budget was altered by the sweep"
        )
        assert "long-gone" not in limiter._calls, "an elapsed key was retained"
        assert "emptied" not in limiter._calls, "an empty deque was retained"

    def test_the_sweep_does_not_run_on_every_call(self) -> None:
        """Amortised, or a large dictionary is swept once per request."""
        async def exercise() -> int:
            limiter = SlidingWindowLimiter(max_calls=100, window_seconds=30.0)
            sweeps = 0
            original = limiter._evict_elapsed

            def counting(now: float) -> None:
                nonlocal sweeps
                before = limiter._last_sweep
                original(now)
                if limiter._last_sweep != before:
                    sweeps += 1

            limiter._evict_elapsed = counting  # type: ignore[method-assign]
            for i in range(200):
                await limiter.is_allowed(f"key-{i}")
            return sweeps

        assert _drain(exercise()) == 0, (
            "the dictionary was swept during a 200-call burst inside one "
            "window, so the cost is per request rather than per window"
        )


class TestTheLimiterStillLimits:
    """Eviction must not weaken what the class is for."""

    @pytest.mark.parametrize("max_calls", [1, 3, 10])
    def test_the_budget_is_still_exactly_max_calls(self, max_calls: int) -> None:
        async def exercise() -> list[bool]:
            limiter = SlidingWindowLimiter(max_calls=max_calls, window_seconds=30.0)
            return [await limiter.is_allowed("steady") for _ in range(max_calls + 2)]

        verdicts = _drain(exercise())
        assert verdicts[:max_calls] == [True] * max_calls
        assert verdicts[max_calls:] == [False, False]

    def test_a_budget_recovers_once_its_window_has_passed(self) -> None:
        async def exercise() -> bool:
            limiter = SlidingWindowLimiter(max_calls=2, window_seconds=0.05)
            await limiter.is_allowed("recovering")
            await limiter.is_allowed("recovering")
            assert await limiter.is_allowed("recovering") is False
            await asyncio.sleep(0.06)
            return await limiter.is_allowed("recovering")

        assert _drain(exercise()) is True, "the window never reopens"
