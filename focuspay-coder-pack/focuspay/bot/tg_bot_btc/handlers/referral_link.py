"""Привязка реферала, если пользователь прислал ссылку текстом (из чата TG)."""
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes
from telegram.ext.filters import MessageFilter

from services.antispam import rate_limit_ok
from services.db import ensure_bot_user
from services.referral_links import message_referral_token
from services.user_referral_attribution import (
    apply_user_referral_from_message,
    referral_result_message,
    seal_referral_gate,
)


class ReferralLinkMessageFilter(MessageFilter):
    """Срабатывает только если в сообщении есть реферальная ссылка."""

    def filter(self, message) -> bool:  # type: ignore[override]
        return message_referral_token(message) is not None


referral_link_message_filter = ReferralLinkMessageFilter()


async def referral_link_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if not await rate_limit_ok(update):
        return

    user = update.effective_user
    await ensure_bot_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )
    result = await apply_user_referral_from_message(user.id, update.message)
    note = referral_result_message(result)
    if note:
        await update.message.reply_text(note)
    if result != "applied":
        await seal_referral_gate(user.id)
    raise ApplicationHandlerStop()
