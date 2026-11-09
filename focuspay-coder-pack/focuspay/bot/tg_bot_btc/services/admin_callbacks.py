import asyncio
import html
import logging
import re
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import secrets
import string
import asyncpg

from services.db import (
    get_order,
    update_order_status,
    get_active_orders,
    get_recent_orders,
    get_paid_orders_for_stats,
    get_paid_orders_for_date,
    BROADCAST_SEGMENTS,
    get_broadcast_user_ids,
    create_promo_campaign,
    list_promo_campaigns,
    get_promo_campaign_by_id,
    update_promo_bonus_percent,
    set_promo_campaign_active,
    delete_promo_campaign,
    promo_campaign_has_attributions,
    get_promo_stats_for_days,
    get_promo_stats_for_date,
    get_promo_paid_orders_for_days,
    sum_review_bonus_rub,
    sum_review_bonus_rub_for_date,
    sum_operator_wallet_payout_rub,
    sum_operator_wallet_payout_rub_for_date,
    sum_buy_network_fee_rub,
    sum_buy_network_fee_rub_for_date,
)
from services.broadcast_html import (
    cancel_broadcast_draft,
    insert_broadcast_draft,
    is_broadcast_copy_account,
    launch_broadcast_draft,
    prepare_broadcast_text,
)
from services.config_rates import (
    TELEGRAM_ADMIN_IDS,
    is_finance_owner,
    is_ops_group_chat,
    is_reports_group_chat,
)
from services.economics_snapshot import order_economics
from services.callback_signatures import sign_order, verify_order_signature as verify_signature
from services.financial_guards import buy_pay_allowed_status, is_admin_group_chat as _is_admin_group_chat
from services.order_transitions import sell_pay_allowed_status
from services.templates import render_admin_message, render_admin_message_sell, base_crypto, fmt_crypto
from services.merchant_order_id import resolve_merchant_display_id
from services.rates_api import CACHE as RATES_CACHE
from services.text_sanitize import sanitize_telegram_html

logger = logging.getLogger("admin_callbacks")

_HASH_PROMPT_SUFFIX = (
    "Ответьте <b>reply на это сообщение</b> одним txid (hash транзакции) "
    "для подтверждения выплаты."
)

PROMO_CODE_LEN = 8
SUPPORT_USERNAME = "@focus_operator"


async def _post_wallet_send_early(order_id: str) -> tuple[int, dict | None]:
    import aiohttp

    base = (os.getenv("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    token = (os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()
    if not token:
        return 503, {"detail": "INTERNAL_API_SECRET не настроен"}
    url = f"{base}/api/internal/payout-wallet-confirm/send-early"
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json={"order_id": order_id},
                headers={"X-Internal-Token": token},
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None
                return resp.status, data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("wallet send early failed order=%s: %s", order_id, exc)
        return 0, None


def _strip_wask_button(reply_markup) -> InlineKeyboardMarkup | None:
    if not reply_markup or not getattr(reply_markup, "inline_keyboard", None):
        return None
    rows = []
    for row in reply_markup.inline_keyboard:
        kept = [
            btn
            for btn in row
            if not str(getattr(btn, "callback_data", "") or "").startswith("wask:")
        ]
        if kept:
            rows.append(kept)
    return InlineKeyboardMarkup(rows) if rows else None


def _order_problem_user_message(order_id: str) -> str:
    return (
        f"❌ Возникли проблемы с заявкой <code>{order_id}</code>.\n"
        f"Пожалуйста, свяжитесь с поддержкой {SUPPORT_USERNAME}"
    )


async def _notify_user_order_cancelled(context: ContextTypes.DEFAULT_TYPE, order) -> None:
    from services.menu import main_menu_keyboard

    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=_order_problem_user_message(order["order_id"]),
            parse_mode="HTML",
            reply_markup=await main_menu_keyboard(order.get("user_id")),
        )
    except Exception as e:
        print(f"[admin_cancel] notify user {order.get('user_id')}: {e}")


def _make_promo_code(length: int = PROMO_CODE_LEN) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _send_hash_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    *,
    kind: str,
    chat_id: int,
    user_id: int,
    card_message_id: int,
    prompt_text: str,
    payload: dict,
) -> None:
    from services.payout_pending_store import save_pending, sync_user_data_pending

    await query.answer()
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=f"{prompt_text}\n{_HASH_PROMPT_SUFFIX}",
        parse_mode="HTML",
        reply_to_message_id=card_message_id,
    )
    save_pending(
        context.application.bot_data,
        kind=kind,
        chat_id=chat_id,
        user_id=user_id,
        prompt_message_id=sent.message_id,
        card_message_id=card_message_id,
        payload=payload,
    )
    sync_user_data_pending(
        context,
        kind=kind,
        chat_id=chat_id,
        user_id=user_id,
        card_message_id=card_message_id,
        payload=payload,
    )


def _resolve_pending_for_hash(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> dict | None:
    from services.payout_pending_store import lookup_pending

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    reply_to = update.message.reply_to_message.message_id if (
        update.message and update.message.reply_to_message
    ) else None
    hit = lookup_pending(
        context.application.bot_data,
        chat_id=chat_id,
        user_id=user_id,
        reply_to_message_id=reply_to,
    )
    if hit:
        return hit
    refwd = context.user_data.get("pending_refwd_tx")
    if refwd:
        return {**refwd, "kind": "refwd"}
    extwd = context.user_data.get("pending_extwd_receipt")
    if extwd:
        return {**extwd, "kind": "extwd_receipt"}
    payout = context.user_data.get("pending_payout_tx")
    if payout:
        kind = payout.get("kind") or "buy_payout"
        return {**payout, "kind": kind}
    return None


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else None

    if not (is_ops_group_chat(chat_id) or _is_admin_group_chat(chat_id)):
        await query.answer("⛔ Действие только в группе операторов", show_alert=True)
        return

    # 🔐 ТОЛЬКО АДМИНЫ
    if user_id not in TELEGRAM_ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        action, order_id, signature = query.data.split(":")
    except ValueError:
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    # 🔐 ПРОВЕРКА ПОДПИСИ
    if not verify_signature(order_id, signature):
        await query.answer("🚨 Подделка запроса", show_alert=True)
        return

    order = await get_order(order_id)
    if not order:
        await query.answer("❌ Заявка не найдена", show_alert=True)
        return

    current_status = order["status"]
    direction = (order.get("direction") or "").lower()

    # ✅ ДЕЙСТВИЕ — кнопки всегда меняют статус в БД (в т.ч. PAID/CANCELED/EXPIRED)
    if action == "pay":
        if current_status in ("PAID", "CANCELED", "EXPIRED"):
            await query.answer("Заявка уже закрыта", show_alert=True)
            return
        if current_status == "OPERATOR_PENDING" and direction == "buy":
            await _send_hash_prompt(
                context,
                query,
                kind="buy_manual",
                chat_id=chat_id,
                user_id=user_id,
                card_message_id=query.message.message_id,
                prompt_text=(
                    f"📤 Ручная заявка <code>{resolve_merchant_display_id(dict(order))}</code>"
                ),
                payload={"order_id": order_id},
            )
            return
        if current_status == "OPERATOR_PENDING" and direction != "buy":
            await query.answer(
                "Заявка через оператора — подтверждайте вручную в кабинете /ops",
                show_alert=True,
            )
            return
        if direction == "buy" and not buy_pay_allowed_status(current_status):
            await query.answer(
                "BUY: подтверждение только после оплаты (статус COMPLETED)",
                show_alert=True,
            )
            return
        if direction == "buy" and buy_pay_allowed_status(current_status):
            from services.payin_requisite_rail import is_payin_order

            if not is_payin_order(order):
                from services.payfast_payin_guard import (
                    payfast_block_message,
                    verify_payfast_ready_for_payout,
                )

                ok_pf, pf_err, _ = await verify_payfast_ready_for_payout(
                    dict(order), require_uuid=True
                )
                if not ok_pf:
                    await query.answer(payfast_block_message(pf_err), show_alert=True)
                    return
            await _send_hash_prompt(
                context,
                query,
                kind="buy_payout",
                chat_id=chat_id,
                user_id=user_id,
                card_message_id=query.message.message_id,
                prompt_text=(
                    f"📤 Заявка <code>{resolve_merchant_display_id(dict(order))}</code>"
                ),
                payload={"order_id": order_id},
            )
            return
        if direction == "sell" and not sell_pay_allowed_status(current_status):
            await query.answer(
                "SELL: подтверждение только после «Я оплатил» (PENDING и далее)",
                show_alert=True,
            )
            return
        ok = await update_order_status(order_id, "PAID")
        if not ok:
            await query.answer("❌ Недопустимый переход статуса", show_alert=True)
            return
        from services.partner_tracking import schedule_partner_exchange

        schedule_partner_exchange(dict(order))
        await query.answer()

    elif action == "cancel":
        prev_status = order["status"]
        ok = await update_order_status(order_id, "CANCELED")
        if not ok:
            await query.answer("❌ Недопустимый переход статуса", show_alert=True)
            return
        await query.answer()
        if prev_status not in ("CANCELED", "EXPIRED"):
            await _notify_user_order_cancelled(context, order)

    elif action == "wask":
        st, body = await _post_wallet_send_early(order_id)
        detail = str((body or {}).get("detail") or "").strip()
        if st != 200:
            await query.answer(
                detail or "❌ Не удалось отправить запрос кошелька",
                show_alert=True,
            )
            return
        await query.answer(
            detail or "⏩ Таймер снят — запрос кошелька отправлен покупателю",
            show_alert=True,
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=_strip_wask_button(query.message.reply_markup)
            )
        except Exception:
            logger.debug("strip wask button skipped", exc_info=True)
        return

    else:
        await query.answer()
        return

    # 🔁 ПЕРЕЧИТЫВАЕМ ИЗ БД
    order = await get_order(order_id)

    # 🧠 РЕНДЕРИМ ЗАНОВО (ЕДИНСТВЕННЫЙ ИСТОЧНИК HTML)
    if order["direction"] == "sell":
        new_text = render_admin_message_sell(order)
    else:
        new_text = render_admin_message(order)


    # 🧹 УБИРАЕМ КНОПКИ + ОБНОВЛЯЕМ ТЕКСТ
    await query.edit_message_text(
        text=new_text,
        parse_mode="HTML",
        reply_markup=None,
    )


async def private_broadcast_draft_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Личка бота: текст или пересылка от автора рассылки сохраняется черновиком."""
    if not _should_capture_broadcast(update, context):
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    await _save_copy_account_message(update, context)


async def admin_payout_tx_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ админа в группе с hash транзакции после «Выплачено» (BUY или крипто-вывод)."""
    if not update.message or not update.message.text:
        return
    if _should_capture_broadcast(update, context):
        await _save_copy_account_message(update, context)
        return
    chat_id = update.effective_chat.id
    if not (is_reports_group_chat(chat_id) or is_ops_group_chat(chat_id)):
        return
    user_id = update.effective_user.id
    if user_id not in TELEGRAM_ADMIN_IDS:
        return

    pending = _resolve_pending_for_hash(update, context)
    if not pending:
        # Только если это reply на что-то в чате — подсказка (не спамим на каждый текст)
        if update.message.reply_to_message:
            logger.warning(
                "payout hash ignored: no pending chat=%s user=%s reply_to=%s",
                chat_id,
                user_id,
                update.message.reply_to_message.message_id,
            )
            await update.message.reply_text(
                "ℹ️ Сначала нажмите «✅ Выплачено» на карточке заявки, "
                "затем ответьте <b>reply</b> на запрос бота с txid.",
                parse_mode="HTML",
            )
        return

    kind = pending.get("kind") or "buy_payout"
    if kind == "refwd":
        await _admin_refwd_tx_reply(update, context, pending, user_id)
        return

    order_id = pending.get("order_id")
    if not order_id:
        from services.payout_pending_store import clear_pending, clear_user_data_pending

        clear_pending(context.application.bot_data, pending)
        clear_user_data_pending(context, kind)
        return

    tx_text = update.message.text.strip()
    from services.buy_payout import (
        build_explorer_url,
        confirm_buy_payout,
        confirm_manual_buy_payout,
    )

    if kind == "buy_manual":
        ok, err, order = await confirm_manual_buy_payout(
            order_id,
            tx_hash=tx_text,
            actor=f"telegram:{user_id}",
            bot=context.bot,
        )
    else:
        ok, err, order = await confirm_buy_payout(
            order_id,
            tx_hash=tx_text,
            actor=f"telegram:{user_id}",
            bot=context.bot,
        )

    recoverable = err in (
        "invalid_tx",
        "crypto_exceeds_paid",
        "wrong_status",
        "amount_mismatch",
    ) or (err and str(err).startswith("payfast_"))

    if not ok:
        if err == "already_paid":
            from services.payout_pending_store import clear_pending, clear_user_data_pending

            clear_pending(context.application.bot_data, pending)
            clear_user_data_pending(context, kind)
            await update.message.reply_text(
                "ℹ️ Заявка уже подтверждена в другом месте.",
                parse_mode="HTML",
            )
            return
        if err == "invalid_tx":
            await update.message.reply_text(
                "❌ Некорректный hash. Отправьте txid (минимум 8 символов, без пробелов).",
                parse_mode="HTML",
            )
            return
        if err and str(err).startswith("payfast_"):
            from services.payfast_payin_guard import payfast_block_message

            await update.message.reply_text(
                f"❌ {payfast_block_message(err)}",
                parse_mode="HTML",
            )
            return
        err_text = html.escape(err or "ошибка")
        if err == "crypto_exceeds_paid":
            err_text = (
                "Сумма крипты в заявке больше, чем покрывает оплата "
                "(часто из‑за старой логики баланса). "
                "Проверьте crypto_amount и cashback_applied_rub в БД или подтвердите через /ops."
            )
        await update.message.reply_text(
            f"❌ Не удалось подтвердить: {err_text}",
            parse_mode="HTML",
        )
        if not recoverable:
            from services.payout_pending_store import clear_pending, clear_user_data_pending

            clear_pending(context.application.bot_data, pending)
            clear_user_data_pending(context, kind)
        return

    from services.payout_pending_store import clear_pending, clear_user_data_pending

    clear_pending(context.application.bot_data, pending)
    clear_user_data_pending(context, kind)

    card_mid = pending.get("card_message_id") or pending.get("message_id")
    order = order or await get_order(order_id)
    if order and card_mid:
        if order["direction"] == "sell":
            new_text = render_admin_message_sell(order)
        else:
            new_text = render_admin_message(order)
        try:
            await context.bot.edit_message_text(
                chat_id=pending.get("chat_id") or chat_id,
                message_id=card_mid,
                text=new_text,
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)

    explorer = build_explorer_url(str(order.get("crypto", "")), tx_text) if order else ""
    await update.message.reply_text(
        f"✅ Выплата подтверждена · <code>{resolve_merchant_display_id(dict(order)) if order else order_id}</code>\n"
        + (f'<a href="{explorer}">Транзакция</a>' if explorer else ""),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


# ============================================================
# /search — только в админ-группе, только админы
# ============================================================

async def admin_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /search [номер_заявки]. Без аргумента — список активных заявок, с аргументом — карточка заявки с кнопками."""
    from services.reports_group_guard import reply_wrong_reports_group

    if await reply_wrong_reports_group(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_reports_group_chat(chat_id):
        return
    if user_id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("⛔ Команда только для администраторов.")
        return

    args = (context.args or [])
    order_id = args[0].strip() if args else None

    if not order_id:
        # Список активных заявок
        orders = await get_active_orders(limit=50)
        if not orders:
            await update.message.reply_text("📋 Нет активных заявок.")
            return
        lines = []
        for o in orders:
            created = o.get("created_at")
            if hasattr(created, "strftime"):
                created = created.strftime("%d.%m %H:%M")
            else:
                created = str(created)[:16]
            direction = (o.get("direction") or "?").upper()
            lines.append(
                f"🆔 <code>{resolve_merchant_display_id(dict(o))}</code> | {direction} | {o['status']} | "
                f"{float(o['fiat_amount']):,.0f} ₽ | {fmt_crypto(o['crypto_amount'], base_crypto(o['crypto']))} {o['crypto']} | {created}"
            )
        text = "📋 <b>Активные заявки</b> (CREATED / PENDING / AWAITING_CHECK / COMPLETED):\n\n" + "\n".join(lines)
        await update.message.reply_text(text, parse_mode="HTML")
        return

    # Конкретная заявка
    order = await get_order(order_id)
    if not order:
        await update.message.reply_text(
            f"❌ Заявка <code>{html.escape(order_id)}</code> не найдена.",
            parse_mode="HTML",
        )
        return

    sig = sign_order(order_id)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Выплачено", callback_data=f"pay:{order_id}:{sig}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"cancel:{order_id}:{sig}"),
        ]
    ])

    if order["direction"] == "sell":
        text = render_admin_message_sell(order)
    else:
        text = render_admin_message(order)

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


# ============================================================
# /list — последние 30 заявок, только в админ-группе, только админы
# ============================================================

async def admin_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /list — показывает последние 30 заявок (любой статус)."""
    from services.reports_group_guard import reply_wrong_reports_group

    if await reply_wrong_reports_group(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_reports_group_chat(chat_id):
        return
    if user_id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("⛔ Команда только для администраторов.")
        return

    orders = await get_recent_orders(limit=30)
    if not orders:
        await update.message.reply_text("📋 Заявок пока нет.")
        return

    lines = []
    for o in orders:
        created = o.get("created_at")
        if hasattr(created, "strftime"):
            created = created.strftime("%d.%m %H:%M")
        else:
            created = str(created)[:16]
        direction = (o.get("direction") or "?").upper()
        lines.append(
            f"🆔 <code>{resolve_merchant_display_id(dict(o))}</code> | {direction} | {o['status']} | "
            f"{float(o['fiat_amount']):,.0f} ₽ | {fmt_crypto(o['crypto_amount'], base_crypto(o['crypto']))} {o['crypto']} | {created}"
        )
    text = "📋 <b>Последние 30 заявок</b>:\n\n" + "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML")


# ============================================================
# /stats [дней] — сумма крипты по PAID за период, только админ-группа
# ============================================================

def _stats_aggregate_by_crypto_and_direction(orders) -> tuple:
    """Группирует заявки по направлению и сохраняет их суммарную экономику."""
    by_buy = {}
    by_sell = {}
    for o in orders:
        base = base_crypto(o["crypto"])
        direction = (o.get("direction") or "buy").lower()
        target = by_buy if direction == "buy" else by_sell
        if base not in target:
            target[base] = {
                "crypto_sum": 0.0,
                "fiat_sum": 0.0,
                "profit_sum": 0.0,
                "merchant_fee_sum": 0.0,
            }
        economics = order_economics(dict(o), clamp=False)
        target[base]["crypto_sum"] += float(o["crypto_amount"])
        target[base]["fiat_sum"] += float(o["fiat_amount"])
        target[base]["profit_sum"] += economics["service_profit_rub"]
        target[base]["merchant_fee_sum"] += economics["merchant_fee_rub"]
    return by_buy, by_sell


def _parse_stats_arg(arg: str) -> tuple:
    from services.stats_period import parse_stats_period_arg

    return parse_stats_period_arg(
        arg,
        get_paid_for_date=get_paid_orders_for_date,
        get_paid_for_days=get_paid_orders_for_stats,
    )


async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats [N | DD.MM.YYYY] — за последние N дней или за конкретную дату (по created_at)."""
    from services.reports_group_guard import reply_wrong_reports_group

    if await reply_wrong_reports_group(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_reports_group_chat(chat_id):
        return
    if user_id not in TELEGRAM_ADMIN_IDS:
        if update.message:
            await update.message.reply_text("⛔ Команда только для администраторов.")
        else:
            await context.bot.send_message(chat_id=chat_id, text="⛔ Команда только для администраторов.")
        return

    show_profit = is_finance_owner(user_id)

    args = (context.args or [])
    # Без аргумента — статистика за сегодня (конкретная дата), иначе — переданный аргумент (число дней или дата)
    arg = args[0] if args else datetime.now().strftime("%d.%m.%Y")
    get_orders_fn, header_kw = _parse_stats_arg(arg)
    by_date = header_kw.get("by_date", False)

    orders = await get_orders_fn()
    if not orders:
        if by_date:
            no_orders_msg = f"📊 За <b>{header_kw['date_label']}</b> выплат (PAID) не было."
        elif header_kw.get("days") == 1:
            no_orders_msg = "📊 За последний 1 день выплат (PAID) не было."
        elif header_kw["days"] % 10 in (2, 3, 4) and header_kw["days"] % 100 not in (12, 13, 14):
            no_orders_msg = f"📊 За последние <b>{header_kw['days']}</b> дня выплат (PAID) не было."
        else:
            no_orders_msg = f"📊 За последние <b>{header_kw['days']}</b> дней выплат (PAID) не было."
        _chat_id = update.effective_chat.id
        if update.message:
            await update.message.reply_text(no_orders_msg, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=_chat_id, text=no_orders_msg, parse_mode="HTML")
        return

    by_buy, by_sell = _stats_aggregate_by_crypto_and_direction(orders)
    order_of_crypto = ["usdt", "btc", "trx", "ltc"]

    def _avg_rate_simple(total_fiat: float, total_crypto: float) -> float:
        """Усреднённый rate по сделкам этой крипты (без коэффициентов)."""
        if not total_crypto:
            return 0.0
        return total_fiat / total_crypto

    def _render_block(by_crypto: dict) -> tuple:
        """Возвращает строки и суммы по сохранённой экономике заявок."""
        lines_out = []
        total_fiat = 0.0
        total_profit = 0.0
        total_merchant_fee = 0.0
        for base in order_of_crypto:
            if base not in by_crypto:
                continue
            data = by_crypto[base]
            total_crypto = data["crypto_sum"]
            total_fiat_cur = data["fiat_sum"]
            total_fiat += total_fiat_cur
            total_profit += data["profit_sum"]
            total_merchant_fee += data["merchant_fee_sum"]
            avg_rate = _avg_rate_simple(total_fiat_cur, total_crypto)
            crypto_str = fmt_crypto(total_crypto, base)
            if show_profit:
                lines_out.append(
                    f"• <b>{base.upper()}</b>: {crypto_str} — <code>{total_fiat_cur:,.0f}</code> ₽ "
                    f"(ср. курс <code>{avg_rate:,.2f}</code> ₽, профит ~ <code>{data['profit_sum']:,.0f}</code> ₽)"
                )
            else:
                lines_out.append(
                    f"• <b>{base.upper()}</b>: {crypto_str} — <code>{total_fiat_cur:,.0f}</code> ₽ "
                    f"(ср. курс <code>{avg_rate:,.2f}</code> ₽)"
                )
        for base, data in by_crypto.items():
            if base in order_of_crypto:
                continue
            total_crypto = data["crypto_sum"]
            total_fiat_cur = data["fiat_sum"]
            total_fiat += total_fiat_cur
            total_profit += data["profit_sum"]
            total_merchant_fee += data["merchant_fee_sum"]
            avg_rate = _avg_rate_simple(total_fiat_cur, total_crypto)
            crypto_str = fmt_crypto(total_crypto, base)
            if show_profit:
                lines_out.append(
                    f"• <b>{base.upper()}</b>: {crypto_str} — <code>{total_fiat_cur:,.0f}</code> ₽ "
                    f"(ср. курс <code>{avg_rate:,.2f}</code> ₽, профит ~ <code>{data['profit_sum']:,.0f}</code> ₽)"
                )
            else:
                lines_out.append(
                    f"• <b>{base.upper()}</b>: {crypto_str} — <code>{total_fiat_cur:,.0f}</code> ₽ "
                    f"(ср. курс <code>{avg_rate:,.2f}</code> ₽)"
                )
        return lines_out, total_fiat, total_profit, total_merchant_fee

    buy_lines, total_fiat_buy, profit_buy, buy_merchant_fee = _render_block(by_buy)
    sell_lines, total_fiat_sell, profit_sell, _sell_merchant_fee = _render_block(by_sell)

    if by_date:
        header = f"📊 <b>Статистика за {header_kw['date_label']}</b> (PAID)\n\n"
    else:
        header = f"📊 <b>Статистика за {header_kw['last_word']} {header_kw['days']} {header_kw['period']}</b> (PAID)\n\n"

    parts = []

    # Блок BUY
    if buy_lines:
        parts.append("🔸 <b>Продали крипты</b>\n" + "\n".join(buy_lines))
        parts.append(f"📌 <b>Итого оплатили юзеры: </b> <code>{total_fiat_buy:,.0f}</code> ₽")
        if total_fiat_buy > 0:
            parts.append(
                f"   (комиссия мерча по зафиксированным сделкам: <code>{buy_merchant_fee:,.0f}</code> ₽)"
            )
        if show_profit:
            parts.append(f"💵 <b>Профит:</b> ~ <code>{profit_buy:,.0f}</code> ₽\n")
    else:
        parts.append("🔸 <b>Продали крипты</b> — за период не было\n")

    # Блок SELL
    if sell_lines:
        parts.append("🔹 <b>Купили крипты</b>\n" + "\n".join(sell_lines))
        parts.append(f"📌 <b>Итого выплатили юзерам:</b> <code>{total_fiat_sell:,.0f}</code> ₽")
        if show_profit:
            parts.append(f"💵 <b>Профит:</b> ~ <code>{profit_sell:,.0f}</code> ₽\n")
    else:
        parts.append("🔹 <b>Купили крипты</b> — за период не было\n")

    total_profit = profit_buy + profit_sell
    if show_profit:
        if by_date:
            d_obj = datetime.strptime(header_kw["date_label"], "%d.%m.%Y").date()
            review_bonus = await sum_review_bonus_rub_for_date(d_obj)
            wallet_payout = await sum_operator_wallet_payout_rub_for_date(d_obj)
            buy_network_fee = await sum_buy_network_fee_rub_for_date(d_obj)
        else:
            days = header_kw.get("days", 1)
            review_bonus = await sum_review_bonus_rub(days)
            wallet_payout = await sum_operator_wallet_payout_rub(days)
            buy_network_fee = await sum_buy_network_fee_rub(days)
        net_profit = total_profit - review_bonus - wallet_payout - buy_network_fee
        extras: list[str] = []
        if review_bonus > 0.009:
            extras.append(f"отзывы <code>{review_bonus:,.0f}</code> ₽")
        if wallet_payout > 0.009:
            extras.append(f"кошельки <code>{wallet_payout:,.0f}</code> ₽")
        if buy_network_fee > 0.009:
            extras.append(f"сеть <code>{buy_network_fee:,.0f}</code> ₽")
        if extras:
            parts.append(
                f"📊 <b>Общий профит:</b> ~ <code>{net_profit:,.0f}</code> ₽ "
                f"(минус {', '.join(extras)})"
            )
        else:
            parts.append(f"📊 <b>Общий профит:</b> ~ <code>{total_profit:,.0f}</code> ₽")

    # Промо-аналитика (только владельцу)
    if show_profit:
        promo_rows = await (
            get_promo_stats_for_date(datetime.strptime(header_kw["date_label"], "%d.%m.%Y").date())
            if by_date
            else get_promo_stats_for_days(header_kw.get("days", 1))
        )
        promo_orders = await (
            get_promo_paid_orders_for_date(datetime.strptime(header_kw["date_label"], "%d.%m.%Y").date())
            if by_date
            else get_promo_paid_orders_for_days(header_kw.get("days", 1))
        )

        campaign_profit_map = {}
        for o in promo_orders:
            cid = int(o["campaign_id"])
            profit = order_economics(dict(o), clamp=False)["service_profit_rub"]
            campaign_profit_map[cid] = campaign_profit_map.get(cid, 0.0) + profit

        promo_lines = []
        for r in promo_rows:
            attracted = int(r["attracted_users"] or 0)
            if attracted <= 0:
                continue
            paid_fiat_sum = float(r["paid_fiat_sum"] or 0.0)
            bonus_percent = float(r["bonus_percent"] or 0.0)
            ad_spend = float(r["ad_spend_rub"] or 0.0)
            campaign_profit = float(campaign_profit_map.get(int(r["id"]), 0.0))
            bonus_cost = campaign_profit * (bonus_percent / 100.0)
            analytics_net = campaign_profit - bonus_cost - ad_spend
            roi = ((analytics_net / ad_spend) * 100.0) if ad_spend > 0 else 0.0
            promo_lines.append(
                f"• <b>{r['name']}</b> (<code>{r['code']}</code>): "
                f"юзеров <code>{attracted}</code>, "
                f"профит <code>{campaign_profit:,.0f}</code> ₽, "
                f"бонус {bonus_percent:.2f}% (~<code>{bonus_cost:,.0f}</code> ₽), "
                f"реклама <code>{ad_spend:,.0f}</code> ₽, ROI ~ <code>{roi:,.1f}%</code>"
            )
        if promo_lines:
            parts.append("\n🎯 <b>Promo аналитика</b>\n" + "\n".join(promo_lines))

    text = header + "\n".join(parts)
    chat_id = update.effective_chat.id
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


# ============================================================
# /promo — управление промо-кампаниями (только админ-группа)
# ============================================================

def _promo_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Создать промо", callback_data="promo:create")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data="promo:edit")],
    ])


def _promo_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="promo:cancel_flow")]
    ])


def _promo_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Создать", callback_data="promo:create_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="promo:create_cancel"),
        ]
    ])


def _promo_actions_keyboard(campaign_id: int, is_active: bool) -> InlineKeyboardMarkup:
    active_btn = "⏸ Деактивировать" if is_active else "▶️ Активировать"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить % бонуса", callback_data=f"promo:set_bonus:{campaign_id}")],
        [InlineKeyboardButton(active_btn, callback_data=f"promo:toggle_active:{campaign_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"promo:delete:{campaign_id}")],
        [InlineKeyboardButton("⬅️ Назад к списку", callback_data="promo:edit")],
    ])


async def _promo_panel_send_or_edit(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
):
    panel_chat_id = context.chat_data.get("promo_panel_chat_id")
    panel_message_id = context.chat_data.get("promo_panel_message_id")
    if panel_chat_id and panel_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
    context.chat_data["promo_panel_chat_id"] = sent.chat_id
    context.chat_data["promo_panel_message_id"] = sent.message_id


async def promo_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not is_reports_group_chat(chat_id):
        return
    if user_id not in TELEGRAM_ADMIN_IDS:
        await update.message.reply_text("⛔ Команда только для администраторов.")
        return

    context.chat_data.pop("promo_state", None)
    context.chat_data.pop("promo_draft", None)
    context.chat_data.pop("promo_edit_id", None)
    await _promo_panel_send_or_edit(
        context,
        chat_id,
        "🎯 <b>Промо-меню</b>\n\nВыберите действие:",
        reply_markup=_promo_main_keyboard(),
    )


async def promo_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not is_reports_group_chat(chat_id) or user_id not in TELEGRAM_ADMIN_IDS:
        return

    context.chat_data["promo_panel_chat_id"] = query.message.chat_id
    context.chat_data["promo_panel_message_id"] = query.message.message_id

    data = query.data or ""
    if not data.startswith("promo:"):
        return

    if data == "promo:create":
        context.chat_data["promo_state"] = "create_name"
        context.chat_data["promo_draft"] = {}
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "Введите <b>название промо</b> (для внутренней статистики).",
            reply_markup=_promo_cancel_keyboard(),
        )
        return

    if data == "promo:cancel_flow":
        context.chat_data.pop("promo_state", None)
        context.chat_data.pop("promo_draft", None)
        context.chat_data.pop("promo_edit_id", None)
        await _promo_panel_send_or_edit(context, chat_id, "❌ Действие отменено.", reply_markup=_promo_main_keyboard())
        return

    if data == "promo:create_cancel":
        context.chat_data.pop("promo_state", None)
        context.chat_data.pop("promo_draft", None)
        await _promo_panel_send_or_edit(context, chat_id, "❌ Создание промо отменено.", reply_markup=_promo_main_keyboard())
        return

    if data == "promo:create_confirm":
        draft = context.chat_data.get("promo_draft") or {}
        if not draft:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Черновик промо не найден. Начните заново: /promo")
            return
        created = None
        last_error = None
        for _ in range(10):
            code = _make_promo_code()
            try:
                created = await create_promo_campaign(
                    code=code,
                    name=draft["name"],
                    bonus_percent=draft["bonus_percent"],
                    ad_spend_rub=draft["ad_spend_rub"],
                    created_by=user_id,
                )
                break
            except asyncpg.UniqueViolationError:
                continue
            except Exception as e:
                last_error = str(e)
                break
        if not created:
            if last_error:
                await _promo_panel_send_or_edit(context, chat_id, f"❌ Не удалось создать промо: <code>{last_error}</code>")
            else:
                await _promo_panel_send_or_edit(context, chat_id, "❌ Не удалось создать промо (повторите попытку).")
            return

        bot_username = context.bot.username
        if not bot_username:
            me = await context.bot.get_me()
            bot_username = me.username
        from services.referral_links import telegram_deep_link, web_ref_link

        ref_tok = created.get("ref_token") or created["code"]
        promo_link = telegram_deep_link(ref_tok, bot_username)
        web_link = web_ref_link(
            ref_tok,
            os.getenv("PUBLIC_SITE_URL", "http://localhost:5173"),
        )

        context.chat_data.pop("promo_state", None)
        context.chat_data.pop("promo_draft", None)
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "✅ <b>Промо создано</b>\n\n"
            f"Название: <b>{created['name']}</b>\n"
            f"Код: <code>{created['code']}</code>\n"
            f"Бонус: <code>{float(created['bonus_percent']):.2f}%</code>\n"
            f"Рекламный бюджет: <code>{float(created['ad_spend_rub']):,.0f}</code> ₽\n\n"
            f"Ссылка (Telegram):\n<code>{promo_link}</code>\n\n"
            f"Ссылка для рекламы (сайт → бот):\n<code>{web_link}</code>",
            reply_markup=_promo_main_keyboard(),
        )
        return

    if data == "promo:edit":
        rows = await list_promo_campaigns(active_only=False, limit=30)
        if not rows:
            await _promo_panel_send_or_edit(context, chat_id, "ℹ️ Промо-кампаний пока нет.", reply_markup=_promo_main_keyboard())
            return
        keyboard = []
        for row in rows:
            flag = "🟢" if row["is_active"] else "⚪"
            keyboard.append(
                [InlineKeyboardButton(
                    f"{flag} {row['name']} ({row['code']})",
                    callback_data=f"promo:open:{row['id']}",
                )]
            )
        keyboard.append([InlineKeyboardButton("⬅️ В меню /promo", callback_data="promo:cancel_flow")])
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "Выберите кампанию для редактирования:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None,
        )
        return

    if data.startswith("promo:open:"):
        campaign_id = int(data.split(":")[2])
        row = await get_promo_campaign_by_id(campaign_id)
        if not row:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Кампания не найдена.")
            return
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "🎯 <b>Кампания</b>\n"
            f"Название: <b>{row['name']}</b>\n"
            f"Код: <code>{row['code']}</code>\n"
            f"Бонус: <code>{float(row['bonus_percent']):.2f}%</code>\n"
            f"Бюджет: <code>{float(row['ad_spend_rub']):,.0f}</code> ₽\n"
            f"Статус: <b>{'активна' if row['is_active'] else 'неактивна'}</b>",
            reply_markup=_promo_actions_keyboard(campaign_id, bool(row["is_active"])),
        )
        return

    if data.startswith("promo:set_bonus:"):
        campaign_id = int(data.split(":")[2])
        row = await get_promo_campaign_by_id(campaign_id)
        if not row:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Кампания не найдена.")
            return
        context.chat_data["promo_state"] = "edit_bonus"
        context.chat_data["promo_edit_id"] = campaign_id
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            f"Введите новый бонус % для <b>{row['name']}</b> (текущее: {float(row['bonus_percent']):.2f}%).",
            reply_markup=_promo_cancel_keyboard(),
        )
        return

    if data.startswith("promo:toggle_active:"):
        campaign_id = int(data.split(":")[2])
        row = await get_promo_campaign_by_id(campaign_id)
        if not row:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Кампания не найдена.")
            return
        updated = await set_promo_campaign_active(campaign_id, not bool(row["is_active"]))
        status_txt = "активирована" if updated["is_active"] else "деактивирована"
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            f"✅ Кампания <b>{updated['name']}</b> {status_txt}.",
            reply_markup=_promo_actions_keyboard(campaign_id, bool(updated["is_active"])),
        )
        return

    if data.startswith("promo:delete:"):
        campaign_id = int(data.split(":")[2])
        row = await get_promo_campaign_by_id(campaign_id)
        if not row:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Кампания не найдена.")
            return
        has_data = await promo_campaign_has_attributions(campaign_id)
        if has_data:
            await _promo_panel_send_or_edit(
                context,
                chat_id,
                "❌ Нельзя удалить кампанию: по ней уже есть привлечённые пользователи.\n"
                "Используйте деактивацию.",
                reply_markup=_promo_actions_keyboard(campaign_id, bool(row["is_active"])),
            )
            return
        ok = await delete_promo_campaign(campaign_id)
        if ok:
            await _promo_panel_send_or_edit(context, chat_id, "🗑 Кампания удалена.", reply_markup=_promo_main_keyboard())
        else:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Не удалось удалить кампанию.")
        return


async def promo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not is_reports_group_chat(chat_id) or user_id not in TELEGRAM_ADMIN_IDS:
        return
    msg = update.message
    if not msg or not msg.text or msg.text.strip().startswith("/"):
        return

    state = context.chat_data.get("promo_state")
    if not state:
        return

    try:
        await msg.delete()
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)

    text = msg.text.strip()
    if state == "create_name":
        context.chat_data["promo_draft"] = {"name": text}
        context.chat_data["promo_state"] = "create_bonus"
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "Введите бонус в % (например: <code>10</code>).",
            reply_markup=_promo_cancel_keyboard(),
        )
        return

    if state == "create_bonus":
        try:
            bonus = float(text.replace(",", "."))
            if bonus < 0 or bonus > 100:
                raise ValueError
        except ValueError:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Некорректный процент. Введите число от 0 до 100.")
            return
        draft = context.chat_data.get("promo_draft") or {}
        draft["bonus_percent"] = bonus
        context.chat_data["promo_draft"] = draft
        context.chat_data["promo_state"] = "create_ad_spend"
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "Введите бюджет рекламы в ₽ (например: <code>15000</code>).",
            reply_markup=_promo_cancel_keyboard(),
        )
        return

    if state == "create_ad_spend":
        try:
            ad_spend = float(text.replace(" ", "").replace(",", "."))
            if ad_spend < 0:
                raise ValueError
        except ValueError:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Некорректная сумма. Введите число >= 0.")
            return
        draft = context.chat_data.get("promo_draft") or {}
        draft["ad_spend_rub"] = ad_spend
        context.chat_data["promo_draft"] = draft
        context.chat_data["promo_state"] = "create_confirm"
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            "Проверьте данные:\n\n"
            f"Название: <b>{draft['name']}</b>\n"
            f"Бонус: <code>{draft['bonus_percent']:.2f}%</code>\n"
            f"Рекламный бюджет: <code>{draft['ad_spend_rub']:,.0f}</code> ₽\n\n"
            "Подтвердить создание?",
            reply_markup=_promo_confirm_keyboard(),
        )
        return

    if state == "edit_bonus":
        campaign_id = context.chat_data.get("promo_edit_id")
        if not campaign_id:
            context.chat_data.pop("promo_state", None)
            await _promo_panel_send_or_edit(context, chat_id, "❌ Режим редактирования сброшен. Вызовите /promo заново.")
            return
        try:
            bonus = float(text.replace(",", "."))
            if bonus < 0 or bonus > 100:
                raise ValueError
        except ValueError:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Некорректный процент. Введите число от 0 до 100.")
            return
        updated = await update_promo_bonus_percent(campaign_id, bonus)
        context.chat_data.pop("promo_state", None)
        context.chat_data.pop("promo_edit_id", None)
        if not updated:
            await _promo_panel_send_or_edit(context, chat_id, "❌ Кампания не найдена.")
            return
        await _promo_panel_send_or_edit(
            context,
            chat_id,
            f"✅ У кампании <b>{updated['name']}</b> новый бонус: <code>{float(updated['bonus_percent']):.2f}%</code>.",
            reply_markup=_promo_actions_keyboard(campaign_id, bool(updated["is_active"])),
        )


# ============================================================
# /post — рассылка (фото + текст), только админ-группа и только админы
# ============================================================

BROADCAST_DELAY = 0.05  # секунд между сообщениями (лимиты Telegram)


def _post_segment_label(segment: str) -> str:
    labels = {
        "all": "все пользователи",
        "inactive7": "не заходили 7+ дней",
        "paid": "хотя бы 1 PAID",
        "referrers": "есть приглашённые (рефералы)",
    }
    return labels.get(segment, labels["all"])


def _can_prepare_broadcast(user) -> bool:
    if not user:
        return False
    if int(user.id) in TELEGRAM_ADMIN_IDS:
        return True
    if is_broadcast_copy_account(getattr(user, "username", None)):
        return True
    from services.config_rates import is_reports_user

    return is_reports_user(int(user.id), getattr(user, "username", None))


def _is_reply_to_bot(msg) -> bool:
    reply = getattr(msg, "reply_to_message", None)
    author = getattr(reply, "from_user", None) if reply else None
    return bool(author and getattr(author, "is_bot", False))


def _is_forwarded(msg) -> bool:
    return bool(getattr(msg, "forward_origin", None) or getattr(msg, "forward_date", None))


def _should_capture_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Текст для черновика: пересылка, ответ боту или сообщение @absoluteop."""
    msg = update.message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or getattr(user, "is_bot", False):
        return False
    if msg.text and msg.text.strip().startswith("/"):
        return False
    if not (msg.text or msg.caption or msg.photo):
        return False
    if chat.type == "private":
        body = (msg.text or msg.caption or "").strip()
        return _can_prepare_broadcast(user) or (_is_forwarded(msg) and len(body) >= 80)
    if not is_reports_group_chat(chat.id):
        return False
    if context.chat_data.get("awaiting_broadcast"):
        return True
    if is_broadcast_copy_account(getattr(user, "username", None)):
        return True
    if _can_prepare_broadcast(user) and (_is_forwarded(msg) or _is_reply_to_bot(msg)):
        return True
    # В отчётах пересланный пост — это и есть материал рассылки.
    return _is_forwarded(msg)


async def post_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /post [all|inactive7|paid|referrers]: рассылка по сегменту."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    in_private = bool(update.effective_chat and update.effective_chat.type == "private")
    if not is_reports_group_chat(chat_id) and not in_private:
        return
    if in_private and not _can_prepare_broadcast(user) and not _is_forwarded(update.message):
        await update.message.reply_text("⛔ Команда только для администраторов.")
        return

    segment = "all"
    args = context.args or []
    if args and args[0].strip().lower() in BROADCAST_SEGMENTS:
        segment = args[0].strip().lower()
    context.chat_data["broadcast_segment"] = segment

    # В группе состояние храним в chat_data, иначе следующий апдейт (фото) не увидит состояние
    context.chat_data["awaiting_broadcast"] = "photo"
    await update.message.reply_text(
        "📢 <b>Рассылка</b>\n\n"
        f"Сегмент: <b>{html.escape(_post_segment_label(segment))}</b>\n"
        "<i>/post inactive7 · paid · referrers · all</i>\n\n"
        "Перешлите готовый пост <b>ответом на это сообщение</b>.\n"
        "Обычная пересылка в чат боту не видна: он не администратор группы.\n"
        "Черновик сохранится со стикерами и сам не уйдёт.",
        parse_mode="HTML",
    )


async def post_broadcast_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает фото или текст от админа в режиме рассылки (/post)."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    if not is_reports_group_chat(chat_id):
        return
    msg = update.message
    if not msg:
        return
    # Не перехватывать команды (/, /post и т.д.)
    if msg.text and msg.text.strip().startswith("/"):
        return

    state = context.chat_data.get("awaiting_broadcast")
    if not _can_prepare_broadcast(user):
        return
    if not state and user and is_broadcast_copy_account(getattr(user, "username", None)):
        await _save_copy_account_message(update, context)
        return
    if not state:
        return

    if state == "photo":
        if msg.photo:
            photo = msg.photo[-1]
            context.chat_data["broadcast_photo_file_id"] = photo.file_id
            caption = ""
            if (msg.caption or "").strip():
                caption = prepare_broadcast_text(
                    msg.caption or "",
                    list(msg.caption_entities or []),
                    max_len=1024,
                )
            context.chat_data["broadcast_caption"] = caption
            if caption:
                await _save_draft_and_preview(update, context, kind="photo")
            else:
                context.chat_data["awaiting_broadcast"] = "text"
                await update.message.reply_text("✅ Фото принято. Отправьте <b>текст поста</b> (или «−» без текста).", parse_mode="HTML")
            return
        if msg.text:
            context.chat_data["broadcast_text_only"] = prepare_broadcast_text(
                msg.text,
                list(msg.entities or []),
                max_len=4096,
            )
            await _save_draft_and_preview(update, context, kind="text")
            return
        await update.message.reply_text("❌ Отправьте фото или текст.")
        return

    if state == "text":
        if not msg.text:
            await update.message.reply_text("❌ Отправьте текст сообщением или «−» чтобы оставить без текста.")
            return
        raw = msg.text.strip()
        if raw == "−":
            context.chat_data["broadcast_caption"] = ""
        else:
            context.chat_data["broadcast_caption"] = prepare_broadcast_text(
                msg.text,
                list(msg.entities or []),
                max_len=1024,
            )
        await _save_draft_and_preview(update, context, kind="photo")


def _broadcast_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить", callback_data="broadcast:send"),
            InlineKeyboardButton("❌ Отменить", callback_data="broadcast:cancel"),
        ]
    ])


def _draft_sender_label(update: Update) -> str:
    user = update.effective_user
    if user and user.username:
        return f"@{user.username}"[:80]
    if user:
        return f"tg:{user.id}"[:80]
    return "tg"


async def _save_copy_account_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Текст @absoluteop в отчётах сразу становится черновиком со стикерами."""
    msg = update.message
    if not msg:
        return
    context.chat_data["broadcast_segment"] = context.chat_data.get("broadcast_segment") or "all"
    if msg.photo:
        context.chat_data["broadcast_photo_file_id"] = msg.photo[-1].file_id
        context.chat_data["broadcast_caption"] = prepare_broadcast_text(
            msg.caption or "",
            list(msg.caption_entities or []),
            max_len=1024,
        )
        context.chat_data.pop("broadcast_text_only", None)
        await _save_draft_and_preview(update, context, kind="photo")
        return
    text = prepare_broadcast_text(msg.text or "", list(msg.entities or []), max_len=4096)
    if not text.strip():
        return
    context.chat_data.pop("broadcast_photo_file_id", None)
    context.chat_data["broadcast_text_only"] = text
    await _save_draft_and_preview(update, context, kind="text")


async def _save_draft_and_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    """Сохраняет подготовленный текст черновиком и показывает его в чате."""
    photo_file_id = context.chat_data.get("broadcast_photo_file_id")
    if kind == "photo":
        text = (context.chat_data.get("broadcast_caption") or "").strip()
    else:
        text = (context.chat_data.get("broadcast_text_only") or "").strip()
    if not text and not photo_file_id:
        await update.message.reply_text("❌ Нужен текст или фото.")
        return
    segment = context.chat_data.get("broadcast_segment") or "all"
    try:
        draft_id = await insert_broadcast_draft(
            segment=str(segment),
            message_text=text,
            photo_file_id=photo_file_id,
            sender_label=_draft_sender_label(update),
        )
    except Exception:
        logger.exception("broadcast draft save failed")
        await update.message.reply_text("❌ Не удалось сохранить черновик.")
        return
    context.chat_data["broadcast_draft_id"] = draft_id
    await _show_broadcast_preview(update, context, kind=kind)


async def _show_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    """Показывает сохранённый текст со стикерами и кнопки Отправить / Отменить."""
    context.chat_data["awaiting_broadcast"] = "confirm"
    chat_id = update.effective_chat.id
    draft_id = context.chat_data.get("broadcast_draft_id")

    if kind == "photo":
        photo_file_id = context.chat_data.get("broadcast_photo_file_id")
        caption = sanitize_telegram_html(
            (context.chat_data.get("broadcast_caption") or "").strip(),
            max_len=1024,
        )
        photo_kwargs = {"chat_id": chat_id, "photo": photo_file_id}
        if caption:
            photo_kwargs["caption"] = caption
            photo_kwargs["parse_mode"] = "HTML"
        await context.bot.send_photo(**photo_kwargs)
    else:
        text = sanitize_telegram_html(context.chat_data.get("broadcast_text_only", "") or "")
        if text:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except Exception:
                logger.exception("broadcast preview html failed")
                plain = re.sub(r"<[^>]+>", "", text)
                await context.bot.send_message(chat_id=chat_id, text=plain[:4000])

    note = f"Черновик #{draft_id} сохранён. В рассылку не ушёл."
    await context.bot.send_message(
        chat_id=chat_id,
        text=note,
        reply_markup=_broadcast_confirm_keyboard(),
    )


async def broadcast_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок Отправить / Отменить под превью рассылки (только админы)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else query.message.chat_id

    in_private = bool(update.effective_chat and update.effective_chat.type == "private")
    if not is_reports_group_chat(chat_id) and not in_private:
        return
    if not in_private and not _can_prepare_broadcast(update.effective_user) and not context.chat_data.get("broadcast_draft_id"):
        return
    if context.chat_data.get("awaiting_broadcast") != "confirm":
        try:
            await query.edit_message_caption(caption="⏭ Рассылка уже обработана или отменена.")
        except Exception:
            try:
                await query.edit_message_text("⏭ Рассылка уже обработана или отменена.")
            except Exception:
                logger.debug("ignored non-fatal error", exc_info=True)
        return

    msg = query.message

    if query.data == "broadcast:cancel":
        draft_id = context.chat_data.pop("broadcast_draft_id", None)
        context.chat_data.pop("broadcast_photo_file_id", None)
        context.chat_data.pop("broadcast_caption", None)
        context.chat_data.pop("broadcast_text_only", None)
        context.chat_data.pop("awaiting_broadcast", None)
        if draft_id:
            try:
                await cancel_broadcast_draft(int(draft_id))
            except Exception:
                logger.exception("broadcast draft cancel failed")
        no_kb = InlineKeyboardMarkup([])
        try:
            if msg.photo:
                await msg.edit_caption(caption="❌ Черновик отменён.", reply_markup=no_kb)
            else:
                await msg.edit_text("❌ Черновик отменён.", reply_markup=no_kb)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text="❌ Черновик отменён.")
        return

    if query.data != "broadcast:send":
        return

    draft_id = context.chat_data.pop("broadcast_draft_id", None)
    context.chat_data.pop("awaiting_broadcast", None)
    context.chat_data.pop("broadcast_photo_file_id", None)
    context.chat_data.pop("broadcast_caption", None)
    context.chat_data.pop("broadcast_text_only", None)
    queued = False
    if draft_id:
        try:
            queued = await launch_broadcast_draft(int(draft_id))
        except Exception:
            logger.exception("broadcast draft launch failed")
    note = (
        f"Черновик #{draft_id} поставлен в очередь."
        if queued
        else "❌ Не удалось поставить черновик в очередь. Откройте его в панели рассылки."
    )
    no_kb = InlineKeyboardMarkup([])
    try:
        if msg.photo:
            await msg.edit_caption(caption=note, reply_markup=no_kb)
        else:
            await msg.edit_text(note, reply_markup=no_kb)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=note)


async def _run_broadcast(
    context: ContextTypes.DEFAULT_TYPE,
    reply_chat_id: int,
    reply_msg,
    photo_file_id: str,
    caption: str,
):
    """Рассылка фото + подпись по сегменту bot_users."""
    segment = context.chat_data.pop("broadcast_segment", "all")
    user_ids = await get_broadcast_user_ids(segment)
    if not user_ids:
        await context.bot.send_message(reply_chat_id, "📭 В базе нет пользователей для рассылки.")
        return

    sent = 0
    failed = 0
    seg_lbl = _post_segment_label(segment)
    await context.bot.send_message(
        reply_chat_id,
        f"📤 Рассылка (фото) · {seg_lbl} ({len(user_ids)} получателей)…",
    )

    for uid in user_ids:
        try:
            await context.bot.send_photo(
                chat_id=uid,
                photo=photo_file_id,
                caption=caption if caption else None,
                parse_mode="HTML" if caption else None,
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY)

    no_kb = InlineKeyboardMarkup([])
    try:
        if reply_msg.photo:
            await reply_msg.edit_caption(caption="✅ Рассылка отправлена.", reply_markup=no_kb)
        else:
            await reply_msg.edit_text("✅ Рассылка отправлена.", reply_markup=no_kb)
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    await context.bot.send_message(
        reply_chat_id,
        f"✅ <b>Рассылка завершена</b>\n\nДоставлено: <code>{sent}</code>\nНе доставлено: <code>{failed}</code>",
        parse_mode="HTML",
    )


async def _run_broadcast_text(context: ContextTypes.DEFAULT_TYPE, reply_chat_id: int, reply_msg, text: str):
    """Рассылка только текстом по сегменту."""
    segment = context.chat_data.pop("broadcast_segment", "all")
    user_ids = await get_broadcast_user_ids(segment)
    if not user_ids:
        await context.bot.send_message(reply_chat_id, "📭 В базе нет пользователей для рассылки.")
        return

    sent = 0
    failed = 0
    seg_lbl = _post_segment_label(segment)
    await context.bot.send_message(
        reply_chat_id,
        f"📤 Рассылка (текст) · {seg_lbl} ({len(user_ids)} получателей)…",
    )

    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY)

    no_kb = InlineKeyboardMarkup([])
    try:
        await reply_msg.edit_text("✅ Рассылка отправлена.", reply_markup=no_kb)
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    await context.bot.send_message(
        reply_chat_id,
        f"✅ <b>Рассылка завершена</b>\n\nДоставлено: <code>{sent}</code>\nНе доставлено: <code>{failed}</code>",
        parse_mode="HTML",
    )


async def _admin_refwd_tx_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: dict,
    admin_user_id: int,
) -> None:
    from services.buy_payout import build_explorer_url
    from services.payout_pending_store import clear_pending, clear_user_data_pending
    from services.user_referral_withdraw import (
        confirm_withdrawal_crypto_payout,
        format_withdrawal_admin_message,
        get_withdrawal,
    )

    withdrawal_id = pending.get("withdrawal_id")
    if not withdrawal_id:
        clear_pending(context.application.bot_data, pending)
        clear_user_data_pending(context, "refwd")
        return

    tx_text = update.message.text.strip()
    ok, err, wd = await confirm_withdrawal_crypto_payout(int(withdrawal_id), tx_text)

    if err == "already_processed":
        clear_pending(context.application.bot_data, pending)
        clear_user_data_pending(context, "refwd")
        await update.message.reply_text(
            "ℹ️ Заявка на вывод уже обработана.",
            parse_mode="HTML",
        )
        return
    if err == "invalid_tx":
        await update.message.reply_text(
            "❌ Некорректный hash. Отправьте txid (минимум 8 символов, без пробелов).",
            parse_mode="HTML",
        )
        return
    if err == "insufficient_balance":
        clear_pending(context.application.bot_data, pending)
        clear_user_data_pending(context, "refwd")
        await update.message.reply_text(
            "❌ Недостаточно средств на балансе пользователя для этой выплаты.",
            parse_mode="HTML",
        )
        return
    if not ok or not wd:
        await update.message.reply_text(
            f"❌ Не удалось подтвердить вывод #{withdrawal_id}.",
            parse_mode="HTML",
        )
        return

    clear_pending(context.application.bot_data, pending)
    clear_user_data_pending(context, "refwd")

    crypto_key = (wd.get("crypto") or "").lower()
    net = (wd.get("network") or "").lower()
    explorer_key = f"{crypto_key}_{net}" if net else crypto_key
    explorer = build_explorer_url(explorer_key, tx_text)

    try:
        await context.bot.send_message(
            chat_id=wd["referrer_user_id"],
            text=(
                f"✅ Ваша заявка на вывод #{withdrawal_id} "
                f"на сумму <b>{float(wd['amount_rub']):,.2f} ₽</b> выполнена."
                + (f'\n🔗 <a href="{explorer}">Транзакция</a>' if explorer else "")
            ),
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    except Exception as e:
        print(f"[refwd] notify user {wd.get('referrer_user_id')}: {e}")

    wd_row = await get_withdrawal(withdrawal_id)
    if wd_row:
        base = format_withdrawal_admin_message(dict(wd_row), None)
        try:
            await context.bot.edit_message_text(
                chat_id=pending.get("chat_id") or update.effective_chat.id,
                message_id=pending.get("card_message_id") or pending.get("message_id"),
                text=f"{base}\n\n✅ <b>Выплачено</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([]),
            )
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)

    await update.message.reply_text(
        f"✅ Вывод #{withdrawal_id} подтверждён · админ <code>{admin_user_id}</code>\n"
        + (f'<a href="{explorer}">Транзакция</a>' if explorer else ""),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


async def operator_payroll_payout_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Выплата / отклонение заявки оператора на зарплату (opay:action:id)."""
    query = update.callback_query
    await query.answer()

    if not is_finance_owner(query.from_user.id):
        await query.answer("⛔ Только владелец финансов", show_alert=True)
        return

    try:
        parts = query.data.split(":")
        prefix, action, req_id_s = parts[0], parts[1], parts[2]
        signature = parts[3] if len(parts) > 3 else ""
        request_id = int(req_id_s)
    except (ValueError, IndexError):
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    if prefix != "opay" or action not in ("paid", "reject"):
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    from services.callback_signatures import verify_operator_payroll_signature

    if not verify_operator_payroll_signature(request_id, signature):
        await query.answer("🚨 Подделка запроса", show_alert=True)
        return

    import os
    import sys

    ex_root = os.environ.get("EXCHANGE_BACKEND_PATH", "/opt/exchange-backend")
    if ex_root not in sys.path:
        sys.path.insert(0, ex_root)
    from operator_payroll_pool import (
        process_request_paid,
        process_request_rejected,
    )
    from services.db import get_pool

    if action == "paid":
        req = await process_request_paid(request_id)
        status_text = "✅ <b>Выплачено</b>"
    else:
        req = await process_request_rejected(request_id)
        status_text = "❌ <b>Отклонено</b>"

    if not req:
        await query.answer("Заявка уже обработана", show_alert=True)
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        op = await conn.fetchrow(
            "SELECT username, display_name FROM operator_accounts WHERE id = $1",
            req["operator_id"],
        )
    name = (op["display_name"] or op["username"]) if op else str(req["operator_id"])

    try:
        base = query.message.text_html or query.message.text or ""
        await query.message.edit_text(
            f"{base}\n\n{status_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([]),
        )
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)


async def referral_withdrawal_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Выплата / отклонение заявки на вывод реферальных (refwd:action:id:sig)."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id if query.message else None
    if not (is_ops_group_chat(chat_id) or is_reports_group_chat(chat_id)):
        await query.answer("⛔ Действие только в группе операторов", show_alert=True)
        return

    if query.from_user.id not in TELEGRAM_ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        prefix, action, wd_id_s, signature = query.data.split(":", 3)
    except ValueError:
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    if prefix != "refwd" or action not in ("paid", "reject"):
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    try:
        withdrawal_id = int(wd_id_s)
    except ValueError:
        await query.answer("❌ Неверный ID", show_alert=True)
        return

    from services.user_referral_withdraw import (
        get_withdrawal,
        process_withdrawal_paid,
        process_withdrawal_rejected,
        verify_withdrawal_signature,
    )

    if not verify_withdrawal_signature(withdrawal_id, signature):
        await query.answer("🚨 Подделка запроса", show_alert=True)
        return

    if action == "paid":
        wd_pending = await get_withdrawal(withdrawal_id)
        if not wd_pending or wd_pending["status"] != "pending":
            await query.answer("Заявка уже обработана", show_alert=True)
            return
        if (wd_pending["method"] or "").lower() == "crypto":
            await _send_hash_prompt(
                context,
                query,
                kind="refwd",
                chat_id=chat_id,
                user_id=user_id,
                card_message_id=query.message.message_id,
                prompt_text=f"📤 Вывод баланса <b>#{withdrawal_id}</b>",
                payload={"withdrawal_id": withdrawal_id},
            )
            return

        wd = await process_withdrawal_paid(withdrawal_id)
        if not wd:
            pool = await get_pool()
            async with pool.acquire() as conn:
                from services.user_unified_balance import unified_available

                wd_chk = await conn.fetchrow(
                    "SELECT referrer_user_id, amount_rub, status FROM user_referral_withdrawals WHERE id = $1",
                    withdrawal_id,
                )
            if not wd_chk or wd_chk["status"] != "pending":
                await query.answer("Заявка уже обработана", show_alert=True)
            else:
                async with pool.acquire() as conn:
                    avail = await unified_available(conn, int(wd_chk["referrer_user_id"]))
                    avail += float(wd_chk["amount_rub"])
                    if float(wd_chk["amount_rub"]) > avail + 0.01:
                        await query.answer(
                            f"Недостаточно средств на балансе ({avail:,.0f} ₽)",
                            show_alert=True,
                        )
                    else:
                        await query.answer("Не удалось провести выплату", show_alert=True)
            return
        status_text = "✅ <b>Выплачено</b>"
        user_text = (
            f"✅ Ваша заявка на вывод реферальных #{withdrawal_id} "
            f"на сумму <b>{float(wd['amount_rub']):,.2f} ₽</b> выполнена."
        )
    else:
        context.user_data.pop("pending_refwd_tx", None)
        wd = await process_withdrawal_rejected(withdrawal_id)
        if not wd:
            await query.answer("Заявка уже обработана", show_alert=True)
            return
        status_text = "❌ <b>Отклонено</b>"
        user_text = (
            f"❌ Заявка на вывод #{withdrawal_id} отклонена. "
            f"Средства остаются на балансе. По вопросам: {SUPPORT_USERNAME}"
        )

    try:
        await context.bot.send_message(
            chat_id=wd["referrer_user_id"],
            text=user_text,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"[refwd] notify user {wd.get('referrer_user_id')}: {e}")

    try:
        base = query.message.text_html or query.message.text or ""
        await query.message.edit_text(
            f"{base}\n\n{status_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([]),
        )
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)


_EXTWD_RECEIPT_PROMPT = (
    "Ответьте <b>reply</b> на это сообщение с чеком (PDF или фото).\n"
    "После загрузки заявка будет закрыта как выплаченная."
)


async def _send_extwd_receipt_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    *,
    chat_id: int,
    user_id: int,
    card_message_id: int,
    payout_id: int,
) -> None:
    from services.payout_pending_store import save_pending, sync_user_data_pending

    await query.answer()
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📎 Вывод внештата <b>#{payout_id}</b>\n{_EXTWD_RECEIPT_PROMPT}"
        ),
        parse_mode="HTML",
        reply_to_message_id=card_message_id,
    )
    payload = {"payout_id": payout_id}
    save_pending(
        context.application.bot_data,
        kind="extwd_receipt",
        chat_id=chat_id,
        user_id=user_id,
        prompt_message_id=sent.message_id,
        card_message_id=card_message_id,
        payload=payload,
    )
    sync_user_data_pending(
        context,
        kind="extwd_receipt",
        chat_id=chat_id,
        user_id=user_id,
        card_message_id=card_message_id,
        payload=payload,
    )


async def external_payout_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Пропуск / чек / отклонение вывода внештатника (extwd:action:id:sig)."""
    query = update.callback_query
    if not query or not query.message:
        return

    chat_id = query.message.chat_id
    if not (is_ops_group_chat(chat_id) or is_reports_group_chat(chat_id)):
        await query.answer("⛔ Только в reports / ops группе", show_alert=True)
        return
    if query.from_user.id not in TELEGRAM_ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        prefix, action, pid_s, signature = (query.data or "").split(":", 3)
    except ValueError:
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    if prefix != "extwd" or action not in ("skip", "receipt", "reject"):
        await query.answer("❌ Неверные данные", show_alert=True)
        return

    try:
        payout_id = int(pid_s)
    except ValueError:
        await query.answer("❌ Неверный ID", show_alert=True)
        return

    from services.callback_signatures import verify_external_payout_signature
    from services.external_payout_admin import (
        get_payout,
        process_payout_paid,
        process_payout_rejected,
    )

    if not verify_external_payout_signature(payout_id, signature):
        await query.answer("🚨 Подделка запроса", show_alert=True)
        return

    user_id = query.from_user.id
    op_label = html.escape(query.from_user.username or str(user_id))

    if action == "receipt":
        pending = await get_payout(payout_id)
        if not pending or pending.get("status") != "pending":
            await query.answer("Заявка уже обработана", show_alert=True)
            return
        await _send_extwd_receipt_prompt(
            context,
            query,
            chat_id=chat_id,
            user_id=user_id,
            card_message_id=query.message.message_id,
            payout_id=payout_id,
        )
        return

    if action == "skip":
        ok, err, payout = await process_payout_paid(
            payout_id,
            completed_by=f"telegram:{user_id}",
        )
        if not ok:
            if err == "already_processed":
                await query.answer("Заявка уже обработана", show_alert=True)
            elif err == "insufficient_balance":
                await query.answer("Недостаточно баланса для выплаты", show_alert=True)
            else:
                await query.answer("Не удалось провести выплату", show_alert=True)
            return
        await query.answer("Выплата закрыта")
        status_text = f"✅ <b>Пропущено / выплачено</b> · @{op_label}"
    else:
        ok, err, payout = await process_payout_rejected(
            payout_id,
            rejected_by=f"telegram:{user_id}",
        )
        if not ok:
            await query.answer(
                "Заявка уже обработана" if err == "already_processed" else "Ошибка",
                show_alert=True,
            )
            return
        await query.answer("Заявка отклонена")
        status_text = f"❌ <b>Отклонено</b> · @{op_label}"
        context.user_data.pop("pending_extwd_receipt", None)

    try:
        base = query.message.text_html or query.message.text or ""
        await query.message.edit_text(
            f"{base}\n\n{status_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([]),
        )
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)


async def admin_extwd_receipt_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Reply админа с PDF/фото после «Прикрепить чек» по выводу внештата."""
    if not update.message:
        return
    if _should_capture_broadcast(update, context):
        await _save_copy_account_message(update, context)
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not (is_reports_group_chat(chat_id) or is_ops_group_chat(chat_id)):
        return
    user_id = update.effective_user.id if update.effective_user else None
    if user_id not in TELEGRAM_ADMIN_IDS:
        return

    pending = _resolve_pending_for_hash(update, context)
    if not pending or pending.get("kind") != "extwd_receipt":
        return

    payout_id = pending.get("payout_id")
    if not payout_id:
        return

    doc = update.message.document
    photos = update.message.photo
    if not doc and not photos:
        await update.message.reply_text(
            "❌ Пришлите PDF-документ или фото чека reply на запрос бота."
        )
        return

    import uuid
    from pathlib import Path

    from services.external_payout_admin import process_payout_paid
    from services.payout_pending_store import clear_pending, clear_user_data_pending
    from services.receipts_storage import (
        assert_receipts_writable,
        download_telegram_file_to_path,
    )

    if doc:
        file_id = doc.file_id
        name = (doc.file_name or "").lower()
        mime = (doc.mime_type or "").lower()
        if name.endswith(".pdf") or mime == "application/pdf":
            ext = "pdf"
        else:
            suffix = Path(name).suffix.lstrip(".").lower() if name else ""
            if suffix in ("jpg", "jpeg", "png", "webp", "gif"):
                ext = "jpg" if suffix == "jpeg" else suffix
            else:
                await update.message.reply_text(
                    "❌ Нужен PDF или изображение (jpg/png/webp)."
                )
                return
        file_size = int(doc.file_size or 0)
    else:
        file_id = photos[-1].file_id
        ext = "jpg"
        file_size = int(photos[-1].file_size or 0)

    if file_size > 15 * 1024 * 1024:
        await update.message.reply_text("❌ Файл слишком большой (лимит 15 МБ).")
        return

    try:
        receipts_dir = assert_receipts_writable()
    except PermissionError as e:
        logger.error("extwd receipt dir not writable: %s", e)
        await update.message.reply_text("⚠️ Нет прав на запись чека на сервере.")
        return

    filename = f"extwd_{payout_id}_{uuid.uuid4().hex}.{ext}"
    dest = receipts_dir / filename
    try:
        await download_telegram_file_to_path(context.bot, file_id, dest)
    except Exception as e:
        logger.exception("extwd receipt download failed payout=%s: %s", payout_id, e)
        await update.message.reply_text("❌ Не удалось скачать файл.")
        return

    ok, err, payout = await process_payout_paid(
        int(payout_id),
        completed_by=f"telegram:{user_id}",
        receipt_file=filename,
    )
    clear_pending(context.application.bot_data, pending)
    clear_user_data_pending(context, "extwd_receipt")

    if not ok:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        if err == "already_processed":
            await update.message.reply_text("ℹ️ Заявка уже обработана.")
        elif err == "insufficient_balance":
            await update.message.reply_text("❌ Недостаточно баланса для выплаты.")
        else:
            await update.message.reply_text("❌ Не удалось закрыть заявку.")
        return

    op_label = html.escape(
        update.effective_user.username or str(user_id)
    )
    await update.message.reply_text(
        f"✅ Вывод внештата #{payout_id} закрыт с чеком · @{op_label}"
    )

    card_message_id = pending.get("card_message_id") or pending.get("message_id")
    if card_message_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=int(card_message_id),
                reply_markup=InlineKeyboardMarkup([]),
            )
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>Выплачено с чеком</b> · @{op_label} · "
                    f"файл <code>{html.escape(filename)}</code>"
                ),
                parse_mode="HTML",
                reply_to_message_id=int(card_message_id),
            )
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
