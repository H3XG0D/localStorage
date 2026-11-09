#!/usr/bin/env python3
"""Дублировать uref-атрибуции партнёров в promo_attributions (для начисления комиссии)."""
from __future__ import annotations

import argparse
import asyncio
import sys

BOT_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

_BACKFILL_SQL = """
INSERT INTO promo_attributions (user_id, promo_code, assigned_at)
SELECT a.user_id, pc.code, COALESCE(a.created_at, now())
FROM user_referral_attributions a
JOIN partner_accounts pa ON pa.telegram_user_id = a.referrer_user_id AND pa.is_active = TRUE
JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id AND pc.is_active = TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM promo_attributions p WHERE p.user_id = a.user_id
)
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, сколько строк будет добавлено",
    )
    args = parser.parse_args()

    from services import config_rates as cfg
    from services.db import get_pool, init_db

    await init_db(cfg.DATABASE_DSN)
    pool = await get_pool()

    async with pool.acquire() as conn:
        pending = await conn.fetch(
            """
            SELECT a.user_id, a.referrer_user_id, pc.code AS promo_code
            FROM user_referral_attributions a
            JOIN partner_accounts pa ON pa.telegram_user_id = a.referrer_user_id AND pa.is_active = TRUE
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id AND pc.is_active = TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM promo_attributions p WHERE p.user_id = a.user_id
            )
            ORDER BY a.created_at ASC
            """
        )

    if not pending:
        print("Нечего бэкофилить — все uref-атрибуции партнёров уже в promo_attributions")
        return 0

    for row in pending:
        print(
            f"{'would link' if args.dry_run else 'linked'} "
            f"user={row['user_id']} -> promo={row['promo_code']} "
            f"(referrer={row['referrer_user_id']})"
        )

    if args.dry_run:
        print(f"Done (dry-run). Would insert: {len(pending)}")
        return 0

    async with pool.acquire() as conn:
        result = await conn.execute(_BACKFILL_SQL)
    print(f"Done (applied). {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
