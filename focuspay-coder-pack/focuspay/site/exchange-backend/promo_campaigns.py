"""Создание промокампаний (общая логика admin + operator)."""
from __future__ import annotations

import secrets
import string

from referral_links import generate_ref_token

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_campaign_code(prefix: str = "B") -> str:
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"{prefix}{suffix}"


async def pick_unique_campaign_code(conn, prefix: str = "B") -> str:
    for _ in range(12):
        code = generate_campaign_code(prefix)
        exists = await conn.fetchval("SELECT 1 FROM promo_campaigns WHERE code = $1", code)
        if not exists:
            return code
    raise RuntimeError("Could not generate unique promo code")


def effective_promo_status(
    *,
    is_active: bool,
    activations_used: int,
    max_activations: int,
    campaign_kind: str | None = None,
) -> str:
    """active | exhausted | disabled"""
    if not is_active:
        return "disabled"
    if (campaign_kind or "").lower() != "partner" and activations_used >= max_activations:
        return "exhausted"
    return "active"


async def create_fixed_rub_campaign(
    conn,
    *,
    client_fixed_bonus_rub: float,
    max_activations: int,
    name: str | None,
    created_by_web_user_id: int | None = None,
    issued_by_operator_id: int | None = None,
    code_prefix: str = "B",
):
    if client_fixed_bonus_rub <= 0:
        raise ValueError("client_fixed_bonus_rub must be positive")
    if max_activations < 1 or max_activations > 1000:
        raise ValueError("max_activations must be between 1 and 1000")

    code = await pick_unique_campaign_code(conn, code_prefix)
    title = name or f"Промо {int(client_fixed_bonus_rub)} ₽"
    ref_token = generate_ref_token()
    return await conn.fetchrow(
        """
        INSERT INTO promo_campaigns (
            code, name, bonus_percent, ad_spend_rub, partner_commission_percent,
            ref_token, campaign_kind, client_fixed_bonus_rub, max_activations,
            is_active, created_by, issued_by_operator_id, created_at, updated_at
        )
        VALUES ($1, $2, 0, 0, 0, $3, 'fixed_rub', $4, $5, TRUE, $6, $7, now(), now())
        RETURNING *
        """,
        code,
        title,
        ref_token,
        client_fixed_bonus_rub,
        max_activations,
        created_by_web_user_id,
        issued_by_operator_id,
    )


async def create_exchange_discount_campaign(
    conn,
    *,
    client_fixed_bonus_rub: float,
    max_activations: int,
    name: str | None,
    created_by_web_user_id: int | None = None,
    issued_by_operator_id: int | None = None,
    min_order_rub: float = 0,
    code_prefix: str = "D",
):
    if client_fixed_bonus_rub <= 0:
        raise ValueError("client_fixed_bonus_rub must be positive")
    if max_activations < 1 or max_activations > 1000:
        raise ValueError("max_activations must be between 1 and 1000")
    min_order = max(0.0, float(min_order_rub or 0))
    if min_order and min_order < client_fixed_bonus_rub:
        raise ValueError("min_order_rub must be >= discount amount")

    code = await pick_unique_campaign_code(conn, code_prefix)
    title = name or f"Скидка {int(client_fixed_bonus_rub)} ₽"
    ref_token = generate_ref_token()
    return await conn.fetchrow(
        """
        INSERT INTO promo_campaigns (
            code, name, bonus_percent, ad_spend_rub, partner_commission_percent,
            ref_token, campaign_kind, client_fixed_bonus_rub, max_activations,
            exchange_discount_min_order_rub,
            is_active, created_by, issued_by_operator_id, created_at, updated_at
        )
        VALUES ($1, $2, 0, 0, 0, $3, 'exchange_discount', $4, $5, $8, TRUE, $6, $7, now(), now())
        RETURNING *
        """,
        code,
        title,
        ref_token,
        client_fixed_bonus_rub,
        max_activations,
        created_by_web_user_id,
        issued_by_operator_id,
        min_order,
    )
