"""IP-адреса без авто-бана и rate limit (владелец, офис) + internal probes."""
from __future__ import annotations

import ipaddress
from functools import lru_cache

from config import settings


def _csv_set(raw: str | None) -> frozenset[str]:
    if not (raw or "").strip():
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def _normalize_ip(ip: str) -> str:
    raw = (ip or "").strip()
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    raw = raw.split("%", 1)[0]
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    return raw.strip()


@lru_cache
def trusted_ip_set() -> frozenset[str]:
    return _csv_set(getattr(settings, "security_trusted_ips", None))


@lru_cache
def internal_ip_set() -> frozenset[str]:
    return _csv_set(getattr(settings, "security_internal_ips", None))


@lru_cache
def trusted_proxy_set() -> frozenset[str]:
    raw = (getattr(settings, "security_trusted_proxies", None) or "").strip()
    if not raw:
        return frozenset({"127.0.0.1", "::1"})
    return _csv_set(raw)


def clear_trusted_ip_caches() -> None:
    trusted_ip_set.cache_clear()
    internal_ip_set.cache_clear()
    trusted_proxy_set.cache_clear()


def is_trusted_ip(ip: str | None) -> bool:
    if not ip:
        return False
    raw = _normalize_ip(ip)
    if not raw:
        return False
    trusted = trusted_ip_set()
    if raw in trusted:
        return True
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if parsed.compressed in trusted or parsed.exploded in trusted:
        return True
    for item in trusted:
        try:
            if "/" in item:
                if parsed in ipaddress.ip_network(item, strict=False):
                    return True
            elif parsed == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue
    return False


def is_internal_ip(ip: str | None) -> bool:
    """Server self-IP / hairpin selfcheck — не Telegram-спам."""
    if not ip:
        return False
    return ip in internal_ip_set()


def is_trusted_proxy(ip: str | None) -> bool:
    if not ip:
        return False
    s = ip.strip().lower()
    if s in trusted_proxy_set():
        return True
    if s in ("127.0.0.1", "::1") or s.startswith("127."):
        return True
    return False
