import time
import pytest
from si_archive.net import Throttle


def test_throttle_spaces_requests_to_the_same_host():
    t = Throttle(min_gap=0.2, jitter=0.0, rest_every=0)
    t.wait("https://example.com/a")
    start = time.monotonic()
    t.wait("https://example.com/b")
    assert time.monotonic() - start >= 0.2


def test_throttle_does_not_delay_a_different_host():
    t = Throttle(min_gap=5.0, jitter=0.0, rest_every=0)
    t.wait("https://example.com/a")
    start = time.monotonic()
    t.wait("https://other.example.org/a")
    assert time.monotonic() - start < 0.5


def test_pushback_penalty_persists_after_a_429():
    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "1"}

    t = Throttle(min_gap=0.0, jitter=0.0, rest_every=0)
    assert t.penalty == 0.0
    t.pushback(FakeResp())
    assert t.penalty > 0.0
