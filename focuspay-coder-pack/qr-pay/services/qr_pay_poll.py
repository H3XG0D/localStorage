"""Фолбэк-опрос статуса оплат по QR, когда вебхук не дошёл.

Платформа повторяет доставку 10 часов; если наш сервер был недоступен всё это время,
итог придётся спросить самим. Интервал опроса одного платежа нарастает:
2, 4, 8, 16, 32 секунды, дальше раз в 30 секунд.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from services import finance666_client as api
from services.db import get_pool
from services.finance666_client import Finance666Error

logger = logging.getLogger("qr_pay_poll")

TICK_SECONDS = 2
POLL_BACKOFF_SEC = (2, 4, 8, 16, 32)
POLL_STEADY_SEC = 30
# После 10 часов повторов платформа сдаётся — и мы тоже, дальше это случай для оператора.
GIVE_UP_AFTER = timedelta(hours=11)

_next_poll_at: dict[str, datetime] = {}
_attempts: dict[str, int] = {}


def _schedule_next(payment_id: str) -> None:
    attempt = _attempts.get(payment_id, 0)
    delay = POLL_BACKOFF_SEC[attempt] if attempt < len(POLL_BACKOFF_SEC) else POLL_STEADY_SEC
    _attempts[payment_id] = attempt + 1
    _next_poll_at[payment_id] = datetime.now(timezone.utc) + timedelta(seconds=delay)


def _forget(payment_id: str) -> None:
    _next_poll_at.pop(payment_id, None)
    _attempts.pop(payment_id, None)


async def _pending_payments() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT merchant_transaction_id, provider_transaction_id, created_at
            FROM qr_sbp_payments
            WHERE local_status = 'RESERVED' AND is_final = FALSE
            ORDER BY created_at
            LIMIT 50
            """
        )
    return [dict(row) for row in rows]


async def poll_once() -> int:
    """Опросить все платежи, которым пришёл срок. Возвращает число запросов."""
    from services.qr_pay_flow import apply_outcome

    if not api.configured():
        return 0
    now = datetime.now(timezone.utc)
    polled = 0
    for row in await _pending_payments():
        payment_id = str(row["merchant_transaction_id"])
        provider_tx = str(row.get("provider_transaction_id") or "")
        if not provider_tx:
            continue
        created = row.get("created_at")
        if created and now - created > GIVE_UP_AFTER:
            _forget(payment_id)
            continue
        due = _next_poll_at.get(payment_id)
        if due is None:
            _schedule_next(payment_id)
            continue
        if due > now:
            continue
        polled += 1
        try:
            payment = await api.transaction_status(provider_tx)
        except Finance666Error as exc:
            logger.warning("qr poll %s failed: %s", payment_id, exc)
            _schedule_next(payment_id)
            continue
        if payment.status.is_final:
            await apply_outcome(payment_id, payment)
            _forget(payment_id)
        else:
            _schedule_next(payment_id)
    return polled


MERCHANT_BALANCE_CHECK_SEC = 600

_low_balance_warned = False


async def check_merchant_balance() -> None:
    """Пустой USDT-пул ломает оплату всем клиентам — предупреждаем операторов заранее."""
    global _low_balance_warned
    from services.qr_pay_flow import ops_notify
    from services.qr_pay_status import merchant_balance
    from services.runtime_settings import qr_pay_min_merchant_usdt

    if not api.configured():
        return
    available = await merchant_balance(force=True)
    if available is None:
        return
    threshold = qr_pay_min_merchant_usdt()
    if available < threshold:
        if not _low_balance_warned:
            ops_notify(
                [
                    "<b>⚠️ Оплата по QR · баланс finance666 на исходе</b>",
                    f"Доступно: <b>{available:,.2f} USDT</b>".replace(",", " "),
                    f"Порог: {threshold:,.2f} USDT".replace(",", " "),
                    "Клиентам показываем «временно недоступно». Пополните баланс.",
                ]
            )
            _low_balance_warned = True
    else:
        _low_balance_warned = False


async def qr_pay_balance_monitor_task(*, shutdown_event: asyncio.Event | None = None) -> None:
    while shutdown_event is None or not shutdown_event.is_set():
        try:
            await check_merchant_balance()
        except Exception:
            logger.warning("merchant balance monitor failed", exc_info=True)
        if shutdown_event is None:
            await asyncio.sleep(MERCHANT_BALANCE_CHECK_SEC)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=MERCHANT_BALANCE_CHECK_SEC)
        except asyncio.TimeoutError:
            continue


async def qr_pay_poll_task(*, shutdown_event: asyncio.Event | None = None) -> None:
    while shutdown_event is None or not shutdown_event.is_set():
        try:
            await poll_once()
        except Exception:
            logger.warning("qr pay poll tick failed", exc_info=True)
        if shutdown_event is None:
            await asyncio.sleep(TICK_SECONDS)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            continue
