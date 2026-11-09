"""Ролик, который партнёрский бот шлёт вместе с баннером (Telegram sendVideo)."""
from __future__ import annotations

from pathlib import Path

BANNER_NAME = "partner_banner.mp4"


def banner_video_path(materials: Path) -> Path | None:
    path = materials / BANNER_NAME
    return path if path.is_file() else None


async def send_banner_video(bot, chat_id: int, path: Path, caption: str, *, video=None) -> None:
    if video is None:
        from aiogram.types import FSInputFile

        video = FSInputFile(path)
    await bot.send_video(
        chat_id=chat_id,
        video=video,
        caption=caption,
        supports_streaming=True,
    )
