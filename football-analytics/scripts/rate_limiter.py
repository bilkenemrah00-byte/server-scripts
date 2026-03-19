"""
Rate limiter for API-Football Ultra plan.

Limits:
  - 300 requests / minute
  - 75,000 requests / day

We operate at max 250/min to keep a safety buffer.

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section VII.2
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Hard limits from API-Football Ultra plan
HARD_LIMIT_PER_MINUTE = 300
HARD_LIMIT_PER_DAY = 75_000

# Our operational limits (safety buffer)
OPERATIONAL_LIMIT_PER_MINUTE = 250
MAX_CONCURRENT_REQUESTS = 10


@dataclass
class RateLimitStats:
    """Track usage for monitoring and audit."""
    requests_this_minute: int = 0
    requests_today: int = 0
    minute_start: float = field(default_factory=time.time)
    day_start: float = field(default_factory=time.time)
    total_waits: int = 0
    total_wait_seconds: float = 0.0


class RateLimiter:
    """Async rate limiter for API-Football requests.

    Enforces:
    - Max 250 requests/minute (operational limit)
    - Max 10 concurrent requests
    - Automatic wait when approaching limit
    - Daily usage tracking

    Usage:
        limiter = RateLimiter()

        async with limiter:
            response = await client.get(...)
    """

    def __init__(
        self,
        max_per_minute: int = OPERATIONAL_LIMIT_PER_MINUTE,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
    ):
        self.max_per_minute = max_per_minute
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._stats = RateLimitStats()
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        await self._acquire()
        return self

    async def __aexit__(self, *args):
        pass

    async def _acquire(self):
        """Acquire a request slot, waiting if necessary."""
        async with self._semaphore:
            async with self._lock:
                await self._enforce_rate_limit()
                self._stats.requests_this_minute += 1
                self._stats.requests_today += 1

                logger.debug(
                    f"Request {self._stats.requests_this_minute}/{self.max_per_minute} "
                    f"this minute, {self._stats.requests_today} today"
                )

    async def _enforce_rate_limit(self):
        """Wait if we're approaching the per-minute limit."""
        now = time.time()

        # Reset minute counter if a full minute has passed
        if now - self._stats.minute_start >= 60:
            self._stats.requests_this_minute = 0
            self._stats.minute_start = now

        # Check daily reset (midnight Istanbul — simplified: 24h from start)
        if now - self._stats.day_start >= 86400:
            self._stats.requests_today = 0
            self._stats.day_start = now

        # Warn if approaching daily limit
        if self._stats.requests_today >= HARD_LIMIT_PER_DAY - 1000:
            logger.warning(
                f"Daily limit warning: {self._stats.requests_today}/{HARD_LIMIT_PER_DAY} requests used"
            )

        # Wait if at per-minute limit
        if self._stats.requests_this_minute >= self.max_per_minute:
            elapsed = now - self._stats.minute_start
            wait_time = max(0.0, 60.0 - elapsed + 0.5)  # +0.5s buffer

            logger.info(
                f"Rate limit reached ({self._stats.requests_this_minute} req), "
                f"waiting {wait_time:.1f}s"
            )

            self._stats.total_waits += 1
            self._stats.total_wait_seconds += wait_time

            await asyncio.sleep(wait_time)

            # Reset after wait
            self._stats.requests_this_minute = 0
            self._stats.minute_start = time.time()

    @property
    def stats(self) -> RateLimitStats:
        """Current usage statistics."""
        return self._stats

    def log_summary(self):
        """Log a summary of rate limiter usage."""
        logger.info(
            f"Rate limiter summary: "
            f"{self._stats.requests_today} total requests, "
            f"{self._stats.total_waits} waits, "
            f"{self._stats.total_wait_seconds:.1f}s total wait time"
        )


class SyncRateLimiter:
    """Synchronous rate limiter for non-async contexts (e.g. Kestra script tasks).

    Usage:
        limiter = SyncRateLimiter()
        limiter.acquire()
        response = requests.get(...)
    """

    def __init__(self, max_per_minute: int = OPERATIONAL_LIMIT_PER_MINUTE):
        self.max_per_minute = max_per_minute
        self._requests_this_minute = 0
        self._minute_start = time.time()
        self._requests_today = 0

    def acquire(self):
        """Block until a request slot is available."""
        now = time.time()

        if now - self._minute_start >= 60:
            self._requests_this_minute = 0
            self._minute_start = now

        if self._requests_this_minute >= self.max_per_minute:
            elapsed = now - self._minute_start
            wait_time = max(0.0, 60.0 - elapsed + 0.5)
            logger.info(f"Rate limit reached, sleeping {wait_time:.1f}s")
            time.sleep(wait_time)
            self._requests_this_minute = 0
            self._minute_start = time.time()

        self._requests_this_minute += 1
        self._requests_today += 1
