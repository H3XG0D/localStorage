"""Определение IP клиента за nginx + Cloudflare.

Заголовки X-Forwarded-For / CF-Connecting-IP / X-Real-IP учитываются
только если прямой peer (request.client) — доверенный прокси.
Иначе клиент мог бы подставить чужой IP.
"""
import ipaddress

from fastapi import Request

from trusted_ips import is_trusted_proxy


def _parse_ip(candidate: str | None) -> str | None:
    if not candidate or not candidate.strip():
        return None
    try:
        return str(ipaddress.ip_address(candidate.strip()))
    except ValueError:
        return None


def get_client_ip(request: Request) -> str | None:
    """Приоритет (только от trusted proxy): CF-Connecting-IP → X-Real-IP → X-Forwarded-For → direct."""
    direct = None
    if request.client:
        direct = _parse_ip(request.client.host)

    if direct and is_trusted_proxy(direct):
        for header in (
            "cf-connecting-ip",
            "x-real-ip",
        ):
            ip = _parse_ip(request.headers.get(header))
            if ip:
                return ip

        forwarded = (request.headers.get("x-forwarded-for") or "").strip()
        if forwarded:
            ip = _parse_ip(forwarded.split(",")[0].strip())
            if ip:
                return ip

    return direct
