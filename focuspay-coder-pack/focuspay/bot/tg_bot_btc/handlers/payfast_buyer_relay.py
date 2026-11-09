"""/msg в рабочих чатах: текст покупателю, ответ копируется без профиля."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from handlers.appeals_stat import can_run_stat, client_alias
from services.db import find_order_for_stat, get_external_deal_by_merchant_ref
from services.operator_availability import get_shift_gate
from services.payfast_buyer_relay import (
    COPY_FAILED,
    HINT,
    MAX_BODY_LEN,
    NOT_DELIVERED,
    NOT_FOUND,
    NO_BUYER,
    SHIFT_ON,
    SHIFT_UNKNOWN,
    TOO_LONG,
    find_relay_anchor,
    format_buyer_dm,
    format_client_label,
    format_group_ack,
    insert_relay_anchor,
    parse_msg_command,
    relay_shift_block_reason,
    reply_reaches_receipt_handler,
)

logger = logging.getLogger("payfast_buyer_relay")


def _thread_id(message) -> int | None:
    raw = getattr(message, "message_thread_id", None)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value or None


def _buyer_id(order: dict) -> int:
    try:
        return int(order.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


async def payfast_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message or update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat:
        return
    sender_id = int(getattr(user, "id", 0) or 0)
    if not can_run_stat(chat.id, sender_id):
        logger.info("msg ignored chat=%s user=%s", chat.id, sender_id or None)
        return

    try:
        gate = await get_shift_gate()
    except Exception as exc:
        logger.warning("msg shift gate failed: %s", exc)
        await msg.reply_text(SHIFT_UNKNOWN)
        return
    block = relay_shift_block_reason(gate)
    if block == "check_failed":
        await msg.reply_text(SHIFT_UNKNOWN)
        return
    if block:
        await msg.reply_text(SHIFT_ON)
        return

    ref, body = parse_msg_command(getattr(msg, "text", None) or "")
    if not ref or not body:
        await msg.reply_text(HINT, parse_mode="HTML")
        return
    if len(body) > MAX_BODY_LEN:
        await msg.reply_text(TOO_LONG)
        return

    try:
        order_row = await find_order_for_stat(ref)
    except Exception as exc:
        logger.warning("msg lookup failed ref=%s: %s", ref, exc)
        await msg.reply_text(NOT_FOUND)
        return

    if not order_row:
        try:
            ext = await get_external_deal_by_merchant_ref(ref)
        except Exception as exc:
            logger.warning("msg external lookup failed ref=%s: %s", ref, exc)
            ext = None
        await msg.reply_text(NO_BUYER if ext else NOT_FOUND)
        return

    order = dict(order_row)
    buyer_id = _buyer_id(order)
    order_id = str(order.get("order_id") or "").strip()
    if buyer_id <= 0 or not order_id:
        await msg.reply_text(NO_BUYER)
        return

    dm = format_buyer_dm(order_id, body)
    try:
        sent = await context.bot.send_message(
            chat_id=buyer_id,
            text=dm,
            parse_mode="HTML",
        )
    except TelegramError as exc:
        logger.warning("msg deliver failed order=%s: %s", order_id, exc)
        await msg.reply_text(NOT_DELIVERED)
        return

    buyer_message_id = int(getattr(sent, "message_id", 0) or 0)
    if buyer_message_id <= 0:
        await msg.reply_text(NOT_DELIVERED)
        return

    alias = client_alias(buyer_id)
    ack_text = format_group_ack(alias, order_id)
    try:
        ack = await msg.reply_text(ack_text, parse_mode="HTML")
        group_message_id = int(getattr(ack, "message_id", 0) or 0) or int(msg.message_id)
    except TelegramError as exc:
        logger.warning("msg ack failed order=%s: %s", order_id, exc)
        group_message_id = int(msg.message_id)

    try:
        await insert_relay_anchor(
            order_id=order_id,
            buyer_user_id=buyer_id,
            buyer_message_id=buyer_message_id,
            group_chat_id=int(chat.id),
            group_message_id=group_message_id,
            message_thread_id=_thread_id(msg),
            sender_tg_id=sender_id or None,
        )
    except Exception as exc:
        logger.warning("msg anchor failed order=%s: %s", order_id, exc)

    logger.info(
        "msg sent order=%s alias=%s group=%s",
        order_id,
        alias,
        chat.id,
    )


def _copy_kwargs(anchor: dict) -> dict:
    kwargs = {
        "chat_id": int(anchor["group_chat_id"]),
        "reply_to_message_id": int(anchor["group_message_id"]),
    }
    thread = anchor.get("message_thread_id")
    try:
        thread_id = int(thread) if thread else None
    except (TypeError, ValueError):
        thread_id = None
    if thread_id:
        kwargs["message_thread_id"] = thread_id
    return kwargs


async def payfast_buyer_reply_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
    user = update.effective_user
    if not msg or not user or not getattr(msg, "reply_to_message", None):
        return
    reply_id = int(getattr(msg.reply_to_message, "message_id", 0) or 0)
    if reply_id <= 0:
        return
    try:
        anchor = await find_relay_anchor(int(user.id), reply_id)
    except Exception as exc:
        logger.warning("msg reply lookup failed: %s", exc)
        return
    if not anchor:
        return

    base = _copy_kwargs(anchor)
    try:
        await context.bot.send_message(
            text=format_client_label(int(anchor["buyer_user_id"])),
            **base,
        )
    except TelegramError as exc:
        logger.warning(
            "msg reply label failed order=%s: %s", anchor.get("order_id"), exc
        )
    try:
        await context.bot.copy_message(
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
            **base,
        )
    except TelegramError as exc:
        logger.warning(
            "msg reply copy failed order=%s: %s", anchor.get("order_id"), exc
        )
        try:
            await context.bot.send_message(text=COPY_FAILED, **base)
        except TelegramError:
            logger.warning("msg reply notice failed order=%s", anchor.get("order_id"))

    if reply_reaches_receipt_handler(msg):
        return
    raise ApplicationHandlerStop
