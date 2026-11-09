"""Опрос бота реквизитов командой /reki с пользовательского аккаунта.

Bot API не умеет писать другому боту, поэтому запрос идёт через ту же
Telethon-сессию, что и скан участников чата (можно развести по REKI_USER_SESSION).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from services import reki_request
from services.chat_members_scan import api_credentials
from services.reki_snapshot import (
    DEFAULT_TTL_SECONDS,
    RekiSnapshot,
    parse_reki_snapshot,
)

logger = logging.getLogger("reki_poll")

DEFAULT_POLL_SECONDS = 120
REPLY_TIMEOUT_SEC = 15
FLOOD_BACKOFF_SEC = 300

_cache: RekiSnapshot | None = None


def reki_peer() -> str | int | None:
    return reki_request.reki_peer()


def reki_session_path() -> Path:
    return reki_request.reki_session_path()


def poll_seconds() -> int:
    try:
        return max(30, int(os.environ.get("REKI_POLL_SECONDS", DEFAULT_POLL_SECONDS)))
    except ValueError:
        return DEFAULT_POLL_SECONDS


def snapshot_ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("REKI_SNAPSHOT_TTL_SECONDS", DEFAULT_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def poll_ready() -> bool:
    if reki_peer() is None or api_credentials() is None:
        return False
    path = reki_session_path()
    return path.is_file() and path.stat().st_size > 0


def cached_snapshot() -> RekiSnapshot | None:
    """Последний снимок в этом процессе. БД — источник для остальных."""
    return _cache


async def fetch_reki_text() -> str | None:
    """Отправляет /reki и ждёт ответ от того же peer."""
    if not poll_ready():
        return None
    return await reki_request.send_command_and_wait(
        "/reki", match="Доступно", timeout_sec=REPLY_TIMEOUT_SEC
    )


async def store_snapshot(snapshot: RekiSnapshot) -> None:
    """Переписывает снимок целиком: частичных состояний быть не должно."""
    from services.db import get_pool

    pool = await get_pool()
    taken = snapshot.taken_at or datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM reki_snapshots")
            await conn.execute("DELETE FROM reki_snapshot_meta")
            for token, section in snapshot.sections.items():
                await conn.execute(
                    """
                    INSERT INTO reki_snapshot_meta (sub_token, count, total_rub, snapshot_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    token,
                    int(section.count),
                    section.total_rub,
                    taken,
                )
                for band in section.bands:
                    await conn.execute(
                        """
                        INSERT INTO reki_snapshots
                            (sub_token, min_rub, max_rub, available_rub, snapshot_at)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        token,
                        band.min_rub,
                        band.max_rub,
                        band.available_rub,
                        taken,
                    )


async def load_snapshot() -> RekiSnapshot | None:
    """Снимок из БД. Свежесть проверяет вызывающий через is_fresh()."""
    from services.db import get_pool
    from services.reki_snapshot import RekiBand, RekiSection

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            meta = await conn.fetch(
                "SELECT sub_token, count, total_rub, snapshot_at FROM reki_snapshot_meta"
            )
            rows = await conn.fetch(
                """
                SELECT sub_token, min_rub, max_rub, available_rub
                FROM reki_snapshots
                ORDER BY sub_token, min_rub
                """
            )
    except Exception:
        logger.warning("reki snapshot load failed", exc_info=True)
        return None

    if not meta:
        return None
    bands: dict[str, list] = {}
    for row in rows:
        bands.setdefault(str(row["sub_token"]), []).append(
            RekiBand(
                min_rub=row["min_rub"],
                max_rub=row["max_rub"],
                available_rub=row["available_rub"],
            )
        )
    sections = {}
    taken_at = None
    for row in meta:
        token = str(row["sub_token"])
        sections[token] = RekiSection(
            sub_token=token,
            count=int(row["count"] or 0),
            total_rub=row["total_rub"],
            bands=tuple(bands.get(token, ())),
        )
        stamp = row["snapshot_at"]
        if stamp is not None and (taken_at is None or stamp > taken_at):
            taken_at = stamp
    return RekiSnapshot(sections=sections, taken_at=taken_at)


async def poll_once() -> RekiSnapshot | None:
    global _cache
    text = await fetch_reki_text()
    if not text:
        return None
    snapshot = parse_reki_snapshot(text, taken_at=datetime.now(timezone.utc))
    if snapshot.empty:
        logger.warning("reki poll: reply parsed into zero bands")
        return None
    _cache = snapshot
    try:
        await store_snapshot(snapshot)
    except Exception:
        logger.warning("reki snapshot store failed", exc_info=True)
    return snapshot


async def reki_poll_task(*, shutdown_event: asyncio.Event | None = None) -> None:
    if not poll_ready():
        logger.info("reki poll disabled: no REKI_BOT_PEER or no Telethon session")
        return
    while shutdown_event is None or not shutdown_event.is_set():
        delay = poll_seconds()
        try:
            snapshot = await poll_once()
            if snapshot is not None:
                logger.info(
                    "reki snapshot: %s",
                    ", ".join(
                        f"{token} {len(section.bands)} полос / {section.total_rub} ₽"
                        for token, section in snapshot.sections.items()
                    ),
                )
        except Exception as exc:
            if type(exc).__name__ == "FloodWaitError":
                delay = max(delay, int(getattr(exc, "seconds", 0) or 0) + 5, FLOOD_BACKOFF_SEC)
                logger.warning("reki poll flood wait: sleeping %ss", delay)
            else:
                logger.warning("reki poll failed", exc_info=True)
                delay = max(delay, FLOOD_BACKOFF_SEC)
        if shutdown_event is None:
            await asyncio.sleep(delay)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue
