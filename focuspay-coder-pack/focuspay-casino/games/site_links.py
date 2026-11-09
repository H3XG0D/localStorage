"""Live casino site URLs for Telegram (http allowed; Web App stays HTTPS-only)."""
from __future__ import annotations

import html
from typing import Any
from urllib.parse import quote

from telebot import types

import config

WATCH_LABEL = "Смотреть на сайте"


def casino_origin() -> str | None:
    miniapp = str(getattr(config, "CASINO_MINIAPP_URL", "") or "").strip().rstrip("/")
    if not miniapp:
        return None
    if miniapp.endswith("/casino/tg"):
        origin = miniapp[: -len("/casino/tg")]
    elif "/casino/" in miniapp:
        origin = miniapp.split("/casino/", 1)[0]
    else:
        origin = miniapp
    return origin or None


def site_href(path: str, query: str | None = None) -> str | None:
    origin = casino_origin()
    if not origin:
        return None
    raw = str(path or "").strip()
    if not raw:
        return None
    if not raw.startswith("/"):
        raw = f"/{raw}"
    url = f"{origin}{raw}"
    extra = str(query or "").strip().lstrip("?")
    if extra:
        url = f"{url}?{extra}"
    return url


def https_only(url: str | None) -> str | None:
    if not url or not url.lower().startswith("https://"):
        return None
    return url


def roulette_play_url() -> str | None:
    return site_href("/casino/play/roulette", "mode=players")


def jackpot_play_url() -> str | None:
    return site_href("/casino/play/jackpot", "mode=players")


def _safe_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return quote(text, safe="-_.")


def duel_url(game_id: object) -> str | None:
    token = _safe_id(game_id)
    if not token:
        return None
    return site_href(f"/casino/duels/{token}")


def table_url(table_id: object) -> str | None:
    token = _safe_id(table_id)
    if not token:
        return None
    return site_href(f"/casino/tables/{token}")


def room_url(room_id: object) -> str | None:
    token = _safe_id(room_id)
    if not token:
        return None
    return site_href(f"/casino/rooms/{token}")


def watch_html(url: str | None, caption: str = WATCH_LABEL) -> str:
    if not url:
        return ""
    href = html.escape(url, quote=True)
    label = html.escape(caption)
    visible = html.escape(url)
    return f'<a href="{href}">{label}</a>\n<code>{visible}</code>'


def append_watch_line(text: str, url: str | None, caption: str = WATCH_LABEL) -> str:
    line = watch_html(url, caption)
    if not line:
        return text
    return f"{text.rstrip()}\n\n{line}"


def add_watch_button(
    keyboard: Any, url: str | None, caption: str = WATCH_LABEL
) -> bool:
    """Inline URL button. Telegram rejects web_app keyboards in groups."""
    if keyboard is None or not url:
        return False
    keyboard.add(types.InlineKeyboardButton(caption, url=url))
    return True


def add_open_url_button(keyboard: Any, url: str | None, caption: str) -> bool:
    """Same as watch: url=, never web_app. web_app is private-chat-only."""
    return add_watch_button(keyboard, url, caption)


def watch_keyboard(url: str | None, caption: str = WATCH_LABEL) -> types.InlineKeyboardMarkup | None:
    if not url:
        return None
    keyboard = types.InlineKeyboardMarkup()
    add_watch_button(keyboard, url, caption)
    return keyboard
