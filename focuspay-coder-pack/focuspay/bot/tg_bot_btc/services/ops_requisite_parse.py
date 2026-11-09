"""Разбор операторской команды «сбп 5400». Копия правил бота внештатников."""
from __future__ import annotations

import re
from typing import Any

from services.reki_snapshot import SUB_TOKEN_CARD, SUB_TOKEN_SBP

_REQ_RE = re.compile(
    r"^\s*(сбп|карта|sbp|card|c2c)\s+([0-9][0-9\s.,]*)\s*$",
    re.IGNORECASE,
)

_CARD_WORDS = ("карта", "card", "c2c")


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
    sub_token = SUB_TOKEN_CARD if method in _CARD_WORDS else SUB_TOKEN_SBP
    return {"amount_rub": amount, "sub_token": sub_token}
