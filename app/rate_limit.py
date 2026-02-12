from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    retry_after_sec: int


class InMemoryRateLimiter:
    def __init__(self, *, requests_per_minute: int) -> None:
        self.requests_per_minute = requests_per_minute
        self.window_sec = 60.0
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> RateLimitResult:
        now = time.time()
        with self._lock:
            queue = self._events[key]
            cutoff = now - self.window_sec
            while queue and queue[0] <= cutoff:
                queue.popleft()

            if len(queue) >= self.requests_per_minute:
                retry_after = max(1, int(queue[0] + self.window_sec - now))
                return RateLimitResult(allowed=False, retry_after_sec=retry_after)

            queue.append(now)
            return RateLimitResult(allowed=True, retry_after_sec=0)
