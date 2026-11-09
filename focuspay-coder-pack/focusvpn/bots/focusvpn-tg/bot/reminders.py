"""Subscription reminders: "ends soon" (6 h before) and "ended" (within a day).

FocusPay keeps the sent-log (vpn_notifications); a reminder is recorded first and
sent only if this bot recorded it, so two bot instances never double-send.
"""

from __future__ import annotations

import asyncio
import logging

from telegram.error import Forbidden, TelegramError

from bot import api, config, reviews, ui
from bot.handlers import reminder_keyboard, reminder_text

log = logging.getLogger("focusvpn-tg.reminders")


async def send_review_due(bot) -> int:
    """Once per 7-day window, and only while a paid subscriber can still leave a review."""
    sent = 0
    for rem in await api.fp_review_reminders():
        tid = int(rem["telegram_id"])
        try:
            if not await api.fp_review_notified(tid, rem["window_at"]):
                continue
            await ui.send_html(bot, tid, reviews.reminder_text(rem), reviews.reminder_keyboard())
            sent += 1
        except Forbidden:
            log.info("review reminder %s: user blocked the bot", tid)
        except (api.APIError, TelegramError) as e:
            log.warning("review reminder %s failed: %s", tid, type(e).__name__)
    return sent


async def send_due(bot) -> int:
    sent = 0
    for rem in await api.fp_expiring():
        tid = int(rem["telegram_id"])
        try:
            if not await api.fp_notified(tid, rem["kind"], rem["ends_at"]):
                continue
            st = await api.fp_status(tid)
            await ui.send_html(bot, tid, reminder_text(rem, st), reminder_keyboard(st))
            sent += 1
        except Forbidden:
            log.info("reminder %s: user blocked the bot", tid)
        except (api.APIError, TelegramError) as e:
            log.warning("reminder %s failed: %s", tid, type(e).__name__)
    return sent + await send_review_due(bot)


async def loop(bot) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            n = await send_due(bot)
            if n:
                log.info("sent %d reminders", n)
        except api.APIError as e:
            log.warning("reminders tick: FocusPay %s", e.status)
        except Exception:
            log.exception("reminders tick failed")
        await asyncio.sleep(config.REMINDER_INTERVAL_SEC)
