from __future__ import annotations

import html
import ipaddress
import os
from urllib.parse import urlparse

_PRIVATE_HOSTS = frozenset(
    {
        "localhost",
        "gateway",
        "backend",
        "postgres",
        "redis",
        "nginx",
        "fake-payfast",
    }
)


def public_site_url() -> str:
    return (os.getenv("PUBLIC_SITE_URL") or "https://focuspay.org").rstrip("/")


def support_chat_url() -> str:
    """Чат поддержки на сайте (виджет)."""
    return f"{public_site_url()}/?chat=1"


def telegram_web_url(url: str | None) -> str | None:
    """URL, который Telegram принимает на inline-кнопке и в <a href>.

    Staging `PUBLIC_SITE_URL=http://gateway:8080` сюда не проходит: Bot API
    отвечает BUTTON_URL_INVALID, и уже созданная заявка выглядит как
    «Ошибка, начните сначала».
    """
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme == "tg":
        return raw
    if scheme not in ("http", "https") or not host:
        return None
    if host in _PRIVATE_HOSTS:
        return None
    if host.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            return None
        return raw
    if not ip.is_global:
        return None
    return raw


def telegram_href(label: str, url: str | None) -> str:
    """`<a href>` if Telegram will accept the URL, else a plain escaped label."""
    safe = telegram_web_url(url)
    if not safe:
        return html.escape(label)
    return f'<a href="{html.escape(safe, quote=True)}">{html.escape(label)}</a>'
