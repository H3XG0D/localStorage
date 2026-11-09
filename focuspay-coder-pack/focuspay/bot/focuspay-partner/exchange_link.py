"""Связка промокода автора с купоном обменника FocusPay.

Сумму, лимит и минимум задаёт обменник (200 ₽, 100 активаций, от 3 000 ₽).
"""
from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger("exchange_link")

DISCOUNT_RUB = 200
MAX_ACTIVATIONS = 100
MIN_ORDER_RUB = 3000


def exchange_sync_configured() -> bool:
    return bool(os.getenv("EXCHANGE_API_URL", "").strip() and os.getenv("TRACK_SECRET", "").strip())


def coupon_payload(
    *,
    code: str,
    author_telegram_id: int,
    video_id: int | None = None,
    issued_for: str = "first_video",
    author_name: str | None = None,
) -> dict:
    body = {
        "code": code,
        "author_telegram_id": int(author_telegram_id),
        "issued_for": issued_for if issued_for in ("first_video", "extra") else "first_video",
    }
    if video_id:
        body["video_id"] = int(video_id)
    if author_name:
        body["author_name"] = author_name
    return body


def lock_first_video_coupon(conn: sqlite3.Connection, author_id: int, *, max_uses: int = MAX_ACTIVATIONS) -> str | None:
    """Если у автора ровно один принятый ролик — фиксирует его код: 100 активаций, без срока."""
    row = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE user_id=? AND status='approved'",
        (author_id,),
    ).fetchone()
    if not row or int(row[0]) != 1:
        return None
    promo = conn.execute("SELECT promo FROM users WHERE id=?", (author_id,)).fetchone()
    code = str(promo[0] or "").strip().upper() if promo else ""
    if not code:
        return None
    conn.execute(
        "UPDATE promo_codes SET max_uses=?, expires=0 WHERE code=?",
        (max_uses, code),
    )
    conn.commit()
    return code


async def push_author_coupon(payload: dict) -> dict | None:
    base = os.getenv("EXCHANGE_API_URL", "").strip().rstrip("/")
    secret = os.getenv("TRACK_SECRET", "").strip()
    if not base or not secret:
        return None
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=10)
    url = f"{base}/api/internal/partner-author-promos"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers={"X-Track-Secret": secret}) as response:
            try:
                body = await response.json(content_type=None)
            except Exception:
                body = {}
            if response.status >= 400:
                detail = body.get("detail") if isinstance(body, dict) else None
                raise RuntimeError(detail or f"exchange promo {response.status}")
            if not isinstance(body, dict):
                raise RuntimeError("exchange promo: пустой ответ")
            logger.info("author coupon synced code=%s created=%s", body.get("code"), body.get("created"))
            return body
