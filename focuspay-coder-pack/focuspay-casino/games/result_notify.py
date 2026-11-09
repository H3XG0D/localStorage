"""Personal bot-DM text after a game: you won/lost/tied, payout, balance."""
from __future__ import annotations

import html
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from games.catalog import GAMES_CONFIG, fmt_id

_HEADLINES = {
    "win": "Вы победили",
    "lose": "Вы проиграли",
    "tie": "Ничья",
    "cancel": "Игра отменена, ставка возвращена",
}


def _money(value: object) -> str:
    try:
        amount = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError):
        amount = Decimal("0")
    return f"{amount:.2f}"


def _game_label(game_type: str) -> str:
    for config in GAMES_CONFIG.values():
        if str(config.get("game_type")) == game_type:
            emoji = str(config.get("emoji") or "🎮")
            name = str(config.get("name") or game_type)
            return f"{emoji} {name}"
    return game_type or "Игра"


def _result_kind(payload: Mapping[str, Any], recipient_id: int | None) -> str:
    result = str(payload.get("result") or "")
    if result in _HEADLINES:
        return result
    kind = str(payload.get("outcome_kind") or "")
    if kind == "tie_split":
        return "tie"
    try:
        payout = Decimal(str(payload.get("your_payout_rub") or "0"))
    except (InvalidOperation, ValueError):
        payout = Decimal("0")
    if payout > 0:
        return "win"
    return "lose"


def format_personal_result_dm(payload: Mapping[str, Any], *, recipient_id: int | None = None) -> str:
    """HTML for the player's private chat. Public table boards do not use this."""
    result = _result_kind(payload, recipient_id)
    game_type = str(payload.get("game_type") or "")
    game_id = str(payload.get("table_id") or payload.get("game_id") or "")
    payout = payload.get("your_payout_rub")
    if payout is None:
        payout = payload.get("payout_rub") or "0"
    available = payload.get("available_rub")
    stake = payload.get("stake_rub")
    commission = payload.get("commission_rub")
    lines = [f"<b>{_HEADLINES.get(result, 'Игра завершена')}</b>"]
    short_id = fmt_id(game_id) if game_id else ""
    label = html.escape(_game_label(game_type))
    if short_id:
        lines.append(f"{label} · стол #{html.escape(short_id)}")
    else:
        lines.append(label)
    if stake is not None and str(stake) != "":
        lines.append(f"Ставка: {_money(stake)} ₽")
    if result != "cancel":
        lines.append(f"Выплата: {_money(payout)} ₽")
    if commission is not None and str(commission) != "":
        lines.append(f"Комиссия стола: {_money(commission)} ₽")
    if available is not None and str(available) != "":
        lines.append(f"Баланс: {_money(available)} ₽")
    return "\n".join(lines)
