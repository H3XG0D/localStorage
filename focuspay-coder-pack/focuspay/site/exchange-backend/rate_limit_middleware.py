"""Блокирующий rate limit для /api (429 до обработки запроса)."""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from client_ip import get_client_ip
from ip_blocklist import is_ip_banned
from onion_access import request_is_onion
from security_threats import is_ip_rate_limited
from trusted_ips import is_trusted_ip

logger = logging.getLogger("rate_limit")

# Публичные реф-лендинги — не блокируем (рекламные ссылки должны открываться всегда).
# ТОЛЬКО GET эндпоинты для просмотра страниц. POST /attribution/track должен проходить
# через IP ban + rate limit для защиты от unbounded синтетических users.
_REF_PUBLIC_PREFIX = "/api/public/ref/"
_INVITE_PUBLIC_PREFIX = "/api/public/invite/"


# Публичные read-only эндпоинты — не режем по IP-ban (курсы/отзывы для всех).
_PUBLIC_READ_GET = frozenset({
    "/api/public/rates",
    "/api/public/reviews",
    "/api/public/site-config",
})

# Signed static media — nginx must also skip api_limit; list of chats loads dozens.
_MEDIA_PREFIXES = (
    "/api/public/bot-user-avatars/",
    "/api/public/casino-avatars/",
    "/api/public/casino-idents/",
    "/api/public/chat/attachments/",
    "/api/public/operator-avatars/",
)
_EXCHANGER_BOT_PREFIX = "/api/bot/exchanger/"
_EXCHANGER_HMAC_PREFIX = "/api/exchanger/v1/"
# Casino/exchange bots share one IP; the scanner bucket must not 429 their
# token-authenticated internal calls (60 concurrent tables is normal load).
_INTERNAL_API_PREFIX = "/api/internal/"

# Authed casino autoplay is ~1 POST/round plus quote/tape/balance. The global
# IP bucket (240/min) is for scanners; counting dice rounds into it 429s the
# whole site (including /auth/login → «Слишком много попыток входа»).
_AUTHED_CASINO_PREFIXES = (
    "/api/user/casino/",
    "/api/public/casino/",
)
_AUTHED_CASINO_EXACT = frozenset({
    "/api/user/balance",
    "/api/auth/me",
})


def _has_bearer(authorization: str | None) -> bool:
    raw = (authorization or "").strip()
    return raw.lower().startswith("bearer ") and len(raw) > 8


def skips_ip_rate_limit(path: str, *, has_bearer: bool) -> bool:
    """Play/session GETs with a bearer do not consume the scanner IP bucket."""
    if not has_bearer:
        return False
    if path in _AUTHED_CASINO_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _AUTHED_CASINO_PREFIXES)


def _is_public_readonly_api(path: str, method: str) -> bool:
    if method.upper() != "GET":
        return False
    if path in _PUBLIC_READ_GET:
        return True
    return any(path.startswith(prefix) for prefix in _MEDIA_PREFIXES)


def _is_public_referral_api(path: str, method: str) -> bool:
    """Только GET эндпоинты реф-лендингов bypass rate limit.
    POST /attribution/track проходит через обычные проверки."""
    if method.upper() != "GET":
        return False
    return (
        path.startswith(_REF_PUBLIC_PREFIX)
        or path.startswith(_INVITE_PUBLIC_PREFIX)
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)
        if _is_public_referral_api(path, request.method):
            return await call_next(request)
        if path.startswith(_EXCHANGER_BOT_PREFIX):
            return await call_next(request)
        if path.startswith(_EXCHANGER_HMAC_PREFIX):
            return await call_next(request)
        if path.startswith(_INTERNAL_API_PREFIX):
            return await call_next(request)
        if _is_public_readonly_api(path, request.method):
            return await call_next(request)
        skip_ip_limit = skips_ip_rate_limit(
            path, has_bearer=_has_bearer(request.headers.get("authorization"))
        )

        ip = get_client_ip(request)
        onion = request_is_onion(request)
        if ip and not onion and not is_trusted_ip(ip) and is_ip_banned(ip):
            logger.warning("ip blocklist deny ip=%s path=%s", ip, path)
            return JSONResponse(
                {"detail": "Доступ временно ограничен."},
                status_code=403,
            )
        if (
            not skip_ip_limit
            and ip
            and not onion
            and not is_trusted_ip(ip)
            and is_ip_rate_limited(ip)
        ):
            logger.warning("rate limit block ip=%s path=%s", ip, path)
            return JSONResponse(
                {"detail": "Слишком много запросов. Попробуйте позже."},
                status_code=429,
            )
        return await call_next(request)
