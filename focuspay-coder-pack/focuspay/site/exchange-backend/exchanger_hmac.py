"""HMAC для API реквизитов магазина: как merchant_client (timestamp + body)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import OrderedDict

HMAC_SKEW_SEC = 5 * 60
_REPLAY_TTL_SEC = HMAC_SKEW_SEC + 60
_REPLAY_MAX = 10_000
_REDIS_PREFIX = "exchanger:hmac:replay:"

logger = logging.getLogger("exchanger_hmac")


def sign_body(secret: str, timestamp: str, body: str) -> str:
    message = f"{timestamp}{body}"
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def timestamp_fresh(timestamp: str, *, now: int | None = None) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(now if now is not None else time.time())
    return abs(current - ts) <= HMAC_SKEW_SEC


def verify_signature(secret: str, timestamp: str, body: str, signature: str) -> bool:
    if not secret or not signature:
        return False
    expected = sign_body(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


def replay_key(api_key: str, timestamp: str, body: str, *, method: str = "", path: str = "") -> str:
    digest = hashlib.sha256(f"{method}\n{path}\n{body}".encode("utf-8")).hexdigest()
    return f"{api_key}:{timestamp}:{digest}"


def _redis_client():
    try:
        from rate_limit_store import _get_redis

        return _get_redis()
    except Exception:
        return None


class ReplayCache:
    """Отсекает повтор того же тела с тем же timestamp (допуск часов ±5 мин).

    Prefer Redis SET NX so multi-worker uvicorn shares the cache; fall back to
    process-local OrderedDict when Redis is unavailable.
    """

    def __init__(self, *, ttl_sec: int = _REPLAY_TTL_SEC, max_size: int = _REPLAY_MAX):
        self.ttl_sec = ttl_sec
        self.max_size = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()

    def _purge(self, now: float) -> None:
        while self._seen:
            key, seen_at = next(iter(self._seen.items()))
            if now - seen_at <= self.ttl_sec and len(self._seen) <= self.max_size:
                break
            self._seen.popitem(last=False)

    def _seen_or_add_memory(self, key: str, *, now: float) -> bool:
        self._purge(now)
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def seen_or_add(self, key: str, *, now: float | None = None) -> bool:
        """True, если этот запрос уже был (replay)."""
        current = float(now if now is not None else time.time())
        r = _redis_client()
        if r is not None:
            try:
                ok = r.set(f"{_REDIS_PREFIX}{key}", "1", nx=True, ex=int(self.ttl_sec))
                # redis-py: True if set, None if key existed
                if ok is None or ok is False:
                    return True
                return False
            except Exception as exc:
                logger.debug("hmac replay redis fallback: %s", exc)
        return self._seen_or_add_memory(key, now=current)


replay_cache = ReplayCache()
