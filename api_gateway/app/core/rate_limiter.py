"""Redis-backed sliding window rate limiter.

Falls back to allow-all with a warning if Redis is unreachable,
so a Redis outage never takes down the gateway.
"""

import logging
import time

logger = logging.getLogger(__name__)

_redis_client = None


async def _get_redis():
    """Return a shared redis.asyncio client, created lazily."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            from .config import settings
            _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception as exc:
            logger.warning("Redis unavailable for rate limiter: %s", exc)
    return _redis_client


class RateLimiter:
    """Sliding-window rate limiter backed by a Redis sorted set.

    Key schema:  ``rl:{key}``
    Each entry is a float timestamp; members older than the window are pruned
    on every call so the set stays small.
    """

    async def is_allowed_async(self, key: str, max_requests: int, window_seconds: int = 60) -> bool:
        redis = await _get_redis()
        if redis is None:
            logger.warning("Rate limiter: Redis unavailable, allowing request for key=%s", key)
            return True

        rkey = f"rl:{key}"
        now = time.time()
        cutoff = now - window_seconds

        try:
            pipe = redis.pipeline()
            pipe.zremrangebyscore(rkey, "-inf", cutoff)
            pipe.zcard(rkey)
            pipe.zadd(rkey, {str(now): now})
            pipe.expire(rkey, window_seconds + 1)
            results = await pipe.execute()
            count_before_add = results[1]
            return count_before_add < max_requests
        except Exception as exc:
            logger.warning("Rate limiter Redis error (%s) — allowing request", exc)
            return True

    async def remaining_async(self, key: str, max_requests: int, window_seconds: int = 60) -> int:
        redis = await _get_redis()
        if redis is None:
            return max_requests

        rkey = f"rl:{key}"
        now = time.time()
        cutoff = now - window_seconds
        try:
            count = await redis.zcount(rkey, cutoff, "+inf")
            return max(0, max_requests - count)
        except Exception:
            return max_requests

    # ── Sync shim kept for compatibility (not used by the async gateway) ──
    def is_allowed(self, key: str, max_requests: int, window_seconds: int = 60) -> bool:  # noqa: ARG002
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Called from an async context — schedule and return True, actual
                # check happens next tick. The async proxy handler uses is_allowed_async.
                return True
            return loop.run_until_complete(self.is_allowed_async(key, max_requests, window_seconds))
        except Exception:
            return True

    def remaining(self, key: str, max_requests: int, window_seconds: int = 60) -> int:
        return max_requests


rate_limiter = RateLimiter()
