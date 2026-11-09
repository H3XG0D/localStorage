"""Привязка пользователя к рефереру по ref_/uref_ deep-link."""
import logging

from services.db import get_pool
from services.referral_links import (
    extract_any_ref_token,
    message_referral_token,
)

logger = logging.getLogger("user_referral_attribution")

AssignResult = str  # applied | already | self | invalid | empty | locked


async def _has_attribution(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                "SELECT 1 FROM user_referral_attributions WHERE user_id = $1",
                user_id,
            )
        )


async def _is_referral_locked(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                "SELECT referral_locked FROM bot_users WHERE user_id = $1",
                user_id,
            )
        )


async def seal_referral_gate(user_id: int) -> None:
    """Закрыть окно реферальной привязки, если пользователь зашёл без реферала."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE bot_users
            SET referral_locked = TRUE,
                pending_ref_token = NULL
            WHERE user_id = $1
              AND referral_locked = FALSE
              AND pending_ref_token IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions WHERE user_id = $1
              )
              AND NOT EXISTS (
                  SELECT 1 FROM promo_attributions WHERE user_id = $1
              )
            """,
            user_id,
        )


async def assign_referrer_by_token(user_id: int, ref_token: str) -> AssignResult:
    token = (ref_token or "").strip().lower()
    if not token:
        return "empty"

    if await _is_referral_locked(user_id):
        return "locked"

    pool = await get_pool()
    async with pool.acquire() as conn:
        referrer = await conn.fetchrow(
            "SELECT user_id FROM bot_users WHERE ref_token = $1",
            token,
        )
        if not referrer:
            return "invalid"
        referrer_id = int(referrer["user_id"])
        if referrer_id == user_id:
            return "self"

        result = await conn.execute(
            """
            INSERT INTO user_referral_attributions (user_id, referrer_user_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
            referrer_id,
        )
        if result.endswith("1"):
            from services.referral_share import ensure_promo_attribution_for_partner_referrer

            await ensure_promo_attribution_for_partner_referrer(conn, user_id, referrer_id)
            logger.info(
                "referral attributed user=%s referrer=%s token=%s",
                user_id,
                referrer_id,
                token,
            )
            import asyncio

            from services.partner_auto_upgrade import maybe_auto_upgrade_referrer

            asyncio.create_task(maybe_auto_upgrade_referrer(referrer_id))
            return "applied"
        return "already"


async def assign_referrer_if_first(user_id: int, payload: str) -> AssignResult:
    token = extract_any_ref_token(payload)
    if not token:
        return "empty"
    return await assign_referrer_by_token(user_id, token)


def _extract_stashable_ref_token(payload: str) -> str | None:
    """Bare-токен из любого формата share-ссылки (ref_/uref_/t.me/…)."""
    return extract_any_ref_token(payload)


async def stash_pending_ref_token_from_payload(user_id: int, payload: str) -> bool:
    """Сохранить ref-токен до капчи или повторного /start без payload."""
    token = _extract_stashable_ref_token(payload)
    await log_start_ref_payload(user_id, payload, ref_token=token)

    if await _is_referral_locked(user_id) or await _has_attribution(user_id):
        return False

    if not token:
        return False

    pool = await get_pool()
    async with pool.acquire() as conn:
        referrer_id = await conn.fetchval(
            "SELECT user_id FROM bot_users WHERE ref_token = $1",
            token,
        )
        if referrer_id and int(referrer_id) == user_id:
            return False
        if not referrer_id:
            # Partner share links may belong to a campaign, not bot_users.
            from services.db import get_active_promo_campaign_by_ref_token

            campaign = await get_active_promo_campaign_by_ref_token(token)
            if not campaign or (campaign.get("campaign_kind") or "") in (
                "fixed_rub", "exchange_discount",
            ):
                return False

        result = await conn.execute(
            """
            UPDATE bot_users
            SET pending_ref_token = $2
            WHERE user_id = $1
              AND referral_locked = FALSE
              AND NOT EXISTS (
                  SELECT 1 FROM user_referral_attributions WHERE user_id = $1
              )
            """,
            user_id,
            token,
        )
        return result.endswith("1")


async def log_start_ref_payload(
    user_id: int,
    payload: str,
    *,
    ref_token: str | None = None,
) -> None:
    raw = (payload or "").strip()
    if not raw:
        return
    token = ref_token if ref_token is not None else _extract_stashable_ref_token(raw)
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_start_ref_log (user_id, payload, ref_token)
                VALUES ($1, $2, $3)
                """,
                user_id,
                raw[:500],
                token,
            )
    except Exception as e:
        logger.debug("start ref log skip user=%s: %s", user_id, e)


async def apply_user_referral_from_start_payload(user_id: int, payload: str) -> AssignResult:
    raw = (payload or "").strip()
    if not raw:
        return "empty"

    token = _extract_stashable_ref_token(raw)
    await log_start_ref_payload(user_id, raw, ref_token=token)

    result = await assign_referrer_if_first(user_id, raw)
    if result != "empty":
        return result
    return "empty"


async def apply_pending_ref_token_if_any(user_id: int) -> AssignResult:
    pool = await get_pool()
    async with pool.acquire() as conn:
        pending = await conn.fetchval(
            "SELECT pending_ref_token FROM bot_users WHERE user_id = $1",
            user_id,
        )
    if not pending:
        return "empty"
    result = await assign_referrer_by_token(user_id, pending)
    if result == "invalid":
        from services.promo_attribution import apply_promo_from_start_payload

        if await apply_promo_from_start_payload(user_id, f"ref_{pending}"):
            result = "applied"
    if result == "applied":
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE bot_users SET pending_ref_token = NULL WHERE user_id = $1",
                user_id,
            )
    return result


async def user_has_attribution(user_id: int) -> bool:
    info = await get_attribution_details(user_id)
    return bool(info.get("has"))


async def get_attribution_details(user_id: int) -> dict:
    """
    Кто привёл клиента: реферер / промо / pending.

    Returns dict:
      has, kind ('referral'|'promo'|'pending'|None),
      label (plain), referrer_user_id, referrer_username, promo_code, promo_name
    """
    empty = {
        "has": False,
        "kind": None,
        "label": "нет",
        "referrer_user_id": None,
        "referrer_username": None,
        "promo_code": None,
        "promo_name": None,
    }
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return empty
    pool = await get_pool()
    async with pool.acquire() as conn:
        ref = await conn.fetchrow(
            """
            SELECT a.referrer_user_id, b.username, b.first_name
            FROM user_referral_attributions a
            LEFT JOIN bot_users b ON b.user_id = a.referrer_user_id
            WHERE a.user_id = $1
            LIMIT 1
            """,
            uid,
        )
        if ref:
            rid = int(ref["referrer_user_id"])
            uname = (ref["username"] or "").strip().lstrip("@")
            who = f"@{uname}" if uname else f"id {rid}"
            return {
                "has": True,
                "kind": "referral",
                "label": f"реферер {who}",
                "referrer_user_id": rid,
                "referrer_username": uname or None,
                "promo_code": None,
                "promo_name": None,
            }
        promo = await conn.fetchrow(
            """
            SELECT pa.promo_code, pc.name
            FROM promo_attributions pa
            LEFT JOIN promo_campaigns pc ON pc.code = pa.promo_code
            WHERE pa.user_id = $1
            LIMIT 1
            """,
            uid,
        )
        if promo:
            code = str(promo["promo_code"] or "").strip()
            name = (promo["name"] or "").strip() if promo["name"] else ""
            label = f"промо {code}" if code else "промо"
            if name:
                label = f"{label} ({name})"
            return {
                "has": True,
                "kind": "promo",
                "label": label,
                "referrer_user_id": None,
                "referrer_username": None,
                "promo_code": code or None,
                "promo_name": name or None,
            }
        pending = await conn.fetchval(
            "SELECT pending_ref_token FROM bot_users WHERE user_id = $1",
            uid,
        )
        if pending:
            return {
                "has": True,
                "kind": "pending",
                "label": "реферал (ожидает привязки)",
                "referrer_user_id": None,
                "referrer_username": None,
                "promo_code": None,
                "promo_name": None,
            }
    return empty


async def apply_user_referral_from_message(user_id: int, message) -> AssignResult:
    if await _is_referral_locked(user_id):
        return "locked"
    token = message_referral_token(message)
    if not token:
        return "empty"
    return await assign_referrer_by_token(user_id, token)


def referral_result_message(result: AssignResult) -> str | None:
    if result == "applied":
        return (
            "✅ Реферальная ссылка принята. "
            "После оплаты обмена реферер получит начисление."
        )
    if result == "already":
        return "ℹ️ Вы уже привязаны к реферальной программе."
    if result == "self":
        return "ℹ️ Нельзя использовать свою реферальную ссылку."
    if result == "locked":
        return (
            "ℹ️ Реферальная ссылка действует только при первом входе в бота. "
            "Повторная привязка недоступна."
        )
    return None
