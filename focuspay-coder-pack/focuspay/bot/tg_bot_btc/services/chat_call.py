"""Сборка сообщений /spam: цитата и скрытые упоминания под смайликами."""
from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Sequence

# Только /spam. В TELEGRAM_ADMIN_IDS обменника этот id не входит.
CALL_ALLOW_USER_ID = 8854187047
BATCH_SIZE = 6
SEND_INTERVAL_SEC = 1.0
QUOTE_MAX_LEN = 1000

# Один кодпоинт вне BMP: длина в UTF-16 равна 2, как ждёт Bot API.
MASK_EMOJI: tuple[str, ...] = (
    "😀",
    "😎",
    "🤖",
    "🎉",
    "🔥",
    "💎",
    "🎯",
    "🎲",
    "🍀",
    "🌙",
    "👀",
    "🚀",
)

_ADMIN_STATUSES = frozenset({"creator", "administrator"})
_COMMAND_RE = re.compile(r"^/spam(?:@[A-Za-z0-9_]+)?(?:\s+|$)", re.IGNORECASE)


@dataclass(frozen=True)
class CallUser:
    user_id: int
    first_name: str = ""
    username: str = ""
    is_bot: bool = False
    deleted: bool = False


@dataclass(frozen=True)
class Mention:
    offset: int
    length: int
    user_id: int
    first_name: str
    username: str = ""


@dataclass(frozen=True)
class CallMessage:
    text: str
    mentions: tuple[Mention, ...]


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def is_call_command(text: str | None) -> bool:
    return bool(_COMMAND_RE.match(text or ""))


def quote_from_command(text: str | None) -> str:
    raw = text or ""
    match = _COMMAND_RE.match(raw)
    if match is None:
        return ""
    return raw[match.end() :].strip()


def user_may_call(user_id: int, chat_status: str | None) -> bool:
    if int(user_id) == CALL_ALLOW_USER_ID:
        return True
    return (chat_status or "") in _ADMIN_STATUSES


def _mention_name(first_name: str) -> str:
    name = " ".join((first_name or "").split())
    if not name:
        return "user"
    return name[:64]


def eligible_users(users: Sequence[CallUser]) -> list[CallUser]:
    seen: set[int] = set()
    picked: list[CallUser] = []
    for user in users:
        if user.is_bot or user.deleted:
            continue
        user_id = int(user.user_id)
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        picked.append(user)
    return picked


def build_call_messages(
    quote: str,
    users: Sequence[CallUser],
    *,
    batch_size: int = BATCH_SIZE,
) -> list[CallMessage]:
    """Пачки с одной и той же цитатой. Пустая цитата или никого — пустой список."""
    text_quote = (quote or "").strip()
    if not text_quote:
        return []
    if batch_size < 1:
        raise ValueError("batch_size")
    people = eligible_users(users)
    messages: list[CallMessage] = []
    for start in range(0, len(people), batch_size):
        chunk = people[start : start + batch_size]
        masks = [MASK_EMOJI[index % len(MASK_EMOJI)] for index in range(len(chunk))]
        body = f"{text_quote}\n{''.join(masks)}"
        offset = utf16_len(text_quote + "\n")
        mentions: list[Mention] = []
        for mask, user in zip(masks, chunk):
            length = utf16_len(mask)
            mentions.append(
                Mention(
                    offset=offset,
                    length=length,
                    user_id=int(user.user_id),
                    first_name=_mention_name(user.first_name),
                    username=(user.username or "").strip().lstrip("@"),
                )
            )
            offset += length
        messages.append(CallMessage(text=body, mentions=tuple(mentions)))
    return messages
