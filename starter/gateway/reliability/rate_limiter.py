"""Token bucket rate limiter (spec section 5).

Single-threaded asyncio use: no locks needed. When the bucket is empty the caller must NOT
wait — the alert goes down the deterministic path instead.
"""

from __future__ import annotations

import time


class TokenBucket:
    def __init__(self, rate_per_s: float, capacity: int, clock=time.monotonic) -> None:
        if rate_per_s <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self.rate = float(rate_per_s)
        self.capacity = float(capacity)
        self._tokens = float(capacity)
        self._clock = clock
        self._last = clock()
        self.rejected = 0

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def try_acquire(self, tokens: int = 1) -> bool:
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        self.rejected += 1
        return False

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens
