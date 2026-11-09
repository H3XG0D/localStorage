"""Агрегированная статистика по внештатным обменам."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _iso(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def _round6(val) -> float:
    return round(float(val or 0), 6)


def _round2(val) -> float:
    return round(float(val or 0), 2)


def stats_from_row(row) -> dict[str, Any]:
    """Преобразовать строку агрегации в dict stats."""
    if not row:
        return empty_stats()
    deal_profit = _round6(row.get("deal_profit_usd"))
    payout_fee = _round6(row.get("payout_fee_usd"))
    paid = int(row.get("deals_confirmed") or row.get("deal_count") or 0)
    failed = int(row.get("deals_failed") or 0)
    awaiting = int(row.get("deals_awaiting") or 0)
    pending = int(row.get("deals_pending") or 0)
    cancelled = int(row.get("deals_cancelled") or 0)
    denom = paid + failed
    conversion_pct = round(100.0 * paid / denom, 1) if denom > 0 else None
    return {
        "balance_usd": _round6(row.get("balance_usd")),
        "deal_count": int(row.get("deal_count") or 0),
        "payout_count": int(row.get("payout_count") or 0),
        "turnover_base_rub": _round2(row.get("turnover_base_rub")),
        "turnover_client_rub": _round2(row.get("turnover_client_rub")),
        "total_credited_usd": _round6(row.get("total_credited_usd")),
        "total_paid_out_usd": _round6(row.get("total_paid_out_usd")),
        "deal_profit_usd": deal_profit,
        "payout_fee_usd": payout_fee,
        "house_profit_usd": _round6(deal_profit + payout_fee),
        "last_deal_at": _iso(row.get("last_deal_at")),
        "last_payout_at": _iso(row.get("last_payout_at")),
        "deals_confirmed": paid,
        "deals_failed": failed,
        "deals_awaiting": awaiting,
        "deals_pending": pending,
        "deals_cancelled": cancelled,
        "deals_open": awaiting + pending,
        "conversion_pct": conversion_pct,
    }


def empty_stats() -> dict[str, Any]:
    return {
        "balance_usd": 0.0,
        "deal_count": 0,
        "payout_count": 0,
        "turnover_base_rub": 0.0,
        "turnover_client_rub": 0.0,
        "total_credited_usd": 0.0,
        "total_paid_out_usd": 0.0,
        "deal_profit_usd": 0.0,
        "payout_fee_usd": 0.0,
        "house_profit_usd": 0.0,
        "last_deal_at": None,
        "last_payout_at": None,
        "deals_confirmed": 0,
        "deals_failed": 0,
        "deals_awaiting": 0,
        "deals_pending": 0,
        "deals_cancelled": 0,
        "deals_open": 0,
        "conversion_pct": None,
    }


_STATS_SQL = """
SELECT
    COALESCE(l.balance_usd, 0)::float AS balance_usd,
    COALESCE(d.deal_count, 0)::int AS deal_count,
    COALESCE(p.payout_count, 0)::int AS payout_count,
    COALESCE(d.turnover_base_rub, 0)::float AS turnover_base_rub,
    COALESCE(d.turnover_client_rub, 0)::float AS turnover_client_rub,
    COALESCE(d.total_credited_usd, 0)::float AS total_credited_usd,
    COALESCE(p.total_paid_out_usd, 0)::float AS total_paid_out_usd,
    COALESCE(d.deal_profit_usd, 0)::float AS deal_profit_usd,
    COALESCE(p.payout_fee_usd, 0)::float AS payout_fee_usd,
    d.last_deal_at,
    p.last_payout_at
FROM (SELECT 1) x
LEFT JOIN (
    SELECT
        COALESCE(SUM(amount_usd), 0) AS balance_usd
    FROM external_ledger
    WHERE exchanger_id = $1
) l ON TRUE
LEFT JOIN (
    SELECT
        COUNT(*) FILTER (WHERE status = 'confirmed') AS deal_count,
        COUNT(*) FILTER (WHERE status = 'confirmed') AS deals_confirmed,
        COUNT(*) FILTER (WHERE status IN ('cancelled', 'canceled', 'failed', 'expired')) AS deals_failed,
        COUNT(*) FILTER (WHERE status = 'awaiting_receipt') AS deals_awaiting,
        COUNT(*) FILTER (WHERE status = 'pending') AS deals_pending,
        COUNT(*) FILTER (WHERE status IN ('cancelled', 'canceled')) AS deals_cancelled,
        COALESCE(SUM(amount_rub) FILTER (WHERE status = 'confirmed'), 0) AS turnover_base_rub,
        COALESCE(SUM(client_pays_rub) FILTER (WHERE status = 'confirmed'), 0) AS turnover_client_rub,
        COALESCE(SUM(principal_usdt + reward_usdt) FILTER (WHERE status = 'confirmed'), 0) AS total_credited_usd,
        COALESCE(SUM(house_profit_usd) FILTER (WHERE status = 'confirmed'), 0) AS deal_profit_usd,
        MAX(created_at) FILTER (WHERE status = 'confirmed') AS last_deal_at
    FROM external_deals
    WHERE exchanger_id = $1
) d ON TRUE
LEFT JOIN (
    SELECT
        COUNT(*) FILTER (WHERE status = 'paid') AS payout_count,
        COALESCE(SUM(gross_usd) FILTER (WHERE status = 'paid'), 0) AS total_paid_out_usd,
        COALESCE(SUM(fee_usd) FILTER (WHERE status = 'paid'), 0) AS payout_fee_usd,
        MAX(created_at) FILTER (WHERE status = 'paid') AS last_payout_at
    FROM external_payouts
    WHERE exchanger_id = $1
) p ON TRUE
"""


async def fetch_exchanger_stats(conn, exchanger_id: int) -> dict[str, Any]:
    row = await conn.fetchrow(_STATS_SQL, exchanger_id)
    return stats_from_row(row)


_PERIOD_EXCHANGER_SQL = """
SELECT
    COALESCE(d.deal_count, 0)::int AS deal_count,
    COALESCE(d.deals_confirmed, 0)::int AS deals_confirmed,
    COALESCE(d.deals_failed, 0)::int AS deals_failed,
    COALESCE(d.deals_awaiting, 0)::int AS deals_awaiting,
    COALESCE(d.deals_pending, 0)::int AS deals_pending,
    COALESCE(d.deals_cancelled, 0)::int AS deals_cancelled,
    COALESCE(p.payout_count, 0)::int AS payout_count,
    COALESCE(d.turnover_base_rub, 0)::float AS turnover_base_rub,
    COALESCE(d.turnover_client_rub, 0)::float AS turnover_client_rub,
    COALESCE(d.total_credited_usd, 0)::float AS total_credited_usd,
    COALESCE(p.total_paid_out_usd, 0)::float AS total_paid_out_usd,
    COALESCE(d.deal_profit_usd, 0)::float AS deal_profit_usd,
    COALESCE(p.payout_fee_usd, 0)::float AS payout_fee_usd,
    d.last_deal_at,
    p.last_payout_at,
    0::float AS balance_usd
FROM (SELECT 1) x
LEFT JOIN (
    SELECT
        COUNT(*) FILTER (WHERE status = 'confirmed') AS deal_count,
        COUNT(*) FILTER (WHERE status = 'confirmed') AS deals_confirmed,
        COUNT(*) FILTER (WHERE status IN ('cancelled', 'canceled', 'failed', 'expired')) AS deals_failed,
        COUNT(*) FILTER (WHERE status = 'awaiting_receipt') AS deals_awaiting,
        COUNT(*) FILTER (WHERE status = 'pending') AS deals_pending,
        COUNT(*) FILTER (WHERE status IN ('cancelled', 'canceled')) AS deals_cancelled,
        COALESCE(SUM(amount_rub) FILTER (WHERE status = 'confirmed'), 0) AS turnover_base_rub,
        COALESCE(SUM(client_pays_rub) FILTER (WHERE status = 'confirmed'), 0) AS turnover_client_rub,
        COALESCE(SUM(principal_usdt + reward_usdt) FILTER (WHERE status = 'confirmed'), 0) AS total_credited_usd,
        COALESCE(SUM(house_profit_usd) FILTER (WHERE status = 'confirmed'), 0) AS deal_profit_usd,
        MAX(created_at) FILTER (WHERE status = 'confirmed') AS last_deal_at
    FROM external_deals
    WHERE exchanger_id = $1 AND created_at::date BETWEEN $2 AND $3
) d ON TRUE
LEFT JOIN (
    SELECT
        COUNT(*) FILTER (WHERE status = 'paid') AS payout_count,
        COALESCE(SUM(gross_usd) FILTER (WHERE status = 'paid'), 0) AS total_paid_out_usd,
        COALESCE(SUM(fee_usd) FILTER (WHERE status = 'paid'), 0) AS payout_fee_usd,
        MAX(created_at) FILTER (WHERE status = 'paid') AS last_payout_at
    FROM external_payouts
    WHERE exchanger_id = $1 AND created_at::date BETWEEN $2 AND $3
) p ON TRUE
"""


async def fetch_exchanger_period_stats(
    conn,
    exchanger_id: int,
    d_from: date,
    d_to: date,
) -> dict[str, Any]:
    """Метрики одного внештатника за период (баланс в результате = 0, брать lifetime)."""
    row = await conn.fetchrow(_PERIOD_EXCHANGER_SQL, exchanger_id, d_from, d_to)
    return stats_from_row(row)


_PERIOD_EXCHANGER_DAILY_SQL = """
SELECT day,
       SUM(deal_profit_usd)::float AS deal_profit_usd,
       SUM(turnover_rub)::float AS turnover_rub,
       SUM(deal_count)::int AS deal_count,
       SUM(cancelled_count)::int AS cancelled_count
FROM (
    SELECT created_at::date AS day,
           CASE WHEN status = 'confirmed' THEN house_profit_usd ELSE 0 END AS deal_profit_usd,
           CASE WHEN status = 'confirmed' THEN amount_rub ELSE 0 END AS turnover_rub,
           CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END AS deal_count,
           CASE WHEN status IN ('cancelled', 'canceled') THEN 1 ELSE 0 END AS cancelled_count
    FROM external_deals
    WHERE exchanger_id = $1 AND created_at::date BETWEEN $2 AND $3
    UNION ALL
    SELECT created_at::date AS day,
           fee_usd AS deal_profit_usd,
           0::numeric AS turnover_rub,
           0,
           0
    FROM external_payouts
    WHERE exchanger_id = $1
      AND status = 'paid'
      AND created_at::date BETWEEN $2 AND $3
) x
GROUP BY day
ORDER BY day
"""


async def fetch_exchanger_period_daily(
    conn,
    exchanger_id: int,
    d_from: date,
    d_to: date,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(_PERIOD_EXCHANGER_DAILY_SQL, exchanger_id, d_from, d_to)
    out: list[dict[str, Any]] = []
    for r in rows:
        day = r["day"].isoformat() if hasattr(r["day"], "isoformat") else str(r["day"])
        out.append({
            "date": day,
            "profit_usd": _round6(r["deal_profit_usd"]),
            "turnover_rub": _round2(r["turnover_rub"]),
            "deal_count": int(r["deal_count"] or 0),
            "cancelled_count": int(r["cancelled_count"] or 0),
        })
    return out


_OPS_STATS_SQL = """
SELECT
    COUNT(*) FILTER (WHERE status = 'confirmed')::int AS confirmed_count,
    COUNT(*) FILTER (WHERE status IN ('cancelled', 'canceled', 'failed', 'expired'))::int AS failed_count,
    COALESCE(SUM(client_pays_rub) FILTER (WHERE status = 'confirmed'), 0)::float AS total_turnover_rub,
    MAX(created_at) FILTER (WHERE status = 'confirmed') AS last_confirmed_at
FROM external_deals
WHERE exchanger_id = $1
"""


async def fetch_exchanger_ops_stats(conn, exchanger_id: int) -> dict[str, Any]:
    """Статистика внештатника для ops-уведомлений."""
    row = await conn.fetchrow(_OPS_STATS_SQL, exchanger_id)
    if not row:
        return {
            "confirmed_count": 0,
            "failed_count": 0,
            "conversion_pct": None,
            "total_turnover_rub": 0.0,
            "last_confirmed_at": None,
        }
    last_at = row["last_confirmed_at"]
    if isinstance(last_at, datetime):
        last_at = last_at.isoformat()
    paid = int(row["confirmed_count"] or 0)
    failed = int(row["failed_count"] or 0)
    denom = paid + failed
    conversion_pct = round(100.0 * paid / denom, 1) if denom > 0 else None
    return {
        "confirmed_count": paid,
        "failed_count": failed,
        "conversion_pct": conversion_pct,
        "total_turnover_rub": _round2(row["total_turnover_rub"]),
        "last_confirmed_at": last_at,
    }


async def fetch_stats_map(conn, exchanger_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not exchanger_ids:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for eid in exchanger_ids:
        out[eid] = await fetch_exchanger_stats(conn, eid)
    return out


_SUMMARY_SQL = """
SELECT
    COUNT(*) FILTER (WHERE is_active) AS active_count,
    COUNT(*) AS total_count,
    COALESCE((
        SELECT SUM(amount_usd) FROM external_ledger
    ), 0)::float AS total_balance_usd,
    COALESCE((
        SELECT SUM(amount_rub) FROM external_deals WHERE status = 'confirmed'
    ), 0)::float AS total_turnover_base_rub,
    COALESCE((
        SELECT SUM(client_pays_rub) FROM external_deals WHERE status = 'confirmed'
    ), 0)::float AS total_turnover_client_rub,
    COALESCE((
        SELECT SUM(house_profit_usd) FROM external_deals WHERE status = 'confirmed'
    ), 0)::float AS total_deal_profit_usd,
    COALESCE((
        SELECT SUM(fee_usd) FROM external_payouts WHERE status = 'paid'
    ), 0)::float AS total_payout_fee_usd,
    COALESCE((
        SELECT COUNT(*) FROM external_deals WHERE status = 'confirmed'
    ), 0)::int AS total_deals,
    COALESCE((
        SELECT COUNT(*) FROM external_payouts WHERE status = 'paid'
    ), 0)::int AS total_payouts
FROM external_exchangers
"""


_PERIOD_SUMMARY_SQL = """
SELECT
    COALESCE((
        SELECT COUNT(*)::int FROM external_deals
        WHERE status = 'confirmed' AND created_at::date BETWEEN $1 AND $2
    ), 0) AS deal_count,
    COALESCE((
        SELECT SUM(amount_rub) FROM external_deals
        WHERE status = 'confirmed' AND created_at::date BETWEEN $1 AND $2
    ), 0)::float AS turnover_base_rub,
    COALESCE((
        SELECT SUM(client_pays_rub) FROM external_deals
        WHERE status = 'confirmed' AND created_at::date BETWEEN $1 AND $2
    ), 0)::float AS turnover_client_rub,
    COALESCE((
        SELECT SUM(house_profit_usd) FROM external_deals
        WHERE status = 'confirmed' AND created_at::date BETWEEN $1 AND $2
    ), 0)::float AS deal_profit_usd,
    COALESCE((
        SELECT SUM(house_profit_usd * usdt_rate_rub) FROM external_deals
        WHERE status = 'confirmed' AND created_at::date BETWEEN $1 AND $2
    ), 0)::float AS deal_profit_rub,
    COALESCE((
        SELECT COUNT(*)::int FROM external_payouts
        WHERE status = 'paid' AND created_at::date BETWEEN $1 AND $2
    ), 0) AS payout_count,
    COALESCE((
        SELECT SUM(fee_usd) FROM external_payouts
        WHERE status = 'paid' AND created_at::date BETWEEN $1 AND $2
    ), 0)::float AS payout_fee_usd
"""


async def fetch_period_summary(
    conn,
    d_from: date,
    d_to: date,
    *,
    usdt_rub_rate: float = 0.0,
) -> dict[str, Any]:
    """Агрегат внештатных обменов за период (подтверждённые сделки + оплаченные выводы)."""
    row = await conn.fetchrow(_PERIOD_SUMMARY_SQL, d_from, d_to)
    if not row:
        return empty_period_summary()
    deal_profit_usd = _round6(row["deal_profit_usd"])
    payout_fee_usd = _round6(row["payout_fee_usd"])
    house_profit_usd = _round6(deal_profit_usd + payout_fee_usd)
    rate = float(usdt_rub_rate or 0)
    deal_profit_rub = _round2(row["deal_profit_rub"])
    payout_fee_rub = _round2(payout_fee_usd * rate) if rate > 0 else 0.0
    house_profit_rub = _round2(deal_profit_rub + payout_fee_rub)
    return {
        "deal_count": int(row["deal_count"] or 0),
        "payout_count": int(row["payout_count"] or 0),
        "turnover_base_rub": _round2(row["turnover_base_rub"]),
        "turnover_client_rub": _round2(row["turnover_client_rub"]),
        "deal_profit_usd": deal_profit_usd,
        "payout_fee_usd": payout_fee_usd,
        "house_profit_usd": house_profit_usd,
        "deal_profit_rub": deal_profit_rub,
        "payout_fee_rub": payout_fee_rub,
        "house_profit_rub": house_profit_rub,
        "usdt_rub_rate": round(rate, 4) if rate > 0 else None,
    }


def empty_period_summary() -> dict[str, Any]:
    return {
        "deal_count": 0,
        "payout_count": 0,
        "turnover_base_rub": 0.0,
        "turnover_client_rub": 0.0,
        "deal_profit_usd": 0.0,
        "payout_fee_usd": 0.0,
        "house_profit_usd": 0.0,
        "deal_profit_rub": 0.0,
        "payout_fee_rub": 0.0,
        "house_profit_rub": 0.0,
        "usdt_rub_rate": None,
    }


_PERIOD_DAILY_SQL = """
SELECT day, SUM(deal_profit_usd)::float AS deal_profit_usd,
       SUM(turnover_rub)::float AS turnover_rub
FROM (
    SELECT created_at::date AS day,
           house_profit_usd AS deal_profit_usd,
           amount_rub AS turnover_rub
    FROM external_deals
    WHERE status = 'confirmed' AND created_at::date BETWEEN $1 AND $2
    UNION ALL
    SELECT created_at::date AS day,
           fee_usd AS deal_profit_usd,
           0::numeric AS turnover_rub
    FROM external_payouts
    WHERE status = 'paid' AND created_at::date BETWEEN $1 AND $2
) x
GROUP BY day
"""


async def fetch_period_daily(conn, d_from: date, d_to: date) -> dict[str, dict[str, float]]:
    """Прибыль и оборот внештатных обменов по дням (profit в USD)."""
    rows = await conn.fetch(_PERIOD_DAILY_SQL, d_from, d_to)
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        day = r["day"].isoformat() if hasattr(r["day"], "isoformat") else str(r["day"])
        out[day] = {
            "profit_usd": _round6(r["deal_profit_usd"]),
            "turnover_rub": _round2(r["turnover_rub"]),
        }
    return out


async def fetch_global_summary(conn, *, active_only: bool = True) -> dict[str, Any]:
    row = await conn.fetchrow(_SUMMARY_SQL)
    if not row:
        return {
            "active_count": 0,
            "total_count": 0,
            "total_balance_usd": 0.0,
            "total_turnover_base_rub": 0.0,
            "total_turnover_client_rub": 0.0,
            "house_profit_usd": 0.0,
            "total_deals": 0,
            "total_payouts": 0,
        }
    deal_profit = _round6(row["total_deal_profit_usd"])
    payout_fee = _round6(row["total_payout_fee_usd"])
    active_count = int(row["active_count"] or 0)
    total_count = int(row["total_count"] or 0)
    return {
        "active_count": active_count if active_only else total_count,
        "total_count": total_count,
        "total_balance_usd": _round6(row["total_balance_usd"]),
        "total_turnover_base_rub": _round2(row["total_turnover_base_rub"]),
        "total_turnover_client_rub": _round2(row["total_turnover_client_rub"]),
        "house_profit_usd": _round6(deal_profit + payout_fee),
        "deal_profit_usd": deal_profit,
        "payout_fee_usd": payout_fee,
        "total_deals": int(row["total_deals"] or 0),
        "total_payouts": int(row["total_payouts"] or 0),
    }


_HISTORY_SQL = """
SELECT * FROM (
    SELECT
        'deal' AS kind,
        d.id,
        d.created_at AS at,
        d.amount_rub,
        d.client_pays_rub,
        (d.principal_usdt + d.reward_usdt) AS amount_usd,
        d.house_profit_usd,
        (d.house_profit_usd * d.usdt_rate_rub) AS house_profit_rub,
        d.crypto,
        d.note,
        d.created_by,
        d.status,
        d.merchant_order_id,
        d.payfast_fee_rub,
        d.operator_earnings_rub,
        (d.receipt_file IS NOT NULL AND d.receipt_file <> '') AS has_receipt,
        NULL::numeric AS gross_usd,
        NULL::numeric AS net_usd,
        NULL::numeric AS fee_usd,
        NULL::numeric AS crypto_amount,
        d.principal_usdt,
        d.reward_usdt,
        d.net_profit_rub,
        d.expires_at
    FROM external_deals d
    WHERE d.exchanger_id = $1
    UNION ALL
    SELECT
        'payout' AS kind,
        p.id,
        p.created_at AS at,
        NULL::numeric AS amount_rub,
        NULL::numeric AS client_pays_rub,
        -p.gross_usd AS amount_usd,
        p.fee_usd AS house_profit_usd,
        NULL::numeric AS house_profit_rub,
        p.crypto,
        p.note,
        p.created_by,
        p.status,
        NULL::text AS merchant_order_id,
        NULL::numeric AS payfast_fee_rub,
        NULL::numeric AS operator_earnings_rub,
        FALSE AS has_receipt,
        p.gross_usd,
        p.net_usd,
        p.fee_usd,
        p.crypto_amount,
        NULL::numeric AS principal_usdt,
        NULL::numeric AS reward_usdt,
        NULL::numeric AS net_profit_rub,
        NULL::timestamptz AS expires_at
    FROM external_payouts p
    WHERE p.exchanger_id = $1
) h
ORDER BY at DESC
LIMIT $2 OFFSET $3
"""


def _history_date_sql(d_from: date | None, d_to: date | None) -> tuple[str, str, list]:
    extra_d = ""
    extra_p = ""
    params: list = []
    if d_from:
        extra_d += f" AND d.created_at::date >= ${len(params) + 2}"
        extra_p += f" AND p.created_at::date >= ${len(params) + 2}"
        params.append(d_from)
    if d_to:
        extra_d += f" AND d.created_at::date <= ${len(params) + 2}"
        extra_p += f" AND p.created_at::date <= ${len(params) + 2}"
        params.append(d_to)
    return extra_d, extra_p, params


async def fetch_history(
    conn,
    exchanger_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[dict[str, Any]], int]:
    extra_d, extra_p, range_params = _history_date_sql(date_from, date_to)
    count_sql = f"""
SELECT (
    SELECT COUNT(*) FROM external_deals d WHERE d.exchanger_id = $1{extra_d}
) + (
    SELECT COUNT(*) FROM external_payouts p WHERE p.exchanger_id = $1{extra_p}
) AS total
"""
    list_sql = _HISTORY_SQL.replace(
        "WHERE d.exchanger_id = $1",
        f"WHERE d.exchanger_id = $1{extra_d}",
    ).replace(
        "WHERE p.exchanger_id = $1",
        f"WHERE p.exchanger_id = $1{extra_p}",
    )
    n_range = len(range_params)
    list_sql = list_sql.replace("LIMIT $2 OFFSET $3", f"LIMIT ${n_range + 2} OFFSET ${n_range + 3}")
    total = int(await conn.fetchval(count_sql, exchanger_id, *range_params) or 0)
    rows = await conn.fetch(list_sql, exchanger_id, *range_params, limit, offset)
    items: list[dict[str, Any]] = []
    for r in rows:
        item = {
            "kind": r["kind"],
            "id": int(r["id"]),
            "at": _iso(r["at"]),
            "amount_rub": float(r["amount_rub"]) if r["amount_rub"] is not None else None,
            "client_pays_rub": float(r["client_pays_rub"]) if r["client_pays_rub"] is not None else None,
            "amount_usd": float(r["amount_usd"]) if r["amount_usd"] is not None else None,
            "house_profit_usd": float(r["house_profit_usd"]) if r["house_profit_usd"] is not None else None,
            "house_profit_rub": float(r["house_profit_rub"]) if r["house_profit_rub"] is not None else None,
            "crypto": r["crypto"],
            "note": r["note"],
            "created_by": r["created_by"],
            "status": r["status"],
            "merchant_order_id": r["merchant_order_id"],
            "payfast_fee_rub": float(r["payfast_fee_rub"]) if r["payfast_fee_rub"] is not None else None,
            "operator_earnings_rub": float(r["operator_earnings_rub"]) if r["operator_earnings_rub"] is not None else None,
            "has_receipt": bool(r["has_receipt"]),
            "gross_usd": float(r["gross_usd"]) if r["gross_usd"] is not None else None,
            "net_usd": float(r["net_usd"]) if r["net_usd"] is not None else None,
            "fee_usd": float(r["fee_usd"]) if r["fee_usd"] is not None else None,
            "crypto_amount": float(r["crypto_amount"]) if r["crypto_amount"] is not None else None,
            "principal_usdt": float(r["principal_usdt"]) if r["principal_usdt"] is not None else None,
            "reward_usdt": float(r["reward_usdt"]) if r["reward_usdt"] is not None else None,
            "net_profit_rub": float(r["net_profit_rub"]) if r["net_profit_rub"] is not None else None,
            "expires_at": _iso(r["expires_at"]) if r.get("expires_at") is not None else None,
        }
        if item["kind"] == "deal":
            item["credited_usd"] = item["amount_usd"]
        items.append(item)
    return items, total
