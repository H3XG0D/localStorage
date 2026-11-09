import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg
from services.config_rates import DATABASE_DSN
from services.promo_bonus import format_bonus_percent, promo_bonus_note


async def main():
    conn = await asyncpg.connect(DATABASE_DSN)
    try:
        rows = await conn.fetch(
            """
            SELECT order_id, promo_code, promo_bonus_percent, crypto_amount, fiat_amount, created_at
            FROM orders
            WHERE promo_code IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 5
            """
        )
        for r in rows:
            pct = r["promo_bonus_percent"]
            print(
                r["order_id"],
                r["promo_code"],
                "db=", pct,
                "display=", format_bonus_percent(pct) if pct is not None else None,
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
