"""Text review from the website cabinet.

Same queue as the bot: one pending review, one review per paid buy, text tier only.
The bonus lands on this account's balance after moderation. No screenshot.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg

import runtime_settings

logger = logging.getLogger("site_reviews_submit")

MIN_LEN = 20
MAX_LEN = 2000
_TAG_RE = re.compile(r"<[^>]+>")

_ELIGIBLE_ORDER_SQL = """
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


class ReviewRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def clean_review_text(raw: str) -> str:
    text = _TAG_RE.sub("", raw or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN].rstrip()
    if len(text) < MIN_LEN:
        raise ReviewRejected(
            "too_short",
            f"Отзыв слишком короткий. Напишите хотя бы {MIN_LEN} символов.",
        )
    return text


def author_label(user: dict) -> str:
    raw = str(user.get("display_name") or user.get("username") or "").strip()
    name = _TAG_RE.sub("", raw).strip()
    return (name or "Клиент")[:120]


def offer_view(
    *,
    has_paid_buy: bool,
    pending: bool,
    order_id: str | None,
    text_rub: int,
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "eligible": False,
        "pending": bool(pending),
        "reason": None,
        "order_id": order_id,
        "text_rub": int(text_rub),
        "min_len": MIN_LEN,
        "needs_photo": False,
    }
    if pending:
        view["reason"] = "pending"
        return view
    if not has_paid_buy:
        view["reason"] = "no_buy"
        return view
    if not order_id:
        view["reason"] = "already_reviewed"
        return view
    view["eligible"] = True
    return view


def reason_message(view: dict[str, Any]) -> str:
    reason = view.get("reason")
    amount = int(view.get("text_rub") or 0)
    if reason == "pending":
        return (
            f"Отзыв уже на проверке. После одобрения {amount} ₽ появятся на балансе."
        )
    if reason == "no_buy":
        return "Отзыв доступен после успешной покупки, когда крипта уже отправлена."
    if reason == "already_reviewed":
        return "По последним покупкам отзыв уже отправлен. Следующий — после новой покупки."
    return "Сейчас отзыв отправить нельзя."


async def load_offer(conn, user_id: int) -> dict[str, Any]:
    text_rub = int(runtime_settings.review_bonus_text_rub())
    pending = await conn.fetchval(
        """
        SELECT 1 FROM review_submissions
        WHERE user_id = $1 AND status = 'pending'
        LIMIT 1
        """,
        int(user_id),
    )
    paid = await conn.fetchval(
        """
        SELECT 1 FROM orders
        WHERE user_id = $1
          AND LOWER(direction) = 'buy'
          AND status = 'PAID'
        LIMIT 1
        """,
        int(user_id),
    )
    order_id = await conn.fetchval(_ELIGIBLE_ORDER_SQL, int(user_id))
    return offer_view(
        has_paid_buy=paid is not None,
        pending=pending is not None,
        order_id=str(order_id) if order_id else None,
        text_rub=text_rub,
    )


async def create_text_review(conn, *, user_id: int, text: str, author: str) -> dict[str, Any]:
    clean = clean_review_text(text)
    author = (author or "Клиент").strip()[:120]
    async with conn.transaction():
        view = await load_offer(conn, user_id)
        if not view["eligible"]:
            raise ReviewRejected(str(view.get("reason") or "blocked"), reason_message(view))
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO review_submissions (
                    user_id, order_id, tier, status, review_text, author_display,
                    source_text_chat_id, source_text_message_id
                )
                VALUES ($1, $2, 'text', 'pending', $3, $4, 0, 0)
                RETURNING id
                """,
                int(user_id),
                view["order_id"],
                clean,
                author,
            )
        except asyncpg.UniqueViolationError as exc:
            raise ReviewRejected("pending", reason_message({"reason": "pending", "text_rub": view["text_rub"]})) from exc
    return {
        "ok": True,
        "id": int(row["id"]),
        "text_rub": int(view["text_rub"]),
        "order_id": view["order_id"],
    }


async def notify_moderators(submission_id: int) -> None:
    try:
        from review_bot_bridge import send_moderation_via_bot

        await send_moderation_via_bot(int(submission_id))
    except Exception:
        logger.exception("site review moderation card failed id=%s", submission_id)
