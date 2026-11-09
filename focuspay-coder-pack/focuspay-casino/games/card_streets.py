"""Street-by-street card reveal pacing for Telegram (mirror of site streets)."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

STREET_PAUSE_SECONDS = 2.0
RESULT_BEAT_SECONDS = 1.0
BLACKJACK_STREET_CARDS = 2


def _as_hands(hands: Mapping[Any, Any] | None) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    if not isinstance(hands, Mapping):
        return out
    for key, raw in hands.items():
        try:
            seat = int(key)
        except (TypeError, ValueError):
            continue
        cards = [str(card) for card in raw] if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
        if cards:
            out[seat] = cards
    return out


def street_count(hands: Mapping[Any, Any] | None, *, game_type: str = "") -> int:
    mapped = _as_hands(hands)
    if not mapped:
        return 0
    longest = max(len(cards) for cards in mapped.values())
    if str(game_type) == "blackjack":
        return min(BLACKJACK_STREET_CARDS, longest)
    return longest


def visible_hands(
    hands: Mapping[Any, Any] | None,
    streets_shown: int,
    *,
    game_type: str = "",
) -> dict[str, list[str]]:
    limit = max(0, int(streets_shown))
    if str(game_type) == "blackjack":
        limit = min(limit, BLACKJACK_STREET_CARDS)
    out: dict[str, list[str]] = {}
    for seat, cards in _as_hands(hands).items():
        out[str(seat)] = list(cards[:limit])
    return out


def dealing_label(street: int) -> str:
    if street == 2:
        return "Раздача: вторая карта…"
    if street == 3:
        return "Раздача: третья карта…"
    return "Раздача: первая карта…"
