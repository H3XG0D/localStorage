#!/usr/bin/env python3
"""Create or refresh FocusLucky campaign: 30 days until draw."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

MSK = timezone(timedelta(hours=3))


async def main() -> None:
    from services.config_rates import DATABASE_DSN
    from services.db import get_pool, init_db
    from services.raffle_constants import CAMPAIGN_DURATION_DAYS, DEFAULT_PRIZE_PLACES
    from services.raffle_db import activate_campaign
    from services.raffle_schedule import campaign_schedule

    await init_db(DATABASE_DSN)
    now = datetime.now(MSK)
    slug = f"focuslucky-{now.year:04d}-{now.month:02d}"
    month_names = (
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    )
    month_label = f"{month_names[now.month - 1]} {now.year}"
    starts, ends, draw = campaign_schedule(now)

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM raffle_campaigns WHERE slug = $1",
            slug,
        )
        if existing:
            cid = int(existing)
            await conn.execute(
                """
                UPDATE raffle_campaigns
                SET starts_at = $2,
                    ends_at = $3,
                    draw_at = $4,
                    month_label = $5,
                    updated_at = now()
                WHERE id = $1 AND status IN ('draft', 'active', 'closed')
                """,
                cid,
                starts,
                ends,
                draw,
                month_label,
            )
            print(
                f"Updated campaign id={cid} slug={slug}\n"
                f"  draw_at={draw.isoformat()} ({CAMPAIGN_DURATION_DAYS} days)"
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO raffle_campaigns (
                    slug, title, month_label, starts_at, ends_at, draw_at,
                    status, prize_places, prize_pool_rub
                )
                VALUES ($1, 'FocusLucky', $2, $3, $4, $5, 'draft', $6::jsonb, 14500)
                RETURNING id
                """,
                slug,
                month_label,
                starts,
                ends,
                draw,
                json.dumps(DEFAULT_PRIZE_PLACES),
            )
            cid = int(row["id"])
            print(f"Created campaign id={cid} slug={slug}")

    ok = await activate_campaign(cid)
    print(f"Activated: {ok}")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
