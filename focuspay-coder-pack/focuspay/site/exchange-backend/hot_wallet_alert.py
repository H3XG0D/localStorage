"""Личка старшему финансисту на смене, когда горячий кошелёк ниже порога.

Повтор не чаще раза в 4 часа. Если на смене никого нет — не запоминаем отправку,
чтобы следующий заступивший получил сообщение сразу. Нет связи с кошельком —
не считаем это восстановлением и не сбрасываем таймер.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import settings
from hot_wallet_runway import fmt_crypto, fmt_rub

logger = logging.getLogger("hot_wallet_alert")

ALERT_KEY = "hot_wallet_low_alert"
REPEAT = timedelta(hours=4)

_SENIORS_SQL = """
SELECT DISTINCT oa.telegram_user_id
FROM operator_accounts oa
JOIN operator_shifts os
  ON os.operator_id = oa.id AND os.ended_at IS NULL
JOIN operator_role_profiles p
  ON p.operator_id = oa.id
 AND p.valid_to IS NULL
 AND p.role = 'finance'
 AND p.grade = 'senior'
WHERE oa.is_active IS TRUE
  AND oa.telegram_user_id IS NOT NULL
"""


def alert_due(last_sent_at: datetime | None, now: datetime) -> bool:
    if last_sent_at is None:
        return True
    sent = last_sent_at
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return moment - sent >= REPEAT


def format_low_balance_message(runway: dict[str, Any]) -> str:
    lines = ["<b>Низкий баланс горячего кошелька</b>"]
    for coin in runway.get("coins") or []:
        name = html.escape(str(coin.get("coin") or "").upper())
        spend = html.escape(fmt_crypto(float(coin.get("spendable") or 0)))
        rub = html.escape(fmt_rub(float(coin.get("value_rub") or 0)))
        hours = html.escape(str(coin.get("hours_phrase") or "темпа нет"))
        lines.append(f"{name} {spend} · ≈ {rub} ₽ · {hours}")
    floor = str(runway.get("floor_phrase") or "").strip()
    if floor:
        lines.append(html.escape(floor))
    return "\n".join(lines)


def parse_last_sent(value: Any) -> datetime | None:
    if value is None:
        return None
    raw: Any = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    text = raw.get("last_sent_at")
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


async def load_last_sent(conn) -> datetime | None:
    row = await conn.fetchrow("SELECT value FROM app_settings WHERE key = $1", ALERT_KEY)
    if not row:
        return None
    return parse_last_sent(row["value"])


async def save_last_sent(conn, when: datetime) -> None:
    payload = json.dumps({"last_sent_at": when.astimezone(timezone.utc).isoformat()})
    await conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES ($1, $2::jsonb, now())
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now()
        """,
        ALERT_KEY,
        payload,
    )


async def clear_last_sent(conn) -> None:
    await conn.execute("DELETE FROM app_settings WHERE key = $1", ALERT_KEY)


async def finance_seniors_on_shift(conn) -> list[int]:
    rows = await conn.fetch(_SENIORS_SQL)
    ids: list[int] = []
    for row in rows:
        raw = row["telegram_user_id"]
        if raw is None:
            continue
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            continue
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def send_telegram_dms(chat_ids: list[int], text: str) -> bool:
    token = (settings.telegram_bot_token or "").strip()
    if not token or not chat_ids:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok_any = False
    for chat_id in chat_ids:
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": int(chat_id),
                    "text": text[:3500],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code < 400:
                ok_any = True
            else:
                logger.warning("hot wallet alert telegram %s: %s", chat_id, resp.status_code)
        except Exception:
            logger.warning("hot wallet alert telegram failed chat=%s", chat_id, exc_info=True)
    return ok_any


async def maybe_alert_low_hot_wallet(
    conn,
    runway: dict[str, Any],
    *,
    now: datetime | None = None,
    send=None,
) -> bool:
    """True, если сообщение ушло хотя бы одному старшему."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    last = await load_last_sent(conn)
    if not runway.get("available"):
        return False
    if not runway.get("below_floor"):
        if last is not None:
            await clear_last_sent(conn)
        return False
    if not alert_due(last, moment):
        return False
    recipients = await finance_seniors_on_shift(conn)
    if not recipients:
        return False
    text = format_low_balance_message(runway)
    sender = send or send_telegram_dms
    sent = await asyncio.to_thread(sender, recipients, text)
    if sent:
        await save_last_sent(conn, moment)
    return bool(sent)


async def alert_hot_wallet_tick() -> None:
    from db import get_pool
    from hot_wallet_runway import build_hot_wallet_runway

    pool = await get_pool()
    async with pool.acquire() as conn:
        runway = await build_hot_wallet_runway(conn)
        await maybe_alert_low_hot_wallet(conn, runway)
