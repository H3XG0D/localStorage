"""Fiat casino deposits must be withdrawn to card before crypto is allowed."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

RAIL_FIAT = "fiat"
RAIL_CRYPTO = "crypto"
RAIL_LEGACY = "legacy"
FIAT_SUB_TOKENS = frozenset({"SBPRUB", "CARDRUB"})
CRYPTO_EPS = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rail_from_sub_token(sub_token: object) -> str:
    sub = str(sub_token or "").strip().upper()
    if sub in FIAT_SUB_TOKENS:
        return RAIL_FIAT
    return RAIL_CRYPTO


def remaining_from_totals(fiat_in: Decimal | int | float | str, fiat_out: Decimal | int | float | str) -> Decimal:
    leftover = money(fiat_in) - money(fiat_out)
    if leftover < 0:
        return Decimal("0.00")
    return money(leftover)


def crypto_allowed_for_remaining(remaining: Decimal | int | float | str) -> bool:
    return money(remaining) <= CRYPTO_EPS


def crypto_withdraw_blocked_message(remaining_rub: Decimal | int | float | str) -> str:
    return f"Сначала выведите {money(remaining_rub):,.2f} ₽ на карту"


def serialize_payout_rail_numbers(progress: Mapping[str, object]) -> dict[str, object]:
    return {
        "fiat_deposited_rub": float(money(progress["fiat_deposited_rub"])),
        "card_withdrawn_rub": float(money(progress["card_withdrawn_rub"])),
        "remaining_rub": float(money(progress["remaining_rub"])),
        "crypto_allowed": bool(progress["crypto_allowed"]),
    }


def _empty_progress() -> dict[str, Decimal | bool]:
    zero = Decimal("0.00")
    return {
        "fiat_deposited_rub": zero,
        "card_withdrawn_rub": zero,
        "remaining_rub": zero,
        "crypto_allowed": True,
    }


async def payout_rail_progress(conn, telegram_id: int) -> dict[str, Decimal | bool]:
    row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(amount_rub), 0) AS fiat_in,
               MIN(credited_at) AS first_at
        FROM casino_deposit_credits
        WHERE telegram_id = $1 AND rail = 'fiat'
        """,
        int(telegram_id),
    )
    fiat_in = money(row["fiat_in"] if row else 0)
    first_at = row["first_at"] if row else None
    if fiat_in <= 0 or first_at is None:
        return _empty_progress()

    fiat_out_raw = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)
        FROM user_referral_withdrawals
        WHERE referrer_user_id = $1
          AND method = 'card'
          AND status IN ('pending', 'paid')
          AND created_at >= $2
        """,
        int(telegram_id),
        first_at,
    )
    fiat_out = money(fiat_out_raw or 0)
    remaining = remaining_from_totals(fiat_in, fiat_out)
    return {
        "fiat_deposited_rub": fiat_in,
        "card_withdrawn_rub": fiat_out,
        "remaining_rub": remaining,
        "crypto_allowed": crypto_allowed_for_remaining(remaining),
    }


async def assert_crypto_withdraw_allowed(conn, telegram_id: int) -> None:
    progress = await payout_rail_progress(conn, telegram_id)
    if progress["crypto_allowed"]:
        return
    raise ValueError(crypto_withdraw_blocked_message(progress["remaining_rub"]))
