"""Фоновый анализатор реквизитов выплат.

Раз в минуту пересчитывает планы по открытым реквизитам, обновляет кэш
snap-целей для котировок, дёргает оператора в Telegram, когда появился план
в один чек или окно вот-вот закроется, и просрочивает истёкшие реквизиты.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import payout_sum_snap
from payin_requisite_rail import (
    give_up_idle_withdrawal_triangles,
    manual_payout_message,
    payin_keep_open,
)
from payout_requisite_cost import safe_post_requisite_cost
from payout_requisite_matcher import (
    ACTIVE_REQUISITE_STATUSES,
    CANDIDATE_ORDER_STATUSES,
    DEFAULT_WINDOW_MINUTES,
    LIST_REQUISITE_STATUSES,
    REQUISITE_COLUMNS,
    active_payin_requisites,
    active_requisites,
    is_triangle_row,
    plan_for_requisite,
    store_plan,
)

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
DEADLINE_WARN_MINUTES = 20

# Дедуп уведомлений в памяти процесса: без него оператор получал бы одно и то
# же сообщение каждую минуту. Перезапуск API допускает один повтор.
_notified: dict[tuple[int, str], str] = {}


def reset_notification_state() -> None:
    _notified.clear()


def _should_notify(requisite_id: int, kind: str, signature: str) -> bool:
    key = (int(requisite_id), kind)
    if _notified.get(key) == signature:
        return False
    _notified[key] = signature
    return True


def _plan_signature(plan) -> str:
    return ",".join(sorted(c.order_id for c in plan.orders)) + f"|{plan.doliv_kop}"


def _format_one_check_message(row, plan) -> str:
    order = plan.orders[0] if plan.orders else None
    label = row["label"] or f"{row['method']} ···{str(row['requisites'])[-4:]}"
    sell_id = str(row.get("source_sell_order_id") or "")
    if sell_id and plan.doliv_kop and not order:
        return (
            "<b>Треугольник: долив закрывает остаток</b>\n"
            f"{label} — продажа <code>{sell_id}</code>\n"
            f"Долить {plan.doliv_kop / 100:.2f} ₽ продавцу."
        )
    if not order:
        return (
            "<b>Реквизит выплаты: план закрытия</b>\n"
            f"{label} — остаток {plan.orders_kop / 100:.2f} ₽."
        )
    if plan.doliv_kop:
        title = "Треугольник: один чек + долив" if sell_id else "Реквизит выплаты: один чек + долив"
        return (
            f"<b>{title}</b>\n"
            f"{label} — заявка <code>{order.order_id}</code> на {float(order.amount_rub):.2f} ₽\n"
            f"Долив {plan.doliv_kop / 100:.2f} ₽ закрывает остаток."
        )
    title = "Треугольник: план в один чек" if sell_id else "Реквизит выплаты: план в один чек"
    return (
        f"<b>{title}</b>\n"
        f"{label} — остаток {plan.orders_kop / 100:.2f} ₽\n"
        f"Заявка <code>{order.order_id}</code> на {float(order.amount_rub):.2f} ₽ закрывает всё."
    )


def _format_deadline_message(row, minutes_left: int) -> str:
    label = row["label"] or f"{row['method']} ···{str(row['requisites'])[-4:]}"
    paid = float(row["paid_rub"] or 0)
    amount = float(row["amount_rub"])
    return (
        "<b>Реквизит выплаты: окно закрывается</b>\n"
        f"{label} — осталось ~{minutes_left} мин\n"
        f"Закрыто {paid:.2f} из {amount:.2f} ₽."
    )


async def _notify_operator(conn, operator_id: int, text: str) -> bool:
    tg = await conn.fetchval(
        "SELECT telegram_user_id FROM operator_accounts WHERE id = $1",
        int(operator_id),
    )
    if not tg:
        return False
    from telegram_notify import send_admin_message

    try:
        await send_admin_message(text, chat_id=int(tg))
        return True
    except Exception as exc:
        logger.warning("payout requisite notify op=%s: %s", operator_id, exc)
        return False


async def _notify_manual_payout(conn, row: dict) -> bool:
    """Финоператору карты, а без привязанного Telegram — в общую группу операторов."""
    text = manual_payout_message(row)
    if row.get("operator_id") is not None and await _notify_operator(conn, int(row["operator_id"]), text):
        return True
    from telegram_notify import send_admin_message

    try:
        return bool(await send_admin_message(text))
    except Exception as exc:
        logger.warning("manual payout notify wd=%s: %s", row.get("source_withdrawal_id"), exc)
        return False


async def _hold_empty_withdrawal_card(conn, row) -> bool:
    """Пустая карта вывода живёт, пока заявка pending и по ней никто не заплатил."""
    raw_id = row.get("source_withdrawal_id") if hasattr(row, "get") else None
    if raw_id in (None, ""):
        return False
    paid_rub = row.get("paid_rub") or 0
    try:
        if float(paid_rub) > 0:
            return False
    except (TypeError, ValueError):
        return False
    has_paid = await conn.fetchval(
        """
        SELECT 1 FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'PAID'
        LIMIT 1
        """,
        int(row["id"]),
    )
    if has_paid:
        return False
    status = await conn.fetchval(
        "SELECT status FROM user_referral_withdrawals WHERE id = $1",
        int(raw_id),
    )
    if str(status or "") != "pending":
        return False
    await conn.execute(
        """
        UPDATE operator_payout_requisites
        SET deadline_at = now() + make_interval(mins => $2),
            updated_at = now()
        WHERE id = $1
        """,
        int(row["id"]),
        int(DEFAULT_WINDOW_MINUTES),
    )
    return True


async def expire_overdue(conn) -> int:
    """Просрочить реквизиты и вернуть их брони в общий пул заявок."""
    rows = await conn.fetch(
        f"""
        SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites
        WHERE status = ANY($1::text[]) AND deadline_at <= now()
        FOR UPDATE
        """,
        list(LIST_REQUISITE_STATUSES),
    )
    expired = 0
    for row in rows:
        if await _hold_empty_withdrawal_card(conn, row):
            continue
        if str(row.get("direction") or "payout").lower() == "payin":
            live = await conn.fetchval(
                """
                SELECT 1
                FROM payout_requisite_allocations a
                JOIN orders o ON o.order_id = a.order_id
                WHERE a.requisite_id = $1
                  AND a.status = 'RESERVED'
                  AND a.kind = 'payin'
                  AND o.status = ANY($2::text[])
                LIMIT 1
                """,
                int(row["id"]),
                ["CREATED", "AWAITING_CHECK", "PENDING"],
            )
            if live:
                continue
            first_paid = await conn.fetchval(
                """
                SELECT MIN(paid_at)
                FROM payout_requisite_allocations
                WHERE requisite_id = $1 AND status = 'PAID'
                """,
                int(row["id"]),
            )
            if payin_keep_open(row, first_paid_at=first_paid):
                continue
        released = await conn.fetch(
            """
            UPDATE payout_requisite_allocations
            SET status = 'CANCELED', updated_at = now()
            WHERE requisite_id = $1 AND status = 'RESERVED'
            RETURNING order_id, operator_id
            """,
            int(row["id"]),
        )
        for rel in released:
            if not rel["order_id"]:
                continue
            await conn.execute(
                """
                UPDATE orders
                SET operator_id = NULL, finance_operator_id = NULL, updated_at = now()
                WHERE order_id = $1
                  AND status = ANY($2::text[])
                  AND operator_id = $3
                """,
                rel["order_id"],
                list(CANDIDATE_ORDER_STATUSES),
                int(rel["operator_id"] or row["operator_id"]),
            )
        await conn.execute(
            """
            UPDATE operator_payout_requisites
            SET status = 'EXPIRED', closed_at = now(), updated_at = now()
            WHERE id = $1
            """,
            int(row["id"]),
        )
        await safe_post_requisite_cost(conn, row)
        _notified.pop((int(row["id"]), "one_check"), None)
        _notified.pop((int(row["id"]), "deadline"), None)
        expired += 1
    return expired


async def run_tick(pool) -> dict:
    """Один проход: просрочка, пересчёт планов, snap-цели, уведомления."""
    expired = 0
    reopened = 0
    plans = 0
    notified = 0
    free_amounts: list = []
    gave_up: list[dict] = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                gave_up = await give_up_idle_withdrawal_triangles(conn)
            except Exception:
                logger.exception("withdrawal triangle give-up failed")
                gave_up = []
            expired = await expire_overdue(conn)
        for row in gave_up:
            logger.info(
                "withdrawal %s triangle card %s: no buyer, manual payout",
                row["source_withdrawal_id"],
                row["id"],
            )
            if await _notify_manual_payout(conn, row):
                notified += 1
        try:
            from payin_requisite_rail import reopen_pending_withdrawal_triangles

            reopened = await reopen_pending_withdrawal_triangles(conn)
        except Exception:
            logger.exception("withdrawal triangle reopen failed")

        rows = await active_requisites(conn)
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                plan, free = await plan_for_requisite(conn, row)
                await store_plan(conn, int(row["id"]), plan, free)
                plans += 1
            except Exception:
                logger.exception("payout requisite plan failed id=%s", row["id"])
                continue
            if free > 0:
                free_amounts.append(free)

            if plan and plan.closes and len(plan.orders) == 1:
                if _should_notify(int(row["id"]), "one_check", _plan_signature(plan)):
                    if await _notify_operator(
                        conn, int(row["operator_id"]), _format_one_check_message(row, plan)
                    ):
                        notified += 1

            deadline = row["deadline_at"]
            if deadline and deadline - now <= timedelta(minutes=DEADLINE_WARN_MINUTES):
                minutes_left = max(0, int((deadline - now).total_seconds() // 60))
                if _should_notify(int(row["id"]), "deadline", str(deadline)):
                    if await _notify_operator(
                        conn,
                        int(row["operator_id"]),
                        _format_deadline_message(row, minutes_left),
                    ):
                        notified += 1

        for row in await active_payin_requisites(conn):
            try:
                plan, free = await plan_for_requisite(conn, row)
                await store_plan(conn, int(row["id"]), plan, free)
                plans += 1
            except Exception:
                logger.exception("payin fill forecast failed id=%s", row["id"])
                continue
            if not is_triangle_row(row):
                continue
            if str(row["status"]) not in ACTIVE_REQUISITE_STATUSES:
                continue
            if plan and plan.closes and (len(plan.orders) <= 1):
                if _should_notify(int(row["id"]), "one_check", _plan_signature(plan)):
                    if await _notify_operator(
                        conn, int(row["operator_id"]), _format_one_check_message(row, plan)
                    ):
                        notified += 1

    payout_sum_snap.set_targets(payout_sum_snap.targets_from_free_amounts(free_amounts))
    return {
        "expired": expired,
        "gave_up": len(gave_up),
        "reopened": reopened,
        "plans": plans,
        "notified": notified,
        "snap_targets": len(payout_sum_snap.get_targets()),
    }


async def payout_requisite_loop() -> None:
    import asyncio

    from db import get_pool

    while True:
        try:
            pool = await get_pool()
            stats = await run_tick(pool)
            if stats["expired"] or stats["notified"] or stats["gave_up"]:
                logger.info("payout requisite tick: %s", stats)
        except Exception:
            logger.exception("payout requisite loop tick failed")
        await asyncio.sleep(TICK_SECONDS)
