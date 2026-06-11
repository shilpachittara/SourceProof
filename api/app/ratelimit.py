"""Lightweight, dependency-free abuse/DoS protection for write endpoints.

A sliding-window, per-client limiter kept in memory. For a single instance this
is enough to blunt abuse; a multi-instance production deployment puts a shared
limiter (e.g. Redis) or an API gateway in front. Read endpoints stay open
(public-good, no auth).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - self.window
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max_requests:
                return False
            dq.append(now)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            dq = self._hits.get(key)
            if not dq:
                return 0
            return max(1, int(self.window - (time.monotonic() - dq[0])))
