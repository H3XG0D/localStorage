#!/usr/bin/env python3
"""Опубликовать существующий pending review_submissions по id."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.db as db
from services import config_rates as cfg
from services.db import init_db
from scripts.process_pending_review import publish_without_forward
from services.review_bonus import get_submission, publish_submission
from telegram import Bot


async def _run(submission_id: int, bonus: float, notify: bool) -> int:
    await init_db(cfg.DATABASE_DSN)
    bot = Bot(cfg.TELEGRAM_BOT_TOKEN)
    admin = int((cfg.TELEGRAM_ADMIN_IDS or [0])[0])
    sub = await get_submission(submission_id)
    if not sub:
        print("not found")
        return 1
    src_mid = int(sub.get("source_text_message_id") or 0)
    if src_mid:
        result = await publish_submission(
            bot, submission_id, bonus_rub=bonus, moderated_by=admin
        )
    else:
        result = await publish_without_forward(
            bot, submission_id=submission_id, bonus_rub=bonus, moderated_by=admin
        )
    print(result)
    if notify:
        await bot.send_message(
            chat_id=int(result["user_id"]),
            text=(
                "✅ <b>Ваш отзыв одобрен и опубликован!</b>\n\n"
                f"🎁 На баланс: <b>{int(result['amount_rub'])} ₽</b>\n"
                f'📢 <a href="{result["channel_url"]}">Канал отзывов</a>'
            ),
            parse_mode="HTML",
        )
    if db.DB_POOL:
        await db.DB_POOL.close()
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("submission_id", type=int)
    p.add_argument("--bonus", type=float, default=50)
    p.add_argument("--no-notify", action="store_true")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args.submission_id, args.bonus, not args.no_notify)))


if __name__ == "__main__":
    main()
