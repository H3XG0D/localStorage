"""База для зарплат админов и операторов: прибыль сервиса − кешбэк − рефералка."""
from __future__ import annotations

from operator_earnings import earnings_from_profit, order_profit_rub, utc_aware


async def fetch_accruals_for_orders(conn, order_ids: list[str]) -> dict[str, dict[str, float]]:
    """Начисления по order_id: cashback и referral (type=accrual)."""
    if not order_ids:
        return {}
    out: dict[str, dict[str, float]] = {oid: {"cashback": 0.0, "referral": 0.0} for oid in order_ids}

    cb_rows = await conn.fetch(
        """
        SELECT order_id, COALESCE(SUM(amount_rub), 0)::float AS rub
        FROM user_cashback_ledger
        WHERE order_id = ANY($1::text[]) AND type = 'accrual'
        GROUP BY order_id
        """,
        order_ids,
    )
    for r in cb_rows:
        oid = r["order_id"]
        if oid in out:
            out[oid]["cashback"] = float(r["rub"] or 0)

    ref_rows = await conn.fetch(
        """
        SELECT order_id, COALESCE(SUM(amount_rub), 0)::float AS rub
        FROM user_referral_ledger
        WHERE order_id = ANY($1::text[]) AND type = 'accrual'
        GROUP BY order_id
        """,
        order_ids,
    )
    for r in ref_rows:
        oid = r["order_id"]
        if oid and oid in out:
            out[oid]["referral"] = float(r["rub"] or 0)

    return out


def order_payroll_base_rub(order: dict, accruals_by_order: dict[str, dict[str, float]]) -> float:
    """Остаток после начисления кешбэка и рефералки по сделке."""
    oid = order.get("order_id")
    acc = accruals_by_order.get(oid, {}) if oid else {}
    deducted = float(acc.get("cashback", 0)) + float(acc.get("referral", 0))
    return max(0.0, order_profit_rub(order) - deducted)


def stats_from_orders(
    orders: list,
    percent: float,
    accruals_by_order: dict[str, dict[str, float]] | None = None,
) -> dict:
    accruals_by_order = accruals_by_order or {}
    fiat = 0.0
    service_profit = 0.0
    accruals_sum = 0.0
    payroll_base = 0.0

    for o in orders:
        fiat += float(o.get("fiat_amount") or 0)
        gross = order_profit_rub(o)
        oid = o.get("order_id")
        acc = accruals_by_order.get(oid, {}) if oid else {}
        deducted = float(acc.get("cashback", 0)) + float(acc.get("referral", 0))
        service_profit += gross
        accruals_sum += deducted
        payroll_base += max(0.0, gross - deducted)

    return {
        "orders_count": len(orders),
        "fiat_total": round(fiat, 2),
        "service_profit_rub": round(service_profit, 2),
        "accruals_rub": round(accruals_sum, 2),
        "profit_rub": round(payroll_base, 2),
        "earnings_rub": earnings_from_profit(payroll_base, percent),
    }


def stats_from_operator_orders(
    orders: list,
    percent: float,
    accruals_by_order: dict[str, dict[str, float]] | None = None,
    role_split_earnings_by_order: dict[str, float] | None = None,
) -> dict:
    """Legacy percent-of-profit plus role_split count/fiat/ledger lines."""
    accruals_by_order = accruals_by_order or {}
    role_split_earnings_by_order = role_split_earnings_by_order or {}
    legacy_orders = [
        o for o in orders if str(o.get("payroll_model") or "legacy") != "role_split"
    ]
    role_split_orders = [
        o for o in orders if str(o.get("payroll_model") or "legacy") == "role_split"
    ]
    st = stats_from_orders(legacy_orders, percent, accruals_by_order)
    split_fiat = sum(float(o.get("fiat_amount") or 0) for o in role_split_orders)
    split_earn = 0.0
    for o in role_split_orders:
        oid = o.get("order_id")
        if oid is None:
            continue
        split_earn += float(role_split_earnings_by_order.get(str(oid), 0) or 0)
    return {
        "orders_count": st["orders_count"] + len(role_split_orders),
        "fiat_total": round(st["fiat_total"] + split_fiat, 2),
        "service_profit_rub": st["service_profit_rub"],
        "accruals_rub": st["accruals_rub"],
        "profit_rub": st["profit_rub"],
        "earnings_rub": round(float(st["earnings_rub"] or 0) + split_earn, 2),
    }


async def stats_from_orders_conn(conn, orders: list, percent: float) -> dict:
    order_ids = [str(o["order_id"]) for o in orders if o.get("order_id")]
    accruals = await fetch_accruals_for_orders(conn, order_ids)
    return stats_from_orders(orders, percent, accruals)


SHIFT_ORDERS_SQL = """
    SELECT order_id, crypto, direction, fiat_amount, crypto_amount, rate,
           cashback_applied_rub, card_fee_pct, economics_snapshot,
           created_at, payout_confirmed_at
    FROM orders
    WHERE operator_id = $1
      AND status IN ('PAID', 'COMPLETED')
      AND COALESCE(payroll_model, 'legacy') <> 'role_split'
      AND COALESCE(payout_confirmed_at, updated_at, created_at) >= $2::timestamptz
      AND ($3::timestamptz IS NULL
           OR COALESCE(payout_confirmed_at, updated_at, created_at) <= $3::timestamptz)
"""


def operator_order_completed_at(order: dict):
    """Момент, когда оператор завершил заявку (подтвердил выплату)."""
    return (
        order.get("payout_confirmed_at")
        or order.get("updated_at")
        or order.get("created_at")
    )


async def fetch_shift_orders(
    conn, operator_id: int, started_at, ended_at
) -> list[dict]:
    """Legacy-only orders for shift-close accrual (role_split is accrued per order)."""
    started = utc_aware(started_at)
    ended = utc_aware(ended_at)
    rows = await conn.fetch(
        SHIFT_ORDERS_SQL,
        operator_id,
        started,
        ended,
    )
    return [dict(r) for r in rows]


ROLE_SPLIT_SHIFT_ORDERS_SQL = """
    SELECT o.order_id, o.crypto, o.direction, o.fiat_amount, o.crypto_amount, o.rate,
           o.cashback_applied_rub, o.card_fee_pct, o.economics_snapshot,
           o.created_at, o.payout_confirmed_at,
           o.updated_at, o.payroll_model
    FROM orders o
    WHERE COALESCE(o.payroll_model, 'legacy') = 'role_split'
      AND o.status IN ('PAID', 'COMPLETED')
      AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) >= $2::timestamptz
      AND ($3::timestamptz IS NULL
           OR COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) <= $3::timestamptz)
      AND (
        o.operator_id = $1
        OR o.intake_operator_id = $1
        OR o.finance_operator_id = $1
        OR EXISTS (
            SELECT 1 FROM order_operator_participants p
            WHERE p.order_id = o.order_id
              AND p.operator_id = $1
              AND p.released_at IS NULL
        )
      )
"""


async def fetch_role_split_shift_orders(
    conn, operator_id: int, started_at, ended_at
) -> list[dict]:
    started = utc_aware(started_at)
    ended = utc_aware(ended_at)
    rows = await conn.fetch(
        ROLE_SPLIT_SHIFT_ORDERS_SQL,
        operator_id,
        started,
        ended,
    )
    return [dict(r) for r in rows]


async def fetch_operator_shift_orders(
    conn, operator_id: int, started_at, ended_at
) -> list[dict]:
    """All completed orders for operator shift KPIs (legacy + role_split)."""
    legacy = await fetch_shift_orders(conn, operator_id, started_at, ended_at)
    role_split = await fetch_role_split_shift_orders(
        conn, operator_id, started_at, ended_at
    )
    by_id: dict[str, dict] = {}
    for row in legacy + role_split:
        oid = row.get("order_id")
        if oid:
            by_id[str(oid)] = row
    return list(by_id.values())


async def fetch_role_split_earnings_by_order(
    conn, operator_id: int, started_at, ended_at
) -> dict[str, float]:
    """Per-order role_split ledger amounts for this operator in a time window."""
    started = utc_aware(started_at)
    ended = utc_aware(ended_at)
    rows = await conn.fetch(
        """
        SELECT s.order_id, COALESCE(SUM(sl.amount_rub), 0)::float AS amount
        FROM order_payroll_split_lines sl
        JOIN order_payroll_splits s ON s.id = sl.split_id
        JOIN orders o ON o.order_id = s.order_id
        WHERE sl.operator_id = $1
          AND sl.role <> 'unassigned'
          AND o.status IN ('PAID', 'COMPLETED')
          AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) >= $2::timestamptz
          AND ($3::timestamptz IS NULL
               OR COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at)
                  <= $3::timestamptz)
        GROUP BY s.order_id
        """,
        operator_id,
        started,
        ended,
    )
    return {str(r["order_id"]): round(float(r["amount"] or 0), 2) for r in rows}


async def shift_role_split_earnings_rub(
    conn, operator_id: int, started_at, ended_at
) -> float:
    started = utc_aware(started_at)
    ended = utc_aware(ended_at)
    value = await conn.fetchval(
        """
        SELECT COALESCE(SUM(sl.amount_rub), 0)::float
        FROM order_payroll_split_lines sl
        JOIN order_payroll_splits s ON s.id = sl.split_id
        JOIN orders o ON o.order_id = s.order_id
        WHERE sl.operator_id = $1
          AND sl.role <> 'unassigned'
          AND o.status IN ('PAID', 'COMPLETED')
          AND COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at) >= $2::timestamptz
          AND ($3::timestamptz IS NULL
               OR COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at)
                  <= $3::timestamptz)
        """,
        operator_id,
        started,
        ended,
    )
    return round(float(value or 0), 2)


async def stats_for_operator_shift_conn(
    conn, operator_id: int, started_at, ended_at, percent: float
) -> dict:
    """Shift KPIs for the operator panel: legacy percent + role_split ledger lines."""
    orders = await fetch_operator_shift_orders(
        conn, operator_id, started_at, ended_at
    )
    legacy_orders = [
        o for o in orders if str(o.get("payroll_model") or "legacy") != "role_split"
    ]
    role_split_orders = [
        o for o in orders if str(o.get("payroll_model") or "legacy") == "role_split"
    ]

    legacy_stats = await stats_from_orders_conn(conn, legacy_orders, percent)
    role_split_fiat = round(
        sum(float(o.get("fiat_amount") or 0) for o in role_split_orders), 2
    )
    role_split_earnings = await shift_role_split_earnings_rub(
        conn, operator_id, started_at, ended_at
    )

    return {
        "orders_count": legacy_stats["orders_count"] + len(role_split_orders),
        "fiat_total": round(legacy_stats["fiat_total"] + role_split_fiat, 2),
        "service_profit_rub": legacy_stats["service_profit_rub"],
        "accruals_rub": legacy_stats["accruals_rub"],
        "profit_rub": legacy_stats["profit_rub"],
        "earnings_rub": round(
            float(legacy_stats["earnings_rub"] or 0) + role_split_earnings, 2
        ),
    }


def order_in_shift(order_at, shift_started, shift_ended) -> bool:
    t = utc_aware(order_at)
    started = utc_aware(shift_started)
    ended = utc_aware(shift_ended) if shift_ended else None
    if t is None or started is None:
        return False
    if t < started:
        return False
    if ended is not None and t > ended:
        return False
    return True


def order_completed_in_shift(order: dict, shift_started, shift_ended) -> bool:
    """Заявка засчитывается оператору по времени подтверждения выплаты."""
    return order_in_shift(
        operator_order_completed_at(order), shift_started, shift_ended
    )


# Open / in-progress work: not accrued into payroll. COMPLETED stays here because
# BUY may still need crypto sent; payroll uses PAID+COMPLETED separately.
IN_WORK_STATUS_SQL = "status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED')"

IN_WORK_BY_OPERATOR_SQL = f"""
    WITH assigned AS (
        SELECT o.operator_id AS oid, o.order_id, o.fiat_amount
        FROM orders o
        WHERE o.{IN_WORK_STATUS_SQL}
          AND o.operator_id IS NOT NULL
        UNION
        SELECT o.intake_operator_id, o.order_id, o.fiat_amount
        FROM orders o
        WHERE o.{IN_WORK_STATUS_SQL}
          AND o.intake_operator_id IS NOT NULL
        UNION
        SELECT o.finance_operator_id, o.order_id, o.fiat_amount
        FROM orders o
        WHERE o.{IN_WORK_STATUS_SQL}
          AND o.finance_operator_id IS NOT NULL
        UNION
        SELECT p.operator_id, o.order_id, o.fiat_amount
        FROM orders o
        JOIN order_operator_participants p ON p.order_id = o.order_id
        WHERE o.{IN_WORK_STATUS_SQL}
          AND p.released_at IS NULL
    )
    SELECT oid AS operator_id,
           COUNT(*)::int AS orders_in_work,
           COALESCE(SUM(fiat_amount), 0)::float AS in_work_rub
    FROM (
        SELECT DISTINCT oid, order_id, fiat_amount
        FROM assigned
        WHERE oid IS NOT NULL
    ) t
    GROUP BY oid
"""


async def fetch_in_work_by_operator(conn) -> dict[int, dict]:
    """Open orders per operator, including role_split intake/finance/participants."""
    rows = await conn.fetch(IN_WORK_BY_OPERATOR_SQL)
    return {
        int(r["operator_id"]): {
            "orders_in_work": int(r["orders_in_work"] or 0),
            "in_work_rub": round(float(r["in_work_rub"] or 0), 2),
        }
        for r in rows
        if r["operator_id"] is not None
    }
