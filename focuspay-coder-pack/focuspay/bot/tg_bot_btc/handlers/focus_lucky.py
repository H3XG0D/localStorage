"""FocusLucky monthly raffle — user UI."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.config_rates import PUBLIC_SITE_URL
from services.raffle_constants import (
    DEFAULT_PRIZE_PLACES,
    format_prizes_block,
    resolve_how_to_text,
)
from services.raffle_db import build_focus_lucky_message, get_campaign_for_user


def focus_lucky_keyboard(active_kind: str = "monthly") -> InlineKeyboardMarkup:
    site = (PUBLIC_SITE_URL or "https://focuspay.org").rstrip("/")
    if "gateway" in site or site.startswith("http://backend"):
        site = "https://focuspay.org"
    monthly_label = "• 🍀 Месячный" if active_kind == "monthly" else "🍀 Месячный"
    weekly_label = "• 🎟 Недельный" if active_kind == "weekly" else "🎟 Недельный"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(monthly_label, callback_data="flucky:kind:monthly"),
                InlineKeyboardButton(weekly_label, callback_data="flucky:kind:weekly"),
            ],
            [
                InlineKeyboardButton("📋 Как получить билеты", callback_data="flucky:how"),
                InlineKeyboardButton("🏆 Призы", callback_data="flucky:prizes"),
            ],
            [InlineKeyboardButton("🎬 Смотреть розыгрыш", url=f"{site}/casino/play/raffle")],
        ]
    )


def _user_kind(context: ContextTypes.DEFAULT_TYPE) -> str:
    kind = (context.user_data or {}).get("flucky_kind")
    return kind if kind in ("weekly", "monthly") else "monthly"


async def _send_focus_lucky(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    text = await build_focus_lucky_message(update.effective_user.id, kind)
    if not text:
        text = (
            "🍀 <b>FocusLucky</b>\n\n"
            "Сейчас нет активного розыгрыша. Следите за новостями!"
        )
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=focus_lucky_keyboard(kind),
    )



async def focus_lucky_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await _send_focus_lucky(update, context, _user_kind(context))


async def focus_lucky_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = query.from_user
    data = query.data

    if data.startswith("flucky:kind:"):
        kind = data.split(":")[-1]
        if kind not in ("weekly", "monthly"):
            return
        context.user_data["flucky_kind"] = kind
        text = await build_focus_lucky_message(user.id, kind)
        if not text:
            text = (
                "🍀 <b>FocusLucky</b>\n\n"
                "Сейчас нет активного розыгрыша. Следите за новостями!"
            )
        try:
            await query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=focus_lucky_keyboard(kind),
            )
        except Exception:
            await query.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=focus_lucky_keyboard(kind),
            )
        return

    if data == "flucky:how":
        campaign = await get_campaign_for_user(user.id, _user_kind(context))
        await query.message.reply_text(
            resolve_how_to_text(campaign),
            parse_mode="HTML",
        )
        return

    if data == "flucky:prizes":
        text = await build_focus_lucky_message(user.id, _user_kind(context))
        if text:
            await query.message.reply_text(text, parse_mode="HTML")
        else:
            await query.message.reply_text(
                format_prizes_block(DEFAULT_PRIZE_PLACES),
                parse_mode="HTML",
            )
