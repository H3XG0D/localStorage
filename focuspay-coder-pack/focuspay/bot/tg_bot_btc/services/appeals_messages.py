"""Разбор сообщений Appeals Payfast в группе споров."""
from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_ORDER_ID_LINE_RE = re.compile(
    r"ID\s+заявки\s*:\s*(\S+)",
    re.IGNORECASE,
)
_CLIENT_ORDER_ID_LINE_RE = re.compile(
    r"Ваш\s+id\s+заявки\s*:\s*(\S+)",
    re.IGNORECASE,
)


def _extract_appeals_order_ref(raw: str) -> str | None:
    """Payfast uuid или наш order_id из текста appeals."""
    client_line = _CLIENT_ORDER_ID_LINE_RE.search(raw)
    if client_line:
        return client_line.group(1).strip().rstrip(".,;")

    line = _ORDER_ID_LINE_RE.search(raw)
    if line:
        return line.group(1).strip().rstrip(".,;")

    uuid = _UUID_RE.search(raw)
    if uuid:
        return uuid.group(0)

    return None


def parse_appeals_success_receipt_request(text: str) -> str | None:
    """Редкий кейс: в PDF статус «ожидается» — Payfast просит чек в успешном статусе."""
    raw = (text or "").strip()
    if not raw:
        return None

    lower = raw.lower()
    waiting_success_receipt = (
        ("ждем чек" in lower or "ждём чек" in lower)
        and "успешном статусе" in lower
    )
    if not waiting_success_receipt:
        return None

    return _extract_appeals_order_ref(raw)


def parse_appeals_video_request(text: str) -> str | None:
    """ID заявки (uuid Payfast или наш order_id), если appeals просит видео после отказа PDF."""
    raw = (text or "").strip()
    if not raw:
        return None

    lower = raw.lower()
    pdf_failed = (
        "проверка pdf не пройдена" in lower
        or ("pdf" in lower and "не пройден" in lower)
    )
    wants_video = (
        "видео подтвержден" in lower
        or "запросить у клиента видео" in lower
        or ("запросить у клиента" in lower and "видео" in lower)
    )
    if not (pdf_failed and wants_video):
        return None

    return _extract_appeals_order_ref(raw)


def parse_reki_pdf_failed(text: str) -> tuple[str | None, str | None] | None:
    """(uuid Payfast, «ваш id») если реки просит видео после отказа PDF.

    None — это не тот шаблон. UUID берём со строки «ID заявки», не с «Ваш id».
    """
    raw = (text or "").strip()
    if not raw:
        return None

    lower = raw.lower()
    pdf_failed = (
        "проверка pdf не пройдена" in lower
        or ("pdf" in lower and "не пройден" in lower)
    )
    wants_video = (
        "видео подтвержден" in lower
        or "запросить у клиента видео" in lower
        or ("запросить у клиента" in lower and "видео" in lower)
    )
    if not (pdf_failed and wants_video):
        return None

    client_ref = None
    client_line = _CLIENT_ORDER_ID_LINE_RE.search(raw)
    if client_line:
        client_ref = client_line.group(1).strip().rstrip(".,;") or None

    payfast_id = None
    for line in raw.splitlines():
        if re.search(r"ваш\s+id\s+заявки", line, re.IGNORECASE):
            continue
        if not re.search(r"\bid\s+заявки\b", line, re.IGNORECASE):
            continue
        found = _UUID_RE.search(line)
        if found:
            payfast_id = found.group(0).lower()
            break

    if not payfast_id and not client_ref:
        return None
    return payfast_id, client_ref
