from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.menu import main_menu_keyboard
from services.antispam import rate_limit_ok
from services.partner_db import (
    bind_partner_telegram_by_token,
    format_partner_cabinet_text,
    get_partner_by_telegram,
    get_partner_stats,
)
from services.user_balance_db import format_full_balance_message, toggle_cashback_use


async def partner_bind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    user = update.effective_user
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text(
            "Использование: /partner_bind <код>\n\n"
            "Код выдаётся в партнёрском кабинете на сайте (раздел «Привязка Telegram»). "
            "Действует 15 минут. Пароль в чат вводить не нужно."
        )
        return
    ok = await bind_partner_telegram_by_token(args[0], user.id)
    if not ok:
        await update.message.reply_text(
            "Не удалось привязать. Проверьте код (возможно, истёк) или что аккаунт "
            "не привязан к другому Telegram."
        )
        return
    await update.message.reply_text(
        "✅ Партнёрский аккаунт привязан. В меню появится «Партнёрский кабинет».",
        reply_markup=await main_menu_keyboard(user.id, user.username),
    )


async def partner_cabinet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    user = update.effective_user
    row = await get_partner_by_telegram(user.id, user.username)
    if not row:
        await update.message.reply_text(
            "Партнёрский кабинет недоступен. Получите код на сайте и: /partner_bind КОД"
        )
        return
    from services import config_rates
    from services.referral_links import web_ref_link

    stats = await get_partner_stats(row["campaign_id"], row["campaign_code"], dict(row))
    ref = row["ref_token"] or row["campaign_code"]
    web_link = web_ref_link(ref, config_rates.PUBLIC_SITE_URL)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📜 История", callback_data="uref:history")],
            [InlineKeyboardButton("🌐 Открыть ссылку сайта", url=web_link)],
        ]
    )
    await update.message.reply_text(
        format_partner_cabinet_text(row, stats),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=kb,
    )


async def user_balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    user_id = update.effective_user.id
    from services.user_referral_attribution import seal_referral_gate

    await seal_referral_gate(user_id)
    from services.marketing_messages import cashback_progress_line

    text = await format_full_balance_message(user_id)
    cb_line = await cashback_progress_line(user_id)
    if cb_line:
        text = f"{text}\n\n{cb_line}"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💸 Вывести средства", callback_data="uref:withdraw")],
            [
                InlineKeyboardButton(
                    "🔄 Списать при следующем обмене",
                    callback_data="cashback:toggle",
                )
            ],
        ]
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def cashback_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()
    enabled = await toggle_cashback_use(query.from_user.id)
    text = await format_full_balance_message(query.from_user.id)
    state = "включено" if enabled else "выключено"
    body = f"{text}\n\n<i>Списание с баланса при обмене: {state}.</i>"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💸 Вывести средства", callback_data="uref:withdraw")],
            [
                InlineKeyboardButton(
                    "🔄 Списать при следующем обмене",
                    callback_data="cashback:toggle",
                )
            ],
        ]
    )
    # С фото-карточки профиля edit_text недоступен — отвечаем новым сообщением.
    if query.message and (query.message.photo or not query.message.text):
        await query.message.reply_text(body, parse_mode="HTML", reply_markup=kb)
        return
    await query.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
