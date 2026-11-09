"""Бизнес-дайджест: P&L + операторы + алерты для собственника."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from db import get_pool
from finance_pnl import compute_pnl
from operator_stats import compute_all_operators_sla

logger = logging.getLogger("business_digest")

MSK = ZoneInfo("Europe/Moscow")
BUSINESS_DIGEST_HOUR = 9


def business_delivery_date(now: datetime | None = None) -> date | None:
    """Return the due report date after 09:00 MSK, regardless of poll phase."""
    current = now.astimezone(MSK) if now is not None else datetime.now(MSK)
    if current.time() < time(BUSINESS_DIGEST_HOUR):
        return None
    return current.date() - timedelta(days=1)


async def build_business_digest(target_date: date | None = None) -> str:
    """Построить бизнес-дайджест за вчерашний день (или указанную дату).

    Включает:
    - P&L: revenue, costs, net profit
    - Заявки: количество, конверсия, средний чек
    - Операторы: top performer, SLA breaches
    - Алерты: критичные проблемы
    """
    if target_date is None:
        # Вчерашний день по МСК
        now = datetime.now(MSK)
        target_date = (now - timedelta(days=1)).date()

    # P&L за день
    pnl = await compute_pnl(target_date, target_date)

    # Заявки
    pool = await get_pool()
    async with pool.acquire() as conn:
        orders_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total_orders,
                COUNT(*) FILTER (WHERE status IN ('COMPLETED', 'PAID')) as completed_orders,
                AVG(fiat_amount) FILTER (WHERE status IN ('COMPLETED', 'PAID')) as avg_check_rub
            FROM orders
            WHERE created_at::date = $1
            """,
            target_date,
        )

        # Операторы: SLA за последние 7 дней (чтобы видеть тренды)
        sla_operators = await compute_all_operators_sla(conn, days=7)

    total_orders = orders_row["total_orders"] or 0
    completed_orders = orders_row["completed_orders"] or 0
    avg_check = float(orders_row["avg_check_rub"] or 0)
    conversion = round(completed_orders / total_orders * 100, 1) if total_orders > 0 else 0.0

    # Форматирование P&L по фактическому контракту compute_pnl.
    total = pnl.get("total") or {}
    costs_summary = pnl.get("costs") or {}
    payroll = pnl.get("payroll") or {}
    revenue = total.get("spread_revenue", 0)
    costs = costs_summary.get("total", 0)
    net_profit = payroll.get("owner_residual", 0)
    margin = total.get("owner_margin_pct", 0)
    casino_profit = float((pnl.get("casino") or {}).get("owner_profit_rub") or 0)

    processed_orders = sum(op.get("total_orders", 0) or 0 for op in sla_operators)
    completed_sla_samples = 0
    completed_sla_minutes = 0.0
    for op in sla_operators:
        sample_count = op.get("orders_with_complete_time", 0) or 0
        time_to_complete = op.get("time_to_complete") or {}
        completed_sla_samples += sample_count
        completed_sla_minutes += (time_to_complete.get("avg_minutes", 0) or 0) * sample_count
    avg_completion_sla = (
        round(completed_sla_minutes / completed_sla_samples, 2)
        if completed_sla_samples
        else 0.0
    )

    # Top performer
    top_op = None
    if sla_operators:
        top_op = min(
            sla_operators,
            key=lambda x: (
                x.get("sla_breaches", {}).get("total", 0)
                / max(x.get("total_orders", 0), 1)
            ),
        )

    # Алерты
    alerts = []

    # Убыточный день
    if net_profit < 0:
        alerts.append(f"🚨 Убыточный день: {net_profit:,.0f} ₽")

    # Низкая конверсия
    if conversion < 50 and total_orders > 10:
        alerts.append(f"⚠️ Низкая конверсия: {conversion}% (при {total_orders} заявках)")

    # SLA breaches >3
    high_breach_ops = [op for op in sla_operators if op.get("sla_breaches", {}).get("total", 0) > 3]
    if high_breach_ops:
        op_names = ", ".join([op.get("display_name") or op.get("username", "?") for op in high_breach_ops[:3]])
        alerts.append(f"⚠️ SLA breach >3: {op_names}")

    # Формирование текста
    lines = [
        f"<b>📊 Бизнес-дайджест {target_date.isoformat()}</b>",
        "",
        "<b>💰 P&L</b>",
        f"Выручка: <b>{revenue:,.0f} ₽</b>",
    ]
    lines.append(f"Казино: <b>{casino_profit:,.0f} ₽</b>")
    lines.extend(
        [
            f"Расходы: {costs:,.0f} ₽",
            f"Чистая прибыль: <b>{net_profit:,.0f} ₽</b> ({margin}%)",
            "",
            "<b>📦 Заявки</b>",
            f"Всего: {total_orders}",
            f"Завершено: {completed_orders} ({conversion}%)",
            f"Средний чек: {avg_check:,.0f} ₽",
            "",
        ]
    )

    lines.append("<b>👨‍💼 Операторы (7 дней)</b>")
    lines.append(f"Обработано: {processed_orders} заявок")
    lines.append(f"Средний SLA завершения: {avg_completion_sla:g} мин")
    if top_op:
        op_name = top_op.get("display_name") or top_op.get("username", "?")
        op_orders = top_op.get("total_orders", 0)
        breaches = top_op.get("sla_breaches", {}).get("total", 0)
        op_breach_rate = round(breaches / op_orders * 100, 1) if op_orders else 0.0
        lines.append(f"Top: {op_name} ({op_orders} заявок, breach {op_breach_rate}%)")
    else:
        lines.append("Top: нет данных")
    lines.append("")

    if alerts:
        lines.append("<b>🔔 Алерты</b>")
        lines.extend(alerts)
    else:
        lines.append("✅ Алертов нет")

    return "\n".join(lines)


async def send_business_digest(target_date: date | None = None) -> bool:
    """Claim and deliver one business digest; failed Telegram sends remain retryable."""
    from config import settings
    from digest_delivery import (
        claim_digest_delivery,
        complete_digest_delivery,
        release_digest_delivery,
    )
    from telegram_notify import send_admin_message

    group_id = settings.reports_telegram_group_id()
    if not group_id:
        logger.warning("reports_telegram_group_id not configured, skipping business digest")
        return False

    delivery_date = target_date or business_delivery_date()
    if delivery_date is None:
        return False
    claim_token = await claim_digest_delivery(
        digest_kind="business",
        recipient_key=str(int(group_id)),
        delivery_date=delivery_date,
    )
    if claim_token is None:
        return False

    try:
        text = await build_business_digest(delivery_date)
        message_id = await send_admin_message(text, chat_id=int(group_id))
        if message_id is None:
            logger.warning("Telegram rejected business digest date=%s", delivery_date)
            await release_digest_delivery(claim_token)
            return False
        if not await complete_digest_delivery(claim_token):
            logger.error("Lost business digest claim before completion date=%s", delivery_date)
            return False
        logger.info("Business digest sent for date=%s", delivery_date)
        return True
    except Exception as e:
        logger.exception("Failed to send business digest: %s", e)
        await release_digest_delivery(claim_token)
        return False
