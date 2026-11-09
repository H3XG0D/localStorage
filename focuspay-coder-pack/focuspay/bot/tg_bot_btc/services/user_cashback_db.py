"""Кешбэк покупателя: баланс, холд, списание после оплаты, остаток."""

from services import config_rates
from services.db import get_pool

HOLD_PREFIX = "hold-"
SPEND_PREFIX = "spend-"
REFUND_PREFIX = "refund-"
PARTNER_HOLD_SUFFIX = ":partner"
PARTNER_SPEND_SUFFIX = ":partner"
PARTNER_REFUND_SUFFIX = ":partner"
LIVE_ORDER_HOLD_STATUSES = frozenset(
    {
        "CREATED",
        "AWAITING_CHECK",
        "PENDING",
        "OPERATOR_PENDING",
        "COMPLETED",
        "PAID",
        "DISPUTE",
    }
)


def order_id_from_hold_ledger_key(key: str | None) -> str | None:
    """hold-O123 / hold-O123:ref / hold-O123:partner → O123."""
    raw = str(key or "").strip()
    if not raw.startswith(HOLD_PREFIX):
        return None
    rest = raw[len(HOLD_PREFIX) :]
    if rest.endswith(PARTNER_HOLD_SUFFIX):
        rest = rest[: -len(PARTNER_HOLD_SUFFIX)]
    elif rest.endswith(":ref"):
        rest = rest[: -len(":ref")]
    rest = rest.strip()
    return rest or None


async def get_cashback_balance_conn(conn, user_id: int) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_cashback_ledger WHERE user_id = $1
        """,
        user_id,
    )
    return max(0.0, float(val or 0))


async def get_cashback_balance(user_id: int) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await get_cashback_balance_conn(conn, user_id)


async def _cashback_spendable(conn, user_id: int) -> float:
    """Общий баланс, доступный к списанию скидкой (учитывает pending withdrawal)."""
    from services.user_unified_balance import unified_available

    available = await unified_available(conn, user_id)
    return max(0.0, available)


async def hold_cashback_for_order(
    conn,
    user_id: int,
    order_id: str,
    amount_rub: float,
) -> float:
    """Резервирует общий баланс (hold) до оплаты. Возвращает фактически зарезервированное."""
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        return 0.0
    # Идемпотентность: если резерв по заявке уже создан — повторно НЕ держим
    # (иначе caller задвоит cb_applied). Возвращаем 0 — ничего нового не зарезервировано.
    already_held = await conn.fetchval(
        """
        SELECT 1 FROM user_cashback_ledger WHERE order_id = $1
        UNION ALL
        SELECT 1 FROM user_referral_ledger WHERE order_id = $2
        UNION ALL
        SELECT 1 FROM partner_ledger WHERE order_id = $3
        LIMIT 1
        """,
        f"{HOLD_PREFIX}{order_id}",
        f"{HOLD_PREFIX}{order_id}:ref",
        f"{HOLD_PREFIX}{order_id}{PARTNER_HOLD_SUFFIX}",
    )
    if already_held:
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
        from services.user_unified_balance import get_partner_campaign_conn

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


async def confirm_cashback_for_order(order_id: str, *, conn=None) -> None:
    """После COMPLETED/PAID: hold -> spend для общего баланса."""
    hold_id = f"{HOLD_PREFIX}{order_id}"
    spend_id = f"{SPEND_PREFIX}{order_id}"
    ref_hold_id = f"{HOLD_PREFIX}{order_id}:ref"
    ref_spend_id = f"{SPEND_PREFIX}{order_id}:ref"
    partner_hold_id = f"{HOLD_PREFIX}{order_id}{PARTNER_HOLD_SUFFIX}"
    partner_spend_id = f"{SPEND_PREFIX}{order_id}{PARTNER_SPEND_SUFFIX}"

    async def _run(c):
        row = await c.fetchrow(
            "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1 AND type = 'hold'",
            hold_id,
        )
        if row:
            spent = abs(float(row["amount_rub"]))
            await c.execute("DELETE FROM user_cashback_ledger WHERE order_id = $1", hold_id)
            await c.execute(
                """
                INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
                VALUES ($1, 'spend', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                row["user_id"],
                -spent,
                spend_id,
                f"Списание кешбэка по заявке {order_id}",
            )
        ref_row = await c.fetchrow(
            """
            SELECT referrer_user_id, amount_rub
            FROM user_referral_ledger
            WHERE order_id = $1 AND type = 'hold'
            """,
            ref_hold_id,
        )
        if ref_row:
            ref_spent = abs(float(ref_row["amount_rub"]))
            await c.execute(
                "DELETE FROM user_referral_ledger WHERE order_id = $1 AND type = 'hold'",
                ref_hold_id,
            )
            await c.execute(
                """
                INSERT INTO user_referral_ledger (
                    referrer_user_id, type, amount_rub, order_id, note
                )
                VALUES ($1, 'spend', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                ref_row["referrer_user_id"],
                -ref_spent,
                ref_spend_id,
                f"Списание реферального баланса по заявке {order_id}",
            )
        partner_row = await c.fetchrow(
            """
            SELECT campaign_id, amount_rub
            FROM partner_ledger
            WHERE order_id = $1 AND type = 'hold'
            """,
            partner_hold_id,
        )
        if partner_row:
            partner_spent = abs(float(partner_row["amount_rub"]))
            await c.execute(
                "DELETE FROM partner_ledger WHERE order_id = $1 AND type = 'hold'",
                partner_hold_id,
            )
            await c.execute(
                """
                INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note)
                VALUES ($1, 'spend', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                partner_row["campaign_id"],
                -partner_spent,
                partner_spend_id,
                f"Списание партнёрского баланса по заявке {order_id}",
            )

    if conn is not None:
        await _run(conn)
        return
    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            await _run(acquired)


async def release_cashback_for_order(order_id: str, *, conn=None) -> None:
    """Отмена/истечение: снять hold или вернуть spend."""
    hold_id = f"{HOLD_PREFIX}{order_id}"
    spend_id = f"{SPEND_PREFIX}{order_id}"
    refund_id = f"{REFUND_PREFIX}{order_id}"
    ref_hold_id = f"{HOLD_PREFIX}{order_id}:ref"
    ref_spend_id = f"{SPEND_PREFIX}{order_id}:ref"
    ref_refund_id = f"{REFUND_PREFIX}{order_id}:ref"
    partner_hold_id = f"{HOLD_PREFIX}{order_id}{PARTNER_HOLD_SUFFIX}"
    partner_spend_id = f"{SPEND_PREFIX}{order_id}{PARTNER_SPEND_SUFFIX}"
    partner_refund_id = f"{REFUND_PREFIX}{order_id}{PARTNER_REFUND_SUFFIX}"

    async def _run(c):
        hold_row = await c.fetchrow(
            "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1 AND type = 'hold'",
            hold_id,
        )
        if hold_row:
            await c.execute("DELETE FROM user_cashback_ledger WHERE order_id = $1", hold_id)
        ref_hold_row = await c.fetchrow(
            """
            SELECT referrer_user_id, amount_rub
            FROM user_referral_ledger
            WHERE order_id = $1 AND type = 'hold'
            """,
            ref_hold_id,
        )
        if ref_hold_row:
            await c.execute(
                "DELETE FROM user_referral_ledger WHERE order_id = $1",
                ref_hold_id,
            )
        spend_row = await c.fetchrow(
            "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1 AND type = 'spend'",
            spend_id,
        )
        if spend_row:
            refund = abs(float(spend_row["amount_rub"]))
            await c.execute(
                """
                INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
                VALUES ($1, 'adjustment', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                spend_row["user_id"],
                refund,
                refund_id,
                f"Возврат кешбэка за отмену {order_id}",
            )
        ref_spend_row = await c.fetchrow(
            """
            SELECT referrer_user_id, amount_rub
            FROM user_referral_ledger
            WHERE order_id = $1 AND type = 'spend'
            """,
            ref_spend_id,
        )
        if ref_spend_row:
            ref_refund = abs(float(ref_spend_row["amount_rub"]))
            await c.execute(
                """
                INSERT INTO user_referral_ledger (
                    referrer_user_id, type, amount_rub, order_id, note
                )
                VALUES ($1, 'adjustment', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                ref_spend_row["referrer_user_id"],
                ref_refund,
                ref_refund_id,
                f"Возврат реферального баланса за отмену {order_id}",
            )
        partner_hold_row = await c.fetchrow(
            """
            SELECT campaign_id, amount_rub
            FROM partner_ledger
            WHERE order_id = $1 AND type = 'hold'
            """,
            partner_hold_id,
        )
        if partner_hold_row:
            await c.execute(
                "DELETE FROM partner_ledger WHERE order_id = $1",
                partner_hold_id,
            )
        partner_spend_row = await c.fetchrow(
            """
            SELECT campaign_id, amount_rub
            FROM partner_ledger
            WHERE order_id = $1 AND type = 'spend'
            """,
            partner_spend_id,
        )
        if partner_spend_row:
            partner_refund = abs(float(partner_spend_row["amount_rub"]))
            await c.execute(
                """
                INSERT INTO partner_ledger (campaign_id, type, amount_rub, order_id, note)
                VALUES ($1, 'adjustment', $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                """,
                partner_spend_row["campaign_id"],
                partner_refund,
                partner_refund_id,
                f"Возврат партнёрского баланса за отмену {order_id}",
            )

    if conn is not None:
        await _run(conn)
        return
    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            await _run(acquired)


async def release_orphan_balance_holds(*, conn=None, limit: int = 50) -> list[str]:
    """Снять hold-* без живой заявки (таймаут payin до INSERT)."""

    async def _run(c) -> list[str]:
        rows = await c.fetch(
            """
            SELECT order_id AS ledger_key FROM user_cashback_ledger
             WHERE type = 'hold' AND order_id LIKE 'hold-%'
            UNION
            SELECT order_id AS ledger_key FROM user_referral_ledger
             WHERE type = 'hold' AND order_id LIKE 'hold-%'
            UNION
            SELECT order_id AS ledger_key FROM partner_ledger
             WHERE type = 'hold' AND order_id LIKE 'hold-%'
            """
        )
        seen: set[str] = set()
        released: list[str] = []
        for row in rows:
            oid = order_id_from_hold_ledger_key(row["ledger_key"])
            # Casino shares these ledgers, but its holds belong to games, not
            # exchange orders. Only casino settlement/recovery may release them.
            # This includes manual_review: missing an exchange order is expected.
            if not oid or oid.startswith("casino-") or oid in seen:
                continue
            seen.add(oid)
            status = await c.fetchval(
                "SELECT status FROM orders WHERE order_id = $1",
                oid,
            )
            if status in LIVE_ORDER_HOLD_STATUSES:
                continue
            await release_cashback_for_order(oid, conn=c)
            released.append(oid)
            if len(released) >= limit:
                break
        return released

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            return await _run(acquired)


async def credit_remainder(user_id: int, amount_rub: float, order_id: str | None, note: str) -> None:
    if amount_rub <= 0:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'remainder_credit', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            user_id,
            round(float(amount_rub), 2),
            order_id,
            note,
        )


OVERPAY_CREDIT_HOLD_KEY = "overpay_credit_hold"
OVERPAY_HOLD_RECEIPT_AMOUNT = "receipt_amount_missing"


def overpay_credit_receipt_ok(snapshot) -> bool:
    """Round-up BUY: кредит на баланс только если чек не противоречит сумме заявки.

    `receipt_pdf_meta.amount_present is False` — PDF читаем, а суммы заявки
    (3990) в нём нет → скорее всего клиент заплатил котировку (3600) и хочет
    получить и крипту, и 390 ₽ на баланс. None/отсутствие меты (видео, фото,
    нечитаемый PDF) не блокирует — там решает оператор по карточке.
    """
    from services.payment_snapshot import parse_payment_snapshot

    snap = parse_payment_snapshot(snapshot)
    meta = snap.get("receipt_pdf_meta")
    if not isinstance(meta, dict):
        return True
    return meta.get("amount_present") is not False


async def credit_manual_buy_overpay_for_order(order_id: str, *, conn=None) -> None:
    """Зачислить дополнительный баланс за переплату по ручной BUY после PAID."""

    async def _run(c):
        row = await c.fetchrow(
            """
            SELECT user_id, overpay_credit_rub, payin_requisite_id, payment_snapshot
            FROM orders
            WHERE order_id = $1
              AND direction = 'buy'
              AND (
                order_source = 'manual_operator'
                OR payin_requisite_id IS NOT NULL
              )
            """,
            order_id,
        )
        if not row:
            return
        amount = round(float(row["overpay_credit_rub"] or 0), 2)
        if amount <= 0:
            return
        if row.get("payin_requisite_id") is not None and not overpay_credit_receipt_ok(
            row.get("payment_snapshot")
        ):
            import json
            import logging

            logging.getLogger(__name__).warning(
                "overpay credit held: receipt amount mismatch order=%s credit=%s",
                order_id,
                amount,
            )
            await c.execute(
                """
                UPDATE orders
                SET payment_snapshot = COALESCE(payment_snapshot, '{}'::jsonb) || $2::jsonb
                WHERE order_id = $1
                """,
                order_id,
                json.dumps({OVERPAY_CREDIT_HOLD_KEY: OVERPAY_HOLD_RECEIPT_AMOUNT}),
            )
            return
        await c.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'overpay_credit', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            int(row["user_id"]),
            amount,
            f"{order_id}:overpay",
            f"Дополнительный баланс за переплату по заявке {order_id}",
        )

    if conn is not None:
        await _run(conn)
        return
    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            await _run(acquired)


async def apply_pending_remainder_for_order(order_id: str, *, conn=None) -> None:
    """Зачислить pending_remainder_rub после оплаты."""

    async def _run(c):
        row = await c.fetchrow(
            "SELECT user_id, pending_remainder_rub FROM orders WHERE order_id = $1",
            order_id,
        )
        if not row:
            return
        amount = float(row["pending_remainder_rub"] or 0)
        if amount <= 0:
            return
        remainder_oid = f"{order_id}:remainder"
        await c.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'remainder_credit', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            int(row["user_id"]),
            round(amount, 2),
            remainder_oid,
            f"Остаток по заявке {order_id}",
        )
        await c.execute(
            "UPDATE orders SET pending_remainder_rub = 0 WHERE order_id = $1",
            order_id,
        )

    if conn is not None:
        await _run(conn)
        return
    pool = await get_pool()
    async with pool.acquire() as acquired:
        await _run(acquired)


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
    # Как ваучер «скидка на обмен»: только меньше ₽ к оплате, крипта без изменений.
    _ = (rate, crypto)
    return fiat_pay, float(crypto_amount), applied


async def apply_cashback_to_buy_amounts(
    user_id: int,
    fiat_amount: float,
    crypto_amount: float,
    rate: float,
    crypto: str,
    *,
    use_cashback: bool,
) -> tuple[float, float, float]:
    """Возвращает (fiat_to_pay, crypto_out, cashback_applied)."""
    if not use_cashback:
        return fiat_amount, crypto_amount, 0.0
    pool = await get_pool()
    async with pool.acquire() as conn:
        balance = await _cashback_spendable(conn, user_id)
    if balance <= 0:
        return fiat_amount, crypto_amount, 0.0
    max_apply = max(0.0, float(fiat_amount) - 1.0)
    applied = min(balance, max_apply)
    if applied <= 0:
        return fiat_amount, crypto_amount, 0.0
    fiat_pay = float(fiat_amount) - applied
    # Как ваучер «скидка на обмен»: только меньше ₽ к оплате, крипта без изменений.
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
    from services.cashback_tier import count_completed_exchanges, tier_info

    pool = await get_pool()
    async with pool.acquire() as conn:
        balance = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger WHERE user_id = $1",
            user_id,
        )
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
        "balance_rub": max(0.0, float(balance or 0)),
        "total_accrued_rub": float(total_accrued or 0),
        "use_on_next": bool(use_next),
        **tiers,
    }
