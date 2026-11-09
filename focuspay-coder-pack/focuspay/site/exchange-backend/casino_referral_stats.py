"""Helper functions for casino referral statistics."""
from db import get_pool


async def get_casino_referral_stats(user_id: int) -> dict:
    """
    Получить статистику реферальных доходов от казино для пользователя.
    
    Returns:
        {
            "casino_total_rub": float,  # Всего заработано от казино
            "casino_l1_rub": float,     # Заработано как L1 реферер
            "casino_l2_rub": float,     # Заработано как L2 реферер
        }
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Общая сумма от казино
        total_row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float as total
            FROM user_referral_ledger
            WHERE referrer_user_id = $1
              AND (note ILIKE 'Casino referral L1%' OR note ILIKE 'Casino referral L2%')
            """,
            user_id,
        )
        
        # L1 комиссии
        l1_row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float as total
            FROM user_referral_ledger
            WHERE referrer_user_id = $1
              AND note ILIKE 'Casino referral L1%'
            """,
            user_id,
        )
        
        # L2 комиссии
        l2_row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float as total
            FROM user_referral_ledger
            WHERE referrer_user_id = $1
              AND note ILIKE 'Casino referral L2%'
            """,
            user_id,
        )
        
        return {
            "casino_total_rub": round(float(total_row["total"] or 0), 2),
            "casino_l1_rub": round(float(l1_row["total"] or 0), 2),
            "casino_l2_rub": round(float(l2_row["total"] or 0), 2),
        }
