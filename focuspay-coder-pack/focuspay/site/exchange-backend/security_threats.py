"""Детекция подозрительных запросов по IP."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from threading import Lock
from typing import Any, Optional

from config import settings
from rate_limit_store import get_request_count, record_request
from trusted_ips import is_trusted_ip

_lock = Lock()
_auth_fail_windows: dict[str, list[float]] = defaultdict(list)

_SCANNER_PATTERNS = re.compile(
    r"(\.env|wp-admin|wp-login|phpmyadmin|\.git|/admin\.php|/xmlrpc|/\.well-known/security\.txt\.\.|/cgi-bin/|\.\./)",
    re.I,
)

# Password guessing only. GET /auth/me (and other session probes) 401 is the
# public SPA checking a cookie — not a brute-force attempt.
_LOGIN_PATH = re.compile(
    r"^/api/auth/(?:(?:admin|operator|partner|exchanger)/)?login(?:/2fa)?$",
    re.I,
)


def is_credential_auth_attempt(method: str, path: str) -> bool:
    if (method or "").upper() != "POST":
        return False
    path_l = (path or "").split("?")[0].rstrip("/") or "/"
    return bool(_LOGIN_PATH.match(path_l))


def evaluate_threat(
    *,
    ip: str,
    method: str,
    path: str,
    status_code: int,
    zone: str,
    scope: str | None,
    user_agent: str | None = None,
) -> tuple[Optional[str], int]:
    """Returns (threat_type, threat_score)."""
    path_l = (path or "").split("?")[0]
    ua = (user_agent or "").strip()

    if is_trusted_ip(ip):
        return None, 0

    # Defensive origin self-check (expects 401/403) — not an attacker.
    if ua.startswith("FocusPay-SelfCheck"):
        return "internal_probe", 0

    if _SCANNER_PATTERNS.search(path_l):
        return "scanner", 80

    if zone == "admin" and status_code in (401, 403) and scope != "admin":
        return "admin_probe", 70

    if zone == "operator" and status_code in (401, 403) and scope != "operator":
        return "operator_probe", 50

    if zone == "auth":
        # Успешный вход снимает накопленные промахи: человек, который опечатался
        # и потом вошёл, не должен оставаться в одном шаге от бана.
        if 200 <= status_code < 300:
            clear_auth_failures(ip)
        elif status_code in (401, 429) and is_credential_auth_attempt(method, path_l):
            now = time.time()
            window = int(settings.security_auth_fail_window_sec)
            threshold = int(settings.security_auth_fail_threshold)
            with _lock:
                recent = [t for t in _auth_fail_windows[ip] if now - t < window]
                recent.append(now)
                _auth_fail_windows[ip] = recent
                if len(recent) >= threshold:
                    return "auth_bruteforce", 75

    if path_l != "/api/health" and _rate_flood(ip):
        return "rate_flood", 85

    return None, 0


def clear_auth_failures(ip: str) -> None:
    """Drop the in-memory auth-fail window so an unban is not immediately re-armed."""
    if not ip:
        return
    with _lock:
        _auth_fail_windows.pop(ip, None)


def record_auth_failure(ip: str) -> Optional[str]:
    """Call on failed admin login; returns threat_type if threshold exceeded."""
    if not ip or is_trusted_ip(ip):
        return None
    now = time.time()
    window = int(settings.security_auth_fail_window_sec)
    threshold = int(settings.security_auth_fail_threshold)
    with _lock:
        recent = [t for t in _auth_fail_windows[ip] if now - t < window]
        recent.append(now)
        _auth_fail_windows[ip] = recent
        if len(recent) >= threshold:
            return "auth_fail_admin"
    return None


def is_ip_rate_limited(ip: str) -> bool:
    """Record request; True if IP exceeded security_rate_limit_per_min."""
    if not ip or is_trusted_ip(ip):
        return False
    limit = int(settings.security_rate_limit_per_min)
    return record_request(ip, 60) > limit


def _rate_flood(ip: str) -> bool:
    limit = int(settings.security_rate_limit_per_min)
    return get_request_count(ip, 60) > limit


def track_request_for_rate(ip: str) -> None:
    """No-op: blocking middleware already records requests."""
    return
