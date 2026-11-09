"""Size / rate / idempotency / retry limits for Sticker AI."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class StickerLimits:
    max_prompt_chars: int = 2000
    max_idea_chars: int = 1000
    max_image_bytes: int = 5 * 1024 * 1024  # 5 MiB
    max_mask_bytes: int = 2 * 1024 * 1024
    max_variants: int = 4
    max_response_bytes: int = 12 * 1024 * 1024
    provider_timeout_sec: float = 90.0
    max_retries: int = 2
    rate_per_minute: int = 20
    idempotency_ttl_sec: int = 3600


DEFAULT_LIMITS = StickerLimits()


class RateLimiter:
    """Simple in-process sliding window (lab/MVP). Prod → Redis."""

    def __init__(self, *, per_minute: int) -> None:
        self.per_minute = max(1, int(per_minute))
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


class IdempotencyStore:
    def __init__(self, *, ttl_sec: int) -> None:
        self.ttl_sec = max(60, int(ttl_sec))
        self._map: dict[str, tuple[float, str]] = {}
        self._lock = Lock()

    def get(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            item = self._map.get(key)
            if not item:
                return None
            ts, value = item
            if now - ts > self.ttl_sec:
                self._map.pop(key, None)
                return None
            return value

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._map[key] = (time.monotonic(), value)


def validate_prompt_length(text: str, *, limits: StickerLimits = DEFAULT_LIMITS) -> str:
    t = (text or "").strip()
    if not t:
        raise ValueError("empty_prompt")
    if len(t) > limits.max_prompt_chars:
        raise ValueError("prompt_too_long")
    return t


def validate_image_size(data: bytes, *, limits: StickerLimits = DEFAULT_LIMITS, kind: str = "image") -> None:
    if not data:
        raise ValueError(f"{kind}_empty")
    max_b = limits.max_mask_bytes if kind == "mask" else limits.max_image_bytes
    if len(data) > max_b:
        raise ValueError(f"{kind}_too_large")
