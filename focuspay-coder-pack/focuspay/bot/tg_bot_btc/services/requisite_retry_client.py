"""Черновик повторного запроса реквизитов через внутренний API."""
from __future__ import annotations

import logging
import os

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("requisite_retry")

EXCHANGE_API_URL = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = (os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()

RETRY_BUTTON = "Повторить запрос реквизитов"
RETRY_CALLBACK = "payin:retry"
REKI_CALLBACK = "payin:reki"


def retry_keyboard(reki_pay_rub=None) -> InlineKeyboardMarkup:
    rows = []
    if reki_pay_rub:
        amount = int(round(float(reki_pay_rub)))
        rows.append(
            [
                InlineKeyboardButton(
                    f"Оформить на {amount} ₽",
                    callback_data=f"{REKI_CALLBACK}:{amount}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(RETRY_BUTTON, callback_data=RETRY_CALLBACK)])
    return InlineKeyboardMarkup(rows)


def retry_saved_text() -> str:
    return (
        "⚠️ <b>Сейчас нет свободных реквизитов.</b>\n\n"
        "Параметры сделки сохранены на 30 минут. "
        "Повторить запрос реквизитов можно раз в 5 минут."
    )


def retry_still_empty_text() -> str:
    return (
        "⚠️ <b>Реквизитов всё ещё нет.</b>\n\n"
        "Запрос висит ещё в пределах 30 минут. "
        "Следующее нажатие — не раньше чем через 5 минут."
    )


def retry_wait_text(message: str | None) -> str:
    text = (message or "").strip()
    if text:
        return f"⏳ {text}"
    return "⏳ Повторить запрос можно через 5 минут."


def retry_expired_text() -> str:
    return "Время запроса вышло. Начните обмен заново."


def reki_offer_text(fit) -> str | None:
    """Подсказка по свободному коридору сумм. None — предлагать нечего.

    Обещаем только пересчёт суммы заявки: зачёт переплаты на баланс предлагает
    отдельный диалог рельса, когда он действительно может его сделать.
    """
    from services.reki_snapshot import FIT_OVER_PAY, FIT_TOP_UP

    if fit is None or fit.kind not in (FIT_TOP_UP, FIT_OVER_PAY):
        return None
    pay = int(round(float(fit.pay_rub)))
    diff = int(round(float(fit.diff_rub)))
    if diff <= 0:
        return None
    if fit.kind == FIT_OVER_PAY:
        return (
            f"\n\n💡 Сейчас свободен реквизит на <b>{pay} ₽</b> — на {diff} ₽ больше вашей суммы. "
            "Можно оформить обмен на него: крипту получите на всю эту сумму."
        )
    return (
        f"\n\n💡 Сейчас свободен реквизит максимум на <b>{pay} ₽</b> — на {diff} ₽ меньше вашей суммы. "
        "Можно оформить обмен на него, остаток обменяете отдельно."
    )


async def _post(path: str, payload: dict) -> dict | None:
    if not INTERNAL_TOKEN:
        logger.warning("requisite retry skipped: INTERNAL_API_SECRET not set")
        return None
    url = f"{EXCHANGE_API_URL}/api/internal{path}"
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status >= 400:
                    text = await response.text()
                    logger.warning(
                        "requisite retry %s -> %s: %s",
                        path,
                        response.status,
                        text[:200],
                    )
                    return None
                data = await response.json(content_type=None)
                return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("requisite retry %s failed: %s", path, exc)
        return None


async def open_requisite_retry(payload: dict) -> dict | None:
    return await _post("/requisite-retries", payload)


async def claim_requisite_retry(user_id: int) -> dict | None:
    return await _post("/requisite-retries/attempt", {"user_id": int(user_id)})


async def close_requisite_retry(user_id: int, order_id: str) -> None:
    if not order_id:
        return
    await _post(
        "/requisite-retries/close",
        {"user_id": int(user_id), "order_id": str(order_id)},
    )
