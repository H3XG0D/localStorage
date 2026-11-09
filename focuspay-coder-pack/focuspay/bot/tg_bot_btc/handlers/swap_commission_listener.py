"""Слушатель рабочего чата: комиссии со свапов + регистрация топика («swap»)."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes
from telegram.ext.filters import MessageFilter

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.swap_commission_db import insert_swap_commission_entry
from services.swap_commission_parse import parse_swap_commission_parts
from services.swap_commission_store import (
    is_swap_commission_chat,
    read_swap_commission_target,
    write_swap_commission_target,
)

logger = logging.getLogger("swap_commission_listener")


class SwapCommissionChatFilter(MessageFilter):
    def filter(self, message) -> bool:  # type: ignore[override]
        if not message or not message.chat:
            return False
        topic_id = getattr(message, "message_thread_id", None)
        return is_swap_commission_chat(message.chat.id, topic_id)


swap_commission_chat_filter = SwapCommissionChatFilter()


async def register_swap_commission_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.message:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Команда только для группы с ботом.")
        return
    if update.effective_user.id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text(
            "Только админ может привязать чат комиссий. "
            "Используйте команду /swap в нужном топике."
        )
        return

    topic_id = getattr(update.message, "message_thread_id", None)
    try:
        path = write_swap_commission_target(chat.id, topic_id)
    except OSError as e:
        logger.error("write swap commission config: %s", e)
        await update.message.reply_text(f"Ошибка записи конфига: {e}")
        return
    title = chat.title or ""
    topic_line = f"\nТопик: <code>{topic_id}</code>" if topic_id else ""
    await update.message.reply_text(
        f"✅ <b>Чат комиссий со свапов</b>\n"
        f"<code>{chat.id}</code> · {title}{topic_line}\n\n"
        f"Пишите сумму и валюту:\n"
        f"• <code>/c 5.2 USDT</code> или <code>/c 10trx + 2usdt + 0.00024btc</code>\n"
        f"• или текстом <code>5.2 USDT</code> (если в @BotFather отключён Privacy)\n"
        f"Файл: <code>{path}</code>",
        parse_mode="HTML",
    )
    logger.warning(
        "swap commission chat registered chat_id=%s topic_id=%s file=%s",
        chat.id,
        topic_id,
        path,
    )


async def swap_commission_text_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if (update.message.text or "").strip().lower() != "swap":
        return
    await register_swap_commission_chat(update, context)


async def _format_swap_line(row: dict) -> str:
    amt = float(row["crypto_amount"])
    rub = float(row["amount_rub"])
    cur = str(row["crypto"]).upper()
    if cur == "RUB":
        return f"{rub:,.2f} ₽".replace(",", " ")
    return f"{amt:g} {cur} → {rub:,.2f} ₽".replace(",", " ")


async def _record_swap_commission_from_message(msg, text: str) -> None:
    parsed_list = parse_swap_commission_parts(text)
    if not parsed_list:
        await msg.reply_text(
            "Не распознал сумму. Примеры:\n"
            "<code>/c 5.2 USDT</code>\n"
            "<code>/c 10trx + 2usdt + 0.00024btc</code>",
            parse_mode="HTML",
        )
        return

    topic_id = getattr(msg, "message_thread_id", None)
    rows: list[dict] = []
    errors: list[str] = []

    for idx, parsed in enumerate(parsed_list):
        try:
            row = await insert_swap_commission_entry(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                part_index=idx,
                topic_id=topic_id,
                telegram_user_id=msg.from_user.id if msg.from_user else None,
                raw_text=text,
                crypto=parsed.crypto,
                crypto_amount=parsed.crypto_amount,
            )
        except ValueError as e:
            errors.append(str(e))
            continue
        except Exception:
            logger.exception("swap commission insert failed part=%s", idx)
            errors.append(f"{parsed.crypto.upper()}: ошибка записи")
            continue
        if row:
            rows.append(row)

    if not rows and errors:
        await msg.reply_text("⚠️ " + "\n".join(errors))
        return
    if not rows:
        return

    lines = [await _format_swap_line(r) for r in rows]
    total_rub = sum(float(r["amount_rub"]) for r in rows)
    body = "\n".join(lines)
    if len(rows) > 1:
        body += f"\n<b>Итого: {total_rub:,.2f} ₽</b>".replace(",", " ")
    if errors:
        body += "\n⚠️ " + "\n⚠️ ".join(errors)

    prefix = "✅ Учтено"
    if len(rows) > 1:
        prefix += f" ({len(rows)} поз.)"

    try:
        await msg.reply_text(
            f"{prefix}:\n{body}",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
    except Exception as e:
        logger.warning("swap commission confirm reply failed: %s", e)


async def swap_commission_command_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
    if not msg or not msg.chat:
        return
    topic_id = getattr(msg, "message_thread_id", None)
    if not is_swap_commission_chat(msg.chat.id, topic_id):
        await msg.reply_text(
            "Сначала привяжите этот топик: команда /swap от админа."
        )
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.reply_text(
            "Формат:\n"
            "<code>/c 5.2 USDT</code>\n"
            "<code>/c 10trx + 2usdt + 0.00024btc</code>",
            parse_mode="HTML",
        )
        return

    await _record_swap_commission_from_message(msg, parts[1].strip())


async def swap_commission_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
    if not msg or not msg.chat:
        return
    topic_id = getattr(msg, "message_thread_id", None)
    if not is_swap_commission_chat(msg.chat.id, topic_id):
        return

    text = (msg.text or msg.caption or "").strip()
    if not text or text.lower() == "swap":
        return

    await _record_swap_commission_from_message(msg, text)


def swap_commission_target_hint() -> str:
    t = read_swap_commission_target()
    if not t:
        return "не настроен (отправьте «swap» в нужном топике от админа)"
    topic = t.get("topic_id")
    if topic:
        return f"chat {t['chat_id']}, topic {topic}"
    return f"chat {t['chat_id']}"
