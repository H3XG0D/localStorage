"""Wait until a Telegram dice animation has shown its face."""
from __future__ import annotations

import asyncio

# Telegram 🎲 animation is ~4s; the API value arrives immediately.
DICE_LAND_SECONDS = 4


async def wait_dice_landed() -> None:
    """Wait until the Telegram dice animation has shown its face."""
    await asyncio.sleep(DICE_LAND_SECONDS)
