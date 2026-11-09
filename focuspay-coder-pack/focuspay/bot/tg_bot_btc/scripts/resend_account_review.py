"""One-shot: resend enriched account-review card for a user."""
import asyncio
import sys

from services import config_rates
from services.account_review import notify_ops_account_review, _avatar_info
from services.buyer_access_guards import is_suspicious_account
from services.db import (
    find_wallet_reuse,
    get_bot_user,
    get_buyer_ops_stats,
    get_pool,
    init_db,
)
from telegram import Bot

USER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 8500999983


async def main():
    await init_db(config_rates.DATABASE_DSN)
    row = await get_bot_user(USER_ID)
    stats = await get_buyer_ops_stats(USER_ID)
    print("status", (row or {}).get("account_review_status"),
          "reason", (row or {}).get("account_review_reason"),
          "first_seen", (row or {}).get("first_seen_at"))

    bot = Bot(token=config_rates.TELEGRAM_BOT_TOKEN)
    has_avatar, avatar_count = await _avatar_info(bot, USER_ID)

    wallet = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        w = await conn.fetchval(
            """
            SELECT COALESCE(NULLIF(btrim(wallet_address), ''), NULLIF(btrim(requisites), ''))
            FROM orders
            WHERE user_id = $1
              AND direction = 'buy'
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
            USER_ID,
        )
        deal = await conn.fetchrow(
            """
            SELECT crypto, fiat_amount, crypto_amount, network, direction
            FROM orders
            WHERE user_id = $1
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
            USER_ID,
        )
    if w:
        wallet = str(w).strip()
    else:
        wallet = "ltc1qkdaqth0j8xl3umpsglq3rytcdfpxe6gt7qnuea"

    reuse = []
    try:
        reuse = await find_wallet_reuse(wallet, USER_ID)
    except Exception as e:
        print("reuse", e)

    # Premium unknown on resend (no live Update) — leave None unless we force display
    reasons = is_suspicious_account(
        row,
        int(stats.get("paid_count") or 0),
        has_avatar=has_avatar,
        first_name=(row or {}).get("first_name"),
        wallet_reuse=bool(reuse),
        is_premium=False,
    )
    if not reasons and row and row.get("account_review_reason"):
        reasons = [x for x in str(row["account_review_reason"]).split(",") if x]
    if not reasons:
        reasons = ["no_username", "fresh_account", "no_premium"]

    fiat = crypto = crypto_amt = network = None
    if deal:
        fiat = deal.get("fiat_amount")
        crypto = deal.get("crypto")
        crypto_amt = deal.get("crypto_amount")
        network = deal.get("network")
        print("deal", dict(deal))

    await notify_ops_account_review(
        user_id=USER_ID,
        bot=bot,
        username=(row or {}).get("username"),
        first_name=(row or {}).get("first_name") or "Bc Game",
        reasons=reasons,
        wallet=wallet,
        wallet_reuse_rows=reuse,
        is_premium=False,
        has_avatar=has_avatar,
        avatar_count=avatar_count,
        fiat_amount=fiat,
        crypto=crypto or "LTC",
        crypto_amount=float(crypto_amt) if crypto_amt is not None else None,
        network=network,
        amount_currency="rub",
        bot_user=dict(row) if row else None,
        ops_stats=stats,
        resend=True,
    )
    print("OK sent", reasons)
    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
