"""Ops-уведомление с PDF-чеком по внештатной сделке."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config import settings
from db import get_pool
from external_deal_ops_notify import format_deal_ops_notify
from external_deals_telegram import external_deals_chat
from external_exchange_stats import fetch_exchanger_ops_stats
from telegram_notify import send_ops_document, send_ops_message

logger = logging.getLogger("external_deal_receipt_notify")


def _exchanger_ctx(exchanger: dict[str, Any]) -> dict[str, Any]:
    return {
        "exchanger_name": exchanger.get("exchanger_name") or exchanger.get("name"),
        "username": exchanger.get("username") or exchanger.get("account_username"),
        "is_trusted_client": exchanger.get("is_trusted_client"),
    }


async def _ops_stats_for_deal(deal: dict[str, Any]) -> dict[str, Any] | None:
    eid = deal.get("exchanger_id")
    if not eid:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await fetch_exchanger_ops_stats(conn, int(eid))


async def notify_ops_external_receipt(
    deal: dict[str, Any],
    exchanger: dict[str, Any],
    receipt_path: str | Path,
) -> None:
    """PDF-чек во внештатную группу (caption с меткой доверия)."""
    if not settings.telegram_bot_token:
        return
    path = Path(receipt_path)
    if not path.is_file():
        logger.warning("receipt notify: missing file %s", path)
        return

    caption = format_deal_ops_notify(
        "receipt",
        deal,
        _exchanger_ctx(exchanger),
        note="PDF чек для просмотра",
        ops_stats=await _ops_stats_for_deal(deal),
    )
    chat_id, topic_id = external_deals_chat()
    if not chat_id:
        logger.warning("external deals receipt notify skipped: chat not configured")
        return
    try:
        await send_ops_document(
            chat_id,
            str(path),
            caption,
            message_thread_id=topic_id,
        )
    except Exception as exc:
        logger.warning("external deals receipt document failed: %s", exc)


async def notify_ops_auto_confirmed(
    deal: dict[str, Any],
    exchanger: dict[str, Any],
) -> None:
    from telegram_notify import send_ops_message

    if not settings.telegram_bot_token:
        return
    stats = await _ops_stats_for_deal(deal)
    text = format_deal_ops_notify(
        "auto_confirmed", deal, _exchanger_ctx(exchanger), ops_stats=stats
    )
    chat_id, topic_id = external_deals_chat()
    if not chat_id:
        return
    try:
        await send_ops_message(text, chat_id=chat_id, message_thread_id=topic_id)
    except Exception as exc:
        logger.warning("external deals auto_confirmed notify failed: %s", exc)
