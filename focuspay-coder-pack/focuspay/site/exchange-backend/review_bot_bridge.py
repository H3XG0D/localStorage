"""Bridge к логике модерации отзывов из tg_bot_btc."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("review_bot_bridge")

_bridge_ready = False


def _ensure_bot_path() -> None:
    configured_root = os.environ.get("TG_BOT_PATH")
    bot_root = Path(configured_root) if configured_root else Path(__file__).resolve().parents[2] / "bot" / "tg_bot_btc"
    if not bot_root.is_dir():
        bot_root = Path("/opt/tg_bot_btc")
    bot_root_str = str(bot_root)
    if bot_root_str not in sys.path:
        sys.path.append(bot_root_str)


async def init_review_bot_bridge(dsn: str) -> bool:
    global _bridge_ready
    if _bridge_ready:
        return True
    _ensure_bot_path()
    try:
        from bot_status_bridge import init_bot_status_bridge

        ok = await init_bot_status_bridge(dsn)
        _bridge_ready = ok
        if ok:
            logger.info("Review bot bridge ready")
        return ok
    except Exception as e:
        logger.warning("Review bot bridge unavailable: %s", e)
        return False


def _bot_module(name: str):
    _ensure_bot_path()
    import importlib

    return importlib.import_module(name)


async def send_moderation_via_bot(submission_id: int) -> None:
    """Post the ops-group card with the FocusPay bot (the bot that owns rev:* callbacks)."""
    if not _bridge_ready:
        raise RuntimeError("review_bot_bridge_unavailable")
    from telegram import Bot

    from config import settings

    moderation = _bot_module("services.review_moderation")
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    bot = Bot(token=token)
    try:
        await moderation.send_moderation_request(bot, int(submission_id))
    finally:
        await bot.shutdown()


async def publish_submission_via_bot(
    submission_id: int,
    *,
    bonus_rub: float,
    moderated_by: int,
):
    if not _bridge_ready:
        raise RuntimeError("review_bot_bridge_unavailable")
    from telegram import Bot

    from config import settings

    review_bonus = _bot_module("services.review_bonus")
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        raise RuntimeError("telegram_bot_token_missing")
    bot = Bot(token=token)
    try:
        return await review_bonus.publish_submission(
            bot,
            submission_id,
            bonus_rub=bonus_rub,
            moderated_by=moderated_by,
        )
    finally:
        await bot.shutdown()


async def reject_submission_via_bot(
    submission_id: int,
    *,
    moderated_by: int,
    reason: str | None = None,
):
    if not _bridge_ready:
        raise RuntimeError("review_bot_bridge_unavailable")
    review_bonus = _bot_module("services.review_bonus")
    return await review_bonus.reject_submission(
        submission_id,
        moderated_by=moderated_by,
        reason=reason,
    )


async def can_claim_review_bonus_today(user_id: int) -> bool:
    review_bonus = _bot_module("services.review_bonus")
    return await review_bonus.can_claim_review_bonus_today(user_id)


async def review_bonus_today_info(user_id: int) -> dict:
    review_bonus = _bot_module("services.review_bonus")
    return await review_bonus.review_bonus_today_info(user_id)


class ReviewBonusError(Exception):
    pass


def review_bonus_error_class():
    return _bot_module("services.review_bonus").ReviewBonusError
