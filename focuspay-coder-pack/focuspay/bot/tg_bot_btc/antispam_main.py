"""Отдельный процесс: антиспам в focus-чате / отзывах / новостях."""
from __future__ import annotations

import logging
import os
import sys

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

from handlers.group_antispam import register_group_antispam_handlers
from handlers.group_call import register_group_call_handlers
from handlers.group_cleanup import register_group_cleanup_handlers
from services.config_rates import DATABASE_DSN
from services.db import init_db
from services.chat_roster import ensure_chat_call_members
from services.group_spam_phrases_store import refresh_phrases

TELEGRAM_ANTISPAM_BOT_TOKEN = os.environ.get("TELEGRAM_ANTISPAM_BOT_TOKEN", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("antispam_main")


async def _antispam_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("antispam handler error: %s", context.error)


async def on_startup(app: Application) -> None:
    dsn = (DATABASE_DSN or "").strip()
    if not dsn:
        print("FATAL: DATABASE_DSN is not set", file=sys.stderr)
        sys.exit(1)
    await init_db(dsn)
    try:
        await ensure_chat_call_members()
    except Exception:
        logger.exception("chat call members table")
    loaded = await refresh_phrases(force=True)
    logger.info("group spam phrases loaded: %s", len(loaded))


def main() -> None:
    token = (TELEGRAM_ANTISPAM_BOT_TOKEN or "").strip()
    if not token:
        print(
            "FATAL: TELEGRAM_ANTISPAM_BOT_TOKEN is not set",
            file=sys.stderr,
        )
        sys.exit(1)

    app = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .post_init(on_startup)
        .build()
    )
    register_group_call_handlers(app)
    register_group_cleanup_handlers(app)
    register_group_antispam_handlers(app)
    app.add_error_handler(_antispam_error)
    print("Group antispam started (polling)")
    app.run_polling(
        drop_pending_updates=False,
        allowed_updates=[
            Update.MESSAGE,
            Update.EDITED_MESSAGE,
            Update.CHANNEL_POST,
            Update.EDITED_CHANNEL_POST,
            Update.CHAT_MEMBER,
        ],
    )


if __name__ == "__main__":
    main()
