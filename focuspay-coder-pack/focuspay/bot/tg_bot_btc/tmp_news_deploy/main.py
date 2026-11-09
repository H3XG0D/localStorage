from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ChatJoinRequestHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
import asyncio
import logging
import os
from pathlib import Path

from services.order_expirer import expire_orders_task
from services.payfast_order_reconciler import payfast_order_reconciler_task
from services.external_deal_payfast_reconciler import external_deal_payfast_reconciler_task
from services.stale_payout_monitor import stale_payout_monitor_task
from services.payout_reminder import payout_reminder_task
from services.rates_api import (
    CACHE,
    get_market_price,
    logger,
    refresh_all_rates_cache,
)
from services.db import init_db

from handlers.start import start_handler
from handlers.captcha_handler import captcha_text_handler
from handlers.referral_link import referral_link_message_filter, referral_link_text_handler
from handlers.reviews_channel import channel_review_handler
from handlers.security_chat_register import (
    security_chat_command,
    security_chat_text_123,
)
from handlers.external_deals_chat_register import register_external_deals_group
from handlers.client_review_chat_register import register_client_review_group
from handlers.operator_shift_chat_register import register_operator_shift_chat
from handlers.community_chat_register import (
    decline_community_chat,
    register_community_chat,
    sync_community_chat,
)
from handlers.community_join_request import community_join_request_handler
from handlers.news_chat_register import (
    decline_news_chat,
    news_bind_private,
    news_text_register,
    register_news_chat,
    sync_news_chat,
)
from handlers.news_join_request import news_join_request_handler
from handlers.business_chat_bridge import register_business_chat_handlers
from handlers.swap_commission_listener import (
    register_swap_commission_chat,
    swap_commission_chat_filter,
    swap_commission_command_handler,
    swap_commission_message_handler,
    swap_commission_text_register,
)
from handlers.partner_bot import (
    partner_bind_command,
    partner_cabinet_handler,
    user_balance_handler,
    cashback_toggle_callback,
)
from handlers.gift_promo import PROMO_MENU, gift_promo_command, promo_menu_handler
from handlers.my_discounts import MY_DISCOUNTS_MENU, my_discounts_handler
from handlers.user_referral import (
    REF_MENU,
    user_referral_cabinet_handler,
    user_referral_callback,
    user_referral_method_callback,
    user_referral_crypto_callback,
    user_referral_confirm_callback,
)
from handlers.profile_hub import (
    about_hub_handler,
    catch_custom_emoji,
    cmd_getemoji,
    hub_callback,
    profile_hub_handler,
)
from services.menu import (
    MENU_ABOUT,
    MENU_ACTIVE_ORDER,
    MENU_EXCHANGE,
    MENU_EXCHANGE_LEGACY,
    MENU_PARTNER,
    MENU_PROFILE,
)
from handlers.exchange_flow import (
    exchange_start,
    exchange_history,
    cancel_to_menu,
    exchange_support,
    community_chat,
    exchange_site,
    exchange_rate,
    reviews,
    exchange_choose_currency,
    exchange_operation_choice,
    exchange_amount_message,
    exchange_balance_discount_message,
    exchange_exchange_discount_message,
    exchange_payment_message,
    exchange_confirm_buy_amount_message,
    exchange_enter_requisites,
    exchange_text_router,
    refresh_rates,
    exchange_confirm_payment,
    exchange_attach_check,
    test_check_command,
    confirm_cancel_handler,
    cancel_cancel_handler,
    exchange_choose_usdt_network,
    exchange_nav_callback,
    resend_active_order_prompt,
    resend_active_order_menu_handler,
)

from services.admin_callbacks import (
    admin_callback_handler,
    admin_payout_tx_message,
    referral_withdrawal_callback_handler,
    operator_payroll_payout_callback_handler,
    admin_search_handler,
    admin_list_handler,
    admin_stats_handler,
    promo_command_handler,
    promo_callback_handler,
    promo_message_handler,
    post_command_handler,
    post_broadcast_message_handler,
    broadcast_confirm_callback,
)
from handlers.owner_dashboard import (
    owner_dash_handler,
    owner_help_handler,
    owner_pulse_handler,
    owner_start_handler,
    owner_users_handler,
)
from handlers.reports_chatid import reports_chatid_handler
from handlers.appeals_listener import (
    appeals_group_filter,
    appeals_video_request_handler,
)
from services.config_rates import (
    TELEGRAM_REPORTS_GROUP_ID,
    DATABASE_DSN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_LISTEN,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_PORT,
    TELEGRAM_WEBHOOK_SECRET,
    TELEGRAM_WEBHOOK_URL,
    ops_group_id,
    owner_dashboard_enabled,
    validate_bot_config,
)


# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # убрать спам HTTP Request: POST https://api.telegram.org/...


# ---------- STARTUP ----------
async def on_startup(app):
    from services.bot_context import set_application

    set_application(app)
    await init_db(DATABASE_DSN)
    print("✅ Database connected")

    from services.runtime_settings import refresh_settings

    await refresh_settings(force=True)

    async def _settings_refresh_loop():
        while True:
            try:
                await refresh_settings(force=True)
            except Exception:
                logging.getLogger("runtime_settings").exception("refresh failed")
            await asyncio.sleep(30)

    asyncio.create_task(_settings_refresh_loop())

    shutdown_event = asyncio.Event()
    app.bot_data["expire_shutdown"] = shutdown_event
    asyncio.create_task(expire_orders_task(app.bot, shutdown_event=shutdown_event))
    print("⏰ Order expiration background task started")

    if owner_dashboard_enabled():
        asyncio.create_task(
            stale_payout_monitor_task(
                app.bot,
                shutdown_event=shutdown_event,
                bot_data=app.bot_data,
            )
        )
        print("📡 Stale payout monitor started (owner group)")

    if ops_group_id():
        asyncio.create_task(
            payout_reminder_task(app.bot, shutdown_event=shutdown_event)
        )
        print("⏰ Payout reminder started (ops group, every 30s)")

    asyncio.create_task(
        payfast_order_reconciler_task(shutdown_event=shutdown_event)
    )
    print("🔄 Payfast order reconciler started")

    asyncio.create_task(
        external_deal_payfast_reconciler_task(shutdown_event=shutdown_event)
    )
    print("🔄 External deal Payfast reconciler started")


async def on_shutdown(app):
    ev = app.bot_data.get("expire_shutdown")
    if ev:
        ev.set()


# ---------- RATES ----------
async def update_all_rates(context):
    try:
        await refresh_all_rates_cache()
    except Exception as e:
        logger.error(f"refresh rates failed: {e}")

    for crypto in ("btc", "usdt", "trx", "ltc"):
        data = CACHE.get(crypto)
        if not data:
            logger.warning(f"[MISSING] {crypto.upper()} — нет в кеше")
            continue
        price = data["price"]
        logger.info(f"[OK] {crypto.upper()} обновлён: {price}")

    logger.info("💱 Currency rates updated")


# ---------- MAIN ----------
def main():
    validate_bot_config()
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    print("🤖 Bot started")

    # Telegram Business (@focus_operator) → веб-чат /ops/chat
    register_business_chat_handlers(app)

    # 🔁 Автообновление курсов
    app.job_queue.run_repeating(update_all_rates, interval=60, first=5)

    # Посты в канале отзывов @focuspayr → сайт
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_review_handler))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_CHANNEL_POST, channel_review_handler))

    # Appeals Payfast: PDF отклонён → запрос видео у клиента (если вебхук не пришёл)
    app.add_handler(
        MessageHandler(
            appeals_group_filter & (filters.TEXT | filters.CAPTION),
            appeals_video_request_handler,
        ),
        group=-1,
    )

    # Focus чат: автоприём заявок (только bot_users)
    app.add_handler(
        ChatJoinRequestHandler(community_join_request_handler),
        group=-1,
    )
    # Новости FocusPay: автоприём заявок (только bot_users)
    app.add_handler(
        ChatJoinRequestHandler(news_join_request_handler),
        group=-1,
    )

    _sec_group = filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP
    app.add_handler(CommandHandler("sec123", security_chat_command, filters=_sec_group))
    app.add_handler(CommandHandler("swap", register_swap_commission_chat, filters=_sec_group))
    app.add_handler(CommandHandler("shift", register_operator_shift_chat, filters=_sec_group))
    app.add_handler(CommandHandler("external", register_external_deals_group, filters=_sec_group))
    app.add_handler(
        CommandHandler("client_review", register_client_review_group, filters=_sec_group)
    )
    app.add_handler(CommandHandler("community", register_community_chat, filters=_sec_group))
    app.add_handler(CommandHandler("community_sync", sync_community_chat, filters=_sec_group))
    app.add_handler(
        CommandHandler("community_sync", sync_community_chat, filters=filters.ChatType.PRIVATE)
    )
    app.add_handler(CommandHandler("community_decline", decline_community_chat, filters=_sec_group))
    app.add_handler(
        CommandHandler("community_decline", decline_community_chat, filters=filters.ChatType.PRIVATE)
    )
    _news_chats = (
        filters.ChatType.GROUPS
        | filters.ChatType.SUPERGROUP
        | filters.ChatType.CHANNEL
    )
    app.add_handler(CommandHandler("news", register_news_chat, filters=_news_chats))
    app.add_handler(
        MessageHandler(
            _news_chats & filters.TEXT & filters.Regex(r"(?i)^/?(news|новости)(?:@\w+)?$"),
            news_text_register,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST
            & filters.TEXT
            & filters.Regex(r"(?i)^/?(news|новости)(?:@\w+)?$"),
            news_text_register,
        )
    )
    app.add_handler(
        CommandHandler("news_bind", news_bind_private, filters=filters.ChatType.PRIVATE)
    )
    app.add_handler(CommandHandler("news_sync", sync_news_chat, filters=_sec_group))
    app.add_handler(
        CommandHandler("news_sync", sync_news_chat, filters=filters.ChatType.PRIVATE)
    )
    app.add_handler(CommandHandler("news_decline", decline_news_chat, filters=_sec_group))
    app.add_handler(
        CommandHandler("news_decline", decline_news_chat, filters=filters.ChatType.PRIVATE)
    )
    app.add_handler(CommandHandler("c", swap_commission_command_handler, filters=_sec_group))
    app.add_handler(
        MessageHandler(_sec_group & filters.TEXT & filters.Regex(r"^123$"), security_chat_text_123)
    )
    app.add_handler(
        MessageHandler(
            _sec_group & filters.TEXT & filters.Regex(r"(?i)^swap$"),
            swap_commission_text_register,
        )
    )
    app.add_handler(
        MessageHandler(
            swap_commission_chat_filter & (filters.TEXT | filters.CAPTION),
            swap_commission_message_handler,
        ),
        group=-1,
    )

    # =====================================================
    # 🔐 ADMIN CALLBACKS (ОБЯЗАТЕЛЬНО ПЕРВЫМИ)
    # =====================================================
    app.add_handler(
        CallbackQueryHandler(
            admin_callback_handler,
            pattern="^(pay|cancel):"
        )
    )
    from services.receipt_review_callbacks import receipt_review_callback_handler

    app.add_handler(
        CallbackQueryHandler(
            receipt_review_callback_handler,
            pattern="^rcpt:",
        )
    )
    from services.account_review_callbacks import account_review_callback_handler
    from services.device_review_callbacks import device_review_callback_handler

    app.add_handler(
        CallbackQueryHandler(
            account_review_callback_handler,
            pattern="^areview:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            device_review_callback_handler,
            pattern="^dreview:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            referral_withdrawal_callback_handler,
            pattern="^refwd:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            operator_payroll_payout_callback_handler,
            pattern="^opay:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            broadcast_confirm_callback,
            pattern="^broadcast:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            promo_callback_handler,
            pattern="^promo:"
        )
    )
    from handlers.review_moderation import review_moderation_callback

    app.add_handler(CallbackQueryHandler(review_moderation_callback, pattern="^rev:"))

    # Команды в группах: chat_id проверяется внутри хендлеров (не в фильтре — иначе тишина при неверном .env)
    _group_cmds = filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP
    app.add_handler(CommandHandler("chatid", reports_chatid_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("search", admin_search_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("list", admin_list_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("stats", admin_stats_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("post", post_command_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("promo", promo_command_handler, filters=_group_cmds))
    from services.raffle_panel import (
        raffle_panel_callback,
        raffle_panel_command,
        raffle_panel_message_handler,
    )
    from services.raffle_admin import (
        raffle_activate_handler,
        raffle_close_handler,
        raffle_draw_handler,
        raffle_pay_handler,
        raffle_status_handler,
    )

    app.add_handler(CommandHandler("raffle", raffle_panel_command, filters=_group_cmds))
    app.add_handler(CallbackQueryHandler(raffle_panel_callback, pattern="^raffle:"))
    app.add_handler(CommandHandler("raffle_status", raffle_status_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("raffle_close", raffle_close_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("raffle_draw", raffle_draw_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("raffle_pay", raffle_pay_handler, filters=_group_cmds))
    app.add_handler(CommandHandler("raffle_activate", raffle_activate_handler, filters=_group_cmds))
    if owner_dashboard_enabled():
        app.add_handler(CommandHandler("start", owner_start_handler, filters=_group_cmds))
        app.add_handler(CommandHandler("help", owner_help_handler, filters=_group_cmds))
        app.add_handler(CommandHandler("dash", owner_dash_handler, filters=_group_cmds))
        app.add_handler(CommandHandler("pulse", owner_pulse_handler, filters=_group_cmds))
        app.add_handler(CommandHandler("users", owner_users_handler, filters=_group_cmds))
    _group_text = _group_cmds & filters.TEXT & ~filters.COMMAND
    app.add_handler(MessageHandler(_group_text, admin_payout_tx_message))
    if TELEGRAM_REPORTS_GROUP_ID:
        _reports_only = filters.Chat(chat_id=TELEGRAM_REPORTS_GROUP_ID)
        app.add_handler(MessageHandler(_reports_only, raffle_panel_message_handler))
        app.add_handler(MessageHandler(_reports_only, promo_message_handler))
        app.add_handler(MessageHandler(_reports_only, post_broadcast_message_handler))

    # Только личные чаты — в группах бот не реагирует (кроме кнопок админа в разрешённой группе)
    private = filters.ChatType.PRIVATE

    from handlers.review_fsm_guard import (
        REVIEW_FSM_PRIVATE_FILTER,
        review_fsm_priority_handler,
    )

    app.add_handler(
        MessageHandler(REVIEW_FSM_PRIVATE_FILTER, review_fsm_priority_handler),
        group=-1,
    )

    # =====================================================
    # Капча при первом /start — текстовый ответ пользователя
    # Группа -2: перехватывает текст раньше основных хендлеров.
    # captcha_text_handler сам проверяет наличие токена в user_data
    # и молча возвращается если пользователь не в режиме капчи.
    # =====================================================
    app.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, captcha_text_handler),
        group=-2,
    )

    # =====================================================
    # /start
    # =====================================================
    app.add_handler(CommandHandler("start", start_handler, filters=private))
    app.add_handler(
        MessageHandler(
            private & ~filters.COMMAND & referral_link_message_filter,
            referral_link_text_handler,
        )
    )
    app.add_handler(CommandHandler("partner_bind", partner_bind_command, filters=private))
    app.add_handler(CommandHandler("gift", gift_promo_command, filters=private))

    # =====================================================
    # Главное меню (компактное: Обмен / Профиль / О нас)
    # =====================================================
    app.add_handler(
        MessageHandler(
            private & filters.Regex(f"^({MENU_EXCHANGE}|{MENU_EXCHANGE_LEGACY})$"),
            exchange_start,
        )
    )
    app.add_handler(
        MessageHandler(
            private & filters.Regex(f"^{MENU_ACTIVE_ORDER}$"),
            resend_active_order_menu_handler,
        )
    )
    app.add_handler(
        MessageHandler(private & filters.Regex(f"^{MENU_PROFILE}$"), profile_hub_handler)
    )
    app.add_handler(
        MessageHandler(private & filters.Regex(f"^{MENU_ABOUT}$"), about_hub_handler)
    )
    app.add_handler(
        MessageHandler(
            private & filters.Regex(f"^({MENU_PARTNER}|📊 Партнёрский кабинет)$"),
            partner_cabinet_handler,
        )
    )
    app.add_handler(CallbackQueryHandler(hub_callback, pattern="^hub:"))
    app.add_handler(CommandHandler("getemoji", cmd_getemoji, filters=private))
    app.add_handler(
        MessageHandler(
            private & ~filters.COMMAND & filters.Entity("custom_emoji"),
            catch_custom_emoji,
        )
    )

    # Legacy reply-кнопки (старая клавиатура до /start)
    app.add_handler(
        MessageHandler(private & filters.Regex(f"^{REF_MENU}$"), user_referral_cabinet_handler)
    )
    app.add_handler(MessageHandler(private & filters.Regex("^💳 Мой баланс$"), user_balance_handler))
    app.add_handler(MessageHandler(private & filters.Regex(f"^{PROMO_MENU}$"), promo_menu_handler))
    app.add_handler(
        MessageHandler(private & filters.Regex(f"^{MY_DISCOUNTS_MENU}$"), my_discounts_handler)
    )
    app.add_handler(MessageHandler(private & filters.Regex("^📚 История операций$"), exchange_history))
    app.add_handler(MessageHandler(private & filters.Regex("^💰 Курсы$"), exchange_rate))
    app.add_handler(MessageHandler(private & filters.Regex("^🌐 Сайт$"), exchange_site))
    app.add_handler(MessageHandler(private & filters.Regex("^💬 Поддержка$"), exchange_support))
    app.add_handler(MessageHandler(private & filters.Regex("^👥 Чат$"), community_chat))
    app.add_handler(MessageHandler(private & filters.Regex("^📢 Отзывы$"), reviews))
    from handlers.focus_lucky import focus_lucky_callback, focus_lucky_handler
    from services.raffle_constants import FOCUS_LUCKY_MENU

    app.add_handler(
        MessageHandler(private & filters.Regex(f"^{FOCUS_LUCKY_MENU}$"), focus_lucky_handler)
    )
    app.add_handler(CallbackQueryHandler(cashback_toggle_callback, pattern="^cashback:"))
    app.add_handler(CallbackQueryHandler(user_referral_callback, pattern="^uref:(history|withdraw)$"))
    app.add_handler(CallbackQueryHandler(user_referral_method_callback, pattern="^uref:method:"))
    app.add_handler(CallbackQueryHandler(user_referral_crypto_callback, pattern="^uref:crypto:"))
    app.add_handler(
        CallbackQueryHandler(
            user_referral_confirm_callback,
            pattern="^uref:(confirm|cancel)$",
        )
    )
    app.add_handler(CallbackQueryHandler(focus_lucky_callback, pattern="^flucky:"))

    # Универсальная отмена
    app.add_handler(MessageHandler(private & filters.Regex("^🚫 Отмена$"), cancel_to_menu))

    # =====================================================
    # Inline-кнопки (клиент)
    # =====================================================
    app.add_handler(CallbackQueryHandler(refresh_rates, pattern="refresh_rates"))
    from handlers.review_bonus import (
        review_cancel_callback,
        review_cancel_command,
        review_photo_handler,
        review_skip_photo_callback,
        review_start_callback,
    )

    app.add_handler(CommandHandler("cancel", review_cancel_command, filters=private))
    app.add_handler(CallbackQueryHandler(review_start_callback, pattern="^review:start$"))
    app.add_handler(
        CallbackQueryHandler(review_skip_photo_callback, pattern="^review:skip_photo$")
    )
    app.add_handler(CallbackQueryHandler(review_cancel_callback, pattern="^review:cancel$"))
    app.add_handler(
        MessageHandler(
            private & filters.PHOTO,
            review_photo_handler,
        )
    )
    from handlers.exchange_flow import payin_plan_callback

    app.add_handler(CallbackQueryHandler(payin_plan_callback, pattern="^payin:"))
    app.add_handler(CallbackQueryHandler(exchange_nav_callback, pattern="^ex:"))

    # =====================================================
    # Поток обмена
    # =====================================================
    app.add_handler(MessageHandler(private & filters.Regex("^(BTC|USDT|TRX|LTC)$"), exchange_choose_currency))

    # =====================================================
    # Выбор сети USDT
    # =====================================================
    app.add_handler(
        MessageHandler(
            private & filters.Regex("^(TRC20|ERC20|BEP20|ARBITRUM|SOLANA)$"),
            exchange_choose_usdt_network
        )
    )

    app.add_handler(
        MessageHandler(
            private & (
                filters.Regex(r"^(🔶 )?Покупка \(RUB →")
                | filters.Regex(r"^(🔷 )?Продажа \(")
            ),
            exchange_operation_choice
        )
    )

    # ── Группа 0: exchange FSM ──────────────────────────────────
    # Важно: конкретные Regex-хендлеры должны идти ДО catch-all TEXT-хендлера,
    # иначе PTB запустит первый совпавший (TEXT) и Regex-хендлеры никогда не достигнут очереди.

    # «Я оплатил» и отмена (специфичные кнопки — первыми)
    app.add_handler(MessageHandler(private & filters.Regex("^💸 Я оплатил$"), exchange_confirm_payment))
    app.add_handler(MessageHandler(private & filters.Regex("^❗ Подтвердить отмену$"), confirm_cancel_handler))
    app.add_handler(MessageHandler(private & filters.Regex("^⬅️ Назад$"), cancel_cancel_handler))

    # Вывод баланса: не отдельный TEXT-хендлер (в группе 0 PTB вызывает только один
    # handler — широкий TEXT перехватывал «10000» и реквизиты обмена).
    # См. exchange_amount_message / exchange_text_router.

    # Скидка на обмен (BUY)
    app.add_handler(
        MessageHandler(
            private
            & filters.Regex(r"^🏷 |^Без скидки на обмен$"),
            exchange_exchange_discount_message,
        )
    )
    # Скидка балансом / без баланса (BUY)
    app.add_handler(
        MessageHandler(
            private
            & filters.Regex(
                r"^✅ Применить баланс как скидку$|^Оплатить без баланса$"
            ),
            exchange_balance_discount_message,
        )
    )
    # Карта / СБП
    app.add_handler(
        MessageHandler(
            private
            & filters.Regex(
                r"^(💳\s*)?[Кк]арта$|^(📱\s*)?СБП$|^[Cc][Aa][Rr][Dd][Rr][Uu][Bb]$|^[Ss][Bb][Pp][Rr][Uu][Bb]$"
            ),
            exchange_payment_message,
        )
    )
    # Подтверждение суммы (BUY)
    app.add_handler(
        MessageHandler(
            private & filters.Regex(r"^✅ Да, устраивает$"),
            exchange_confirm_buy_amount_message,
        )
    )
    # Сумма (кнопки и числа)
    app.add_handler(
        MessageHandler(
            private
            & filters.Regex(
                r"^\d+([.,]\d+)?$|^Указать сумму в Рублях$|^Указать сумму в (BTC|USDT|TRX|LTC)$"
            ),
            exchange_amount_message,
        )
    )
    # Реквизиты и catch-all FSM (отзыв — внутри exchange_text_router)
    app.add_handler(
        MessageHandler(
            private & filters.TEXT & ~filters.COMMAND,
            exchange_text_router,
        )
    )

    # =====================================================
    # Тест проверок чека (без заявки)
    # =====================================================
    app.add_handler(CommandHandler("test_check", test_check_command, filters=private))

    # =====================================================
    # Прикрепление чека (документ PDF или видео)
    # =====================================================
    app.add_handler(
        MessageHandler(
            private & (filters.Document.ALL | filters.VIDEO | filters.VIDEO_NOTE),
            exchange_attach_check,
        )
    )

    # =====================================================
    # START (webhook на prod — без Conflict с вторым polling)
    # =====================================================
    if TELEGRAM_WEBHOOK_URL.strip():
        secret = (TELEGRAM_WEBHOOK_SECRET or "").strip() or None
        print(f"🌐 Webhook mode: {TELEGRAM_WEBHOOK_URL.strip()}")
        app.run_webhook(
            listen=TELEGRAM_WEBHOOK_LISTEN,
            port=TELEGRAM_WEBHOOK_PORT,
            url_path=TELEGRAM_WEBHOOK_PATH,
            webhook_url=TELEGRAM_WEBHOOK_URL.strip(),
            secret_token=secret,
            drop_pending_updates=False,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        print("📡 Polling mode (set TELEGRAM_WEBHOOK_URL on prod)")
        app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
