"""Сохранение отзывов из канала Telegram в общую БД (для сайта)."""
from datetime import datetime, timezone

from services.db import get_pool
from services.text_sanitize import sanitize_author_name, sanitize_review_text

REVIEWS_CHANNEL = "focuspayr"


async def save_channel_review(
    *,
    message_id: int,
    text: str,
    author_name: str | None = None,
    published_at: datetime | None = None,
    channel_username: str = REVIEWS_CHANNEL,
    conn=None,
) -> None:
    raw = (text or "").strip()
    if not raw or raw.lower() == "channel created":
        return
    text = sanitize_review_text(raw)
    if not text:
        return
    author_name = sanitize_author_name(author_name)

    ch = channel_username.lower().lstrip("@")
    pub = published_at or datetime.now(timezone.utc)
    sql = """
        INSERT INTO site_reviews (
            telegram_message_id, channel_username, text, author_name, published_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, now())
        ON CONFLICT (channel_username, telegram_message_id) DO UPDATE SET
            text = EXCLUDED.text,
            author_name = COALESCE(EXCLUDED.author_name, site_reviews.author_name),
            published_at = COALESCE(EXCLUDED.published_at, site_reviews.published_at),
            updated_at = now()
    """
    args = (message_id, ch, text, author_name, pub)
    if conn is not None:
        await conn.execute(sql, *args)
        return
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute(sql, *args)
