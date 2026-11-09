"""Команды панели владельца в группе отчётов."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from services import config_rates
from services.owner_dashboard import (
    build_dash_text,
    build_help_text,
    build_misses_text,
    build_pulse_text,
    build_users_text,
)
from services.reports_group_guard import reply_wrong_reports_group


def _chat_id(update: Update) -> int | None:
    return update.effective_chat.id if update.effective_chat else None


def _owner_access_ok(update: Update) -> bool:
    chat_id = _chat_id(update)
    user = update.effective_user
    user_id = user.id if user else 0
    if not config_rates.is_reports_group_chat(chat_id):
        return False
    return config_rates.is_reports_user(user_id, user.username if user else None)


async def _deny(update: Update) -> None:
    if update.message:
        await update.message.reply_text(
            "⛔ Нет доступа к командам отчётов."
        )


async def _guard_group(update: Update) -> bool:
    if await reply_wrong_reports_group(update):
        return True
    return False


async def _require_owner(update: Update) -> bool:
    if await _guard_group(update):
        return False
    if not _owner_access_ok(update):
        # Как /search: в чужой группе молчим. Отказ — только в группе отчётов.
        if config_rates.is_reports_group_chat(_chat_id(update)):
            await _deny(update)
        return False
    return True


async def owner_help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_group(update):
        return
    if not _owner_access_ok(update):
        if not config_rates.is_reports_group_chat(_chat_id(update)):
            return
        if update.effective_user and update.effective_user.id in config_rates.TELEGRAM_ADMIN_IDS:
            await update.message.reply_text(build_help_text(), parse_mode="HTML")
        else:
            await _deny(update)
        return
    await update.message.reply_text(build_help_text(), parse_mode="HTML")


async def owner_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await owner_help_handler(update, context)


async def owner_dash_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update):
        return
    args = context.args or []
    arg = args[0] if args else None
    try:
        text = await build_dash_text(arg)
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        if update.message:
            await update.message.reply_text(f"⚠️ /dash ошибка: {type(e).__name__}: {e}")
        raise


async def owner_pulse_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update):
        return
    text = await build_pulse_text()
    await update.message.reply_text(text, parse_mode="HTML")


async def owner_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update):
        return
    args = context.args or []
    days = 1
    if args:
        try:
            days = int(args[0])
        except ValueError:
            days = 1
    text = await build_users_text(days)
    await update.message.reply_text(text, parse_mode="HTML")


async def owner_misses_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update):
        return
    args = context.args or []
    hours = 24
    if args:
        try:
            hours = int(args[0])
        except ValueError:
            hours = 24
    text = await build_misses_text(hours)
    await update.message.reply_text(text, parse_mode="HTML")
