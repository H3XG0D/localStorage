"""Нормализация и валидация фраз антиспама (литерал, не regex).

Держать в синхроне с bot/tg_bot_btc/services/group_spam_filter.py.
"""
from __future__ import annotations

import re
import unicodedata

PHRASE_MIN_LEN = 4
PHRASE_MAX_LEN = 120

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
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")

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


def normalize_for_phrases(text: str) -> str:
    raw = unicodedata.normalize("NFKC", text or "")
    raw = raw.replace("ё", "е").replace("Ё", "е")
    raw = raw.lower()
    raw = _ZW_RE.sub("", raw)
    raw = raw.translate(_HOMOGLYPHS)
    return re.sub(r"\s+", " ", raw).strip()


def prepared_phrase(raw: str) -> tuple[str, str] | None:
    """(display, normalized) или None если после нормализации пусто."""
    display = re.sub(r"\s+", " ", (raw or "").strip())
    if not display:
        return None
    normalized = normalize_for_phrases(display)
    if not normalized:
        return None
    return display, normalized


def validate_operator_phrase(raw: str) -> tuple[str, str]:
    prepared = prepared_phrase(raw)
    if prepared is None:
        raise ValueError("Введите слово или фразу")
    display, normalized = prepared
    if len(normalized) < PHRASE_MIN_LEN:
        raise ValueError(f"Слишком коротко: минимум {PHRASE_MIN_LEN} символа")
    if len(normalized) > PHRASE_MAX_LEN:
        raise ValueError(f"Слишком длинно: максимум {PHRASE_MAX_LEN} символов")
    return display, normalized
