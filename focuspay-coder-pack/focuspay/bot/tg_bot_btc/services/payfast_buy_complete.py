"""Завершение BUY-заявки (→ COMPLETED) после подтверждения оплаты Payfast."""
from __future__ import annotations

import asyncio
import logging

from services.callback_signatures import sign_order
from services.db import get_order, update_order_status
from services.order_ops_notify import notify_ops_order
from services.payment_snapshot import order_payment_snapshot
from services.payfast_payin_guard import (
    payfast_amount_from_payload,
    verify_payfast_ready_for_complete,
)
from services.webhook_security import amount_matches_order, order_ready_for_merchant_complete

logger = logging.getLogger("payfast_buy_complete")


def notify_user_payment_confirmed(user_id: int, order_id: str) -> None:
    """Telegram-сообщение клиенту (sync HTTP, без зависимости от webhook_server)."""
    from services import config_rates as cfg

    if not user_id or int(user_id) <= 0:
        return
    import requests

    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    text = (
        f"✅ <b>Платёж подтверждён</b>\n\n"
        f"🆔 Заявка: <code>{order_id}</code>\n\n"
        "⏳ Ожидайте зачисления средств — вам придёт транзакция "
        "на кошелёк в течение пары минут."
    )
    try:
        requests.post(
            url,
            json={"chat_id": int(user_id), "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("notify_user_payment_confirmed failed user=%s: %s", user_id, e)


async def advance_awaiting_check_to_pending(order_id: str, order: dict) -> tuple[dict | None, bool]:
    """AWAITING_CHECK → PENDING когда Payfast подтвердил оплату без принятого чека."""
    if str(order.get("status") or "") != "AWAITING_CHECK":
        return order, False
    ok = await update_order_status(order_id, "PENDING")
    if not ok:
        logger.warning("advance AWAITING_CHECK→PENDING rejected order=%s", order_id)
        return None, False
    refreshed = await get_order(order_id)
    return (dict(refreshed) if refreshed else None), True


CLIENT_VIDEO_EXTS = frozenset({"mp4", "mov", "avi", "webm", "mkv"})


def has_client_receipt_file(order: dict) -> bool:
    return bool(str(order.get("receipt_file") or "").strip())


def has_client_video_file(order: dict) -> bool:
    """True только если на заявке лежит видео, а не старый PDF после запроса ролика."""
    name = str(order.get("receipt_file") or "").strip().lower()
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1] in CLIENT_VIDEO_EXTS


def is_video_receipt_hold(order: dict) -> bool:
    try:
        return int(order.get("required_receipt_type") or 0) == 3
    except (TypeError, ValueError):
        return False


def awaiting_check_can_settle(order: dict) -> bool:
    """AWAITING_CHECK + чек у нас: Payfast уже может закрыть заявку.

    Видео-холд (req_type=3) снимается только если прислан именно ролик.
    Старый PDF после запроса видео держит выплату.
    """
    if str(order.get("status") or "").upper() != "AWAITING_CHECK":
        return False
    if is_video_receipt_hold(order):
        return has_client_video_file(order)
    return has_client_receipt_file(order)


async def complete_buy_on_payfast_confirmed(
    order_id: str,
    order: dict,
    *,
    data_order: dict | None = None,
    webhook_body: dict | None = None,
    verified_payfast_response: dict | None = None,
    receipt_bypass: bool = False,
) -> tuple[bool, str | None, str | None]:
    """
    PENDING → COMPLETED после проверки Payfast API.

    Returns (ok, error_reason, amount_note).
    """
    data_order = data_order or {}
    ready, ready_reason = order_ready_for_merchant_complete(order)
    if not ready:
        # AWAITING_CHECK означает: чек ещё не принят мерчантом и не прошёл
        # операторскую/приёмочную проверку. Никогда не завершаем в этом
        # состоянии, даже если вызывающий передал receipt_bypass=True.
        return False, ready_reason, None

    if verified_payfast_response is None:
        pf_ok, pf_reason, payfast_response = await verify_payfast_ready_for_complete(
            dict(order), webhook_body
        )
        if not pf_ok:
            return False, pf_reason, None
    else:
        payfast_response = verified_payfast_response

    live_amount = payfast_amount_from_payload(payfast_response)
    amount_ok, amount_reason = amount_matches_order({"amount": live_amount}, order)
    amount_note: str | None = None
    if not amount_ok:
        logger.warning(
            "payfast complete amount diff order=%s reason=%s",
            order_id,
            amount_reason,
        )
        amount_note = amount_reason

    updated = await update_order_status(order_id, "COMPLETED")
    if not updated:
        return False, "transition_rejected", amount_note

    return True, None, amount_note


def _order_needs_wallet_confirm(order: dict) -> bool:
    if not order or str(order.get("direction") or "buy").lower() != "buy":
        return False
    coin = str(order.get("crypto") or "").split("_", 1)[0].lower()
    if coin in ("btc", "ltc"):
        return True
    snap = order_payment_snapshot(order)
    return bool(snap.get("requisite_retry") and coin in ("usdt", "trx"))


async def finalize_buy_payfast_completed(
    order_id: str,
    order: dict,
    *,
    amount_note: str | None = None,
    receipt_bypass: bool = False,
) -> None:
    """Ops + user notify после COMPLETED.

    Защищён от дублей через mark_ops_alert_once: при гонке webhook+reconciler
    только первый вызов отправит уведомление.
    """
    from services.db import mark_ops_alert_once

    already_sent = not await mark_ops_alert_once(order_id, "merchant_confirmed_notify")
    if already_sent:
        logger.info("finalize_buy_payfast_completed dedup order=%s — notify skipped", order_id)
        return

    confirm_note = "Отправьте крипту клиенту"
    if receipt_bypass:
        confirm_note = (
            "Payfast подтвердил оплату (чек в бот не принят мерчантом). "
            "Отправьте крипту клиенту."
        )
    if amount_note:
        confirm_note += (
            f"\n⚠️ Расхождение суммы: {amount_note} "
            "(Payfast подтвердил — ставка зафиксирована при создании)"
        )
    refreshed = await get_order(order_id) or order
    needs_wallet_timer = _order_needs_wallet_confirm(dict(refreshed))
    if needs_wallet_timer:
        confirm_note += (
            "\n⏳ Таймер 5 мин: через 5 минут покупателю придёт запрос уточнения кошелька "
            "(или нажмите «Отправить запрос досрочно»)."
        )
    try:
        await notify_ops_order(
            "merchant_confirmed",
            dict(refreshed),
            bot=None,
            pay_signature=sign_order(order_id),
            note=confirm_note,
            wallet_early=needs_wallet_timer,
        )
    except Exception as e:
        logger.warning("ops notify merchant_confirmed failed order=%s: %s", order_id, e)

    user_id = refreshed.get("user_id")
    if user_id:
        await asyncio.to_thread(notify_user_payment_confirmed, int(user_id), order_id)


async def complete_buy_from_payfast_settled(
    order_id: str,
    order: dict,
    *,
    data_order: dict | None = None,
    webhook_body: dict | None = None,
    verified_payfast_response: dict | None = None,
    receipt_bypass: bool = False,
) -> tuple[bool, str | None]:
    """
    Полный путь: AWAITING_CHECK→PENDING (если нужно) → COMPLETED → notify.

    Returns (ok, error_reason).
    """
    current = dict(order)
    # Видео-удержание: Appeals запросил видео (req_type=3) после подтверждения
    # мерчантом. Пока клиент не прислал ролик, не даём reconciler/webhook
    # авто-завершить заявку обратно в COMPLETED. Если mp4 уже на заявке —
    # Payfast SUCCSES может закрыть, как PDF после settle.
    if (
        str(current.get("status") or "").upper() == "AWAITING_CHECK"
        and is_video_receipt_hold(current)
        and not has_client_video_file(current)
    ):
        return False, "awaiting_video_hold"
    if str(current.get("status") or "").upper() == "AWAITING_CHECK":
        # Без файла чека не закрываем: инцидент «крипта ушла, PDF не долетел».
        # Если PDF уже у нас, а Payfast settled — операторский холд больше
        # не должен блокировать выплату (Payfast подтвердил оплату сам).
        if not has_client_receipt_file(current):
            return False, "receipt_not_submitted"
        current, changed = await advance_awaiting_check_to_pending(order_id, current)
        if not current:
            return False, "transition_rejected"
        try:
            from services.db import clear_receipt_ops_pending

            await clear_receipt_ops_pending(order_id)
        except Exception:
            logger.warning(
                "clear receipt_ops_pending after settle failed order=%s",
                order_id,
                exc_info=True,
            )

    ok, err, amount_note = await complete_buy_on_payfast_confirmed(
        order_id,
        current,
        data_order=data_order,
        webhook_body=webhook_body,
        verified_payfast_response=verified_payfast_response,
        receipt_bypass=receipt_bypass,
    )
    if not ok:
        return False, err

    await finalize_buy_payfast_completed(
        order_id,
        current,
        amount_note=amount_note,
        receipt_bypass=receipt_bypass,
    )
    return True, None
