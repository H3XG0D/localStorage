"""Strict synthetic Telegram adapter for staging Casino E2E tests.

The adapter records only fixture traffic and deliberately has no Telegram SDK dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


FIXTURE_GAME_CHAT_ID = -1001234567890
FIXTURE_USER_IDS = frozenset({100000001, 100000002, 100000003})
_ALLOWED_CHAT_IDS = FIXTURE_USER_IDS | {FIXTURE_GAME_CHAT_ID}


@dataclass(frozen=True)
class RecordedCall:
    method: str
    chat_id: int | None
    payload: dict[str, Any]


class SyntheticTelegramAdapter:
    """Duck-typed bot used only by PvP and recovery staging integration tests."""

    def __init__(
        self,
        *,
        fail_next_publication: bool = False,
        fail_next_send: bool = False,
    ) -> None:
        self.fail_next_publication = fail_next_publication
        self.fail_next_send = fail_next_send
        self.calls: list[RecordedCall] = []
        self._next_message_id = 1

    @staticmethod
    def _require_chat_id(chat_id: Any) -> int:
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            raise ValueError("synthetic Telegram adapter requires an integer fixture chat ID")
        if chat_id not in _ALLOWED_CHAT_IDS:
            raise ValueError("synthetic Telegram adapter rejected a non-fixture chat ID")
        return chat_id

    @staticmethod
    def _require_user_id(user_id: Any) -> int:
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise ValueError("synthetic Telegram adapter requires an integer fixture user ID")
        if user_id not in FIXTURE_USER_IDS:
            raise ValueError("synthetic Telegram adapter rejected a non-fixture user ID")
        return user_id

    def _record(self, method: str, chat_id: int | None, **payload: Any) -> None:
        self.calls.append(RecordedCall(method=method, chat_id=chat_id, payload=payload))

    async def send_message(self, chat_id: Any, text: str, **kwargs: Any) -> SimpleNamespace:
        checked_chat_id = self._require_chat_id(chat_id)
        if self.fail_next_send:
            self.fail_next_send = False
            raise RuntimeError("synthetic message delivery failure")
        if self.fail_next_publication and checked_chat_id == FIXTURE_GAME_CHAT_ID:
            self.fail_next_publication = False
            raise RuntimeError("synthetic card publication failure")
        message_id = self._next_message_id
        self._next_message_id += 1
        self._record("send_message", checked_chat_id, text=text, **kwargs)
        return SimpleNamespace(message_id=message_id, chat=SimpleNamespace(id=checked_chat_id))

    async def reply_to(self, message: Any, text: str, **kwargs: Any) -> SimpleNamespace:
        chat_id = self._require_chat_id(message.chat.id)
        message_id = self._next_message_id
        self._next_message_id += 1
        self._record("reply_to", chat_id, text=text, reply_to_message_id=message.message_id, **kwargs)
        return SimpleNamespace(message_id=message_id, chat=SimpleNamespace(id=chat_id))

    async def delete_message(self, chat_id: Any, message_id: Any, **kwargs: Any) -> bool:
        checked_chat_id = self._require_chat_id(chat_id)
        self._record("delete_message", checked_chat_id, message_id=message_id, **kwargs)
        return True

    async def edit_message_reply_markup(self, chat_id: Any, message_id: Any, **kwargs: Any) -> bool:
        checked_chat_id = self._require_chat_id(chat_id)
        self._record("edit_message_reply_markup", checked_chat_id, message_id=message_id, **kwargs)
        return True

    async def edit_message_text(self, text: str, *, chat_id: Any, message_id: Any, **kwargs: Any) -> bool:
        checked_chat_id = self._require_chat_id(chat_id)
        self._record("edit_message_text", checked_chat_id, text=text, message_id=message_id, **kwargs)
        return True

    async def answer_callback_query(self, callback_query_id: Any, text: str | None = None, **kwargs: Any) -> bool:
        self._record("answer_callback_query", None, callback_query_id=callback_query_id, text=text, **kwargs)
        return True

    async def send_dice(self, *, chat_id: Any, emoji: str, **kwargs: Any) -> SimpleNamespace:
        checked_chat_id = self._require_chat_id(chat_id)
        message_id = self._next_message_id
        self._next_message_id += 1
        self._record("send_dice", checked_chat_id, emoji=emoji, **kwargs)
        return SimpleNamespace(message_id=message_id, dice=SimpleNamespace(value=1))

    def assert_fixture_user(self, user_id: Any) -> int:
        return self._require_user_id(user_id)
