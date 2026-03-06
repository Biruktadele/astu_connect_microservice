import time
from collections import defaultdict


class RateLimiter:
    def __init__(self):
        self._windows = defaultdict(list)

    def is_allowed(self, key, max_requests, window_seconds=60):
        now = time.monotonic()
        cutoff = now - window_seconds
        timestamps = self._windows[key]
        self._windows[key] = [t for t in timestamps if t > cutoff]
        if len(self._windows[key]) >= max_requests:
            return False
        self._windows[key].append(now)
        return True

    def remaining(self, key, max_requests, window_seconds=60):
        now = time.monotonic()
        cutoff = now - window_seconds
        count = sum(1 for t in self._windows.get(key, []) if t > cutoff)
        return max(0, max_requests - count)


rate_limiter = RateLimiter()
