#!/usr/bin/env python3
"""Одобрить висящие заявки в focus чат для всех bot_users."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import config_rates as cfg
from services.community_join_sync import sync_community_join_requests
from services.db import init_db
from telegram import Bot


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chat-id",
        type=int,
        default=0,
        help="ID чата (по умолчанию community_chat_id)",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        action="append",
        dest="user_ids",
        help="Проверить только указанных user_id (можно несколько раз)",
    )
    args = parser.parse_args()

    await init_db(cfg.DATABASE_DSN)
    bot = Bot(cfg.TELEGRAM_BOT_TOKEN)
    chat_id = args.chat_id or cfg.community_chat_id()
    if not chat_id:
        print("community chat_id не задан", file=sys.stderr)
        return 1

    result = await sync_community_join_requests(
        bot,
        chat_id=chat_id,
        user_ids=args.user_ids,
    )
    print(
        f"chat={chat_id} checked={result.checked} approved={result.approved} "
        f"skipped={result.skipped} errors={result.errors}"
    )
    return 0 if result.errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
