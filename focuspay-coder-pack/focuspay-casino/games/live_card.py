"""One editable Telegram card per chat for a live shared round."""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from games.chat_reaper import TTL_CARD, message_id_of, track, untrack
from games.drama import wait_drama

logger = logging.getLogger(__name__)

HTML_EDIT_KWARGS = {
    "parse_mode": "HTML",
    "disable_web_page_preview": True,
}


def _not_modified(exc: BaseException) -> bool:
    return "message is not modified" in str(exc).lower()


async def edit_html_message(
    bot: Any,
    chat_id: int,
    message_id: int,
    text: str,
    markup: Any = None,
    *,
    log_name: str = "card",
) -> str | None:
    """Edit HTML. If the keyboard is rejected (group web_app), retry without it.

    Returns None on success, or a lowercased error string when the message is gone.
    """
    try:
        if markup is not None:
            await bot.edit_message_text(
                text, chat_id, message_id, reply_markup=markup, **HTML_EDIT_KWARGS
            )
        else:
            await bot.edit_message_text(text, chat_id, message_id, **HTML_EDIT_KWARGS)
        return None
    except Exception as exc:
        if _not_modified(exc):
            return None
        logger.warning(
            "%s card edit failed chat=%s msg=%s: %s",
            log_name,
            chat_id,
            message_id,
            exc,
        )
        if markup is not None:
            try:
                await bot.edit_message_text(text, chat_id, message_id, **HTML_EDIT_KWARGS)
                return None
            except Exception as inner:
                if _not_modified(inner):
                    return None
                logger.warning(
                    "%s card edit without keyboard failed chat=%s msg=%s: %s",
                    log_name,
                    chat_id,
                    message_id,
                    inner,
                )
                exc = inner
        text_l = str(exc).lower()
        if "message to edit not found" in text_l or "message to delete not found" in text_l:
            return text_l
        return None


FetchSnapshot = Callable[..., Awaitable[dict[str, Any]]]
RenderText = Callable[[dict[str, Any] | None], str]
RenderKeyboard = Callable[[dict[str, Any] | None], Any]
IsTerminal = Callable[[dict[str, Any] | None], bool]
IntervalFn = Callable[[dict[str, Any] | None], float]
OnSnapshot = Callable[..., Awaitable[bool]]
DramaKeyFn = Callable[[int, dict[str, Any] | None], str | None]


class LiveCardBoard:
    def __init__(
        self,
        *,
        name: str,
        interval: float,
        fetch: FetchSnapshot,
        render: RenderText,
        keyboard: RenderKeyboard,
        terminal: IsTerminal,
        ttl: float = TTL_CARD,
        interval_fn: IntervalFn | None = None,
        on_snapshot: OnSnapshot | None = None,
        drama_key: DramaKeyFn | None = None,
    ) -> None:
        self.name = name
        self.interval = interval
        self._fetch = fetch
        self._render = render
        self._keyboard = keyboard
        self._terminal = terminal
        self._ttl = ttl
        self._interval_fn = interval_fn
        self._on_snapshot = on_snapshot
        self._drama_key = drama_key
        self._cards: dict[int, dict[str, Any]] = {}

    def reset(self) -> None:
        for card in list(self._cards.values()):
            task = card.get("task")
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
        self._cards.clear()

    async def drain(self) -> None:
        tasks: list[asyncio.Task] = []
        for card in list(self._cards.values()):
            task = card.get("task")
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                tasks.append(task)
        self._cards.clear()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def peek(self, chat_id: int) -> dict[str, Any] | None:
        card = self._cards.get(chat_id)
        return dict(card) if isinstance(card, dict) else None

    def cards(self) -> dict[int, dict[str, Any]]:
        return dict(self._cards)

    def round_id_of(self, snapshot: dict[str, Any] | None) -> str:
        if not isinstance(snapshot, dict):
            return ""
        return str(snapshot.get("round_id") or snapshot.get("room_id") or "")

    def _sleep_for(self, snapshot: dict[str, Any] | None) -> float:
        if self._interval_fn is not None:
            try:
                return max(0.0, float(self._interval_fn(snapshot)))
            except Exception:
                logger.exception("%s interval_fn failed", self.name)
        return max(0.0, float(self.interval))

    async def _pull(self, client: Any, telegram_id: int | None, chat_id: int) -> dict[str, Any]:
        fetch = self._fetch
        params = inspect.signature(fetch).parameters
        if len(params) >= 3:
            data = await fetch(client, telegram_id, chat_id)
        else:
            data = await fetch(client, telegram_id)
        return data if isinstance(data, dict) else {}

    async def upsert(
        self,
        bot: Any,
        client: Any,
        chat_id: int,
        snapshot: dict[str, Any] | None,
        *,
        telegram_id: int | None = None,
        message_id: int | None = None,
    ) -> None:
        snap = snapshot if isinstance(snapshot, dict) else {}
        text = self._render(snap)
        markup = self._keyboard(snap)
        round_id = self.round_id_of(snap)
        existing = self._cards.get(chat_id)
        if (
            existing
            and existing.get("round_id") == round_id
            and isinstance(existing.get("message_id"), int)
        ):
            await self._edit(bot, chat_id, int(existing["message_id"]), text, markup)
            existing["telegram_id"] = telegram_id or existing.get("telegram_id")
            existing["snapshot"] = snap
            await self._maybe_drama(bot, client, chat_id, snap, existing, wait=False)
            self._ensure_ticker(bot, client, chat_id)
            return
        if existing:
            await self.drop(bot, chat_id)
        if isinstance(message_id, int) and not isinstance(message_id, bool):
            self._cards[chat_id] = {
                "round_id": round_id,
                "message_id": message_id,
                "telegram_id": telegram_id,
                "snapshot": snap,
                "task": None,
            }
            await self._edit(bot, chat_id, message_id, text, markup)
            await self._maybe_drama(bot, client, chat_id, snap, self._cards[chat_id], wait=False)
            self._ensure_ticker(bot, client, chat_id)
            return
        sent = await self._send(bot, chat_id, text, markup)
        mid = message_id_of(sent)
        self._cards[chat_id] = {
            "round_id": round_id,
            "message_id": mid,
            "telegram_id": telegram_id,
            "snapshot": snap,
            "task": None,
        }
        await self._maybe_drama(bot, client, chat_id, snap, self._cards[chat_id], wait=False)
        self._ensure_ticker(bot, client, chat_id)

    async def drop(self, bot: Any, chat_id: int) -> None:
        card = self._cards.pop(chat_id, None)
        if not isinstance(card, dict):
            return
        task = card.get("task")
        current = asyncio.current_task()
        if isinstance(task, asyncio.Task) and task is not current and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        mid = card.get("message_id")
        if isinstance(mid, int):
            untrack(chat_id, mid)
            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id, mid)

    def _ensure_ticker(self, bot: Any, client: Any, chat_id: int) -> None:
        card = self._cards.get(chat_id)
        if not card:
            return
        task = card.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        card["task"] = asyncio.create_task(
            self._tick(bot, client, chat_id),
            name=f"{self.name}-card-{chat_id}",
        )

    async def _maybe_drama(
        self,
        bot: Any,
        client: Any,
        chat_id: int,
        snap: dict[str, Any],
        card: dict[str, Any],
        *,
        wait: bool,
    ) -> bool:
        if self._on_snapshot is None:
            return False
        try:
            handled = bool(await self._on_snapshot(bot, client, chat_id, snap, card))
        except Exception:
            logger.exception("%s on_snapshot failed chat=%s", self.name, chat_id)
            return False
        if not handled or not wait:
            return handled
        key = self._drama_key(chat_id, snap) if self._drama_key is not None else None
        if key:
            await wait_drama(key, timeout=30)
        return False

    async def _tick(self, bot: Any, client: Any, chat_id: int) -> None:
        try:
            while True:
                card = self._cards.get(chat_id)
                if not card:
                    return
                await asyncio.sleep(self._sleep_for(card.get("snapshot") if isinstance(card.get("snapshot"), dict) else None))
                card = self._cards.get(chat_id)
                if not card:
                    return
                telegram_id = card.get("telegram_id")
                try:
                    snap = await self._pull(
                        client,
                        telegram_id if isinstance(telegram_id, int) else None,
                        chat_id,
                    )
                except Exception:
                    logger.exception("%s card snapshot failed chat=%s", self.name, chat_id)
                    continue
                if not isinstance(snap, dict):
                    snap = {}
                round_id = self.round_id_of(snap)
                stored_round = str(card.get("round_id") or "")
                if round_id and stored_round and round_id != stored_round:
                    card["round_id"] = round_id
                handled = await self._maybe_drama(bot, client, chat_id, snap, card, wait=True)
                mid = card.get("message_id")
                if not handled and isinstance(mid, int):
                    await self._edit(bot, chat_id, mid, self._render(snap), self._keyboard(snap))
                card["snapshot"] = snap
                if self._terminal(snap):
                    if isinstance(mid, int):
                        track(chat_id, mid, self._ttl)
                    card["task"] = None
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s card ticker failed chat=%s", self.name, chat_id)

    async def _send(self, bot: Any, chat_id: int, text: str, markup: Any) -> Any:
        kwargs: dict[str, Any] = {
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if markup is not None:
            try:
                return await bot.send_message(chat_id, text, reply_markup=markup, **kwargs)
            except Exception as exc:
                logger.warning("%s card send with keyboard failed: %s", self.name, exc)
        return await bot.send_message(chat_id, text, **kwargs)

    async def _edit(self, bot: Any, chat_id: int, message_id: int, text: str, markup: Any) -> None:
        missing = await edit_html_message(
            bot, chat_id, message_id, text, markup, log_name=self.name
        )
        if missing:
            card = self._cards.get(chat_id)
            if card:
                sent = await self._send(bot, chat_id, text, markup)
                card["message_id"] = message_id_of(sent)
