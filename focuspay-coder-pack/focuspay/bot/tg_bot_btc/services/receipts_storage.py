"""Каталог чеков: единая точка + проверка записи и скачивание файлов из Telegram с ретраями."""
from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path

from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("receipts_storage")

TG_FILE_CONNECT_TIMEOUT = 15.0
TG_FILE_READ_TIMEOUT = 60.0
TG_FILE_WRITE_TIMEOUT = 30.0
TG_FILE_POOL_TIMEOUT = 15.0
TG_FILE_MAX_ATTEMPTS = 3
TG_FILE_RETRY_BASE_DELAY = 1.0


def receipts_dir() -> Path:
    raw = (os.getenv("RECEIPTS_DIR") or "").strip()
    path = Path(raw) if raw else _ROOT / "receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def assert_receipts_writable(path: Path | None = None) -> Path:
    """Проверяет, что процесс может создавать файлы в каталоге чеков."""
    directory = path or receipts_dir()
    probe = directory / ".write_probe"
    try:
        probe.write_bytes(b"")
        probe.unlink(missing_ok=True)
    except OSError as e:
        raise PermissionError(
            f"Нет прав на запись в {directory} (запустите chown focuspay:focuspay на сервере)"
        ) from e
    return directory


def _timeout_kwargs(read_timeout: float = TG_FILE_READ_TIMEOUT) -> dict[str, float]:
    return {
        "connect_timeout": TG_FILE_CONNECT_TIMEOUT,
        "read_timeout": read_timeout,
        "write_timeout": TG_FILE_WRITE_TIMEOUT,
        "pool_timeout": TG_FILE_POOL_TIMEOUT,
    }


def _is_retryable_tg_download_error(exc: BaseException) -> bool:
    if isinstance(exc, BadRequest):
        return False
    if isinstance(exc, (TimedOut, NetworkError, RetryAfter, TimeoutError, asyncio.TimeoutError)):
        return True
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg or "connection" in msg


async def _get_tg_file(bot, file_id: str, *, read_timeout: float = TG_FILE_READ_TIMEOUT):
    kwargs = _timeout_kwargs(read_timeout)
    try:
        return await bot.get_file(file_id, **kwargs)
    except TypeError:
        return await bot.get_file(file_id)


async def download_telegram_file_to_path(
    bot,
    file_id: str,
    dest_path: str | Path,
    *,
    read_timeout: float = TG_FILE_READ_TIMEOUT,
    max_attempts: int = TG_FILE_MAX_ATTEMPTS,
    retry_base_delay: float = TG_FILE_RETRY_BASE_DELAY,
) -> Path:
    """Скачивает файл из Telegram на диск с увеличенным таймаутом и ретраями при сетевых сбоях."""
    target = Path(dest_path)
    kwargs = _timeout_kwargs(read_timeout)
    last_exc: BaseException | None = None

    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            tg_file = await _get_tg_file(bot, file_id, read_timeout=read_timeout)
            try:
                await tg_file.download_to_drive(str(target), **kwargs)
            except TypeError:
                await tg_file.download_to_drive(str(target))
            return target
        except Exception as exc:
            last_exc = exc
            target.unlink(missing_ok=True)
            if attempt >= max_attempts or not _is_retryable_tg_download_error(exc):
                raise
            delay = (
                float(getattr(exc, "retry_after", 0) or 0)
                if isinstance(exc, RetryAfter)
                else retry_base_delay * attempt
            )
            logger.warning(
                "Telegram file download retry %d/%d file_id=%s err=%s (sleep %.1fs)",
                attempt,
                max_attempts,
                file_id,
                exc,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc


async def download_telegram_file_bytes(
    bot,
    file_id: str,
    *,
    read_timeout: float = TG_FILE_READ_TIMEOUT,
    max_attempts: int = TG_FILE_MAX_ATTEMPTS,
    retry_base_delay: float = TG_FILE_RETRY_BASE_DELAY,
) -> bytes:
    """Скачивает файл из Telegram в память с увеличенным таймаутом и ретраями."""
    kwargs = _timeout_kwargs(read_timeout)
    last_exc: BaseException | None = None

    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            tg_file = await _get_tg_file(bot, file_id, read_timeout=read_timeout)
            if hasattr(tg_file, "download_as_bytearray"):
                try:
                    data = await tg_file.download_as_bytearray(**kwargs)
                except TypeError:
                    data = await tg_file.download_as_bytearray()
                return bytes(data)
            buf = io.BytesIO()
            try:
                await tg_file.download_to_memory(buf, **kwargs)
            except TypeError:
                await tg_file.download_to_memory(buf)
            return buf.getvalue()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_tg_download_error(exc):
                raise
            delay = (
                float(getattr(exc, "retry_after", 0) or 0)
                if isinstance(exc, RetryAfter)
                else retry_base_delay * attempt
            )
            logger.warning(
                "Telegram file bytes download retry %d/%d file_id=%s err=%s (sleep %.1fs)",
                attempt,
                max_attempts,
                file_id,
                exc,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc

