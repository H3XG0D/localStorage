"""Единый баланс: кешбэк + рефералка + партнёрские начисления."""
from services import config_rates
from services.runtime_settings import min_withdraw_card_rub
from services.cashback_tier import count_completed_exchanges, tier_info
from services.db import get_pool
from services.user_referral_db import get_referral_stats, has_pending_withdrawal
from services.referral_share import resolve_share_links


async def _promo_balance_rub(conn, user_id: int, cb: float) -> float:
    ledger = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_cashback_ledger
        WHERE user_id = $1 AND amount_rub > 0 AND note ILIKE 'Промокод%'
        """,
        user_id,
    )
    redeemed = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM promo_gift_redemptions
        WHERE user_id = $1
        """,
        user_id,
    )
    raw = max(float(ledger or 0), float(redeemed or 0))
    if raw <= 0:
        return 0.0
    return min(raw, max(0.0, cb))


async def get_partner_campaign_conn(conn, user_id: int) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT pa.promo_campaign_id AS campaign_id, pc.code AS campaign_code
        FROM partner_accounts pa
        JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
        WHERE pa.telegram_user_id = $1
          AND pa.is_active = TRUE
          AND pc.is_active = TRUE
        LIMIT 1
        """,
        user_id,
    )
    return dict(row) if row else None


async def _pending_user_withdrawal_rub(conn, user_id: int) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_referral_withdrawals
        WHERE referrer_user_id = $1 AND status = 'pending'
        """,
        user_id,
    )
    return float(val or 0)


async def qr_reserved_rub(conn, user_id: int) -> float:
    """Резервы под незавершённые оплаты по QR: деньги уже обещаны получателю кода."""
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(charged_rub), 0)::float
        FROM qr_sbp_payments
        WHERE user_id = $1 AND local_status = 'RESERVED'
        """,
        user_id,
    )
    return float(val or 0)


async def _blocked_user_rub(conn, user_id: int) -> float:
    """Всё, что уже обещано наружу: pending-вывод + резервы оплат по QR."""
    pending = await _pending_user_withdrawal_rub(conn, user_id)
    return pending + await qr_reserved_rub(conn, user_id)


async def _ledger_parts(conn, user_id: int) -> tuple[float, float, float]:
    cashback = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger WHERE user_id = $1",
        user_id,
    )
    referral = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_referral_ledger WHERE referrer_user_id = $1
        """,
        user_id,
    )
    blocked = await _blocked_user_rub(conn, user_id)
    cb = max(0.0, float(cashback or 0))
    ref = float(referral or 0)
    available = max(0.0, cb + ref - blocked)
    return cb, ref, available


async def _partner_parts(conn, user_id: int) -> dict:
    campaign = await get_partner_campaign_conn(conn, user_id)
    if not campaign:
        return {
            "campaign_id": None,
            "campaign_code": None,
            "balance_rub": 0.0,
            "available_rub": 0.0,
            "pending_partner_rub": 0.0,
        }

    campaign_id = int(campaign["campaign_id"])
    balance = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM partner_ledger WHERE campaign_id = $1
        """,
        campaign_id,
    )
    pending_partner = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM partner_withdrawals
        WHERE campaign_id = $1 AND status = 'pending'
        """,
        campaign_id,
    )
    blocked_user = await _blocked_user_rub(conn, user_id)
    cb, ref, _ = await _ledger_parts(conn, user_id)
    client_gross = cb + ref
    from_partner_in_user_pending = max(0.0, blocked_user - client_gross)
    partner_avail = max(
        0.0,
        float(balance or 0) - float(pending_partner or 0) - from_partner_in_user_pending,
    )
    return {
        "campaign_id": campaign_id,
        "campaign_code": campaign["campaign_code"],
        "balance_rub": max(0.0, float(balance or 0)),
        "available_rub": round(partner_avail, 2),
        "pending_partner_rub": float(pending_partner or 0),
    }


async def unified_available(conn, user_id: int) -> float:
    _, _, client_avail = await _ledger_parts(conn, user_id)
    partner = await _partner_parts(conn, user_id)
    return round(client_avail + partner["available_rub"], 2)


async def deduct_unified_payout(
    conn,
    user_id: int,
    amount_rub: float,
    withdrawal_id: int,
) -> None:
    """Списать выплату: кешбэк → рефералка → партнёрский ledger."""
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        return

    cashback = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger WHERE user_id = $1",
        user_id,
    )
    cb_avail = max(0.0, float(cashback or 0))
    from_cb = min(cb_avail, amount)
    remainder = round(amount - from_cb, 2)

    referral = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_referral_ledger WHERE referrer_user_id = $1
        """,
        user_id,
    )
    ref_avail = max(0.0, float(referral or 0))
    from_ref = min(ref_avail, remainder)
    from_partner = round(remainder - from_ref, 2)

    if from_cb > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
            VALUES ($1, 'adjustment', $2, $3)
            """,
            user_id,
            -from_cb,
            f"Вывод баланса #{withdrawal_id}",
        )
    if from_ref > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (
                referrer_user_id, type, amount_rub, withdrawal_id, note
            )
            VALUES ($1, 'payout', $2, $3, $4)
            """,
            user_id,
            -from_ref,
            withdrawal_id,
            f"Вывод баланса #{withdrawal_id}",
        )
    if from_partner > 0:
        partner = await _partner_parts(conn, user_id)
        campaign_id = partner.get("campaign_id")
        if not campaign_id:
            raise ValueError(
                f"Недостаточно партнёрского баланса: {partner['balance_rub']:,.2f} ₽"
            )
        if from_partner > partner["balance_rub"] + 0.01:
            raise ValueError(
                f"Недостаточно партнёрского баланса: {partner['balance_rub']:,.2f} ₽"
            )
        await conn.execute(
            "SELECT pg_advisory_xact_lock($1)",
            int(campaign_id),
        )
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, note)
            VALUES ($1, 'payout', $2, $3)
            """,
            int(campaign_id),
            -from_partner,
            f"Вывод баланса #{withdrawal_id}",
        )


async def get_unified_balance_stats(user_id: int) -> dict:
    from services.user_cashback_db import should_use_cashback

    pool = await get_pool()
    async with pool.acquire() as conn:
        cb, ref, client_available = await _ledger_parts(conn, user_id)
        partner = await _partner_parts(conn, user_id)
        promo_rub = await _promo_balance_rub(conn, user_id, cb)
        exchange_cashback_rub = max(0.0, cb - promo_rub)
        completed = await count_completed_exchanges(conn, user_id)
        total_cb_accrued = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger
            WHERE user_id = $1 AND type = 'accrual'
            """,
            user_id,
        )
        cashback_saved = await conn.fetchval(
            """
            SELECT COALESCE(SUM(ABS(amount_rub)), 0)::float
            FROM user_cashback_ledger
            WHERE user_id = $1 AND type = 'spend'
            """,
            user_id,
        )
        referral_saved = await conn.fetchval(
            """
            SELECT COALESCE(SUM(ABS(amount_rub)), 0)::float
            FROM user_referral_ledger
            WHERE referrer_user_id = $1 AND type = 'spend'
            """,
            user_id,
        )
        client_balance = cb + ref
        total_balance = client_balance + partner["balance_rub"]
        total_available = round(client_available + partner["available_rub"], 2)
        from services.casino_payout_rail import payout_rail_progress, serialize_payout_rail_numbers

        payout_rail = serialize_payout_rail_numbers(await payout_rail_progress(conn, user_id))

    tiers = tier_info(completed)
    ref_stats = await get_referral_stats(user_id)
    share = await resolve_share_links(user_id)
    from services.crypto_network_fee import withdraw_terms_snapshot

    withdraw_terms = await withdraw_terms_snapshot()

    return {
        "balance_rub": round(total_balance, 2),
        "available_rub": total_available,
        "client_balance_rub": round(client_balance, 2),
        "client_available_rub": round(client_available, 2),
        "partner_balance_rub": round(partner["balance_rub"], 2),
        "partner_available_rub": round(partner["available_rub"], 2),
        "partner_campaign_code": partner.get("campaign_code"),
        "cashback_rub": round(cb, 2),
        "exchange_cashback_rub": round(exchange_cashback_rub, 2),
        "promo_rub": round(promo_rub, 2),
        "referral_rub": round(ref, 2),
        "total_accrued_rub": round(float(total_cb_accrued or 0) + ref_stats["total_accrual_rub"], 2),
        "saved_rub": round(float(cashback_saved or 0) + float(referral_saved or 0), 2),
        "use_on_next": await should_use_cashback(user_id),
        "has_pending_withdrawal": await has_pending_withdrawal(user_id),
        "min_withdraw_card_rub": min_withdraw_card_rub(),
        "min_withdraw_crypto_usd_btc": config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_BTC,
        "min_withdraw_crypto_usd_ltc": config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_LTC,
        "min_withdraw_crypto_usd_trx": config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_TRX,
        "min_withdraw_crypto_usd_usdt": config_rates.USER_REFERRAL_MIN_WITHDRAW_CRYPTO_USD_USDT,
        "withdraw_terms": withdraw_terms,
        "ref_token": share["ref_token"],
        "share_link_kind": share["kind"],
        "telegram_link": share["telegram_link"],
        "web_invite_link": share["web_link"],
        "referred_count": ref_stats["referred_count"],
        "paid_orders_count": ref_stats["paid_orders_count"],
        "referral_total_accrual_rub": ref_stats["total_accrual_rub"],
        "payout_rail": payout_rail,
        **tiers,
    }
