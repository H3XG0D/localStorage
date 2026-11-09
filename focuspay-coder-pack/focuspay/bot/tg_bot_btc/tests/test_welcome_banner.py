from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import InputFile
from telegram.error import BadRequest

from services.welcome_banner import (
    reset_welcome_file_id_cache,
    send_welcome_photo,
    welcome_filename,
)


class WelcomeFilenameTests(unittest.TestCase):
    def test_jpeg_magic_uses_jpg_name(self):
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 16
        self.assertEqual(welcome_filename(data), "welcome.jpg")

    def test_png_magic_keeps_png_name(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        self.assertEqual(welcome_filename(data), "welcome.png")


class SendWelcomePhotoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_welcome_file_id_cache()

    def tearDown(self):
        reset_welcome_file_id_cache()

    async def test_sends_jpeg_filename_not_png(self):
        bot = SimpleNamespace(send_photo=AsyncMock())
        sent = SimpleNamespace(photo=[SimpleNamespace(file_id="file-1")])
        bot.send_photo.return_value = sent

        jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
        with patch("services.welcome_banner.WELCOME_IMAGE") as path:
            path.is_file.return_value = True
            path.read_bytes.return_value = jpeg
            await send_welcome_photo(bot, 42, caption="hi", parse_mode="HTML")

        kwargs = bot.send_photo.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 42)
        self.assertEqual(kwargs["caption"], "hi")
        photo = kwargs["photo"]
        self.assertIsInstance(photo, InputFile)
        self.assertTrue(str(photo.filename).endswith(".jpg"))

    async def test_caption_too_long_sends_photo_then_text(self):
        bot = SimpleNamespace(
            send_photo=AsyncMock(
                return_value=SimpleNamespace(photo=[SimpleNamespace(file_id="file-1")])
            ),
            send_message=AsyncMock(),
        )
        jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
        long_caption = "x" * 1025
        with patch("services.welcome_banner.WELCOME_IMAGE") as path:
            path.is_file.return_value = True
            path.read_bytes.return_value = jpeg
            await send_welcome_photo(bot, 7, caption=long_caption)

        photo_kwargs = bot.send_photo.await_args.kwargs
        self.assertNotIn("caption", photo_kwargs)
        bot.send_message.assert_awaited()
        self.assertEqual(bot.send_message.await_args.kwargs["text"], long_caption)

    async def test_bad_request_falls_back_to_text(self):
        bot = SimpleNamespace(
            send_photo=AsyncMock(side_effect=BadRequest("IMAGE_PROCESS_FAILED")),
            send_message=AsyncMock(),
        )
        jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
        with patch("services.welcome_banner.WELCOME_IMAGE") as path:
            path.is_file.return_value = True
            path.read_bytes.return_value = jpeg
            await send_welcome_photo(bot, 9, caption="FocusPay")

        bot.send_message.assert_awaited()
        self.assertEqual(bot.send_message.await_args.kwargs["text"], "FocusPay")


if __name__ == "__main__":
    unittest.main()
