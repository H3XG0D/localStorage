"""Merge password-only client_user_id into telegram_user_id."""
from db import get_pool


async def merge_client_user_to_telegram(client_user_id: int, telegram_user_id: int) -> dict:
    """Перенос данных с synthetic client_user_id на Telegram ID."""
    if client_user_id == telegram_user_id:
        return {"orders": 0}

    pool = await get_pool()
    orders_count = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            orders_result = await conn.execute(
                "UPDATE orders SET user_id = $2, updated_at = now() WHERE user_id = $1",
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                UPDATE user_cashback_ledger SET user_id = $2
                WHERE user_id = $1
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                UPDATE user_referral_ledger SET referrer_user_id = $2
                WHERE referrer_user_id = $1
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                UPDATE user_referral_withdrawals SET referrer_user_id = $2
                WHERE referrer_user_id = $1
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                UPDATE user_referral_attributions SET user_id = $2
                WHERE user_id = $1
                  AND NOT EXISTS (
                      SELECT 1 FROM user_referral_attributions x
                      WHERE x.user_id = $2
                  )
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                DELETE FROM user_referral_attributions
                WHERE user_id = $1
                """,
                client_user_id,
            )
            await conn.execute(
                """
                UPDATE user_referral_attributions SET referrer_user_id = $2
                WHERE referrer_user_id = $1
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                UPDATE promo_attributions SET user_id = $2
                WHERE user_id = $1
                  AND NOT EXISTS (
                      SELECT 1 FROM promo_attributions x WHERE x.user_id = $2
                  )
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                "DELETE FROM promo_attributions WHERE user_id = $1",
                client_user_id,
            )
            await conn.execute(
                """
                UPDATE web_chat_threads SET telegram_user_id = $2
                WHERE telegram_user_id = $1
                """,
                client_user_id,
                telegram_user_id,
            )
            await conn.execute(
                """
                UPDATE web_users SET client_user_id = NULL
                WHERE client_user_id = $1
                """,
                client_user_id,
            )
            await conn.execute(
                """
                DELETE FROM bot_users WHERE user_id = $1
                """,
                client_user_id,
            )

    try:
        orders_count = int(str(orders_result).split()[-1])
    except (ValueError, IndexError):
        orders_count = 0
    return {"orders": orders_count}
