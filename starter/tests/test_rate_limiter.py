from gateway.reliability.rate_limiter import TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_burst_then_reject():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_s=5, capacity=10, clock=clock)
    assert all(bucket.try_acquire() for _ in range(10))
    assert not bucket.try_acquire()
    assert bucket.rejected == 1


def test_refills_over_time():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_s=5, capacity=10, clock=clock)
    for _ in range(10):
        bucket.try_acquire()
    clock.t += 1.0  # +5 tokens
    assert sum(bucket.try_acquire() for _ in range(10)) == 5


def test_never_exceeds_capacity():
    clock = FakeClock()
    bucket = TokenBucket(rate_per_s=100, capacity=3, clock=clock)
    clock.t += 60
    assert bucket.available == 3
