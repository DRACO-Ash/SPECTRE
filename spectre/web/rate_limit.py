"""In-process sliding-window rate limiters for SPECTRE UDL proxy routes.

Three tiers match the cost profile of UDL operations:
  - udl_auth  : credential probes      — 5 / 60 s   per operator
  - udl_data  : TLE / SV / HRR fetches — 60 / 60 s  per operator
  - udl_sync  : bulk NOTSO sync         — 3 / 600 s  per operator
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status

from spectre.web.auth import require_login
from spectre.web.log_safety import log_safe
from spectre.web.models import User

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    """Asyncio-safe sliding-window rate limiter (per string key)."""

    # Bounding the key COUNT does not bound the memory, because the dictionary
    # retains the keys themselves and on the login tiers the caller chooses how
    # long they are: the raw submitted username and the raw first
    # X-Forwarded-For entry, neither length-bounded by the framework. Measured
    # against this class: 873 bytes per key at a realistic length, 263,001 at
    # 256 KiB. So 400 requests retained 100 MiB where, before any sweep
    # existed, 200,000 requests had retained 168 MiB. The eviction sweep made
    # the attack roughly 500 times CHEAPER per request while leaving it
    # unbounded, on an endpoint that is unauthenticated and CSRF-exempt.
    #
    # 64 is models.py's String(64) for username, and the longest textual IPv6
    # address is 45 characters, so no legitimate key is truncated here.
    # Truncation can only MERGE over-long keys into one budget, which throttles
    # more and never less. It cannot steal a real account's budget either:
    # colliding with a victim requires submitting the victim's own username,
    # which was always possible and buys an attacker nothing.
    _MAX_KEY_CHARS = 64

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_sweep = time.monotonic()

    def _evict_elapsed(self, now: float) -> None:
        """Drop keys whose whole window has elapsed. Caller holds the lock.

        Without this the dictionary is unbounded and the caller chooses the
        keys. The login limiters key on the first X-Forwarded-For entry and on
        the submitted username, both attacker-supplied, on an endpoint that is
        unauthenticated AND exempt from CSRF, so a flood of distinct values is
        free to send and permanent to hold. Measured before this existed:
        200,000 distinct keys retained 168.4 MiB, about 883 bytes each, which
        projects to 303 MiB an hour at 100 requests a second. The guard added
        to stop a brute force was itself a way to exhaust the process.

        Retention is now bounded by RATE TIMES WINDOW rather than by the
        number of distinct keys ever seen: the same 200,000 offered keys
        retain 20,000 and 17.7 MiB.

        That bounds the key COUNT only. The key SIZE is bounded separately by
        _MAX_KEY_CHARS, because this sweep alone left the dictionary's memory
        entirely under the caller's control. See the comment on that constant.

        An LRU cap would be the wrong instrument. A flood could evict a
        victim's username entry and hand an attacker a fresh budget against
        that account, which is the control this class exists to provide.
        Expiry cannot be gamed that way: a key only leaves once its window has
        genuinely elapsed, and a key under active attack never qualifies.

        The sweep runs at most once per window, so it is amortised to roughly
        one pass over the dictionary per window rather than per request. It is
        synchronous and holds the lock on the event loop while it runs:
        measured at 0.8 ms per 10,000 keys, 47 ms to scan 300,000 and 146 ms to
        scan and delete them. Acceptable at one pass per window, and with the
        key size bounded the count is the only remaining growth dimension, so
        that figure is the latency consequence of this bound rather than a
        surprise to be found later.

        Retention follows the window only WHILE TRAFFIC CONTINUES. The sweep
        runs from is_allowed and nothing else calls it, so when a flood stops,
        the dictionary is held until the next failed login arrives. Measured:
        371.0 MiB resident indefinitely after traffic ceased, dropping on the
        single next request. It is why a peak persists rather than decaying.
        """
        if now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        elapsed = [
            key for key, calls in self._calls.items()
            if not calls or now - calls[-1] > self._window
        ]
        for key in elapsed:
            del self._calls[key]

    async def is_blocked(self, key: str) -> bool:
        """Return ``True`` when *key* has already spent its budget, without charging it.

        The login route has to refuse an exhausted account BEFORE it compares
        the password. Asking ``is_allowed`` there would charge a successful
        sign-in, which this limiter must never do, so the read is separate.
        """
        key = key[: self._MAX_KEY_CHARS]
        now = time.monotonic()
        async with self._lock:
            q = self._calls.get(key)
            if not q:
                return False
            while q and now - q[0] > self._window:
                q.popleft()
            return len(q) >= self._max

    async def is_allowed(self, key: str) -> bool:
        # Clamped here rather than at the call sites so every present and
        # future caller inherits the bound.
        key = key[: self._MAX_KEY_CHARS]
        now = time.monotonic()
        async with self._lock:
            self._evict_elapsed(now)
            q = self._calls[key]
            while q and now - q[0] > self._window:
                q.popleft()
            if len(q) >= self._max:
                return False
            q.append(now)
            return True


_udl_auth_limiter = SlidingWindowLimiter(max_calls=5, window_seconds=60)
_udl_data_limiter = SlidingWindowLimiter(max_calls=60, window_seconds=60)
_udl_sync_limiter = SlidingWindowLimiter(max_calls=3, window_seconds=600)


async def _guard(limiter: SlidingWindowLimiter, user: User, label: str) -> None:
    if not await limiter.is_allowed(user.username):
        # The operator name is the only part of this record that came from
        # outside the application, so it is the only part that can turn one
        # warning into two log lines and forge an audit entry against another
        # account (pythonsecurity:S5145). The label is a literal supplied by
        # the three callers below and needs no flattening.
        logger.warning("Rate limit hit: %s for operator %s", label, log_safe(user.username))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {label}. Please wait before retrying.",
        )


async def udl_auth_rate_limit(current_user: User = Depends(require_login)) -> None:
    """5 UDL credential probes per 60 s per operator."""
    await _guard(_udl_auth_limiter, current_user, "UDL authentication")


async def udl_data_rate_limit(current_user: User = Depends(require_login)) -> None:
    """60 UDL data requests per 60 s per operator."""
    await _guard(_udl_data_limiter, current_user, "UDL data")


async def udl_sync_rate_limit(current_user: User = Depends(require_login)) -> None:
    """3 NOTSO bulk-sync operations per 600 s per operator."""
    await _guard(_udl_sync_limiter, current_user, "UDL sync")
