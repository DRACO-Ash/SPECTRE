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
from spectre.web.models import User

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    """Asyncio-safe sliding-window rate limiter (per string key)."""

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
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
        logger.warning("Rate limit hit: %s for operator %s", label, user.username)
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
