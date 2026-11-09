"""Welcome banner for /start and «Совершить обмен».

assets/welcome.png is a JPEG (JFIF) saved with a .png name. Telegram sendPhoto
uses the filename for decoding; a JPEG labeled as PNG is dropped and the user
sees caption-only / a failed photo.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from telegram import InputFile
from telegram.error import BadRequest, Forbidden

logger = logging.getLogger(__name__)

WELCOME_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "welcome.png"
PHOTO_CAPTION_LIMIT = 1024

_cached_file_id: str | None = None


def welcome_filename(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "welcome.jpg"
    if data.startswith(b"\x89PNG"):
        return "welcome.png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "welcome.webp"
    return "welcome.jpg"


def welcome_input_file() -> InputFile:
    data = WELCOME_IMAGE.read_bytes()
    return InputFile(io.BytesIO(data), filename=welcome_filename(data))


def _photo_payload():
    if _cached_file_id:
        return _cached_file_id
    return welcome_input_file()


def _remember_file_id(sent) -> None:
    global _cached_file_id
    if _cached_file_id:
        return
    photos = getattr(sent, "photo", None) or []
    if photos:
        _cached_file_id = photos[-1].file_id


def reset_welcome_file_id_cache() -> None:
    global _cached_file_id
    _cached_file_id = None


async def send_welcome_photo(
    bot,
    chat_id: int,
    *,
    caption: str | None = None,
    reply_markup=None,
    parse_mode: str = "HTML",
):
    """Send the FocusPay welcome image. Caption is attached when Telegram allows it."""
    if not WELCOME_IMAGE.is_file():
        logger.error("welcome image missing path=%s", WELCOME_IMAGE)
        if caption:
            return await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        return None

    cap = caption if caption and len(caption) <= PHOTO_CAPTION_LIMIT else None

    async def _send(photo, *, with_caption: bool):
        kwargs = {
            "chat_id": chat_id,
            "photo": photo,
            "reply_markup": reply_markup,
        }
        if with_caption and cap:
            kwargs["caption"] = cap
            kwargs["parse_mode"] = parse_mode
        return await bot.send_photo(**kwargs)

    photo = _photo_payload()
    try:
        sent = await _send(photo, with_caption=True)
    except Forbidden:
        raise
    except BadRequest as exc:
        logger.warning("welcome send_photo failed, retry without caption: %s", exc)
        reset_welcome_file_id_cache()
        try:
            sent = await _send(welcome_input_file(), with_caption=False)
        except Exception:
            logger.exception("welcome send_photo retry failed path=%s", WELCOME_IMAGE)
            if caption:
                return await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            raise
        if caption:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
    except Exception:
        logger.exception("welcome send_photo failed path=%s", WELCOME_IMAGE)
        if caption:
            return await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        raise
    else:
        if cap is None and caption:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )

    _remember_file_id(sent)
    return sent
