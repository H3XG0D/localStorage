"""Санитизация текста перед рассылкой в Telegram."""
import re

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


def sanitize_telegram_html(text: str, max_len: int = 4096) -> str:
    """
    Убираем опасные теги/JS, оставляем базовую Telegram-разметку.
    <br>/<p>/<div> конвертируем в переносы строк (Telegram их не парсит).
    """
    if not text:
        return ""
    t = text[: max_len * 2]
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
    return t.strip()[:max_len]
