"""Shared network pacing.

Throttle lived in bin/canvas_media_archive.py until a third tool needed it.
Behaviour is unchanged; only its home moved.
"""
import random
import time
from urllib.parse import urlsplit

import requests


class Throttle:
    """Keep request pacing in the range a person browsing would produce.

    Everything is serial -- there is deliberately no concurrency here. Gaps are
    randomised so the cadence is not a machine-perfect metronome, a longer rest
    is taken every so often the way a reader pauses on a page, and any explicit
    server pushback (429/503, Retry-After) is obeyed and then remembered as a
    penalty so the run backs off for the rest of the session rather than
    immediately resuming the old rate.
    """

    def __init__(self, min_gap=1.5, jitter=1.5, rest_every=25, rest_secs=(8, 20)):
        self.min_gap = min_gap
        self.jitter = jitter
        self.rest_every = rest_every
        self.rest_secs = rest_secs
        self.last = {}
        self.count = 0
        self.penalty = 0.0
        self.waited = 0.0

    def wait(self, url):
        host = urlsplit(url).netloc
        gap = self.min_gap + random.uniform(0, self.jitter) + self.penalty
        due = self.last.get(host, 0) + gap
        now = time.monotonic()
        if now < due:
            time.sleep(due - now)
            self.waited += due - now
        self.count += 1
        if self.rest_every and self.count % self.rest_every == 0:
            nap = random.uniform(*self.rest_secs)
            print(f"    (pausing {nap:.0f}s -- keeping the session's pace human)")
            time.sleep(nap)
            self.waited += nap
        self.last[host] = time.monotonic()

    def pushback(self, resp):
        """Return seconds to sleep if the server asked us to slow down."""
        if resp is None or resp.status_code not in (429, 503, 403):
            # A clean run slowly forgives an earlier penalty.
            self.penalty = max(0.0, self.penalty - 0.05)
            return 0
        if resp.status_code == 403:
            return 0  # entitlement, not rate limiting -- retrying will not help
        self.penalty = min(15.0, (self.penalty or 1.0) * 2)
        try:
            return min(120, int(resp.headers.get("Retry-After", "")))
        except ValueError:
            return min(60, 5 * self.penalty)


def get(url, throttle, headers=None, timeout=45, tries=3):
    """Serial, paced GET with backoff. Raises on final failure."""
    hdrs = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0 Safari/537.36")}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(tries):
        throttle.wait(url)
        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
            continue
        nap = throttle.pushback(resp)
        if nap:
            time.sleep(nap)
            last = RuntimeError(f"{resp.status_code} from {url}")
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"GET failed after {tries} tries: {url}") from last
