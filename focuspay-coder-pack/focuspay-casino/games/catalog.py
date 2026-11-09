"""Shared FocusCasino game catalog. Import this instead of games.pvp for config."""
from __future__ import annotations

from typing import Any

EMOJI_GAMES: dict[str, dict[str, Any]] = {
    "cub": {"name": "Кубики", "emoji": "🎲", "rolls": 1, "game_type": "pvp_dice", "family": "cub"},
    "2cub": {"name": "Кубики x2", "emoji": "🎲", "rolls": 2, "game_type": "pvp_dice", "family": "cub"},
}

CARD_GAMES: dict[str, dict[str, Any]] = {
    "baccara": {"name": "Baccara", "emoji": "🃏", "rolls": 0, "game_type": "baccara", "family": "baccara"},
    "blackjack": {"name": "Blackjack", "emoji": "🂡", "rolls": 0, "game_type": "blackjack", "family": "blackjack"},
}

GAMES_CONFIG: dict[str, dict[str, Any]] = {**EMOJI_GAMES, **CARD_GAMES}

FAMILIES: tuple[str, ...] = ("cub", "baccara", "blackjack")

FAMILY_LABELS = {
    "cub": ("🎲", "Кубики"),
    "baccara": ("🃏", "Baccara"),
    "blackjack": ("🂡", "Blackjack"),
}

# Shared live tables / equal-stake rooms — not V2 create.
HUB_GAMES: dict[str, dict[str, Any]] = {
    "roulette": {"name": "Рулетка", "emoji": "🎡", "game_type": "roulette"},
    "jackpot": {"name": "Джекпот", "emoji": "🎡", "game_type": "jackpot"},
    "rooms": {"name": "Комнаты", "emoji": "🎯", "game_type": "fixed_room"},
}


def is_card_game(game_key: str) -> bool:
    return game_key in CARD_GAMES


def is_emoji_game(game_key: str) -> bool:
    return game_key in EMOJI_GAMES


def game_key_for(*, family: str, rolls: int) -> str:
    if family in CARD_GAMES:
        return family
    if rolls == 2:
        return f"2{family}"
    return family


def emoji_for_canonical(game_type: str) -> str:
    for config in EMOJI_GAMES.values():
        if config["game_type"] == game_type:
            return str(config["emoji"])
    for config in CARD_GAMES.values():
        if config["game_type"] == game_type:
            return str(config["emoji"])
    return "🎮"


def fmt_id(game_id: str) -> str:
    return str(game_id)[:8].upper()
