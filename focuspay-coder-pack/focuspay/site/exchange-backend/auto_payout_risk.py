"""Риск-гейт автовыплат реферального баланса."""
from __future__ import annotations

import logging
from typing import Literal

from auto_settings import auto_payout_enabled, auto_withdraw_enabled, auto_withdraw_max_rub
from db import get_pool
from payin_requisite_rail import buy_paid_count
from wallet_validation import clean_crypto_address, validate_buy_wallet

logger = logging.getLogger("auto_payout_risk")

RiskOutcome = Literal["auto", "manual", "reject"]


async def _address_used_by_other(conn, address: str, user_id: int) -> bool:
    norm = clean_crypto_address(address).lower()
    if len(norm) < 10:
        return False
    other = await conn.fetchval(
        """
        SELECT 1 FROM user_referral_withdrawals
        WHERE lower(trim(requisites)) = $1
          AND referrer_user_id <> $2
          AND status IN ('pending', 'reserved', 'sending', 'paid')
        LIMIT 1
        """,
        norm,
        int(user_id),
    )
    return other is not None


async def _first_payout_to_address(conn, user_id: int, address: str) -> bool:
    norm = clean_crypto_address(address).lower()
    prev = await conn.fetchval(
        """
        SELECT 1 FROM user_referral_withdrawals
        WHERE referrer_user_id = $1
          AND lower(trim(requisites)) = $2
          AND status = 'paid'
        UNION ALL
        SELECT 1 FROM orders
        WHERE user_id = $1
          AND lower(trim(requisites)) = $2
          AND status IN ('PAID', 'COMPLETED')
          AND upper(COALESCE(direction, '')) = 'BUY'
        LIMIT 1
        """,
        int(user_id),
        norm,
    )
    return prev is None


async def _paid_withdraw_count(conn, user_id: int) -> int:
    """Успешные выводы баланса — для партнёров без своих BUY."""
    value = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM user_referral_withdrawals
        WHERE referrer_user_id = $1
          AND status = 'paid'
          AND COALESCE(source, 'balance') = 'balance'
        """,
        int(user_id),
    )
    return int(value or 0)


async def _paid_referral_or_partner_count(conn, user_id: int) -> int:
    """Начисления рефералки/партнёрки с оплаченных заявок."""
    value = await conn.fetchval(
        """
        SELECT (
            (SELECT COUNT(*)::int FROM user_referral_ledger
             WHERE referrer_user_id = $1 AND type = 'accrual' AND amount_rub > 0)
            +
            (SELECT COUNT(*)::int FROM partner_ledger pl
             JOIN partner_accounts pa ON pa.promo_campaign_id = pl.campaign_id
             WHERE pa.telegram_user_id = $1 AND pl.type = 'accrual' AND pl.amount_rub > 0)
        )::int
        """,
        int(user_id),
    )
    return int(value or 0)


async def _referral_self_dealing(conn, user_id: int) -> bool:
    """Грубая проверка: IP реферера пересекается с IP оплаченных заказов рефералов."""
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM user_referral_attributions ua
        JOIN orders o ON o.user_id = ua.user_id
        JOIN orders self_o ON self_o.user_id = ua.referrer_user_id
        WHERE ua.referrer_user_id = $1
          AND o.client_ip IS NOT NULL
          AND self_o.client_ip IS NOT NULL
          AND o.client_ip = self_o.client_ip
          AND o.status IN ('PAID', 'COMPLETED')
        LIMIT 1
        """,
        int(user_id),
    )
    return row is not None


async def evaluate_withdraw_risk(
    *,
    user_id: int,
    amount_rub: float,
    method: str,
    requisites: str,
    crypto: str | None,
    network: str | None,
    source: str,
) -> tuple[RiskOutcome, str]:
    if not auto_withdraw_enabled():
        return "manual", "auto_disabled"
    if source != "balance":
        return "manual", "casino_source"
    if method != "crypto":
        return "manual", "card_manual"
    if amount_rub > auto_withdraw_max_rub() + 0.01:
        return "manual", "over_cap"

    coin = (crypto or "").strip().lower()
    if coin not in ("btc", "ltc"):
        return "manual", "unsupported_coin"

    try:
        validate_buy_wallet(coin, network, requisites)
    except ValueError as exc:
        return "reject", str(exc)

    pool = await get_pool()
    async with pool.acquire() as conn:
        from bot_status_bridge import is_user_banned

        banned, _, _ = await is_user_banned(user_id)
        if banned:
            return "reject", "banned"

        review = str(
            await conn.fetchval(
                "SELECT account_review_status FROM bot_users WHERE user_id = $1",
                int(user_id),
            )
            or ""
        ).lower()
        if review in ("required", "rejected"):
            return "manual", "account_review"

        paid = await buy_paid_count(conn, user_id)
        paid_withdraws = await _paid_withdraw_count(conn, user_id)
        paid_accruals = await _paid_referral_or_partner_count(conn, user_id)
        if review == "pending" and paid < 1 and paid_withdraws < 1:
            return "manual", "account_review"

        # Партнёры и рефереры часто не покупают сами — хватает истории выводов или начислений.
        if paid < 1 and paid_withdraws < 1 and paid_accruals < 1:
            return "manual", "no_paid_history"

        if await _referral_self_dealing(conn, user_id):
            return "manual", "referral_ip_overlap"

        if await _address_used_by_other(conn, requisites, user_id):
            return "manual", "address_shared"

        # Постоянники часто меняют кошельки: новый адрес не повод звать
        # оператора. Новичкам — только на адрес, куда уже выплачивали.
        # «Постоянник» = достаточно BUY, paid-выводов или партнёрских/реферальных начислений.
        from auto_settings import auto_no_shift_min_buy_paid

        regular_threshold = auto_no_shift_min_buy_paid()
        is_regular = (
            paid >= regular_threshold
            or paid_withdraws >= regular_threshold
            or paid_accruals >= regular_threshold
        )
        if not is_regular and await _first_payout_to_address(conn, user_id, requisites):
            return "manual", "new_address_not_regular"

        from casino_payout_rail import assert_crypto_withdraw_allowed

        try:
            await assert_crypto_withdraw_allowed(conn, user_id)
        except ValueError as exc:
            return "manual", str(exc)

        from casino_wagering import locked_by_wagering

        locked = float(await locked_by_wagering(conn, user_id))
        if locked > 0.01:
            return "manual", "wagering_lock"

        daily = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_withdrawals
            WHERE referrer_user_id = $1
              AND status IN ('paid', 'sending', 'reserved')
              AND created_at > now() - interval '24 hours'
            """,
            int(user_id),
        )
        if float(daily or 0) + amount_rub > auto_withdraw_max_rub() * 3:
            return "manual", "daily_velocity"

        # Резерв имеет смысл, только если выплата реально уйдёт сейчас.
        if not auto_payout_enabled():
            return "manual", "auto_payout_disabled"
        from auto_payout_guard import signer_circuit_closed

        if not await signer_circuit_closed(conn):
            return "manual", "signer_circuit_open"
        from auto_payout_worker import daily_cap_room

        if amount_rub > await daily_cap_room(conn) + 0.01:
            return "manual", "global_daily_cap"

    return "auto", "ok"
