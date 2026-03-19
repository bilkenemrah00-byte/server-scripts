"""Rate limiter — thread-safe sync version for parallel data collection."""

import time
import logging
import threading

logger = logging.getLogger(__name__)

OPERATIONAL_LIMIT_PER_MINUTE = 250
MAX_CONCURRENT_REQUESTS = 10


class SyncRateLimiter:
    def __init__(self, max_per_minute: int = OPERATIONAL_LIMIT_PER_MINUTE):
        self.max_per_minute = max_per_minute
        self._lock = threading.Lock()
        self._requests_this_minute = 0
        self._minute_start = time.time()
        self._requests_today = 0

    def acquire(self):
        with self._lock:
            now = time.time()
            if now - self._minute_start >= 60:
                self._requests_this_minute = 0
                self._minute_start = now

            if self._requests_this_minute >= self.max_per_minute:
                elapsed = now - self._minute_start
                wait_time = max(0.0, 60.0 - elapsed + 1.0)
                logger.info(f"Rate limit reached ({self._requests_this_minute} req), sleeping {wait_time:.1f}s")
                time.sleep(wait_time)
                self._requests_this_minute = 0
                self._minute_start = time.time()

            self._requests_this_minute += 1
            self._requests_today += 1

# Singleton — tüm thread'ler aynı limiter'ı paylaşır
_global_limiter = None

def get_global_limiter() -> SyncRateLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = SyncRateLimiter(max_per_minute=40)  # Güvenli limit
    return _global_limiter

# Eski isimler için alias
RateLimiter = SyncRateLimiter
