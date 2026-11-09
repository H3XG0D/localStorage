"""Санитизация пользовательского/канального текста перед сохранением и рассылкой."""
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_SCRIPT_BLOCK_RE = re.compile(r"<\s*script[^>]*>.*?</script>", re.I | re.S)
_DANGEROUS_TAG_RE = re.compile(
    r"<\s*(iframe|object|embed|style|link|meta|form|input)\b[^>]*>.*?</\1>",
    re.I | re.S,
)
_VOID_DANGEROUS_RE = re.compile(
    r"<\s*(iframe|object|embed|input)\b[^>]*?/?>",
    re.I,
)
_EVENT_HANDLER_RE = re.compile(r"\s(on\w+)\s*=\s*['\"][^'\"]*['\"]", re.I)
_JS_HREF_RE = re.compile(
    r"""href\s*=\s*['"]?\s*javascript:[^'">]*['"]?""",
    re.I,
)
# Telegram HTML не знает <br>/<p>/<div> — только перевод строки.
_BR_TAG_RE = re.compile(r"<\s*br\b[^>]*?/?>", re.I)
_BLOCK_CLOSE_RE = re.compile(r"<\s*/\s*(p|div|li|h[1-6]|tr)\s*>", re.I)
_BLOCK_OPEN_RE = re.compile(r"<\s*(p|div|li|h[1-6]|tr)\b[^>]*>", re.I)
_NBSP_RE = re.compile(r"&nbsp;|&#160;", re.I)
_MULTI_NL_RE = re.compile(r"\n{3,}")


class _TelegramMarkupSanitizer(HTMLParser):
    _ALLOWED_TAGS = frozenset(
        {
            "b",
            "strong",
            "i",
            "em",
            "u",
            "ins",
            "s",
            "strike",
            "del",
            "tg-spoiler",
            "code",
            "pre",
            "blockquote",
            "a",
        }
    )
    _ALLOWED_ENTITIES = frozenset({"lt", "gt", "amp", "quot"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._tg_emoji_open = 0

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if name in self._ALLOWED_ENTITIES:
            self.parts.append(f"&{name};")
        else:
            self.parts.append(html.escape(f"&{name};", quote=False))

    def handle_charref(self, name: str) -> None:
        self.parts.append(html.escape(f"&#{name};", quote=False))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tg-emoji":
            emoji_id = str(dict(attrs).get("emoji-id") or "")
            if emoji_id.isdigit() and 5 <= len(emoji_id) <= 32:
                self._tg_emoji_open += 1
                self.parts.append(f'<tg-emoji emoji-id="{emoji_id}">')
            return
        if tag not in self._ALLOWED_TAGS:
            self.parts.append(
                html.escape(self.get_starttag_text() or f"<{tag}>", quote=False)
            )
            return
        if tag != "a":
            self.parts.append(f"<{tag}>")
            return

        href = dict(attrs).get("href")
        parsed = urlsplit(href or "")
        if not href or parsed.scheme not in {"http", "https", "tg"}:
            self.parts.append(
                html.escape(self.get_starttag_text() or "<a>", quote=False)
            )
            return
        self.parts.append(f'<a href="{html.escape(href, quote=True)}">')

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "tg-emoji":
            if self._tg_emoji_open:
                self._tg_emoji_open -= 1
                self.parts.append("</tg-emoji>")
            return
        if tag in self._ALLOWED_TAGS:
            self.parts.append(f"</{tag}>")
        else:
            self.parts.append(html.escape(f"</{tag}>", quote=False))

    def handle_comment(self, data: str) -> None:
        self.parts.append(html.escape(f"<!--{data}-->", quote=False))


def _sanitize_telegram_markup(text: str) -> str:
    parser = _TelegramMarkupSanitizer()
    parser.feed(text)
    parser.close()
    return "".join(parser.parts)


def strip_html(text: str) -> str:
    return _STRIP_TAGS_RE.sub("", text or "")


def sanitize_review_text(text: str, max_len: int = 4000) -> str:
    """Отзывы на сайте — только plain text."""
    return strip_html(text).strip()[:max_len]


def sanitize_author_name(name: str | None, max_len: int = 120) -> str | None:
    if not name:
        return None
    return html.escape(strip_html(name).strip()[:max_len], quote=False)


def sanitize_telegram_html(text: str, max_len: int = 4096) -> str:
    """
    Рассылка админов: убираем опасные теги/JS, оставляем базовую Telegram-разметку.
    <br>/<p>/<div> конвертируем в переносы строк (Telegram их не парсит).
    """
    if not text:
        return ""
    t = text[: max_len * 2]  # запас до конвертации тегов в \n
    t = _SCRIPT_BLOCK_RE.sub("", t)
    t = _DANGEROUS_TAG_RE.sub("", t)
    t = _VOID_DANGEROUS_RE.sub("", t)
    t = _EVENT_HANDLER_RE.sub("", t)
    t = _JS_HREF_RE.sub('href="#"', t)
    t = _BR_TAG_RE.sub("\n", t)
    t = _BLOCK_CLOSE_RE.sub("\n", t)
    t = _BLOCK_OPEN_RE.sub("", t)
    t = _NBSP_RE.sub(" ", t)
    t = _MULTI_NL_RE.sub("\n\n", t)
    return _sanitize_telegram_markup(t).strip()[:max_len]
