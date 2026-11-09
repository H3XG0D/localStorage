"""Команда /qrpay и callback qrpay: — вырезаны из бота обменника как есть."""

from telegram import Update
from telegram.ext import ContextTypes


async def owner_qrpay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.owner_dashboard import _require_owner
    from services.qr_pay_panel import build_panel_keyboard, build_panel_text

    if not await _require_owner(update):
        return

    text, state = await build_panel_text()
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=build_panel_keyboard(state),
        disable_web_page_preview=True,
    )


async def owner_qrpay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.owner_dashboard import _owner_access_ok
    from handlers.telegram_errors import answer_callback_safe
    from services.qr_pay_panel import (
        apply_panel_action,
        build_panel_keyboard,
        build_panel_text,
    )

    query = update.callback_query
    if not query:
        return
    if not _owner_access_ok(update):
        await answer_callback_safe(query, "⛔ Нет доступа", show_alert=True)
        return
    notice = await apply_panel_action(query.data or "")
    await answer_callback_safe(query, notice or "Обновлено")
    text, state = await build_panel_text()
    try:
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=build_panel_keyboard(state),
            disable_web_page_preview=True,
        )
    except Exception:
        # Текст не изменился — Telegram отвечает ошибкой, это не проблема.
        pass
