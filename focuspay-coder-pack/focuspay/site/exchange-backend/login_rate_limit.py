"""In-memory rate limit для login endpoints (per IP + username)."""
import time
from collections import defaultdict
from threading import Lock

_lock = Lock()
_attempts: dict[str, list[float]] = defaultdict(list)

DEFAULT_MAX_ATTEMPTS = 10
DEFAULT_WINDOW_SEC = 900


def login_allowed(key: str, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS, window_sec: int = DEFAULT_WINDOW_SEC) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _attempts[key] if now - t < window_sec]
        if len(recent) >= max_attempts:
            _attempts[key] = recent
            return False
        recent.append(now)
        _attempts[key] = recent
        return True
