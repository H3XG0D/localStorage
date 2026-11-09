"""Парсинг суммы и валюты комиссии со свапа из текста сообщения."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_CURRENCY_ALIASES: dict[str, str] = {
    "usdt": "usdt",
    "юсдт": "usdt",
    "usd": "usdt",
    "btc": "btc",
    "биткоин": "btc",
    "биток": "btc",
    "ltc": "ltc",
    "лайткоин": "ltc",
    "trx": "trx",
    "трон": "trx",
    "rub": "rub",
    "руб": "rub",
    "руб.": "rub",
    "рублей": "rub",
    "₽": "rub",
}

# 10trx · 2 usdt · 0.00024btc · 150 ₽
_PATTERN = re.compile(
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<cur>[a-zA-Zа-яёА-ЯЁ₽]+)",
    re.UNICODE,
)


@dataclass(frozen=True)
class ParsedSwapCommission:
    crypto: str
    crypto_amount: Decimal
    raw_match: str


def _normalize_currency(token: str) -> str | None:
    key = (token or "").strip().lower().replace("ё", "е")
    return _CURRENCY_ALIASES.get(key)


def parse_swap_commission_parts(text: str) -> list[ParsedSwapCommission]:
    if not text or not text.strip():
        return []
    out: list[ParsedSwapCommission] = []
    seen: set[tuple[str, str]] = set()
    for match in _PATTERN.finditer(text):
        cur = _normalize_currency(match.group("cur"))
        if not cur:
            continue
        raw_amount = match.group("amount").replace(",", ".")
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            continue
        if amount <= 0:
            continue
        key = (cur, str(amount))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ParsedSwapCommission(
                crypto=cur,
                crypto_amount=amount,
                raw_match=match.group(0),
            )
        )
    return out


def parse_swap_commission_text(text: str) -> ParsedSwapCommission | None:
    parts = parse_swap_commission_parts(text)
    return parts[0] if parts else None
