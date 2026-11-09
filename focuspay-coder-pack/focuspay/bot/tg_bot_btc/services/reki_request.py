"""Запросы к боту реквизитов с пользовательского аккаунта.

Bot API не умеет писать другому боту, поэтому и опрос /reki, и ручная выдача
реквизита оператору идут через одну Telethon-сессию. Сессия одна на процесс,
параллельные запросы к ней ломают файл — поэтому общий лок.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from services.chat_members_scan import api_credentials, session_path

logger = logging.getLogger("reki_request")

REPLY_TIMEOUT_SEC = 20
POLL_STEP_SEC = 1.0

_session_lock: asyncio.Lock | None = None


def session_lock() -> asyncio.Lock:
    """Один лок на процесс: Telethon-сессия не переживает параллельных клиентов."""
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


def reki_peer() -> str | int | None:
    raw = os.environ.get("REKI_BOT_PEER", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw.lstrip("@") or None


def reki_session_path() -> Path:
    raw = os.environ.get("REKI_USER_SESSION", "").strip()
    return Path(raw) if raw else session_path()


def request_ready() -> bool:
    if reki_peer() is None or api_credentials() is None:
        return False
    path = reki_session_path()
    return path.is_file() and path.stat().st_size > 0


@dataclass(frozen=True)
class RekiReply:
    """Ответ бота реквизитов: текст и id сообщения, на котором висит отмена."""

    text: str
    message_id: int


def _button_rows(message) -> list:
    return list(getattr(message, "buttons", None) or [])


def is_cancel_label(text: str | None) -> bool:
    return "отмен" in str(text or "").lower()


def message_has_cancel(message) -> bool:
    for row in _button_rows(message):
        for button in row or []:
            if is_cancel_label(getattr(button, "text", None)):
                return True
    return False


def cancel_message_id(messages, *, after_id: int) -> int | None:
    """Id входящего сообщения после нашей команды, если на нём есть «Отменить»."""
    for message in messages or []:
        message_id = int(getattr(message, "id", 0) or 0)
        if message_id <= int(after_id) or getattr(message, "out", False):
            continue
        if message_has_cancel(message):
            return message_id
    return None


async def click_cancel_button(message) -> bool:
    """Жмёт первую inline-кнопку с «Отменить». False — такой кнопки нет."""
    for row in _button_rows(message):
        for button in row or []:
            if not is_cancel_label(getattr(button, "text", None)):
                continue
            await button.click()
            return True
    return False


async def send_command_and_capture(
    command: str,
    *,
    match: str | None = None,
    timeout_sec: int = REPLY_TIMEOUT_SEC,
) -> RekiReply | None:
    """Шлёт команду и возвращает текст ответа вместе с id сообщения."""
    creds = api_credentials()
    peer = reki_peer()
    if creds is None or peer is None or not request_ready():
        return None

    from telethon import TelegramClient

    from services.chat_members_scan import _client_session_name

    api_id, api_hash = creds
    async with session_lock():
        client = TelegramClient(
            _client_session_name(reki_session_path()),
            api_id,
            api_hash,
            flood_sleep_threshold=120,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                logger.warning("reki request skipped: session is not authorized")
                return None
            entity = await client.get_entity(peer)
            sent = await client.send_message(entity, command)
            sent_id = int(getattr(sent, "id", 0) or 0)
            deadline = asyncio.get_event_loop().time() + max(1, int(timeout_sec))
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(POLL_STEP_SEC)
                messages = await client.get_messages(entity, limit=5)
                for message in messages:
                    message_id = int(getattr(message, "id", 0) or 0)
                    if message_id <= sent_id:
                        continue
                    if getattr(message, "out", False):
                        continue
                    text = getattr(message, "message", None) or getattr(message, "raw_text", None)
                    if not text:
                        continue
                    if match and match not in text:
                        continue
                    cancel_id = cancel_message_id(messages, after_id=sent_id)
                    return RekiReply(text=str(text), message_id=cancel_id or message_id)
            logger.warning("reki request %r: no reply within %ss", command, timeout_sec)
            return None
        finally:
            await client.disconnect()


async def send_command_and_wait(
    command: str,
    *,
    match: str | None = None,
    timeout_sec: int = REPLY_TIMEOUT_SEC,
) -> str | None:
    """Шлёт команду боту реквизитов и ждёт первый входящий ответ после неё."""
    reply = await send_command_and_capture(command, match=match, timeout_sec=timeout_sec)
    return None if reply is None else reply.text


async def cancel_reki_message(message_id: int) -> bool:
    """Жмёт «Отменить» на сообщении реки. False — кнопки нет или бот не ответил."""
    if not message_id:
        return False
    creds = api_credentials()
    peer = reki_peer()
    if creds is None or peer is None or not request_ready():
        return False

    from telethon import TelegramClient

    from services.chat_members_scan import _client_session_name

    api_id, api_hash = creds
    async with session_lock():
        client = TelegramClient(
            _client_session_name(reki_session_path()),
            api_id,
            api_hash,
            flood_sleep_threshold=120,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                logger.warning("reki cancel skipped: session is not authorized")
                return False
            entity = await client.get_entity(peer)
            message = await client.get_messages(entity, ids=int(message_id))
            if message is None:
                logger.warning("reki cancel: message %s is gone", message_id)
                return False
            clicked = await click_cancel_button(message)
            if not clicked:
                logger.warning("reki cancel: no cancel button message_id=%s", message_id)
            return clicked
        except Exception:
            logger.warning("reki cancel failed message_id=%s", message_id, exc_info=True)
            return False
        finally:
            await client.disconnect()


_CARD_RE = re.compile(r"\b(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{2,6})\b")
_PHONE_RE = re.compile(r"(\+?7[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})")
_AMOUNT_RE = re.compile(r"([\d\s.,]+)\s*(?:RUB|РУБ|₽)", re.IGNORECASE)
_BANK_RE = re.compile(r"(?:банк|bank)\s*:?\s*(.+)", re.IGNORECASE)
_HOLDER_RE = re.compile(r"(?:получатель|держатель|фио|holder)\s*:?\s*(.+)", re.IGNORECASE)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_YOUR_ORDER_ID_RE = re.compile(r"ваш\s+id\s+заявки", re.IGNORECASE)
_ORDER_ID_LINE_RE = re.compile(r"\bid\s+заявки\b", re.IGNORECASE)

_REFUSAL_MARKERS = (
    "нет свободных",
    "нет доступных",
    "недоступно",
    "попробуйте позже",
    "не найдено",
)


@dataclass(frozen=True)
class RekiIssued:
    """Реквизит, выданный ботом. raw хранится для разбора спорных случаев."""

    requisite: str
    method: str
    bank: str | None = None
    holder: str | None = None
    amount_rub: str | None = None
    raw: str = ""
    payfast_id: str | None = None
    message_id: int | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().strip("*_`").strip()
    return text or None


def looks_like_refusal(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _REFUSAL_MARKERS)


def payfast_id_from_issue(text: str) -> str | None:
    """UUID со строки «ID заявки». «Ваш id заявки» — это другой номер, его не берём."""
    for line in (text or "").splitlines():
        if _YOUR_ORDER_ID_RE.search(line):
            continue
        if not _ORDER_ID_LINE_RE.search(line):
            continue
        found = _UUID_RE.search(line)
        if found:
            return found.group(0).lower()
    return None


def parse_issued_requisite(text: str) -> RekiIssued | None:
    """Достаёт номер карты или телефон из ответа бота. None — выдачи нет."""
    if not text or looks_like_refusal(text):
        return None

    card = _CARD_RE.search(text)
    phone = None if card else _PHONE_RE.search(text)
    if card is None and phone is None:
        return None

    bank = _BANK_RE.search(text)
    holder = _HOLDER_RE.search(text)
    amount = _AMOUNT_RE.search(text)
    return RekiIssued(
        requisite=(card.group(1) if card else phone.group(1)).strip(),
        method="card" if card else "sbp",
        bank=_clean(bank.group(1)) if bank else None,
        holder=_clean(holder.group(1)) if holder else None,
        amount_rub=_clean(amount.group(1)) if amount else None,
        raw=text,
        payfast_id=payfast_id_from_issue(text),
    )


async def request_requisite(amount_rub, sub_token: str) -> RekiIssued | None:
    """Просит у бота реквизит той же командой, что шлют внештатники."""
    from services.reki_snapshot import SUB_TOKEN_CARD

    word = "карта" if (sub_token or "").upper() == SUB_TOKEN_CARD else "сбп"
    quote = int(round(float(amount_rub)))
    reply = await send_command_and_capture(f"{word} {quote}")
    if not reply:
        return None
    issued = parse_issued_requisite(reply.text)
    if issued is None:
        return None
    return RekiIssued(
        requisite=issued.requisite,
        method=issued.method,
        bank=issued.bank,
        holder=issued.holder,
        amount_rub=issued.amount_rub,
        raw=issued.raw,
        payfast_id=issued.payfast_id,
        message_id=reply.message_id,
    )


async def _with_reki_client(action):
    """Один заход в Telethon-сессию. FloodWait пробрасываем, остальное глушим."""
    creds = api_credentials()
    peer = reki_peer()
    if creds is None or peer is None or not request_ready():
        return None

    from telethon import TelegramClient

    from services.chat_members_scan import _client_session_name

    api_id, api_hash = creds
    async with session_lock():
        client = TelegramClient(
            _client_session_name(reki_session_path()),
            api_id,
            api_hash,
            flood_sleep_threshold=120,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                logger.warning("reki session is not authorized")
                return None
            entity = await client.get_entity(peer)
            return await action(client, entity)
        except Exception as exc:
            if type(exc).__name__ == "FloodWaitError":
                raise
            logger.warning("reki session call failed", exc_info=True)
            return None
        finally:
            await client.disconnect()


async def send_receipt_to_reki(payfast_id: str, file_path: str, *, video: bool) -> bool:
    """Сначала текст с UUID, следом файл. В наш PayFast API это не уходит."""
    uid = str(payfast_id or "").strip()
    if not _UUID_RE.fullmatch(uid):
        logger.warning("reki receipt skipped: bad payfast id")
        return False
    path = Path(file_path)
    if not path.is_file():
        logger.warning("reki receipt file missing path=%s", file_path)
        return False

    async def _send(client, entity):
        await client.send_message(entity, uid)
        await client.send_file(entity, str(path), force_document=not video)
        return True

    try:
        sent = await _with_reki_client(_send)
    except Exception:
        logger.warning("reki receipt send failed id=%s", uid, exc_info=True)
        return False
    return bool(sent)


async def fetch_recent_incoming_texts(*, limit: int = 20) -> list[tuple[int, str]]:
    """Последние входящие сообщения реки: (message_id, text)."""

    async def _read(client, entity):
        messages = await client.get_messages(entity, limit=max(1, int(limit)))
        found: list[tuple[int, str]] = []
        for message in messages or []:
            if getattr(message, "out", False):
                continue
            text = getattr(message, "message", None) or getattr(message, "raw_text", None)
            if not text:
                continue
            found.append((int(getattr(message, "id", 0) or 0), str(text)))
        return found

    rows = await _with_reki_client(_read)
    return list(rows or [])
