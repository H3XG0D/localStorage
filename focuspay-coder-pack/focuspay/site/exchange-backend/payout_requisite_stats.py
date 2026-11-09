"""Срез реквизитного пула: оборот, стоимость и экономия против провайдера карт.

Стоимость реквизита проводится в `owner_finance_ledger` один раз при
финализации (`payout_requisite_cost.post_requisite_cost`), поэтому и оборот
берём по финализированным реквизитам — обе цифры описывают один и тот же факт.
Знак сохраняем: плюс — доплатили реквизитчику (расход), минус — заработали.
"""
from __future__ import annotations

import logging
from datetime import date

from payout_requisite_cost import LEDGER_SOURCE

logger = logging.getLogger(__name__)

FINALIZED_STATUSES = ("CLOSED", "EXPIRED", "CANCELED")


def card_fee_auto_pct() -> float:
    """Комиссия провайдера карт — база для сравнения с реквизитным пулом."""
    from runtime_settings import get_settings_sync

    try:
        return float(get_settings_sync()["card_fee_auto_pct"])
    except Exception:
        logger.debug("card_fee_auto_pct unavailable", exc_info=True)
        return 0.0


def empty_pool_stats(card_fee_pct: float = 0.0) -> dict:
    return {
        "requisites": 0,
        "turnover_rub": 0.0,
        "cost_rub": 0.0,
        "avg_cost_pct": 0.0,
        "card_fee_pct": round(float(card_fee_pct), 2),
        "card_fee_cost_rub": 0.0,
        "saving_rub": 0.0,
    }


async def fetch_requisite_cost(conn, d_from: date, d_to: date) -> float:
    """Стоимость реквизитов за период по журналу. Может быть отрицательной."""
    try:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0)::float
            FROM owner_finance_ledger
            WHERE source = $3
              AND status = 'confirmed'
              AND occurred_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
            LEDGER_SOURCE,
        )
        return round(float(val or 0), 2)
    except Exception:
        logger.debug("payout requisite ledger unreadable", exc_info=True)
        return 0.0


async def fetch_requisite_cost_daily(conn, d_from: date, d_to: date) -> dict[str, float]:
    """Дата ISO → стоимость реквизитов этого дня."""
    try:
        rows = await conn.fetch(
            """
            SELECT occurred_at::date AS day, COALESCE(SUM(amount), 0)::float AS amount
            FROM owner_finance_ledger
            WHERE source = $3
              AND status = 'confirmed'
              AND occurred_at::date BETWEEN $1 AND $2
            GROUP BY 1
            """,
            d_from,
            d_to,
            LEDGER_SOURCE,
        )
    except Exception:
        logger.debug("payout requisite ledger unreadable", exc_info=True)
        return {}
    return {r["day"].isoformat(): round(float(r["amount"] or 0), 2) for r in rows}


async def fetch_requisite_pool_stats(
    conn,
    d_from: date,
    d_to: date,
    *,
    card_fee_pct: float = 0.0,
) -> dict:
    """Оборот пула и во сколько он обошёлся против того же объёма через карты."""
    fee_pct = max(0.0, float(card_fee_pct or 0))
    try:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS requisites,
                   COALESCE(SUM(paid_rub), 0)::float AS turnover,
                   COALESCE(SUM(paid_rub * cost_pct / 100), 0)::float AS cost
            FROM operator_payout_requisites
            WHERE status = ANY($3::text[])
              AND closed_at IS NOT NULL
              AND closed_at::date BETWEEN $1 AND $2
              AND paid_rub > 0
            """,
            d_from,
            d_to,
            list(FINALIZED_STATUSES),
        )
    except Exception:
        logger.debug("operator_payout_requisites unreadable", exc_info=True)
        return empty_pool_stats(fee_pct)

    if not row:
        return empty_pool_stats(fee_pct)

    turnover = float(row["turnover"] or 0)
    cost = float(row["cost"] or 0)
    card_fee_cost = turnover * fee_pct / 100.0
    return {
        "requisites": int(row["requisites"] or 0),
        "turnover_rub": round(turnover, 2),
        "cost_rub": round(cost, 2),
        "avg_cost_pct": round(cost / turnover * 100, 3) if turnover > 0 else 0.0,
        "card_fee_pct": round(fee_pct, 2),
        "card_fee_cost_rub": round(card_fee_cost, 2),
        "saving_rub": round(card_fee_cost - cost, 2),
    }


def sell_bonus_rub(card_rub: float, bonus_pct: float) -> float:
    """Доля доплаты внутри суммы на карте: 10300 при 3% → 300."""
    pct = max(0.0, float(bonus_pct or 0))
    amount = max(0.0, float(card_rub or 0))
    if pct <= 0 or amount <= 0:
        return 0.0
    return round(amount * pct / (100.0 + pct), 2)


def triangle_net_rub(
    saved_rub: float,
    sell_bonus: float,
    doliv_rub: float,
    withdraw_fee_rub: float,
    subsidy_rub: float = 0,
) -> float:
    """Экономия провайдера минус бонус продажи, долив и доплата коридора, плюс комиссия вывода.

    Возврат недостачи на баланс сюда не входит: это не расход.
    """
    return round(
        float(saved_rub) - float(sell_bonus) - float(doliv_rub) - float(subsidy_rub) + float(withdraw_fee_rub),
        2,
    )


_TRIANGLE_LIVE = ("QUEUED", "OPEN", "RESERVED", "PARTIAL")
_TRIANGLE_DONE = ("CLOSED", "EXPIRED", "CANCELED")


def _slice(
    turnover: float,
    sell_paid: float,
    doliv: float,
    balance_fee: float,
    casino_fee: float,
    *,
    provider_pct: float,
    bonus_pct: float,
    subsidy: float = 0,
    sell_bonus: float | None = None,
) -> dict:
    saved = round(float(turnover) * float(provider_pct) / 100.0, 2)
    bonus = sell_bonus_rub(sell_paid, bonus_pct) if sell_bonus is None else round(float(sell_bonus), 2)
    fee = round(float(balance_fee) + float(casino_fee), 2)
    subsidy_rub = round(float(subsidy or 0), 2)
    return {
        "turnover_rub": round(float(turnover), 2),
        "sell_paid_rub": round(float(sell_paid), 2),
        "saved_provider_rub": saved,
        "sell_bonus_rub": bonus,
        "subsidy_rub": subsidy_rub,
        "doliv_rub": round(float(doliv), 2),
        "balance_fee_rub": round(float(balance_fee), 2),
        "casino_fee_rub": round(float(casino_fee), 2),
        "withdraw_fee_rub": fee,
        "net_rub": triangle_net_rub(saved, bonus, doliv, fee, subsidy_rub),
    }


async def fetch_triangle_overview(conn, d_from, d_to) -> dict:
    """Живые карты треугольника и плюс за период против 12% провайдера."""
    from runtime_settings import triangle_enabled, triangle_sell_bonus_pct

    provider_pct = card_fee_auto_pct()
    bonus_pct = triangle_sell_bonus_pct()
    empty = _slice(0, 0, 0, 0, 0, provider_pct=provider_pct, bonus_pct=bonus_pct)
    try:
        live = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE source_sell_order_id IS NOT NULL)::int AS sell_cards,
              COUNT(*) FILTER (WHERE source_withdrawal_id IS NOT NULL)::int AS withdraw_cards,
              COALESCE(SUM(amount_rub) FILTER (WHERE source_sell_order_id IS NOT NULL), 0)::float AS sell_amount,
              COALESCE(SUM(amount_rub) FILTER (WHERE source_withdrawal_id IS NOT NULL), 0)::float AS withdraw_amount,
              COALESCE(SUM(paid_rub), 0)::float AS paid
            FROM operator_payout_requisites
            WHERE status = ANY($1::text[])
              AND (source_sell_order_id IS NOT NULL OR source_withdrawal_id IS NOT NULL)
            """,
            list(_TRIANGLE_LIVE),
        )
        reserved = await conn.fetchval(
            """
            SELECT COALESCE(SUM(a.amount_rub), 0)::float
            FROM payout_requisite_allocations a
            JOIN operator_payout_requisites r ON r.id = a.requisite_id
            WHERE a.status = 'RESERVED'
              AND r.status = ANY($1::text[])
              AND (r.source_sell_order_id IS NOT NULL OR r.source_withdrawal_id IS NOT NULL)
            """,
            list(_TRIANGLE_LIVE),
        )
        live_doliv = await conn.fetchval(
            """
            SELECT COALESCE(SUM(a.amount_rub), 0)::float
            FROM payout_requisite_allocations a
            JOIN operator_payout_requisites r ON r.id = a.requisite_id
            WHERE a.kind = 'doliv' AND a.status = 'PAID'
              AND r.status = ANY($1::text[])
              AND (r.source_sell_order_id IS NOT NULL OR r.source_withdrawal_id IS NOT NULL)
            """,
            list(_TRIANGLE_LIVE),
        )
        live_fee = await conn.fetchrow(
            """
            SELECT
              COALESCE(SUM(w.network_fee_rub) FILTER (
                WHERE COALESCE(w.source, 'balance') <> 'casino'
              ), 0)::float AS balance_fee,
              COALESCE(SUM(w.network_fee_rub) FILTER (
                WHERE COALESCE(w.source, 'balance') = 'casino'
              ), 0)::float AS casino_fee
            FROM operator_payout_requisites r
            JOIN user_referral_withdrawals w ON w.id = r.source_withdrawal_id
            WHERE r.status = ANY($1::text[])
            """,
            list(_TRIANGLE_LIVE),
        )
        period = await conn.fetchrow(
            """
            SELECT
              COUNT(*)::int AS cards,
              COALESCE(SUM(paid_rub), 0)::float AS turnover,
              COALESCE(SUM(paid_rub) FILTER (WHERE source_sell_order_id IS NOT NULL), 0)::float AS sell_paid,
              COALESCE(SUM(
                CASE
                  WHEN source_sell_order_id IS NOT NULL AND client_due_rub IS NOT NULL
                  THEN GREATEST(LEAST(paid_rub, amount_rub) - client_due_rub, 0)
                  ELSE 0
                END
              ), 0)::float AS sell_bonus_actual,
              COALESCE(SUM(paid_rub) FILTER (
                WHERE source_sell_order_id IS NOT NULL AND client_due_rub IS NULL
              ), 0)::float AS sell_paid_legacy,
              COALESCE(SUM(GREATEST(paid_rub - amount_rub, 0)), 0)::float AS subsidy
            FROM operator_payout_requisites
            WHERE status = ANY($3::text[])
              AND closed_at IS NOT NULL
              AND closed_at::date BETWEEN $1 AND $2
              AND paid_rub > 0
              AND (source_sell_order_id IS NOT NULL OR source_withdrawal_id IS NOT NULL)
            """,
            d_from,
            d_to,
            list(_TRIANGLE_DONE),
        )
        period_doliv = await conn.fetchval(
            """
            SELECT COALESCE(SUM(a.amount_rub), 0)::float
            FROM payout_requisite_allocations a
            JOIN operator_payout_requisites r ON r.id = a.requisite_id
            WHERE a.kind = 'doliv' AND a.status = 'PAID'
              AND r.closed_at IS NOT NULL
              AND r.closed_at::date BETWEEN $1 AND $2
              AND (r.source_sell_order_id IS NOT NULL OR r.source_withdrawal_id IS NOT NULL)
            """,
            d_from,
            d_to,
        )
        period_fee = await conn.fetchrow(
            """
            SELECT
              COALESCE(SUM(w.network_fee_rub) FILTER (
                WHERE COALESCE(w.source, 'balance') <> 'casino'
              ), 0)::float AS balance_fee,
              COALESCE(SUM(w.network_fee_rub) FILTER (
                WHERE COALESCE(w.source, 'balance') = 'casino'
              ), 0)::float AS casino_fee
            FROM operator_payout_requisites r
            JOIN user_referral_withdrawals w ON w.id = r.source_withdrawal_id
            WHERE r.status = ANY($3::text[])
              AND r.closed_at IS NOT NULL
              AND r.closed_at::date BETWEEN $1 AND $2
            """,
            d_from,
            d_to,
            list(_TRIANGLE_DONE),
        )
    except Exception:
        logger.debug("triangle overview unreadable", exc_info=True)
        live = None
        reserved = 0
        live_doliv = 0
        live_fee = None
        period = None
        period_doliv = 0
        period_fee = None

    sell_amount = float((live or {}).get("sell_amount") or 0) if live else 0.0
    withdraw_amount = float((live or {}).get("withdraw_amount") or 0) if live else 0.0
    if live is None:
        forecast = empty
    else:
        forecast = _slice(
            sell_amount + withdraw_amount,
            sell_amount,
            float(live_doliv or 0),
            float((live_fee or {}).get("balance_fee") or 0),
            float((live_fee or {}).get("casino_fee") or 0),
            provider_pct=provider_pct,
            bonus_pct=bonus_pct,
        )
    if period is None:
        closed = empty
    else:
        has_band = "sell_bonus_actual" in period or "subsidy" in period
        actual_bonus = None
        subsidy = 0.0
        if has_band:
            legacy_paid = float(period.get("sell_paid_legacy") or 0)
            actual_bonus = round(
                float(period.get("sell_bonus_actual") or 0) + sell_bonus_rub(legacy_paid, bonus_pct),
                2,
            )
            subsidy = float(period.get("subsidy") or 0)
        closed = _slice(
            float(period["turnover"] or 0),
            float(period["sell_paid"] or 0),
            float(period_doliv or 0),
            float((period_fee or {}).get("balance_fee") or 0),
            float((period_fee or {}).get("casino_fee") or 0),
            provider_pct=provider_pct,
            bonus_pct=bonus_pct,
            subsidy=subsidy,
            sell_bonus=actual_bonus,
        )
    from config import settings

    return {
        "enabled": triangle_enabled(),
        "sell_bonus_pct": bonus_pct,
        "provider_fee_pct": provider_pct,
        "withdraw_flat_fee_rub": float(settings.casino_withdraw_fee_card_rub),
        "open": {
            "sell_cards": int((live or {}).get("sell_cards") or 0) if live else 0,
            "withdraw_cards": int((live or {}).get("withdraw_cards") or 0) if live else 0,
            "sell_amount_rub": round(sell_amount, 2),
            "withdraw_amount_rub": round(withdraw_amount, 2),
            "paid_rub": round(float((live or {}).get("paid") or 0) if live else 0, 2),
            "reserved_rub": round(float(reserved or 0), 2),
        },
        "forecast": forecast,
        "period": closed,
    }
