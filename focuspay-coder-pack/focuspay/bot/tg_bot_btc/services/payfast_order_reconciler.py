"""Сверка BUY с Payfast — доводим подтверждённые платежи до COMPLETED."""
from __future__ import annotations

import asyncio
import logging

from services.db import get_buy_orders_for_payfast_reconcile, get_order
from services.payfast_buy_complete import complete_buy_from_payfast_settled
from services.payfast_payin_guard import (
    PAYFAST_REVIEW_HOLD_REASONS,
    handle_payfast_recheck,
    keep_order_alive_for_payfast_review,
    payfast_status_file_from_payload,
    payfast_status_from_payload,
    verify_payfast_ready_for_payout,
)

logger = logging.getLogger("payfast_order_reconciler")

RECONCILE_INTERVAL_SEC = 120
RECONCILE_MIN_AGE_SEC = 90


async def reconcile_one_order(order: dict) -> bool:
    """Проверить Payfast и при settled перевести в COMPLETED. Returns True if completed."""
    order_id = str(order["order_id"])
    status = str(order.get("status") or "").upper()
    if status not in ("CREATED", "PENDING", "AWAITING_CHECK"):
        return False

    ok_pf, pf_err, resp = await verify_payfast_ready_for_payout(dict(order), require_uuid=True)
    if status == "CREATED":
        if not ok_pf:
            logger.debug("reconcile recovery skip order=%s payfast=%s", order_id, pf_err)
            return False
        from services.db import update_order_status

        if not await update_order_status(order_id, "PENDING"):
            logger.warning("reconcile recovery CREATED→PENDING rejected order=%s", order_id)
            return False
        refreshed = await get_order(order_id)
        if not refreshed:
            return False
        order = dict(refreshed)
        status = "PENDING"
        logger.info("reconcile recovery accepted PayFast payment order=%s", order_id)

    if pf_err == "payfast_recheck_requested":
        await handle_payfast_recheck(dict(order), resp, source="reconciler")
        return False
    if pf_err in PAYFAST_REVIEW_HOLD_REASONS:
        await keep_order_alive_for_payfast_review(
            dict(order), resp, pf_err=pf_err, source="reconciler"
        )
        return False
    if not ok_pf:
        logger.debug("reconcile skip order=%s payfast=%s", order_id, pf_err)
        return False
    if status not in ("PENDING", "AWAITING_CHECK"):
        return False

    ok, err = await complete_buy_from_payfast_settled(
        order_id,
        dict(order),
        verified_payfast_response=resp,
    )
    if not ok:
        logger.debug("reconcile order=%s not completed: %s", order_id, err)
        return False

    logger.info(
        "reconcile completed order=%s → COMPLETED payfast_status=%s file=%s",
        order_id,
        payfast_status_from_payload(resp),
        payfast_status_file_from_payload(resp),
    )
    return True


async def payfast_order_reconciler_task(
    *,
    shutdown_event: asyncio.Event | None = None,
    interval_sec: int = RECONCILE_INTERVAL_SEC,
    min_age_sec: int = RECONCILE_MIN_AGE_SEC,
) -> None:
    while True:
        if shutdown_event and shutdown_event.is_set():
            break
        try:
            rows = await get_buy_orders_for_payfast_reconcile(min_age_sec)
            for row in rows:
                try:
                    await reconcile_one_order(dict(row))
                except Exception:
                    logger.exception(
                        "reconcile failed order=%s", row.get("order_id")
                    )
        except Exception:
            logger.exception("payfast_order_reconciler loop error")

        if shutdown_event is None:
            await asyncio.sleep(interval_sec)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_sec)
            break
        except asyncio.TimeoutError:
            pass
