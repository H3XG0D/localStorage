#!/usr/bin/env python3
"""Догон начислений кешбэка для PAID BUY без accrual в ledger (profit > 0)."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_ROOT not in sys.path:
    sys.path.insert(0, BOT_ROOT)

from services.economics_snapshot import order_economics
from services.user_cashback_commission import accrue_user_cashback


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать заявки, без INSERT в ledger",
    )
    args = parser.parse_args()

    from services import config_rates as cfg
    from services.db import get_pool, init_db

    await init_db(cfg.DATABASE_DSN)
    pool = await get_pool()
    accrued = 0
    skipped_profit = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT o.order_id, o.user_id, o.direction, o.status, o.crypto,
                   o.fiat_amount, o.crypto_amount, o.rate, o.cashback_applied_rub,
                   o.card_fee_pct, o.economics_snapshot
            FROM orders o
            WHERE o.direction = 'buy'
              AND o.status IN ('PAID', 'COMPLETED')
              AND NOT EXISTS (
                  SELECT 1 FROM user_cashback_ledger l
                  WHERE l.order_id = o.order_id AND l.type = 'accrual'
              )
            ORDER BY o.updated_at ASC
            """
        )
        for r in rows:
            o = dict(r)
            profit = order_economics(o)["service_profit_rub"]
            if profit <= 0:
                skipped_profit += 1
                print(f"skip {o['order_id']}: profit={profit:.2f}")
                continue
            if args.dry_run:
                print(f"would accrue {o['order_id']} user={o['user_id']} profit={profit:.2f}")
                accrued += 1
                continue
            ok = await accrue_user_cashback(o["order_id"], conn=conn)
            if ok:
                print(f"accrued {o['order_id']} user={o['user_id']} profit={profit:.2f}")
                accrued += 1
            else:
                print(f"no-op {o['order_id']} (already accrued or zero accrual)")

    mode = "dry-run" if args.dry_run else "applied"
    print(
        f"Done ({mode}). Accrued/would accrue: {accrued}, "
        f"skipped (profit<=0): {skipped_profit}, scanned: {len(rows)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
