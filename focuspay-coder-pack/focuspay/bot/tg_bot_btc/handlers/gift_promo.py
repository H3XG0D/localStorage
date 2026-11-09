from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from services.antispam import rate_limit_ok
from services.menu import main_menu_keyboard
from services.promo_redeem import PromoRedeemError, redeem_promo_code

PROMO_MENU = "🎁 Промокод"


async def _prompt_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.exchange_flow import clear_exchange_session

    clear_exchange_session(context)
    context.user_data.pop("uref_wd", None)
    context.user_data["promo_enter"] = True
    kb = ReplyKeyboardMarkup([["🚫 Отмена"]], resize_keyboard=True)
    await update.message.reply_text(
        "🎁 <b>Промокод</b>\n\n"
        "Отправьте код одним сообщением.\n"
        "Код может зачислить сумму на баланс или выдать скидку на обмен — "
        "зависит от типа промо.",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def _reply_redeemed(update: Update, result: dict) -> None:
    user = update.effective_user
    from services.user_unified_balance import get_unified_balance_stats

    kind = result.get("campaign_kind") or "fixed_rub"
    if kind == "exchange_discount":
        min_order = float(result.get("min_order_rub") or 0)
        floor = (
            f"\nДействует при обмене от <b>{min_order:,.0f} ₽</b>."
            if min_order > 0
            else ""
        )
        text = (
            f"✅ Промокод <code>{result['code']}</code> активирован!\n"
            f"Скидка на обмен: <b>{result['amount_rub']:,.0f} ₽</b>."
            f"{floor}\n\n"
            "Применится при следующей покупке. Смотрите в 🏷 Мои скидки."
        ).replace(",", " ")
    else:
        stats = await get_unified_balance_stats(user.id)
        text = (
            f"✅ Промокод <code>{result['code']}</code> активирован!\n"
            f"Зачислено <b>{result['amount_rub']:,.0f} ₽</b> на общий баланс.\n"
            f"Сейчас на счёте: <b>{stats['balance_rub']:,.0f} ₽</b> "
            f"(доступно: <b>{stats['available_rub']:,.0f} ₽</b>)."
        ).replace(",", " ")
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=await main_menu_keyboard(user.id, user.username),
    )


async def promo_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    await _prompt_promo_code(update, context)


async def gift_promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    user = update.effective_user
    args = context.args or []
    if not args:
        await _prompt_promo_code(update, context)
        return

    code = " ".join(args).strip()
    try:
        result = await redeem_promo_code(user.id, code)
    except PromoRedeemError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    context.user_data.pop("promo_enter", None)
    await _reply_redeemed(update, result)
    _track_author_promo(user.id, result)


def _track_author_promo(user_id: int, result: dict) -> None:
    if (result.get("campaign_kind") or "") != "exchange_discount":
        return
    from services.partner_tracking import schedule_partner_event

    schedule_partner_event(
        "promo",
        user_id,
        promo=result.get("code"),
        discount=result.get("amount_rub"),
    )


async def promo_code_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("promo_enter"):
        return
    if not update.message or not update.message.text:
        return
    if not await rate_limit_ok(update):
        raise ApplicationHandlerStop()

    text = update.message.text.strip()
    if text == "🚫 Отмена":
        return

    user = update.effective_user
    try:
        result = await redeem_promo_code(user.id, text)
    except PromoRedeemError as e:
        await update.message.reply_text(f"❌ {e}")
        raise ApplicationHandlerStop()

    context.user_data.pop("promo_enter", None)
    await _reply_redeemed(update, result)
    _track_author_promo(user.id, result)
    raise ApplicationHandlerStop()
