#!/usr/bin/env python3
"""Lock the current economics of legacy closed orders after the snapshot migration."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
import sys

import asyncpg

from economics_snapshot import LEGACY_LOCKED_VERSION, build_economics_snapshot


async def backfill(*, dsn: str, apply: bool, batch_size: int) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        if not apply:
            count = await conn.fetchval(
                """
                SELECT COUNT(*)::int
                FROM orders
                WHERE status IN ('PAID', 'COMPLETED')
                  AND economics_snapshot IS NULL
                """
            )
            return int(count or 0)

        updated = 0
        while True:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT order_id, direction, crypto, fiat_amount, crypto_amount, rate,
                           cashback_applied_rub, card_fee_pct
                    FROM orders
                    WHERE status IN ('PAID', 'COMPLETED')
                      AND economics_snapshot IS NULL
                    ORDER BY id
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                    """,
                    batch_size,
                )
                if not rows:
                    break

                locked_at = datetime.now(tz=timezone.utc).isoformat()
                for row in rows:
                    order = dict(row)
                    snapshot = build_economics_snapshot(
                        str(order["direction"]),
                        str(order["crypto"]),
                        float(order["fiat_amount"] or 0),
                        float(order["crypto_amount"] or 0),
                        float(order["rate"] or 0),
                        cashback_applied_rub=float(order.get("cashback_applied_rub") or 0),
                        card_fee=(
                            float(order["card_fee_pct"])
                            if order["card_fee_pct"] is not None
                            else None
                        ),
                        formula_version=LEGACY_LOCKED_VERSION,
                    )
                    snapshot["locked_at"] = locked_at
                    if apply:
                        result = await conn.execute(
                            """
                            UPDATE orders
                            SET economics_snapshot = $2::jsonb
                            WHERE order_id = $1
                              AND economics_snapshot IS NULL
                            """,
                            str(order["order_id"]),
                            json.dumps(snapshot),
                        )
                    if result.endswith(" 1"):
                        updated += 1

        return updated
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lock current economics for PAID/COMPLETED legacy orders without snapshots"
    )
    parser.add_argument("--apply", action="store_true", help="write snapshots (default is dry-run)")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_DSN", ""))
    args = parser.parse_args()
    if not args.dsn:
        print("DATABASE_DSN required", file=sys.stderr)
        return 1
    if args.batch_size < 1 or args.batch_size > 1000:
        print("--batch-size must be between 1 and 1000", file=sys.stderr)
        return 1

    count = asyncio.run(
        backfill(dsn=args.dsn, apply=args.apply, batch_size=args.batch_size)
    )
    mode = "updated" if args.apply else "would lock"
    print(f"{mode}: {count} orders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
