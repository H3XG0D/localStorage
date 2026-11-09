"""Синхронизация отзывов из публичного канала Telegram (t.me/s/username)."""
import logging
import re
import time
from datetime import datetime, timezone
from html import unescape

import aiohttp

from config import settings
from db import get_pool

logger = logging.getLogger("reviews_sync")

_LAST_SYNC = 0.0
_SYNC_INTERVAL_SEC = 900  # 15 min

_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*dir="auto">(.*?)</div>',
    re.DOTALL,
)
_AUTHOR_RE = re.compile(
    r'<div class="tgme_widget_message_author[^"]*">[\s\S]*?<span dir="auto">([^<]*)</span>',
    re.DOTALL,
)
_TIME_RE = re.compile(r'<time datetime="([^"]+)"')


def _strip_html(text: str) -> str:
    t = unescape(re.sub(r"<br\s*/?>", "\n", text, flags=re.I))
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


async def upsert_review(
    *,
    message_id: int,
    channel_username: str,
    text: str,
    author_name: str | None = None,
    published_at: datetime | None = None,
) -> None:
    text = (text or "").strip()
    if not text or text.lower() == "channel created":
        return

    channel = channel_username.lower().lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Проверка «был ли уже такой отзыв»: тот же текст мог прийти из другого
        # источника (бот-модерация) под другим telegram_message_id. Если он уже
        # есть под ДРУГИМ id — не плодим дубликат, только обновляем автора, если
        # его не было.
        existing = await conn.fetchrow(
            """
            SELECT telegram_message_id, author_name
            FROM site_reviews
            WHERE channel_username = $1 AND lower(trim(text)) = lower(trim($2))
            ORDER BY telegram_message_id
            LIMIT 1
            """,
            channel,
            text,
        )
        if existing is not None and int(existing["telegram_message_id"]) != int(message_id):
            if author_name and not existing["author_name"]:
                await conn.execute(
                    """
                    UPDATE site_reviews
                    SET author_name = $3, updated_at = now()
                    WHERE channel_username = $1 AND telegram_message_id = $2
                    """,
                    channel,
                    int(existing["telegram_message_id"]),
                    author_name,
                )
            return

        await conn.execute(
            """
            INSERT INTO site_reviews (
                telegram_message_id, channel_username, text, author_name, published_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT (channel_username, telegram_message_id) DO UPDATE SET
                text = EXCLUDED.text,
                author_name = COALESCE(EXCLUDED.author_name, site_reviews.author_name),
                published_at = COALESCE(EXCLUDED.published_at, site_reviews.published_at),
                updated_at = now()
            """,
            message_id,
            channel,
            text,
            author_name,
            published_at,
        )


def _parse_channel_html(html: str, channel: str) -> list[dict]:
    ch = channel.lower()
    pattern = re.compile(rf'data-post="{re.escape(ch)}/(\d+)"', re.I)
    splits = pattern.split(html)
    if len(splits) < 2:
        return []

    items: list[dict] = []
    for i in range(1, len(splits), 2):
        msg_id = int(splits[i])
        block = splits[i + 1] if i + 1 < len(splits) else ""
        text_m = _TEXT_RE.search(block)
        if not text_m:
            continue
        text = _strip_html(text_m.group(1))
        if not text:
            continue
        author_m = _AUTHOR_RE.search(block)
        author = author_m.group(1).strip() if author_m else None
        published_at = None
        time_m = _TIME_RE.search(block)
        if time_m:
            try:
                published_at = datetime.fromisoformat(
                    time_m.group(1).replace("Z", "+00:00")
                )
            except ValueError:
                pass
        items.append(
            {
                "message_id": msg_id,
                "text": text,
                "author_name": author,
                "published_at": published_at,
            }
        )
    return items


async def sync_reviews_from_public_channel(force: bool = False) -> int:
    """Парсит https://t.me/s/{channel} и сохраняет посты в БД. Возвращает число обработанных."""
    global _LAST_SYNC
    channel = (settings.reviews_channel_username or "focuspayr").lstrip("@")
    now = time.time()
    if not force and now - _LAST_SYNC < _SYNC_INTERVAL_SEC:
        return 0

    url = f"https://t.me/s/{channel}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "FocusPayReviewsSync/1.0"},
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("reviews sync HTTP %s for %s", resp.status, url)
                    return 0
                html = await resp.text()
    except Exception as e:
        logger.exception("reviews sync fetch failed: %s", e)
        return 0

    parsed = _parse_channel_html(html, channel)
    count = 0
    for item in parsed:
        await upsert_review(
            message_id=item["message_id"],
            channel_username=channel,
            text=item["text"],
            author_name=item["author_name"],
            published_at=item["published_at"],
        )
        count += 1

    _LAST_SYNC = now
    logger.info("reviews sync: %s messages from @%s", count, channel)
    return count


async def list_reviews(limit: int = 20) -> list[dict]:
    channel = (settings.reviews_channel_username or "focuspayr").lstrip("@")
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Один и тот же отзыв может попасть в таблицу из нескольких источников
        # (бот-модерация и скрапер канала) с разными telegram_message_id, поэтому
        # ON CONFLICT по message_id их не склеивает. У копий совпадает ТЕКСТ
        # (а автор может отличаться: бот хранит имя пользователя, скрапер — подпись
        # из канала). Поэтому дедуп по нормализованному тексту: один и тот же отзыв
        # показываем один раз, предпочитая запись с заполненным автором и посвежее.
        rows = await conn.fetch(
            """
            SELECT id, telegram_message_id, text, author_name, published_at
            FROM (
                SELECT DISTINCT ON (lower(trim(text)))
                    id, telegram_message_id, text, author_name, published_at
                FROM site_reviews
                WHERE channel_username = $1
                  AND text IS NOT NULL
                  AND lower(trim(text)) <> 'channel created'
                ORDER BY
                    lower(trim(text)),
                    (author_name IS NOT NULL AND trim(author_name) <> '') DESC,
                    published_at DESC NULLS LAST,
                    telegram_message_id DESC
            ) deduped
            ORDER BY published_at DESC NULLS LAST, telegram_message_id DESC
            LIMIT $2
            """,
            channel,
            limit,
        )
    return [
        {
            "id": r["id"],
            "telegram_message_id": r["telegram_message_id"],
            "text": r["text"],
            "author_name": r["author_name"],
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
        }
        for r in rows
    ]
