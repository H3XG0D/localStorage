#!/usr/bin/env python3
"""Проверка финансовых инвариантов в БД (запускать на сервере или с доступом к DSN)."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from services.config_rates import DATABASE_DSN

QUERIES = {
    "paid_buy_without_cashback_accrual": """
        SELECT o.order_id, o.user_id, o.fiat_amount, o.status
        FROM orders o
        WHERE o.direction = 'buy'
          AND o.status = 'PAID'
          AND NOT EXISTS (
              SELECT 1 FROM user_cashback_ledger l
              WHERE l.order_id = o.order_id AND l.type = 'accrual'
          )
        ORDER BY o.updated_at DESC
        LIMIT 20
    """,
    "paid_without_referral_accrual_when_attributed": """
        SELECT o.order_id, o.user_id
        FROM orders o
        JOIN user_referral_attributions a ON a.user_id = o.user_id
        WHERE o.status = 'PAID'
          AND NOT EXISTS (
              SELECT 1 FROM user_referral_ledger l WHERE l.order_id = o.order_id
          )
        ORDER BY o.updated_at DESC
        LIMIT 20
    """,
    "cashback_hold_without_order": """
        SELECT l.order_id, l.user_id, l.amount_rub
        FROM user_cashback_ledger l
        WHERE l.type = 'hold'
          AND NOT EXISTS (
              SELECT 1 FROM orders o
              WHERE o.order_id = replace(l.order_id, 'hold-', '')
                AND o.status IN ('CREATED', 'PENDING', 'AWAITING_CHECK', 'COMPLETED', 'PAID')
          )
        LIMIT 20
    """,
    "pending_withdrawals_over_available": """
        SELECT w.id, w.referrer_user_id, w.amount_rub,
               COALESCE(cb.balance, 0) + COALESCE(ref.balance, 0) AS ledger_total
        FROM user_referral_withdrawals w
        LEFT JOIN LATERAL (
            SELECT COALESCE(SUM(amount_rub), 0)::float AS balance
            FROM user_cashback_ledger WHERE user_id = w.referrer_user_id
        ) cb ON TRUE
        LEFT JOIN LATERAL (
            SELECT COALESCE(SUM(amount_rub), 0)::float AS balance
            FROM user_referral_ledger WHERE referrer_user_id = w.referrer_user_id
        ) ref ON TRUE
        WHERE w.status = 'pending'
          AND w.amount_rub > COALESCE(cb.balance, 0) + COALESCE(ref.balance, 0) + 0.01
        LIMIT 20
    """,
    "duplicate_referral_accrual_per_order": """
        SELECT order_id, COUNT(*)::int AS cnt
        FROM user_referral_ledger
        WHERE type = 'accrual' AND order_id IS NOT NULL
        GROUP BY order_id
        HAVING COUNT(*) > 1
        LIMIT 20
    """,
    "paid_without_cashback_spend_after_paid_buy": """
        SELECT o.order_id
        FROM orders o
        WHERE o.direction = 'buy'
          AND o.status = 'PAID'
          AND o.cashback_applied_rub > 0
          AND EXISTS (
              SELECT 1 FROM user_cashback_ledger h
              WHERE h.order_id = 'hold-' || o.order_id AND h.type = 'hold'
          )
          AND NOT EXISTS (
              SELECT 1 FROM user_cashback_ledger s
              WHERE s.order_id = 'spend-' || o.order_id AND s.type = 'spend'
          )
        LIMIT 20
    """,
    "pending_ltc_raffle_winners": """
        SELECT w.id, w.campaign_id, w.place, w.user_id, w.prize_rub
        FROM raffle_winners w
        JOIN raffle_campaigns c ON c.id = w.campaign_id
        WHERE w.payout_method = 'ltc'
          AND w.status = 'pending'
          AND c.status = 'drawn'
        ORDER BY w.campaign_id DESC, w.place
        LIMIT 20
    """,
}


async def main() -> int:
    if not DATABASE_DSN:
        print("DATABASE_DSN is not set", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(DATABASE_DSN)
    issues = 0
    try:
        for name, sql in QUERIES.items():
            rows = await conn.fetch(sql)
            if rows:
                issues += len(rows)
                print(f"\n[!] {name}: {len(rows)} row(s)")
                for row in rows[:5]:
                    print("   ", dict(row))
                if len(rows) > 5:
                    print(f"    ... and {len(rows) - 5} more")
            else:
                print(f"[ok] {name}")
    finally:
        await conn.close()

    if issues:
        print(f"\nTotal suspicious rows: {issues}")
        return 2
    print("\nAll financial integrity checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
