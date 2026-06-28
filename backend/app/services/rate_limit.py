from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    """A simple in-memory sliding-window rate limiter.

    Process-local only — for multi-instance / horizontally-scaled deployments
    use a shared store (e.g. Redis). Use a per-client key for fairness and a
    fixed global key as a hard backstop against abuse when client identity
    cannot be trusted.
    """

    def __init__(self, max_events: int, window_seconds: float = 60.0) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        if self.max_events <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self.max_events:
                return False
            events.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
