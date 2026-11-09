"""Реферальная программа: кабинет, вывод, история."""
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services import config_rates
from services.antispam import rate_limit_ok
from services.user_errors import user_facing_message
from services.order_ops_notify import notify_ops_withdrawal
from services.menu import main_menu_keyboard
from services.user_referral_db import (
    format_referral_cabinet_message,
    has_pending_withdrawal,
)
from services.user_referral_withdraw import (
    create_withdrawal,
    format_crypto_withdraw_limits,
    min_crypto_amount_rub,
    preview_crypto_withdraw,
)
from services.crypto_network_fee import format_withdraw_terms_html, format_crypto_fee_hint_html, resolve_usdt_rub
from services.user_unified_balance import get_unified_balance_stats
from handlers.exchange_flow import clear_exchange_session
from services.debug_agent import agent_log
from telegram.ext import ApplicationHandlerStop

REF_MENU = "👥 Реферальная программа"
CANCEL = "🚫 Отмена"

_CRYPTO_CHOICES = [
    ("USDT TRC20", "usdt", "trc20"),
    ("USDT ERC20", "usdt", "erc20"),
    ("BTC", "btc", None),
    ("LTC", "ltc", None),
    ("TRX", "trx", None),
]


def _payout_rail_from_stats(stats: dict) -> tuple[bool, float]:
    rail = stats.get("payout_rail")
    if not isinstance(rail, dict):
        return True, 0.0
    if rail.get("crypto_allowed") is True:
        return True, 0.0
    try:
        remaining = float(rail.get("remaining_rub") or 0)
    except (TypeError, ValueError):
        remaining = 0.0
    if remaining <= 0.01:
        return True, 0.0
    return False, remaining


def withdraw_method_markup(crypto_allowed: bool) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton("💳 Карта / СБП", callback_data="uref:method:card")]
    if crypto_allowed:
        row.append(InlineKeyboardButton("🪙 Крипта", callback_data="uref:method:crypto"))
    return InlineKeyboardMarkup([row])


def _cabinet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💸 Вывести средства", callback_data="uref:withdraw")],
            [InlineKeyboardButton("📜 История", callback_data="uref:history")],
        ]
    )


async def user_referral_cabinet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    context.user_data.pop("uref_wd", None)
    user = update.effective_user
    text = await format_referral_cabinet_message(user.id, user.username)
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=_cabinet_keyboard(),
    )


async def user_referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "uref:history":
        from services.db import get_pool
        from services.partner_db import (
            format_partner_history_message,
            get_partner_by_telegram,
            merge_partner_history_rows,
        )

        partner = await get_partner_by_telegram(user_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            if partner:
                referral_rows = await conn.fetch(
                    """
                    SELECT type, amount_rub, note, created_at
                    FROM user_referral_ledger
                    WHERE referrer_user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 15
                    """,
                    user_id,
                )
                partner_rows = await conn.fetch(
                    """
                    SELECT type, amount_rub, note, created_at
                    FROM partner_ledger
                    WHERE campaign_id = $1 AND type <> 'hold'
                    ORDER BY created_at DESC
                    LIMIT 15
                    """,
                    partner["campaign_id"],
                )
                text = format_partner_history_message(
                    merge_partner_history_rows(referral_rows, partner_rows)
                )
                await query.message.reply_text(
                    text or "История пуста.",
                    parse_mode="HTML",
                )
                return

            rows = await conn.fetch(
                """
                SELECT type, amount_rub, note, created_at
                FROM user_referral_ledger
                WHERE referrer_user_id = $1
                ORDER BY created_at DESC
                LIMIT 15
                """,
                user_id,
            )
        if not rows:
            await query.message.reply_text("История пуста.")
            return
        lines = ["📜 <b>Последние операции</b>\n"]
        for r in rows:
            sign = "+" if float(r["amount_rub"]) >= 0 else ""
            t = r["type"]
            label = {"accrual": "начисление", "payout": "выплата", "adjustment": "корректировка"}.get(
                t, t
            )
            lines.append(
                f"• {r['created_at'].strftime('%d.%m %H:%M')} — "
                f"{label}: <b>{sign}{float(r['amount_rub']):,.2f} ₽</b>"
            )
        await query.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if data == "uref:withdraw":
        if await has_pending_withdrawal(user_id):
            await query.message.reply_text(
                "У вас уже есть заявка на вывод в обработке. Дождитесь решения оператора."
            )
            return
        stats = await get_unified_balance_stats(user_id)
        if stats["available_rub"] < 1:
            await query.message.reply_text("Нет средств, доступных к выводу.")
            return
        clear_exchange_session(context)
        context.user_data["uref_wd"] = {"step": "amount"}
        await query.message.reply_text(
            "Введите сумму вывода в ₽.\n"
            f"Доступно с <b>общего</b> баланса: <b>{stats['available_rub']:,.2f} ₽</b>\n"
            "Кешбэк + промокоды + рефералка + партнёрские начисления.\n\n"
            f"{await format_withdraw_terms_html(compact=True)}\n\n"
            f"Для отмены нажмите «{CANCEL}».",
            parse_mode="HTML",
        )
        return


async def user_referral_withdraw_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not await rate_limit_ok(update):
        return
    wd = context.user_data.get("uref_wd")
    if not wd:
        return

    text = update.message.text.strip()
    user = update.effective_user
    step = wd.get("step")
    agent_log(
        "user_referral.py:withdraw_msg",
        "uref_wd active",
        {
            "step": step,
            "text_preview": text[:40],
            "exchange_step": context.user_data.get("step"),
        },
        hypothesis_id="A",
    )

    if step == "amount":
        try:
            amount = float(text.replace(",", ".").replace(" ", ""))
        except ValueError:
            await update.message.reply_text("Введите число, например 20000")
            raise ApplicationHandlerStop()
        stats = await get_unified_balance_stats(user.id)
        if amount <= 0 or amount > stats["available_rub"] + 0.01:
            await update.message.reply_text(
                f"Сумма должна быть от 1 до {stats['available_rub']:,.2f} ₽ "
                "(доступно с общего баланса)."
            )
            raise ApplicationHandlerStop()
        wd["amount_rub"] = round(amount, 2)
        wd["step"] = "method"
        crypto_allowed, remaining = _payout_rail_from_stats(stats)
        extra = ""
        if not crypto_allowed:
            extra = (
                f"\n\nСначала выведите {remaining:,.2f} ₽ на карту — "
                "после этого откроется вывод в крипту."
            )
        await update.message.reply_text(
            "Выберите способ вывода:" + extra,
            reply_markup=withdraw_method_markup(crypto_allowed),
        )
        raise ApplicationHandlerStop()

    if step == "requisites_card":
        if len(text) < 5:
            await update.message.reply_text("Укажите реквизиты (карта, банк, СБП).")
            raise ApplicationHandlerStop()
        wd["requisites"] = text
        wd["step"] = "confirm"
        await _send_confirm(update, wd)
        raise ApplicationHandlerStop()

    if step == "requisites_crypto":
        from services.wallet_validation import clean_crypto_address, validate_buy_wallet

        addr = clean_crypto_address(text)
        try:
            validate_buy_wallet(wd.get("crypto") or "", wd.get("network"), addr)
        except ValueError as e:
            await update.message.reply_text(user_facing_message(e))
            raise ApplicationHandlerStop()
        wd["requisites"] = addr
        wd["step"] = "confirm"
        await _send_confirm(update, wd)
        raise ApplicationHandlerStop()

    agent_log(
        "user_referral.py:withdraw_msg",
        "uref_wd unhandled step — no stop",
        {"step": step, "text_preview": text[:40]},
        hypothesis_id="A",
    )


async def user_referral_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()
    wd = context.user_data.get("uref_wd")
    if not wd or wd.get("step") != "method":
        return

    method = query.data.split(":")[-1]
    wd["method"] = method
    amount = wd["amount_rub"]

    if method == "card":
        from services.user_referral_withdraw import min_card_withdraw_rub

        card_min = min_card_withdraw_rub("balance")
        if amount < card_min:
            await query.message.reply_text(
                f"Для карты минимум {card_min:,.0f} ₽. "
                "Введите другую сумму."
            )
            context.user_data.pop("uref_wd", None)
            return
        wd["step"] = "requisites_card"
        from services.ux_copy import CARD_WITHDRAW_PROMISE

        await query.message.reply_text(
            "Введите реквизиты: номер карты или телефон для СБП и название банка.\n\n"
            f"{CARD_WITHDRAW_PROMISE}"
        )
        return

    if method == "crypto":
        stats = await get_unified_balance_stats(query.from_user.id)
        crypto_allowed, remaining = _payout_rail_from_stats(stats)
        if not crypto_allowed:
            await query.message.reply_text(
                f"Сначала выведите {remaining:,.2f} ₽ на карту."
            )
            wd["step"] = "method"
            await query.message.reply_text(
                "Выберите способ вывода:",
                reply_markup=withdraw_method_markup(False),
            )
            return
        rows = []
        for label, crypto, network in _CRYPTO_CHOICES:
            cb = f"uref:crypto:{crypto}:{network or ''}"
            rows.append([InlineKeyboardButton(label, callback_data=cb)])
        await query.message.reply_text(
            "Выберите монету и сеть:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        wd["step"] = "choose_crypto"
        return


async def user_referral_crypto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()
    wd = context.user_data.get("uref_wd")
    if not wd or wd.get("step") != "choose_crypto":
        return

    parts = query.data.split(":")
    if len(parts) < 4:
        return
    crypto = parts[2]
    network = parts[3] or None
    amount = wd["amount_rub"]
    try:
        min_rub = await min_crypto_amount_rub(crypto)
    except ValueError as e:
        await query.message.reply_text(user_facing_message(e))
        context.user_data.pop("uref_wd", None)
        return
    if amount < min_rub - 0.01:
        await query.message.reply_text(
            f"Для {crypto.upper()} минимум ~{min_rub:,.0f} ₽ "
            f"({format_crypto_withdraw_limits(crypto)}). "
            "Начните вывод заново с большей суммы."
        )
        context.user_data.pop("uref_wd", None)
        return

    wd["crypto"] = crypto
    wd["network"] = network
    wd["step"] = "requisites_crypto"
    net = f" ({network.upper()})" if network else ""
    try:
        usdt_rub = await resolve_usdt_rub()
        hint = format_crypto_fee_hint_html(crypto, usdt_rub=usdt_rub)
    except ValueError:
        hint = f"Минимум для {crypto.upper()}: {format_crypto_withdraw_limits(crypto)}."
    await query.message.reply_text(
        f"Введите адрес кошелька {crypto.upper()}{net}:\n\n{hint}",
        parse_mode="HTML",
    )


async def _send_confirm(update: Update, wd: dict):
    method = wd["method"]
    if method == "card":
        from services.crypto_network_fee import card_withdraw_fee_rub, payout_from_fee
        from services.payin_requisite_rail import frozen_subsidy_cap_rub, triangle_band_notice
        from services.ux_copy import CARD_WITHDRAW_PROMISE

        fee = float(card_withdraw_fee_rub())
        payout = payout_from_fee(float(wd["amount_rub"]), fee)
        notice = triangle_band_notice(
            due=payout,
            nominal=payout,
            cap=frozen_subsidy_cap_rub(payout),
        )
        detail = f"💳 Карта / СБП\n<code>{html.escape(str(wd['requisites']))}</code>"
        amount_lines = (
            f"Списание с баланса: <b>{wd['amount_rub']:,.2f} ₽</b>\n"
            f"Комиссия: <b>{fee:,.2f} ₽</b>\n"
            f"К получению на карту: <b>{payout:,.2f} ₽</b>\n"
            f"{notice}\n"
            f"{CARD_WITHDRAW_PROMISE}\n"
        )
    else:
        net = wd.get("network") or ""
        crypto = wd.get("crypto", "").upper()
        detail = (
            f"🪙 {crypto} {net.upper()}\n"
            f"<code>{html.escape(str(wd['requisites']))}</code>"
        )
        try:
            fee, payout = await preview_crypto_withdraw(wd["amount_rub"], wd["crypto"])
            amount_lines = (
                f"Списание с баланса: <b>{wd['amount_rub']:,.2f} ₽</b>\n"
                f"Комиссия сети: <b>{fee:,.2f} ₽</b> (удерживается с суммы)\n"
                f"К получению: <b>~{payout:,.2f} ₽</b> в {crypto}\n"
            )
        except ValueError:
            amount_lines = f"Сумма: <b>{wd['amount_rub']:,.2f} ₽</b>\n"
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data="uref:confirm"),
                InlineKeyboardButton("❌ Отмена", callback_data="uref:cancel"),
            ]
        ]
    )
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"Проверьте заявку:\n\n"
        f"{amount_lines}"
        f"{detail}",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def user_referral_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not await rate_limit_ok(update):
        return
    await query.answer()
    data = query.data
    wd = context.user_data.get("uref_wd")

    if data == "uref:cancel":
        context.user_data.pop("uref_wd", None)
        await query.message.reply_text(
            "Заявка отменена.",
            reply_markup=await main_menu_keyboard(query.from_user.id, query.from_user.username),
        )
        return

    if data != "uref:confirm" or not wd or wd.get("step") != "confirm":
        return

    user = query.from_user
    try:
        row = await create_withdrawal(
            referrer_user_id=user.id,
            amount_rub=wd["amount_rub"],
            method=wd["method"],
            requisites=wd["requisites"],
            crypto=wd.get("crypto"),
            network=wd.get("network"),
        )
    except ValueError as e:
        await query.message.reply_text(user_facing_message(e))
        context.user_data.pop("uref_wd", None)
        return

    context.user_data.pop("uref_wd", None)
    confirm_lines = [f"✅ Заявка #{row['id']} отправлена операторам. Ожидайте выплаты."]
    if row.get("method") == "crypto" and float(row.get("network_fee_rub") or 0) > 0:
        payout = float(row.get("payout_amount_rub") or 0)
        fee = float(row.get("network_fee_rub") or 0)
        crypto = (row.get("crypto") or "").upper()
        confirm_lines.append(
            f"Комиссия сети: {fee:,.2f} ₽. К получению: ~{payout:,.2f} ₽ в {crypto}."
        )
    await query.message.reply_text(
        "\n".join(confirm_lines),
        reply_markup=await main_menu_keyboard(user.id, user.username),
    )

    msg_id = await notify_ops_withdrawal(row, context.bot, username=user.username)
    if msg_id:
        from services.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_referral_withdrawals SET admin_message_id = $1 WHERE id = $2",
                msg_id,
                row["id"],
            )
