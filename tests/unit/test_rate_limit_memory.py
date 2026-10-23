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
import sys

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
        assert list(limiter._calls["victim"]) == [now - 11.0, now - 5.0, now - 1.0], (
            "the victim's spent budget was altered by the sweep. Pinned by "
            "identity rather than by length: the three timestamps are spread "
            "across the window, so a sweep that pruned the oldest and left the "
            "count intact would otherwise pass"
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


class TestTheKeyItselfIsBounded:
    """Bounding the key COUNT does not bound the memory.

    The sweep above bounds how many keys are retained. It says nothing about
    how large each one is, and on the login tiers the caller chooses: the raw
    submitted username reaches the limiter straight from ``Form()`` with no
    ``max_length``, and the first ``X-Forwarded-For`` entry is whatever was
    sent. Measured against this class before the clamp existed: 873 bytes per
    key at a realistic length and 263,001 at 256 KiB, so 400 requests retained
    100 MiB where 200,000 requests had retained 168 MiB before any sweep
    existed at all.

    That is the regression worth naming. The control written to stop a memory
    exhaustion made the attack roughly 500 times cheaper per request, because
    it bounded the dimension an attacker was not using.
    """

    @staticmethod
    def _retained_bytes(calls: dict[str, object]) -> int:
        """Shallow-deep size of the dictionary: keys, deques and timestamps."""
        total = sys.getsizeof(calls)
        for key, queue in calls.items():
            total += sys.getsizeof(key) + sys.getsizeof(queue)
            total += sum(sys.getsizeof(stamp) for stamp in queue)  # type: ignore[attr-defined]
        return total

    def test_retention_does_not_scale_with_key_length(self) -> None:
        """A long key must cost what a short one costs, or the bound is fiction."""
        async def exercise(key_chars: int) -> int:
            limiter = SlidingWindowLimiter(max_calls=10, window_seconds=300.0)
            for i in range(400):
                await limiter.is_allowed(f"{i:08d}".ljust(key_chars, "x"))
            return self._retained_bytes(limiter._calls)

        realistic = _drain(exercise(16))
        enormous = _drain(exercise(256 * 1024))

        assert isinstance(realistic, int) and isinstance(enormous, int)
        # Without the clamp this ratio is about 301. The deques and timestamps
        # are identical in both runs, so anything above a small constant is the
        # key strings themselves being retained.
        assert enormous <= realistic * 1.5, (
            f"a 256 KiB key retained {enormous / 1048576:.1f} MiB against "
            f"{realistic / 1048576:.1f} MiB for a realistic one, so the "
            "dictionary's memory is still sized by the caller"
        )

    def test_a_long_key_cannot_consume_a_real_account_budget(self) -> None:
        """Truncation must not let an attacker collide with a victim's key.

        Clamping merges over-long keys, which throttles more and never less.
        The property that matters is the other direction: padding a victim's
        username must not spend that victim's budget.
        """
        async def exercise() -> bool:
            limiter = SlidingWindowLimiter(max_calls=3, window_seconds=300.0)
            for _ in range(50):
                await limiter.is_allowed("operator" + "x" * 100_000)
            return await limiter.is_allowed("operator")

        assert _drain(exercise()) is True, (
            "a flood of padded keys exhausted the budget of the real account "
            "whose name they begin with"
        )

    def test_two_distinct_maximum_length_usernames_do_not_share_a_budget(self) -> None:
        """The clamp must not split or merge any key a real account can hold.

        models.py declares username as String(64), so 64 characters is the
        longest legitimate key and both of these are valid accounts.
        """
        async def exercise() -> bool:
            limiter = SlidingWindowLimiter(max_calls=2, window_seconds=300.0)
            first = "a" * 63 + "1"
            second = "a" * 63 + "2"
            for _ in range(2):
                await limiter.is_allowed(first)
            return await limiter.is_allowed(second)

        assert _drain(exercise()) is True, (
            "two accounts differing only in their final character were metered "
            "as one, so exhausting one locks out the other"
        )
