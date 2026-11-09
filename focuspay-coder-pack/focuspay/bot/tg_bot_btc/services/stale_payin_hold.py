"""Разруливание зависших BUY payin, которые блокируют новый обмен.

Инцидент: AWAITING_CHECK + receipt_ops_pending=true крутился экспайрером
(+30 мин вечно). Мерчант уже SUCCSES, крипта ушла на ручной OP-заявке —
клиент не мог ни отменить, ни создать новую.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

logger = logging.getLogger("stale_payin_hold")

CRYPTO_DECIMALS = {
    "btc": 8,
    "usdt": 2,
    "trx": 2,
    "ltc": 8,
}

SUPERSEDE_OPEN_STATUSES = frozenset(
    {"CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED"}
)
PAID_SIBLING_WINDOW = timedelta(hours=48)
MANUAL_PAYOUT_SOURCES = frozenset({"manual", "manual_operator"})

ACTION_HOLD_OPS = "hold_ops"
ACTION_SUPERSEDE = "supersede"
ACTION_COMPLETE = "complete"
ACTION_EXPIRE = "expire"
ACTION_SKIP_SETTLED = "skip_settled"
ACTION_HOLD_PF = "hold_pf"

_NOT_PENDING_MARKERS = (
    "не в ожидании",
    "not pending",
    "not in pending",
    "not in wait",
)


def _crypto_key(crypto: object) -> str:
    return str(crypto or "").strip().lower().split("_")[0]


def crypto_quantum(crypto: object) -> Decimal:
    places = CRYPTO_DECIMALS.get(_crypto_key(crypto), 8)
    return Decimal("1").scaleb(-places)


def crypto_amounts_match(left: object, right: object, crypto: object) -> bool:
    """Одинаковая выплата с точностью до шага монеты (LTC/BTC 8 знаков)."""
    try:
        a = Decimal(str(left))
        b = Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if a <= 0 or b <= 0:
        return False
    q = crypto_quantum(crypto)
    return a.quantize(q, rounding=ROUND_HALF_UP) == b.quantize(q, rounding=ROUND_HALF_UP)


def wallets_match(left: object, right: object) -> bool:
    a = str(left or "").strip()
    b = str(right or "").strip()
    return bool(a) and a == b


def payout_identity_matches(open_order: dict, paid_order: dict) -> bool:
    """Та же выплата: сумма крипты и кошелёк, если он есть на обеих заявках."""
    crypto = open_order.get("crypto") or paid_order.get("crypto")
    if not crypto_amounts_match(
        open_order.get("crypto_amount"), paid_order.get("crypto_amount"), crypto
    ):
        return False
    open_w = str(open_order.get("wallet_address") or open_order.get("requisites") or "").strip()
    paid_w = str(paid_order.get("wallet_address") or paid_order.get("requisites") or "").strip()
    if open_w and paid_w:
        return open_w == paid_w
    src = str(paid_order.get("order_source") or "").lower()
    open_payin = bool(str(open_order.get("merchant_order_id") or "").strip())
    if src not in MANUAL_PAYOUT_SOURCES or not open_payin:
        return False
    # Ручная OP-заявка часто без wallet_address; фиат на ней может чуть
    # отличаться (курс/комиссия). Сумма крипты уже сверена выше.
    return True


def merchant_cancel_is_not_pending(error: object) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _NOT_PENDING_MARKERS)


def receipt_ops_hold_started_at(order: dict) -> datetime | None:
    from services.db import get_receipt_requested_at, get_receipt_submitted_at

    started = get_receipt_submitted_at(order) or get_receipt_requested_at(order)
    if started is None:
        raw = order.get("created_at")
        if isinstance(raw, datetime):
            started = raw
    if started is None:
        return None
    if started.tzinfo is None:
        return started.replace(tzinfo=timezone.utc)
    return started.astimezone(timezone.utc)


def receipt_ops_pending_max_minutes() -> int:
    from services import config_rates

    return max(0, int(getattr(config_rates, "RECEIPT_OPS_PENDING_MAX_MINUTES", 120) or 0))


def receipt_ops_pending_is_fresh(
    order: dict,
    *,
    now: datetime | None = None,
    max_minutes: int | None = None,
) -> bool:
    """True — оператор ещё может смотреть чек, экспайрер не вмешивается."""
    started = receipt_ops_hold_started_at(order)
    if started is None:
        return False
    window = receipt_ops_pending_max_minutes() if max_minutes is None else max(0, int(max_minutes))
    if window <= 0:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return started + timedelta(minutes=window) > current.astimezone(timezone.utc)


def is_video_hold(order: dict) -> bool:
    return (
        str(order.get("status") or "").upper() == "AWAITING_CHECK"
        and int(order.get("required_receipt_type") or 0) == 3
    )


def decide_stale_payin_action(
    *,
    ops_pending: bool,
    ops_pending_fresh: bool,
    pf_ok: bool | None,
    pf_err: str | None,
    has_sibling_paid: bool,
    video_hold: bool,
) -> str:
    """Что делать с открытым BUY, который попал в экспайрер."""
    if has_sibling_paid:
        return ACTION_SUPERSEDE
    if ops_pending and ops_pending_fresh:
        return ACTION_HOLD_OPS
    if pf_ok:
        if video_hold:
            return ACTION_SKIP_SETTLED
        if ops_pending:
            return ACTION_COMPLETE
        return ACTION_SKIP_SETTLED
    err = str(pf_err or "")
    if err in {
        "payfast_check_pending",
        "payfast_awaiting_trader",
        "payfast_recheck_requested",
        "payfast_api_error",
    }:
        return ACTION_HOLD_PF
    return ACTION_EXPIRE


async def close_superseded_payin(
    order: dict,
    sibling: dict,
    *,
    bot=None,
    notify_user: bool = True,
) -> bool:
    """Закрыть зомби: крипта уже ушла на другой заявке (обычно manual_operator)."""
    from services.db import (
        clear_receipt_ops_pending,
        mark_ops_alert_once,
        merge_order_payment_snapshot,
        update_order_status,
    )
    from services.order_ops_notify import notify_ops_order

    order_id = str(order.get("order_id") or "").strip()
    sibling_id = str(sibling.get("order_id") or "").strip()
    if not order_id or not sibling_id or order_id == sibling_id:
        return False
    if str(order.get("status") or "").upper() not in SUPERSEDE_OPEN_STATUSES:
        return False

    await merge_order_payment_snapshot(
        order_id,
        {
            "superseded_by": sibling_id,
            "superseded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await clear_receipt_ops_pending(order_id)
    if not await update_order_status(order_id, "CANCELED"):
        logger.warning(
            "supersede transition rejected order=%s sibling=%s status=%s",
            order_id,
            sibling_id,
            order.get("status"),
        )
        return False

    logger.info("superseded payin order=%s by paid %s", order_id, sibling_id)
    if await mark_ops_alert_once(order_id, "superseded_by_paid"):
        try:
            await notify_ops_order(
                "expired",
                dict(order),
                bot=bot,
                note=(
                    f"Заявка закрыта автоматически: выплата уже в "
                    f"<code>{sibling_id}</code>. Клиент больше не заблокирован."
                ),
            )
        except Exception as e:
            logger.warning("ops notify supersede failed order=%s: %s", order_id, e)

    if notify_user:
        uid = int(order.get("user_id") or 0)
        if uid > 0 and bot is not None:
            try:
                from services.menu import main_menu_keyboard

                menu = await main_menu_keyboard(uid)
                await bot.send_message(
                    chat_id=uid,
                    text=(
                        "Заявка закрыта — крипта по ней уже отправлена.\n"
                        "Можно создать новый обмен."
                    ),
                    reply_markup=menu,
                )
            except Exception as e:
                logger.warning("user notify supersede failed order=%s: %s", order_id, e)
    return True


async def complete_stale_ops_pending_if_settled(
    order: dict,
    *,
    verified_payfast_response: dict | None = None,
) -> bool:
    """Забытый ops-hold, мерчант уже подтвердил оплату, ручной выплаты нет."""
    from services.db import clear_receipt_ops_pending
    from services.payfast_buy_complete import (
        advance_awaiting_check_to_pending,
        complete_buy_on_payfast_confirmed,
        finalize_buy_payfast_completed,
    )

    order_id = str(order.get("order_id") or "").strip()
    if not order_id or is_video_hold(order):
        return False

    await clear_receipt_ops_pending(order_id)
    current, advanced = await advance_awaiting_check_to_pending(order_id, dict(order))
    if current is None:
        return False
    if not advanced and str(current.get("status") or "").upper() != "PENDING":
        return False

    ok, err, amount_note = await complete_buy_on_payfast_confirmed(
        order_id,
        dict(current),
        verified_payfast_response=verified_payfast_response,
    )
    if not ok:
        logger.warning(
            "stale ops-pending complete failed order=%s err=%s",
            order_id,
            err,
        )
        return False
    await finalize_buy_payfast_completed(
        order_id,
        dict(current),
        amount_note=amount_note,
        receipt_bypass=True,
    )
    logger.info("stale ops-pending completed order=%s", order_id)
    return True


async def resolve_failed_merchant_cancel(
    order: dict,
    merchant_result: dict[str, Any] | None,
) -> str:
    """
    Merchant cancel не прошёл.

    Returns:
      closed_superseded | closed_merchant | settled | still_open
    """
    from services.db import (
        clear_receipt_ops_pending,
        find_matching_paid_buy_payout,
        update_order_status,
    )
    from services.payfast_payin_guard import verify_payfast_ready_for_payout

    sibling = await find_matching_paid_buy_payout(order)
    if sibling:
        if await close_superseded_payin(order, sibling, bot=None, notify_user=False):
            return "closed_superseded"

    body = (merchant_result or {}).get("body") or {}
    err = body.get("error") or (merchant_result or {}).get("error") or ""
    try:
        pf_ok, pf_err, _resp = await verify_payfast_ready_for_payout(
            dict(order), require_uuid=True
        )
    except Exception as e:
        logger.warning(
            "cancel fallback payfast check failed order=%s: %s",
            order.get("order_id"),
            e,
        )
        return "still_open"

    if pf_ok:
        return "settled"
    if str(pf_err or "").startswith("payfast_status_") or merchant_cancel_is_not_pending(err):
        if str(pf_err or "").startswith("payfast_status_"):
            if await update_order_status(str(order["order_id"]), "CANCELED"):
                await clear_receipt_ops_pending(str(order["order_id"]))
                return "closed_merchant"
        elif merchant_cancel_is_not_pending(err) and not pf_ok:
            # «не в ожидании», но статус не SUCCESS и не явный fail — не гадаем.
            if str(pf_err or "") not in {
                "payfast_check_pending",
                "payfast_awaiting_trader",
                "payfast_recheck_requested",
                "payfast_api_error",
            }:
                if await update_order_status(str(order["order_id"]), "CANCELED"):
                    await clear_receipt_ops_pending(str(order["order_id"]))
                    return "closed_merchant"
    return "still_open"


async def sweep_superseded_completed_payins(*, bot=None, limit: int = 40) -> list[str]:
    """COMPLETED, который ошибочно оставили в очереди выплаты при уже существующей PAID."""
    from services.db import (
        find_completed_buys_possibly_superseded,
        find_matching_paid_buy_payout,
    )

    closed: list[str] = []
    try:
        rows = await find_completed_buys_possibly_superseded(limit=limit)
    except Exception:
        logger.exception("lookup completed superseded payins failed")
        return closed
    for row in rows:
        order = dict(row)
        try:
            sibling = await find_matching_paid_buy_payout(order)
            if not sibling:
                continue
            if await close_superseded_payin(order, sibling, bot=bot, notify_user=True):
                closed.append(str(order["order_id"]))
        except Exception:
            logger.exception(
                "sweep completed superseded failed order=%s",
                order.get("order_id"),
            )
    return closed


async def close_open_payins_superseded_by_paid(paid_order: dict, *, bot=None) -> list[str]:
    """После ручной PAID закрыть парный зависший payin того же клиента."""
    from services.db import find_open_payins_superseded_by_paid

    closed: list[str] = []
    try:
        rows = await find_open_payins_superseded_by_paid(paid_order)
    except Exception:
        logger.exception(
            "lookup superseded payins failed paid=%s",
            paid_order.get("order_id"),
        )
        return closed
    for row in rows:
        try:
            if await close_superseded_payin(dict(row), paid_order, bot=bot, notify_user=True):
                closed.append(str(row["order_id"]))
        except Exception:
            logger.exception(
                "close superseded payin failed open=%s paid=%s",
                row.get("order_id"),
                paid_order.get("order_id"),
            )
    return closed
