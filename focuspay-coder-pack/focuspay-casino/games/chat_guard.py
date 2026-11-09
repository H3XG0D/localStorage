"""Fail-closed authorization for starting casino games in Telegram chats."""
from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from focuspay_client import FocusPayClient

from games.chat_reaper import TTL_SERVICE, reply_ephemeral, try_delete_user_message

logger = logging.getLogger(__name__)

GAME_CHAT_REQUIRED_MESSAGE = (
    "Игры доступны только в подтверждённом игровом чате FocusCasino."
)


def _field(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def parse_telegram_chat_id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def chat_id_from(chat: Any) -> int | None:
    return parse_telegram_chat_id(_field(chat, "id"))


def telegram_user_id(user: Any) -> int | None:
    return parse_telegram_chat_id(_field(user, "id"))


def chat_id_aliases(chat_id: int) -> set[int]:
    """A basic group `-X` and its migrated supergroup `-100X` are the same chat."""
    aliases = {chat_id}
    if chat_id >= 0:
        return aliases
    digits = str(abs(chat_id))
    if digits.startswith("100") and len(digits) > 3:
        rest = digits[3:].lstrip("0") or "0"
        aliases.add(-int(rest))
    else:
        aliases.add(-int(f"100{digits}"))
    return aliases


def _chat_from_callback_json(call: Any) -> Any:
    raw = _field(call, "json") or _field(call, "json_string")
    if isinstance(raw, str):
        with contextlib.suppress(Exception):
            raw = json.loads(raw)
    if not isinstance(raw, dict):
        return None
    return _field(_field(raw, "message"), "chat")


def message_chat(message: Any) -> Any:
    return _field(message, "chat")


def callback_chat(call: Any) -> Any:
    message = _field(call, "message")
    chat = message_chat(message)
    if chat is not None:
        return chat
    return _chat_from_callback_json(call)


class ActiveGameChatGuard:
    """Authorize game-entry actions against the backend's current chat binding.

    The active binding is deliberately checked for every entry action instead of
    cached at bot startup: an administrator can revoke or replace it at any time.
    API failures deny access so an unavailable binding service never opens games.
    """

    def __init__(self, client: FocusPayClient):
        self._client = client

    async def allows_chat(self, chat_id: Any) -> bool:
        parsed = parse_telegram_chat_id(chat_id)
        if parsed is None:
            return False
        try:
            binding = await self._client.get_active_game_chat_binding()
        except Exception:
            logger.exception("Unable to verify active game chat binding")
            return False
        if binding is None:
            return False
        bound = parse_telegram_chat_id(_field(binding, "chat_id"))
        if bound is None:
            return False
        return bool(chat_id_aliases(parsed) & chat_id_aliases(bound))

    @staticmethod
    def is_private_owner_chat(chat: Any, user: Any) -> bool:
        """A player's own DM with the bot is a valid game-entry surface."""
        chat_id = chat_id_from(chat)
        user_id = telegram_user_id(user)
        return (
            str(_field(chat, "type") or "") == "private"
            and chat_id is not None
            and user_id is not None
            and user_id > 0
            and chat_id == user_id
        )

    async def allows_entry(self, chat: Any, user: Any) -> bool:
        if chat is None:
            return False
        if self.is_private_owner_chat(chat, user):
            return True
        return await self.allows_chat(chat_id_from(chat))

    async def require_message(self, bot: Any, message: Any, *, notify: bool = True) -> bool:
        """Allow a command or next-step message in the active game chat or the player's DM."""
        chat = message_chat(message)
        user = _field(message, "from_user") or _field(message, "from")
        if await self.allows_entry(chat, user):
            return True
        if notify:
            await reply_ephemeral(bot, message, GAME_CHAT_REQUIRED_MESSAGE, TTL_SERVICE)
            await try_delete_user_message(bot, message)
        return False

    async def require_callback(self, bot: Any, call: Any) -> bool:
        """Allow a game-entry callback from the active chat or the player's DM."""
        chat = callback_chat(call)
        user = _field(call, "from_user") or _field(call, "from")
        if await self.allows_entry(chat, user):
            return True
        logger.warning(
            "game-chat callback denied chat_id=%r",
            chat_id_from(chat),
        )
        await bot.answer_callback_query(
            _field(call, "id"),
            GAME_CHAT_REQUIRED_MESSAGE,
            show_alert=True,
        )
        return False
