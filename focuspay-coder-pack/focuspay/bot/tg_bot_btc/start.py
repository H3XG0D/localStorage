from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import community_chat_url
from services.db import ensure_bot_user, get_bot_user
from services.menu import main_menu_keyboard
from services.promo_attribution import apply_promo_from_start_payload
from services.user_referral_attribution import (
    apply_user_referral_from_start_payload,
    apply_pending_ref_token_if_any,
    referral_result_message,
    seal_referral_gate,
    user_has_attribution,
)
from services.support_urls import support_chat_url
from services.user_unified_balance import get_unified_balance_stats
from services.concurrency import SEM_START
from services.antispam import rate_limit_ok
from services.welcome_banner import send_welcome_photo

START_CAPTION = """<b>FocusPay</b>

Надёжный криптообменник. Быстрый и безопасный обмен <b>BTC, USDT, LTC, TRX</b> в рубли и обратно.

🌐 Сайт: <a href="https://focuspay.org">focuspay.org</a>
📢 Отзывы: <a href="https://t.me/focuspayr">канал FocusPay</a>
👥 Чат: <a href="{chat_url}">focus чат</a>

💡 Выберите нужный раздел в меню ниже.

💬 Поддержка: <a href="{support_url}">чат на сайте</a> или @focus_operator"""


def _build_start_caption(saved_rub: float) -> str:
    caption = START_CAPTION.format(
        chat_url=community_chat_url(),
        support_url=support_chat_url(),
    )
    if saved_rub > 0:
        caption += (
            f"\n\n💚 Вы уже сэкономили: <b>{saved_rub:,.2f}</b> ₽ "
            "общим балансом при обменах."
        )
    return caption


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    async with SEM_START:
        user = update.effective_user
        await get_bot_user(user.id)
        await ensure_bot_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )

        from services.community_join_actions import (
            notify_channels_limit,
            try_approve_community_join,
        )

        join_result = await try_approve_community_join(context.bot, user.id)
        if join_result == "approved" and update.message:
            await update.message.reply_text(
                "✅ Заявка в focus чат одобрена — можно зайти в группу."
            )
        elif join_result == "channels_blocked" and update.message:
            await notify_channels_limit(context.bot, user.id)

        # Незавершённую заявку (выданные реквизиты / ожидание чека) нельзя
        # «потерять» через /start — возвращаем пользователя к её экрану,
        # а не в главное меню, иначе кнопка «💸 Я оплатил» пропадает.
        from handlers.exchange_flow import resend_active_order_prompt

        if await resend_active_order_prompt(update, context):
            return

        # Deep-link: uref_ (реферал), ref_/promo_ (кампании)
        args = context.args or []
        ref_result = "empty"
        if args:
            ref_result = await apply_user_referral_from_start_payload(user.id, args[0])
        if ref_result != "applied" and update.message and update.message.text:
            ref_result = await apply_user_referral_from_start_payload(
                user.id, update.message.text
            )
        if ref_result not in ("applied", "already", "self") and args:
            await apply_promo_from_start_payload(user.id, args[0])

        if ref_result not in ("applied", "already", "self"):
            pending_result = await apply_pending_ref_token_if_any(user.id)
            if pending_result == "applied":
                ref_result = "applied"

        menu = await main_menu_keyboard(user.id, user.username)
        stats = await get_unified_balance_stats(user.id)
        caption = _build_start_caption(float(stats.get("saved_rub") or 0))

        ref_note = referral_result_message(ref_result)

        chat_id = user.id
        if update.effective_chat:
            chat_id = update.effective_chat.id
        await send_welcome_photo(
            context.bot,
            chat_id,
            caption=caption,
            reply_markup=menu,
        )
        if ref_note:
            await update.message.reply_text(ref_note)

        if ref_result != "applied" and not await user_has_attribution(user.id):
            await seal_referral_gate(user.id)
