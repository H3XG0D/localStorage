"""C2C vs SBP channel helpers for trader cards."""
from __future__ import annotations

import re

from fastapi import HTTPException

from app.models import PaymentChannel, TraderCard


_PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
_CARD_DIGITS_RE = re.compile(r"^[0-9]{12,19}$")


def parse_channel(raw: str | None) -> PaymentChannel:
    value = (raw or PaymentChannel.c2c.value).strip().lower()
    try:
        return PaymentChannel(value)
    except ValueError as e:
        raise HTTPException(400, f"Invalid channel: {raw}. Use c2c or sbp") from e


def normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = re.sub(r"[\s\-()]", "", raw.strip())
    if not cleaned:
        return None
    if cleaned.startswith("8") and len(cleaned) == 11:
        cleaned = "+7" + cleaned[1:]
    elif cleaned.startswith("7") and len(cleaned) == 11 and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    if not _PHONE_RE.match(cleaned):
        raise HTTPException(400, "Invalid SBP phone (use +7XXXXXXXXXX)")
    return cleaned


def normalize_card_number(raw: str | None) -> str | None:
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw.strip())
    if not digits:
        return None
    if not _CARD_DIGITS_RE.match(digits):
        raise HTTPException(400, "Invalid card number (12–19 digits)")
    return digits


def session_display_name(card: TraderCard) -> str:
    channel = parse_channel(card.channel)
    if channel == PaymentChannel.sbp:
        parts = ["СБП", card.phone or "", card.recipient_name or card.name]
        return " · ".join(p for p in parts if p)
    mask = card.card_number or (f"•••• {card.last4}" if card.last4 else "")
    parts = ["C2C", card.bank or "", mask or card.name]
    return " · ".join(p for p in parts if p)


def assert_channel_ready_for_online(card: TraderCard) -> None:
    channel = parse_channel(card.channel)
    if channel == PaymentChannel.sbp:
        if not card.phone:
            raise HTTPException(400, "SBP requires phone number")
        if not (card.recipient_name and card.recipient_name.strip()):
            raise HTTPException(400, "SBP requires recipient name (ФИО)")
        return
    # c2c — card number preferred; last4 alone is acceptable for lab/legacy
    if not card.card_number and not card.last4:
        raise HTTPException(400, "C2C requires card number")
