"""SSE-хаб для покупателей: PostgreSQL NOTIFY web_chat_buyer → подписчики сайта.

Аддитивный аналог chat_events_hub (операторский канал web_chat_new). Здесь ловим
события, адресованные покупателю: ответы оператора в чате и смену статуса заявки.
Каждое событие несёт order_id, по которому SSE-роут фильтрует нужную заявку.
"""
from __future__ import annotations

import asyncio
import json
import logging

from db import get_pool

logger = logging.getLogger("buyer_events_hub")

_subscribers: set[asyncio.Queue] = set()
_listener_task: asyncio.Task | None = None
_listener_conn = None


def _on_notify(_conn, _pid, _channel, payload: str) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {"raw": payload}
    dead: list[asyncio.Queue] = []
    for q in list(_subscribers):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


async def _listen_loop() -> None:
    global _listener_conn
    while True:
        try:
            pool = await get_pool()
            _listener_conn = await pool.acquire()
            await _listener_conn.add_listener("web_chat_buyer", _on_notify)
            logger.info("buyer events: LISTEN web_chat_buyer")
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("buyer events listener failed, retry in 5s")
            await asyncio.sleep(5)
        finally:
            if _listener_conn is not None:
                try:
                    await _listener_conn.remove_listener("web_chat_buyer", _on_notify)
                except Exception:
                    logger.debug("ignored non-fatal error", exc_info=True)
                try:
                    pool = await get_pool()
                    await pool.release(_listener_conn)
                except Exception:
                    logger.debug("ignored non-fatal error", exc_info=True)
                _listener_conn = None


async def start_buyer_events_listener() -> None:
    global _listener_task
    if _listener_task and not _listener_task.done():
        return
    _listener_task = asyncio.create_task(_listen_loop())


async def stop_buyer_events_listener() -> None:
    global _listener_task, _listener_conn
    if _listener_task:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
        _listener_task = None
    if _listener_conn is not None:
        try:
            await _listener_conn.remove_listener("web_chat_buyer", _on_notify)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        try:
            pool = await get_pool()
            await pool.release(_listener_conn)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
        _listener_conn = None


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)
