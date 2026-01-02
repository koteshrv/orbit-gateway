"""Redis-backed helpers for rate limiting and quota management.

This module centralizes Redis client creation and small atomic helpers
used by the gateway to enforce distributed rate limits and quotas.
"""
import time
from datetime import datetime
import calendar
from typing import Tuple
import redis.asyncio as aioredis


def create_redis(url: str = "redis://localhost:6379/0") -> aioredis.Redis:
    """Create and return an `aioredis.Redis` client.

    Args:
        url: Redis connection URL.

    Returns:
        An async Redis client instance. The caller should reuse this client
        for the app lifetime (it's cheap to create but maintains a connection pool).
    """
    return aioredis.from_url(url, decode_responses=True)


async def rate_allow(redis: aioredis.Redis, tenant: str, requests: int, per_seconds: int) -> Tuple[bool, int]:
    """Check and increment a fixed-window counter for tenant rate limiting.

    Uses a Redis key scoped by tenant and window index (int(time() / per_seconds)).
    This is resilient across processes and containers.

    Returns (allowed, retry_after_seconds).
    """
    now = int(time.time())
    window = now // max(1, per_seconds)
    key = f"rl:{tenant}:{window}"
    # INCR and set EXPIRE if first seen
    val = await redis.incr(key)
    if val == 1:
        await redis.expire(key, per_seconds)
    if val > requests:
        ttl = await redis.ttl(key)
        retry = ttl if ttl and ttl > 0 else per_seconds
        return False, retry
    return True, 0


def _seconds_until_month_end() -> int:
    now = datetime.utcnow()
    year = now.year
    month = now.month
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59)
    return int((end - now).total_seconds())


async def quota_consume(redis: aioredis.Redis, tenant: str, tokens: int, cap: int) -> bool:
    """Atomically consume `tokens` from tenant monthly quota.

    Uses a Lua script to ensure the check-and-increment is atomic across
    processes. If the increment would exceed `cap`, the script returns -1
    and we return False. Otherwise returns True.
    """
    key = f"quota:{tenant}:{time.strftime('%Y-%m')}"
    # Expire key after month end plus a cushion (so old keys disappear)
    expire_seconds = _seconds_until_month_end() + 60 * 60 * 24

    lua = """
    local key = KEYS[1]
    local tokens = tonumber(ARGV[1])
    local cap = tonumber(ARGV[2])
    local expire = tonumber(ARGV[3])
    local curr = redis.call('GET', key)
    if not curr then curr = 0 else curr = tonumber(curr) end
    if curr + tokens > cap then return -1 end
    local v = redis.call('INCRBY', key, tokens)
    redis.call('EXPIRE', key, expire)
    return v
    """

    res = await redis.eval(lua, 1, key, tokens, cap, expire_seconds)
    if isinstance(res, (int,)) and res == -1:
        return False
    return True
