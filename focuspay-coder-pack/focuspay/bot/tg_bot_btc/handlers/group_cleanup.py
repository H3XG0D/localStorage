"""Авточистка focus-чата: удалённые аккаунты и тех, кто не был в сети больше месяца."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram.error import RetryAfter
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from services.chat_call import CALL_ALLOW_USER_ID, user_may_call
from services.chat_cleanup import (
    CLEAN_INTERVAL_SEC,
    KICK_PAUSE_SEC,
    REASON_DELETED,
    cleanup_reason,
    is_stale_reason,
    summary_line,
)
from services.chat_members_scan import (
    MemberScanNotConfigured,
    scan_chat_members,
    scan_ready,
)
from services.chat_roster import forget_member
from services.config_rates import (
    TELEGRAM_ADMIN_IDS,
    community_chat_id,
    is_community_chat,
    reports_group_id,
)

logger = logging.getLogger("group_cleanup")

_GROUP_TYPES = frozenset({"group", "supergroup"})
_lock = asyncio.Lock()
_active = False

_SKIP_TEXT = {
    "config": "Список участников не настроен.",
    "members": "Не удалось прочитать участников чата.",
    "admins": "Не удалось прочитать админов чата.",
    "no_chat": "Эта команда только в focus-чате.",
}


class CleanupStats:
    def __init__(self) -> None:
        self.checked = 0
        self.stale = 0
        self.deleted = 0
        self.skipped = ""
        self.error = ""

    @property
    def report(self) -> bool:
        return self.skipped == "" and not self.error


def _retry_seconds(exc: RetryAfter) -> float:
    value = exc.retry_after
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    return float(value)


async def _api_call(action, chat_id: int, user_id: int, label: str) -> bool:
    delay = 0.0
    for _attempt in range(4):
        if delay:
            await asyncio.sleep(delay)
            delay = 0.0
        try:
            await action()
            return True
        except RetryAfter as exc:
            delay = _retry_seconds(exc) + 0.5
            logger.warning(
                "cleanup flood chat=%s user=%s op=%s wait=%s",
                chat_id,
                user_id,
                label,
                delay,
            )
        except Exception:
            logger.warning(
                "cleanup %s failed chat=%s user=%s",
                label,
                chat_id,
                user_id,
                exc_info=True,
            )
            return False
    logger.error("cleanup %s gave up chat=%s user=%s", label, chat_id, user_id)
    return False


async def _kick(bot: object, chat_id: int, user_id: int) -> bool:
    banned = await _api_call(
        lambda: bot.ban_chat_member(  # type: ignore[attr-defined]
            chat_id=chat_id,
            user_id=user_id,
            revoke_messages=False,
        ),
        chat_id,
        user_id,
        "ban",
    )
    if not banned:
        return False
    unbanned = await _api_call(
        lambda: bot.unban_chat_member(chat_id=chat_id, user_id=user_id),  # type: ignore[attr-defined]
        chat_id,
        user_id,
        "unban",
    )
    if not unbanned:
        logger.error(
            "cleanup unban failed, user stays banned chat=%s user=%s",
            chat_id,
            user_id,
        )
    return unbanned


def _protected_ids(scanner_id: int, admins: object) -> set[int]:
    protected = {int(item) for item in TELEGRAM_ADMIN_IDS if int(item) > 0}
    protected.add(CALL_ALLOW_USER_ID)
    if scanner_id > 0:
        protected.add(int(scanner_id))
    for admin in admins or ():
        user = getattr(admin, "user", None)
        user_id = getattr(user, "id", None)
        if isinstance(user_id, int) and user_id > 0:
            protected.add(user_id)
    return protected


async def execute_cleanup(bot: object) -> CleanupStats:
    stats = CleanupStats()
    chat_id = int(community_chat_id() or 0)
    if chat_id == 0:
        stats.skipped = "no_chat"
        logger.info("cleanup skipped: no community chat")
        return stats
    if not scan_ready():
        stats.skipped = "config"
        logger.info("cleanup skipped: session not configured")
        return stats
    try:
        scanned = await scan_chat_members(chat_id)
    except MemberScanNotConfigured:
        stats.skipped = "config"
        logger.info("cleanup skipped: session not configured")
        return stats
    except Exception:
        stats.skipped = "members"
        stats.error = _SKIP_TEXT["members"]
        logger.exception("cleanup scan failed chat=%s", chat_id)
        return stats

    try:
        admins = await bot.get_chat_administrators(chat_id)  # type: ignore[attr-defined]
    except Exception:
        stats.skipped = "admins"
        stats.error = _SKIP_TEXT["admins"]
        logger.warning("cleanup admins failed chat=%s", chat_id, exc_info=True)
        return stats

    protected = _protected_ids(scanned.scanner_id, admins)
    now = datetime.now(timezone.utc)
    targets: list[tuple[int, str]] = []
    seen: set[int] = set()
    for member in scanned.members:
        user_id = int(member.user_id)
        if user_id in seen:
            continue
        seen.add(user_id)
        reason = cleanup_reason(
            user_id=user_id,
            is_bot=member.is_bot,
            deleted=member.deleted,
            presence=member.presence,
            was_online=member.was_online,
            protected_ids=protected,
            now=now,
        )
        if reason:
            targets.append((user_id, reason))
    stats.checked = len(seen)

    for index, (user_id, reason) in enumerate(targets):
        removed = await _kick(bot, chat_id, user_id)
        if removed:
            if reason == REASON_DELETED:
                stats.deleted += 1
            elif is_stale_reason(reason):
                stats.stale += 1
            removed_total = stats.stale + stats.deleted
            if removed_total and removed_total % 100 == 0:
                logger.info(
                    "cleanup progress chat=%s stale=%s deleted=%s",
                    chat_id,
                    stats.stale,
                    stats.deleted,
                )
            try:
                await forget_member(chat_id, user_id)
            except Exception:
                logger.warning(
                    "cleanup forget failed chat=%s user=%s",
                    chat_id,
                    user_id,
                    exc_info=True,
                )
        if index + 1 < len(targets):
            await asyncio.sleep(KICK_PAUSE_SEC)

    logger.info(
        "cleanup done chat=%s checked=%s stale=%s deleted=%s",
        chat_id,
        stats.checked,
        stats.stale,
        stats.deleted,
    )
    return stats


async def _notify_reports(bot: object, stats: CleanupStats) -> None:
    if not stats.report:
        return
    gid = reports_group_id()
    if not gid:
        return
    text = (
        f"<b>Авточистка focus-чата</b>: давно {stats.stale}, удалённые {stats.deleted}"
    )
    try:
        await bot.send_message(  # type: ignore[attr-defined]
            chat_id=gid,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning("cleanup report failed chat=%s", gid, exc_info=True)


async def _reply(bot: object, chat_id: int | None, text: str) -> None:
    if not chat_id or not text:
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text)  # type: ignore[attr-defined]
    except Exception:
        logger.warning("cleanup reply failed chat=%s", chat_id, exc_info=True)


async def _guarded(bot: object, reply_chat_id: int | None) -> None:
    global _active
    try:
        stats = await execute_cleanup(bot)
        await _notify_reports(bot, stats)
        if reply_chat_id:
            if stats.error:
                await _reply(bot, reply_chat_id, stats.error)
            elif stats.skipped:
                await _reply(bot, reply_chat_id, _SKIP_TEXT.get(stats.skipped, ""))
            elif stats.report:
                await _reply(bot, reply_chat_id, summary_line(stats.stale, stats.deleted))
    except Exception:
        logger.exception("cleanup failed")
        await _reply(bot, reply_chat_id, _SKIP_TEXT["members"])
    finally:
        async with _lock:
            _active = False


async def start_cleanup(bot: object, *, reply_chat_id: int | None = None) -> str:
    global _active
    async with _lock:
        if _active:
            return "busy"
        _active = True
    asyncio.create_task(_guarded(bot, reply_chat_id), name="focusclear-cleanup")
    return "started"


async def cleanup_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    if int(community_chat_id() or 0) == 0:
        logger.info("cleanup skipped: no community chat")
        return
    if not scan_ready():
        logger.info("cleanup skipped: session not configured")
        return
    state = await start_cleanup(context.bot)
    if state == "busy":
        logger.info("cleanup skipped: already running")


async def _chat_status(bot: object, chat_id: int, user_id: int) -> str | None:
    try:
        member = await bot.get_chat_member(chat_id, user_id)  # type: ignore[attr-defined]
    except Exception:
        logger.warning(
            "cleanup admin check failed chat=%s user=%s",
            chat_id,
            user_id,
            exc_info=True,
        )
        return None
    return str(getattr(member, "status", "") or "")


async def clean_command(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message  # type: ignore[attr-defined]
    chat = update.effective_chat  # type: ignore[attr-defined]
    user = update.effective_user  # type: ignore[attr-defined]
    if message is None or chat is None or user is None:
        return
    if str(getattr(chat, "type", "") or "") not in _GROUP_TYPES:
        return
    chat_id = int(chat.id)
    if not is_community_chat(chat_id):
        await message.reply_text("Эта команда только в focus-чате.")
        return
    user_id = int(user.id)
    status: str | None = None
    if user_id != CALL_ALLOW_USER_ID:
        status = await _chat_status(context.bot, chat_id, user_id)
    if not user_may_call(user_id, status):
        await message.reply_text("Команда только для админа чата.")
        return
    if not scan_ready():
        await message.reply_text("Список участников не настроен.")
        return
    state = await start_cleanup(context.bot, reply_chat_id=chat_id)
    if state == "busy":
        await message.reply_text("Чистка уже идёт.")
        return
    await message.reply_text("Чистка запущена.")


def register_group_cleanup_handlers(app: Application) -> None:
    app.add_handler(
        CommandHandler("clean", clean_command, filters=filters.ChatType.GROUPS),
        group=-1,
    )
    queue = app.job_queue
    if queue is None:
        logger.warning("cleanup job queue missing")
        return
    queue.run_repeating(
        cleanup_daily,
        interval=CLEAN_INTERVAL_SEC,
        first=CLEAN_INTERVAL_SEC,
        name="focusclear_cleanup",
    )
