"""VPN reviews: once every 7 days, live subscription (paid or trial), bonus on the FocusPay balance.

The exchange review stays on its own daily bonus. A VPN claim does not use that day,
and an exchange claim does not use the VPN week.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg

import vpn_billing
from db import get_pool

logger = logging.getLogger("vpn_reviews")

PRODUCT = "vpn"
WEEK = timedelta(days=7)
WEEK_SECONDS = 7 * 24 * 3600
MIN_LEN = 20
MAX_LEN = 2000
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
REMINDER_BATCH = 40


class ReviewRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def photo_root() -> Path:
    return Path(os.getenv("VPN_REVIEW_PHOTO_DIR", "/var/lib/focuspay/vpn-review-photos"))


def review_window_start(now: datetime | None = None) -> datetime:
    """Start of the current 7-day bucket, aligned to the unix epoch."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = int(now.timestamp()) // WEEK_SECONDS * WEEK_SECONDS
    return datetime.fromtimestamp(start, tz=timezone.utc)


def clean_review_text(raw: str) -> str:
    text = _strip_tags(raw or "")
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN].rstrip()
    if len(text) < MIN_LEN:
        raise ReviewRejected("too_short", f"Отзыв слишком короткий. Напишите хотя бы {MIN_LEN} символов.")
    return text


def _strip_tags(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "<":
            end = raw.find(">", i + 1)
            if end == -1:
                out.append(raw[i:])
                break
            i = end + 1
            continue
        out.append(raw[i])
        i += 1
    text = "".join(out).replace("\r\n", "\n").replace("\r", "\n").strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def offer_view(
    *,
    active: bool,
    status: str | None,
    pending: bool,
    last_published_at: datetime | None,
    now: datetime,
    text_rub: int,
    photo_rub: int,
) -> dict[str, Any]:
    """Who may leave a VPN review right now. A live paid or trial subscription is enough."""
    now = _aware(now) or datetime.now(timezone.utc)
    last = _aware(last_published_at)
    view: dict[str, Any] = {
        "eligible": False,
        "pending": bool(pending),
        "reason": None,
        "next_at": None,
        "text_rub": int(text_rub),
        "photo_rub": int(photo_rub),
    }
    if not active or status not in ("active", "trialing"):
        view["reason"] = "no_sub"
        return view
    if pending:
        view["reason"] = "pending"
        return view
    if last is not None and now - last < WEEK:
        view["reason"] = "cooldown"
        view["next_at"] = (last + WEEK).isoformat()
        return view
    view["eligible"] = True
    return view


def reason_message(view: dict[str, Any]) -> str:
    reason = view.get("reason")
    if reason == "pending":
        return "У вас уже есть отзыв на проверке. Дождитесь решения."
    if reason == "cooldown":
        return "Отзыв о VPN можно оставить раз в неделю."
    if reason == "too_short":
        return str(view.get("message") or "Отзыв слишком короткий.")
    return "Отзыв можно оставить при живой подписке FocusVPN."


def safe_photo_path(path: str | None) -> Path | None:
    if not path:
        return None
    try:
        root = photo_root().resolve()
        target = Path(path).resolve()
    except OSError:
        return None
    if not target.is_file() or root not in target.parents:
        return None
    return target


def read_photo(path: str | None) -> tuple[bytes, str] | None:
    target = safe_photo_path(path)
    if target is None:
        return None
    ext = target.suffix.lower().lstrip(".")
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")
    return target.read_bytes(), mime


def save_photo(telegram_id: int, data: bytes, ext: str) -> str:
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ReviewRejected("photo", "Скрин слишком большой. Пришлите файл до 8 МБ.")
    suffix = ext if ext in {"jpg", "jpeg", "png", "webp", "gif"} else "jpg"
    root = photo_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{int(telegram_id)}-{uuid.uuid4().hex}.{suffix}"
    dest.write_bytes(data)
    return str(dest)


async def offer_for_user(conn, telegram_id: int, subscription: dict[str, Any]) -> dict[str, Any]:
    cfg = await vpn_billing.load_settings(conn)
    pending = await conn.fetchval(
        """
        SELECT 1 FROM review_submissions
        WHERE user_id = $1 AND status = 'pending'
        LIMIT 1
        """,
        int(telegram_id),
    )
    last = await conn.fetchval(
        """
        SELECT moderated_at FROM review_submissions
        WHERE user_id = $1 AND product = 'vpn' AND status = 'published'
        ORDER BY moderated_at DESC NULLS LAST
        LIMIT 1
        """,
        int(telegram_id),
    )
    return offer_view(
        active=bool(subscription.get("active")),
        status=subscription.get("status"),
        pending=pending is not None,
        last_published_at=last,
        now=datetime.now(timezone.utc),
        text_rub=int(cfg["review_bonus_text_rub"]),
        photo_rub=int(cfg["review_bonus_photo_rub"]),
    )


async def create_submission(
    conn,
    *,
    telegram_id: int,
    text: str,
    author: str,
    subscription: dict[str, Any],
    photo: bytes | None = None,
    photo_ext: str | None = None,
) -> dict[str, Any]:
    clean = clean_review_text(text)
    author = (author or f"id{int(telegram_id)}").strip()[:255]
    path: str | None = None
    try:
        async with conn.transaction():
            view = await offer_for_user(conn, telegram_id, subscription)
            if not view["eligible"]:
                raise ReviewRejected(str(view.get("reason") or "not_eligible"), reason_message(view))
            tier = "text"
            if photo:
                path = save_photo(telegram_id, photo, photo_ext or "jpg")
                tier = "photo"
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO review_submissions (
                        user_id, order_id, tier, status, review_text, author_display,
                        source_text_chat_id, source_text_message_id,
                        source_photo_path, product
                    )
                    VALUES ($1, NULL, $2, 'pending', $3, $4, 0, 0, $5, 'vpn')
                    RETURNING id
                    """,
                    int(telegram_id),
                    tier,
                    clean,
                    author,
                    path,
                )
            except asyncpg.UniqueViolationError as exc:
                raise ReviewRejected("pending", reason_message({"reason": "pending"})) from exc
    except Exception:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return {"id": int(row["id"]), "tier": tier, "text_rub": view["text_rub"], "photo_rub": view["photo_rub"]}


async def post_ops_card(submission_id: int) -> None:
    """Ask the FocusPay bot to drop the same moderation card into the ops group."""
    try:
        from review_bot_bridge import send_moderation_via_bot

        await send_moderation_via_bot(submission_id)
    except Exception:
        logger.exception("vpn review ops card failed id=%s", submission_id)


async def due_reminders(conn, now: datetime | None = None) -> list[dict[str, Any]]:
    """Live subscribers, paid or trial, who may review and were not reminded in this 7-day window."""
    now = now or datetime.now(timezone.utc)
    bucket = review_window_start(now)
    cfg = await vpn_billing.load_settings(conn)
    rows = await conn.fetch(
        """
        SELECT p.telegram_id
        FROM (
            SELECT DISTINCT ON (telegram_id) telegram_id
            FROM vpn_purchases
            WHERE kind IN ('paid', 'trial') AND status = 'paid' AND cp_ends_at > now()
            ORDER BY telegram_id, paid_at DESC NULLS LAST, created_at DESC
        ) p
        WHERE NOT EXISTS (
            SELECT 1 FROM vpn_notifications n
            WHERE n.telegram_id = p.telegram_id AND n.kind = 'review' AND n.ends_at = $1
        )
        AND NOT EXISTS (
            SELECT 1 FROM review_submissions rs
            WHERE rs.user_id = p.telegram_id AND rs.status = 'pending'
        )
        AND NOT EXISTS (
            SELECT 1 FROM review_submissions rs
            WHERE rs.user_id = p.telegram_id
              AND rs.product = 'vpn'
              AND rs.status = 'published'
              AND rs.moderated_at > now() - interval '7 days'
        )
        LIMIT $2
        """,
        bucket,
        REMINDER_BATCH,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        tg = int(row["telegram_id"])
        cp = await vpn_billing.cp_status(tg)
        sub = vpn_billing.subscription_view(cp, now)
        if not sub.get("active") or sub.get("status") not in ("active", "trialing"):
            continue
        out.append({
            "telegram_id": tg,
            "window_at": bucket.isoformat(),
            "text_rub": int(cfg["review_bonus_text_rub"]),
            "photo_rub": int(cfg["review_bonus_photo_rub"]),
        })
    return out


async def mark_reminded(conn, telegram_id: int, window_at: datetime) -> bool:
    """Record the reminder. False if this window was already taken."""
    if window_at.tzinfo is None:
        window_at = window_at.replace(tzinfo=timezone.utc)
    row = await conn.fetchrow(
        """
        INSERT INTO vpn_notifications (telegram_id, kind, ends_at)
        VALUES ($1, 'review', $2)
        ON CONFLICT DO NOTHING
        RETURNING telegram_id
        """,
        int(telegram_id),
        window_at,
    )
    return row is not None


async def submit_and_notify(
    *,
    telegram_id: int,
    text: str,
    author: str,
    subscription: dict[str, Any],
    photo: bytes | None = None,
    photo_ext: str | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        created = await create_submission(
            conn,
            telegram_id=telegram_id,
            text=text,
            author=author,
            subscription=subscription,
            photo=photo,
            photo_ext=photo_ext,
        )
    await post_ops_card(int(created["id"]))
    return created
