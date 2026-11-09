import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import asyncpg
from services.config_rates import DATABASE_DSN

ORDER_ID = sys.argv[1] if len(sys.argv) > 1 else "64261662"


async def main():
    conn = await asyncpg.connect(DATABASE_DSN)
    try:
        order = await conn.fetchrow(
            "SELECT order_id, user_id, promo_code, promo_bonus_percent, crypto_amount, fiat_amount "
            "FROM orders WHERE order_id = $1",
            ORDER_ID,
        )
        print("order:", dict(order) if order else None)
        if order:
            uid = order["user_id"]
            attr = await conn.fetchrow(
                "SELECT * FROM promo_attributions WHERE user_id = $1", uid
            )
            usage = await conn.fetchrow(
                "SELECT * FROM promo_bonus_usages WHERE user_id = $1", uid
            )
            print("attribution:", dict(attr) if attr else None)
            print("usage:", dict(usage) if usage else None)
        camps = await conn.fetch("SELECT code, bonus_percent, is_active FROM promo_campaigns")
        print("campaigns:", [dict(c) for c in camps])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
