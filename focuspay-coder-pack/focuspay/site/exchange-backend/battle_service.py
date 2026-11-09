"""Shared battle round manager singleton."""
from __future__ import annotations

from battle_round import BattleRoundManager

_manager: BattleRoundManager | None = None


async def get_battle_manager() -> BattleRoundManager:
    global _manager
    if _manager is None:
        _manager = BattleRoundManager()
        await _manager.init()
    return _manager
