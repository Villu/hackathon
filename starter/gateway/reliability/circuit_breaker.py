"""Circuit breaker for the LLM and MCP dependencies (spec section 5).

closed  → normal; failures counted in a sliding window
open    → all calls rejected; after `half_open_after_s` one probe call is allowed
half_open → the probe decides: success closes, failure re-opens
"""

from __future__ import annotations

import time
from collections import deque
from enum import StrEnum


class BreakerState(StrEnum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        window_s: float = 30.0,
        half_open_after_s: float = 10.0,
        clock=time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_s = window_s
        self.half_open_after_s = half_open_after_s
        self._clock = clock
        self._failures: deque[float] = deque()
        self._state = BreakerState.closed
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.open and self._opened_at is not None:
            if self._clock() - self._opened_at >= self.half_open_after_s:
                self._state = BreakerState.half_open
                self._probe_in_flight = False
        return self._state

    def allow(self) -> bool:
        state = self.state
        if state is BreakerState.closed:
            return True
        if state is BreakerState.half_open and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        self._failures.clear()
        self._state = BreakerState.closed
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        now = self._clock()
        if self._state is BreakerState.half_open:
            self._trip(now)
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self.window_s:
            self._failures.popleft()
        if len(self._failures) >= self.failure_threshold:
            self._trip(now)

    def _trip(self, now: float) -> None:
        self._state = BreakerState.open
        self._opened_at = now
        self._probe_in_flight = False
        self._failures.clear()
