from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    """Small deployment-safe limiter. Use Redis when SaaS runs multiple API replicas."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = monotonic()
        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - self.window_seconds:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(now)
            return True


registration_limiter = InMemoryRateLimiter(limit=10, window_seconds=300)
heartbeat_limiter = InMemoryRateLimiter(limit=30, window_seconds=60)
tenant_password_reset_limiter = InMemoryRateLimiter(limit=5, window_seconds=900)
tenant_password_reset_consume_limiter = InMemoryRateLimiter(
    limit=10, window_seconds=900
)
