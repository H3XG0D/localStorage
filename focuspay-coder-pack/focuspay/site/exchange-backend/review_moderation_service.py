"""Модерация отзывов для веб-панели операторов и админов."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import aiohttp

import runtime_settings
from config import settings
from db import get_pool
from review_bot_bridge import (
    can_claim_review_bonus_today,
    init_review_bot_bridge,
    publish_submission_via_bot,
    reject_submission_via_bot,
    review_bonus_error_class,
    review_bonus_today_info,
)
from telegram_notify import clear_message_reply_markup, deliver_review_notice, edit_admin_message

logger = logging.getLogger("review_moderation")

ReviewBonusError = review_bonus_error_class()

StatusFilter = Literal["pending", "published", "rejected", "all"]

_LEGACY_SOURCE_CHAT = 0


def _iso(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
    return str(val)


def _channel_post_url(message_id: int | None) -> str | None:
    if not message_id:
        return None
    ch = (settings.reviews_channel_username or "focuspayr").lstrip("@")
    return f"https://t.me/{ch}/{int(message_id)}"


def _row_out(row: dict) -> dict[str, Any]:
    r = dict(row)
    text_mid = r.get("channel_text_message_id")
    has_photo = bool(r.get("source_photo_message_id")) or r.get("tier") == "photo"
    return {
        "id": int(r["id"]),
        "user_id": int(r["user_id"]) if r.get("user_id") else None,
        "username": r.get("username"),
        "first_name": r.get("first_name"),
        "author_display": r.get("author_display"),
        "order_id": r.get("order_id"),
        "tier": r.get("tier") or "text",
        "status": r.get("status"),
        "review_text": r.get("review_text") or "",
        "bonus_rub": float(r["bonus_rub"]) if r.get("bonus_rub") is not None else None,
        "bonus_credited": bool(r.get("bonus_credited")),
        "product": r.get("product") or "exchange",
        "has_photo": has_photo or bool(r.get("source_photo_path")),
        "has_photo_preview": bool(
            r.get("source_photo_file_id")
            or r.get("source_photo_path")
            or (
                r.get("source_photo_chat_id")
                and int(r.get("source_photo_chat_id") or 0) != _LEGACY_SOURCE_CHAT
                and r.get("source_photo_message_id")
            )
        ),
        "is_legacy": int(r.get("source_text_chat_id") or 0) == _LEGACY_SOURCE_CHAT,
        "channel_url": _channel_post_url(text_mid),
        "channel_text_message_id": int(text_mid) if text_mid else None,
        "moderated_by_operator_id": r.get("moderated_by_operator_id"),
        "moderated_at": _iso(r.get("moderated_at")),
        "reject_reason": r.get("reject_reason"),
        "created_at": _iso(r.get("created_at")),
    }


_LIST_SQL_BASE = """
    SELECT rs.*, bu.username, bu.first_name
    FROM review_submissions rs
    LEFT JOIN bot_users bu ON bu.user_id = rs.user_id
"""


async def pending_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*)::int FROM review_submissions WHERE status = 'pending'"
        )
    return int(val or 0)


async def _users_with_bonus_today(user_ids: list[int]) -> set[int]:
    if not user_ids:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT user_id
            FROM review_bonus_claims
            WHERE created_at::date = CURRENT_DATE
              AND COALESCE(product, 'exchange') = 'exchange'
              AND user_id = ANY($1::bigint[])
            """,
            user_ids,
        )
    return {int(r["user_id"]) for r in rows}


async def list_reviews(
    *,
    status: StatusFilter = "all",
    q: str | None = None,
    user_id: int | None = None,
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    page = max(1, page)
    limit = max(1, min(limit, 100))
    offset = (page - 1) * limit

    conditions = ["1=1"]
    params: list[Any] = []
    idx = 1

    if status != "all":
        conditions.append(f"rs.status = ${idx}")
        params.append(status)
        idx += 1

    if user_id is not None:
        conditions.append(f"rs.user_id = ${idx}")
        params.append(int(user_id))
        idx += 1

    if q:
        conditions.append(
            f"""(
                rs.review_text ILIKE ${idx}
                OR rs.author_display ILIKE ${idx}
                OR rs.order_id ILIKE ${idx}
                OR bu.username ILIKE ${idx}
                OR bu.first_name ILIKE ${idx}
                OR rs.user_id::text ILIKE ${idx}
            )"""
        )
        params.append(f"%{q.strip()}%")
        idx += 1

    where = " AND ".join(conditions)
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*)::int FROM review_submissions rs "
            f"LEFT JOIN bot_users bu ON bu.user_id = rs.user_id WHERE {where}",
            *params,
        )
        order = "rs.created_at ASC" if status == "pending" else "rs.created_at DESC"
        rows = await conn.fetch(
            f"{_LIST_SQL_BASE} WHERE {where} "
            f"ORDER BY {order} LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
            limit,
            offset,
        )

    items = [_row_out(dict(r)) for r in rows]
    await _attach_bonus_labels(items)
    if status in ("pending", "all"):
        pending_uids = [
            int(i["user_id"])
            for i in items
            if i.get("status") == "pending" and i.get("user_id")
        ]
        claimed_today = await _users_with_bonus_today(pending_uids)
        for item in items:
            if item.get("status") != "pending" or not item.get("user_id"):
                continue
            uid = int(item["user_id"])
            if item.get("product") != "vpn":
                item["can_claim_bonus_today"] = uid not in claimed_today

    return {
        "items": items,
        "total": int(total or 0),
        "page": page,
        "limit": limit,
    }


async def get_review(submission_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_LIST_SQL_BASE} WHERE rs.id = $1",
            submission_id,
        )
    if not row:
        return None
    out = _row_out(dict(row))
    await _attach_bonus_labels([out])
    uid = out.get("user_id")
    if out.get("product") == "vpn":
        out["bonus_today"] = {"claimed_today": False}
        out["bonus_policy"] = (
            "Бонус за отзыв VPN — не чаще 1 раза в 7 дней. "
            "Живая подписка, платная или пробная. Дневной бонус за отзыв об обмене этот отзыв не тратит."
        )
    elif uid:
        out["can_claim_bonus_today"] = await can_claim_review_bonus_today(int(uid))
        out["bonus_today"] = await review_bonus_today_info(int(uid))
        out["bonus_policy"] = (
            "Бонус за отзыв — не чаще 1 раза в сутки на клиента. "
            "Один обмен — один отзыв; при второй сделке в тот же день отзыв можно опубликовать без повторной выплаты."
        )
    else:
        out["can_claim_bonus_today"] = True
        out["bonus_today"] = {"claimed_today": False}
        out["bonus_policy"] = (
            "Бонус за отзыв — не чаще 1 раза в сутки на клиента. "
            "Один обмен — один отзыв; при второй сделке в тот же день отзыв можно опубликовать без повторной выплаты."
        )
    return out


async def list_reviews_for_user(user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    data = await list_reviews(status="all", user_id=user_id, page=1, limit=limit)
    return data["items"]


async def _set_moderated_by_operator(
    submission_id: int, operator_id: int | None
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE review_submissions
            SET moderated_by_operator_id = $2
            WHERE id = $1
            """,
            submission_id,
            operator_id,
        )


async def _clear_ops_keyboard(sub: dict, *, status_note: str) -> None:
    chat_id = sub.get("moderation_chat_id")
    msg_id = sub.get("moderation_message_id")
    if not chat_id or not msg_id:
        return
    cid, mid = int(chat_id), int(msg_id)
    if await clear_message_reply_markup(cid, mid):
        return
    await edit_admin_message(
        mid,
        status_note,
        chat_id=cid,
        reply_markup={"inline_keyboard": []},
    )


async def _users_with_vpn_bonus_week(user_ids: list[int]) -> set[int]:
    if not user_ids:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT user_id
            FROM review_bonus_claims
            WHERE COALESCE(product, 'exchange') = 'vpn'
              AND created_at > now() - interval '7 days'
              AND user_id = ANY($1::bigint[])
            """,
            user_ids,
        )
    return {int(r["user_id"]) for r in rows}


async def _attach_bonus_labels(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    exchange_text = float(runtime_settings.review_bonus_text_rub())
    exchange_photo = float(runtime_settings.review_bonus_photo_rub())
    vpn_items = [i for i in items if i.get("product") == "vpn"]
    vpn_cfg = None
    week: set[int] = set()
    if vpn_items:
        import vpn_billing

        pool = await get_pool()
        async with pool.acquire() as conn:
            vpn_cfg = await vpn_billing.load_settings(conn)
        week = await _users_with_vpn_bonus_week(
            [int(i["user_id"]) for i in vpn_items if i.get("user_id")]
        )
    for item in items:
        if item.get("product") == "vpn" and vpn_cfg is not None:
            item["bonus_text_rub"] = float(vpn_cfg["review_bonus_text_rub"])
            item["bonus_photo_rub"] = float(vpn_cfg["review_bonus_photo_rub"])
            if item.get("status") == "pending":
                uid = int(item.get("user_id") or 0)
                item["can_claim_bonus_today"] = uid not in week
        else:
            item["bonus_text_rub"] = exchange_text
            item["bonus_photo_rub"] = exchange_photo


async def _submission_product(submission_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT product FROM review_submissions WHERE id = $1",
            submission_id,
        )
    return str(val or "exchange")


async def publish_review(
    submission_id: int,
    *,
    bonus: Literal["text", "photo", "none"],
    operator_id: int | None,
    moderated_by_telegram_id: int = 0,
) -> dict[str, Any]:
    product = await _submission_product(submission_id)
    if bonus == "none":
        bonus_rub = 0.0
    elif product == "vpn":
        import vpn_billing

        pool = await get_pool()
        async with pool.acquire() as conn:
            cfg = await vpn_billing.load_settings(conn)
        bonus_rub = float(cfg["review_bonus_photo_rub"] if bonus == "photo" else cfg["review_bonus_text_rub"])
    elif bonus == "text":
        bonus_rub = float(runtime_settings.review_bonus_text_rub())
    else:
        bonus_rub = float(runtime_settings.review_bonus_photo_rub())

    try:
        result = await publish_submission_via_bot(
            submission_id,
            bonus_rub=bonus_rub,
            moderated_by=moderated_by_telegram_id,
        )
    except ReviewBonusError as e:
        raise ValueError(str(e)) from e

    if operator_id is not None:
        await _set_moderated_by_operator(submission_id, operator_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT moderation_chat_id, moderation_message_id FROM review_submissions WHERE id = $1",
            submission_id,
        )
    if row:
        try:
            await _clear_ops_keyboard(
                {**dict(row), "id": submission_id},
                status_note=f"✅ Отзыв #{submission_id} опубликован (веб-панель)",
            )
        except Exception as e:
            logger.warning("clear ops keyboard failed sub=%s: %s", submission_id, e)

    ch_url = html.escape(result["channel_url"])
    amount = result["amount_rub"]
    skipped_daily = bool(result.get("bonus_skipped_daily_limit"))
    skipped_week = bool(result.get("bonus_skipped_weekly_limit"))
    product = result.get("product") or product
    user_lines = [
        "✅ <b>Ваш отзыв одобрен и опубликован!</b>",
        f'📢 <a href="{ch_url}">Канал отзывов</a>',
        f'🌐 <a href="{html.escape(result["site_url"])}">Сайт</a>',
    ]
    if amount > 0:
        user_lines.insert(1, f"🎁 На баланс: <b>{amount:g} ₽</b>")
    elif skipped_week and bonus_rub > 0:
        user_lines.insert(
            1,
            "ℹ️ Бонус за отзыв VPN уже был на этой неделе — повторная выплата не выдаётся.",
        )
    elif skipped_daily and bonus_rub > 0:
        user_lines.insert(
            1,
            "ℹ️ Бонус за отзыв сегодня уже начислялся — повторная выплата не выдаётся.",
        )
    try:
        await deliver_review_notice(int(result["user_id"]), "\n".join(user_lines), product)
    except Exception as e:
        logger.warning("review publish notify failed sub=%s: %s", submission_id, e)

    return {
        "ok": True,
        "submission_id": submission_id,
        "amount_rub": amount,
        "bonus_skipped_daily_limit": skipped_daily,
        "bonus_skipped_weekly_limit": skipped_week,
        "channel_url": result["channel_url"],
        "user_id": result["user_id"],
        "product": product,
    }


async def reject_review(
    submission_id: int,
    *,
    operator_id: int | None,
    reason: str | None = None,
    moderated_by_telegram_id: int = 0,
) -> dict[str, Any]:
    try:
        sub = await reject_submission_via_bot(
            submission_id,
            moderated_by=moderated_by_telegram_id,
            reason=reason,
        )
    except ReviewBonusError as e:
        raise ValueError(str(e)) from e

    if not sub:
        raise ValueError("Заявка уже обработана или не найдена")

    if operator_id is not None:
        await _set_moderated_by_operator(submission_id, operator_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT moderation_chat_id, moderation_message_id FROM review_submissions WHERE id = $1",
            submission_id,
        )
    if row:
        try:
            await _clear_ops_keyboard(
                {**dict(row), "id": submission_id},
                status_note=f"❌ Отзыв #{submission_id} отклонён (веб-панель)",
            )
        except Exception as e:
            logger.warning("clear ops keyboard failed sub=%s: %s", submission_id, e)

    product = sub.get("product") or "exchange"
    if product == "vpn":
        reject_text = (
            "ℹ️ Ваш отзыв не опубликован после проверки. "
            "Можете отправить новый в боте FocusVPN."
        )
    else:
        reject_text = (
            "ℹ️ Ваш отзыв не опубликован после проверки. "
            "Можете отправить новый через меню «Отзывы»."
        )
    try:
        await deliver_review_notice(int(sub["user_id"]), reject_text, product)
    except Exception as e:
        logger.warning("review reject notify failed sub=%s: %s", submission_id, e)
    return {"ok": True, "submission_id": submission_id, "user_id": int(sub["user_id"])}


async def _telegram_api(method: str, payload: dict) -> dict:
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    url = f"https://api.telegram.org/bot{token}/{method}"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description") or f"{method} failed")
            return data.get("result") or {}


async def _download_file(file_id: str) -> tuple[bytes, str]:
    file_meta = await _telegram_api("getFile", {"file_id": file_id})
    file_path = file_meta.get("file_path")
    if not file_path:
        raise RuntimeError("file_path_missing")
    token = settings.telegram_bot_token.strip()
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            content = await resp.read()
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "jpg"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return content, mime


async def _resolve_photo_file_id(sub: dict) -> str | None:
    fid = sub.get("source_photo_file_id")
    if fid:
        return str(fid)

    photo_chat = sub.get("source_photo_chat_id")
    photo_mid = sub.get("source_photo_message_id")
    if not photo_chat or not photo_mid:
        return None
    if int(photo_chat) == _LEGACY_SOURCE_CHAT:
        return None

    cache_chat = settings.ops_telegram_group_id()
    if not cache_chat:
        return None

    # copyMessage в Bot API возвращает только message_id без photo[] — file_id не извлечь.
    forwarded = await _telegram_api(
        "forwardMessage",
        {
            "chat_id": cache_chat,
            "from_chat_id": int(photo_chat),
            "message_id": int(photo_mid),
        },
    )
    photos = forwarded.get("photo") or []
    if photos:
        return photos[-1].get("file_id")
    doc = forwarded.get("document")
    if doc:
        return doc.get("file_id")
    return None


async def _cache_photo_file_id(submission_id: int, file_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE review_submissions
            SET source_photo_file_id = $2
            WHERE id = $1 AND source_photo_file_id IS NULL
            """,
            submission_id,
            file_id,
        )


async def get_review_photo_bytes(submission_id: int) -> tuple[bytes, str] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM review_submissions WHERE id = $1",
            submission_id,
        )
    if not row:
        return None
    sub = dict(row)
    from vpn_reviews import read_photo

    stored = read_photo(sub.get("source_photo_path"))
    if stored:
        return stored
    try:
        file_id = await _resolve_photo_file_id(sub)
        if not file_id:
            return None
        if not sub.get("source_photo_file_id"):
            await _cache_photo_file_id(submission_id, file_id)
        return await _download_file(file_id)
    except Exception as e:
        logger.warning("review photo fetch failed id=%s: %s", submission_id, e)
        return None
