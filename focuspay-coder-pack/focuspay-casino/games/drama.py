"""Staged Telegram edits with throttle, wait, and shutdown drain."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

MIN_EDIT_INTERVAL = 1.2
REVEAL_HOLD_SECONDS = 12

BeatFn = Callable[[], Awaitable[Any]]
Beat = tuple[BeatFn, float] | tuple[BeatFn, float, str]

_TASKS: dict[str, asyncio.Task] = {}
_EVENTS: dict[str, asyncio.Event] = {}
_PHASE: dict[str, str] = {}
_LAST_EDIT: dict[str, float] = {}
_DONE: set[str] = set()


def reset_state() -> None:
    _TASKS.clear()
    _EVENTS.clear()
    _PHASE.clear()
    _LAST_EDIT.clear()
    _DONE.clear()


def is_running(key: str) -> bool:
    task = _TASKS.get(key)
    return isinstance(task, asyncio.Task) and not task.done()


def is_done(key: str) -> bool:
    return key in _DONE


def phase_of(key: str) -> str | None:
    return _PHASE.get(key)


def set_phase(key: str, phase: str) -> None:
    _PHASE[key] = phase


async def throttle(key: str) -> None:
    gap = float(MIN_EDIT_INTERVAL or 0)
    if gap <= 0:
        _LAST_EDIT[key] = time.monotonic()
        return
    now = time.monotonic()
    wait = gap - (now - _LAST_EDIT.get(key, 0.0))
    if wait > 0:
        await asyncio.sleep(wait)
    _LAST_EDIT[key] = time.monotonic()


def _event(key: str) -> asyncio.Event:
    existing = _EVENTS.get(key)
    if isinstance(existing, asyncio.Event):
        return existing
    event = asyncio.Event()
    _EVENTS[key] = event
    return event


async def run_beats(key: str, beats: Sequence[Beat], *, restart: bool = False) -> asyncio.Task | None:
    if not key:
        return None
    if is_running(key) and not restart:
        return _TASKS.get(key)
    if is_running(key) and restart:
        task = _TASKS.get(key)
        if isinstance(task, asyncio.Task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    _DONE.discard(key)
    event = _event(key)
    if event.is_set():
        event = asyncio.Event()
        _EVENTS[key] = event
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    packed = list(beats)
    task = loop.create_task(_run(key, packed), name=f"drama-{key}")
    _TASKS[key] = task
    return task


async def _run(key: str, beats: list[Beat]) -> None:
    event = _event(key)
    try:
        for item in beats:
            fn = item[0]
            delay = float(item[1]) if len(item) > 1 else 0.0
            if len(item) > 2 and item[2]:
                set_phase(key, str(item[2]))
            await throttle(key)
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("drama beat failed key=%s", key)
            if delay > 0:
                await asyncio.sleep(delay)
        _DONE.add(key)
        event.set()
    except asyncio.CancelledError:
        event.set()
        raise
    except Exception:
        logger.exception("drama run failed key=%s", key)
        event.set()
    finally:
        current = asyncio.current_task()
        stored = _TASKS.get(key)
        if stored is current:
            _TASKS.pop(key, None)


async def wait_drama(key: str, timeout: float | None = REVEAL_HOLD_SECONDS) -> bool:
    if not key or key in _DONE:
        return True
    event = _EVENTS.get(key)
    if event is None:
        return True
    if event.is_set():
        return True
    if timeout is None:
        await event.wait()
        return True
    try:
        await asyncio.wait_for(event.wait(), timeout=max(0.0, float(timeout)))
        return True
    except asyncio.TimeoutError:
        logger.warning("drama wait timed out key=%s", key)
        return False


async def drain_drama() -> None:
    tasks = [task for task in list(_TASKS.values()) if isinstance(task, asyncio.Task) and not task.done()]
    for task in tasks:
        task.cancel()
    _TASKS.clear()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    for event in list(_EVENTS.values()):
        event.set()
    reset_state()
