"""Send Telegram DMs to partners (tier / rate notifications)."""
from __future__ import annotations

from https_fetch import https_urlopen

import json
import logging
import os
import urllib.request

logger = logging.getLogger("partner_telegram_notify")

COMMISSION_BASIS = "чистой прибыли сервиса"


def format_rate_change_message(
    *,
    new_percent: float,
    refs: int,
    tier_after: dict,
    old_percent: float | None = None,
    reason: str = "admin",
) -> str:
    site = os.getenv("PUBLIC_SITE_URL", "https://focuspay.org").rstrip("/")
    if old_percent is not None and abs(old_percent - new_percent) >= 0.01:
        head = (
            f"📈 <b>Ставка изменилась:</b> {old_percent:g}% → <b>{new_percent:g}%</b>\n"
            f"Начисление: <b>{new_percent:g}%</b> с {COMMISSION_BASIS} по каждой оплаченной сделке ваших клиентов."
        )
    else:
        head = (
            f"📈 <b>Ставка обновлена!</b> Теперь <b>{new_percent:g}%</b> с {COMMISSION_BASIS} "
            f"по каждой оплаченной сделке ваших клиентов."
        )

    lines = [head, f"\nПриведено клиентов: <b>{refs}</b>"]
    if tier_after.get("at_max_tier"):
        lines.append("Вы на максимальном уровне программы.")
    else:
        nxt = tier_after.get("next_tier_percent")
        until = tier_after.get("refs_until_next_tier", 0)
        if nxt is not None:
            lines.append(f"До {nxt:g}%: ещё <b>{until}</b> реф.")
    if reason == "admin":
        lines.append("\n<i>Ставку обновил администратор.</i>")
    lines.append(f"\n📊 Кабинет: {site}/partner/login")
    return "\n".join(lines)


async def send_partner_telegram_dm(telegram_user_id: int, text: str) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or not telegram_user_id:
        return
    payload = json.dumps(
        {"chat_id": int(telegram_user_id), "text": text, "parse_mode": "HTML"}
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with https_urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            logger.warning("partner telegram dm failed: %s", body)
    except Exception as e:
        logger.warning("partner telegram dm error: %s", e)


async def notify_partner_rate_change(
    telegram_user_id: int,
    *,
    old_percent: float,
    new_percent: float,
    refs: int,
    tier_after: dict,
    reason: str = "admin",
) -> None:
    if abs(old_percent - new_percent) < 0.01:
        return
    text = format_rate_change_message(
        new_percent=new_percent,
        old_percent=old_percent,
        refs=refs,
        tier_after=tier_after,
        reason=reason,
    )
    await send_partner_telegram_dm(telegram_user_id, text)
