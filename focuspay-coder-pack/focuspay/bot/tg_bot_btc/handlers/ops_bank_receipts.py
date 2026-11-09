""" /checks <банк> [N] в группе отчётов: апрувнутые чеки отправок из этого банка. """
from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.ops_last_receipts import _send_receipt_file
from services import config_rates
from services.receipt_bank_report import (
    DEFAULT_COUNT,
    bank_help_list,
    collect_sender_receipts,
    format_check_caption,
    format_checks_summary,
    parse_checks_request,
)
from services.receipts_storage import receipts_dir
from services.reports_group_guard import reply_wrong_reports_group

logger = logging.getLogger("ops_bank_receipts")

_HINT = (
    "Использование: <code>/checks втб 10</code> — последние апрувнутые чеки "
    "отправок из этого банка (только документы, видео не шлю).\n"
    f"Без числа отдаю {DEFAULT_COUNT}. Банки: " + bank_help_list() + "."
)
_LOAD_FAILED = "Не удалось загрузить чеки."


async def ops_bank_receipts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message or update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat:
        return
    if await reply_wrong_reports_group(update):
        return
    if not config_rates.is_reports_user(
        int(getattr(user, "id", 0) or 0), getattr(user, "username", None)
    ):
        await msg.reply_text("⛔ Нет доступа к командам отчётов.")
        return

    parsed = parse_checks_request(list(getattr(context, "args", None) or []))
    if parsed is None:
        await msg.reply_text(_HINT, parse_mode="HTML")
        return
    label, patterns, count = parsed

    await msg.reply_text(
        f"Ищу отправки из <b>{html.escape(label)}</b>…",
        parse_mode="HTML",
    )
    try:
        orders, scanned, capped = await collect_sender_receipts(
            patterns, count, receipts_dir()
        )
    except Exception as e:
        logger.warning("checks load failed bank=%s: %s", label, e)
        await msg.reply_text(_LOAD_FAILED)
        return

    await msg.reply_text(
        format_checks_summary(label, count, orders, scanned=scanned, capped=capped),
        parse_mode="HTML",
    )

    bot = getattr(context, "bot", None)
    failed = 0
    if bot is None:
        failed = len(orders)
    else:
        for order in orders:
            # Видео в выборку не попадают, поэтому всё уходит документом:
            # required_receipt_type=3 на PDF иначе увёл бы файл в send_video.
            ok = await _send_receipt_file(
                bot,
                int(chat.id),
                order["_path"],
                format_check_caption(order),
                False,
            )
            if not ok:
                failed += 1
    if failed:
        await msg.reply_text(f"Не удалось отправить файлов: {failed}.")
    logger.info(
        "checks shown bank=%s count=%s orders=%s scanned=%s capped=%s failed=%s",
        label,
        count,
        len(orders),
        scanned,
        capped,
        failed,
    )
