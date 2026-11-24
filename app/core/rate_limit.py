"""Small in-memory rate limits for sign-in and auth emails.

Counts live in this process only, which is enough for the single-process MVP;
several workers or servers would need a shared store such as Redis.
"""

import time
from collections import deque
from threading import Lock

from app.core.config import settings


class RateLimiter:
    """Allow at most ``limit`` hits per key within ``window`` seconds."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def retry_after(self, key: str) -> int | None:
        """Seconds until the key may try again, or None when it is allowed."""
        if not settings.RATE_LIMIT_ENABLED:
            return None
        now = time.monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) < self.limit:
                return None
            return max(1, int(hits[0] + self.window - now) + 1)

    def hit(self, key: str) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._hits.setdefault(key, deque()).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Failed sign-ins per email address
login_failures = RateLimiter(
    settings.LOGIN_MAX_FAILURES, settings.LOGIN_WINDOW_MINUTES * 60
)
# Password-reset and verification emails per address
auth_emails = RateLimiter(
    settings.AUTH_EMAILS_PER_WINDOW, settings.AUTH_EMAIL_WINDOW_MINUTES * 60
)
