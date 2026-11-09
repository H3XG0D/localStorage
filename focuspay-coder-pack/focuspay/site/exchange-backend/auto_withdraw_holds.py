"""Резерв баланса при автовыводе (ledger hold)."""
from __future__ import annotations

HOLD_PREFIX = "wd_hold:"
RELEASE_PREFIX = "wd_rel:"


def _hold_key(withdrawal_id: int, suffix: str) -> str:
    return f"{HOLD_PREFIX}{withdrawal_id}:{suffix}"


async def hold_unified_withdrawal(conn, user_id: int, withdrawal_id: int, amount_rub: float) -> float:
    """Списывает доступный баланс в hold-строки леджера. Возвращает зарезервированную сумму."""
    from user_cashback_db import get_cashback_balance_conn
    from user_unified_balance import get_partner_campaign_conn

    amount = round(float(amount_rub), 2)
    if amount <= 0:
        return 0.0

    cashback_balance = await get_cashback_balance_conn(conn, user_id)
    cashback_hold = min(max(0.0, float(cashback_balance)), amount)
    remainder = round(amount - cashback_hold, 2)

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
    partner_held = 0.0

    if cashback_hold > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'hold', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            user_id,
            -cashback_hold,
            _hold_key(withdrawal_id, "cb"),
            f"Резерв вывода #{withdrawal_id}",
        )
    if referral_hold > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (
                referrer_user_id, type, amount_rub, order_id, note, withdrawal_id
            )
            VALUES ($1, 'hold', $2, $3, $4, $5)
            ON CONFLICT (order_id) DO NOTHING
            """,
            user_id,
            -referral_hold,
            _hold_key(withdrawal_id, "ref"),
            f"Резерв вывода #{withdrawal_id}",
            withdrawal_id,
        )
    if partner_hold > 0:
        campaign = await get_partner_campaign_conn(conn, user_id)
        if campaign:
            campaign_id = int(campaign["campaign_id"])
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                campaign_id,
            )
            # withdrawal_id FK → partner_withdrawals, не user_referral_withdrawals.
            # Связь с unified-выводом держим в order_id (wd_hold:{id}:partner).
            await conn.execute(
                """
                INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note)
                VALUES ($1, 'hold', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                campaign_id,
                -partner_hold,
                _hold_key(withdrawal_id, "partner"),
                f"Резерв вывода #{withdrawal_id}",
            )
            partner_held = partner_hold

    held = cashback_hold + referral_hold + partner_held
    return round(held, 2)


async def release_withdrawal_holds(conn, withdrawal_id: int) -> None:
    """Снимает резерв: hold-строки нейтрализуются, а не удаляются (как в casino_finance)."""
    prefix = f"{HOLD_PREFIX}{withdrawal_id}:"
    note = f"Снятие резерва вывода #{withdrawal_id}"
    released = f"{RELEASE_PREFIX}{withdrawal_id}:"
    await conn.execute(
        """
        UPDATE user_cashback_ledger
        SET type = 'adjustment',
            amount_rub = 0,
            order_id = $2 || split_part(order_id, ':', 3),
            note = $3
        WHERE order_id LIKE $1 || '%' AND type = 'hold'
        """,
        prefix,
        released,
        note,
    )
    await conn.execute(
        """
        UPDATE user_referral_ledger
        SET type = 'adjustment',
            amount_rub = 0,
            order_id = $2 || split_part(order_id, ':', 3),
            note = $3
        WHERE order_id LIKE $1 || '%' AND type = 'hold'
        """,
        prefix,
        released,
        note,
    )
    await conn.execute(
        """
        UPDATE partner_ledger
        SET type = 'adjustment',
            amount_rub = 0,
            order_id = $2 || split_part(order_id, ':', 3),
            note = $3
        WHERE order_id LIKE $1 || '%' AND type = 'hold'
        """,
        prefix,
        released,
        note,
    )
