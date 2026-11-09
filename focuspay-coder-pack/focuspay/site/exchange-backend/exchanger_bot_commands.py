"""Чистые функции бота внештатника: парсинг команд и маска токена."""
from __future__ import annotations

import re
from typing import Any

_REQ_RE = re.compile(
    r"^\s*(сбп|карта|sbp|card|c2c)\s+([0-9][0-9\s.,]*)\s*$",
    re.IGNORECASE,
)
_ADD_RE = re.compile(r"^/add(?:@\w+)?\s+(-?\d{5,})(?:\s+(.+))?\s*$", re.IGNORECASE)
_KICK_RE = re.compile(r"^/kick(?:@\w+)?\s+(-?\d{5,})\s*$", re.IGNORECASE)


def mask_bot_token(token: str | None) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if ":" not in raw or len(raw) < 12:
        return "••••"
    prefix, secret = raw.split(":", 1)
    tail = secret[-4:] if len(secret) >= 4 else secret
    return f"{prefix}:…{tail}"


def parse_requisite_command(text: str) -> dict[str, Any] | None:
    """«сбп 5400» / «карта 12000» → amount_rub + sub_token. Иначе None."""
    match = _REQ_RE.match(text or "")
    if not match:
        return None
    method = match.group(1).lower()
    raw_amount = match.group(2).replace(" ", "").replace(",", ".")
    try:
        amount = float(raw_amount)
    except ValueError:
        return None
    if amount <= 0:
        return None
    sub_token = "CARDRUB" if method in ("карта", "card", "c2c") else "SBPRUB"
    return {"amount_rub": amount, "sub_token": sub_token}


def parse_add_command(text: str) -> tuple[int, str | None] | None:
    match = _ADD_RE.match(text or "")
    if not match:
        return None
    label = (match.group(2) or "").strip() or None
    return int(match.group(1)), label


def parse_kick_command(text: str) -> int | None:
    match = _KICK_RE.match(text or "")
    if not match:
        return None
    return int(match.group(1))


def is_balance_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in ("баланс", "balance", "/balance", "/баланс")


def is_paid_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in ("оплатил", "оплачено", "paid", "/paid")


def is_who_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.split("@", 1)[0] in ("/who", "кто", "who")


def is_reki_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.split("@", 1)[0] in ("/reki", "реки", "реквизиты", "/reqs")
