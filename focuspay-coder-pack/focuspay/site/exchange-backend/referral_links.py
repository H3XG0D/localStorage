"""Referral deep links: web /ref/<token> and Telegram ?start=ref_<token>."""
import re
import secrets
import string

from config import settings

_REF_ALPHABET = string.ascii_lowercase + string.digits
_REF_LEN = 18
_START_PREFIX = "ref_"
_USER_REF_PREFIX = "uref_"
_TME_START_RE = re.compile(
    r"[?&]start=(uref_[a-z0-9]+|ref_[a-z0-9]+|[a-z0-9]{4,32})",
    re.IGNORECASE,
)
_UREF_INLINE_RE = re.compile(r"uref_[a-z0-9]{4,32}", re.IGNORECASE)
_INVITE_PATH_RE = re.compile(r"/invite/([a-z0-9]{4,32})", re.IGNORECASE)


def generate_ref_token(length: int = _REF_LEN) -> str:
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(length))


def telegram_start_payload(ref_token: str) -> str:
    return f"{_START_PREFIX}{ref_token}"


def telegram_deep_link(ref_token: str, bot_username: str | None = None) -> str:
    bot = (bot_username or settings.telegram_bot_username or "focuspay1_bot").lstrip("@")
    return f"https://t.me/{bot}?start={telegram_start_payload(ref_token)}"


def web_ref_path(ref_token: str) -> str:
    return f"/ref/{ref_token}"


def web_ref_link(ref_token: str, site_base: str | None = None) -> str:
    base = (site_base or settings.public_site_url or "http://localhost:5173").rstrip("/")
    return f"{base}{web_ref_path(ref_token)}"


def web_onion_ref_link(ref_token: str, site_base: str | None = None) -> str | None:
    from onion_access import normalize_onion_origin, public_onion_url

    base = normalize_onion_origin(site_base) if site_base else public_onion_url()
    if not base:
        return None
    return f"{base}{web_ref_path(ref_token)}"


def user_referral_start_payload(ref_token: str) -> str:
    return f"{_USER_REF_PREFIX}{ref_token}"


def user_telegram_deep_link(ref_token: str, bot_username: str | None = None) -> str:
    bot = (bot_username or settings.telegram_bot_username or "focuspay1_bot").lstrip("@")
    return f"https://t.me/{bot}?start={user_referral_start_payload(ref_token)}"


def web_user_invite_path(ref_token: str) -> str:
    return f"/invite/{ref_token}"


def web_user_invite_link(ref_token: str, site_base: str | None = None) -> str:
    base = (site_base or settings.public_site_url or "http://localhost:5173").rstrip("/")
    return f"{base}{web_user_invite_path(ref_token)}"


def web_onion_invite_link(ref_token: str, site_base: str | None = None) -> str | None:
    from onion_access import normalize_onion_origin, public_onion_url

    base = normalize_onion_origin(site_base) if site_base else public_onion_url()
    if not base:
        return None
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


def extract_referral_token_from_text(text: str) -> str | None:
    t = text or ""
    m = _TME_START_RE.search(t)
    if m:
        part = m.group(1).lower()
        if part.startswith(_USER_REF_PREFIX):
            return parse_user_referral_payload(part)
        if part.startswith(_START_PREFIX):
            return None
        return extract_user_referral_token(part)
    m = _UREF_INLINE_RE.search(t)
    if m:
        return parse_user_referral_payload(m.group(0))
    m = _INVITE_PATH_RE.search(t)
    if m:
        return extract_user_referral_token(m.group(1))
    return None


def parse_start_payload(payload: str) -> str | None:
    """Extract ref_token from /start argument."""
    p = (payload or "").strip()
    if not p:
        return None
    if p.startswith(_USER_REF_PREFIX):
        return None
    if p.startswith(_START_PREFIX):
        return p[len(_START_PREFIX) :].strip() or None
    if p.startswith("promo_"):
        return None
    if len(p) <= 32 and all(c in _REF_ALPHABET for c in p.lower()):
        return p.lower()
    return None
