"""Presentation dice for web cub. Does not decide money.

Web cub still wins when HMAC digest < policy threshold. These two d6 faces
are a deterministic illustration of that already-decided `won` flag so the
canvas can show player-vs-house without a second RNG.
"""
from __future__ import annotations

from typing import Mapping

WIN_PAIRS: tuple[tuple[int, int], ...] = tuple(
    (player, house) for player in range(1, 7) for house in range(1, 7) if player > house
)
LOSE_PAIRS: tuple[tuple[int, int], ...] = tuple(
    (player, house) for player in range(1, 7) for house in range(1, 7) if player < house
)


def cub_presentation_pips(digest: int, *, won: bool) -> tuple[int, int]:
    pairs = WIN_PAIRS if won else LOSE_PAIRS
    player, house = pairs[int(digest) % len(pairs)]
    return int(player), int(house)


def _valid_pips(value: object) -> int | None:
    try:
        pips = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= pips <= 6:
        return pips
    return None


def cub_pips_from_rng(rng: object) -> dict[str, int]:
    """Top-level player_pips/house_pips for a play_cub payload."""
    data = dict(rng) if isinstance(rng, Mapping) else {}
    stored_player = _valid_pips(data.get("player_pips"))
    stored_house = _valid_pips(data.get("house_pips"))
    if stored_player is not None and stored_house is not None:
        return {"player_pips": stored_player, "house_pips": stored_house}
    digest_hex = data.get("digest_hex")
    won = data.get("won")
    if not isinstance(digest_hex, str) or not digest_hex or not isinstance(won, bool):
        return {}
    try:
        digest = int(digest_hex, 16)
    except ValueError:
        return {}
    player, house = cub_presentation_pips(digest, won=won)
    return {"player_pips": player, "house_pips": house}
