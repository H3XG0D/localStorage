"""Запрос PDF/видео для сделок кабинета внештатника (appeals Payfast)."""
from __future__ import annotations

import logging

from services.db import get_external_deal_by_merchant_ref, get_pool
from services.external_deal_ops_notify import notify_external_deal_ops

logger = logging.getLogger("external_deal_receipt_request")


async def request_external_deal_receipt_check(
    deal_id: int,
    req_type: int,
    *,
    bot=None,
    source: str = "appeals",
) -> tuple[bool, str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT d.*, e.name AS exchanger_name, ea.username AS account_username
            FROM external_deals d
            JOIN external_exchangers e ON e.id = d.exchanger_id
            LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
            WHERE d.id = $1
            """,
            deal_id,
        )
        if not row:
            return False, "deal_not_found"

        status = str(row["status"] or "")
        if status not in ("awaiting_receipt", "pending"):
            logger.info(
                "external deal receipt blocked deal=%s status=%s source=%s",
                deal_id,
                status,
                source,
            )
            return False, f"status_blocked ({status})"

        if req_type == 3:
            if status == "pending":
                await conn.execute(
                    """
                    UPDATE external_deals
                    SET status = 'awaiting_receipt',
                        required_receipt_type = 3,
                        receipt_submitted_at = NULL
                    WHERE id = $1
                    """,
                    deal_id,
                )
            else:
                await conn.execute(
                    "UPDATE external_deals SET required_receipt_type = 3 WHERE id = $1",
                    deal_id,
                )
            event = "video_requested"
        elif req_type == 2 and status == "pending":
            await conn.execute(
                """
                UPDATE external_deals
                SET status = 'awaiting_receipt',
                    required_receipt_type = 2,
                    receipt_submitted_at = NULL
                WHERE id = $1
                """,
                deal_id,
            )
            event = "success_receipt"
        else:
            await conn.execute(
                "UPDATE external_deals SET required_receipt_type = $1 WHERE id = $2",
                req_type,
                deal_id,
            )
            event = "success_receipt"

        refreshed = await conn.fetchrow(
            """
            SELECT d.*, e.name AS exchanger_name, ea.username AS account_username
            FROM external_deals d
            JOIN external_exchangers e ON e.id = d.exchanger_id
            LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
            WHERE d.id = $1
            """,
            deal_id,
        )

    if refreshed:
        await notify_external_deal_ops(event, dict(refreshed), bot=bot)
    return True, "ok"


async def request_external_deal_by_ref(
    ref: str,
    req_type: int,
    *,
    bot=None,
    source: str = "appeals",
) -> tuple[bool, str]:
    deal = await get_external_deal_by_merchant_ref(ref)
    if not deal:
        return False, "deal_not_found"
    return await request_external_deal_receipt_check(
        int(deal["id"]),
        req_type,
        bot=bot,
        source=source,
    )
