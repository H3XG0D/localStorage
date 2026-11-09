"""Referral deep links (shared logic with exchange backend)."""
import os
import re
import secrets
import string

_REF_ALPHABET = string.ascii_lowercase + string.digits
_REF_LEN = 18
_START_PREFIX = "ref_"
_USER_REF_PREFIX = "uref_"
_TME_START_RE = re.compile(
    r"[?&]start=(uref_[a-z0-9]+|ref_[a-z0-9]+|[a-z0-9]{4,32})",
    re.IGNORECASE,
)
_TG_RESOLVE_START_RE = re.compile(
    r"tg://resolve(?:\?[^#\s]*)?[?&]start=(uref_[a-z0-9]+|ref_[a-z0-9]+|[a-z0-9]{4,32})",
    re.IGNORECASE,
)
_START_CMD_RE = re.compile(
    r"^/start(?:@[\w]+)?\s+(uref_[a-z0-9]+|ref_[a-z0-9]+|[a-z0-9]{4,32})\b",
    re.IGNORECASE,
)
_UREF_INLINE_RE = re.compile(r"uref_[a-z0-9]{4,32}", re.IGNORECASE)
_INVITE_PATH_RE = re.compile(r"/invite/([a-z0-9]{4,32})", re.IGNORECASE)
_REF_PATH_RE = re.compile(r"/ref/([a-z0-9]{4,32})", re.IGNORECASE)
_ANY_START_RE = re.compile(
    r"[?&]start=((?:uref_|ref_)?[a-z0-9]{4,32})",
    re.IGNORECASE,
)
_ANY_START_CMD_RE = re.compile(
    r"^/start(?:@[\w]+)?\s+((?:uref_|ref_)?[a-z0-9]{4,32})\b",
    re.IGNORECASE,
)


def _bot_username() -> str:
    return (
        os.getenv("BOT_USERNAME")
        or os.getenv("TELEGRAM_BOT_USERNAME")
        or "focuspay1_bot"
    ).lstrip("@")


def generate_ref_token(length: int = _REF_LEN) -> str:
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(length))


def telegram_start_payload(ref_token: str) -> str:
    return f"{_START_PREFIX}{ref_token}"


def telegram_deep_link(ref_token: str, bot_username: str | None = None) -> str:
    bot = (bot_username or _bot_username()).lstrip("@")
    return f"https://t.me/{bot}?start={telegram_start_payload(ref_token)}"


def web_ref_path(ref_token: str) -> str:
    return f"/ref/{ref_token}"


def web_ref_link(ref_token: str, site_base: str | None = None) -> str:
    base = (site_base or os.getenv("PUBLIC_SITE_URL", "http://localhost:5173")).rstrip("/")
    return f"{base}{web_ref_path(ref_token)}"


def user_referral_start_payload(ref_token: str) -> str:
    return f"{_USER_REF_PREFIX}{ref_token}"


def user_telegram_deep_link(ref_token: str, bot_username: str | None = None) -> str:
    bot = (bot_username or _bot_username()).lstrip("@")
    return f"https://t.me/{bot}?start={user_referral_start_payload(ref_token)}"


def web_user_invite_path(ref_token: str) -> str:
    return f"/invite/{ref_token}"


def web_user_invite_link(ref_token: str, site_base: str | None = None) -> str:
    base = (site_base or os.getenv("PUBLIC_SITE_URL", "https://focuspay.org")).rstrip("/")
    return f"{base}{web_user_invite_path(ref_token)}"


def parse_user_referral_payload(payload: str) -> str | None:
    p = (payload or "").strip()
    if not p.startswith(_USER_REF_PREFIX):
        return None
    token = p[len(_USER_REF_PREFIX) :].strip().lower()
    if not token or len(token) > 32:
        return None
    if not all(c in _REF_ALPHABET for c in token):
        return None
    return token


def extract_user_referral_token(raw: str) -> str | None:
    """uref_TOKEN, bare user ref token (not ref_/promo_)."""
    p = (raw or "").strip()
    if not p:
        return None
    tok = parse_user_referral_payload(p)
    if tok:
        return tok
    if p.startswith(_START_PREFIX) or p.startswith("promo_"):
        return None
    if len(p) <= 32 and all(c in _REF_ALPHABET for c in p.lower()):
        return p.lower()
    return None


def _token_from_start_param(part: str) -> str | None:
    """Bare-токен из start-параметра (ref_/uref_/bare). promo_ — не токен."""
    return strip_ref_prefixes(part)


def extract_referral_token_from_text(text: str) -> str | None:
    """Ссылка из чата: t.me?start=ref_/uref_..., /invite|/ref/TOKEN, uref_ в тексте.

    Не принимает «голый» alphanumeric текст без URL/команды — только явные ссылки.
    """
    t = text or ""
    for pattern in (_START_CMD_RE, _TME_START_RE, _TG_RESOLVE_START_RE, _ANY_START_RE):
        m = pattern.search(t)
        if m:
            tok = _token_from_start_param(m.group(1))
            if tok:
                return tok
    m = _UREF_INLINE_RE.search(t)
    if m:
        return strip_ref_prefixes(m.group(0))
    m = _INVITE_PATH_RE.search(t)
    if m:
        return strip_ref_prefixes(m.group(1))
    m = _REF_PATH_RE.search(t)
    if m:
        return strip_ref_prefixes(m.group(1))
    return None


def message_referral_token(message) -> str | None:
    """Токен из текста сообщения и скрытых URL в entities."""
    if not message:
        return None
    text = message.text or message.caption or ""
    token = extract_referral_token_from_text(text)
    if token:
        return token
    for ent in message.entities or message.caption_entities or []:
        etype = getattr(ent, "type", None)
        if etype not in ("url", "text_link"):
            continue
        if etype == "text_link":
            chunk = getattr(ent, "url", None) or text[ent.offset : ent.offset + ent.length]
        else:
            chunk = text[ent.offset : ent.offset + ent.length]
        token = extract_referral_token_from_text(chunk)
        if token:
            return token
    return None


def strip_ref_prefixes(value: str) -> str | None:
    """Bare-токен из ref_X / uref_X / bare X. promo_ не является токеном."""
    p = (value or "").strip().lower()
    if not p:
        return None
    if p.startswith(_USER_REF_PREFIX):
        p = p[len(_USER_REF_PREFIX):]
    elif p.startswith(_START_PREFIX):
        p = p[len(_START_PREFIX):]
    elif p.startswith("promo_"):
        return None
    # Мин. 4 символа — как в URL-паттернах; отсекает ответы капчи ("42").
    if p and 4 <= len(p) <= 32 and all(c in _REF_ALPHABET for c in p):
        return p
    return None


def extract_any_ref_token(payload: str) -> str | None:
    """
    Единый bare-токен из ЛЮБОГО формата реферальной ссылки:
    ref_X, uref_X, /ref/X, /invite/X, t.me?start=..., tg://resolve, /start X, bare X.

    Не различает партнёра и обычного реферера — определение владельца токена
    (bot_users vs promo_campaigns) выполняется на этапе привязки.
    """
    p = (payload or "").strip()
    if not p:
        return None

    direct = strip_ref_prefixes(p)
    if direct:
        return direct

    m = _INVITE_PATH_RE.search(p)
    if m:
        return strip_ref_prefixes(m.group(1))
    m = _REF_PATH_RE.search(p)
    if m:
        return strip_ref_prefixes(m.group(1))

    for pattern in (_ANY_START_CMD_RE, _ANY_START_RE, _TG_RESOLVE_START_RE):
        m = pattern.search(p)
        if m:
            tok = strip_ref_prefixes(m.group(1))
            if tok:
                return tok

    m = _UREF_INLINE_RE.search(p)
    if m:
        return strip_ref_prefixes(m.group(0))
    return None


def parse_start_payload(payload: str) -> str | None:
    p = (payload or "").strip()
    if not p:
        return None
    if p.startswith(_USER_REF_PREFIX):
        return None
    if p.startswith(_START_PREFIX):
        return p[len(_START_PREFIX) :].strip().lower() or None
    if p.startswith("promo_"):
        return None
    if len(p) <= 32 and all(c in _REF_ALPHABET for c in p.lower()):
        return p.lower()
    return None
