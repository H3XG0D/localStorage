"""Кешбэк: баланс, hold, spend, remainder (parity с ботом)."""

from config import settings
from db import get_pool

HOLD_PREFIX = "hold-"
SPEND_PREFIX = "spend-"
REFUND_PREFIX = "refund-"
PARTNER_HOLD_SUFFIX = ":partner"


async def get_cashback_balance_conn(conn, user_id: int) -> float:
    val = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger WHERE user_id = $1",
        user_id,
    )
    return max(0.0, float(val or 0))


async def get_cashback_balance(user_id: int) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await get_cashback_balance_conn(conn, user_id)


async def _cashback_spendable(conn, user_id: int) -> float:
    """Общий баланс, доступный к списанию скидкой (учитывает pending withdrawal)."""
    from user_unified_balance import unified_available

    available = await unified_available(conn, user_id)
    return max(0.0, available)


async def hold_cashback_for_order(conn, user_id: int, order_id: str, amount_rub: float) -> float:
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        return 0.0
    spendable = await _cashback_spendable(conn, user_id)
    hold_amount = min(spendable, amount)
    if hold_amount <= 0:
        return 0.0
    cashback_balance = await get_cashback_balance_conn(conn, user_id)
    cashback_hold = min(cashback_balance, hold_amount)
    remainder = round(hold_amount - cashback_hold, 2)
    referral_balance = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_referral_ledger WHERE referrer_user_id = $1
        """,
        user_id,
    )
    ref_avail = max(0.0, float(referral_balance or 0))
    referral_hold = min(ref_avail, remainder)
    remainder = round(remainder - referral_hold, 2)
    partner_hold = remainder
    if cashback_hold > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'hold', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            user_id,
            -cashback_hold,
            f"{HOLD_PREFIX}{order_id}",
            f"Резерв кешбэка по заявке {order_id}",
        )
    if referral_hold > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (
                referrer_user_id, type, amount_rub, order_id, note
            )
            VALUES ($1, 'hold', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            user_id,
            -referral_hold,
            f"{HOLD_PREFIX}{order_id}:ref",
            f"Резерв реферального баланса по заявке {order_id}",
        )
    partner_hold = remainder
    if partner_hold > 0:
        from user_unified_balance import get_partner_campaign_conn

        campaign = await get_partner_campaign_conn(conn, user_id)
        if not campaign:
            return hold_amount - partner_hold
        campaign_id = int(campaign["campaign_id"])
        await conn.execute(
            "SELECT pg_advisory_xact_lock($1)",
            campaign_id,
        )
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note)
            VALUES ($1, 'hold', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            campaign_id,
            -partner_hold,
            f"{HOLD_PREFIX}{order_id}{PARTNER_HOLD_SUFFIX}",
            f"Резерв партнёрского баланса по заявке {order_id}",
        )
    return hold_amount


async def apply_cashback_with_conn(
    conn,
    user_id: int,
    fiat_amount: float,
    crypto_amount: float,
    rate: float,
    crypto: str,
    *,
    use_cashback: bool,
) -> tuple[float, float, float]:
    """Расчёт скидки по балансу внутри транзакции (без гонки)."""
    if not use_cashback:
        return fiat_amount, crypto_amount, 0.0
    balance = await _cashback_spendable(conn, user_id)
    if balance <= 0:
        return fiat_amount, crypto_amount, 0.0
    max_apply = max(0.0, float(fiat_amount) - 1.0)
    applied = min(balance, max_apply)
    if applied <= 0:
        return fiat_amount, crypto_amount, 0.0
    fiat_pay = float(fiat_amount) - applied
    _ = (rate, crypto)
    return fiat_pay, float(crypto_amount), applied


async def should_use_cashback(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        flag = await conn.fetchval(
            "SELECT use_cashback_on_next_order FROM bot_users WHERE user_id = $1",
            user_id,
        )
    return bool(flag)


async def set_use_cashback_on_next(user_id: int, value: bool) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_users (user_id, use_cashback_on_next_order)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET use_cashback_on_next_order = $2
            """,
            user_id,
            value,
        )


async def get_cashback_stats(user_id: int) -> dict:
    from cashback_tier import count_completed_exchanges, tier_info

    pool = await get_pool()
    async with pool.acquire() as conn:
        balance = await get_cashback_balance_conn(conn, user_id)
        total_accrued = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger
            WHERE user_id = $1 AND type = 'accrual'
            """,
            user_id,
        )
        use_next = await conn.fetchval(
            "SELECT use_cashback_on_next_order FROM bot_users WHERE user_id = $1",
            user_id,
        )
        completed = await count_completed_exchanges(conn, user_id)
    tiers = tier_info(completed)
    return {
        "balance_rub": round(balance, 2),
        "total_accrued_rub": round(float(total_accrued or 0), 2),
        "use_on_next": bool(use_next),
        **tiers,
    }
