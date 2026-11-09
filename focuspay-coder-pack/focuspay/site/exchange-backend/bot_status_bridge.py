"""Единая смена статуса через логику бота (финансовые хуки, split)."""
import logging
import os
import sys

logger = logging.getLogger("bot_status_bridge")

_bot_db = None


async def init_bot_status_bridge(dsn: str) -> bool:
    global _bot_db
    if _bot_db is not None:
        return True
    bot_root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
    # append: модули exchange-backend (order_ops_notify и т.д.) должны иметь приоритет
    if bot_root not in sys.path:
        sys.path.append(bot_root)
    try:
        from services import db as bot_db

        await bot_db.init_db(dsn)
        _bot_db = bot_db
        logger.info("Bot status bridge ready (%s)", bot_root)
        return True
    except Exception as e:
        logger.warning("Bot status bridge unavailable: %s", e)
        return False


async def update_order_status(
    order_id: str,
    status: str,
    *,
    cancel_reason: str | None = None,
    canceled_by: int | None = None,
) -> bool:
    if _bot_db is None:
        return False
    return await _bot_db.update_order_status(
        order_id,
        status.upper(),
        cancel_reason=cancel_reason,
        canceled_by=canceled_by,
    )


async def update_order_to_awaiting_check(order_id: str, required_receipt_type: int = 2) -> bool:
    if _bot_db is None:
        return False
    return await _bot_db.update_order_to_awaiting_check(order_id, required_receipt_type)


async def route_uploaded_receipt(order: dict, receipt_name: str) -> dict:
    """Проверка чека миниапки тем же деревом, что файл в боте. Bot=None → HTTP."""
    from services.receipt_ops_review import route_client_receipt

    return await route_client_receipt(dict(order), receipt_name, bot=None)


async def send_receipt_to_payfast(
    order_id: str, *, operator_id: int
) -> tuple[bool, str | None]:
    """Операторская отправка PDF в Payfast (тот же путь, что кнопка в ops-чате)."""
    oid = str(order_id).strip()
    try:
        from services.receipt_ops_review import approve_receipt_and_send_to_payfast

        return await approve_receipt_and_send_to_payfast(
            oid,
            int(operator_id),
            bot=None,
            allow_resend=True,
        )
    except Exception as e:
        logger.warning("send_receipt_to_payfast failed order=%s: %s", oid, e)
        return False, "bridge_unavailable"


async def try_complete_if_payfast_settled(order_id: str) -> None:
    """Если Payfast уже SUCCSES — снять с проверки (AWAITING_CHECK/PENDING → COMPLETED)."""
    oid = str(order_id).strip()
    try:
        from services.receipt_ops_review import _try_reconcile_payfast_settled

        await _try_reconcile_payfast_settled(oid)
    except Exception as e:
        logger.warning("payfast settle after receipt failed order=%s: %s", oid, e)


async def request_client_video(order_id: str, *, source: str = "operator") -> tuple[bool, str]:
    """BUY → AWAITING_CHECK + required_receipt_type=3; клиенту то же сообщение, что у бота."""
    oid = str(order_id).strip()
    try:
        from services.video_receipt_request import request_client_receipt_check

        return await request_client_receipt_check(oid, 3, source=source)
    except Exception as e:
        logger.warning("video_receipt_request unavailable order=%s: %s", oid, e)
    ok = await update_order_to_awaiting_check(oid, 3)
    if ok:
        return True, "db_only"
    return False, "bridge_unavailable"


async def confirm_buy_payout(
    order_id: str,
    *,
    tx_hash: str,
    actor: str,
    operator_id: int | None = None,
    force: bool = False,
) -> tuple[bool, str | None, dict | None]:
    if _bot_db is None:
        return False, "bridge_unavailable", None
    from services.buy_payout import confirm_buy_payout as _confirm

    return await _confirm(
        order_id,
        tx_hash=tx_hash,
        actor=actor,
        operator_id=operator_id,
        force=force,
    )


async def confirm_manual_buy_payout(
    order_id: str,
    *,
    tx_hash: str,
    actor: str,
    operator_id: int | None = None,
) -> tuple[bool, str | None, dict | None]:
    if _bot_db is None:
        return False, "bridge_unavailable", None
    from services.buy_payout import confirm_manual_buy_payout as _confirm

    return await _confirm(
        order_id,
        tx_hash=tx_hash,
        actor=actor,
        operator_id=operator_id,
    )


async def confirm_awaiting_check_buy_payout(
    order_id: str,
    *,
    tx_hash: str,
    actor: str,
    operator_id: int | None = None,
) -> tuple[bool, str | None, dict | None]:
    if _bot_db is None:
        return False, "bridge_unavailable", None
    try:
        from services.buy_payout import confirm_awaiting_check_buy_payout as _confirm
    except ImportError:
        logger.exception("confirm_awaiting_check_buy_payout missing in bot buy_payout")
        return False, "bridge_unavailable", None

    return await _confirm(
        order_id,
        tx_hash=tx_hash,
        actor=actor,
        operator_id=operator_id,
    )


async def notify_buyer_paid_for_order(order: dict) -> None:
    if _bot_db is None:
        return
    from services.buy_payout import build_explorer_url, notify_buyer_paid

    tx = (order.get("payout_tx_hash") or "").strip()
    explorer = (
        build_explorer_url(str(order.get("crypto") or ""), tx) if tx else ""
    )
    await notify_buyer_paid(order, explorer)


async def notify_sell_completed_for_user(order: dict) -> None:
    """Уведомление клиенту о завершённой продаже крипты (ручная / QR)."""
    user_id = order.get("user_id")
    if not user_id or _bot_db is None:
        return
    import html

    oid = html.escape(str(order.get("order_id") or ""))
    fiat = order.get("fiat_amount")
    crypto = html.escape(str(order.get("crypto") or "").upper())
    crypto_amt = order.get("crypto_amount")
    fiat_s = f"{float(fiat):,.0f}".replace(",", " ") if fiat is not None else "—"
    crypto_s = f"{float(crypto_amt):g}" if crypto_amt is not None else "—"
    paid_line = f"💵 Выплата: <b>{fiat_s}</b> ₽"
    if order.get("triangle_paid_rub") is not None:
        from user_referral_withdraw import _triangle_done_line

        done = _triangle_done_line(
            card_paid_rub=float(order.get("triangle_paid_rub") or 0),
            balance_return_rub=float(order.get("triangle_return_rub") or 0),
            subsidy_rub=float(order.get("triangle_subsidy_rub") or 0),
        )
        if done:
            paid_line = done
    text = (
        "✅ <b>Сделка завершена</b>\n\n"
        f"🆔 Заявка: <code>{oid}</code>\n"
        f"💎 Вы отдали: <b>{crypto_s}</b> {crypto}\n"
        f"{paid_line}"
    )
    try:
        from services.webhook_server import notify_user

        notify_user(int(user_id), text)
    except Exception as e:
        logger.warning("notify sell completed user=%s: %s", user_id, e)


async def notify_order_completed_for_user(order: dict) -> None:
    direction = (order.get("direction") or "").lower()
    if direction == "buy":
        await notify_buyer_paid_for_order(order)
    elif direction == "sell":
        await notify_sell_completed_for_user(order)


async def ban_user(user_id: int, *, reason: str = "", operator_id: int, ban_type: str = "hard") -> bool:
    if _bot_db is None:
        return False
    return await _bot_db.ban_user(user_id, reason=reason, operator_id=operator_id, ban_type=ban_type)


async def unban_user(user_id: int) -> bool:
    if _bot_db is None:
        return False
    return await _bot_db.unban_user(user_id)


async def is_user_banned(user_id: int) -> tuple[bool, str | None, str]:
    if _bot_db is None:
        return False, None, "hard"
    return await _bot_db.is_user_banned(user_id)
