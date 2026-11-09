#!/usr/bin/env python3
"""
Удалить старый пост в канале и переслать отзыв заново (forward от сообщения в личке).
Для новых отзывов используйте модерацию в ops-группе (rev: кнопки), не этот скрипт.

  .venv/bin/python scripts/republish_review_forward.py \\
    --user-id 8718118115 --private-message-id 1234 --text "..."

  # по опубликованной review_submissions (status=published):
  .venv/bin/python scripts/republish_review_forward.py --submission-id 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.db as db
from services import config_rates as cfg
from services.db import get_pool, init_db
from services.review_bonus import (
    REVIEWS_CHANNEL,
    author_display_name,
    channel_post_url,
    forward_review_to_channel,
    validate_review_text,
)
from services.site_reviews import save_channel_review


def _delete_channel_message(message_id: int) -> bool:
    token = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
    chat = cfg.REVIEWS_PUBLISH_CHAT_ID or f"@{cfg.REVIEWS_CHANNEL_USERNAME}"
    if not token or not chat:
        return False
    payload = json.dumps({"chat_id": chat, "message_id": int(message_id)}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/deleteMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("ok", False)
    except Exception as e:
        print("deleteMessage:", e)
        return False


async def _delete_claim_rows(conn, claim_id: int) -> None:
    row = await conn.fetchrow(
        "SELECT channel_message_id FROM review_bonus_claims WHERE id = $1",
        claim_id,
    )
    if not row:
        return
    mid = row["channel_message_id"]
    if mid:
        ok = _delete_channel_message(int(mid))
        print(f"delete channel msg {mid}: {ok}")
        await conn.execute(
            """
            DELETE FROM site_reviews
            WHERE channel_username = $1 AND telegram_message_id = $2
            """,
            REVIEWS_CHANNEL,
            int(mid),
        )
    await conn.execute("DELETE FROM review_bonus_claims WHERE id = $1", claim_id)
    print(f"deleted claim id={claim_id}")


async def _republish(
    *,
    user_id: int,
    private_message_id: int,
    from_chat_id: int | None,
    text: str | None,
    order_id: str | None,
    skip_bonus: bool,
) -> None:
    from telegram import Bot

    bot = Bot(cfg.TELEGRAM_BOT_TOKEN)
    src_chat = int(from_chat_id or user_id)
    if not text:
        raise SystemExit("Нужен --text или review_text в claim")
    review_text = validate_review_text(text)

    new_mid = await forward_review_to_channel(
        bot,
        from_chat_id=src_chat,
        message_id=int(private_message_id),
    )
    print(f"forwarded → channel message_id={new_mid}")
    print(f"url: {channel_post_url(new_mid)}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            author = f"id{user_id}"
            await save_channel_review(
                message_id=new_mid,
                text=review_text if text else "(переслано)",
                author_name=author,
                channel_username=REVIEWS_CHANNEL,
                conn=conn,
            )
            if not skip_bonus:
                amount = float(cfg.REVIEW_BONUS_RUB)
                await conn.execute(
                    """
                    INSERT INTO review_bonus_claims (
                        user_id, amount_rub, order_id, channel_message_id,
                        review_text, author_display, source_chat_id, source_message_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    user_id,
                    amount,
                    order_id,
                    new_mid,
                    review_text if text else "",
                    author,
                    src_chat,
                    private_message_id,
                )
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    user_id,
                    amount,
                    "Бонус за отзыв (republish)",
                )
                print(f"bonus {amount} ₽ credited")


async def _run(args: argparse.Namespace) -> int:
    if not cfg.DATABASE_DSN or not cfg.TELEGRAM_BOT_TOKEN:
        raise SystemExit("DATABASE_DSN / TELEGRAM_BOT_TOKEN required")

    await init_db(cfg.DATABASE_DSN)
    try:
        if args.claim_id:
            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, user_id, review_text, order_id,
                           channel_message_id, source_chat_id, source_message_id
                    FROM review_bonus_claims WHERE id = $1
                    """,
                    args.claim_id,
                )
                if not row:
                    print("claim not found")
                    return 1
                await _delete_claim_rows(conn, args.claim_id)
                if args.delete_only:
                    return 0
                src_mid = row["source_message_id"]
                if not src_mid:
                    print(
                        "Нет source_message_id в БД (старый отзыв был постом бота). "
                        "Укажите --private-message-id из лички с ботом."
                    )
                    return 1
                args.user_id = int(row["user_id"])
                args.private_message_id = int(src_mid)
                args.from_chat_id = int(row["source_chat_id"] or row["user_id"])
                args.text = row["review_text"]

        if not args.user_id or not args.private_message_id:
            raise SystemExit("Нужны --user-id и --private-message-id (или --claim-id с source_*)")

        await _republish(
            user_id=int(args.user_id),
            private_message_id=int(args.private_message_id),
            from_chat_id=args.from_chat_id,
            text=args.text,
            order_id=args.order_id,
            skip_bonus=args.skip_bonus,
        )
        return 0
    finally:
        if db.DB_POOL is not None:
            await db.DB_POOL.close()
            db.DB_POOL = None


def main() -> None:
    p = argparse.ArgumentParser(description="Republish review via forward_message")
    p.add_argument("--claim-id", type=int, help="Удалить claim и переслать по source_*")
    p.add_argument("--user-id", type=int)
    p.add_argument("--private-message-id", type=int, help="message_id отзыва в личке с ботом")
    p.add_argument("--from-chat-id", type=int, help="обычно = user_id")
    p.add_argument("--text", help="текст для site_reviews")
    p.add_argument("--order-id")
    p.add_argument("--delete-only", action="store_true")
    p.add_argument("--skip-bonus", action="store_true")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
