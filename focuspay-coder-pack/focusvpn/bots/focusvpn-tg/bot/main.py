"""Entry point: python -m bot.main"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot import config, reminders, reviews
from bot.handlers import cmd_cancel, cmd_help, cmd_menu, cmd_start, on_callback

log = logging.getLogger("focusvpn-tg")


async def _post_init(app: Application) -> None:
    app.bot_data["reminders"] = asyncio.create_task(reminders.loop(app.bot))
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Открыть FocusVPN"),
                BotCommand("menu", "Главное меню"),
                BotCommand("help", "Как подключиться"),
                BotCommand("cancel", "Отменить ввод отзыва"),
            ]
        )
    except Exception:
        log.warning("could not set bot commands")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # httpx logs request URLs, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN required", file=sys.stderr)
        sys.exit(1)
    if not config.FOCUSPAY_INTERNAL_TOKEN or not config.FOCUSVPN_INTERNAL_TOKEN:
        print("FOCUSPAY_INTERNAL_TOKEN and FOCUSVPN_INTERNAL_TOKEN required", file=sys.stderr)
        sys.exit(1)

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        # 36 MB APK; the default media write limit is 20s and drops the upload.
        .media_write_timeout(180)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, reviews.on_message))
    print("FocusVPN Telegram bot starting…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
