"""Скоринг рекламного спама в публичных Telegram-чатах FocusPay.

Не каталог магазинов: фразы-маркеры, шортнеры, стена эмодзи, пачка ссылок.
Порог 3: один сильный сигнал (+3) или два слабых (+2).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse
from collections.abc import Sequence

SCORE_THRESHOLD = 3
PHRASE_SCORE = 3
SHORTENER_SCORE = 2
MANY_LINKS_SCORE = 2
EMOJI_WALL_SCORE = 2
MANY_LINKS_MIN = 3
EMOJI_COUNT_MIN = 25
EMOJI_REPEAT_MIN = 6

DEFAULT_WHITELIST_HOSTS = frozenset(
    {
        "focuspay.org",
        "www.focuspay.org",
    }
)
DEFAULT_WHITELIST_TME = frozenset(
    {
        "focuspayr",
        "focuspay1_bot",
    }
)
SHORTENER_HOSTS = frozenset(
    {
        "clck.ru",
        "bit.ly",
        "tinyurl.com",
        "tinyurl",
        "cutt.ly",
        "t.ly",
        "vk.cc",
        "goo.gl",
    }
)

# Латиница, которой маскируют кириллицу в «лс» / «пишите».
_HOMOGLYPHS = str.maketrans(
    {
        "a": "а",
        "e": "е",
        "o": "о",
        "p": "р",
        "c": "с",
        "x": "х",
        "y": "у",
        "h": "н",
        "k": "к",
        "m": "м",
        "t": "т",
    }
)

BUILTIN_PHRASE_LABELS: tuple[str, ...] = (
    "боты распределители",
    "пополнение адресов",
    "в поиске курьеров",
    "тадж банк",
    "жми на кнопки снизу",
    "актуальные контакты",
    "пишите в лс",
    "писать в лс",
    "пишите в личные",
    "зп в день",
    "заработок в интернете",
    "ищу партнеров",
)

_PHRASE_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"бот(?:ы)?\s*распределител",
        r"пополнение\s+адресов",
        r"в\s+поиске\s+курьер",
        r"тадж\s*банк",
        r"жми\s+на\s+кнопки\s+снизу",
        r"актуальн(?:ые|ых|ыми)?\s+контакт",
        r"пишите\s+в\s+лс",
        r"писать\s+в\s+лс",
        r"(?<![\w])(?:пиши(?:те)?|писать|напиши(?:те)?|отпиши(?:те)?)\s*,?\s*(?:мне\s+)?в\s+лич",
        r"(?:з/?п|зарплат\w{0,6})\s*(?:от\s*)?\d[\d\s]*\s*(?:[-–—]\s*\d[\d\s]*)?\s*(?:к|тыс\w{0,6})?\s*(?:в|/)\s*день",
        r"(?<!\d)\d{1,3}\s*[-–—]\s*\d{1,3}\s*(?:к|тыс\w{0,6})\s*(?:в|/)\s*день",
        r"заработок\s+в\s+интернете",
        r"ищу\s+партнеров",
    )
)

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
_EMOJI_RE = re.compile(
    r"(?:"
    r"[#*0-9]\uFE0F?\u20E3"
    r"|[\U0001F1E6-\U0001F1FF]{2}"
    r"|(?:[\U0001F100-\U0001FAFF]|[\U00002600-\U000027BF]|[\U00002300-\U000023FF])\uFE0F?"
    r")"
)


@dataclass(frozen=True)
class SpamVerdict:
    score: int
    reasons: tuple[str, ...]
    is_spam: bool


def normalize_for_phrases(text: str) -> str:
    raw = unicodedata.normalize("NFKC", text or "")
    raw = raw.replace("ё", "е").replace("Ё", "е")
    raw = raw.lower()
    raw = _ZW_RE.sub("", raw)
    raw = raw.translate(_HOMOGLYPHS)
    return re.sub(r"\s+", " ", raw).strip()


def extract_urls(text: str, extra_urls: Sequence[str] | None = None) -> list[str]:
    found = [m.group(0).rstrip(".,;:!?)") for m in _URL_RE.finditer(text or "")]
    if extra_urls:
        for item in extra_urls:
            cleaned = (item or "").strip().rstrip(".,;:!?)")
            if cleaned:
                found.append(cleaned)
    return found


def _with_scheme(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if re.match(r"^https?://", raw, re.I):
        return raw
    if raw.lower().startswith("www."):
        return "http://" + raw
    return "http://" + raw


def _hostname(url: str) -> str:
    parsed = urlparse(_with_scheme(url))
    return (parsed.hostname or "").lower().rstrip(".")


def _tme_username(url: str) -> str:
    parsed = urlparse(_with_scheme(url))
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        return ""
    part = parsed.path.lstrip("/").split("/", 1)[0]
    return part.lower()


def _is_whitelisted(
    url: str,
    *,
    extra_tme: frozenset[str],
) -> bool:
    host = _hostname(url)
    if not host:
        return False
    if host in DEFAULT_WHITELIST_HOSTS or host.endswith(".focuspay.org"):
        return True
    tme = _tme_username(url)
    if tme and tme in DEFAULT_WHITELIST_TME.union(extra_tme):
        return True
    return False


def _is_shortener(url: str) -> bool:
    host = _hostname(url)
    if not host:
        return False
    if host in SHORTENER_HOSTS:
        return True
    return any(host == item or host.endswith("." + item) for item in SHORTENER_HOSTS)


def _emoji_tokens(text: str) -> list[str]:
    return _EMOJI_RE.findall(text or "")


def _emoji_wall(text: str) -> bool:
    tokens = _emoji_tokens(text)
    if len(tokens) >= EMOJI_COUNT_MIN:
        return True
    run = 1
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            run += 1
            if run >= EMOJI_REPEAT_MIN:
                return True
        else:
            run = 1
    return False


def check_group_spam(
    text: str,
    extra_urls: Sequence[str] | None = None,
    *,
    extra_tme_usernames: Sequence[str] | None = None,
    extra_phrases: Sequence[str] | None = None,
) -> SpamVerdict:
    body = text or ""
    extra_tme = frozenset(
        u.strip().lstrip("@").lower()
        for u in (extra_tme_usernames or ())
        if u and u.strip()
    )
    urls = extract_urls(body, extra_urls)
    reasons: list[str] = []
    score = 0

    normalized = normalize_for_phrases(body)
    extra_hits = [
        normalize_for_phrases(p)
        for p in (extra_phrases or ())
        if p and str(p).strip()
    ]
    extra_hits = [p for p in extra_hits if p and p in normalized]
    if any(p.search(normalized) for p in _PHRASE_PATTERNS) or extra_hits:
        score += PHRASE_SCORE
        reasons.append("phrase")

    external = [u for u in urls if not _is_whitelisted(u, extra_tme=extra_tme)]
    if any(_is_shortener(u) for u in external):
        score += SHORTENER_SCORE
        reasons.append("shortener")
    if len(external) >= MANY_LINKS_MIN:
        score += MANY_LINKS_SCORE
        reasons.append("many_links")
    if _emoji_wall(body):
        score += EMOJI_WALL_SCORE
        reasons.append("emoji_wall")

    return SpamVerdict(
        score=score,
        reasons=tuple(reasons),
        is_spam=score >= SCORE_THRESHOLD,
    )
