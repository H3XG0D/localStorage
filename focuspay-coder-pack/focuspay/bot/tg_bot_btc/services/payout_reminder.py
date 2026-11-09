"""Напоминания операторам раз в 5 мин о BUY-заявках, подтверждённых мерчантом,
но ещё не выплаченных (status COMPLETED). Прекращаются автоматически, когда
оператор отправляет крипту (status → PAID) или заявка отменяется."""
from __future__ import annotations

import asyncio
import logging

from services import config_rates
from services.callback_signatures import sign_order
from services.db import (
    get_completed_buy_orders_for_payout_reminder,
    ops_alert_was_sent,
)
from services.order_ops_notify import notify_ops_order

logger = logging.getLogger("payout_reminder")

REMINDER_INTERVAL_SEC = 300


async def payout_reminder_task(
    bot,
    *,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    if not config_rates.ops_group_id():
        logger.info("ops group not configured — payout reminder disabled")
        return

    while True:
        if shutdown_event and shutdown_event.is_set():
            break
        try:
            orders = await get_completed_buy_orders_for_payout_reminder(
                min_age_seconds=REMINDER_INTERVAL_SEC
            )
            for row in orders:
                order = dict(row)
                oid = str(order.get("order_id"))
                if not oid:
                    continue
                # Напоминание только после карточки «мерчант подтвердил» —
                # иначе в ops-чате «ожидает выплату» может прийти раньше.
                if not await ops_alert_was_sent(oid, "merchant_confirmed_notify"):
                    continue
                try:
                    await notify_ops_order(
                        "payout_reminder",
                        order,
                        bot=bot,
                        pay_signature=sign_order(oid),
                    )
                except Exception as e:
                    logger.warning("payout reminder send failed order=%s: %s", oid, e)
        except Exception as e:
            logger.exception("payout_reminder error: %s", e)

        if shutdown_event:
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=REMINDER_INTERVAL_SEC
                )
                break
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(REMINDER_INTERVAL_SEC)
