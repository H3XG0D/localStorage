"""Список участников focus-чата через пользовательский аккаунт.

Bot API не отдаёт last seen. Аккаунт должен состоять в чате.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from services.chat_cleanup import describe_presence

logger = logging.getLogger("chat_members_scan")


class MemberScanError(Exception):
    pass


class MemberScanNotConfigured(MemberScanError):
    pass


class MemberScanUnavailable(MemberScanError):
    pass


@dataclass(frozen=True)
class ScannedMember:
    user_id: int
    is_bot: bool = False
    deleted: bool = False
    presence: str | None = None
    was_online: datetime | None = None


@dataclass(frozen=True)
class ChatMemberScan:
    scanner_id: int
    members: tuple[ScannedMember, ...]


def session_path() -> Path:
    raw = os.environ.get("FOCUSCLEAR_USER_SESSION", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "focusclear_user.session"


def api_credentials() -> tuple[int, str] | None:
    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id_raw or not api_hash:
        return None
    try:
        api_id = int(api_id_raw)
    except ValueError:
        return None
    if api_id <= 0:
        return None
    return api_id, api_hash


def scan_ready() -> bool:
    if api_credentials() is None:
        return False
    path = session_path()
    return path.is_file() and path.stat().st_size > 0


def _client_session_name(path: Path) -> str:
    """Telethon сам дописывает .session, если его нет в имени."""
    name = str(path)
    if name.endswith(".session"):
        return name[: -len(".session")]
    return name


async def _resolve_entity(client: object, chat_id: int) -> object:
    from telethon.tl.types import PeerChannel

    wanted = int(chat_id)
    try:
        return await client.get_entity(wanted)  # type: ignore[attr-defined]
    except Exception:
        logger.info("cleanup entity cache miss chat=%s", wanted)

    raw = str(wanted)
    if raw.startswith("-100"):
        try:
            return await client.get_entity(PeerChannel(int(raw[4:])))  # type: ignore[attr-defined]
        except Exception:
            logger.info("cleanup peer miss chat=%s", wanted)

    async for dialog in client.iter_dialogs():  # type: ignore[attr-defined]
        if int(getattr(dialog, "id", 0) or 0) == wanted:
            entity = getattr(dialog, "entity", None)
            if entity is not None:
                return entity
    raise MemberScanUnavailable(str(wanted))


async def scan_chat_members(chat_id: int) -> ChatMemberScan:
    creds = api_credentials()
    if creds is None or not scan_ready():
        raise MemberScanNotConfigured("session")
    from telethon import TelegramClient

    api_id, api_hash = creds
    client = TelegramClient(
        _client_session_name(session_path()),
        api_id,
        api_hash,
        flood_sleep_threshold=120,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise MemberScanNotConfigured("session")
        me = await client.get_me()
        scanner_id = int(getattr(me, "id", 0) or 0)
        entity = await _resolve_entity(client, int(chat_id))
        found: list[ScannedMember] = []
        async for user in client.iter_participants(entity, aggressive=True):
            user_id = getattr(user, "id", None)
            if not isinstance(user_id, int) or user_id <= 0:
                continue
            presence, was_online = describe_presence(getattr(user, "status", None))
            found.append(
                ScannedMember(
                    user_id=user_id,
                    is_bot=bool(getattr(user, "bot", False)),
                    deleted=bool(getattr(user, "deleted", False)),
                    presence=presence,
                    was_online=was_online,
                )
            )
        logger.info(
            "cleanup scan chat=%s members=%s scanner=%s",
            chat_id,
            len(found),
            scanner_id,
        )
        return ChatMemberScan(scanner_id=scanner_id, members=tuple(found))
    finally:
        await client.disconnect()
