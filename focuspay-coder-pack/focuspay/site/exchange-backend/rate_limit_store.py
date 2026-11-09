"""Rate limit storage: Redis (optional) или in-memory fallback."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from config import settings

logger = logging.getLogger("rate_limit_store")

_lock = Lock()
_memory: dict[str, list[float]] = defaultdict(list)
_redis_client = None
_redis_checked = False


def _get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    try:
        import redis

        _redis_client = redis.from_url(url, decode_responses=True, socket_timeout=1)
        _redis_client.ping()
        logger.info("rate limit: using Redis")
        return _redis_client
    except Exception as e:
        logger.warning("rate limit: Redis unavailable (%s), using memory", e)
        _redis_client = None
        return None


def _count_memory(ip: str, window_sec: int, *, record: bool) -> int:
    now = time.time()
    with _lock:
        recent = [t for t in _memory[ip] if now - t < window_sec]
        if record:
            recent.append(now)
            _memory[ip] = recent
        return len(recent)


def _count_redis(ip: str, window_sec: int, *, record: bool) -> int:
    r = _get_redis()
    if r is None:
        return _count_memory(ip, window_sec, record=record)
    try:
        key = f"rl:{ip}"
        now = time.time()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_sec)
        if record:
            pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        if record:
            pipe.expire(key, window_sec + 5)
        results = pipe.execute()
        return int(results[-2] if record else results[-1])
    except Exception as e:
        logger.debug("redis rate limit fallback: %s", e)
        return _count_memory(ip, window_sec, record=record)


def get_request_count(ip: str, window_sec: int = 60) -> int:
    """Current request count in window (read-only)."""
    if not ip:
        return 0
    return _count_redis(ip, window_sec, record=False)


def record_request(ip: str, window_sec: int = 60) -> int:
    """Record request and return new count in window."""
    if not ip:
        return 0
    return _count_redis(ip, window_sec, record=True)
