"""Вопрос оператору: пропушить чужую Bitcoin-транзакцию или вернуть оплату."""
from __future__ import annotations

import logging
import os
import re

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("payout_push")

_OPPUSH = re.compile(r"^oppush:(\d+):([01])$")
EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()


def parse_oppush(data: str) -> tuple[int, bool] | None:
    match = _OPPUSH.fullmatch((data or "").strip())
    if not match:
        return None
    return int(match.group(1)), match.group(2) == "1"


async def payout_push_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    parsed = parse_oppush(query.data or "")
    if not parsed:
        await query.answer()
        return
    bump_id, accept = parsed
    if not INTERNAL_TOKEN:
        await query.answer("Сервис недоступен", show_alert=True)
        return
    url = f"{EXCHANGE_API_URL}/api/internal/payout-push/answer"
    payload = {
        "bump_id": bump_id,
        "telegram_user_id": int(query.from_user.id),
        "accept": accept,
    }
    text = "Не удалось сохранить ответ"
    ok = False
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json=payload,
                headers={"X-Internal-Token": INTERNAL_TOKEN},
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 403:
                    await query.answer("Это не ваша выплата", show_alert=True)
                    return
                if resp.status < 400 and isinstance(data, dict):
                    ok = True
                    text = str(data.get("text") or ("Принято" if accept else "Вернули клиенту"))
    except Exception:
        logger.exception("operator push answer failed bump=%s", bump_id)
    await query.answer(text[:180], show_alert=not ok)
    if ok and query.message:
        try:
            await query.edit_message_text(text, reply_markup=None)
        except Exception:
            logger.debug("edit operator push message failed", exc_info=True)
