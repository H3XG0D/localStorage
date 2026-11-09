#!/usr/bin/env python3
"""Починить BUY-заявки, где crypto_amount больше оплаченного payin (не PAID)."""
from __future__ import annotations

import asyncio
import os
import sys

BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_ROOT not in sys.path:
    sys.path.insert(0, BOT_ROOT)

from services.buy_payout_validate import expected_crypto_for_paid_rub, max_crypto_for_paid_rub


async def main() -> None:
    from services import config_rates as cfg
    from services.db import get_pool, init_db

    await init_db(cfg.DATABASE_DSN)
    pool = await get_pool()
    fixed = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_id, crypto, fiat_amount, crypto_amount, rate,
                   cashback_applied_rub, status
            FROM orders
            WHERE direction = 'buy'
              AND status NOT IN ('PAID', 'CANCELED', 'EXPIRED')
            """
        )
        for r in rows:
            o = dict(r)
            cap = max_crypto_for_paid_rub(o)
            crypto = float(o["crypto_amount"] or 0)
            if cap is None or crypto <= cap * 1.001:
                continue
            exp = expected_crypto_for_paid_rub(
                fiat_amount=float(o["fiat_amount"] or 0),
                rate=float(o["rate"] or 0),
                crypto=str(o["crypto"] or ""),
                cashback_applied_rub=float(o["cashback_applied_rub"] or 0),
            )
            if exp is None:
                continue
            await conn.execute(
                "UPDATE orders SET crypto_amount = $1, updated_at = now() WHERE order_id = $2",
                exp,
                o["order_id"],
            )
            print(f"fixed {o['order_id']}: {crypto:.8f} -> {exp:.8f} ({o['status']})")
            fixed += 1
    print(f"Done. Fixed {fixed} orders.")


if __name__ == "__main__":
    asyncio.run(main())
