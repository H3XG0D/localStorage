"""Telegram admin notifications — allowlist + safe summary only."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from privacy_redaction import pseudonym, redact_text
from sticker_ai.constants import UI_TASK_PATH_TMPL

logger = logging.getLogger("security.sticker_ai.notify")


@dataclass
class NotifyAllowlist:
    user_ids: frozenset[int] = field(default_factory=frozenset)
    chat_ids: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_csv(cls, users: str = "", chats: str = "") -> "NotifyAllowlist":
        def parse(raw: str) -> frozenset[int]:
            out: set[int] = set()
            for part in (raw or "").split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    out.add(int(part))
                except ValueError:
                    continue
            return frozenset(out)

        return cls(user_ids=parse(users), chat_ids=parse(chats))

    def allows_user(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        if not self.user_ids:
            return False  # fail closed
        return int(user_id) in self.user_ids

    def allows_chat(self, chat_id: int | None) -> bool:
        if chat_id is None:
            return False
        if not self.chat_ids:
            return False  # fail closed
        return int(chat_id) in self.chat_ids


def build_safe_summary(
    *,
    task_id: str,
    status: str,
    actor_type: str,
    actor_id: int,
    change_type: str,
) -> str:
    actor = pseudonym(actor_id, prefix=actor_type[:3] or "act")
    ui = UI_TASK_PATH_TMPL.format(task_id=task_id)
    # No tokens, .env, prompts, or logs.
    text = (
        f"Sticker AI\n"
        f"task={task_id}\n"
        f"status={status}\n"
        f"actor={actor}\n"
        f"change={change_type}\n"
        f"ui={ui}"
    )
    return redact_text(text, keep_short_ids=True)


SendFn = Callable[[int, str], Awaitable[None]]


@dataclass
class StickerNotifier:
    allowlist: NotifyAllowlist
    send: SendFn | None = None
    sent: list[tuple[int, str]] = field(default_factory=list)

    async def notify_admins(
        self,
        *,
        task_id: str,
        status: str,
        actor_type: str,
        actor_id: int,
        change_type: str,
        target_chat_id: int | None = None,
        target_user_id: int | None = None,
    ) -> bool:
        body = build_safe_summary(
            task_id=task_id,
            status=status,
            actor_type=actor_type,
            actor_id=actor_id,
            change_type=change_type,
        )
        targets: list[int] = []
        if target_chat_id is not None:
            if not self.allowlist.allows_chat(target_chat_id):
                logger.warning("sticker_notify_denied chat not in allowlist")
                return False
            targets.append(int(target_chat_id))
        elif target_user_id is not None:
            if not self.allowlist.allows_user(target_user_id):
                logger.warning("sticker_notify_denied user not in allowlist")
                return False
            targets.append(int(target_user_id))
        else:
            # Broadcast only to explicitly configured chats; fail closed if empty.
            if not self.allowlist.chat_ids:
                logger.warning("sticker_notify_fail_closed empty chat allowlist")
                return False
            targets.extend(sorted(self.allowlist.chat_ids))

        for tid in targets:
            self.sent.append((tid, body))
            if self.send:
                await self.send(tid, body)
        return True
