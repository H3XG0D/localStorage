"""Telegram-алерты по подозрительной активности."""
from __future__ import annotations

import html
import logging
import time
import uuid
from threading import Lock
from typing import Any, Optional

import requests

from config import settings
from geoip_lookup import format_geo, lookup_geo
from trusted_ips import is_internal_ip, is_trusted_ip

logger = logging.getLogger("security_alerts")

_lock = Lock()
_last_sent: dict[str, float] = {}

SELFCHECK_UA_PREFIX = "FocusPay-SelfCheck"


_DANGEROUS_THREATS = frozenset(
    {
        "admin_force_close_shift",
        "auth_bruteforce",
        "auth_fail_admin",
        "rate_flood",
        "scanner",
    }
)


def is_dangerous_alert(threat_type: str, status_code: int = 0) -> bool:
    """Высокий приоритет только для реальной атаки, не для обычного 401 probe."""
    return threat_type in _DANGEROUS_THREATS or int(status_code) >= 500


def security_alert_chat_id() -> int | None:
    """Куда слать алерты: только SECURITY_TELEGRAM_* (не админ-группа ордеров)."""
    cid = int(settings.security_telegram_chat_id or 0)
    if cid:
        return cid
    uid = int(settings.security_telegram_user_id or 0)
    if uid:
        return uid
    return None


def is_loopback_ip(ip: str | None) -> bool:
    """Local health-checks / direct uvicorn probes — не спамим Telegram."""
    if not ip:
        return False
    s = ip.strip().lower()
    return s in ("127.0.0.1", "::1", "localhost") or s.startswith("127.")


def is_selfcheck_ua(user_agent: str | None) -> bool:
    return bool(user_agent) and user_agent.strip().startswith(SELFCHECK_UA_PREFIX)


def _normalize_route(path: str) -> str:
    return (path or "").split("?")[0][:200] or "/"


def _cooldown_key(ip: str, threat_type: str, path: str = "", status_code: int = 0) -> str:
    # Узкий ключ: одинаковые 401 на один route не флудят; другой path — отдельное окно.
    return f"{ip}:{threat_type}:{_normalize_route(path)}:{int(status_code)}"


def reset_alert_cooldowns_for_tests() -> None:
    with _lock:
        _last_sent.clear()


def should_send_alert(
    ip: str,
    threat_type: str,
    *,
    path: str = "",
    status_code: int = 0,
    user_agent: str | None = None,
) -> bool:
    if not settings.security_alerts_enabled:
        return False
    if not security_alert_chat_id() or not settings.telegram_bot_token:
        return False
    if threat_type in ("internal_probe", "selfcheck", "admin_probe", "operator_probe"):
        # Обычный 401 на панель и сканеры сессии — в лог, не в чат.
        return False
    if is_trusted_ip(ip):
        return False
    # Loopback / internal / trusted: лог в БД есть, Telegram нет.
    if (
        is_loopback_ip(ip)
        or is_internal_ip(ip)
        or is_trusted_ip(ip)
        or is_selfcheck_ua(user_agent)
    ) and threat_type in (
        "operator_probe",
        "admin_probe",
        "scanner",
        "rate_flood",
        "internal_probe",
        "selfcheck",
    ):
        return False
    key = _cooldown_key(ip, threat_type, path, status_code)
    now = time.time()
    cooldown = int(settings.security_alert_cooldown_sec)
    with _lock:
        last = _last_sent.get(key, 0)
        if now - last < cooldown:
            return False
        _last_sent[key] = now
    return True


def send_security_alert(
    *,
    threat_type: str,
    ip: str,
    path: str,
    method: str = "GET",
    status_code: int = 0,
    city: str | None = None,
    country_code: str | None = None,
    zone: str | None = None,
    extra: dict[str, Any] | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> None:
    if not should_send_alert(
        ip,
        threat_type,
        path=path,
        status_code=status_code,
        user_agent=user_agent,
    ):
        return

    if not city and not country_code:
        country_code, city = lookup_geo(ip)

    geo_line = html.escape(format_geo(ip, country_code, city))
    rid = (request_id or "").strip() or str(uuid.uuid4())

    dangerous = is_dangerous_alert(threat_type, status_code)
    heading = "ОПАСНО" if dangerous else "Безопасность"
    marker = "🚨" if dangerous else "⚠️"
    lines = [
        f"{marker} <b>{heading}: {html.escape(threat_type)}</b>",
        f"🆔 <code>{html.escape(rid[:64])}</code>",
        f"🌐 <code>{geo_line}</code>",
        f"📍 <code>{html.escape(method)}</code> {html.escape(path[:200])}",
        f"↩️ HTTP {status_code}",
    ]
    if zone:
        lines.append(f"Зона: {html.escape(zone)}")
    if user_agent:
        lines.append(f"UA: <code>{html.escape(user_agent[:120])}</code>")
    if extra:
        for k, v in list(extra.items())[:5]:
            lines.append(f"{html.escape(str(k))}: <code>{html.escape(str(v)[:120])}</code>")

    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": security_alert_chat_id(),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("security alert telegram HTTP %s: %s", resp.status_code, resp.text[:300])
    except Exception as e:
        logger.error("security alert failed: %s", e)
