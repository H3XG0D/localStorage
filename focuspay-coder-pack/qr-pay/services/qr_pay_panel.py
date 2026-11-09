"""Экран настроек оплаты по QR СБП для владельца: баланс, порог, наценка, лимиты."""
from __future__ import annotations

import logging

from services import finance666_client as api
from services.db import get_pool
from services.runtime_settings import (
    qr_pay_enabled,
    qr_pay_low_balance_allowlist,
    qr_pay_markup_pct,
    qr_pay_max_rub_per_day,
    qr_pay_max_rub_per_tx,
    qr_pay_min_merchant_usdt,
    save_settings,
)

logger = logging.getLogger("qr_pay_panel")

CB_PREFIX = "qrpay:"
CB_REFRESH = "qrpay:refresh"
CB_TOGGLE = "qrpay:toggle"

MARKUP_STEPS = (0.0, 1.0, 3.0, 5.0, 10.0)


def _money(value, digits: int = 2) -> str:
    return f"{float(value or 0):,.{digits}f}".replace(",", " ")


async def _usage_stats() -> dict:
    """Что происходило с оплатами за сутки — чтобы вкладка не была только настройками."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE local_status = 'SETTLED')::int AS paid,
                COUNT(*) FILTER (WHERE local_status = 'RESERVED')::int AS in_flight,
                COUNT(*) FILTER (WHERE local_status = 'RELEASED')::int AS failed,
                COUNT(*) FILTER (WHERE local_status = 'REFUNDED')::int AS refunded,
                COALESCE(SUM(charged_rub) FILTER (WHERE local_status = 'SETTLED'), 0)::float
                    AS paid_rub
            FROM qr_sbp_payments
            WHERE created_at >= now() - interval '24 hours'
            """
        )
    return dict(row) if row else {}


def _allowlist_line() -> str:
    entries = qr_pay_low_balance_allowlist()
    if not entries:
        return "👤 Исключения из порога: нет"
    shown = ", ".join(e if e.isdigit() else f"@{e}" for e in entries)
    return f"👤 Ниже порога платит только: <b>{shown}</b>"


async def build_panel_text() -> tuple[str, dict]:
    """Текст вкладки и состояние (для клавиатуры)."""
    from services.qr_pay_status import availability, currency

    enabled = qr_pay_enabled()
    state = await availability(force=True)
    balance = state.get("balance")
    threshold = qr_pay_min_merchant_usdt()

    if not api.configured():
        balance_line = "🔌 Ключ не задан: <code>FINANCE666_API_KEY</code> пуст"
    elif balance is None:
        balance_line = "⚠️ Баланс недоступен: платформа не ответила"
    else:
        mark = "✅" if balance >= threshold else "❌"
        balance_line = f"{mark} Баланс: <b>{_money(balance)} {currency()}</b>"

    if not enabled:
        status_line = "⛔ Оплата по QR <b>выключена</b>"
    elif state["reason"] == "low_balance_allowlisted":
        status_line = "⏳ Клиентам: <b>временно недоступно</b>, работает только исключение"
    elif state["available"]:
        status_line = "✅ Оплата по QR <b>работает</b>"
    elif state["reason"] == "low_balance":
        status_line = "⏳ Клиентам: <b>временно куары недоступны</b>"
        if qr_pay_low_balance_allowlist():
            status_line += ", кроме исключений"
    elif state["reason"] == "no_key":
        status_line = "⛔ Нет ключа платформы"
    else:
        status_line = "⏳ Клиентам: <b>временно недоступно</b>"

    try:
        stats = await _usage_stats()
    except Exception:
        logger.warning("qr pay stats failed", exc_info=True)
        stats = {}

    lines = [
        "<b>📷 Оплата по QR СБП · finance666</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        status_line,
        balance_line,
        f"🪫 Порог: <b>{_money(threshold)} USDT</b>",
        _allowlist_line(),
        "",
        "ℹ️ <b>Тариф и лимиты</b>",
        f"Наценка клиенту: <b>{_money(qr_pay_markup_pct())}%</b>",
        f"Лимит на платёж: <b>{_money(qr_pay_max_rub_per_tx(), 0)} ₽</b>",
        f"Лимит в сутки: <b>{_money(qr_pay_max_rub_per_day(), 0)} ₽</b>",
    ]
    if stats:
        lines += [
            "",
            "📊 <b>За 24 часа</b>",
            f"Оплачено: <b>{stats.get('paid') or 0}</b> на {_money(stats.get('paid_rub'))} ₽",
            f"В работе: {stats.get('in_flight') or 0} · "
            f"не прошло: {stats.get('failed') or 0} · "
            f"возвраты: {stats.get('refunded') or 0}",
        ]
    return "\n".join(lines), {"enabled": enabled}


def build_panel_keyboard(state: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    enabled = bool(state.get("enabled"))
    markup_now = qr_pay_markup_pct()
    markup_row = [
        InlineKeyboardButton(
            f"{'•' if abs(step - markup_now) < 0.01 else ''}{_money(step, 0)}%",
            callback_data=f"{CB_PREFIX}markup:{step}",
        )
        for step in MARKUP_STEPS
    ]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⛔ Выключить" if enabled else "✅ Включить",
                    callback_data=CB_TOGGLE,
                ),
                InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH),
            ],
            markup_row,
        ]
    )


async def apply_panel_action(data: str) -> str | None:
    """Обработать нажатие. Возвращает короткий ответ для alert, если есть."""
    action = (data or "")[len(CB_PREFIX) :]
    if action == "refresh":
        from services.qr_pay_status import invalidate

        invalidate()
        return None
    if action == "toggle":
        await save_settings({"qr_pay_enabled": not qr_pay_enabled()})
        return "Включено" if qr_pay_enabled() else "Выключено"
    if action.startswith("markup:"):
        try:
            value = float(action.split(":", 1)[1])
        except ValueError:
            return "Непонятная наценка"
        await save_settings({"qr_pay_markup_pct": value})
        return f"Наценка {_money(value, 0)}%"
    return None
