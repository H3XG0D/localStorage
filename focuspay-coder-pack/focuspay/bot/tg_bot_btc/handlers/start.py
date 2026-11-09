import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.db import ensure_bot_user, get_bot_user
from services.menu import main_menu_keyboard, send_exchange_open_prompt
from services.promo_attribution import apply_promo_from_start_payload
from services.user_referral_attribution import (
    apply_pending_ref_token_if_any,
    log_start_ref_payload,
    referral_result_message,
    seal_referral_gate,
    stash_pending_ref_token_from_payload,
    user_has_attribution,
)
from services.user_unified_balance import get_unified_balance_stats
from services.concurrency import SEM_START
from services.antispam import rate_limit_ok
from services.cashback_tier import tier_info
from services.tg_emoji import e
from services.ux_copy import txt_start
from services.welcome_banner import send_welcome_photo

logger = logging.getLogger(__name__)


def _build_start_caption(saved_rub: float) -> str:
    max_pct = float(tier_info(0).get("percent_max") or 15)
    caption = txt_start(cashback_max_pct=max_pct)
    if saved_rub > 0:
        caption += (
            f"\n\n{e('gift')} Вы уже сэкономили: <b>{saved_rub:,.2f}</b> ₽ "
            "общим балансом при обменах."
        )
    return caption


async def _approve_pending_gated_joins(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user
) -> None:
    """Одобрить висящие заявки в gated-чаты сразу после Start (до капчи)."""
    from services.community_join_actions import (
        notify_channels_limit,
        try_approve_community_join,
    )
    from services.news_join_actions import (
        notify_news_channels_limit,
        try_approve_news_join,
    )
    from services.reviews_join_actions import (
        notify_reviews_channels_limit,
        try_approve_reviews_join,
    )

    msg = update.message

    join_result = await try_approve_community_join(context.bot, user.id)
    if join_result == "approved" and msg:
        await msg.reply_text(
            "✅ Заявка в focus чат одобрена — можно зайти в группу."
        )
    elif join_result == "channels_blocked" and msg:
        await notify_channels_limit(context.bot, user.id)

    news_result = await try_approve_news_join(context.bot, user.id)
    if news_result == "approved" and msg:
        await msg.reply_text(
            "✅ Заявка в новости FocusPay одобрена — можно зайти в группу."
        )
    elif news_result == "channels_blocked" and msg:
        await notify_news_channels_limit(context.bot, user.id)

    reviews_result = await try_approve_reviews_join(context.bot, user.id)
    if reviews_result == "approved" and msg:
        await msg.reply_text(
            "✅ Заявка в канал отзывов FocusPay одобрена — можно подписаться."
        )
    elif reviews_result == "channels_blocked" and msg:
        await notify_reviews_channels_limit(context.bot, user.id)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    async with SEM_START:
        user = update.effective_user
        bot_user_row = await get_bot_user(user.id)
        await ensure_bot_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )

        # Висящие заявки в чаты — сразу после Start, не ждать капчу.
        try:
            await _approve_pending_gated_joins(update, context, user)
        except Exception:
            logger.exception("gated join approve on start failed user=%s", user.id)

        # Казино: cauth_ закрывает вход сразу, капча обмена не блокирует.
        from handlers.casino_login import maybe_send_casino_login

        await maybe_send_casino_login(update, context)

        # Капча при первом входе: только новым пользователям, не администраторам.
        from services import config_rates as cfg
        from handlers.captcha_handler import CAPTCHA_REF_PAYLOAD_KEY, send_captcha

        is_admin = user.id in getattr(cfg, "TELEGRAM_ADMIN_IDS", [])
        already_passed = bot_user_row and bot_user_row.get("captcha_passed_at")
        if not is_admin and not already_passed and update.message:
            # Deep-link payload теряется после капчи — сохраняем до проверки.
            # Не затираем уже сохранённый ref при повторном /start (новая картинка).
            from handlers.ops_bind import extract_ops_bind_token
            from services.ops_bind import OPS_BIND_PAYLOAD_KEY
            from handlers.casino_login import extract_cauth_token

            args = context.args or []
            payload = args[0] if args else ""
            if not payload and update.message.text:
                payload = update.message.text
            if extract_ops_bind_token(payload):
                context.user_data[OPS_BIND_PAYLOAD_KEY] = payload
            elif extract_cauth_token(payload):
                pass
            elif args:
                await stash_pending_ref_token_from_payload(user.id, args[0])
                context.user_data[CAPTCHA_REF_PAYLOAD_KEY] = args[0]
            elif update.message.text:
                from services.referral_links import extract_any_ref_token

                text = update.message.text
                await stash_pending_ref_token_from_payload(user.id, text)
                if extract_any_ref_token(text):
                    context.user_data[CAPTCHA_REF_PAYLOAD_KEY] = text
            await send_captcha(update, context)
            return

        from handlers.ops_bind import maybe_handle_ops_bind

        if await maybe_handle_ops_bind(update, context):
            return

        # Незавершённую заявку (выданные реквизиты / ожидание чека) нельзя
        # «потерять» через /start — возвращаем пользователя к её экрану,
        # а не в главное меню, иначе кнопка «💸 Я оплатил» пропадает.
        from handlers.exchange_flow import resend_active_order_prompt

        if await resend_active_order_prompt(update, context):
            return

        # Единая реферальная ссылка: ref_/uref_/bare/promo_ — один резолвер.
        # 1) реферер-пользователь/партнёр (bot_users.ref_token),
        # 2) fallback — промо-кампания (promo_campaigns.ref_token / promo_<code>).
        args = context.args or []
        payload = args[0] if args else ""
        if not payload and update.message and update.message.text:
            payload = update.message.text

        from services.referral_links import extract_any_ref_token
        from services.user_referral_attribution import assign_referrer_by_token

        await log_start_ref_payload(user.id, payload)

        ref_result = "empty"
        bare_token = extract_any_ref_token(payload)
        if bare_token:
            ref_result = await assign_referrer_by_token(user.id, bare_token)

        if ref_result not in ("applied", "already", "self") and payload:
            if await apply_promo_from_start_payload(user.id, payload):
                ref_result = "applied"

        if ref_result not in ("applied", "already", "self"):
            pending_result = await apply_pending_ref_token_if_any(user.id)
            if pending_result == "applied":
                ref_result = "applied"

        # Партнёрка: ссылка автора t.me/...?start=p_CODE — только уведомляем,
        # свою атрибуцию не трогаем.
        if payload and str(payload).startswith("p_"):
            from services.author_promo_arrival import apply_author_promo_arrival
            from services.partner_tracking import schedule_partner_event

            schedule_partner_event("start", user.id, start_param=str(payload))
            await apply_author_promo_arrival(user.id, str(payload))

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
            await context.bot.send_message(chat_id=chat_id, text=ref_note)

        if ref_result != "applied" and not await user_has_attribution(user.id):
            await seal_referral_gate(user.id)

        # Последним: иначе список чатов не покажет «ОТКРЫТЬ» на мини-приложение обмена.
        await send_exchange_open_prompt(context.bot, chat_id)
