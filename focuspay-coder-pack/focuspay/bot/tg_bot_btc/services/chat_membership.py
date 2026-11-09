"""Проверка, состоит ли покупатель в публичных чатах FocusPay."""
from __future__ import annotations

import logging
from typing import Literal

from telegram import Bot
from telegram.error import BadRequest, Forbidden

logger = logging.getLogger("chat_membership")

MembershipStatus = Literal["in", "out", "unconfigured", "unknown"]

_IN = frozenset({"creator", "administrator", "member", "restricted"})
_OUT = frozenset({"left", "kicked"})
_OUT_ERRORS = (
    "user not found",
    "user_not_participant",
    "member not found",
    "participant_id_invalid",
    "chat_member not found",
)

MEMBERSHIP_CHATS: tuple[tuple[str, str], ...] = (
    ("community", "Focus-чат"),
    ("reviews", "Отзывы"),
    ("news", "Новости"),
)


def _is_out_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _OUT_ERRORS)


async def user_in_chat(
    bot: Bot | None,
    chat_id: int | str | None,
    user_id: int,
) -> MembershipStatus:
    """in / out / unconfigured / unknown (ошибка API)."""
    if not chat_id or chat_id == 0 or chat_id == "0":
        return "unconfigured"
    if bot is None or int(user_id) <= 0:
        return "unknown"
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=int(user_id))
        status = str(getattr(member, "status", "") or "").lower()
        if status in _IN:
            return "in"
        if status in _OUT:
            return "out"
        return "unknown"
    except (BadRequest, Forbidden) as e:
        if _is_out_error(e):
            return "out"
        logger.debug(
            "get_chat_member failed chat=%s user=%s: %s",
            chat_id,
            user_id,
            e,
        )
        return "unknown"
    except Exception as e:
        logger.debug(
            "get_chat_member failed chat=%s user=%s: %s",
            chat_id,
            user_id,
            type(e).__name__,
        )
        return "unknown"


async def public_chat_membership(
    bot: Bot | None,
    user_id: int,
) -> dict[str, MembershipStatus]:
    """Членство в focus-чате, отзывах и новостях."""
    from services.config_rates import community_chat_id, news_chat_id, reviews_chat_id

    targets: dict[str, int | str] = {
        "community": community_chat_id(),
        "reviews": reviews_chat_id(),
        "news": news_chat_id(),
    }
    result: dict[str, MembershipStatus] = {}
    for key, gid in targets.items():
        result[key] = await user_in_chat(bot, gid, user_id)
    return result


def format_membership_checklist_lines(
    membership: dict[str, MembershipStatus] | None,
) -> list[str]:
    if not membership:
        return []
    in_label = {
        "community": "в группе",
        "reviews": "подписан",
        "news": "в чате",
    }
    lines: list[str] = []
    for key, title in MEMBERSHIP_CHATS:
        status = membership.get(key) or "unknown"
        if status == "in":
            lines.append(f"✅ {title}: {in_label.get(key, 'да')}")
        elif status == "out":
            lines.append(f"❌ {title}: нет")
        elif status == "unconfigured":
            lines.append(f"❔ {title}: чат не привязан")
        else:
            lines.append(f"❔ {title}: неизвестно")
    return lines
