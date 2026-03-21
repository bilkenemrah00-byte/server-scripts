"""Rate limiter — thread-safe sync version for parallel data collection."""

import time
import logging
import threading

logger = logging.getLogger(__name__)

OPERATIONAL_LIMIT_PER_MINUTE = 150


class SyncRateLimiter:
    def __init__(self, max_per_minute: int = OPERATIONAL_LIMIT_PER_MINUTE):
        self.max_per_minute = max_per_minute
        self.min_interval = 60.0 / max_per_minute  # pacing
        self._lock = threading.Lock()
        self._last_request_ts = 0.0
        self._requests_today = 0

    def acquire(self):
        with self._lock:
            now = time.time()
            wait_time = self.min_interval - (now - self._last_request_ts)

            if wait_time > 0:
                time.sleep(wait_time)

            self._last_request_ts = time.time()
            self._requests_today += 1


_global_limiter = None

def get_global_limiter() -> SyncRateLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = SyncRateLimiter(max_per_minute=150)
    return _global_limiter

RateLimiter = SyncRateLimiter
