"""Временная блокировка IP при высоком threat_score."""
from __future__ import annotations

import ipaddress
import logging
import os
import subprocess  # nosec B404 — fail2ban bridge only; argv allowlisted in _maybe_fail2ban_unban
import time
from threading import Lock

from config import settings
from trusted_ips import is_trusted_ip

logger = logging.getLogger("ip_blocklist")

_lock = Lock()
_blocked: dict[str, float] = {}
_redis_client = None
_redis_checked = False


def _ip_variants(ip: str) -> list[str]:
    """Forms that may have been used as Redis/memory keys (IPv4 + compressed/exploded IPv6)."""
    raw = (ip or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in out:
            out.append(value)

    add(raw)
    if raw.startswith("[") and "]" in raw:
        add(raw[1 : raw.index("]")])
    core = out[-1]
    if "/" in core:
        add(core.split("/", 1)[0])
    core = out[-1]
    if "%" in core:
        add(core.split("%", 1)[0])
    try:
        parsed = ipaddress.ip_address(out[-1])
        add(str(parsed))
        if isinstance(parsed, ipaddress.IPv6Address):
            add(parsed.compressed)
            add(parsed.exploded)
    except ValueError:
        pass
    return out


def _ban_keys(ip: str) -> list[str]:
    return [f"ban:{variant}" for variant in _ip_variants(ip)]

def _auto_ban_score() -> int:
    return int(getattr(settings, "security_ip_ban_score", 70) or 70)


def _default_ban_sec() -> int:
    return int(getattr(settings, "security_ip_ban_sec", 3600) or 3600)


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
        logger.info("ip blocklist: using Redis")
        return _redis_client
    except Exception as e:
        logger.warning("ip blocklist: Redis unavailable (%s), using memory", e)
        _redis_client = None
        return None


def _is_loopback_ip(ip: str) -> bool:
    raw = (ip or "").strip()
    if not raw:
        return False
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    raw = raw.split("%", 1)[0]
    try:
        return ipaddress.ip_address(raw).is_loopback
    except ValueError:
        return raw in ("127.0.0.1", "::1", "localhost")


def _is_staging() -> bool:
    return (settings.environment or "").strip().lower() == "staging"


def ban_ip(ip: str, *, duration_sec: int | None = None, reason: str = "") -> None:
    duration_sec = duration_sec if duration_sec is not None else _default_ban_sec()
    if not ip:
        return
    if _is_loopback_ip(ip) or _is_staging():
        logger.debug("skip ban ip=%s reason=%s", ip, reason)
        return
    until = time.time() + max(60, int(duration_sec))
    r = _get_redis()
    if r is not None:
        try:
            r.setex(f"ban:{ip}", max(60, int(duration_sec)), reason or "threat")
            logger.warning("ip banned (redis) ip=%s reason=%s", ip, reason)
            return
        except Exception as e:
            logger.debug("redis ban fallback: %s", e)
    with _lock:
        _blocked[ip] = until
    logger.warning("ip banned (memory) ip=%s reason=%s", ip, reason)


def is_ip_banned(ip: str) -> bool:
    if not ip or is_trusted_ip(ip) or _is_loopback_ip(ip) or _is_staging():
        return False
    now = time.time()
    r = _get_redis()
    if r is not None:
        try:
            return bool(r.exists(f"ban:{ip}"))
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
    with _lock:
        until = _blocked.get(ip)
        if until is None:
            return False
        if now >= until:
            del _blocked[ip]
            return False
        return True


def maybe_ban_for_threat(ip: str, threat_type: str | None, threat_score: int) -> None:
    if not ip or not threat_type or threat_score < _auto_ban_score():
        return
    if is_trusted_ip(ip):
        return
    # Сканеры, пробы кабинетов и rate flood — алерт без бана (операторский чат даёт много запросов).
    if threat_type in ("scanner", "admin_probe", "operator_probe", "rate_flood", "internal_probe"):
        return
    ban_ip(ip, reason=threat_type)


def _maybe_fail2ban_unban(ip: str) -> None:
    """Best-effort: only the existing bridge script, no new jail."""
    if not getattr(settings, "security_fail2ban_bridge", False):
        return
    script = (getattr(settings, "security_fail2ban_bridge_script", "") or "").strip()
    if not script or not os.path.isabs(script) or not os.path.isfile(script):
        return
    try:
        parsed = ipaddress.ip_address((ip or "").strip().strip("[]").split("/", 1)[0])
    except ValueError:
        return
    try:
        subprocess.run(  # nosec B603 — settings script + verb unban + parsed IP only
            [script, "unban", str(parsed)],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        logger.debug("fail2ban unban skipped ip=%s", ip, exc_info=True)


def _clear_auth_fail_window(ip: str) -> None:
    try:
        from security_threats import clear_auth_failures

        for variant in _ip_variants(ip):
            clear_auth_failures(variant)
    except Exception:
        logger.debug("auth-fail window clear skipped ip=%s", ip, exc_info=True)


def unban_ip(ip: str) -> dict:
    """Lift Redis/memory app ban. Idempotent: already gone → ok."""
    variants = _ip_variants(ip)
    if not variants:
        return {"ok": True, "ip": ip or "", "was_banned": False, "reason": None}
    canonical = variants[0]
    try:
        canonical = str(ipaddress.ip_address(variants[-1] if variants else ip))
    except ValueError:
        canonical = variants[0]

    was_banned = False
    reason = None
    r = _get_redis()
    if r is not None:
        try:
            keys = _ban_keys(ip)
            for key in keys:
                try:
                    val = r.get(key)
                    if val is not None and reason is None:
                        reason = val
                except Exception:
                    logger.debug("ignored non-fatal error", exc_info=True)
            deleted = 0
            try:
                deleted = int(r.delete(*keys) or 0)
            except TypeError:
                for key in keys:
                    try:
                        deleted += int(r.delete(key) or 0)
                    except Exception:
                        logger.debug("ignored non-fatal error", exc_info=True)
            if deleted:
                was_banned = True
        except Exception as e:
            logger.debug("redis unban fallback: %s", e)

    now = time.time()
    with _lock:
        for variant in variants:
            until = _blocked.pop(variant, None)
            if until is not None and until > now:
                was_banned = True

    _clear_auth_fail_window(canonical)
    _maybe_fail2ban_unban(canonical)
    if was_banned:
        logger.warning("ip unbanned ip=%s reason=%s", canonical, reason)
    return {
        "ok": True,
        "ip": canonical,
        "was_banned": was_banned,
        "reason": reason,
    }


def list_bans() -> list[dict]:
    items: list[dict] = []
    r = _get_redis()
    if r is not None:
        try:
            for key in r.scan_iter("ban:*", count=200):
                ip = key[4:] if isinstance(key, str) and key.startswith("ban:") else str(key)
                try:
                    ttl = int(r.ttl(key) or 0)
                except Exception:
                    ttl = 0
                try:
                    reason = r.get(key)
                except Exception:
                    reason = None
                items.append({"ip": ip, "ttl_sec": ttl, "reason": reason})
            items.sort(key=lambda row: str(row.get("ip") or ""))
            return items
        except Exception as e:
            logger.debug("redis list bans fallback: %s", e)
    now = time.time()
    with _lock:
        for ip, until in _blocked.items():
            if until > now:
                items.append({"ip": ip, "ttl_sec": int(until - now), "reason": "memory"})
    items.sort(key=lambda row: str(row.get("ip") or ""))
    return items


def get_ban(ip: str) -> dict | None:
    if not ip:
        return None
    r = _get_redis()
    if r is not None:
        try:
            for key in _ban_keys(ip):
                if r.exists(key):
                    try:
                        ttl = int(r.ttl(key) or 0)
                    except Exception:
                        ttl = 0
                    try:
                        reason = r.get(key)
                    except Exception:
                        reason = None
                    return {"ip": key[4:], "ttl_sec": ttl, "reason": reason}
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
    now = time.time()
    with _lock:
        for variant in _ip_variants(ip):
            until = _blocked.get(variant)
            if until is not None and until > now:
                return {"ip": variant, "ttl_sec": int(until - now), "reason": "memory"}
    return None
