"""Текст сообщения из «Админ отчётов» → HTML рассылки с премиум-стикерами.

Telegram отдаёт кастомные эмодзи отдельными entities (смещения в UTF-16),
а не символами. Без этой сборки в рассылку попадает только плоский фолбэк.
"""
from __future__ import annotations

import html
import re
from typing import Any

from services.tg_emoji import EMOJI

BROADCAST_COPY_USERNAMES = frozenset({"absoluteop"})


def is_broadcast_copy_account(username: str | None) -> bool:
    """Аккаунт, чьи тексты в отчётах сохраняем как черновик рассылки."""
    return (username or "").lstrip("@").strip().lower() in BROADCAST_COPY_USERNAMES


_FORMAT = {
    "bold": ("<b>", "</b>"),
    "italic": ("<i>", "</i>"),
    "underline": ("<u>", "</u>"),
    "strikethrough": ("<s>", "</s>"),
    "code": ("<code>", "</code>"),
    "spoiler": ("<tg-spoiler>", "</tg-spoiler>"),
    "blockquote": ("<blockquote>", "</blockquote>"),
}
_STRICT_RE = re.compile(r'<tg-emoji emoji-id="(\d{5,32})">([^<]{1,8})</tg-emoji>')


def _etype(entity: Any) -> str:
    raw = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", "")
    return str(raw or "").rsplit(".", 1)[-1].lower()


def _field(entity: Any, name: str, default: Any = None) -> Any:
    if isinstance(entity, dict):
        return entity.get(name, default)
    return getattr(entity, name, default)


def _utf16_map(text: str) -> list[int]:
    mapping: list[int] = []
    for index, char in enumerate(text):
        mapping.extend([index] * (len(char.encode("utf-16-le")) // 2))
    mapping.append(len(text))
    return mapping


def _py_span(mapping: list[int], offset: int, length: int) -> tuple[int, int] | None:
    if offset < 0 or length <= 0:
        return None
    end_unit = offset + length
    if offset >= len(mapping) - 1 or end_unit > len(mapping) - 1:
        return None
    return mapping[offset], mapping[end_unit]


def _unique_pack() -> dict[str, tuple[str, str]]:
    owners: dict[str, set[str]] = {}
    canonical: dict[str, str] = {}
    for emoji_id, fallback in EMOJI.values():
        if not emoji_id or not fallback:
            continue
        for form in {fallback, fallback.replace("\ufe0f", "")}:
            if not form:
                continue
            owners.setdefault(form, set()).add(emoji_id)
            canonical.setdefault(form, fallback)
    out: dict[str, tuple[str, str]] = {}
    for form, ids in owners.items():
        if len(ids) == 1:
            out[form] = (next(iter(ids)), canonical[form])
    return out


# Клавиатурные смайлы, которых нет в паке: ближайший премиум-стикер FocusPay.
_KEYBOARD_ALIASES = {
    "🚀": ("5424818078833715060", "📢"),
    "⚡": ("5424972470023104089", "🔥"),
    "⚡️": ("5424972470023104089", "🔥"),
    "🎨": ("5422439311196834318", "💡"),
    "🔒": ("5206607081334906820", "✅"),
    "🤝": ("5942877472163892475", "👥"),
}


def _with_aliases(unique: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    merged = dict(unique)
    merged.update(_KEYBOARD_ALIASES)
    return merged


_UNIQUE = _with_aliases(_unique_pack())
_UNIQUE_RE = re.compile("|".join(re.escape(item) for item in sorted(_UNIQUE, key=len, reverse=True)))


def _tag(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def _upgrade_pack(chunk: str) -> str:
    if not chunk or not _UNIQUE:
        return chunk

    def _sub(match: re.Match[str]) -> str:
        emoji_id, fallback = _UNIQUE[match.group(0)]
        return _tag(emoji_id, fallback)

    return _UNIQUE_RE.sub(_sub, chunk)


def upgrade_pack_emoji(text: str) -> str:
    """Поднять символы пака вне уже готовых тегов. Общие фолбэки (💵 💳 💬) не трогаем."""
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    for match in _STRICT_RE.finditer(text):
        out.append(_upgrade_pack(text[pos : match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(_upgrade_pack(text[pos:]))
    return "".join(out)


def fit_premium_html(text: str, max_len: int = 4096) -> str:
    """Ужать HTML, снимая премиум-теги с конца, а не разрезая их."""
    if max_len < 1:
        return ""
    value = text or ""
    while len(value) > max_len:
        last = None
        for last in _STRICT_RE.finditer(value):
            pass
        if last is None:
            return value[:max_len].rstrip()
        value = value[: last.start()] + (last.group(2) or "") + value[last.end() :]
    return value


def prepare_broadcast_text(text: str, entities: list[Any] | None = None, *, max_len: int = 4096) -> str:
    from services.text_sanitize import sanitize_telegram_html

    built = fit_premium_html(message_to_broadcast_html(text, entities), max_len)
    return fit_premium_html(sanitize_telegram_html(built, max_len=max_len), max_len)


async def insert_broadcast_draft(
    *,
    segment: str,
    message_text: str,
    photo_file_id: str | None,
    sender_label: str,
) -> int:
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO broadcast_jobs (
                sender_role, sender_id, sender_label, segment,
                message_text, photo_file_id, status, total_count,
                sticker_ids, sticker_mode, sticker_status, destination
            )
            VALUES ('admin', 0, $1, $2, $3, $4, 'draft', 0, '[]', 'none', 'none', 'bot')
            RETURNING id
            """,
            (sender_label or "tg")[:80],
            segment or "all",
            message_text or "",
            photo_file_id,
        )
    return int(row["id"])


async def launch_broadcast_draft(job_id: int) -> bool:
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE broadcast_jobs
            SET status = 'pending', scheduled_at = NULL
            WHERE id = $1 AND status = 'draft' AND started_at IS NULL
            RETURNING id
            """,
            int(job_id),
        )
    return row is not None


async def cancel_broadcast_draft(job_id: int) -> None:
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE broadcast_jobs
            SET status = 'cancelled', finished_at = now(),
                error_summary = 'Отменено в отчётах'
            WHERE id = $1 AND status = 'draft'
            """,
            int(job_id),
        )


def message_to_broadcast_html(text: str, entities: list[Any] | None = None) -> str:
    """Собрать Telegram HTML. custom_emoji сохраняет emoji-id, остальной текст экранируется."""
    if not text:
        return ""
    mapping = _utf16_map(text)
    spans: list[tuple[int, int, str, str]] = []
    for entity in entities or []:
        span = _py_span(mapping, int(_field(entity, "offset", 0) or 0), int(_field(entity, "length", 0) or 0))
        if not span:
            continue
        start, end = span
        kind = _etype(entity)
        if kind == "custom_emoji":
            emoji_id = str(_field(entity, "custom_emoji_id", "") or "")
            if not emoji_id.isdigit():
                continue
            spans.append((start, end, _tag(emoji_id, text[start:end]), ""))
            continue
        if kind in ("text_link", "url"):
            url = str(_field(entity, "url", "") or "")
            if kind == "url":
                url = text[start:end]
            if url.startswith("http://") or url.startswith("https://") or url.startswith("tg://"):
                href = html.escape(url, quote=True)
                spans.append((start, end, f'<a href="{href}">', "</a>"))
            continue
        pair = _FORMAT.get(kind)
        if pair:
            spans.append((start, end, pair[0], pair[1]))

    leaves = [(start, end, open_tag) for start, end, open_tag, close_tag in spans if not close_tag]
    wrapped = [(start, end, open_tag, close_tag) for start, end, open_tag, close_tag in spans if close_tag]
    leaf_at = {start: (end, open_tag) for start, end, open_tag in leaves}

    def _active(pos: int) -> list[tuple[int, int, str, str]]:
        found = [item for item in wrapped if item[0] <= pos < item[1]]
        found.sort(key=lambda item: (item[0], item[0] - item[1]))
        return found

    parts: list[str] = []
    stack: list[tuple[int, int, str, str]] = []
    index = 0
    length = len(text)
    while index <= length:
        active = _active(index)
        common = 0
        while common < len(stack) and common < len(active) and stack[common] == active[common]:
            common += 1
        while len(stack) > common:
            parts.append(stack.pop()[3])
        while len(stack) < len(active):
            opened = active[len(stack)]
            parts.append(opened[2])
            stack.append(opened)
        if index == length:
            break
        leaf = leaf_at.get(index)
        if leaf:
            end, open_tag = leaf
            parts.append(open_tag)
            index = end
            continue
        parts.append(html.escape(text[index], quote=False))
        index += 1
    while stack:
        parts.append(stack.pop()[3])
    return upgrade_pack_emoji("".join(parts))
