import logging
from services.payment_snapshot import order_payment_snapshot
import html
import re
import importlib
import time
import os
import hmac
import hashlib
import shutil
import aiohttp
import uuid
import asyncpg
from pathlib import Path
import telegram
import asyncio
from datetime import datetime, timezone
from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from telegram.ext import ApplicationHandlerStop, ContextTypes
from decimal import Decimal, ROUND_DOWN, ROUND_CEILING, getcontext, ROUND_HALF_UP
from services import config_rates
from services.debug_agent import agent_log
from services.rates_api import (
    CACHE,
    USER_NEED_RATES_UNAVAILABLE,
    USER_RATES_UNAVAILABLE,
    RatesUnavailableError,
    ensure_rates_cache,
    get_cached_buy_market,
    get_cached_rate,
    get_market_price,
    get_need_price,
    get_need_rates_cached,
    has_rate_changed,
)
from services.buy_rub_quote import quote_buy_rub_base
from services.db import (
    update_order_status,
    update_order_to_awaiting_check,
    create_order_with_promo,
    get_order,
    get_active_order_by_user,
    get_completed_orders_count,
    get_completed_orders_by_user,
    get_order_awaiting_check_by_user,
    count_orders_by_user_in_last_minutes,
)

from services.promo_bonus import promo_bonus_note
from services.storage import user_sessions
from services.concurrency import SEM_CREATE_ORDER, SEM_ATTACH_CHECK
from services.antispam import rate_limit_ok
from handlers.telegram_utils import url_button
from services.support_urls import support_chat_url, telegram_href, telegram_web_url
from services.user_errors import user_facing_message

logger = logging.getLogger("exchange_flow")
exchange_fsm_logger = logging.getLogger("exchange_fsm")
merchant_logger = logging.getLogger("merchant_api")
receipt_logger = logging.getLogger("receipt_attach")


def _payfast_requisites_remaining_sec(order: dict) -> int | None:
    """Остаток recovery-окна, либо None вне него или для старой заявки."""
    snapshot = order_payment_snapshot(order)
    if int(order.get("required_receipt_type") or 0) == 3:
        return None
    raw_merchant_end = snapshot.get("merchant_expires_at")
    requisites_end = order.get("expires_at")
    if not raw_merchant_end or not requisites_end:
        return None
    try:
        merchant_end = datetime.fromisoformat(str(raw_merchant_end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if merchant_end.tzinfo is None:
        merchant_end = merchant_end.replace(tzinfo=timezone.utc)
    if requisites_end.tzinfo is None:
        requisites_end = requisites_end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    merchant_end = merchant_end.astimezone(timezone.utc)
    if requisites_end.astimezone(timezone.utc) <= now < merchant_end:
        return max(0, int((merchant_end - now).total_seconds()))
    return None


def _payfast_requisites_closed_for_order(order: dict) -> bool:
    """После внутреннего срока новой PayFast BUY клиентские действия закрыты."""
    snapshot = order_payment_snapshot(order)
    if int(order.get("required_receipt_type") or 0) == 3:
        return False
    if not snapshot.get("merchant_expires_at"):
        return False
    requisites_end = order.get("expires_at")
    if not requisites_end:
        return False
    if requisites_end.tzinfo is None:
        requisites_end = requisites_end.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= requisites_end.astimezone(timezone.utc)


async def _reply_payfast_requisites_closed(update, order: dict) -> None:
    from services.buyer_access_guards import format_requisites_closed_message

    remaining_sec = _payfast_requisites_remaining_sec(order)
    text = (
        format_requisites_closed_message(remaining_sec)
        if remaining_sec is not None
        else "⏰ <b>Время на оплату истекло.</b>\n\nНапишите оператору: @focus_operator"
    )
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=await menu_for(update),
    )


def _payfast_cancellation_is_locked_for_order(order: dict) -> bool:
    return (
        int(order.get("required_receipt_type") or 0) == 3
        or _payfast_requisites_remaining_sec(order) is not None
    )


async def _reply_payfast_cancellation_locked(update, order: dict) -> None:
    if int(order.get("required_receipt_type") or 0) == 3:
        text = (
            "⚠️ <b>Заявку нельзя отменить.</b>\n\n"
            "По ней запрошено видео подтверждения. Прикрепите видео или напишите оператору: @focus_operator"
        )
    else:
        text = (
            "⚠️ <b>Заявку нельзя отменить.</b>\n\n"
            "Реквизиты уже закрыты. Если вы сделали перевод, напишите оператору: @focus_operator"
        )
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=await menu_for(update),
    )


RUB_AMOUNT_RE = re.compile(r"^\d+([.,]\d{1,2})?$")
FSM_TTL = int(os.environ.get("EXCHANGE_FSM_TTL_SEC", "1800"))
MAX_RATE_DEVIATION = Decimal("0.005")  # 0.5%
# высокая точность для крипты
getcontext().prec = 28

CRYPTO_DECIMALS = {
    "btc": 8,
    "usdt": 2,
    "trx": 2,
    "ltc": 8,
}

def fmt_crypto(value, crypto: str) -> str:
    """
    Форматирует крипту для отображения:
    - BTC → до 8 знаков
    - USDT / TRX → 2 знака; LTC → 5 знаков
    """
    crypto = crypto.lower()
    decimals = CRYPTO_DECIMALS.get(crypto, 8)

    q = Decimal("1") / (Decimal(10) ** decimals)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_DOWN)

    return format(d, "f")


def check_fsm_ttl(context) -> bool:
    now = time.time()
    started = context.user_data.get("fsm_started_at")

    if not started:
        context.user_data["fsm_started_at"] = now
        return True

    if now - started > FSM_TTL:
        context.user_data.clear()
        return False

    return True


APPLY_BALANCE_DISCOUNT = "✅ Применить баланс как скидку"
SKIP_BALANCE_DISCOUNT = "Оплатить без баланса"
SKIP_EXCHANGE_DISCOUNT = "Без скидки на обмен"
CONFIRM_BUY_AMOUNT = "✅ Да, устраивает"

EXCHANGE_FSM_STEPS = frozenset({
    "choose_currency",
    "choose_usdt_network",
    "choose_operation",
    "enter_amount",
    "choose_exchange_discount",
    "choose_balance_discount",
    "choose_payment_method",
    "confirm_buy_amount",
    "awaiting_requisites",
    "awaiting_payin_choice",
    "awaiting_payin_round",
    "awaiting_payment_confirmation",
    "confirm_cancel",
    "confirm_cancel_order",
})

STEPS_AFTER_AMOUNT = frozenset({
    "choose_exchange_discount",
    "choose_balance_discount",
    "choose_payment_method",
    "confirm_buy_amount",
    "awaiting_requisites",
    "awaiting_payin_choice",
    "awaiting_payin_round",
    "awaiting_payment_confirmation",
})

STEPS_BEFORE_AMOUNT = frozenset({
    "choose_currency",
    "choose_usdt_network",
    "choose_operation",
})

_REPEAT_INPUT_HINTS: dict[tuple[str, str], str] = {
    ("amount", "choose_exchange_discount"): (
        "Сумма уже указана. Выберите скидку на обмен или «Без скидки на обмен»."
    ),
    ("amount", "choose_balance_discount"): (
        "Сумма уже указана. Нажмите «✅ Применить баланс как скидку» "
        "или «Оплатить без баланса»."
    ),
    ("amount", "choose_payment_method"): (
        "Сумма уже указана. Выберите способ оплаты: <b>Карта</b> или <b>СБП</b>."
    ),
    ("amount", "confirm_buy_amount"): (
        "Сумма уже указана. Подтвердите условия: нажмите «✅ Да, устраивает»."
    ),
    ("amount", "awaiting_requisites"): (
        "Сумма уже указана. Введите адрес кошелька для получения крипты."
    ),
    ("amount", "awaiting_payin_choice"): (
        "Сумма уже указана. Выберите вариант из сообщения выше или нажмите «🚫 Отмена»."
    ),
    ("amount", "awaiting_payin_round"): (
        "Сумма уже указана. Сейчас есть только реквизит на сумму выше — подтвердите или отмените."
    ),
    ("amount", "awaiting_payment_confirmation"): (
        "Заявка уже создана. Откройте реквизиты кнопкой и нажмите «💸 Я оплатил»."
    ),
    ("payment", "confirm_buy_amount"): (
        "Способ оплаты уже выбран. Подтвердите сумму: нажмите «✅ Да, устраивает»."
    ),
    ("payment", "awaiting_requisites"): (
        "Способ оплаты уже выбран. Введите адрес кошелька для получения крипты."
    ),
    ("payment", "awaiting_payin_choice"): (
        "Способ оплаты уже выбран. Дождитесь реквизитов или выберите вариант выше."
    ),
    ("payment", "awaiting_payin_round"): (
        "Способ оплаты уже выбран. Подтвердите сумму реквизита или отмените."
    ),
    ("payment", "awaiting_payment_confirmation"): (
        "Заявка уже создана. Откройте реквизиты кнопкой и нажмите «💸 Я оплатил»."
    ),
    ("balance", "choose_payment_method"): (
        "Выбор баланса уже сделан. Нажмите <b>Карта</b> или <b>СБП</b>."
    ),
    ("discount", "choose_balance_discount"): (
        "Скидка уже выбрана. Примените баланс или оплатите без него."
    ),
    ("discount", "choose_payment_method"): (
        "Скидка уже выбрана. Нажмите <b>Карта</b> или <b>СБП</b>."
    ),
    ("balance", "confirm_buy_amount"): (
        "Выбор баланса уже сделан. Подтвердите сумму: нажмите «✅ Да, устраивает»."
    ),
    ("balance", "awaiting_requisites"): (
        "Выбор баланса уже сделан. Введите адрес кошелька."
    ),
    ("discount", "confirm_buy_amount"): (
        "Скидка уже выбрана. Подтвердите сумму: нажмите «✅ Да, устраивает»."
    ),
}


async def exchange_repeat_input_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    kind: str,
) -> bool:
    """
    Пользователь повторно нажал сумму/оплату на более позднем шаге FSM.
    Возвращает True, если ответ отправлен (не считать сессию «устаревшей»).
    """
    step = context.user_data.get("step")
    hint = _REPEAT_INPUT_HINTS.get((kind, step or ""))
    if hint:
        await update.message.reply_text(hint, parse_mode="HTML")
        return True
    if kind == "amount" and step in STEPS_BEFORE_AMOUNT:
        await update.message.reply_text(
            "Сначала выберите валюту и операцию обмена (кнопки выше в чате).",
        )
        return True
    if kind == "payment" and step in STEPS_BEFORE_AMOUNT | {
        "enter_amount",
        "choose_exchange_discount",
        "choose_balance_discount",
    }:
        await update.message.reply_text(
            "Сначала укажите сумму обмена, затем выберите способ оплаты.",
        )
        return True
    return False


def exchange_input_is_stale(step: str | None) -> bool:
    """Сессия действительно потеряна — нет активного шага обмена."""
    return not step or step not in EXCHANGE_FSM_STEPS

PAYMENT_METHOD_TEXTS = frozenset({
    "💳 Карта",
    "📱 СБП",
    "Карта",
    "СБП",
    "карта",
    "сбп",
})


def _collapse_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_payment_method(text: str) -> str | None:
    """card | sbp | None. Учитывает эмодзи, лишние пробелы и разный регистр."""
    raw = text or ""
    t = _collapse_text(raw).lower().replace("ё", "е")
    if not t:
        return None
    if t in ("сбп", "sbprub") or "сбп" in t or "📱" in raw:
        return "sbp"
    if t in ("карта", "cardrub") or "карт" in t or "💳" in raw:
        return "card"
    return None


async def exchange_stale_session_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.message.reply_text(
        "⏱ Сессия обмена устарела.\n"
        "Нажмите «Совершить обмен» и пройдите шаги заново.",
        reply_markup=await menu_for(update),
    )
    context.user_data.clear()


AMOUNT_FLOW_RE = re.compile(
    r"^\d+([.,]\d+)?$|^Указать сумму в Рублях$|^Указать сумму в (BTC|USDT|TRX|LTC)$"
)


def is_amount_flow_text(text: str) -> bool:
    return bool(AMOUNT_FLOW_RE.match(text.strip()))


def is_payment_flow_text(text: str) -> bool:
    return normalize_payment_method(text) is not None


async def exchange_payment_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Прямой хендлер «Карта / СБП» (block=True), не зависит от роутера."""
    if context.user_data.get("uref_wd"):
        return
    if not update.message or not update.message.text:
        return
    if not normalize_payment_method(update.message.text):
        return
    if not await rate_limit_ok(update):
        return
    exchange_fsm_logger.info(
        "payment_handler user=%s step=%s text=%r",
        update.effective_user.id if update.effective_user else 0,
        context.user_data.get("step"),
        _collapse_text(update.message.text)[:60],
    )
    await exchange_choose_payment_method(update, context)


async def exchange_amount_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Прямой хендлер суммы (block=True)."""
    uref = context.user_data.get("uref_wd")
    step = context.user_data.get("step")
    text_in = (update.message.text or "")[:40] if update.message else ""
    if uref and uref.get("step") == "amount":
        from handlers.user_referral import user_referral_withdraw_message

        agent_log(
            "exchange_flow.py:amount_msg",
            "delegate to uref_wd amount",
            {"text": text_in},
            hypothesis_id="F",
            run_id="post-fix",
        )
        await user_referral_withdraw_message(update, context)
        raise ApplicationHandlerStop()
    if not update.message or not update.message.text:
        return
    if not is_amount_flow_text(update.message.text):
        return
    agent_log(
        "exchange_flow.py:amount_msg",
        "amount handler proceed",
        {"exchange_step": step, "amount_currency": context.user_data.get("amount_currency"), "text": text_in},
        hypothesis_id="B",
    )
    if not await rate_limit_ok(update):
        return
    exchange_fsm_logger.info(
        "amount_handler user=%s step=%s text=%r",
        update.effective_user.id if update.effective_user else 0,
        context.user_data.get("step"),
        _collapse_text(update.message.text)[:60],
    )
    await exchange_enter_amount(update, context)


async def exchange_balance_discount_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Прямой хендлер выбора скидки балансом (block=True)."""
    if context.user_data.get("uref_wd"):
        return
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text not in (APPLY_BALANCE_DISCOUNT, SKIP_BALANCE_DISCOUNT):
        return
    if not await rate_limit_ok(update):
        return
    await exchange_choose_balance_discount(update, context)


EXCHANGE_SESSION_KEYS = (
    "step",
    "crypto",
    "direction",
    "fiat_amount",
    "crypto_amount",
    "effective_rate",
    "network",
    "amount_currency",
    "sub_token",
    "buy_wallet",
    "payin_plan",
    "last_rate",
    "fsm_started_at",
    "active_order_id",
    "test_check",
    "exchange_discount_id",
    "exchange_discount_applied",
    "exchange_discount_options",
    "buy_send_fee_rub",
    "buy_btc_fee_rate_sat_vb",
)


def _buy_crypto_sym(context) -> str:
    crypto = context.user_data.get("crypto") or ""
    network = context.user_data.get("network")
    if crypto == "usdt" and network:
        return f"USDT_{network.upper()}"
    return crypto.upper() if crypto else ""


async def _build_buy_amount_preview(context, user_id: int) -> str:
    """Текст превью суммы перед запросом кошелька (BUY)."""
    from services.tg_emoji import e
    from services.user_cashback_db import should_use_cashback
    from services.user_unified_balance import get_unified_balance_stats
    from services.ux_copy import txt_buy_amount_preview

    fiat_amount = float(context.user_data.get("fiat_amount") or 0)
    crypto_amount = context.user_data.get("crypto_amount")
    crypto = context.user_data.get("crypto") or ""
    crypto_upper = _buy_crypto_sym(context)
    disc_applied = float(context.user_data.get("exchange_discount_applied") or 0)
    fiat_after_disc = max(1.0, fiat_amount - disc_applied)

    extra: list[str] = []
    sub = context.user_data.get("sub_token") or ""
    pay_label = "Карта" if sub == "CARDRUB" else "СБП" if sub == "SBPRUB" else "—"

    if disc_applied > 0:
        extra.append(
            f"{e('discount')} Скидка на обмен: <b>{disc_applied:,.2f}</b> ₽".replace(",", " ")
        )

    fiat_pay = fiat_after_disc
    if await should_use_cashback(user_id):
        stats = await get_unified_balance_stats(user_id)
        available = float(stats.get("available_rub") or 0)
        est_cb = min(available, max(0.0, fiat_after_disc - 1.0))
        if est_cb > 0:
            extra.append(
                f"{e('discount')} Скидка балансом: ~<b>{est_cb:,.2f}</b> ₽".replace(",", " ")
            )
            fiat_pay = max(1.0, fiat_after_disc - est_cb)

    send_fee = float(context.user_data.get("buy_send_fee_rub") or 0)
    # BTC: надбавка за загрузку сети входит в сумму к оплате и отдельной строкой
    # не раскрывается, иначе здесь сработал бы текст про отправку USDT.
    if send_fee > 0 and not context.user_data.get("buy_btc_fee_rate_sat_vb"):
        from services.crypto_network_fee import format_usdt_buy_send_fee_html

        extra.append(format_usdt_buy_send_fee_html(fee_rub=send_fee))

    receive = None
    if crypto_amount is not None:
        receive = (
            f"{e('obmen')} Вы получите: ~<b>{fmt_crypto(crypto_amount, crypto)} {crypto_upper}</b>"
        )
    return txt_buy_amount_preview(
        pay_label=pay_label,
        lines_extra=extra,
        fiat_pay=fiat_pay,
        receive_line=receive,
    )


async def _prompt_buy_amount_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    context.user_data["step"] = "confirm_buy_amount"
    user_id = update.effective_user.id if update.effective_user else 0
    text = await _build_buy_amount_preview(context, user_id)
    keyboard = ReplyKeyboardMarkup(
        [[CONFIRM_BUY_AMOUNT], ["🚫 Отмена"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _ask_buy_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from services.ux_copy import txt_ask_wallet

    context.user_data["step"] = "awaiting_requisites"
    crypto_upper = _buy_crypto_sym(context)
    keyboard_cancel = ReplyKeyboardMarkup([["🚫 Отмена"]], resize_keyboard=True)
    await update.message.reply_text(
        txt_ask_wallet(crypto_upper=crypto_upper),
        parse_mode="HTML",
        reply_markup=keyboard_cancel,
    )


async def _proceed_buy_balance_or_payment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    from services.user_unified_balance import get_unified_balance_stats

    user_id = update.effective_user.id
    fiat_amount = context.user_data.get("fiat_amount")
    disc_applied = float(context.user_data.get("exchange_discount_applied") or 0)
    fiat_after_disc = max(1.0, float(fiat_amount) - disc_applied)

    stats = await get_unified_balance_stats(user_id)
    available = float(stats.get("available_rub") or 0)
    if available > 0:
        est_discount = min(available, max(0.0, fiat_after_disc - 1.0))
        context.user_data["step"] = "choose_balance_discount"
        keyboard_balance = ReplyKeyboardMarkup(
            [[APPLY_BALANCE_DISCOUNT], [SKIP_BALANCE_DISCOUNT], ["🚫 Отмена"]],
            resize_keyboard=True,
        )
        disc_note = ""
        if disc_applied > 0:
            disc_note = (
                f"\n\n🏷 Скидка на обмен: <b>{disc_applied:,.2f}</b> ₽ "
                f"(к оплате ~<b>{fiat_after_disc:,.2f}</b> ₽ до баланса)."
                .replace(",", " ")
            )
        from services.ux_copy import txt_balance_discount_prompt

        await update.message.reply_text(
            txt_balance_discount_prompt(
                available=available,
                est_discount=est_discount,
                disc_note=disc_note,
            ),
            parse_mode="HTML",
            reply_markup=keyboard_balance,
        )
        return

    context.user_data["step"] = "choose_payment_method"
    keyboard_payment = ReplyKeyboardMarkup(
        [["Карта", "СБП"], ["🚫 Отмена"]],
        resize_keyboard=True,
    )
    pay_hint = ""
    if disc_applied > 0:
        pay_hint = (
            f"\n\n🏷 С учётом скидки к оплате ~<b>{fiat_after_disc:,.2f}</b> ₽."
            .replace(",", " ")
        )
    from services.ux_copy import txt_payment_method_prompt

    await update.message.reply_text(
        txt_payment_method_prompt(pay_hint=pay_hint),
        parse_mode="HTML",
        reply_markup=keyboard_payment,
    )


async def _proceed_buy_after_amount(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    from services.exchange_discount_db import (
        get_active_discounts,
        preview_discount_application,
    )

    user_id = update.effective_user.id
    fiat_amount = context.user_data.get("fiat_amount")
    crypto_amount = context.user_data.get("crypto_amount")
    effective_rate = context.user_data.get("effective_rate")
    crypto_sym = _buy_crypto_sym(context)

    discounts = await get_active_discounts(
        user_id, fiat_amount=float(fiat_amount) if fiat_amount is not None else None
    )
    context.user_data.pop("exchange_discount_options", None)
    if not discounts:
        context.user_data.pop("exchange_discount_id", None)
        context.user_data.pop("exchange_discount_applied", None)
        await _proceed_buy_balance_or_payment(update, context)
        return

    # Всегда спрашиваем: применить скидку сейчас или позже (даже если одна).
    options: dict[str, int] = {}
    rows: list[list[str]] = []
    for d in discounts:
        _, _, preview_applied = await preview_discount_application(
            d["id"],
            user_id,
            float(fiat_amount),
            float(crypto_amount),
            float(effective_rate),
            crypto_sym,
        )
        new_price = max(0.0, float(fiat_amount) - float(preview_applied))
        label = (
            f"🏷 Применить {d['amount_rub']:,.0f} ₽ · к оплате {new_price:,.0f} ₽"
            .replace(",", " ")
        )
        options[label] = d["id"]
        rows.append([label])
    rows.append([SKIP_EXCHANGE_DISCOUNT])
    rows.append(["🚫 Отмена"])
    context.user_data["exchange_discount_options"] = options
    context.user_data["step"] = "choose_exchange_discount"
    from services.ux_copy import txt_exchange_discount_prompt

    if len(discounts) == 1:
        prompt = txt_exchange_discount_prompt(
            amount_rub=float(discounts[0]["amount_rub"]), multi=False
        )
    else:
        prompt = txt_exchange_discount_prompt(amount_rub=None, multi=True)
    await update.message.reply_text(
        prompt,
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
    )


def clear_exchange_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сброс FSM обмена (не трогает uref_wd — вывод баланса)."""
    for key in EXCHANGE_SESSION_KEYS:
        context.user_data.pop(key, None)


async def exchange_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Реквизиты и прочие шаги обмена по TEXT."""
    if context.user_data.get("awaiting_review"):
        from handlers.review_bonus import review_message_handler

        await review_message_handler(update, context)
        return
    uref = context.user_data.get("uref_wd")
    if uref:
        from handlers.user_referral import user_referral_withdraw_message

        agent_log(
            "exchange_flow.py:text_router",
            "delegate to uref_wd",
            {"uref_step": uref.get("step")},
            hypothesis_id="F",
            run_id="post-fix",
        )
        await user_referral_withdraw_message(update, context)
        return
    if context.user_data.get("promo_enter"):
        from handlers.gift_promo import promo_code_message

        await promo_code_message(update, context)
        return
    if not await rate_limit_ok(update):
        return
    if not update.message or not update.message.text:
        return

    text = _collapse_text(update.message.text)
    step = context.user_data.get("step")
    user_id = update.effective_user.id if update.effective_user else 0

    if step in EXCHANGE_FSM_STEPS or is_payment_flow_text(text) or is_amount_flow_text(text):
        exchange_fsm_logger.info("FSM router user=%s step=%s text=%r", user_id, step, text[:60])

    try:
        if step == "enter_amount":
            exchange_fsm_logger.info("FSM enter_amount user=%s text=%r", user_id, text[:60])
            await exchange_enter_amount(update, context)
            raise ApplicationHandlerStop()
        if step == "awaiting_requisites":
            exchange_fsm_logger.info("FSM requisites user=%s", user_id)
            await exchange_enter_requisites(update, context)
            raise ApplicationHandlerStop()

        if is_payment_flow_text(text) or is_amount_flow_text(text):
            kind = "payment" if is_payment_flow_text(text) else "amount"
            if await exchange_repeat_input_reply(update, context, kind=kind):
                raise ApplicationHandlerStop()
            if exchange_input_is_stale(step):
                exchange_fsm_logger.warning(
                    "FSM stale user=%s step=%s text=%r", user_id, step, text[:60]
                )
                await exchange_stale_session_reply(update, context)
            raise ApplicationHandlerStop()
    except ApplicationHandlerStop:
        raise
    except Exception:
        exchange_fsm_logger.exception("FSM router error user=%s step=%s", user_id, step)
        try:
            await update.message.reply_text(
                "❌ Не получилось завершить шаг. Нажмите «Совершить обмен». "
                "Если заявка уже создана — бот предложит отменить её.",
                reply_markup=await menu_for(update),
            )
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        context.user_data.clear()
        raise ApplicationHandlerStop() from None


def generate_local_order_id() -> str:
    return str(uuid.uuid4().int)[0:8]


def _display_order_id(order_id: str, payfast_id: str | None = None) -> str:
    pf = str(payfast_id or "").strip()
    return pf or order_id


async def _render_buy_order_message(
    update,
    *,
    order_id: str,
    fiat_amount: int,
    payout_crypto: float,
    crypto: str,
    crypto_upper: str,
    order_result: dict,
    bill: dict,
    link: str,
    part_index: int = 1,
    parts_count: int = 1,
    payment_note: str = "",
    payfast_id: str = "",
) -> None:
    from services.buy_payment_prompt import send_buy_payment_prompt
    from services.db import get_order

    order = await get_order(order_id) or {
        "order_id": order_id,
        "fiat_amount": fiat_amount,
        "crypto": crypto,
        "crypto_amount": payout_crypto,
        "payment_snapshot": {"bill": bill or {}, "pay_link": link or ""},
        "merchant_order_id": payfast_id or order_id,
    }
    extra: list[str] = []
    if parts_count > 1:
        extra.append(f"📌 Платёж <b>{part_index}</b> из <b>{parts_count}</b>")
    if payment_note:
        extra.append(payment_note)
    cb_applied = float(order_result.get("cashback_applied") or 0)
    if cb_applied > 0:
        extra.append(f"🏷 Скидка балансом: <b>{cb_applied:,.2f}</b> ₽")
    if order_result.get("promo_applied"):
        note = promo_bonus_note(
            bonus_percent=order_result.get("promo_bonus_percent"),
            bonus_fixed_rub=order_result.get("promo_bonus_fixed_rub"),
        )
        if note:
            extra.append(note)
    from services.crypto_network_fee import (
        buy_client_send_fee_rub,
        format_usdt_buy_send_fee_html,
    )

    if (crypto_upper or crypto or "").split("_")[0].lower() == "usdt":
        usdt_market = get_cached_buy_market("usdt")
        send_fee = buy_client_send_fee_rub(
            crypto_upper or crypto, usdt_rub=float(usdt_market or 0)
        )
        extra.append(format_usdt_buy_send_fee_html(fee_rub=send_fee or None))

    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return
    await send_buy_payment_prompt(
        msg,
        dict(order),
        title="Заявка создана!",
        extra_lines=extra or None,
    )


def _payin_plan_keyboard(plan) -> InlineKeyboardMarkup:
    rows = []
    if plan.mode == "operator":
        row = []
        support_btn = url_button("💬 Написать оператору", support_chat_url())
        if support_btn:
            row.append(support_btn)
        row.append(InlineKeyboardButton("🛎 Заявка оператору", callback_data="payin:go:operator"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🚫 Отмена", callback_data="payin:cancel")])
    return InlineKeyboardMarkup(rows)


def sell_created_keyboard() -> InlineKeyboardMarkup | None:
    support_btn = url_button("💬 Написать оператору", support_chat_url())
    if not support_btn:
        return None
    return InlineKeyboardMarkup([[support_btn]])


def _tg_msg(update: Update):
    return update.message or (
        update.callback_query.message if update.callback_query else None
    )


def _payin_round_keyboard(pay_rub, credit_rub, *, offer_mode: str = "happy") -> InlineKeyboardMarkup:
    if offer_mode == "happy":
        label = f"Счастливая сделка: {int(pay_rub)} ₽ (−{int(credit_rub)} ₽)"
    else:
        label = f"Заплатить {int(pay_rub)} ₽, +{int(credit_rub)} ₽ на баланс"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data="payin:round:yes")],
            [InlineKeyboardButton("🚫 Отмена", callback_data="payin:cancel")],
        ]
    )


async def _preview_payin_fit_for_user(user_id: int, amount, sub_token: str):
    from services.db import get_pool
    from services.payin_requisite_rail import preview_payin_fit

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await preview_payin_fit(
            conn,
            amount_rub=amount,
            sub_token=sub_token,
            user_id=int(user_id),
        )


async def _offer_payin_round_if_close(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    fiat_amount: int,
    sub_token: str,
) -> bool:
    """Близкая карта — silent авто или happy-оффер. PayFast при отказе не предлагаем."""
    try:
        fit = await _preview_payin_fit_for_user(user_id, fiat_amount, sub_token)
    except Exception:
        exchange_fsm_logger.exception("payin round preview failed user=%s", user_id)
        return False
    if not fit.offer:
        return False
    msg = _tg_msg(update)
    if not msg:
        return False
    pay_rub = int(fit.pay_rub)
    credit_rub = int(fit.credit_rub)
    offer_mode = str(getattr(fit, "offer_mode", None) or "happy")

    if offer_mode == "silent":
        crypto = context.user_data.get("crypto") or "btc"
        crypto_upper = str(crypto).upper()
        await msg.reply_text(
            f"К оплате {pay_rub} ₽. Разница {credit_rub} ₽ вернётся на баланс после оплаты."
        )
        created = await _create_payin_rail_and_show(
            update,
            context,
            user_id=user_id,
            crypto=crypto,
            crypto_upper=crypto_upper,
            crypto_amount=context.user_data.get("crypto_amount"),
            fiat_amount=fiat_amount,
            effective_rate=context.user_data.get("effective_rate")
            or context.user_data.get("rate"),
            wallet=context.user_data.get("buy_wallet") or "",
            sub_token=sub_token,
            accept_round_up=True,
        )
        return bool(created)

    context.user_data["step"] = "awaiting_payin_round"
    await msg.reply_text(
        f"Счастливая сделка: к оплате {pay_rub} ₽ (−{credit_rub} ₽).\n"
        f"Разница зачислим на баланс после оплаты.",
        reply_markup=_payin_round_keyboard(pay_rub, credit_rub, offer_mode="happy"),
    )
    return True


async def _create_payin_rail_and_show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    crypto,
    crypto_upper: str,
    crypto_amount,
    fiat_amount: int,
    effective_rate,
    wallet: str,
    sub_token: str,
    accept_round_up: bool = False,
) -> bool | None:
    """True — заявка на карте; False — слота нет; None — конфликт активной заявки."""
    from services.buy_order_service import create_payin_rail_buy_order

    msg = _tg_msg(update)
    try:
        rail = await create_payin_rail_buy_order(
            generate_order_id_fn=generate_local_order_id,
            user_id=user_id,
            crypto=crypto_upper,
            crypto_amount=float(crypto_amount) if crypto_amount is not None else 0.0,
            fiat_amount=int(fiat_amount),
            rate=float(effective_rate),
            wallet=wallet,
            sub_token=sub_token,
            exchange_discount_id=context.user_data.get("exchange_discount_id"),
            amount_currency=context.user_data.get("amount_currency"),
            accept_round_up=accept_round_up,
        )
    except ValueError as e:
        if str(e) == "ACTIVE_ORDER_EXISTS":
            if msg:
                await msg.reply_text(
                    "⚠️ У вас уже есть незавершённая заявка на покупку.\n"
                    "Нажмите «Совершить обмен» — бот предложит отменить её и создать новую.",
                    reply_markup=await menu_for(update),
                )
            context.user_data.clear()
            return None
        raise
    if rail is None:
        return False
    order_result = rail.get("order_result") or {}
    await _render_buy_order_message(
        update,
        order_id=rail["order_id"],
        fiat_amount=rail["fiat_amount"],
        payout_crypto=order_result.get("crypto_amount", crypto_amount),
        crypto=crypto,
        crypto_upper=crypto_upper,
        order_result=order_result,
        bill=rail.get("bill") or {},
        link="",
        payment_note=(
            "Оплата на карту сервиса. После перевода нажмите «Я оплатил» и пришлите чек."
        ),
        payfast_id="",
    )
    await _note_autopilot_order(
        context,
        order_id=rail["order_id"],
        user_id=user_id,
        fiat_amount=rail["fiat_amount"],
        crypto=crypto_upper,
    )
    await _close_retry_order(context, user_id, rail["order_id"])
    context.user_data.clear()
    context.user_data["step"] = "awaiting_payment_confirmation"
    return True


async def _run_merchant_payin_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    fiat_amount: int,
    sub_token: str,
    crypto,
    crypto_upper: str,
    crypto_amount,
    effective_rate,
    wallet: str,
    callback_url: str,
) -> None:
    from services.payin_discovery import discover_payin_plan
    from services.payin_resolver import plan_to_dict

    msg = _tg_msg(update)

    async def _probe_payin(**kwargs):
        kwargs.setdefault("callback_url", callback_url)
        return await create_payin_order(**kwargs)

    PAYIN_FLOW_TIMEOUT_SEC = 75.0

    async def _run_payin_flow():
        discovery = await discover_payin_plan(
            fiat_amount=fiat_amount,
            sub_token=sub_token,
            user_id=user_id,
            create_payin_fn=_probe_payin,
            cancel_payin_fn=cancel_order_merchant,
            generate_order_id_fn=generate_local_order_id,
        )
        plan = discovery.plan
        probe_resp = discovery.probe_response
        probe_id = discovery.probe_order_id

        if plan.mode == "reject":
            if context.user_data.get("requisite_retry_attempt"):
                await _send_retry_still_empty(update, context)
                return
            await _reply_no_requisites_for_amount(update, context, plan.message)
            return

        effective_sub = plan.resolved_sub_token or sub_token

        if await _try_create_single_buy_order(
            update,
            context,
            plan=plan,
            probe_resp=probe_resp,
            probe_id=probe_id,
            user_id=user_id,
            crypto=crypto,
            crypto_upper=crypto_upper,
            crypto_amount=crypto_amount,
            fiat_amount=fiat_amount,
            effective_rate=effective_rate,
            wallet=wallet,
            effective_sub=effective_sub,
            callback_url=callback_url,
            create_payin_fn=_probe_payin,
            cancel_payin_fn=cancel_order_merchant,
        ):
            return

        discovery = await discover_payin_plan(
            fiat_amount=fiat_amount,
            sub_token=sub_token,
            user_id=user_id,
            create_payin_fn=_probe_payin,
            cancel_payin_fn=cancel_order_merchant,
            generate_order_id_fn=generate_local_order_id,
        )
        plan = discovery.plan
        probe_resp = discovery.probe_response
        probe_id = discovery.probe_order_id
        effective_sub = plan.resolved_sub_token or sub_token

        if plan.mode == "reject":
            if context.user_data.get("requisite_retry_attempt"):
                await _send_retry_still_empty(update, context)
                return
            await _reply_no_requisites_for_amount(update, context, plan.message)
            return

        if await _try_create_single_buy_order(
            update,
            context,
            plan=plan,
            probe_resp=probe_resp,
            probe_id=probe_id,
            user_id=user_id,
            crypto=crypto,
            crypto_upper=crypto_upper,
            crypto_amount=crypto_amount,
            fiat_amount=fiat_amount,
            effective_rate=effective_rate,
            wallet=wallet,
            effective_sub=effective_sub,
            callback_url=callback_url,
            create_payin_fn=_probe_payin,
            cancel_payin_fn=cancel_order_merchant,
        ):
            return

        if plan.mode == "single" and fiat_amount >= config_rates.OPERATOR_FALLBACK_MIN_RUB:
            from services.payin_resolver import PayinPlan

            plan = PayinPlan(
                mode="operator",
                pay_now=fiat_amount,
                message=(
                    "Сейчас нет свободных реквизитов на эту сумму. "
                    "Можно оформить заявку через оператора."
                ),
            )

        if plan.mode != "operator":
            if context.user_data.get("requisite_retry_attempt"):
                await _send_retry_still_empty(update, context)
                return
            await _reply_no_requisites_for_amount(update, context, plan.message)
            return

        if await _block_requisites_if_no_shift(
            update,
            context,
            user_id,
            direction="buy",
            probe_resp=probe_resp,
            cancel_payin_fn=cancel_order_merchant,
            honor_autopilot=False,
        ):
            return

        if context.user_data.get("requisite_retry_attempt"):
            await _send_retry_still_empty(update, context)
            return

        context.user_data["payin_plan"] = plan_to_dict(plan)
        context.user_data["step"] = "awaiting_payin_choice"
        intro = "⚠️ <b>Сейчас нет свободных реквизитов</b>\n\n"
        if plan.message:
            intro += plan.message + "\n\n"
        intro += "Можно оформить заявку оператору:"
        if msg:
            await msg.reply_text(
                intro,
                parse_mode="HTML",
                reply_markup=_payin_plan_keyboard(plan),
            )

    try:
        await asyncio.wait_for(_run_payin_flow(), timeout=PAYIN_FLOW_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        exchange_fsm_logger.error("payin flow timeout user=%s fiat=%s", user_id, fiat_amount)
        if msg:
            await msg.reply_text(
                "⚠️ Платёжная система долго не отвечает.\n\n"
                "Нажмите «Совершить обмен» и попробуйте снова "
                "или напишите в чат на сайте / оператору @focus_operator.",
                reply_markup=await menu_for(update),
            )
        context.user_data.clear()


def _coin_short_user_text(gate: dict | None) -> str | None:
    code = str((gate or {}).get("reason") or "")
    if code == "coin_short":
        coin = str((gate or {}).get("coin") or "").upper()
        label = coin if coin.isalnum() else "этой валюты"
        return (
            f"⚠️ <b>Сейчас нет столько {label}.</b>\n\n"
            "Сумма больше, чем есть на кошельке. "
            "Укажите меньшую сумму или попробуйте позже."
        )
    if code == "coin_unknown":
        return (
            "⚠️ <b>Сейчас не можем выдать эту сумму.</b>\n\n"
            "Попробуйте позже через 30–60 минут."
        )
    return None


def _retry_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    user = update.effective_user
    data = context.user_data
    wallet = str(data.get("buy_wallet") or "").strip()
    crypto = data.get("crypto")
    fiat = data.get("fiat_amount")
    if user is None or len(wallet) < 10 or not crypto or fiat in (None, ""):
        return None
    network = data.get("network")
    if str(crypto).lower() == "usdt" and network:
        crypto_sym = f"USDT_{str(network).upper()}"
    else:
        crypto_sym = str(crypto).upper()
    try:
        fiat_amount = float(fiat)
        rate = float(data.get("effective_rate") or 0)
        crypto_amount = float(data.get("crypto_amount") or 0)
    except (TypeError, ValueError):
        return None
    if fiat_amount <= 0:
        return None
    return {
        "user_id": int(user.id),
        "fiat_amount": fiat_amount,
        "crypto": crypto_sym,
        "network": str(network) if network else None,
        "wallet": wallet,
        "sub_token": str(data.get("sub_token") or "SBPRUB"),
        "rate": rate,
        "crypto_amount": crypto_amount,
        "amount_currency": data.get("amount_currency"),
        "order_source": "bot",
    }


async def _reki_fit(context: ContextTypes.DEFAULT_TYPE):
    """Ближайший свободный коридор из /reki. Подсказка, а не обещание реквизита."""
    data = context.user_data
    try:
        fiat = float(data.get("fiat_amount") or 0)
    except (TypeError, ValueError):
        return None
    if fiat <= 0:
        return None
    from services.reki_poll import load_snapshot, snapshot_ttl_seconds
    from services.reki_snapshot import fit_reki

    try:
        snapshot = await load_snapshot()
    except Exception:
        logger.warning("reki hint skipped", exc_info=True)
        return None
    fit = fit_reki(
        snapshot,
        str(data.get("sub_token") or "SBPRUB"),
        fiat,
        ttl_seconds=snapshot_ttl_seconds(),
    )
    return fit if fit.found else None


def _stash_reki_offer(context: ContextTypes.DEFAULT_TYPE, body: dict | None, fit) -> None:
    """Черновик под кнопку «Оформить на N ₽». Кладём после очистки user_data."""
    from services.reki_snapshot import FIT_OVER_PAY, FIT_TOP_UP

    if not body or fit is None or fit.kind not in (FIT_TOP_UP, FIT_OVER_PAY):
        return
    context.user_data["reki_offer"] = {
        "pay_rub": int(round(float(fit.pay_rub))),
        "crypto": body.get("crypto"),
        "network": body.get("network"),
        "wallet": body.get("wallet"),
        "sub_token": body.get("sub_token"),
        "rate": body.get("rate"),
        "amount_currency": body.get("amount_currency"),
    }


async def _send_retry_notice(update: Update, text: str, fit=None) -> None:
    from services.requisite_retry_client import reki_offer_text, retry_keyboard

    msg = _tg_msg(update)
    if not msg:
        return
    hint = reki_offer_text(fit)
    await msg.reply_text(
        f"{text}{hint}" if hint else text,
        parse_mode="HTML",
        reply_markup=retry_keyboard(fit.pay_rub if hint else None),
    )
    await msg.reply_text("Главное меню", reply_markup=await menu_for(update))


async def _send_retry_still_empty(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    from services.requisite_retry_client import retry_still_empty_text

    body = _retry_body(update, context)
    fit = await _reki_fit(context)
    await _send_retry_notice(update, retry_still_empty_text(), fit=fit)
    context.user_data.clear()
    _stash_reki_offer(context, body, fit)


async def _try_save_requisite_retry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    body = _retry_body(update, context)
    if not body:
        return False
    from services.requisite_retry_client import open_requisite_retry, retry_saved_text

    saved = await open_requisite_retry(body)
    if not saved or not saved.get("saved"):
        return False
    fit = await _reki_fit(context)
    await _send_retry_notice(update, retry_saved_text(), fit=fit)
    context.user_data.clear()
    _stash_reki_offer(context, body, fit)
    return True


async def _reply_no_requisites_for_amount(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str | None
) -> None:
    """Нет реквизита на запрошенную сумму: подсказываем ближайшую проходящую."""
    import html

    from services.requisite_retry_client import reki_offer_text, retry_keyboard

    msg = _tg_msg(update)
    text = message or "❌ Нет реквизитов на эту сумму. Укажите другую сумму."
    body = _retry_body(update, context)
    fit = await _reki_fit(context)
    hint = reki_offer_text(fit)
    if msg and hint:
        await msg.reply_text(
            f"{html.escape(text)}{hint}",
            parse_mode="HTML",
            reply_markup=retry_keyboard(fit.pay_rub),
        )
        await msg.reply_text("Главное меню", reply_markup=await menu_for(update))
    elif msg:
        await msg.reply_text(text, reply_markup=await menu_for(update))
    context.user_data.clear()
    if hint:
        _stash_reki_offer(context, body, fit)


async def _close_retry_order(context: ContextTypes.DEFAULT_TYPE, user_id: int, order_id: str) -> None:
    if not context.user_data.get("requisite_retry_attempt") or not order_id:
        return
    from services.requisite_retry_client import close_requisite_retry

    try:
        await close_requisite_retry(int(user_id), str(order_id))
    except Exception:
        logger.exception("close requisite retry failed user=%s order=%s", user_id, order_id)


def _apply_retry_draft(context: ContextTypes.DEFAULT_TYPE, claimed: dict) -> None:
    crypto_raw = str(claimed.get("crypto") or "")
    base = crypto_raw.split("_", 1)[0].lower()
    network = claimed.get("network")
    if not network and "_" in crypto_raw:
        network = crypto_raw.split("_", 1)[1]
    context.user_data.clear()
    context.user_data.update(
        {
            "direction": "buy",
            "crypto": base,
            "network": network,
            "buy_wallet": claimed.get("wallet") or "",
            "fiat_amount": int(round(float(claimed.get("fiat_amount") or 0))),
            "crypto_amount": claimed.get("crypto_amount"),
            "effective_rate": claimed.get("rate"),
            "sub_token": claimed.get("sub_token") or "SBPRUB",
            "amount_currency": claimed.get("amount_currency"),
            "requisite_retry_attempt": True,
        }
    )


async def _handle_requisite_retry_press(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user if query else update.effective_user
    msg = _tg_msg(update)
    if user is None:
        return
    from services.requisite_retry_client import (
        claim_requisite_retry,
        retry_expired_text,
        retry_keyboard,
        retry_wait_text,
    )

    claimed = await claim_requisite_retry(user.id)
    if not claimed:
        if msg:
            await msg.reply_text(
                "Не получилось повторить запрос. Попробуйте ещё раз.",
                reply_markup=await menu_for(update),
            )
        return
    if not claimed.get("ok"):
        if msg:
            reason = str(claimed.get("reason") or "")
            if reason == "expired":
                await msg.reply_text(
                    retry_expired_text(), reply_markup=await menu_for(update)
                )
            else:
                await msg.reply_text(
                    retry_wait_text(claimed.get("message")),
                    reply_markup=retry_keyboard(),
                )
                await msg.reply_text("Главное меню", reply_markup=await menu_for(update))
        return

    _apply_retry_draft(context, claimed)
    await _run_buy_draft(update, context, user_id=int(user.id))


async def _handle_reki_offer_press(
    update: Update, context: ContextTypes.DEFAULT_TYPE, raw_amount: str
) -> None:
    """«Оформить на N ₽» — обычный поиск реквизитов на подсказанную сумму."""
    user = update.effective_user
    msg = _tg_msg(update)
    offer = context.user_data.get("reki_offer")
    try:
        amount = int(raw_amount)
    except (TypeError, ValueError):
        amount = 0
    if user is None or not offer or amount <= 0 or amount != int(offer.get("pay_rub") or 0):
        if msg:
            await msg.reply_text(
                "Предложение больше не действует. Начните обмен заново.",
                reply_markup=await menu_for(update),
            )
        context.user_data.clear()
        return

    try:
        rate = float(offer.get("rate") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        if msg:
            await msg.reply_text(
                "Курс устарел. Начните обмен заново.", reply_markup=await menu_for(update)
            )
        context.user_data.clear()
        return

    _apply_retry_draft(
        context,
        {
            "crypto": offer.get("crypto"),
            "network": offer.get("network"),
            "wallet": offer.get("wallet"),
            "fiat_amount": amount,
            "crypto_amount": amount / rate,
            "rate": rate,
            "sub_token": offer.get("sub_token"),
            "amount_currency": offer.get("amount_currency"),
        },
    )
    await _run_buy_draft(update, context, user_id=int(user.id))


async def _run_buy_draft(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, user_id: int
) -> None:
    """Обычный путь поиска реквизитов по уже разложенному в user_data черновику."""
    msg = _tg_msg(update)
    crypto = context.user_data.get("crypto")
    network = context.user_data.get("network")
    if crypto == "usdt" and network:
        crypto_upper = f"USDT_{str(network).upper()}"
    else:
        crypto_upper = str(crypto or "").upper()
    fiat_amount = int(context.user_data.get("fiat_amount") or 0)
    crypto_amount = context.user_data.get("crypto_amount")
    effective_rate = context.user_data.get("effective_rate") or 0
    wallet = str(context.user_data.get("buy_wallet") or "")
    sub_token = str(context.user_data.get("sub_token") or "SBPRUB")
    cfg = load_config()
    callback_url = (cfg.MERCHANT.get("callback_url") or "").strip()
    if msg:
        await msg.reply_text("⏳ Ищем реквизиты для оплаты, подождите…")
    created = await _create_payin_rail_and_show(
        update,
        context,
        user_id=user_id,
        crypto=crypto,
        crypto_upper=crypto_upper,
        crypto_amount=crypto_amount,
        fiat_amount=fiat_amount,
        effective_rate=effective_rate,
        wallet=wallet,
        sub_token=sub_token,
        accept_round_up=False,
    )
    if created or created is None:
        return
    if await _offer_payin_round_if_close(
        update,
        context,
        user_id=user_id,
        fiat_amount=fiat_amount,
        sub_token=sub_token,
    ):
        return
    await _run_merchant_payin_flow(
        update,
        context,
        user_id=user_id,
        fiat_amount=fiat_amount,
        sub_token=sub_token,
        crypto=crypto,
        crypto_upper=crypto_upper,
        crypto_amount=crypto_amount,
        effective_rate=effective_rate,
        wallet=wallet,
        callback_url=callback_url,
    )


async def _reply_no_requisites_without_shift(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    direction: str,
    missing_roles: tuple[str, ...] = (),
    why: str | None = None,
    user_text: str | None = None,
) -> None:
    from services.operator_availability import NO_REQUISITES_NO_SHIFT_TEXT
    from services.no_shift_block_notify import record_no_shift_block_and_notify

    user = update.effective_user
    msg = update.message or (
        update.callback_query.message if update.callback_query else None
    )
    if (direction or "").lower() == "buy" and user_text is None:
        if context.user_data.get("requisite_retry_attempt"):
            await _send_retry_still_empty(update, context)
            return
        if await _try_save_requisite_retry(update, context):
            return
    if msg:
        await msg.reply_text(
            user_text or NO_REQUISITES_NO_SHIFT_TEXT,
            parse_mode="HTML",
            reply_markup=await menu_for(update),
        )
    if user:
        try:
            bot_data = (
                context.application.bot_data
                if context.application is not None
                else context.bot_data
            )
            fiat_raw = context.user_data.get("fiat_amount")
            try:
                fiat_amount = int(fiat_raw) if fiat_raw not in (None, "") else None
            except (TypeError, ValueError):
                fiat_amount = None
            await record_no_shift_block_and_notify(
                context.bot,
                bot_data,
                user_id=user.id,
                direction=direction,
                username=user.username,
                missing_roles=missing_roles,
                fiat_amount=fiat_amount,
                why=why,
            )
        except Exception:
            logger.exception(
                "no_shift notify/record failed after buyer notice user=%s",
                user.id,
            )
    context.user_data.clear()


async def _note_autopilot_order(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    order_id: str,
    user_id: int,
    fiat_amount,
    crypto: str,
) -> None:
    if not context.user_data.get("autopilot_no_shift"):
        return
    from services.no_shift_autopilot import mark_regular_no_shift_order

    try:
        fiat = float(fiat_amount or 0)
    except (TypeError, ValueError):
        fiat = 0.0
    await mark_regular_no_shift_order(
        order_id=str(order_id),
        user_id=int(user_id),
        fiat_amount=fiat,
        crypto=str(crypto or ""),
    )


async def _block_requisites_if_no_shift(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    direction: str,
    probe_resp: dict | None = None,
    cancel_payin_fn=None,
    honor_autopilot: bool = True,
) -> bool:
    from services.operator_availability import missing_requisite_roles
    from services.payin_discovery import _safe_cancel

    missing_roles = await missing_requisite_roles(user_id)
    if not missing_roles:
        return False
    from services.no_shift_block_notify import block_why

    gate: dict | None = None
    gate_code = ""
    if (direction or "buy").lower() == "sell":
        gate_code = "sell_requires_shift"
    elif not honor_autopilot:
        gate_code = "no_bill"
    elif honor_autopilot:
        from services.no_shift_autopilot import no_shift_access

        fiat_raw = context.user_data.get("fiat_amount")
        try:
            fiat_amount = int(fiat_raw) if fiat_raw not in (None, "") else None
        except (TypeError, ValueError):
            fiat_amount = None
        crypto_raw = context.user_data.get("crypto")
        network = context.user_data.get("network")
        if str(crypto_raw or "").lower() == "usdt" and network:
            crypto_sym = f"USDT_{str(network).upper()}"
        else:
            crypto_sym = str(crypto_raw or "")
        raw_amt = context.user_data.get("crypto_amount")
        try:
            crypto_amount = float(raw_amt) if raw_amt not in (None, "") else None
        except (TypeError, ValueError):
            crypto_amount = None
        gate = await no_shift_access(
            user_id,
            fiat_amount,
            crypto=crypto_sym or None,
            crypto_amount=crypto_amount,
        )
        if gate and gate.get("kind") == "allow_auto":
            context.user_data["autopilot_no_shift"] = True
            return False
        gate_code = str((gate or {}).get("reason") or "autopilot_unavailable")
    if probe_resp and cancel_payin_fn:
        await _safe_cancel(cancel_payin_fn, probe_resp)
    await _reply_no_requisites_without_shift(
        update,
        context,
        direction=direction,
        missing_roles=missing_roles,
        why=block_why(gate_code, gate),
        user_text=_coin_short_user_text(gate),
    )
    return True


async def _try_create_single_buy_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    plan,
    probe_resp: dict | None,
    probe_id: str | None,
    user_id: int,
    crypto: str,
    crypto_upper: str,
    crypto_amount,
    fiat_amount: int,
    effective_rate,
    wallet: str,
    effective_sub: str,
    callback_url: str,
    create_payin_fn,
    cancel_payin_fn,
) -> bool:
    from services.buy_order_service import create_buy_part_order

    if not (plan.mode == "single" and plan.has_bill and probe_resp and probe_id):
        return False
    if await _block_requisites_if_no_shift(
        update,
        context,
        user_id,
        direction="buy",
        probe_resp=probe_resp,
        cancel_payin_fn=cancel_payin_fn,
    ):
        return True
    try:
        async with SEM_CREATE_ORDER:
            result = await create_buy_part_order(
                create_payin_order_fn=create_payin_fn,
                cancel_payin_fn=cancel_payin_fn,
                order_id=probe_id,
                user_id=user_id,
                crypto=crypto_upper,
                crypto_amount=float(crypto_amount),
                fiat_amount=fiat_amount,
                rate=float(effective_rate),
                requisites=wallet,
                sub_token=effective_sub,
                callback_url=callback_url,
                api_response=probe_resp,
                exchange_discount_id=context.user_data.get("exchange_discount_id"),
                amount_currency=context.user_data.get("amount_currency"),
            )
    except ValueError as e:
        code = str(e)
        if code == "ACTIVE_ORDER_EXISTS":
            exchange_fsm_logger.warning("buy blocked: active buy order user=%s", user_id)
            msg = _tg_msg(update)
            if msg:
                await msg.reply_text(
                    "⚠️ У вас уже есть незавершённая заявка на покупку.\n"
                    "Нажмите «Совершить обмен» — бот предложит отменить её и создать новую.",
                    reply_markup=await menu_for(update),
                )
            context.user_data.clear()
            return True
        # Известные ошибки платёжной системы: не запускаем повторный discovery
        # (счёт уже отменён внутри create_buy_part_order), показываем причину.
        if code in ("NO_BILL", "PAYMENT_PROVIDER_ERROR", "PAYFAST_DEADLINE_TOO_SHORT"):
            exchange_fsm_logger.warning("buy payment error user=%s: %s", user_id, code)
            if context.user_data.get("requisite_retry_attempt"):
                await _send_retry_still_empty(update, context)
                return True
            msg = _tg_msg(update)
            if msg:
                await msg.reply_text(
                    user_facing_message(e, payment=True),
                    reply_markup=await menu_for(update),
                )
            context.user_data.clear()
            return True
        # Непредвиденный сбой — не маскируем ложным «нет реквизитов», пробрасываем.
        exchange_fsm_logger.exception("create_buy_part_order failed user=%s", user_id)
        raise

    order_result = result.get("order_result") or {}
    payment_note = plan.message if plan.resolved_sub_token == "SBPRUB" else ""  # nosec B105
    from services.payin_resolver import extract_merchant_uuid

    await _render_buy_order_message(
        update,
        order_id=result["order_id"],
        fiat_amount=result["fiat_amount"],
        payout_crypto=order_result.get("crypto_amount", crypto_amount),
        crypto=crypto,
        crypto_upper=crypto_upper,
        order_result=order_result,
        bill=result.get("bill") or {},
        link=result.get("link") or "",
        payment_note=payment_note,
        payfast_id=extract_merchant_uuid(result.get("api_response")) or "",
    )
    await _note_autopilot_order(
        context,
        order_id=result["order_id"],
        user_id=user_id,
        fiat_amount=result["fiat_amount"],
        crypto=crypto_upper,
    )
    await _close_retry_order(context, user_id, result["order_id"])
    context.user_data.clear()
    context.user_data["step"] = "awaiting_payment_confirmation"
    return True


async def _end_payin_without_requisites(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    if context.user_data.get("requisite_retry_attempt"):
        await _send_retry_still_empty(update, context)
        return
    context.user_data.clear()
    msg = _tg_msg(update)
    if msg:
        await msg.reply_text(text, reply_markup=await menu_for(update))


async def _handle_payin_round_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    accept: bool,
) -> None:
    query = update.callback_query
    msg = _tg_msg(update)
    if context.user_data.get("step") != "awaiting_payin_round":
        if msg:
            await msg.reply_text("Сессия истекла. Начните обмен заново.")
        return
    if not accept:
        await _end_payin_without_requisites(
            update,
            context,
            "Без этой суммы реквизиты сейчас не выдаём.",
        )
        return
    user = query.from_user if query else update.effective_user
    if user is None:
        return
    user_id = user.id
    crypto = context.user_data.get("crypto")
    crypto_amount = context.user_data.get("crypto_amount")
    fiat_amount = int(context.user_data.get("fiat_amount"))
    effective_rate = float(context.user_data.get("effective_rate"))
    wallet = context.user_data.get("buy_wallet") or ""
    sub_token = context.user_data.get("sub_token") or "CARDRUB"
    network = context.user_data.get("network")
    if crypto == "usdt" and network:
        crypto_upper = f"USDT_{network.upper()}"
    else:
        crypto_upper = crypto.upper() if crypto else ""
    if await _block_requisites_if_no_shift(
        update,
        context,
        user_id,
        direction="buy",
    ):
        return
    created = await _create_payin_rail_and_show(
        update,
        context,
        user_id=user_id,
        crypto=crypto,
        crypto_upper=crypto_upper,
        crypto_amount=crypto_amount,
        fiat_amount=fiat_amount,
        effective_rate=effective_rate,
        wallet=wallet,
        sub_token=sub_token,
        accept_round_up=True,
    )
    if created or created is None:
        return
    await _end_payin_without_requisites(
        update,
        context,
        "Карта уже занята. Свободных реквизитов на эту сумму нет.",
    )


async def payin_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()
    if query.data == "payin:cancel":
        context.user_data.clear()
        await query.message.reply_text("Отменено.", reply_markup=await menu_for(update))
        return
    if query.data in ("payin:round:yes", "payin:round:no"):
        await _handle_payin_round_choice(update, context, accept=query.data.endswith("yes"))
        return
    if query.data == "payin:retry":
        await _handle_requisite_retry_press(update, context)
        return
    if query.data.startswith("payin:reki:"):
        await _handle_reki_offer_press(update, context, query.data.rsplit(":", 1)[-1])
        return
    if not query.data.startswith("payin:go:"):
        return
    requested_mode = query.data.split(":")[-1]
    plan_data = context.user_data.get("payin_plan")
    if not plan_data:
        await query.message.reply_text("Сессия истекла. Начните обмен заново.")
        return
    from services.payin_resolver import PayinPlan, resolve_payin_mode
    from services.buy_order_service import execute_buy_with_plan

    try:
        mode = resolve_payin_mode(plan_data, requested_mode)
    except ValueError as e:
        await query.message.reply_text(
            user_facing_message(e), reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    fiat_amount = int(context.user_data.get("fiat_amount"))
    parts = plan_data.get("parts") or []
    if mode == "single":
        parts = [fiat_amount]

    plan = PayinPlan(
        mode=mode,
        parts=parts,
        pay_now=plan_data.get("pay_now", 0) or fiat_amount,
        remainder_rub=plan_data.get("remainder_rub", 0),
        message=plan_data.get("message", ""),
        has_bill=bool(plan_data.get("has_bill")),
        partial_probe_ok=bool(plan_data.get("partial_probe_ok")),
        resolved_sub_token=plan_data.get("resolved_sub_token"),
    )

    user = query.from_user
    crypto = context.user_data.get("crypto")
    crypto_amount = context.user_data.get("crypto_amount")
    effective_rate = float(context.user_data.get("effective_rate"))
    wallet = context.user_data.get("buy_wallet") or ""
    sub_token = plan.resolved_sub_token or context.user_data.get("sub_token") or "CARDRUB"
    network = context.user_data.get("network")
    if crypto == "usdt" and network:
        crypto_upper = f"USDT_{network.upper()}"
    else:
        crypto_upper = crypto.upper() if crypto else ""

    cfg = load_config()
    callback_url = (cfg.MERCHANT.get("callback_url") or "").strip()

    if await _block_requisites_if_no_shift(
        update,
        context,
        user.id,
        direction="buy",
        honor_autopilot=plan.mode != "operator",
    ):
        return

    if mode == "operator":
        if context.user_data.get("requisite_retry_attempt"):
            await _send_retry_still_empty(update, context)
            return
        if await _try_save_requisite_retry(update, context):
            return

    try:
        async with SEM_CREATE_ORDER:
            result = await execute_buy_with_plan(
                create_payin_order_fn=create_payin_order,
                cancel_payin_fn=cancel_order_merchant,
                generate_order_id_fn=generate_local_order_id,
                user_id=user.id,
                crypto=crypto_upper,
                crypto_amount=float(crypto_amount),
                fiat_amount=fiat_amount,
                rate=effective_rate,
                requisites=wallet,
                sub_token=sub_token,
                callback_url=callback_url,
                plan=plan,
                exchange_discount_id=context.user_data.get("exchange_discount_id"),
                amount_currency=context.user_data.get("amount_currency"),
            )
    except ValueError as e:
        await query.message.reply_text(
            user_facing_message(e, payment=True), reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    if result.get("mode") == "operator":
        from services.db import get_order
        from services.order_ops_notify import notify_ops_order

        op_order = await get_order(result["order_id"])
        if op_order:
            await notify_ops_order(
                "created",
                dict(op_order),
                bot=context.bot,
                username=user.username,
                note="Нет реквизитов мерчанта — оператор",
            )
        await query.message.reply_text(
            "Сейчас нет свободных реквизитов на эту сумму.\n\n"
            "Напишите в чат на сайте или оператору @focus_operator — он подберёт вариант.\n"
            f"Минимум для ручного обмена — <b>{config_rates.OPERATOR_FALLBACK_MIN_RUB:,.0f} ₽</b>.\n\n"
            f"🆔 Номер заявки: <code>{result['order_id']}</code>",
            parse_mode="HTML",
            reply_markup=await menu_for(update),
        )
        context.user_data.clear()
        return

    order_result = result.get("order_result") or {}
    from services.db import get_order
    from services.order_ops_notify import notify_ops_order

    created = await get_order(result["order_id"])
    if created:
        await notify_ops_order(
            "created",
            dict(created),
            bot=context.bot,
            username=user.username,
        )
    from services.payin_resolver import extract_merchant_uuid

    await _render_buy_order_message(
        update,
        order_id=result["order_id"],
        fiat_amount=result["fiat_amount"],
        payout_crypto=order_result.get("crypto_amount", crypto_amount),
        crypto=crypto,
        crypto_upper=crypto_upper,
        order_result=order_result,
        bill=result.get("bill") or {},
        link=result.get("link") or "",
        part_index=1,
        parts_count=result.get("parts_count", 1),
        payfast_id=extract_merchant_uuid(result.get("api_response")) or "",
    )
    await _note_autopilot_order(
        context,
        order_id=result["order_id"],
        user_id=user.id,
        fiat_amount=result["fiat_amount"],
        crypto=crypto_upper,
    )
    context.user_data.clear()
    context.user_data["step"] = "awaiting_payment_confirmation"


def check_rate_change(context, crypto: str, direction: str):
    raw = get_cached_rate(crypto, direction)
    if raw is None:
        fallback = context.user_data.get("last_rate")
        if fallback is None:
            raise ValueError(f"No cached rate for {crypto}")
        raw = float(fallback)
    current_rate = Decimal(str(raw))
    last_rate = context.user_data.get("last_rate")

    if last_rate is None:
        context.user_data["last_rate"] = current_rate
        return current_rate, False

    last_rate = Decimal(str(last_rate))
    delta = abs(current_rate - last_rate) / last_rate

    if delta > MAX_RATE_DEVIATION:
        context.user_data["last_rate"] = current_rate
        return current_rate, True

    return current_rate, False

from services.menu import main_menu_keyboard as _main_menu_keyboard


async def menu_for(update: Update):
    u = update.effective_user
    return await _main_menu_keyboard(u.id if u else None, u.username if u else None)


def buy_operation_label(crypto_upper: str) -> str:
    return f"Покупка (RUB → {crypto_upper})"


def sell_operation_label(crypto_upper: str) -> str:
    return f"Продажа ({crypto_upper} → RUB)"


def operation_choice_keyboard(crypto: str) -> ReplyKeyboardMarkup:
    crypto_upper = crypto.upper()
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(buy_operation_label(crypto_upper), style="success")],
            [KeyboardButton(sell_operation_label(crypto_upper), style="danger")],
            ["🚫 Отмена"],
        ],
        resize_keyboard=True,
    )


def usdt_network_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["TRC20", "ERC20"],
            ["BEP20", "ARBITRUM"],
            ["SOLANA"],
            ["🚫 Отмена"]
        ],
        resize_keyboard=True
    )


# --- Inline-навигация обмена (внешний вид как в demo_bot) ---------------

_EX_COINS = (
    ("BTC", "Bitcoin", "btc"),
    ("USDT", "Tether", "usdt"),
    ("TRX", "Tron", "trx"),
    ("LTC", "Litecoin", "ltc"),
)
_EX_NETWORKS = ("TRC20", "ERC20", "BEP20", "ARBITRUM", "SOLANA")


def _ib(
    text: str,
    data: str,
    *,
    style: str | None = None,
    icon: str | None = None,
) -> InlineKeyboardButton:
    kwargs: dict = {}
    if style:
        kwargs["style"] = style
    if icon:
        kwargs["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(text=text, callback_data=data, **kwargs)


def kb_ex_coins() -> InlineKeyboardMarkup:
    from services.tg_emoji import eid

    rows = []
    pair: list[InlineKeyboardButton] = []
    for code, name, key in _EX_COINS:
        pair.append(_ib(f"{code} · {name}", f"ex:coin:{code}", icon=eid(key)))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([_ib("✖️ Отмена", "ex:cancel", style="danger")])
    return InlineKeyboardMarkup(rows)


def kb_ex_networks() -> InlineKeyboardMarkup:
    rows = [
        [_ib("TRC20", "ex:net:TRC20", style="primary"), _ib("ERC20", "ex:net:ERC20")],
        [_ib("BEP20", "ex:net:BEP20"), _ib("ARBITRUM", "ex:net:ARBITRUM")],
        [_ib("SOLANA", "ex:net:SOLANA")],
        [_ib("⬅️ Другая монета", "ex:back:coins"), _ib("✖️ Отмена", "ex:cancel", style="danger")],
    ]
    return InlineKeyboardMarkup(rows)


def kb_ex_direction(coin: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                _ib(f"Купить {coin}", "ex:dir:buy", style="success"),
                _ib(f"Продать {coin}", "ex:dir:sell", style="danger"),
            ],
            [_ib("⬅️ Назад", "ex:back:after_coin")],
        ]
    )


def kb_ex_unit(coin: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                _ib("В рублях ₽", "ex:unit:rub", style="primary"),
                _ib(f"В {coin}", "ex:unit:coin", style="primary"),
            ],
            [
                _ib("⬅️ Назад", "ex:back:dir"),
                _ib("✖️ Отмена", "ex:cancel", style="danger"),
            ],
        ]
    )


def _ex_cancel_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["🚫 Отмена"]], resize_keyboard=True)


async def _ex_send(
    update: Update,
    text: str,
    *,
    markup=None,
    parse_mode: str = "HTML",
    edit: bool = True,
):
    """Ответ в FSM: при callback — edit сообщения, иначе reply."""
    q = update.callback_query
    if q and q.message and edit:
        try:
            await q.edit_message_text(text, reply_markup=markup, parse_mode=parse_mode)
            return
        except telegram.error.BadRequest as ex:
            if "message is not modified" in str(ex).lower():
                return
            # нельзя отредактировать — шлём новое
        await q.message.reply_text(text, reply_markup=markup, parse_mode=parse_mode)
        return
    msg = update.effective_message
    if msg:
        await msg.reply_text(text, reply_markup=markup, parse_mode=parse_mode)


async def _ex_show_coins(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    with_banner: bool = False,
) -> None:
    from services.cashback_tier import percent_for_completed_count
    from services.ux_copy import txt_exchange_start

    context.user_data["step"] = "choose_currency"
    context.user_data.pop("crypto", None)
    context.user_data.pop("network", None)
    context.user_data.pop("direction", None)
    context.user_data.pop("amount_currency", None)

    try:
        await ensure_rates_cache()
    except RatesUnavailableError:
        await _ex_send(
            update,
            USER_RATES_UNAVAILABLE,
            markup=await menu_for(update),
            edit=False,
        )
        context.user_data.clear()
        return

    rates = {}
    for c in ("btc", "usdt", "trx", "ltc"):
        rates[c] = get_cached_rate(c, "buy") or CACHE.get(c, {}).get("price")
    text = txt_exchange_start(
        rates=rates,
        cashback_from_pct=percent_for_completed_count(0),
    )
    if with_banner and not update.callback_query:
        from services.welcome_banner import send_welcome_photo

        chat_id = update.effective_user.id if update.effective_user else None
        if update.effective_chat:
            chat_id = update.effective_chat.id
        if chat_id is not None:
            await send_welcome_photo(
                context.bot,
                chat_id,
                caption=text,
                reply_markup=kb_ex_coins(),
            )
            return
    await _ex_send(update, text, markup=kb_ex_coins())


async def _ex_after_coin_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE, crypto_upper: str
) -> None:
    from services.ux_copy import COIN_NAMES, txt_direction, txt_usdt_network

    crypto_lower = crypto_upper.lower()
    context.user_data["crypto"] = crypto_lower
    context.user_data.pop("network", None)
    context.user_data.pop("direction", None)
    context.user_data.pop("amount_currency", None)

    if crypto_lower == "usdt":
        context.user_data["step"] = "choose_usdt_network"
        await _ex_send(update, txt_usdt_network(), markup=kb_ex_networks())
        return

    buy_price = get_cached_rate(crypto_lower, "buy")
    sell_price = get_cached_rate(crypto_lower, "sell")
    if buy_price is None or sell_price is None:
        try:
            await ensure_rates_cache()
        except RatesUnavailableError:
            pass
        buy_price = get_cached_rate(crypto_lower, "buy")
        sell_price = get_cached_rate(crypto_lower, "sell")
    if buy_price is None or sell_price is None:
        await _ex_send(
            update,
            USER_RATES_UNAVAILABLE,
            markup=await menu_for(update),
            edit=False,
        )
        context.user_data.clear()
        return

    context.user_data["step"] = "choose_operation"
    title = f"{COIN_NAMES.get(crypto_lower, crypto_upper)} ({crypto_upper})"
    rate = buy_price or CACHE.get(crypto_lower, {}).get("price")
    await _ex_send(
        update,
        txt_direction(
            crypto=crypto_lower,
            coin_title=title,
            rate=rate,
        ),
        markup=kb_ex_direction(crypto_upper),
    )


async def _ex_after_network(
    update: Update, context: ContextTypes.DEFAULT_TYPE, network: str
) -> None:
    from services.ux_copy import txt_direction

    context.user_data["network"] = network.lower()
    context.user_data["step"] = "choose_operation"
    crypto = context.user_data.get("crypto") or "usdt"
    market_price = CACHE.get(crypto, {}).get("price")
    if market_price is None:
        try:
            await ensure_rates_cache()
        except RatesUnavailableError:
            pass
        market_price = CACHE.get(crypto, {}).get("price")
    if market_price is None:
        await _ex_send(
            update,
            USER_RATES_UNAVAILABLE,
            markup=await menu_for(update),
            edit=False,
        )
        context.user_data.clear()
        return
    buy_price = get_cached_rate(crypto, "buy")
    sell_price = get_cached_rate(crypto, "sell")
    if buy_price is None or sell_price is None:
        await _ex_send(
            update,
            USER_RATES_UNAVAILABLE,
            markup=await menu_for(update),
            edit=False,
        )
        context.user_data.clear()
        return
    await _ex_send(
        update,
        txt_direction(
            crypto="usdt",
            coin_title=f"Tether (USDT · {network})",
            rate=buy_price or market_price,
        ),
        markup=kb_ex_direction("USDT"),
    )


async def _ex_after_direction(
    update: Update, context: ContextTypes.DEFAULT_TYPE, direction: str
) -> None:
    from services.ux_copy import txt_unit

    crypto = context.user_data.get("crypto")
    if not crypto:
        await _ex_show_coins(update, context)
        return
    crypto_upper = crypto.upper()
    context.user_data["direction"] = direction

    if direction == "sell":
        try:
            await get_need_rates_cached()
        except Exception:
            pass
    rate = get_cached_rate(crypto, direction)
    if rate is None:
        try:
            await ensure_rates_cache()
        except RatesUnavailableError:
            pass
        rate = get_cached_rate(crypto, direction)
    if rate is None:
        await _ex_send(
            update,
            USER_RATES_UNAVAILABLE,
            markup=await menu_for(update),
            edit=False,
        )
        context.user_data.clear()
        return
    rate = Decimal(str(rate))
    context.user_data["last_rate"] = rate

    context.user_data["step"] = "enter_amount"
    context.user_data.pop("amount_currency", None)
    await _ex_send(
        update,
        txt_unit(crypto=crypto, direction=direction),
        markup=kb_ex_unit(crypto_upper),
    )


async def _ex_after_unit(
    update: Update, context: ContextTypes.DEFAULT_TYPE, unit: str
) -> None:
    """unit: rub | coin — дальше ждём число с reply-клавиатуры «Отмена»."""
    from services.ux_copy import txt_amount_prompt

    crypto = context.user_data.get("crypto") or "btc"
    direction = context.user_data.get("direction") or "buy"
    crypto_upper = crypto.upper()

    cfg = load_config()
    limits = cfg.AMOUNT_LIMITS.get(crypto, {})
    min_crypto = to_decimal(limits["min_crypto"])
    max_crypto = to_decimal(limits["max_crypto"])
    rate_raw = context.user_data.get("last_rate") or get_cached_rate(crypto, direction)
    rate = Decimal(str(rate_raw)) if rate_raw is not None else None
    min_fiat = (min_crypto * rate).quantize(Decimal("0.01")) if rate else None
    max_fiat = (max_crypto * rate).quantize(Decimal("0.01")) if rate else None

    if unit == "rub":
        context.user_data["amount_currency"] = "rub"
        if direction == "buy":
            need_price = await get_need_price(crypto)
            if need_price is None:
                await _ex_send(
                    update,
                    USER_NEED_RATES_UNAVAILABLE,
                    markup=await menu_for(update),
                    edit=False,
                )
                return
            need_dec = Decimal(str(need_price))
            min_fiat = (min_crypto * need_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            max_fiat = (max_crypto * need_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        min_label = f"{min_fiat} ₽" if min_fiat is not None else "—"
        max_label = f"{max_fiat} ₽" if max_fiat is not None else None
    else:
        context.user_data["amount_currency"] = "crypto"
        min_label = f"{fmt_crypto(min_crypto, crypto)} {crypto_upper}"
        if min_fiat is not None:
            min_label += f" (≈ {min_fiat} ₽)"
        max_label = f"{fmt_crypto(max_crypto, crypto)} {crypto_upper}"

    prompt = txt_amount_prompt(
        crypto=crypto,
        direction=direction,
        unit=unit,
        min_label=min_label,
        max_label=max_label,
    )

    context.user_data["step"] = "enter_amount"
    q = update.callback_query
    if q and q.message:
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        await q.message.reply_text(
            prompt,
            parse_mode="HTML",
            reply_markup=_ex_cancel_reply_kb(),
        )
    elif update.message:
        await update.message.reply_text(
            prompt,
            parse_mode="HTML",
            reply_markup=_ex_cancel_reply_kb(),
        )


async def exchange_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline-навигация обмена: монета / сеть / направление / единица суммы."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("ex:"):
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 2:
        return
    action = parts[1]
    arg = parts[2] if len(parts) > 2 else ""

    if action == "cancel":
        from services.ux_copy import txt_exchange_cancelled

        context.user_data.clear()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        await _ex_send(
            update,
            txt_exchange_cancelled(),
            markup=await menu_for(update),
            edit=False,
        )
        return

    if not check_fsm_ttl(context):
        await _ex_send(
            update,
            "⏱ Время истекло. Начните заново.",
            markup=await menu_for(update),
            edit=False,
        )
        return

    if action == "back":
        if arg == "coins":
            await _ex_show_coins(update, context)
            return
        if arg == "after_coin":
            crypto = (context.user_data.get("crypto") or "").lower()
            if crypto == "usdt":
                from services.ux_copy import txt_usdt_network

                context.user_data["step"] = "choose_usdt_network"
                context.user_data.pop("direction", None)
                await _ex_send(update, txt_usdt_network(), markup=kb_ex_networks())
            else:
                await _ex_show_coins(update, context)
            return
        if arg == "dir":
            from services.ux_copy import COIN_NAMES, txt_direction

            crypto_l = context.user_data.get("crypto") or "btc"
            context.user_data.pop("direction", None)
            context.user_data.pop("amount_currency", None)
            context.user_data["step"] = "choose_operation"
            if crypto_l == "usdt":
                net = (context.user_data.get("network") or "").upper()
                title = f"Tether (USDT · {net})" if net else "Tether (USDT)"
                coin_btn = "USDT"
            else:
                title = f"{COIN_NAMES.get(crypto_l, crypto_l.upper())} ({crypto_l.upper()})"
                coin_btn = crypto_l.upper()
            rate = get_cached_rate(crypto_l, "buy") or CACHE.get(crypto_l, {}).get("price")
            await _ex_send(
                update,
                txt_direction(
                    crypto=crypto_l,
                    coin_title=title,
                    rate=rate,
                ),
                markup=kb_ex_direction(coin_btn),
            )
            return
        return

    if action == "coin":
        if arg not in ("BTC", "USDT", "TRX", "LTC"):
            return
        if context.user_data.get("step") not in (None, "choose_currency"):
            return
        if not context.user_data.get("fsm_started_at"):
            context.user_data["fsm_started_at"] = time.time()
        await _ex_after_coin_selected(update, context, arg)
        return

    if action == "net":
        if context.user_data.get("step") != "choose_usdt_network":
            return
        if arg not in _EX_NETWORKS:
            return
        await _ex_after_network(update, context, arg)
        return

    if action == "dir":
        if context.user_data.get("step") != "choose_operation":
            return
        if arg not in ("buy", "sell"):
            return
        await _ex_after_direction(update, context, arg)
        return

    if action == "unit":
        if context.user_data.get("step") != "enter_amount":
            return
        if arg not in ("rub", "coin"):
            return
        await _ex_after_unit(update, context, arg)
        return


# ============================================================
# 0. ТАЙМЕР ОЖИДАНИЯ ОПЛАТЫ
# ============================================================
# Авто-истечение заявок реализовано в services/order_expirer.py:
# каждые 10 сек проверяются заявки со статусом CREATED / AWAITING_CHECK / PENDING,
# у которых expires_at <= now(). Они переводятся в EXPIRED, у мерча отменяются
# (BUY + merchant_order_id), пользователю — блок 30 мин за неоплату.
# expires_at задаётся при создании заявки (по умолчанию 20 мин).

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def load_config():
    """Динамически перезагружает конфиг при каждом вызове."""
    importlib.reload(config_rates)
    return config_rates


def to_decimal(value) -> Decimal:
    """Безопасно конвертирует float/str в Decimal."""
    return Decimal(str(value))

# ============================================================
# 1. ГЛАВНОЕ МЕНЮ / ОТМЕНА
# ============================================================

def awaiting_payment_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["💸 Я оплатил"], ["🚫 Отмена"]], resize_keyboard=True)


async def resend_active_order_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Возвращает пользователя к незавершённой заявке вместо выхода в меню.

    Пока заявка ждёт оплаты (CREATED) или чека (AWAITING_CHECK), её нельзя
    «потерять» — например, командой /start. Покинуть экран оплаты можно только
    через явное подтверждение отмены.

    Возвращает True, если навигация перехвачена (заявка активна).
    """
    user = update.effective_user
    msg = update.message or (
        update.callback_query.message if update.callback_query else None
    )
    if not user or not msg:
        return False

    order = await get_active_order_by_user(user.id)
    if not order:
        return False

    status = order["status"]
    order_id = order["order_id"]

    if status == "CREATED":
        context.user_data["step"] = "awaiting_payment_confirmation"
        context.user_data["active_order_id"] = order_id
        from services.buy_payment_prompt import send_buy_payment_prompt

        await send_buy_payment_prompt(
            msg,
            dict(order),
            title="⚠️ <b>У вас есть незавершённая заявка</b>",
            extra_lines=[
                "✅ Если уже оплатили — нажмите «💸 Я оплатил» и отправьте чек.",
                "🚫 Выйти можно только через «🚫 Отмена» с подтверждением.",
            ],
        )
        return True

    if status == "AWAITING_CHECK":
        from services.receipt_instructions import receipt_request_message

        req_type = order.get("required_receipt_type") or 2
        context.user_data.clear()
        await msg.reply_text(
            receipt_request_message(str(order_id), int(req_type)),
            parse_mode="HTML",
            reply_markup=await menu_for(update),
        )
        return True

    return False


async def resend_active_order_menu_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Кнопка «Активная заявка» в главном меню."""
    if not await rate_limit_ok(update):
        return
    if await resend_active_order_prompt(update, context):
        return
    msg = update.message
    if msg:
        await msg.reply_text(
            "Сейчас нет активной заявки на оплату.\n"
            "Нажмите «Совершить обмен», чтобы создать новую.",
            reply_markup=await menu_for(update),
        )


async def cancel_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    user_id = update.effective_user.id
    step = context.user_data.get("step")

    order = await get_active_order_by_user(user_id)

    if not order:
        context.user_data.clear()
        from services.ux_copy import txt_action_cancelled

        await update.message.reply_text(
            txt_action_cancelled(),
            reply_markup=await menu_for(update),
            parse_mode="HTML",
        )
        return

    if step != "confirm_cancel":
        context.user_data["step"] = "confirm_cancel"

        keyboard = ReplyKeyboardMarkup(
            [["❗ Подтвердить отмену"], ["⬅️ Назад"]],
            resize_keyboard=True,
        )

        await update.message.reply_text(
            "⚠️ Вы уверены, что хотите отменить заявку?\n"
            "Это действие нельзя будет отменить.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

# ============================================================
# 2. ИСТОРИЯ
# ============================================================

async def exchange_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    from services.tg_emoji import e
    from services.ux_copy import block, txt_history

    user_id = update.effective_user.id
    active = await get_active_order_by_user(user_id)
    total = await get_completed_orders_count(user_id)
    last_orders = await get_completed_orders_by_user(user_id, limit=5)

    active_block = None
    if active:
        direction = "Покупка" if active["direction"] == "buy" else "Продажа"
        active_block = (
            f"{e('bell')} <b>Активная заявка</b> (новый обмен заблокирован):\n"
            + block(
                f"<code>{active['order_id']}</code> · {direction}",
                f"{float(active['crypto_amount']):.8f} {active['crypto']} · "
                f"{float(active['fiat_amount']):,.0f} ₽".replace(",", " "),
                "Отмена: «Совершить обмен» → «❗ Подтвердить отмену».",
            )
        )

    order_blocks: list[str] = []
    for o in last_orders:
        direction = "Покупка" if o["direction"] == "buy" else "Продажа"
        created = o["created_at"].strftime("%d.%m.%Y %H:%M") if o.get("created_at") else "—"
        cb_parts: list[str] = []
        applied = float(o.get("cashback_applied_rub") or 0)
        accrued_raw = o.get("cashback_accrued_rub")
        accrued = float(accrued_raw) if accrued_raw is not None else 0.0
        if applied > 0:
            cb_parts.append(f"Списано с баланса: {applied:,.0f} ₽".replace(",", " "))
        if accrued > 0 and o.get("direction") == "buy":
            cb_parts.append(f"На баланс: +{accrued:,.0f} ₽".replace(",", " "))
        elif o.get("direction") == "buy" and o.get("status") in ("PAID", "COMPLETED"):
            cb_parts.append("Кешбэк: не начислен")
        lines = [
            f"{e('calendar')} <b>{created}</b> · {direction} · {o['crypto'].upper()}",
            f"{e('ruble')} {float(o['fiat_amount']):,.0f} ₽ · "
            f"{float(o['crypto_amount']):.8f} {o['crypto']}".replace(",", " "),
            f"{e('link')} <code>{o['order_id']}</code>",
            f"{e('check')} Завершена",
        ]
        if cb_parts:
            lines.append(" · ".join(cb_parts))
        order_blocks.append(block(*lines))

    text = txt_history(
        total=total,
        shown=len(last_orders),
        active_block=active_block,
        order_blocks=order_blocks,
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ============================================================
# 3. ПОДДЕРЖКА
# ============================================================

async def exchange_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    from services.config_rates import community_chat_url
    from services.ux_copy import txt_support

    chat_url = support_chat_url()
    community_url = community_chat_url()
    markup = None
    support_btn = url_button("💬 Открыть чат на сайте", chat_url)
    if support_btn:
        markup = InlineKeyboardMarkup([[support_btn]])
    await update.message.reply_text(
        txt_support(chat_url=chat_url, community_url=community_url),
        parse_mode="HTML",
        reply_markup=markup,
    )


async def community_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    from services.config_rates import community_chat_url
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    url = community_chat_url()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👥 Вступить в focus чат", url=url)]])
    await update.message.reply_text(
        "👥 <b>Чат FocusPay</b>\n\n"
        "Общение, новости и вопросы по сервису — присоединяйтесь к нашему чату.",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ============================================================
# 4. ОТЗЫВЫ
# ============================================================

async def reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    from services.review_bonus import (
        review_invite_keyboard,
        review_invite_keyboard_for_user,
        review_invite_text,
        review_submission_block_message,
        user_can_submit_review,
    )

    user = update.effective_user
    if user and await user_can_submit_review(user.id):
        text = review_invite_text()
        kb = await review_invite_keyboard_for_user(user.id)
    else:
        from services.ux_copy import txt_reviews

        extra = None
        if user:
            extra = await review_submission_block_message(user.id)
        text = txt_reviews(extra=extra)
        kb = review_invite_keyboard(include_start=False)

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=kb,
    )


async def exchange_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    from services.ux_copy import txt_site

    await update.message.reply_text(
        txt_site(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

# ============================================================
# 5. КУРСЫ
# ============================================================

async def exchange_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return

    from services.payment_methods_display import build_rates_message_html

    keyboard = _rates_keyboard()
    try:
        text = await build_rates_message_html()
    except Exception:
        logger.exception("exchange_rate: failed to build rates message")
        text = f"<b>{USER_RATES_UNAVAILABLE}</b>"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================
# 6. ОБНОВЛЕНИЕ КУРСОВ
# ============================================================

LAST_REFRESH = {}


def _rates_keyboard() -> InlineKeyboardMarkup:
    from services import config_rates

    site = (getattr(config_rates, "PUBLIC_SITE_URL", None) or "https://focuspay.org").rstrip("/")
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_rates")],
    ]
    site_btn = url_button("🌐 Курсы на сайте", site)
    if site_btn:
        rows.append([site_btn])
    return InlineKeyboardMarkup(rows)


async def refresh_rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    query = update.callback_query
    if update.effective_chat and update.effective_chat.type != "private":
        await query.answer()
        return

    user_id = query.from_user.id
    now = time.time()
    last = LAST_REFRESH.get(user_id, 0)

    if now - last < 5:
        await query.answer("⏳ Подождите пару секунд...", show_alert=True)
        return

    LAST_REFRESH[user_id] = now
    await query.answer()

    from handlers.telegram_utils import edit_message_text_safe
    from services.payment_methods_display import build_rates_message_html

    keyboard = _rates_keyboard()
    try:
        text = await build_rates_message_html()
    except Exception:
        logger.exception("refresh_rates: failed to build rates message")
        text = f"<b>{USER_RATES_UNAVAILABLE}</b>"

    await edit_message_text_safe(
        query.edit_message_text,
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================
# 7. СТАРТ ОБМЕНА
# ============================================================

async def exchange_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    from services.menu import MENU_EXCHANGE, MENU_EXCHANGE_LEGACY

    text = (update.message.text or "").strip()
    if text not in (MENU_EXCHANGE, MENU_EXCHANGE_LEGACY):
        return

    user_id = update.effective_user.id

    from services.db import is_user_banned
    banned, _ban_reason, ban_type = await is_user_banned(user_id)
    if banned and ban_type != "soft":
        await update.message.reply_text(
            "🚫 Ваш аккаунт заблокирован.\n\nОбратитесь в поддержку для уточнения деталей.",
            reply_markup=await menu_for(update),
        )
        return
    # soft ban: в меню обмена пускаем (sell ок); BUY/реквизиты режем ниже

    from services.user_referral_attribution import seal_referral_gate

    await seal_referral_gate(user_id)

    # =====================================================
    # 🔎 ПРОВЕРКА АКТИВНОЙ ЗАЯВКИ
    # =====================================================
    order = await get_active_order_by_user(user_id)

    if order:
        if _payfast_cancellation_is_locked_for_order(order):
            await _reply_payfast_cancellation_locked(update, order)
            return
        context.user_data.clear()
        context.user_data["step"] = "confirm_cancel_order"
        context.user_data["active_order_id"] = order["order_id"]

        keyboard = ReplyKeyboardMarkup(
            [
                ["❗ Подтвердить отмену"],
                ["⬅️ Назад"]
            ],
            resize_keyboard=True
        )

        await update.message.reply_text(
            f"⚠️ <b>У вас уже есть активная заявка</b>\n\n"
            f"📄 <b>ID:</b> <code>{order['order_id']}</code>\n"
            f"💱 <b>Валюта:</b> {order['crypto'].upper()}\n"
            f"💰 <b>Сумма:</b> {order['fiat_amount']:,.2f} ₽\n"
            f"Хотите отменить её и создать новую?",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # =====================================================
    # 🚀 ЕСЛИ АКТИВНОЙ ЗАЯВКИ НЕТ — СТАРТ ОБМЕНА (inline UX)
    # =====================================================
    context.user_data.clear()
    context.user_data["fsm_started_at"] = time.time()
    context.user_data["step"] = "choose_currency"
    await _ex_show_coins(update, context, with_banner=True)



# ============================================================
# 8. ВЫБОР ВАЛЮТЫ
# ============================================================

async def exchange_choose_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    step = context.user_data.get("step")
    if step != "choose_currency":
        if exchange_input_is_stale(step):
            await update.message.reply_text(
                "Сессия обмена не начата. Нажмите «Совершить обмен».",
                reply_markup=await menu_for(update),
            )
        elif step == "choose_usdt_network":
            await update.message.reply_text("Сначала выберите сеть USDT кнопкой выше.")
        elif step == "choose_operation":
            await update.message.reply_text(
                "Валюта уже выбрана. Нажмите «Покупка» или «Продажа».",
            )
        else:
            await update.message.reply_text(
                "Валюта уже выбрана. Продолжите по шагам выше в чате.",
            )
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update)
        )
        return

    crypto = update.message.text.upper()
    if crypto not in ["BTC", "USDT", "LTC", "TRX"]:
        return

    await _ex_after_coin_selected(update, context, crypto)

# ============================================================
# 8.1 ВЫБОР СЕТИ USDT
# ============================================================

async def exchange_choose_usdt_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    if context.user_data.get("step") != "choose_usdt_network":
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    network = update.message.text.upper()
    if network not in _EX_NETWORKS:
        await update.message.reply_text("❌ Выберите сеть кнопкой.")
        return

    await _ex_after_network(update, context, network)


# ============================================================
# 9. ВЫБОР ОПЕРАЦИИ
# ============================================================

async def exchange_operation_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    if context.user_data.get("step") != "choose_operation":
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update)
        )
        return

    text = update.message.text
    crypto = context.user_data.get("crypto")
    if not crypto:
        return
    crypto_upper = crypto.upper()

    # Старые подписи с эмодзи — для пользователей с открытой клавиатурой до обновления
    legacy_buy = f"🔶 {buy_operation_label(crypto_upper)}"
    legacy_sell = f"🔷 {sell_operation_label(crypto_upper)}"
    if text in (buy_operation_label(crypto_upper), legacy_buy):
        direction = "buy"
    elif text in (sell_operation_label(crypto_upper), legacy_sell):
        direction = "sell"
    else:
        return

    if direction == "buy":
        from services.buyer_access_guards import (
            format_soft_ban_no_requisites_message,
            soft_ban_blocks_buy_requisites,
        )

        if await soft_ban_blocks_buy_requisites(update.effective_user.id):
            await update.message.reply_text(
                format_soft_ban_no_requisites_message(),
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return

    await _ex_after_direction(update, context, direction)





# ============================================================
# 10. ВВОД СУММЫ
# ============================================================

async def exchange_enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    is_amount_flow = (
        text == "Указать сумму в Рублях"
        or re.match(r"^Указать сумму в (BTC|USDT|TRX|LTC)$", text)
        or re.match(r"^\d+([.,]\d+)?$", text.replace(",", "."))
    )

    if context.user_data.get("step") != "enter_amount":
        if is_amount_flow:
            if await exchange_repeat_input_reply(update, context, kind="amount"):
                return
            if exchange_input_is_stale(context.user_data.get("step")):
                agent_log(
                    "exchange_flow.py:enter_amount",
                    "stale: step not enter_amount",
                    {"step": context.user_data.get("step"), "text": text[:40]},
                    hypothesis_id="B",
                )
                await exchange_stale_session_reply(update, context)
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    cfg = load_config()

    crypto = context.user_data.get("crypto")
    direction = context.user_data.get("direction")
    if not crypto or not direction:
        await update.message.reply_text(
            "❌ Произошла ошибка. Начните обмен заново.",
            reply_markup=await menu_for(update),
        )
        context.user_data.clear()
        return

    crypto_upper = crypto.upper()

    limits = cfg.AMOUNT_LIMITS.get(crypto, {})
    min_crypto = to_decimal(limits["min_crypto"])
    max_crypto = to_decimal(limits["max_crypto"])

    keyboard_cancel = ReplyKeyboardMarkup([["🚫 Отмена"]], resize_keyboard=True)

    # ---------- выбор валюты ввода (до пересчёта курса) ----------
    if text in ("Указать сумму в Рублях", f"Указать сумму в {crypto_upper}"):
        rate_raw = context.user_data.get("last_rate")
        if rate_raw is None:
            rate_raw = get_cached_rate(crypto, direction)
        if rate_raw is None:
            await update.message.reply_text(
                USER_RATES_UNAVAILABLE,
                reply_markup=await menu_for(update),
            )
            return
        effective_rate = Decimal(str(rate_raw))
        context.user_data["last_rate"] = effective_rate
        market_raw = CACHE.get(crypto, {}).get("price")
        if direction == "buy" and market_raw:
            need_price = await get_need_price(crypto)
            if text == "Указать сумму в Рублях" and need_price is None:
                await update.message.reply_text(
                    USER_NEED_RATES_UNAVAILABLE,
                    reply_markup=await menu_for(update),
                )
                return
            market_for_limits = Decimal(str(need_price or market_raw))
            min_fiat = (min_crypto * market_for_limits).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            max_fiat = (max_crypto * market_for_limits).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            rub_hint = (
                "\n\nℹ️ Итоговую сумму к оплате вы увидите на следующем шаге."
            )
        else:
            min_fiat = (min_crypto * effective_rate).quantize(Decimal("0.01"))
            max_fiat = (max_crypto * effective_rate).quantize(Decimal("0.01"))
            rub_hint = ""

        if text == "Указать сумму в Рублях":
            from services.ux_copy import txt_amount_prompt

            context.user_data["amount_currency"] = "rub"
            await update.message.reply_text(
                txt_amount_prompt(
                    crypto=crypto,
                    direction=direction,
                    unit="rub",
                    min_label=f"{min_fiat} ₽",
                    max_label=f"{max_fiat} ₽",
                )
                + rub_hint,
                parse_mode="HTML",
                reply_markup=keyboard_cancel,
            )
        else:
            from services.ux_copy import txt_amount_prompt

            context.user_data["amount_currency"] = "crypto"
            await update.message.reply_text(
                txt_amount_prompt(
                    crypto=crypto,
                    direction=direction,
                    unit="coin",
                    min_label=f"{fmt_crypto(min_crypto, crypto)} {crypto_upper}",
                    max_label=f"{fmt_crypto(max_crypto, crypto)} {crypto_upper}",
                ),
                parse_mode="HTML",
                reply_markup=keyboard_cancel,
            )
        return

    # =====================================================
    # ✅ ЧИСЛОВОЙ ВВОД
    # =====================================================
    try:
        effective_rate, changed = check_rate_change(context, crypto, direction)
    except (ValueError, ArithmeticError):
        await update.message.reply_text(
            USER_RATES_UNAVAILABLE,
            reply_markup=await menu_for(update),
        )
        return

    market_price = CACHE.get(crypto, {}).get("price")
    if market_price is None:
        try:
            await ensure_rates_cache()
        except RatesUnavailableError:
            pass
        market_price = CACHE.get(crypto, {}).get("price")
    if market_price is None:
        await update.message.reply_text(
            USER_RATES_UNAVAILABLE,
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    if direction == "buy":
        served = get_cached_buy_market(crypto)
        if served is None:
            await update.message.reply_text(
                USER_RATES_UNAVAILABLE,
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return
        market_rate = Decimal(str(served))
    else:
        market_rate = Decimal(str(market_price))

    if direction == "sell":
        from services.runtime_settings import sell_discount

        need_price = await get_need_price(crypto)
        if need_price:
            market_rate = Decimal(str(need_price))
        effective_rate = market_rate * Decimal(str(sell_discount()))

    min_fiat = (min_crypto * effective_rate).quantize(Decimal("0.01"))
    max_fiat = (max_crypto * effective_rate).quantize(Decimal("0.01"))

    raw_text = text.replace(",", ".")

    try:
        value = Decimal(raw_text)
    except Exception:
        from services.ux_copy import txt_bad_amount

        await update.message.reply_text(txt_bad_amount(), parse_mode="HTML")
        return

    amount_currency = context.user_data.get("amount_currency")
    if not amount_currency:
        agent_log(
            "exchange_flow.py:enter_amount",
            "missing amount_currency",
            {"step": context.user_data.get("step"), "text": text[:40]},
            hypothesis_id="C",
        )
        await update.message.reply_text(
            "❗ Сначала выберите валюту ввода.",
            parse_mode="HTML",
        )
        return

    # ===== ОГРАНИЧЕНИЕ DECIMAL-ОВ =====
    if amount_currency == "rub":
        # 🔹 рубли → максимум 2 знака
        if value.as_tuple().exponent < -2:
            from services.ux_copy import txt_bad_amount

            await update.message.reply_text(txt_bad_amount(), parse_mode="HTML")
            return

    else:
        # 🔹 крипта
        crypto = context.user_data.get("crypto")
        max_decimals = CRYPTO_DECIMALS.get(crypto, 8)

        if value.as_tuple().exponent < -max_decimals:
            await update.message.reply_text(
                f"❗ Для {crypto.upper()} можно указать не более {max_decimals} знаков после точки."
            )
            return

    # =====================================================
    # ✅ РАСЧЁТ
    # =====================================================
    if amount_currency == "rub":
        base_fiat = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if direction == "buy":
            need_price = await get_need_price(crypto)
            if need_price is None:
                await update.message.reply_text(
                    USER_NEED_RATES_UNAVAILABLE,
                    reply_markup=await menu_for(update),
                )
                return
            from services.runtime_settings import buy_markup as _buy_markup

            try:
                buy_markup_factor = Decimal(
                    str(_buy_markup(manual=False, amount_rub=float(base_fiat)))
                )
                crypto_amount, fiat_amount, quoted_rate = quote_buy_rub_base(
                    base_fiat=base_fiat,
                    rapira=market_rate,
                    coingecko=Decimal(str(need_price)),
                    markup=buy_markup_factor,
                )
                effective_rate = quoted_rate
            except ValueError:
                await update.message.reply_text(
                    USER_NEED_RATES_UNAVAILABLE,
                    reply_markup=await menu_for(update),
                )
                return
        else:
            fiat_amount = base_fiat
            crypto_amount = Decimal(str(fiat_amount / effective_rate))

    else:
        # --- пользователь фиксирует крипту ---
        crypto_amount = Decimal(str(value))
        raw_fiat = crypto_amount * market_rate
        if direction == "buy":
            from services.runtime_settings import buy_markup as _buy_markup

            buy_markup_factor = Decimal(
                str(_buy_markup(manual=False, amount_rub=float(raw_fiat)))
            )
            fiat_amount = (raw_fiat * buy_markup_factor).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            effective_rate = market_rate * buy_markup_factor
        else:
            commission_factor = effective_rate / market_rate
            fiat_amount = (raw_fiat * commission_factor).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

    context.user_data.pop("buy_send_fee_rub", None)
    context.user_data.pop("buy_btc_fee_rate_sat_vb", None)
    if direction == "buy":
        from services.crypto_network_fee import apply_buy_client_send_fee

        btc_rate = None
        if crypto.split("_")[0].lower() == "btc":
            from services.btc_fee_rate import btc_fee_rate_sat_vb

            btc_rate = await btc_fee_rate_sat_vb()
        fiat_amount, send_fee = apply_buy_client_send_fee(
            fiat_amount,
            crypto,
            usdt_rub=float(market_rate),
            btc_fee_rate_sat_vb=btc_rate,
        )
        if send_fee > 0:
            context.user_data["buy_send_fee_rub"] = send_fee
            if btc_rate:
                context.user_data["buy_btc_fee_rate_sat_vb"] = btc_rate

    # ---------- лимиты ----------
    if crypto_amount < min_crypto:
        from services.ux_copy import txt_amount_below_min

        await update.message.reply_text(
            txt_amount_below_min(
                coin=crypto_upper,
                minimum=f"{fmt_crypto(min_crypto, crypto)} {crypto_upper}",
            ),
            parse_mode="HTML",
        )
        return

    if crypto_amount > max_crypto:
        from services.ux_copy import txt_amount_above_max

        await update.message.reply_text(
            txt_amount_above_max(
                coin=crypto_upper,
                maximum=f"{fmt_crypto(max_crypto, crypto)} {crypto_upper}",
            ),
            parse_mode="HTML",
        )
        return

    if changed:
        await update.message.reply_text(
            "⚠️ Условия обмена изменились, сумма пересчитана.",
            parse_mode="HTML"
        )

    # =====================================================
    # ✅ СОХРАНЯЕМ ОБА ЗНАЧЕНИЯ
    # =====================================================
    context.user_data["crypto_amount"] = crypto_amount
    context.user_data["fiat_amount"] = fiat_amount
    context.user_data["effective_rate"] = effective_rate

    if direction == "buy":
        await _proceed_buy_after_amount(update, context)
    else:
        from services.ux_copy import txt_ask_sell_requisites

        context.user_data["step"] = "awaiting_requisites"
        await update.message.reply_text(
            txt_ask_sell_requisites(),
            parse_mode="HTML",
            reply_markup=keyboard_cancel
        )


# ============================================================
# 10.04 ВЫБОР СКИДКИ НА ОБМЕН (BUY)
# ============================================================
async def exchange_choose_exchange_discount(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not await rate_limit_ok(update):
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if context.user_data.get("step") != "choose_exchange_discount":
        if text == SKIP_EXCHANGE_DISCOUNT or text.startswith("🏷 "):
            if await exchange_repeat_input_reply(update, context, kind="discount"):
                return
            if exchange_input_is_stale(context.user_data.get("step")):
                await exchange_stale_session_reply(update, context)
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update),
        )
        context.user_data.clear()
        return

    from services.exchange_discount_db import preview_discount_application

    user_id = update.effective_user.id
    options = context.user_data.get("exchange_discount_options") or {}
    if text == SKIP_EXCHANGE_DISCOUNT:
        context.user_data.pop("exchange_discount_id", None)
        context.user_data.pop("exchange_discount_applied", None)
    elif text in options:
        disc_id = options[text]
        fiat_amount = context.user_data.get("fiat_amount")
        crypto_amount = context.user_data.get("crypto_amount")
        effective_rate = context.user_data.get("effective_rate")
        _, _, applied = await preview_discount_application(
            disc_id,
            user_id,
            float(fiat_amount),
            float(crypto_amount),
            float(effective_rate),
            _buy_crypto_sym(context),
        )
        context.user_data["exchange_discount_id"] = disc_id
        context.user_data["exchange_discount_applied"] = applied
    else:
        await update.message.reply_text(
            "❗ Выберите скидку из списка или «Без скидки на обмен».",
        )
        return

    context.user_data.pop("exchange_discount_options", None)
    await _proceed_buy_balance_or_payment(update, context)


async def exchange_exchange_discount_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if context.user_data.get("uref_wd"):
        return
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text != SKIP_EXCHANGE_DISCOUNT and not text.startswith("🏷 "):
        return
    if not await rate_limit_ok(update):
        return
    await exchange_choose_exchange_discount(update, context)


# ============================================================
# 10.05 ВЫБОР СКИДКИ БАЛАНСОМ (BUY)
# ============================================================
async def exchange_choose_balance_discount(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not await rate_limit_ok(update):
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if context.user_data.get("step") != "choose_balance_discount":
        if text in (APPLY_BALANCE_DISCOUNT, SKIP_BALANCE_DISCOUNT):
            if await exchange_repeat_input_reply(update, context, kind="balance"):
                return
            if exchange_input_is_stale(context.user_data.get("step")):
                await exchange_stale_session_reply(update, context)
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update),
        )
        context.user_data.clear()
        return

    from services.user_cashback_db import set_use_cashback_on_next

    user_id = update.effective_user.id
    if text == APPLY_BALANCE_DISCOUNT:
        await set_use_cashback_on_next(user_id, True)
    elif text == SKIP_BALANCE_DISCOUNT:
        await set_use_cashback_on_next(user_id, False)
    else:
        await update.message.reply_text(
            "❗ Выберите: применить баланс как скидку или оплатить без баланса.",
        )
        return

    context.user_data["step"] = "choose_payment_method"
    keyboard_payment = ReplyKeyboardMarkup(
        [["Карта", "СБП"], ["🚫 Отмена"]],
        resize_keyboard=True,
    )
    disc_applied = float(context.user_data.get("exchange_discount_applied") or 0)
    fiat_amount = float(context.user_data.get("fiat_amount") or 0)
    pay_hint = ""
    if disc_applied > 0:
        pay_hint = (
            f"\n\n🏷 С учётом скидки к оплате ~"
            f"<b>{max(1.0, fiat_amount - disc_applied):,.2f}</b> ₽."
            .replace(",", " ")
        )
    await update.message.reply_text(
        f"💬 Куда удобнее оплатить?{pay_hint}",
        parse_mode="HTML",
        reply_markup=keyboard_payment,
    )


# ============================================================
# 10.1 ВЫБОР СПОСОБА ОПЛАТЫ (ТОЛЬКО BUY: КАРТА / СБП)
# ============================================================
async def exchange_choose_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    pay_kind = normalize_payment_method(text)

    if context.user_data.get("step") != "choose_payment_method":
        if pay_kind is not None:
            if await exchange_repeat_input_reply(update, context, kind="payment"):
                return
            if exchange_input_is_stale(context.user_data.get("step")):
                await exchange_stale_session_reply(update, context)
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    if pay_kind == "card":
        context.user_data["sub_token"] = "CARDRUB"  # nosec B105
    elif pay_kind == "sbp":
        context.user_data["sub_token"] = "SBPRUB"  # nosec B105
    else:
        await update.message.reply_text(
            "❗ Выберите способ оплаты: нажмите <b>Карта</b> или <b>СБП</b>.",
            parse_mode="HTML",
        )
        return

    await _prompt_buy_amount_confirm(update, context)


# ============================================================
# 10.15 ПОДТВЕРЖДЕНИЕ СУММЫ (BUY) ПЕРЕД КОШЕЛЬКОМ
# ============================================================
async def exchange_confirm_buy_amount(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await rate_limit_ok(update):
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if context.user_data.get("step") != "confirm_buy_amount":
        if text == CONFIRM_BUY_AMOUNT:
            if await exchange_repeat_input_reply(update, context, kind="amount"):
                return
            if await exchange_repeat_input_reply(update, context, kind="payment"):
                return
            if await exchange_repeat_input_reply(update, context, kind="balance"):
                return
            if await exchange_repeat_input_reply(update, context, kind="discount"):
                return
            if exchange_input_is_stale(context.user_data.get("step")):
                await exchange_stale_session_reply(update, context)
        return

    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update),
        )
        context.user_data.clear()
        return

    if text != CONFIRM_BUY_AMOUNT:
        await update.message.reply_text(
            "❗ Подтвердите сумму: нажмите «✅ Да, устраивает» или «🚫 Отмена».",
        )
        return

    crypto = context.user_data.get("crypto")
    direction = context.user_data.get("direction") or "buy"
    _, changed = check_rate_change(context, crypto, direction)
    if changed:
        await update.message.reply_text(
            "⚠️ Условия обмена изменились. Пожалуйста, начните обмен заново.",
            reply_markup=await menu_for(update),
        )
        context.user_data.clear()
        return

    await _ask_buy_wallet(update, context)


async def exchange_confirm_buy_amount_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Прямой хендлер «✅ Да, устраивает» (block=True)."""
    if context.user_data.get("uref_wd"):
        return
    if not update.message or not update.message.text:
        return
    if update.message.text.strip() != CONFIRM_BUY_AMOUNT:
        return
    if not await rate_limit_ok(update):
        return
    await exchange_confirm_buy_amount(update, context)


# ============================================================
# 11 ВВОД РЕКВИЗИТОВ + СОЗДАНИЕ СДЕЛКИ (СРАЗУ)
# ============================================================

async def exchange_enter_requisites(update, context):
    if not await rate_limit_ok(update):
        return
    step = context.user_data.get("step")
    if step != "awaiting_requisites":
        agent_log(
            "exchange_flow.py:enter_requisites",
            "skip: wrong step",
            {"step": step, "direction": context.user_data.get("direction")},
            hypothesis_id="E",
        )
        return
    agent_log(
        "exchange_flow.py:enter_requisites",
        "processing wallet/requisites",
        {"direction": context.user_data.get("direction"), "fiat": context.user_data.get("fiat_amount")},
        hypothesis_id="E",
    )

    # ✅ TTL
    if not check_fsm_ttl(context):
        await update.message.reply_text(
            "⏱ Время истекло. Начните заново.",
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    text = update.message.text.strip()

    crypto = context.user_data.get("crypto")
    direction = context.user_data.get("direction")

    crypto_amount = context.user_data.get("crypto_amount")
    fiat_amount = context.user_data.get("fiat_amount")
    effective_rate = context.user_data.get("effective_rate")

    if not crypto or not direction or crypto_amount is None:
        await update.message.reply_text("❌ Произошла ошибка. Начните заново.")
        context.user_data.clear()
        return

    network = context.user_data.get("network")

    if crypto == "usdt" and network:
        crypto_upper = f"USDT_{network.upper()}"
    else:
        crypto_upper = crypto.upper()
    cfg = load_config()

    # =====================================================
    # 🔴 SELL — ПРОДАЖА КРИПТЫ (РУЧНАЯ)
    # =====================================================
    if direction == "sell":
        from services.wallet_validation import validate_sell_fiat_requisites

        try:
            validate_sell_fiat_requisites(text)
        except ValueError as e:
            await update.message.reply_text(f"❗ {e}", parse_mode="HTML")
            return

        market_price = Decimal(str(CACHE.get(crypto, {}).get("price")))
        if not market_price:
            await update.message.reply_text(
                USER_RATES_UNAVAILABLE,
                reply_markup=await menu_for(update)
            )
            context.user_data.clear()
            return

        payout_rate = Decimal(str(context.user_data.get("effective_rate") or 0))
        if payout_rate <= 0:
            await update.message.reply_text(
                "⚠️ Курс ЦБ временно недоступен.",
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return
        fiat_amount = (crypto_amount * payout_rate).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        network = context.user_data.get("network")
        if not network:
            network = "mainnet"

        user_id = update.effective_user.id
        if user_id not in getattr(config_rates, "TELEGRAM_ADMIN_IDS", []):
            n = await count_orders_by_user_in_last_minutes(user_id, 15)
            if n >= 3:
                await update.message.reply_text(
                    "⚠️ Вы создали слишком много заявок за последнее время. Попробуйте позже.",
                    reply_markup=await menu_for(update),
                )
                context.user_data.clear()
                return

        if await _block_requisites_if_no_shift(
            update,
            context,
            user_id,
            direction="sell",
        ):
            return

        async with SEM_CREATE_ORDER:
            order_id = None
            order_result = None
            for _ in range(3):
                order_id = str(uuid.uuid4().int)[:8]
                try:
                    order_result = await create_order_with_promo(
                        order_id=order_id,
                        user_id=update.effective_user.id,
                        crypto=crypto_upper,
                        direction="sell",
                        crypto_amount=float(crypto_amount),
                        fiat_amount=float(fiat_amount),
                        rate=float(payout_rate),
                        requisites=text,
                        status="OPERATOR_PENDING",
                        ttl_seconds=86400,
                    )
                    break
                except asyncpg.UniqueViolationError:
                    continue
            else:
                await update.message.reply_text(
                    "❌ Не удалось создать заявку. Попробуйте ещё раз.",
                    reply_markup=await menu_for(update),
                )
                context.user_data.clear()
                return

            payout_fiat = Decimal(str(order_result["fiat_amount"]))
            promo_line = ""
            if order_result["promo_applied"]:
                note = promo_bonus_note(
                    bonus_percent=order_result.get("promo_bonus_percent"),
                    bonus_fixed_rub=order_result.get("promo_bonus_fixed_rub"),
                )
                promo_line = f"{note}\n" if note else ""

            keyboard = sell_created_keyboard()
            chat_url = telegram_web_url(support_chat_url())
            if chat_url:
                support_bit = (
                    f"Напишите в {telegram_href('чат на сайте', chat_url)} "
                    f"или оператору @focus_operator"
                )
            else:
                support_bit = "Напишите оператору @focus_operator"
            from services.payin_requisite_rail import frozen_subsidy_cap_rub, triangle_band_notice
            from services.runtime_settings import triangle_sell_bonus_pct

            bonus_pct = Decimal(str(triangle_sell_bonus_pct()))
            card_nominal = payout_fiat
            if bonus_pct > 0:
                card_nominal = (payout_fiat * (Decimal("1") + bonus_pct / Decimal("100"))).quantize(
                    Decimal("0.01")
                )
            band_notice = triangle_band_notice(
                due=payout_fiat,
                nominal=card_nominal,
                cap=frozen_subsidy_cap_rub(card_nominal),
            )
            summary = (
                f"✅ <b>Заявка на продажу передана оператору</b>\n\n"
                f"🆔 <b>ID:</b> <code>{order_id}</code>\n\n"
                f"💱 Отправите: <b>{fmt_crypto(crypto_amount, crypto)} {crypto_upper}</b>\n"
                f"💰 Получите: <b>{payout_fiat} ₽</b>\n"
                f"{band_notice}\n"
                f"{promo_line}"
                f"📬 Рубли на: <code>{html.escape(text)}</code>\n\n"
                f"{support_bit} — он выдаст адрес для перевода крипты "
                f"и отправит рубли после поступления."
            )
            try:
                await update.message.reply_text(
                    summary,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            except Exception:
                exchange_fsm_logger.exception(
                    "sell confirm message failed order=%s", order_id
                )
                try:
                    await update.message.reply_text(
                        f"✅ Заявка <code>{html.escape(str(order_id))}</code> передана оператору.",
                        parse_mode="HTML",
                        reply_markup=await menu_for(update),
                    )
                except Exception:
                    exchange_fsm_logger.exception(
                        "sell confirm fallback failed order=%s", order_id
                    )
            try:
                from services.db import get_order
                from services.order_ops_notify import notify_ops_order

                created = await get_order(order_id)
                if created:
                    await notify_ops_order(
                        "created",
                        dict(created),
                        bot=context.bot,
                        username=update.effective_user.username,
                        note="Продажа · клиент на оператора",
                    )
            except Exception:
                exchange_fsm_logger.exception("sell ops notify failed order=%s", order_id)
            context.user_data.clear()
        return

    # =====================================================
    # 🟢 BUY — ПОКУПКА
    # =====================================================
    from services.wallet_validation import validate_buy_wallet

    try:
        validate_buy_wallet(crypto, network, text)
    except ValueError as e:
        await update.message.reply_text(f"❗ {e}", parse_mode="HTML")
        return

    try:
        crypto_amount = to_decimal(crypto_amount)
        fiat_amount = to_decimal(fiat_amount)
        effective_rate = Decimal(str(effective_rate))
    except Exception:
        await update.message.reply_text("❌ Ошибка в расчётах.")
        context.user_data.clear()
        return

    current_rate, changed = check_rate_change(context, crypto, direction)
    if changed:
        await update.message.reply_text(
            "⚠️ Условия обмена изменились. Пожалуйста, начните обмен заново.",
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    if context.user_data.get("amount_currency") == "crypto":
        fiat_amount = int(fiat_amount.to_integral_value(rounding=ROUND_CEILING))
    else:
        fiat_amount = int(fiat_amount.to_integral_value(rounding=ROUND_HALF_UP))
    user_id = update.effective_user.id
    cfg = load_config()
    callback_url = (cfg.MERCHANT.get("callback_url") or "").strip()
    if not callback_url:
        await update.message.reply_text("❌ Не настроен callback_url мерчанта.")
        context.user_data.clear()
        return

    if user_id not in getattr(config_rates, "TELEGRAM_ADMIN_IDS", []):
        n = await count_orders_by_user_in_last_minutes(user_id, 15)
        if n >= 3:
            await update.message.reply_text(
                "⚠️ Вы создали слишком много заявок за последнее время. Попробуйте позже.",
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return

        from services.buyer_access_guards import (
            check_cancel_cooldown,
            format_cooldown_message,
        )
        from services.db import get_buyer_payfast_conversion

        rem = await check_cancel_cooldown(user_id)
        if rem is not None:
            conv = await get_buyer_payfast_conversion(user_id)
            await update.message.reply_text(
                format_cooldown_message(rem, conv),
                parse_mode="HTML",
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return

        from services.account_review import ensure_account_review_or_block
        from services.buyer_access_guards import (
            format_soft_ban_no_requisites_message,
            soft_ban_blocks_buy_requisites,
        )

        if await soft_ban_blocks_buy_requisites(user_id):
            await update.message.reply_text(
                format_soft_ban_no_requisites_message(),
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return

        tg_user = update.effective_user
        premium = None
        if tg_user is not None:
            premium = getattr(tg_user, "is_premium", None)
            if premium is not None:
                premium = bool(premium)
        allowed, review_msg = await ensure_account_review_or_block(
            user_id=user_id,
            bot=context.bot,
            username=tg_user.username if tg_user else None,
            first_name=tg_user.first_name if tg_user else None,
            wallet=text,
            is_premium=premium,
            fiat_amount=fiat_amount,
            crypto=crypto_upper,
            crypto_amount=float(crypto_amount) if crypto_amount is not None else None,
            network=network,
            amount_currency=context.user_data.get("amount_currency"),
        )
        if not allowed:
            await update.message.reply_text(
                review_msg or "⚠️ Требуется проверка аккаунта.",
                parse_mode="HTML",
                reply_markup=await menu_for(update),
            )
            context.user_data.clear()
            return

    sub_token = context.user_data.get("sub_token") or "CARDRUB"
    context.user_data["buy_wallet"] = text
    context.user_data["fiat_amount"] = fiat_amount

    await update.message.reply_text("⏳ Ищем реквизиты для оплаты, подождите…")

    created = await _create_payin_rail_and_show(
        update,
        context,
        user_id=user_id,
        crypto=crypto,
        crypto_upper=crypto_upper,
        crypto_amount=crypto_amount,
        fiat_amount=fiat_amount,
        effective_rate=effective_rate,
        wallet=text,
        sub_token=sub_token,
        accept_round_up=False,
    )
    if created or created is None:
        return
    if await _offer_payin_round_if_close(
        update,
        context,
        user_id=user_id,
        fiat_amount=int(fiat_amount),
        sub_token=sub_token,
    ):
        return

    await _run_merchant_payin_flow(
        update,
        context,
        user_id=user_id,
        fiat_amount=fiat_amount,
        sub_token=sub_token,
        crypto=crypto,
        crypto_upper=crypto_upper,
        crypto_amount=crypto_amount,
        effective_rate=effective_rate,
        wallet=text,
        callback_url=callback_url,
    )
    return



# ============================================================
# 12 ПОДТВЕРЖДЕНИЕ ОПЛАТЫ
# ============================================================

async def exchange_confirm_payment(update, context):
    if not await rate_limit_ok(update):
        return
    if update.message.text != "💸 Я оплатил":
        return

    user_id = update.effective_user.id
    order = await get_active_order_by_user(user_id)

    if not order:
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Активная заявка не найдена или истекла.",
            reply_markup=await menu_for(update)
        )
        return

    direction = order["direction"]

    # =====================================================
    # BUY — всегда запрашиваем PDF; видео только если мерч отклонил PDF (webhook status_check=3)
    # =====================================================
    if direction == "buy":
        if _payfast_requisites_closed_for_order(dict(order)):
            await _reply_payfast_requisites_closed(update, dict(order))
            return
        req_type = 2
        if not await update_order_to_awaiting_check(order["order_id"], required_receipt_type=req_type):
            await update.message.reply_text(
                "❌ Не удалось перевести заявку в ожидание чека. "
                "Обновите историю и попробуйте снова.",
                reply_markup=await menu_for(update),
            )
            return
        from services.order_ops_notify import notify_ops_order
        from services.receipt_instructions import receipt_request_message

        refreshed = await get_order(order["order_id"]) or order
        from services.db import mark_ops_alert_once

        if await mark_ops_alert_once(order["order_id"], "awaiting_receipt_notify"):
            await notify_ops_order(
                "awaiting_receipt",
                dict(refreshed),
                bot=update.get_bot(),
                username=update.effective_user.username if update.effective_user else None,
            )

        context.user_data.clear()
        await update.message.reply_text(
            receipt_request_message(str(order["order_id"]), req_type),
            reply_markup=await menu_for(update),
            parse_mode="HTML",
        )
        return

    # =====================================================
    # SELL — ручная обработка
    # =====================================================
    if direction == "sell":
        if not await update_order_status(order["order_id"], "PENDING"):
            logger.warning(
                "sell PENDING transition rejected order=%s status=%s",
                order["order_id"],
                order.get("status"),
            )
            await update.message.reply_text(
                "⚠️ Не удалось передать заявку на выплату. Напишите оператору.",
                reply_markup=await menu_for(update),
            )
            return

        from services.callback_signatures import sign_order
        from services.order_ops_notify import notify_ops_order

        refreshed = await get_order(order["order_id"]) or order
        await notify_ops_order(
            "awaiting_payout",
            dict(refreshed),
            bot=update.get_bot(),
            username=update.effective_user.username if update.effective_user else None,
            pay_signature=sign_order(order["order_id"]),
            sell=True,
        )

        context.user_data.clear()
        await update.message.reply_text(
            "✅ Перевод отправлен на проверку.\n"
            "Ожидайте выплаты.",
            reply_markup=await menu_for(update)
        )


# ============================================================
# 13 СОЗДАНИЕ PAYIN (новый мерчант: HMAC, POST /create_order_payin)
# ============================================================
async def create_payin_order(
    *,
    order_id: str,
    user_id: int,
    fiat_amount: Decimal,
    callback_url: str,
    sub_token: str | None = None,
) -> dict:
    """
    Создаёт заявку payin у мерча. fingerprint — string (Telegram user id), callback_url обязателен.
    sub_token: CARDRUB / SBPRUB — способ оплаты; если не передан, берётся из конфига.
    """
    cfg = load_config()
    base_url = (cfg.MERCHANT.get("base_url") or "").rstrip("/")
    api_key = cfg.MERCHANT.get("api_key") or ""
    secret_key = cfg.MERCHANT.get("secret_key") or ""
    if sub_token is None:
        sub_token = cfg.MERCHANT.get("sub_token") or "CARDRUB"

    if not base_url or not api_key or not secret_key:
        raise ValueError("В config_rates.MERCHANT задайте base_url, api_key, secret_key")

    callback_url = (callback_url or "").strip()
    if "{WEBHOOK_SECRET}" in callback_url:
        callback_url = callback_url.replace("{WEBHOOK_SECRET}", "")
    if "?token=" in callback_url or callback_url.rstrip("/").endswith("token="):
        callback_url = callback_url.split("?")[0].rstrip("/")
    if "{ORDER_ID}" in callback_url:
        callback_url = callback_url.replace("{ORDER_ID}", str(order_id))
    elif callback_url.startswith("https://webhook.focuspay.org"):
        callback_url = f"{callback_url.rstrip('/')}/{order_id}"

    payload = {
        "token": "P2P",
        "sub_token": sub_token,
        "fingerprint": str(user_id),
        "client_transaction_id": str(order_id),
        "amount": int(Decimal(fiat_amount).to_integral_value()),
        "callback_url": callback_url,
    }
    from services.merchant_client import MERCHANT_HTTP_TIMEOUT, merchant_post

    try:
        return await merchant_post(
            "/create_order_payin",
            payload,
            timeout=MERCHANT_HTTP_TIMEOUT,
        )
    except asyncio.TimeoutError:
        merchant_logger.warning("create_payin_order timeout order_id=%s", order_id)
        return {"status_pending": "error", "error": "timeout"}
    except aiohttp.ClientError as e:
        merchant_logger.warning("create_payin_order failed order_id=%s: %s", order_id, e)
        return {"status_pending": "error", "error": str(e)}


# ============================================================
# 13.1 ПРИКРЕПЛЕНИЕ ЧЕКА (POST /payin_set_check)
# ============================================================
# API: body { uuid — id заявки в системе мерча (uuid_system), file — ссылка на файл }.
# Подпись: та же HMAC (X-API-Key, X-Timestamp, X-Signature). 200 — чек принят, 400 — неверные данные, 500 — ошибка на их стороне.
# file — только наш публичный URL (/receipt/...), без токена бота.
def _is_retryable_payin_error(body: dict) -> bool:
    """Временная ошибка Payfast (повторить позже), а не отказ по чеку.

    Payfast §5.4: 500 {"status_pending":"error_server","error":"Попробуйте позже"}.
    На практике встречается и status_pending=error с текстом «Попробуйте позже».
    """
    if not isinstance(body, dict):
        return False
    sp = str(body.get("status_pending") or "").lower()
    if "server" in sp:
        return True
    text = " ".join(
        str(body.get(k) or "") for k in ("error", "err", "msg")
    ).lower()
    markers = ("позже", "повторите", "try later", "later", "timeout", "http 5")
    return any(m in text for m in markers)


async def payin_set_check(uuid_merchant: str, file_url: str) -> dict:
    """Отправляет мерчу ссылку на чек. uuid_merchant = uuid_system (ID заявки у мерча). file_url = наш GET /receipt/... без токена."""
    payload = {"uuid": uuid_merchant, "file": file_url}
    from services.merchant_client import MERCHANT_HTTP_TIMEOUT, merchant_post

    try:
        body = await merchant_post(
            "/payin_set_check",
            payload,
            timeout=MERCHANT_HTTP_TIMEOUT,
        )
        if body.get("status_pending") == "error":
            # 503 — временная ошибка Payfast (повторить); 400 — реальный отказ.
            return {"status": 503 if _is_retryable_payin_error(body) else 400, "body": body}
        return {"status": 200, "body": body}
    except asyncio.TimeoutError:
        merchant_logger.warning("payin_set_check timeout uuid=%s", uuid_merchant)
        return {"status": 504, "body": {"error": "timeout"}}
    except aiohttp.ClientError as e:
        merchant_logger.warning("payin_set_check failed uuid=%s: %s", uuid_merchant, e)
        return {"status": 0, "body": {"error": str(e)}}


# ============================================================
# 13.2 ОТМЕНА ЗАЯВКИ У МЕРЧА (POST /cancel_order_payin)
# ============================================================
async def cancel_order_merchant(uuid_value: str) -> dict:
    """
    POST /cancel_order_payin.
    Returns {status, body, ok} with real HTTP status (не всегда 200).
    """
    from services.merchant_client import cancel_order_payin

    return await cancel_order_payin(uuid_value)


# status_check 2 = только PDF, 3 = только видео. Файлы не открываем и не парсим — только проверка расширения.
ALLOWED_RECEIPT_EXTENSIONS = {
    2: ("pdf",),
    3: ("mp4", "mov", "avi", "webm", "mkv"),
}

# Лимиты приёма чеков: размер файла и минимум свободного места на диске
MAX_RECEIPT_PDF_BYTES = 5 * 1024 * 1024    # 5 МБ для PDF (чеки обычно 100 КБ–2 МБ)
MAX_RECEIPT_VIDEO_BYTES = 20 * 1024 * 1024 # 20 МБ для видео (короткая запись экрана оплаты)
MIN_DISK_FREE_BYTES = 2 * 1024 * 1024 * 1024  # 2 ГБ — не сохраняем чек, если свободно меньше


def _get_file_extension_from_message(update: Update):
    """Определяет расширение по метаданным Telegram (без открытия/парсинга файла)."""
    doc = update.message.document
    video = update.message.video
    if doc:
        if doc.file_name:
            ext = Path(doc.file_name).suffix.lstrip(".").lower()
            if ext.isalnum():
                return ext[:20]
        mime = (getattr(doc, "mime_type", None) or "").lower()
        if mime == "application/pdf":
            return "pdf"
    if video:
        if getattr(video, "mime_type", None) and "/" in video.mime_type:
            return video.mime_type.split("/")[-1].lower()
        return "mp4"
    return None


# ============================================================
# 13.1 ТЕСТ ПРОВЕРОК ЧЕКА (команда /test_check)
# ============================================================
async def test_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает чек для проверки без создания заявки: только проверки типа, размера и места на диске. Только для админов."""
    if not await rate_limit_ok(update):
        return
    user_id = update.effective_user.id
    admin_ids = getattr(config_rates, "TELEGRAM_ADMIN_IDS", [])
    if admin_ids and user_id not in admin_ids:
        return
    context.user_data["test_check"] = True
    await update.message.reply_text(
        "🧪 <b>Режим проверки чека</b>\n\n"
        "Пришлите файл — <b>документ (PDF)</b> или <b>видео</b> (MP4, MOV, AVI, WebM, MKV).\n\n"
        "Проверятся: тип файла, размер (PDF до 5 МБ, видео до 20 МБ), свободное место на диске. "
        "Файл никуда не отправляется.",
        parse_mode="HTML",
    )


# ============================================================
# 13.2 ОБРАБОТКА ПРИСЛАННОГО ЧЕКА (документ или видео)
# ============================================================
async def exchange_attach_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прикрепляем чек к заявке AWAITING_CHECK. Только проверка расширения, файл не открываем."""
    if not await rate_limit_ok(update):
        return
    if not update.message:
        return

    user_id = update.effective_user.id
    receipt_logger.info("attach_check user=%s video_note=%s video=%s doc=%s",
                        user_id, bool(update.message.video_note),
                        bool(update.message.video), bool(update.message.document))

    if update.message.video_note:
        await update.message.reply_text(
            "❌ Отправьте <b>видео файлом</b>, не «кружок».\n"
            "Нажмите 📎 → выберите видео или отправьте как файл.",
            parse_mode="HTML",
            reply_markup=await menu_for(update),
        )
        return

    # ----- Режим теста: только проверки, без заявки и без отправки -----
    if context.user_data.get("test_check"):
        doc = update.message.document
        video = update.message.video
        if not doc and not video:
            await update.message.reply_text(
                "❌ Отправьте файл: документ (PDF) или видео."
            )
            return
        req_type = 3 if video else 2
        allowed = ALLOWED_RECEIPT_EXTENSIONS.get(req_type, ("pdf",))
        ext = _get_file_extension_from_message(update)
        if not ext or ext not in allowed:
            if req_type == 2:
                await update.message.reply_text(
                    "❌ В тесте принимается только <b>файл PDF</b>. Отправьте .pdf",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    "❌ В тесте принимается только <b>видео</b> (MP4, MOV, AVI, WebM, MKV).",
                    parse_mode="HTML",
                )
            context.user_data.pop("test_check", None)
            return
        file_size = (doc.file_size if doc else getattr(video, "file_size", 0)) or 0
        if req_type == 2 and file_size > MAX_RECEIPT_PDF_BYTES:
            await update.message.reply_text(
                "❌ Файл слишком большой. Лимит для PDF: 5 МБ."
            )
            context.user_data.pop("test_check", None)
            return
        if req_type == 3 and file_size > MAX_RECEIPT_VIDEO_BYTES:
            await update.message.reply_text(
                "❌ Файл слишком большой. Лимит для видео: 20 МБ."
            )
            context.user_data.pop("test_check", None)
            return
        from services.receipts_storage import assert_receipts_writable

        try:
            receipts_dir = assert_receipts_writable()
        except PermissionError as e:
            await update.message.reply_text(
                "⚠️ Временно не можем принять чек (ошибка сервера). Сообщите оператору.",
            )
            receipt_logger.error("receipts dir not writable: %s", e)
            context.user_data.pop("test_check", None)
            return
        disk = shutil.disk_usage(receipts_dir)
        if disk.free < MIN_DISK_FREE_BYTES:
            cfg = load_config()
            admin_chat_id = cfg.reports_group_id() or None
            if admin_chat_id:
                free_gb = disk.free / (1024**3)
                try:
                    await context.bot.send_message(
                        chat_id=admin_chat_id,
                        text=f"⚠️ <b>Мало места на диске</b> (тест чека)\nСвободно: <code>{free_gb:.1f}</code> ГБ.",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.debug("ignored non-fatal error", exc_info=True)
            await update.message.reply_text(
                f"❌ Проверка не пройдена: мало места на диске (свободно {disk.free / (1024**3):.1f} ГБ, нужно минимум 2 ГБ)."
            )
            context.user_data.pop("test_check", None)
            return
        # Все проверки пройдены
        context.user_data.pop("test_check", None)
        await update.message.reply_text(
            "✅ <b>Все проверки пройдены</b> (тест): тип файла, размер, место на диске — ок. Файл никуда не отправлялся.",
            parse_mode="HTML",
        )
        return

    order = await get_order_awaiting_check_by_user(user_id)

    if not order:
        # Если заявка в статусе CREATED (пользователь не нажал «Я оплатил»),
        # автоматически переводим в AWAITING_CHECK при получении чека.
        active = await get_active_order_by_user(user_id)
        if active and active["direction"] == "buy" and active["status"] == "CREATED":
            if _payfast_requisites_closed_for_order(dict(active)):
                await _reply_payfast_requisites_closed(update, dict(active))
                return
            transitioned = await update_order_to_awaiting_check(
                active["order_id"], required_receipt_type=2
            )
            if transitioned:
                from services.order_ops_notify import notify_ops_order

                refreshed = await get_order(active["order_id"]) or active
                from services.db import mark_ops_alert_once as _mark_awaiting_once

                if await _mark_awaiting_once(active["order_id"], "awaiting_receipt_notify"):
                    await notify_ops_order(
                        "awaiting_receipt",
                        dict(refreshed),
                        bot=update.get_bot(),
                        username=update.effective_user.username if update.effective_user else None,
                    )
                order = await get_order_awaiting_check_by_user(user_id)

    if not order:
        await update.message.reply_text(
            "ℹ️ Нет заявки, ожидающей чек. Если вы уже отправили чек — ожидайте проверки.",
            reply_markup=await menu_for(update),
        )
        return
    if _payfast_requisites_closed_for_order(dict(order)):
        await _reply_payfast_requisites_closed(update, dict(order))
        return

    merchant_uuid = order.get("merchant_order_id")
    if not merchant_uuid and not order.get("order_id"):
        await update.message.reply_text("❌ Ошибка: не найден ID заявки у платёжной системы.")
        return

    req_type = order.get("required_receipt_type") or 2
    allowed = ALLOWED_RECEIPT_EXTENSIONS.get(req_type, ("pdf",))

    # Только документ или видео; фото не принимаем (для 2 нужен PDF, для 3 — видео)
    doc = update.message.document
    video = update.message.video
    if not doc and not video:
        await update.message.reply_text(
            "❌ Отправьте файл: документ (PDF) или видео в зависимости от требования к заявке."
        )
        return

    ext = _get_file_extension_from_message(update)
    if not ext or ext not in allowed:
        if req_type == 2:
            await update.message.reply_text("❌ Для этой заявки принимается только <b>файл PDF</b>. Отправьте .pdf", parse_mode="HTML")
        else:
            await update.message.reply_text(
                "❌ Для этой заявки принимается только <b>видео</b> (MP4, MOV, AVI, WebM, MKV).",
                parse_mode="HTML",
            )
        return

    file_size = (doc.file_size if doc else getattr(video, "file_size", 0)) or 0
    if req_type == 2 and file_size > MAX_RECEIPT_PDF_BYTES:
        await update.message.reply_text(
            "❌ Файл слишком большой. Лимит для PDF: 5 МБ. Отправьте файл меньшего размера.",
            reply_markup=await menu_for(update),
        )
        return
    if req_type == 3 and file_size > MAX_RECEIPT_VIDEO_BYTES:
        await update.message.reply_text(
            "❌ Файл слишком большой. Лимит для видео: 20 МБ. Отправьте файл меньшего размера.",
            reply_markup=await menu_for(update),
        )
        return

    if req_type == 3:
        await update.message.reply_text("⏳ Принимаем видео…")

    async with SEM_ATTACH_CHECK:
        # Каталог для чеков; файл только сохраняем на диск, не открываем и не парсим
        from services.receipts_storage import (
            assert_receipts_writable,
            download_telegram_file_to_path,
        )

        try:
            receipts_dir = assert_receipts_writable()
        except PermissionError as e:
            receipt_logger.error("receipts dir not writable: %s", e)
            await update.message.reply_text(
                "⚠️ Временно не можем принять чек (ошибка сервера). Сообщите оператору.",
                reply_markup=await menu_for(update),
            )
            return

        disk = shutil.disk_usage(receipts_dir)
        if disk.free < MIN_DISK_FREE_BYTES:
            cfg = load_config()
            admin_chat_id = cfg.reports_group_id() or None
            if admin_chat_id:
                free_gb = disk.free / (1024**3)
                try:
                    await context.bot.send_message(
                        chat_id=admin_chat_id,
                        text=f"⚠️ <b>Мало места на диске</b>\nСвободно: <code>{free_gb:.1f}</code> ГБ. Рекомендуется освободить место.",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.debug("ignored non-fatal error", exc_info=True)
            await update.message.reply_text(
                "⚠️ Временно не можем принять чек. Попробуйте через пару минут.",
                reply_markup=await menu_for(update),
            )
            return

        file_id = doc.file_id if doc else video.file_id

        safe_ext = ext if ext.isalnum() else "bin"
        receipt_id = uuid.uuid4().hex
        local_path = receipts_dir / f"{receipt_id}.{safe_ext}"

        try:
            await download_telegram_file_to_path(
                context.bot,
                file_id,
                local_path,
                read_timeout=120.0 if req_type == 3 else 60.0,
            )
        except Exception as e:
            receipt_logger.warning(
                "attach_check download failed order=%s user=%s req_type=%s err=%s",
                order.get("order_id"),
                user_id,
                req_type,
                e,
            )
            await update.message.reply_text(
                f"❌ Не удалось получить файл: {e}\n"
                "Отправьте файл ещё раз — заявка активна и ожидает чек.",
                reply_markup=await menu_for(update),
            )
            return

        from services.receipt_validation import is_valid_pdf_file, is_valid_video_file

        if req_type == 2 and not is_valid_pdf_file(local_path):
            local_path.unlink(missing_ok=True)
            await update.message.reply_text(
                "❌ Файл не похож на PDF. Отправьте настоящий документ .pdf",
                reply_markup=await menu_for(update),
            )
            return
        if req_type == 3 and not is_valid_video_file(local_path):
            local_path.unlink(missing_ok=True)
            await update.message.reply_text(
                "❌ Файл не похож на видео. Отправьте MP4, MOV или другой поддерживаемый формат.",
                reply_markup=await menu_for(update),
            )
            return

        # URL для мерча: подписанный доступ без секрета в query.
        receipt_name = f"{receipt_id}.{safe_ext}"

        # Сохраняем имя файла в заявке, чтобы админ мог посмотреть чек.
        try:
            from services.db import set_order_receipt_file

            await set_order_receipt_file(order["order_id"], receipt_name)
        except Exception as e:
            receipt_logger.warning(
                "save receipt_file failed order=%s: %s", order.get("order_id"), e
            )

        from services.receipt_ops_review import route_client_receipt

        routed = await route_client_receipt(
            dict(order),
            receipt_name,
            bot=context.bot,
            username=update.effective_user.username if update.effective_user else None,
            telegram_file_id=file_id,
            as_document=bool(doc),
        )
        reply_kwargs = {"reply_markup": await menu_for(update)}
        if routed.get("parse_mode"):
            reply_kwargs["parse_mode"] = routed["parse_mode"]
        await update.message.reply_text(routed["client_message"], **reply_kwargs)


# ============================================================
# 14. ПОДТВЕРЖДЕНИЕ ОТМЕНЫ ЗАЯВКИ
# ============================================================
async def _reply_cancel_done(update, context, order, *, extra: str = "") -> None:
    """Сообщение после отмены: кулдаун + конверсия для Payfast BUY."""
    from services.buyer_access_guards import (
        format_cancel_followup_message,
        format_conversion_line,
    )
    from services.db import get_buyer_payfast_conversion

    had_payfast = (
        str(order.get("direction") or "").lower() == "buy"
        and bool(str(order.get("merchant_order_id") or "").strip())
    )
    conv = await get_buyer_payfast_conversion(update.effective_user.id)
    if had_payfast:
        text = format_cancel_followup_message(conv)
        if extra:
            text = f"{text}\n{extra}"
    else:
        text = "🚫 Заявка отменена"
        if extra:
            text = f"{text}{extra}"
        if (conv.get("paid") or 0) + (conv.get("failed") or 0) > 0:
            text = f"{text}\n\n{format_conversion_line(conv)}"
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=await menu_for(update),
    )
    context.user_data.clear()


async def confirm_cancel_handler(update, context):
    if not await rate_limit_ok(update):
        return
    user_id = update.effective_user.id
    order = await get_active_order_by_user(user_id)

    if not order:
        await update.message.reply_text(
            "❌ Активная заявка не найдена.",
            reply_markup=await menu_for(update)
        )
        context.user_data.clear()
        return

    if _payfast_cancellation_is_locked_for_order(order):
        await _reply_payfast_cancellation_locked(update, order)
        context.user_data.clear()
        return

    # BUY — отмена у мерча (POST /cancel_order_payin), кроме заявок только на оператора
    if order.get("direction") == "buy" and order.get("status") != "OPERATOR_PENDING":
        from services.merchant_api_helpers import cancel_payin_for_order

        try:
            result = await cancel_payin_for_order(dict(order), cancel_order_merchant)
            merchant_logger.debug("cancel_order result status=%s", (result or {}).get("status"))
            merchant_ok = (
                bool(result.get("ok"))
                if "ok" in result
                else int(result.get("status") or 0) == 200
            )
            if not merchant_ok:
                from services.stale_payin_hold import resolve_failed_merchant_cancel

                outcome = await resolve_failed_merchant_cancel(dict(order), result)
                if outcome == "closed_superseded":
                    await _reply_cancel_done(
                        update,
                        context,
                        order,
                        extra="Крипта по этой заявке уже была отправлена.",
                    )
                    return
                if outcome == "closed_merchant":
                    await _reply_cancel_done(update, context, order)
                    return
                if outcome == "settled":
                    await update.message.reply_text(
                        "✅ Оплата по этой заявке уже подтверждена мерчантом.\n"
                        "Отменить её нельзя — дождитесь выплаты крипты или напишите "
                        "оператору: @focus_operator",
                        reply_markup=await menu_for(update),
                    )
                    return
                err = (result.get("body") or {}).get("error", "")
                err_line = f"\n⚠️ Ответ мерчанта: {err}" if err else ""
                await update.message.reply_text(
                    "❌ Не удалось отменить заявку. Попробуйте ещё раз или напишите оператору: @focus_operator"
                    f"{err_line}",
                    parse_mode="HTML",
                    reply_markup=await menu_for(update),
                )
                return
        except Exception as e:
            merchant_logger.exception("cancel_order failed order_id=%s", order["order_id"])
            await update.message.reply_text(
                "❌ Не удалось отменить заявку. Попробуйте ещё раз или напишите оператору: @focus_operator"
                f"\n⚠️ Ошибка при отмене у мерчанта: {e}",
                parse_mode="HTML",
                reply_markup=await menu_for(update),
            )
            return

    await update_order_status(order["order_id"], "CANCELED")

    from services.db import clear_receipt_ops_pending

    await clear_receipt_ops_pending(order["order_id"])

    await _reply_cancel_done(update, context, order)



#============================================================
# 16. ОБРАБОТКА "НАЗАД" ПРИ ОТМЕНЕ ЗАЯВКИ
#============================================================

async def cancel_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit_ok(update):
        return
    if update.message.text != "⬅️ Назад":
        return

    user_id = update.effective_user.id
    order = await get_active_order_by_user(user_id)
    step = context.user_data.get("step")

    # ❌ Заявки нет / истекла / отменена
    if not order:
        context.user_data.clear()
        await update.message.reply_text(
            "ℹ️ Заявка больше не активна. Вы в главном меню.",
            reply_markup=await menu_for(update)
        )
        return

    if step == "confirm_cancel_order":
        await update.message.reply_text(
        "ℹ️ Действие отменено, вы вернулись в главное меню",
        reply_markup=await menu_for(update),
    )
    else:
        context.user_data["step"] = "awaiting_payment_confirmation"

        await update.message.reply_text(
            "⏳ Продолжаем ожидать оплату.",
            reply_markup=awaiting_payment_keyboard(),
        )


    # если не хочешь точку — можно удалить сообщение через Bot API,
    # но это уже через отдельный delete_message
