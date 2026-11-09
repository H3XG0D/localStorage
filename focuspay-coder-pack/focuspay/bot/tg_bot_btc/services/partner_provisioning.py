"""Create partner campaign + account (shared by admin API logic and auto-upgrade)."""
from __future__ import annotations

import secrets
import string
from typing import Any

from services.partner_auth import (
    _USERNAME_RE,
    hash_password,
    normalize_username,
    validate_username,
)
from services.referral_links import generate_ref_token
from services.partner_tier import partner_tier_overrides_for_rate
from services.runtime_settings import partner_tier_global, refresh_settings

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_campaign_code(prefix: str = "PR") -> str:
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"{prefix}{suffix}"


async def pick_unique_campaign_code(conn, prefix: str = "PR") -> str:
    for _ in range(12):
        code = generate_campaign_code(prefix)
        exists = await conn.fetchval("SELECT 1 FROM promo_campaigns WHERE code = $1", code)
        if not exists:
            return code
    raise RuntimeError("Could not generate unique promo code")


async def pick_unique_username(conn, base: str) -> str:
    candidate = validate_username(base)
    if not await conn.fetchval(
        "SELECT 1 FROM partner_accounts WHERE LOWER(username) = $1", candidate
    ):
        return candidate
    for i in range(2, 100):
        suffix = f"_{i}"
        trimmed = candidate[: 32 - len(suffix)]
        alt = validate_username(f"{trimmed}{suffix}")
        if not await conn.fetchval(
            "SELECT 1 FROM partner_accounts WHERE LOWER(username) = $1", alt
        ):
            return alt
    raise RuntimeError("Could not allocate unique partner username")


def suggest_username(telegram_user_id: int, tg_username: str | None) -> str:
    if tg_username:
        raw = normalize_username(tg_username)
        if _USERNAME_RE.match(raw):
            return raw
    return f"user{telegram_user_id}"


async def _existing_user_ref_token(conn, telegram_user_id: int | None) -> str | None:
    """Существующий реферальный токен пользователя (для единой ссылки)."""
    if not telegram_user_id:
        return None
    return await conn.fetchval(
        "SELECT ref_token FROM bot_users WHERE user_id = $1",
        telegram_user_id,
    )


async def create_partner_in_tx(
    conn,
    *,
    username: str,
    telegram_user_id: int | None = None,
    created_by: int | None = None,
    base_percent: float | None = None,
    ref_token: str | None = None,
) -> dict[str, Any]:
    """Creates promo_campaign (partner) + partner_accounts row inside an open transaction.

    Единая ссылка: если у пользователя уже есть bot_users.ref_token, он
    переиспользуется как токен партнёрской кампании (ссылка не меняется).
    """
    await refresh_settings()
    tier = partner_tier_global()
    pct = float(base_percent if base_percent is not None else tier["base_percent"])

    uname = await pick_unique_username(conn, username)
    code = await pick_unique_campaign_code(conn, "PR")
    ref_token = (
        ref_token
        or await _existing_user_ref_token(conn, telegram_user_id)
        or generate_ref_token()
    )
    display = f"Партнёр {uname}"
    password_plain = secrets.token_urlsafe(10)

    row = await conn.fetchrow(
        """
        INSERT INTO promo_campaigns (
            code, name, bonus_percent, ad_spend_rub, partner_commission_percent,
            ref_token, campaign_kind, client_fixed_bonus_rub, max_activations,
            is_active, created_by, created_at, updated_at
        )
        VALUES ($1, $2, 0, 0, $3, $4, 'partner', NULL, 1000, TRUE, $5, now(), now())
        RETURNING *
        """,
        code,
        display,
        pct,
        ref_token,
        created_by,
    )
    tier_overrides = partner_tier_overrides_for_rate(pct, tier)
    tier_sets = []
    tier_vals = [row["id"]]
    for col, val in tier_overrides.items():
        tier_sets.append(f"{col} = ${len(tier_vals) + 1}")
        tier_vals.append(val)
    if tier_sets:
        await conn.execute(
            f"UPDATE promo_campaigns SET {', '.join(tier_sets)} WHERE id = $1",
            *tier_vals,
        )
    await conn.execute(
        """
        INSERT INTO partner_accounts (
            promo_campaign_id, username, password_hash, display_name, telegram_user_id
        )
        VALUES ($1, $2, $3, $4, $5)
        """,
        row["id"],
        uname,
        hash_password(password_plain),
        display,
        telegram_user_id,
    )
    if telegram_user_id:
        # Единая ссылка: bot_users.ref_token = токен партнёрской кампании.
        await conn.execute(
            """
            UPDATE bot_users SET ref_token = $1
            WHERE user_id = $2 AND ref_token IS DISTINCT FROM $1
            """,
            ref_token,
            telegram_user_id,
        )
    return {
        "campaign": dict(row),
        "username": uname,
        "password_plain": password_plain,
        "promo_code": code,
        "ref_token": ref_token,
    }


async def migrate_uref_attributions_to_promo(
    conn, referrer_user_id: int, promo_code: str
) -> int:
    """Copy user_referral attributions to promo_attributions where missing."""
    rows = await conn.fetch(
        """
        SELECT user_id FROM user_referral_attributions
        WHERE referrer_user_id = $1
        """,
        referrer_user_id,
    )
    migrated = 0
    for row in rows:
        result = await conn.execute(
            """
            INSERT INTO promo_attributions (user_id, promo_code, assigned_at)
            VALUES ($1, $2, now())
            ON CONFLICT (user_id) DO NOTHING
            """,
            row["user_id"],
            promo_code,
        )
        if result.endswith("1"):
            migrated += 1
    return migrated
