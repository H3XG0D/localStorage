"""Отзыв через бота: модерация в ops, публикация в канал, бонус 50/100 ₽."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from services import config_rates, runtime_settings
from services.db import get_pool
from services.review_invite_content import review_invite_text
from services.site_reviews import REVIEWS_CHANNEL, save_channel_review
from services.text_sanitize import sanitize_review_text

if TYPE_CHECKING:
    from telegram import User

logger = logging.getLogger("review_bonus")

_pending_review_orders: dict[int, str] = {}

MIN_REVIEW_LEN = 20
MAX_REVIEW_LEN = 2000

TIER_TEXT = "text"
TIER_PHOTO = "photo"


def review_invite_keyboard(*, include_start: bool = True):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from services.review_invite_content import review_invite_reply_markup_dict

    buttons = []
    for row in review_invite_reply_markup_dict(include_start=include_start)[
        "inline_keyboard"
    ]:
        btn_row = []
        for b in row:
            if b.get("url"):
                btn_row.append(InlineKeyboardButton(b["text"], url=b["url"]))
            else:
                btn_row.append(
                    InlineKeyboardButton(b["text"], callback_data=b["callback_data"])
                )
        buttons.append(btn_row)
    return InlineKeyboardMarkup(buttons)


async def review_invite_keyboard_for_user(user_id: int):
    return review_invite_keyboard(
        include_start=await user_can_submit_review(user_id)
    )


async def get_eligible_review_order_id(user_id: int) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            oid = await conn.fetchval(_REVIEW_ELIGIBLE_ORDER_SQL, user_id)
            return str(oid) if oid else None
        except Exception:
            logger.exception("get_eligible_review_order_id failed user=%s", user_id)
            return None


async def user_has_paid_buy_order(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return bool(
                await conn.fetchval(
                    """
                    SELECT 1 FROM orders
                    WHERE user_id = $1
                      AND LOWER(direction) = 'buy'
                      AND status = 'PAID'
                    LIMIT 1
                    """,
                    user_id,
                )
            )
        except Exception:
            return False


async def user_can_submit_review(user_id: int) -> bool:
    if await user_has_pending_submission(user_id):
        return False
    return await get_eligible_review_order_id(user_id) is not None


async def review_submission_block_message(user_id: int) -> str:
    if await user_has_pending_submission(user_id):
        return (
            "ℹ️ У вас уже есть отзыв на проверке. "
            "Дождитесь решения админа."
        )
    if not await user_has_paid_buy_order(user_id):
        return (
            "Отзыв доступен только после <b>успешной покупки</b> "
            "(крипта уже отправлена — авто или ручной обмен).\n\n"
            "После сделки придёт отдельное приглашение оставить отзыв."
        )
    return (
        "По вашим последним покупкам отзыв уже отправлен.\n\n"
        "После следующей успешной покупки можно оставить новый отзыв."
    )


async def resolve_review_order_id(
    user_id: int, hinted_order_id: str | None = None
) -> str:
    if await user_has_pending_submission(user_id):
        raise ReviewBonusError(await review_submission_block_message(user_id))

    pool = await get_pool()
    async with pool.acquire() as conn:
        if hinted_order_id:
            try:
                ok = await conn.fetchval(
                    """
                    SELECT o.order_id
                    FROM orders o
                    WHERE o.user_id = $1
                      AND o.order_id = $2
                      AND LOWER(o.direction) = 'buy'
                      AND o.status = 'PAID'
                      AND NOT EXISTS (
                          SELECT 1 FROM review_submissions rs
                          WHERE rs.user_id = o.user_id
                            AND rs.order_id = o.order_id
                            AND rs.status IN ('pending', 'published')
                      )
                    """,
                    user_id,
                    hinted_order_id,
                )
                if ok:
                    return str(ok)
            except Exception:
                logger.exception(
                    "resolve_review_order_id hint failed user=%s order=%s",
                    user_id,
                    hinted_order_id,
                )

    oid = await get_eligible_review_order_id(user_id)
    if oid:
        return oid
    raise ReviewBonusError(await review_submission_block_message(user_id))


def submission_tier(*, has_photo: bool) -> str:
    return TIER_PHOTO if has_photo else TIER_TEXT


def remember_pending_review_order(user_id: int, order_id: str | None) -> None:
    if order_id:
        _pending_review_orders[int(user_id)] = str(order_id)


def pop_pending_review_order(user_id: int) -> str | None:
    return _pending_review_orders.pop(int(user_id), None)


_REVIEW_ELIGIBLE_ORDER_SQL = """
    SELECT o.order_id
    FROM orders o
    WHERE o.user_id = $1
      AND LOWER(o.direction) = 'buy'
      AND o.status = 'PAID'
      AND NOT EXISTS (
          SELECT 1 FROM review_submissions rs
          WHERE rs.user_id = o.user_id
            AND rs.order_id = o.order_id
            AND rs.status IN ('pending', 'published')
      )
    ORDER BY o.updated_at DESC NULLS LAST, o.created_at DESC
    LIMIT 1
"""


class ReviewBonusError(Exception):
    pass


def author_display_name(user: User | Any | None, user_id: int) -> str:
    if not user:
        return f"id{user_id}"
    if user.username:
        return f"@{user.username}"
    name = (user.first_name or "").strip()
    if name:
        return f"{name} · id{user_id}"
    return f"id{user_id}"


def validate_review_text(raw: str) -> str:
    text = sanitize_review_text(raw or "", max_len=MAX_REVIEW_LEN)
    if len(text) < MIN_REVIEW_LEN:
        raise ReviewBonusError(
            f"Отзыв слишком короткий. Напишите хотя бы {MIN_REVIEW_LEN} символов."
        )
    return text


def clear_review_session(context) -> None:
    ud = context if isinstance(context, dict) else context.user_data
    for key in (
        "awaiting_review",
        "review_step",
        "review_draft_text",
        "review_text_chat_id",
        "review_text_message_id",
        "review_photo_chat_id",
        "review_photo_message_id",
        "review_photo_file_id",
        "review_order_id",
        "review_finalize_generation",
    ):
        ud.pop(key, None)


async def can_claim_review_bonus_today(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            claimed = await conn.fetchval(
                """
                SELECT 1 FROM review_bonus_claims
                WHERE user_id = $1
                  AND created_at::date = CURRENT_DATE
                  AND COALESCE(product, 'exchange') = 'exchange'
                LIMIT 1
                """,
                user_id,
            )
            return claimed is None
        except Exception:
            return True


async def review_bonus_today_info(user_id: int) -> dict:
    """Бонус за отзыв: не чаще 1 раза в календарные сутки на пользователя."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                SELECT amount_rub, order_id, created_at
                FROM review_bonus_claims
                WHERE user_id = $1
                  AND created_at::date = CURRENT_DATE
                  AND COALESCE(product, 'exchange') = 'exchange'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                user_id,
            )
        except Exception:
            return {"claimed_today": False, "amount_rub": None, "order_id": None}
    if not row:
        return {"claimed_today": False, "amount_rub": None, "order_id": None}
    return {
        "claimed_today": True,
        "amount_rub": float(row["amount_rub"] or 0),
        "order_id": row.get("order_id"),
        "claimed_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


async def user_has_pending_submission(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchval(
                """
                SELECT 1 FROM review_submissions
                WHERE user_id = $1 AND status = 'pending'
                LIMIT 1
                """,
                user_id,
            )
            return row is not None
        except Exception:
            return False


def exchange_review_has_telegram_source(sub: dict) -> bool:
    """Bot reviews carry a Telegram message. Site reviews store the text only."""
    try:
        chat_id = int(sub.get("source_text_chat_id") or 0)
        message_id = int(sub.get("source_text_message_id") or 0)
    except (TypeError, ValueError):
        return False
    return chat_id > 0 and message_id > 0


def _topic_kwargs(chat_id, product: str) -> dict:
    from services.review_topics import thread_kwargs

    return thread_kwargs(chat_id, product)


async def publish_exchange_to_channel(bot, sub: dict) -> tuple[int, int | None]:
    if exchange_review_has_telegram_source(sub):
        text_mid = await forward_review_to_channel(
            bot,
            from_chat_id=int(sub["source_text_chat_id"]),
            message_id=int(sub["source_text_message_id"]),
        )
        photo_mid = None
        photo_src_id = sub.get("source_photo_message_id")
        if photo_src_id:
            text_src_id = int(sub["source_text_message_id"])
            if int(photo_src_id) != text_src_id:
                photo_mid = await forward_review_to_channel(
                    bot,
                    from_chat_id=int(sub["source_photo_chat_id"]),
                    message_id=int(photo_src_id),
                )
        return text_mid, photo_mid

    chat_id = config_rates.REVIEWS_PUBLISH_CHAT_ID
    if not chat_id:
        raise ReviewBonusError("Канал отзывов не настроен (REVIEWS_PUBLISH_CHAT_ID)")
    text = (sub.get("review_text") or "")[:4000]
    msg = await bot.send_message(chat_id=chat_id, text=text, **_topic_kwargs(chat_id, "exchange"))
    return int(msg.message_id), None


async def forward_review_to_channel(
    bot,
    *,
    from_chat_id: int,
    message_id: int,
) -> int:
    chat_id = config_rates.REVIEWS_PUBLISH_CHAT_ID
    if not chat_id:
        raise ReviewBonusError("Канал отзывов не настроен (REVIEWS_PUBLISH_CHAT_ID)")
    msg = await bot.forward_message(
        chat_id=chat_id,
        from_chat_id=int(from_chat_id),
        message_id=int(message_id),
        **_topic_kwargs(chat_id, "exchange"),
    )
    return int(msg.message_id)


def channel_post_url(message_id: int) -> str:
    ch = config_rates.REVIEWS_CHANNEL_USERNAME
    return f"https://t.me/{ch}/{message_id}"


def review_bonus_blocked(
    product: str,
    *,
    exchange_claimed_today: bool,
    vpn_claimed_within_week: bool,
) -> bool:
    """Exchange bonus is once a calendar day. VPN bonus is once per 7 days. They do not share the counter."""
    if (product or "exchange") == "vpn":
        return bool(vpn_claimed_within_week)
    return bool(exchange_claimed_today)


def publish_bonus_rub(
    product: str,
    action: str,
    *,
    exchange_text: float,
    exchange_photo: float,
    vpn_text: float,
    vpn_photo: float,
) -> float:
    if (product or "exchange") == "vpn":
        return float(vpn_text if action == "pub50" else vpn_photo)
    return float(exchange_text if action == "pub50" else exchange_photo)


async def vpn_bonus_claimed_within_week(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            claimed = await conn.fetchval(
                """
                SELECT 1 FROM review_bonus_claims
                WHERE user_id = $1
                  AND COALESCE(product, 'exchange') = 'vpn'
                  AND created_at > now() - interval '7 days'
                LIMIT 1
                """,
                user_id,
            )
            return claimed is not None
        except Exception:
            return False


async def vpn_review_amounts() -> tuple[int, int]:
    """Amounts from /x8/vpn settings. Defaults match the VPN review offer."""
    import json

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM app_settings WHERE key = 'vpn_billing'"
            )
        if not row:
            return 25, 50
        val = row["value"]
        raw = json.loads(val) if isinstance(val, str) else dict(val)
        text_rub = int(raw.get("review_bonus_text_rub") or 25)
        photo_rub = int(raw.get("review_bonus_photo_rub") or 50)
        return text_rub, photo_rub
    except Exception:
        logger.exception("vpn review amounts")
        return 25, 50


def _safe_vpn_photo(path: str | None):
    import os
    from pathlib import Path

    if not path:
        return None
    root = Path(os.getenv("VPN_REVIEW_PHOTO_DIR", "/var/lib/focuspay/vpn-review-photos")).resolve()
    try:
        target = Path(path).resolve()
    except OSError:
        return None
    if not target.is_file() or root not in target.parents:
        return None
    return target


async def _publish_vpn_to_channel(bot, sub: dict) -> tuple[int, int | None]:
    chat_id = config_rates.REVIEWS_PUBLISH_CHAT_ID
    if not chat_id:
        raise ReviewBonusError("Канал отзывов не настроен (REVIEWS_PUBLISH_CHAT_ID)")
    text = (sub.get("review_text") or "")[:4000]
    msg = await bot.send_message(chat_id=chat_id, text=text, **_topic_kwargs(chat_id, "vpn"))
    text_mid = int(msg.message_id)
    photo_mid = None
    target = _safe_vpn_photo(sub.get("source_photo_path"))
    if target is not None:
        with target.open("rb") as fh:
            photo = await bot.send_photo(chat_id=chat_id, photo=fh, **_topic_kwargs(chat_id, "vpn"))
        photo_mid = int(photo.message_id)
    return text_mid, photo_mid


async def notify_review_user(fallback_bot, user_id: int, text: str, product: str | None) -> None:
    """VPN authors are waiting in @focusvpn1_bot. Exchange authors stay on the FocusPay bot."""
    import os

    if (product or "") == "vpn":
        token = (os.getenv("FOCUSVPN_BOT_TOKEN") or "").strip()
        if token:
            from telegram import Bot

            vpn = Bot(token)
            try:
                await vpn.send_message(
                    chat_id=int(user_id),
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
                return
            except Exception:
                logger.warning("vpn review notify failed user=%s", user_id)
            finally:
                await vpn.shutdown()
    try:
        await fallback_bot.send_message(
            chat_id=int(user_id),
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    except Exception:
        logger.warning("review notify failed user=%s", user_id)


async def create_pending_submission(
    *,
    user_id: int,
    review_text: str,
    user: User | None,
    order_id: str | None,
    source_text_chat_id: int,
    source_text_message_id: int,
    tier: str,
    source_photo_chat_id: int | None = None,
    source_photo_message_id: int | None = None,
    source_photo_file_id: str | None = None,
) -> int:
    if tier == TIER_PHOTO and (
        source_photo_chat_id is None or source_photo_message_id is None
    ):
        raise ReviewBonusError("Для отзыва с фото нужен скриншот.")

    if await user_has_pending_submission(user_id):
        raise ReviewBonusError(
            "У вас уже есть отзыв на проверке. Дождитесь решения админа."
        )

    order_id = await resolve_review_order_id(user_id, order_id)

    author = author_display_name(user, user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO review_submissions (
                user_id, order_id, tier, status, review_text, author_display,
                source_text_chat_id, source_text_message_id,
                source_photo_chat_id, source_photo_message_id,
                source_photo_file_id
            )
            VALUES ($1, $2, $3, 'pending', $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            user_id,
            order_id,
            tier,
            review_text,
            author,
            source_text_chat_id,
            source_text_message_id,
            source_photo_chat_id,
            source_photo_message_id,
            source_photo_file_id,
        )
    return int(row["id"])


async def get_submission(submission_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM review_submissions WHERE id = $1",
            submission_id,
        )
    return dict(row) if row else None


async def publish_submission(
    bot,
    submission_id: int,
    *,
    bonus_rub: float,
    moderated_by: int,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # FOR UPDATE блокирует строку: при двойном клике/двух админах
            # второй вызов дождётся коммита первого и увидит status='published',
            # поэтому повторной пересылки и дубля в site_reviews не будет.
            sub_row = await conn.fetchrow(
                "SELECT * FROM review_submissions WHERE id = $1 FOR UPDATE",
                submission_id,
            )
            if not sub_row:
                raise ReviewBonusError("Заявка не найдена.")
            sub = dict(sub_row)
            if sub["status"] != "pending":
                raise ReviewBonusError("Заявка уже обработана.")

            product = sub.get("product") or "exchange"
            credit_bonus = bonus_rub > 0
            bonus_skipped_daily_limit = False
            bonus_skipped_weekly_limit = False
            if credit_bonus:
                if product == "vpn":
                    already = await conn.fetchval(
                        """
                        SELECT 1 FROM review_bonus_claims
                        WHERE user_id = $1
                          AND COALESCE(product, 'exchange') = 'vpn'
                          AND created_at > now() - interval '7 days'
                        LIMIT 1
                        """,
                        int(sub["user_id"]),
                    )
                else:
                    already = await conn.fetchval(
                        """
                        SELECT 1 FROM review_bonus_claims
                        WHERE user_id = $1
                          AND created_at::date = CURRENT_DATE
                          AND COALESCE(product, 'exchange') = 'exchange'
                        LIMIT 1
                        """,
                        int(sub["user_id"]),
                    )
                if already is not None and review_bonus_blocked(
                    product,
                    exchange_claimed_today=product != "vpn",
                    vpn_claimed_within_week=product == "vpn",
                ):
                    credit_bonus = False
                    if product == "vpn":
                        bonus_skipped_weekly_limit = True
                    else:
                        bonus_skipped_daily_limit = True

            if product == "vpn":
                text_mid, photo_mid = await _publish_vpn_to_channel(bot, sub)
            else:
                text_mid, photo_mid = await publish_exchange_to_channel(bot, sub)

            published_at = datetime.now(timezone.utc)
            author = sub["author_display"] or f"id{sub['user_id']}"
            site_author = author[1:] if author.startswith("@") else author
            review_text = sub["review_text"]

            await save_channel_review(
                message_id=text_mid,
                text=review_text,
                author_name=site_author,
                published_at=published_at,
                channel_username=REVIEWS_CHANNEL,
                conn=conn,
            )
            if photo_mid is not None:
                await conn.execute(
                    """
                    UPDATE site_reviews
                    SET channel_photo_message_id = $1, submission_id = $2
                    WHERE channel_username = $3 AND telegram_message_id = $4
                    """,
                    photo_mid,
                    submission_id,
                    REVIEWS_CHANNEL,
                    text_mid,
                )
            else:
                await conn.execute(
                    """
                    UPDATE site_reviews
                    SET submission_id = $1
                    WHERE channel_username = $2 AND telegram_message_id = $3
                    """,
                    submission_id,
                    REVIEWS_CHANNEL,
                    text_mid,
                )

            if credit_bonus:
                note = (
                    f"Бонус за отзыв VPN ({int(bonus_rub)} ₽)"
                    if product == "vpn"
                    else f"Бонус за отзыв ({int(bonus_rub)} ₽)"
                )
                await conn.execute(
                    """
                    INSERT INTO review_bonus_claims (
                        user_id, amount_rub, order_id, channel_message_id,
                        review_text, author_display, source_chat_id, source_message_id,
                        product
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    sub["user_id"],
                    bonus_rub,
                    sub.get("order_id"),
                    text_mid,
                    review_text,
                    author,
                    sub["source_text_chat_id"],
                    sub["source_text_message_id"],
                    product,
                )
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    sub["user_id"],
                    bonus_rub,
                    note,
                )

            await conn.execute(
                """
                UPDATE review_submissions
                SET status = 'published',
                    channel_text_message_id = $2,
                    channel_photo_message_id = $3,
                    bonus_rub = $4,
                    bonus_credited = $5,
                    moderated_by = $6,
                    moderated_at = now()
                WHERE id = $1
                """,
                submission_id,
                text_mid,
                photo_mid,
                bonus_rub if credit_bonus else None,
                credit_bonus,
                moderated_by,
            )

    try:
        from services.review_topics import copy_into_topic

        await copy_into_topic(
            bot,
            product=product,
            from_chat_id=config_rates.REVIEWS_PUBLISH_CHAT_ID,
            text_message_id=text_mid,
            photo_message_id=photo_mid,
        )
    except Exception:
        logger.warning("review topic copy failed id=%s", submission_id)

    result = {
        "message_id": text_mid,
        "channel_url": channel_post_url(text_mid),
        "site_url": config_rates.reviews_site_url(),
        "amount_rub": round(bonus_rub, 2) if credit_bonus else 0,
        "bonus_skipped_daily_limit": bonus_skipped_daily_limit,
        "bonus_skipped_weekly_limit": bonus_skipped_weekly_limit,
        "product": product,
        "author": author,
        "user_id": int(sub["user_id"]),
    }
    return result


async def reject_submission(
    submission_id: int,
    *,
    moderated_by: int,
    reason: str | None = None,
) -> dict | None:
    sub = await get_submission(submission_id)
    if not sub or sub["status"] != "pending":
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE review_submissions
            SET status = 'rejected',
                moderated_by = $2,
                moderated_at = now(),
                reject_reason = $3
            WHERE id = $1 AND status = 'pending'
            """,
            submission_id,
            moderated_by,
            reason,
        )
    sub["status"] = "rejected"
    return sub
