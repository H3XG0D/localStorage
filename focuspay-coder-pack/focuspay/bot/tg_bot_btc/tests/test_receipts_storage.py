"""Tests for receipts storage helper and Telegram file download retries."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest, TimedOut

from services.receipts_storage import (
    assert_receipts_writable,
    download_telegram_file_bytes,
    download_telegram_file_to_path,
)


class ReceiptsStorageTests(unittest.TestCase):
    def test_writable_dir_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.assertEqual(assert_receipts_writable(path), path)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root bypasses chmod 0555")
    def test_readonly_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            path.chmod(0o555)
            try:
                with self.assertRaises(PermissionError):
                    assert_receipts_writable(path)
            finally:
                path.chmod(0o755)


class TelegramFileDownloadRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_to_path_retries_on_timed_out_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "receipt.pdf"
            tg_file = MagicMock()
            calls = 0

            async def fake_download(custom_path, **kwargs):
                nonlocal calls
                calls += 1
                if calls < 3:
                    Path(custom_path).write_bytes(b"partial")
                    raise TimedOut("Timed out")
                Path(custom_path).write_bytes(b"%PDF-1.4\nok")
                return Path(custom_path)

            tg_file.download_to_drive = AsyncMock(side_effect=fake_download)
            bot = MagicMock()
            bot.get_file = AsyncMock(return_value=tg_file)

            out = await download_telegram_file_to_path(
                bot,
                "file-123",
                dest,
                read_timeout=60.0,
                max_attempts=3,
                retry_base_delay=0.0,
            )

            self.assertEqual(out, dest)
            self.assertEqual(dest.read_bytes(), b"%PDF-1.4\nok")
            self.assertEqual(bot.get_file.await_count, 3)
            self.assertEqual(tg_file.download_to_drive.await_count, 3)
            self.assertEqual(
                bot.get_file.await_args.kwargs.get("read_timeout"),
                60.0,
            )

    async def test_download_to_path_cleans_up_partial_file_after_exhausted_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "receipt.pdf"
            tg_file = MagicMock()

            async def always_timeout(custom_path, **kwargs):
                Path(custom_path).write_bytes(b"partial")
                raise TimedOut("Timed out")

            tg_file.download_to_drive = AsyncMock(side_effect=always_timeout)
            bot = MagicMock()
            bot.get_file = AsyncMock(return_value=tg_file)

            with self.assertRaises(TimedOut):
                await download_telegram_file_to_path(
                    bot,
                    "file-123",
                    dest,
                    max_attempts=2,
                    retry_base_delay=0.0,
                )

            self.assertFalse(dest.exists())
            self.assertEqual(bot.get_file.await_count, 2)

    async def test_download_to_path_does_not_retry_non_network_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "receipt.pdf"
            bot = MagicMock()
            bot.get_file = AsyncMock(side_effect=BadRequest("invalid file_id"))

            with self.assertRaises(BadRequest):
                await download_telegram_file_to_path(
                    bot,
                    "bad-id",
                    dest,
                    max_attempts=3,
                    retry_base_delay=0.0,
                )

            self.assertEqual(bot.get_file.await_count, 1)

    async def test_download_bytes_retries_on_get_file_timeout(self):
        tg_file = MagicMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"hello"))
        bot = MagicMock()
        bot.get_file = AsyncMock(side_effect=[TimedOut("Timed out"), tg_file])

        raw = await download_telegram_file_bytes(
            bot,
            "file-xyz",
            max_attempts=3,
            retry_base_delay=0.0,
        )

        self.assertEqual(raw, b"hello")
        self.assertEqual(bot.get_file.await_count, 2)


if __name__ == "__main__":
    unittest.main()

