from gateway.reliability.circuit_breaker import BreakerState, CircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker("llm", failure_threshold=3, window_s=30, half_open_after_s=10, clock=clock)


def test_opens_after_threshold_failures():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        assert cb.allow()
        cb.record_failure()
    assert cb.state is BreakerState.open
    assert not cb.allow()


def test_half_open_probe_then_close():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        cb.record_failure()
    clock.t += 10
    assert cb.state is BreakerState.half_open
    assert cb.allow()  # one probe
    assert not cb.allow()  # only one
    cb.record_success()
    assert cb.state is BreakerState.closed
    assert cb.allow()


def test_failure_in_half_open_reopens():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        cb.record_failure()
    clock.t += 10
    assert cb.allow()
    cb.record_failure()
    assert cb.state is BreakerState.open
    assert not cb.allow()


def test_old_failures_expire():
    clock = FakeClock()
    cb = _breaker(clock)
    cb.record_failure()
    cb.record_failure()
    clock.t += 31
    cb.record_failure()
    assert cb.state is BreakerState.closed
