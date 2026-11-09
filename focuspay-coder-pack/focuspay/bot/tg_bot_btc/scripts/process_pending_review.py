#!/usr/bin/env python3
"""Создать и опубликовать отзыв вручную (восстановление после сбоя FSM)."""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
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
    create_pending_submission,
    publish_submission,
    validate_review_text,
)
from services.site_reviews import save_channel_review
from telegram import Bot, User
from telegram.error import BadRequest, RetryAfter


async def find_message_id(
    bot: Bot,
    *,
    chat_id: int,
    needle: str,
    start: int,
    end: int,
) -> int | None:
    needle_l = needle.lower()
    for mid in range(start, end + 1):
        while True:
            try:
                copied = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=chat_id,
                    message_id=mid,
                )
                break
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 1)
            except BadRequest:
                copied = None
                break
        if not copied:
            continue
        text = (copied.text or copied.caption or "").strip()
        try:
            await bot.delete_message(chat_id=chat_id, message_id=copied.message_id)
        except BadRequest:
            pass
        if needle_l in text.lower():
            return mid
        await asyncio.sleep(0.05)
    return None


async def publish_without_forward(
    bot: Bot,
    *,
    submission_id: int,
    bonus_rub: float,
    moderated_by: int,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            sub = await conn.fetchrow(
                "SELECT * FROM review_submissions WHERE id = $1 FOR UPDATE",
                submission_id,
            )
            if not sub:
                raise RuntimeError("submission not found")
            sub = dict(sub)
            if sub["status"] != "pending":
                raise RuntimeError("submission already processed")

            chat_id = cfg.REVIEWS_PUBLISH_CHAT_ID
            if not chat_id:
                raise RuntimeError("REVIEWS_PUBLISH_CHAT_ID not set")

            sent = await bot.send_message(chat_id=chat_id, text=sub["review_text"])
            text_mid = int(sent.message_id)
            author = sub["author_display"] or f"id{sub['user_id']}"
            site_author = author[1:] if author.startswith("@") else author
            published_at = datetime.now(timezone.utc)

            await save_channel_review(
                message_id=text_mid,
                text=sub["review_text"],
                author_name=site_author,
                published_at=published_at,
                channel_username=REVIEWS_CHANNEL,
                conn=conn,
            )

            credit = bonus_rub > 0
            if credit:
                already = await conn.fetchval(
                    """
                    SELECT 1 FROM review_bonus_claims
                    WHERE user_id = $1 AND created_at::date = CURRENT_DATE
                    LIMIT 1
                    """,
                    int(sub["user_id"]),
                )
                if already is not None:
                    raise RuntimeError("bonus already claimed today")

                await conn.execute(
                    """
                    INSERT INTO review_bonus_claims (
                        user_id, amount_rub, order_id, channel_message_id,
                        review_text, author_display, source_chat_id, source_message_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    sub["user_id"],
                    bonus_rub,
                    sub.get("order_id"),
                    text_mid,
                    sub["review_text"],
                    author,
                    sub["source_text_chat_id"],
                    sub["source_text_message_id"],
                )
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    sub["user_id"],
                    bonus_rub,
                    f"Бонус за отзыв ({int(bonus_rub)} ₽)",
                )

            await conn.execute(
                """
                UPDATE review_submissions
                SET status = 'published',
                    channel_text_message_id = $2,
                    bonus_rub = $3,
                    bonus_credited = $4,
                    moderated_by = $5,
                    moderated_at = now()
                WHERE id = $1
                """,
                submission_id,
                text_mid,
                bonus_rub if credit else None,
                credit,
                moderated_by,
            )

    return {
        "channel_url": channel_post_url(text_mid),
        "amount_rub": bonus_rub if credit else 0,
        "user_id": int(sub["user_id"]),
    }


async def _run(args: argparse.Namespace) -> int:
    if not cfg.DATABASE_DSN or not cfg.TELEGRAM_BOT_TOKEN:
        raise SystemExit("DATABASE_DSN / TELEGRAM_BOT_TOKEN required")

    await init_db(cfg.DATABASE_DSN)
    bot = Bot(cfg.TELEGRAM_BOT_TOKEN)
    user_id = int(args.user_id)
    order_id = str(args.order_id)
    review_text = validate_review_text(args.text)

    message_id = args.message_id
    if not message_id and args.find_needle:
        print(f"scanning message_id {args.scan_start}..{args.scan_end} ...")
        message_id = await find_message_id(
            bot,
            chat_id=user_id,
            needle=args.find_needle,
            start=args.scan_start,
            end=args.scan_end,
        )
        if message_id:
            print(f"found message_id={message_id}")

    if not message_id:
        message_id = 0
        print("using message_id=0 (publish without forward)")

    tg_user = await bot.get_chat(user_id)
    user = User(
        id=user_id,
        is_bot=False,
        first_name=tg_user.first_name or "",
        username=getattr(tg_user, "username", None),
    )

    sub_id = await create_pending_submission(
        user_id=user_id,
        review_text=review_text,
        user=user,
        order_id=order_id,
        source_text_chat_id=user_id,
        source_text_message_id=int(message_id),
        tier="text",
    )
    print(f"created pending submission id={sub_id}")

    if args.publish:
        admin_id = int((cfg.TELEGRAM_ADMIN_IDS or [0])[0])
        if message_id:
            result = await publish_submission(
                bot,
                sub_id,
                bonus_rub=float(args.bonus),
                moderated_by=admin_id,
            )
        else:
            result = await publish_without_forward(
                bot,
                submission_id=sub_id,
                bonus_rub=float(args.bonus),
                moderated_by=admin_id,
            )
        print(
            f"published sub_id={sub_id} bonus={result['amount_rub']} "
            f"url={result['channel_url']}"
        )
        await bot.send_message(
            chat_id=user_id,
            text=(
                "✅ <b>Ваш отзыв одобрен и опубликован!</b>\n\n"
                f"🎁 На баланс: <b>{int(result['amount_rub'])} ₽</b>\n"
                f'📢 <a href="{result["channel_url"]}">Канал отзывов</a>'
            ),
            parse_mode="HTML",
        )

    if db.DB_POOL is not None:
        await db.DB_POOL.close()
        db.DB_POOL = None
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Create/publish review manually")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--order-id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--message-id", type=int)
    p.add_argument("--find-needle")
    p.add_argument("--scan-start", type=int, default=5600)
    p.add_argument("--scan-end", type=int, default=6200)
    p.add_argument("--publish", action="store_true")
    p.add_argument("--bonus", type=float, default=50)
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
