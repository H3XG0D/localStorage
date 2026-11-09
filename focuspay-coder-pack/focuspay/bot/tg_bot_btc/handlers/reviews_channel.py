"""Новые посты в канале отзывов → БД для сайта (бот должен быть админом канала)."""
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from services.site_reviews import REVIEWS_CHANNEL, save_channel_review

_SKIP_TEXT = frozenset({"channel created"})


async def channel_review_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.edited_channel_post
    if not msg or not msg.chat:
        return

    username = (msg.chat.username or "").lower()
    if username != REVIEWS_CHANNEL:
        return

    # Скриншоты отзывов с фото публикуются через модерацию (publish_submission)
    # и привязываются к текстовой строке через channel_photo_message_id.
    # Если индексировать фото-пост отдельно, на сайте появляется дубль отзыва.
    if msg.photo or msg.video or msg.document or msg.animation:
        return

    text = (msg.text or msg.caption or "").strip()
    if not text or text.lower() in _SKIP_TEXT:
        return

    author = None
    if msg.from_user:
        author = msg.from_user.first_name or msg.from_user.username

    published = msg.date
    if published and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    await save_channel_review(
        message_id=msg.message_id,
        text=text,
        author_name=author,
        published_at=published,
        channel_username=username,
    )
