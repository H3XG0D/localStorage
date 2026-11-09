"""Сообщения Appeals Payfast в группе споров → запрос чека/видео у клиента."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes
from telegram.ext.filters import MessageFilter

from services.appeals_messages import (
    parse_appeals_success_receipt_request,
    parse_appeals_video_request,
)
from services.config_rates import is_appeals_group_chat
from services.db import get_external_deal_by_merchant_ref, get_order_by_merchant_ref
from services.external_deal_receipt_request import request_external_deal_by_ref
from services.video_receipt_request import request_client_receipt_check

logger = logging.getLogger("appeals_listener")


class AppealsGroupFilter(MessageFilter):
    def filter(self, message) -> bool:  # type: ignore[override]
        return bool(message and message.chat and is_appeals_group_chat(message.chat.id))


appeals_group_filter = AppealsGroupFilter()


async def _handle_appeals_receipt_ref(
    ref: str,
    *,
    req_type: int,
    source: str,
    allow_late: bool,
    bot,
) -> None:
    order = await get_order_by_merchant_ref(ref)
    if order:
        ok, reason = await request_client_receipt_check(
            str(order["order_id"]),
            req_type,
            bot=bot,
            source=source,
            allow_late=allow_late,
        )
        if not ok:
            logger.warning(
                "appeals receipt request failed ref=%s order=%s reason=%s",
                ref,
                order.get("order_id"),
                reason,
            )
        return

    ext_deal = await get_external_deal_by_merchant_ref(ref)
    if not ext_deal:
        logger.warning("appeals receipt request: order/deal not found ref=%s", ref)
        return

    ok, reason = await request_external_deal_by_ref(
        ref,
        req_type,
        bot=bot,
        source=source,
    )
    if not ok:
        logger.warning(
            "appeals external deal receipt failed ref=%s deal=%s reason=%s",
            ref,
            ext_deal.get("id"),
            reason,
        )


async def appeals_video_request_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message or update.edited_message
    if not msg or not msg.chat:
        return
    if not is_appeals_group_chat(msg.chat.id):
        return

    text = (msg.text or msg.caption or "").strip()

    success_ref = parse_appeals_success_receipt_request(text)
    if success_ref:
        await _handle_appeals_receipt_ref(
            success_ref,
            req_type=2,
            source="appeals_success_receipt",
            allow_late=True,
            bot=context.bot,
        )
        return

    video_ref = parse_appeals_video_request(text)
    if not video_ref:
        return

    await _handle_appeals_receipt_ref(
        video_ref,
        req_type=3,
        source="appeals",
        allow_late=False,
        bot=context.bot,
    )
