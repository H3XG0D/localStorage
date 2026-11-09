"""Единый pipeline маскирования PII/секретов (deny-sensitive by default).

Используется перед внешним LLM и перед записью в защищённый AI-аудит.
Не логирует исходный текст.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

# Email
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Телефоны (RU/международные фрагменты)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d[\d\-\s()]{8,}\d)(?!\w)"
)
# Telegram @username и числовые id в типичных контекстах
_TG_USER_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{4,32}\b")
_TG_ID_CTX_RE = re.compile(
    r"(?i)\b(?:tg(?:ram)?[_\s-]?id|telegram[_\s-]?(?:user[_\s-]?)?id|chat[_\s-]?id|user[_\s-]?id)\s*[:=]?\s*-?\d{5,}\b"
)
_BARE_LONG_ID_RE = re.compile(r"(?<!\w)-?\d{9,15}(?!\w)")
# Кошельки / адреса
_TRON_RE = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")
_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BTC_RE = re.compile(r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}\b")
_LTC_RE = re.compile(r"\b(?:ltc1|[LM3])[a-zA-HJ-NP-Z0-9]{25,62}\b")
# Документы / карты
_PASSPORT_RE = re.compile(r"(?i)\b(?:passport|паспорт)\s*[:=]?\s*\d{4}\s?\d{6}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
# Секреты / токены / ключи
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|authorization|"
    r"private[_-]?key|jwt|dsn|database_url|openai[_-]?api[_-]?key|"
    r"ops_ai_[a-z0-9_]*key|sticker_ai_worker_token|x[_-]?internal[_-]?token|"
    r"internal[_-]?token|focuspay_ssh_password|"
    r"merchant[_-]?(?:api|secret)[_-]?key|"
    r"webhook[_-]?secret|callback[_-]?secret|bot[_-]?token)\b\s*[:=]\s*([^\s,;\"']{6,})"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
_HEADER_TOKEN_RE = re.compile(
    r"(?i)\b(X-Internal-Token|Internal-Token|X-Api-Key)\s*[:=]\s*([^\s,;\"']{6,})"
)
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_token|api_key|token|secret|password|x_internal_token)=)([^&\s#]+)"
)
_INTERNAL_URL_RE = re.compile(
    r"(?i)\bhttps?://(?:127\.0\.0\.1|localhost|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(?::\d+)?(?:/[^\s]*)?"
)
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")

_REDACT = "[REDACTED]"
_PSEUDO_SALT = "focuspay-privacy-v1"


def correlation_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(f"{_PSEUDO_SALT}:{raw}".encode()).hexdigest()[:24]


def pseudonym(value: Any, *, prefix: str = "id") -> str:
    """Стабильный псевдоним для логов (не обратим без brute-force)."""
    h = hashlib.sha256(f"{_PSEUDO_SALT}:{prefix}:{value}".encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def redact_text(text: str | None, *, keep_short_ids: bool = False) -> str:
    if not text:
        return ""
    out = str(text)
    out = _PEM_RE.sub(_REDACT, out)
    out = _JWT_RE.sub(_REDACT, out)
    out = _BEARER_RE.sub(f"Bearer {_REDACT}", out)
    out = _HEADER_TOKEN_RE.sub(lambda m: f"{m.group(1)}: {_REDACT}", out)
    out = _SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}={_REDACT}", out)
    out = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}{_REDACT}", out)
    out = _INTERNAL_URL_RE.sub("[INTERNAL_URL]", out)
    out = _EMAIL_RE.sub(_REDACT, out)
    out = _PHONE_RE.sub(_REDACT, out)
    out = _TG_ID_CTX_RE.sub(lambda m: re.sub(r"-?\d{5,}", _REDACT, m.group(0)), out)
    out = _TG_USER_RE.sub(_REDACT, out)
    out = _TRON_RE.sub(_REDACT, out)
    out = _ETH_RE.sub(_REDACT, out)
    out = _BTC_RE.sub(_REDACT, out)
    out = _LTC_RE.sub(_REDACT, out)
    out = _PASSPORT_RE.sub(_REDACT, out)
    # Карты: только если похоже на PAN (Luhn-ish length), не трогаем order fiat
    def _card_sub(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19:
            return _REDACT
        return m.group(0)

    out = _CARD_RE.sub(_card_sub, out)
    if not keep_short_ids:
        out = _BARE_LONG_ID_RE.sub(_REDACT, out)
    return out


def redact_mapping(data: dict[str, Any] | None, *, allow: frozenset[str] | None = None) -> dict[str, Any]:
    """Deny-by-default: оставляет только allowlist ключи, значения редактирует."""
    if not data:
        return {}
    allowed = allow or frozenset()
    out: dict[str, Any] = {}
    for k, v in data.items():
        key = str(k)
        if key not in allowed:
            continue
        if v is None:
            out[key] = None
        elif isinstance(v, (int, float, bool)):
            out[key] = v
        elif isinstance(v, str):
            out[key] = redact_text(v, keep_short_ids=True)[:2000]
        elif isinstance(v, dict):
            out[key] = redact_mapping(v, allow=allowed)
        else:
            out[key] = redact_text(str(v), keep_short_ids=True)[:500]
    return out


# Safe UI fields for LLM/audit (no PII dump)
UI_CONTEXT_ALLOW = frozenset(
    {
        "path",
        "search",
        "title",
        "hint",
        "order_id",
        # client_id intentionally omitted unless hashed separately
    }
)

AUDIT_META_ALLOW = frozenset(
    {
        "path",
        "order_id",
        "provider",
        "model",
        "has_images",
        "rag_hits",
        "escalate",
        "session_id",
        "task_id",
        "consent_version",
        "error_class",
    }
)
