"""Exchange ledger wallet for battle bets (hold / spend / win / refund)."""
from __future__ import annotations

from user_cashback_db import HOLD_PREFIX, hold_cashback_for_order
from user_unified_balance import unified_available
from db import get_pool


def _order_ref(round_id: int, user_id: int, hold_id: int) -> str:
    return f"battle-{round_id}-{user_id}-{hold_id}"


async def _confirm_hold_order(conn, order_id: str) -> None:
    """hold -> spend (loss)."""
    hold_id = f"{HOLD_PREFIX}{order_id}"
    spend_id = f"spend-{order_id}"
    ref_hold_id = f"{HOLD_PREFIX}{order_id}:ref"
    ref_spend_id = f"spend-{order_id}:ref"
    partner_hold_id = f"{HOLD_PREFIX}{order_id}:partner"
    partner_spend_id = f"spend-{order_id}:partner"

    row = await conn.fetchrow(
        "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1 AND type = 'hold'",
        hold_id,
    )
    if row:
        spent = abs(float(row["amount_rub"]))
        await conn.execute("DELETE FROM user_cashback_ledger WHERE order_id = $1", hold_id)
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'spend', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            row["user_id"],
            -spent,
            spend_id,
            f"Battle loss {order_id}",
        )
    ref_row = await conn.fetchrow(
        """
        SELECT referrer_user_id, amount_rub FROM user_referral_ledger
        WHERE order_id = $1 AND type = 'hold'
        """,
        ref_hold_id,
    )
    if ref_row:
        ref_spent = abs(float(ref_row["amount_rub"]))
        await conn.execute(
            "DELETE FROM user_referral_ledger WHERE order_id = $1 AND type = 'hold'",
            ref_hold_id,
        )
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'spend', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            ref_row["referrer_user_id"],
            -ref_spent,
            ref_spend_id,
            f"Battle loss {order_id}",
        )
    partner_row = await conn.fetchrow(
        """
        SELECT campaign_id, amount_rub FROM partner_ledger
        WHERE order_id = $1 AND type = 'hold'
        """,
        partner_hold_id,
    )
    if partner_row:
        partner_spent = abs(float(partner_row["amount_rub"]))
        await conn.execute(
            "DELETE FROM partner_ledger WHERE order_id = $1 AND type = 'hold'",
            partner_hold_id,
        )
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note)
            VALUES ($1, 'spend', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            partner_row["campaign_id"],
            -partner_spent,
            partner_spend_id,
            f"Battle loss {order_id}",
        )


async def _release_hold_order(conn, order_id: str) -> None:
    """Cancel hold (refund)."""
    hold_id = f"{HOLD_PREFIX}{order_id}"
    ref_hold_id = f"{HOLD_PREFIX}{order_id}:ref"
    partner_hold_id = f"{HOLD_PREFIX}{order_id}:partner"

    hold_row = await conn.fetchrow(
        "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1 AND type = 'hold'",
        hold_id,
    )
    if hold_row:
        refund = abs(float(hold_row["amount_rub"]))
        await conn.execute("DELETE FROM user_cashback_ledger WHERE order_id = $1", hold_id)
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            hold_row["user_id"],
            refund,
            f"refund-{order_id}",
            f"Battle refund {order_id}",
        )
    ref_hold_row = await conn.fetchrow(
        """
        SELECT referrer_user_id, amount_rub FROM user_referral_ledger
        WHERE order_id = $1 AND type = 'hold'
        """,
        ref_hold_id,
    )
    if ref_hold_row:
        ref_refund = abs(float(ref_hold_row["amount_rub"]))
        await conn.execute("DELETE FROM user_referral_ledger WHERE order_id = $1", ref_hold_id)
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            ref_hold_row["referrer_user_id"],
            ref_refund,
            f"refund-{order_id}:ref",
            f"Battle refund {order_id}",
        )
    partner_hold_row = await conn.fetchrow(
        """
        SELECT campaign_id, amount_rub FROM partner_ledger
        WHERE order_id = $1 AND type = 'hold'
        """,
        partner_hold_id,
    )
    if partner_hold_row:
        partner_refund = abs(float(partner_hold_row["amount_rub"]))
        await conn.execute("DELETE FROM partner_ledger WHERE order_id = $1", partner_hold_id)
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            partner_hold_row["campaign_id"],
            partner_refund,
            f"refund-{order_id}:partner",
            f"Battle refund {order_id}",
        )


async def _clear_hold_without_refund(conn, order_id: str) -> None:
    """Remove hold entries before crediting win."""
    for ledger_sql, oid in (
        ("DELETE FROM user_cashback_ledger WHERE order_id = $1", f"{HOLD_PREFIX}{order_id}"),
        ("DELETE FROM user_referral_ledger WHERE order_id = $1", f"{HOLD_PREFIX}{order_id}:ref"),
        ("DELETE FROM partner_ledger WHERE order_id = $1", f"{HOLD_PREFIX}{order_id}:partner"),
    ):
        await conn.execute(ledger_sql, oid)


class ExchangeLedgerWallet:
    async def available(self, user_id: str) -> float:
        uid = int(user_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await unified_available(conn, uid)

    async def hold_bet(self, user_id: str, round_id: int, amount: float, hold_id: int) -> None:
        uid = int(user_id)
        amount = round(float(amount), 2)
        order_ref = _order_ref(round_id, uid, hold_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                held = await hold_cashback_for_order(conn, uid, order_ref, amount)
                if held < amount - 0.01:
                    raise ValueError("insufficient balance")
                await conn.execute(
                    """
                    INSERT INTO battle_wallet_holds (round_id, user_id, order_ref, amount_rub, status)
                    VALUES ($1, $2, $3, $4, 'held')
                    ON CONFLICT (order_ref) DO NOTHING
                    """,
                    round_id,
                    uid,
                    order_ref,
                    amount,
                )

    async def release_win(self, user_id: str, round_id: int, amount: float) -> None:
        uid = int(user_id)
        amount = round(float(amount), 2)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT order_ref FROM battle_wallet_holds
                    WHERE round_id = $1 AND user_id = $2 AND status = 'held'
                    """,
                    round_id,
                    uid,
                )
                for row in rows:
                    await _clear_hold_without_refund(conn, row["order_ref"])
                    await conn.execute(
                        "UPDATE battle_wallet_holds SET status = 'won' WHERE order_ref = $1",
                        row["order_ref"],
                    )
                win_oid = f"battle-win-{round_id}-{uid}"
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
                    VALUES ($1, 'accrual', $2, $3, $4)
                    ON CONFLICT (order_id) DO NOTHING
                    """,
                    uid,
                    amount,
                    win_oid,
                    f"Battle round #{round_id} win",
                )

    async def confirm_loss(self, user_id: str, round_id: int) -> None:
        uid = int(user_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT order_ref FROM battle_wallet_holds
                    WHERE round_id = $1 AND user_id = $2 AND status = 'held'
                    """,
                    round_id,
                    uid,
                )
                for row in rows:
                    await _confirm_hold_order(conn, row["order_ref"])
                    await conn.execute(
                        "UPDATE battle_wallet_holds SET status = 'lost' WHERE order_ref = $1",
                        row["order_ref"],
                    )

    async def refund_round(self, user_id: str, round_id: int) -> None:
        uid = int(user_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT order_ref FROM battle_wallet_holds
                    WHERE round_id = $1 AND user_id = $2 AND status = 'held'
                    """,
                    round_id,
                    uid,
                )
                for row in rows:
                    await _release_hold_order(conn, row["order_ref"])
                    await conn.execute(
                        "UPDATE battle_wallet_holds SET status = 'refunded' WHERE order_ref = $1",
                        row["order_ref"],
                    )

    async def seed(self, user_id: str, amount: float) -> None:
        raise NotImplementedError("seed is lab-only")
