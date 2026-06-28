from __future__ import annotations

from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic


class MemoryRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = self._clock()
        oldest_allowed = now - window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= oldest_allowed:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window_seconds - now))
                return False, retry_after
            events.append(now)
        return True, 0
