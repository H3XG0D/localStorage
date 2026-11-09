"""Web-first referral/promo attribution: track visits, apply to guest, merge on auth."""
from __future__ import annotations

import logging
from typing import Literal

from auth import ensure_bot_user
from db import get_pool
from guest_sessions import get_or_create_guest_user_id
from promo_attribution_service import (
    assign_promo_to_user_if_first,
    get_active_promo_campaign_by_ref_token,
)
from user_referral_db import assign_referrer_if_first

logger = logging.getLogger("web_attribution")

RefKind = Literal["promo", "user"]
_SKIP_PROMO_KINDS = frozenset({"fixed_rub", "exchange_discount"})


async def resolve_ref_token_kind(token: str) -> RefKind | None:
    """Единая ссылка: определить тип токена (промо-кампания или реферер-пользователь)."""
    token = (token or "").strip().lower()
    if not token:
        return None
    campaign = await get_active_promo_campaign_by_ref_token(token)
    if campaign:
        kind = (campaign.get("campaign_kind") or "").lower()
        if kind in _SKIP_PROMO_KINDS:
            return None
        return "promo"
    pool = await get_pool()
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT user_id FROM bot_users WHERE ref_token = $1",
            token,
        )
    return "user" if owner else None


async def merge_promo_attribution(from_user_id: int, to_user_id: int) -> None:
    if from_user_id == to_user_id:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            has_target = await conn.fetchval(
                "SELECT 1 FROM promo_attributions WHERE user_id = $1 LIMIT 1",
                to_user_id,
            )
            if has_target:
                await conn.execute(
                    "DELETE FROM promo_attributions WHERE user_id = $1",
                    from_user_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE promo_attributions SET user_id = $2
                    WHERE user_id = $1
                      AND NOT EXISTS (
                          SELECT 1 FROM promo_attributions x WHERE x.user_id = $2
                      )
                    """,
                    from_user_id,
                    to_user_id,
                )
                await conn.execute(
                    "DELETE FROM promo_attributions WHERE user_id = $1",
                    from_user_id,
                )


async def merge_user_referral_attribution(from_user_id: int, to_user_id: int) -> None:
    if from_user_id == to_user_id:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            has_target = await conn.fetchval(
                "SELECT 1 FROM user_referral_attributions WHERE user_id = $1 LIMIT 1",
                to_user_id,
            )
            if has_target:
                await conn.execute(
                    "DELETE FROM user_referral_attributions WHERE user_id = $1",
                    from_user_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE user_referral_attributions SET user_id = $2
                    WHERE user_id = $1
                      AND NOT EXISTS (
                          SELECT 1 FROM user_referral_attributions x WHERE x.user_id = $2
                      )
                    """,
                    from_user_id,
                    to_user_id,
                )
                await conn.execute(
                    "DELETE FROM user_referral_attributions WHERE user_id = $1",
                    from_user_id,
                )
            await conn.execute(
                """
                UPDATE bot_users SET pending_ref_token = COALESCE(
                    (SELECT pending_ref_token FROM bot_users WHERE user_id = $1),
                    pending_ref_token
                )
                WHERE user_id = $2 AND pending_ref_token IS NULL
                """,
                from_user_id,
                to_user_id,
            )


async def merge_guest_attribution_to_user(guest_user_id: int, real_user_id: int) -> None:
    if guest_user_id == real_user_id:
        return
    await merge_promo_attribution(guest_user_id, real_user_id)
    await merge_user_referral_attribution(guest_user_id, real_user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE web_attribution_pending
            SET applied = TRUE
            WHERE guest_user_id = $1 AND applied = FALSE
            """,
            guest_user_id,
        )


async def _record_pending(
    *,
    ref_kind: RefKind,
    ref_token: str,
    guest_user_id: int,
    fingerprint: str | None,
    client_ip: str | None,
    user_agent: str | None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO web_attribution_pending (
                ref_kind, ref_token, guest_user_id, fingerprint, client_ip, user_agent
            )
            VALUES ($1, $2, $3, $4, $5::inet, $6)
            """,
            ref_kind,
            ref_token,
            guest_user_id,
            (fingerprint or "")[:64] or None,
            client_ip,
            (user_agent or "")[:500] or None,
        )


async def _set_pending_ref_token(user_id: int, ref_token: str | None) -> None:
    if not ref_token:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE bot_users SET pending_ref_token = $2
            WHERE user_id = $1
              AND (pending_ref_token IS NULL OR pending_ref_token = $2)
            """,
            user_id,
            ref_token.strip().lower(),
        )


async def track_ref_visit(
    *,
    ref_kind: str,
    ref_token: str,
    guest_session: str,
    fingerprint: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> dict:
    token = (ref_token or "").strip().lower()
    if not token:
        return {"ok": False, "reason": "invalid_token"}

    # Единая ссылка: авто-определение типа токена, если не задан явно.
    if ref_kind not in ("promo", "user"):
        if ref_kind not in ("auto", "", None):
            return {"ok": False, "reason": "invalid_kind"}
        detected = await resolve_ref_token_kind(token)
        if detected is None:
            return {"ok": False, "reason": "token_not_found"}
        ref_kind = detected

    guest_user_id = await get_or_create_guest_user_id(guest_session)
    await ensure_bot_user(guest_user_id)

    applied = False
    if ref_kind == "promo":
        campaign = await get_active_promo_campaign_by_ref_token(token)
        if not campaign:
            return {"ok": False, "reason": "campaign_not_found"}
        kind = (campaign.get("campaign_kind") or "").lower()
        if kind in _SKIP_PROMO_KINDS:
            return {"ok": False, "reason": "campaign_not_applicable"}
        applied = await assign_promo_to_user_if_first(guest_user_id, campaign["code"])
    else:
        applied = await assign_referrer_if_first(guest_user_id, token)
        if applied:
            await _set_pending_ref_token(guest_user_id, token)

    await _record_pending(
        ref_kind=ref_kind,
        ref_token=token,
        guest_user_id=guest_user_id,
        fingerprint=fingerprint,
        client_ip=client_ip,
        user_agent=user_agent,
    )

    if ref_kind == "user" and not applied:
        await _set_pending_ref_token(guest_user_id, token)

    logger.info(
        "web ref track kind=%s token=%s guest=%s applied=%s",
        ref_kind,
        token[:8],
        guest_user_id,
        applied,
    )
    return {
        "ok": True,
        "applied": applied,
        "guest_user_id": guest_user_id,
        "ref_kind": ref_kind,
        "ref_token": token,
    }


async def _merge_by_signal_guests(
    real_user_id: int,
    *,
    fingerprint: str | None,
    client_ip: str | None,
) -> None:
    fp = (fingerprint or "").strip()[:64] or None
    if not fp and not client_ip:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        if fp:
            rows = await conn.fetch(
                """
                SELECT DISTINCT guest_user_id FROM web_attribution_pending
                WHERE applied = FALSE
                  AND expires_at > now()
                  AND fingerprint = $1
                  AND guest_user_id != $2
                ORDER BY guest_user_id
                LIMIT 5
                """,
                fp,
                real_user_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT DISTINCT guest_user_id FROM web_attribution_pending
                WHERE applied = FALSE
                  AND expires_at > now()
                  AND client_ip = $1::inet
                  AND guest_user_id != $2
                  AND created_at >= now() - interval '24 hours'
                ORDER BY guest_user_id
                LIMIT 3
                """,
                client_ip,
                real_user_id,
            )
    for row in rows:
        await merge_guest_attribution_to_user(int(row["guest_user_id"]), real_user_id)


async def resolve_pending_for_user(
    real_user_id: int,
    *,
    guest_session: str | None = None,
    fingerprint: str | None = None,
    client_ip: str | None = None,
) -> None:
    await ensure_bot_user(real_user_id)

    if guest_session:
        try:
            guest_user_id = await get_or_create_guest_user_id(guest_session)
            if guest_user_id != real_user_id:
                await merge_guest_attribution_to_user(guest_user_id, real_user_id)
        except Exception as e:
            logger.debug("guest session merge skip: %s", e)

    await _merge_by_signal_guests(
        real_user_id,
        fingerprint=fingerprint,
        client_ip=client_ip,
    )


async def user_has_any_attribution(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if await conn.fetchval(
            "SELECT 1 FROM promo_attributions WHERE user_id = $1 LIMIT 1", user_id
        ):
            return True
        if await conn.fetchval(
            "SELECT 1 FROM user_referral_attributions WHERE user_id = $1 LIMIT 1",
            user_id,
        ):
            return True
        if await conn.fetchval(
            "SELECT 1 FROM bot_users WHERE user_id = $1 AND pending_ref_token IS NOT NULL",
            user_id,
        ):
            return True
    return False
