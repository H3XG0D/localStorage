"""HttpOnly cookies для панелей admin/operator."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request, Response

from config import settings
from onion_access import request_is_onion

ADMIN_COOKIE = "focuspay_admin_token"
OPERATOR_COOKIE = "focuspay_operator_token"
GUEST_COOKIE = "focuspay_guest_session"
USER_COOKIE = "focuspay_user_session"
COOKIE_MAX_AGE = int(timedelta(hours=4).total_seconds())
GUEST_COOKIE_MAX_AGE = int(timedelta(days=30).total_seconds())
GUEST_SESSION_GRACE_END = datetime(2026, 8, 28, tzinfo=timezone.utc)
# Постоянная сессия покупателя — чтобы заходить на сайт без повторного логина.
USER_COOKIE_MAX_AGE = int(timedelta(days=30).total_seconds())


def _cookie_secure(request: Request | None = None) -> bool:
    # HTTP .onion is already encrypted by Tor; Secure cookies would never stick.
    if request_is_onion(request):
        return False
    if request is not None:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").strip().lower()
        if proto:
            return proto == "https"
    site = (settings.public_site_url or "").strip().lower()
    return site.startswith("https://")


def set_guest_cookie(response: Response, token: str, request: Request | None = None) -> bool:
    """Установить guest cookie, не позволяя заголовку перезаписать чужую привязку."""
    if not token:
        return False
    existing = read_guest_cookie(request) if request is not None else None
    if existing and existing != token:
        return False
    response.set_cookie(
        key=GUEST_COOKIE,
        value=token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=GUEST_COOKIE_MAX_AGE,
        path="/",
    )
    return True


def read_guest_cookie(request: Request) -> str | None:
    return request.cookies.get(GUEST_COOKIE)


def guest_session_trusted(
    request: Request,
    x_guest_session: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Проверить HttpOnly-привязку guest session с ограниченным legacy grace period.

    Совпавшие cookie и header доверены. Header без cookie разрешён только до
    ``GUEST_SESSION_GRACE_END``; после grace policy fail-secure. Отсутствующий
    header и любая несовпавшая пара всегда отклоняются.
    """
    if not x_guest_session:
        return False

    cookie = read_guest_cookie(request)
    if cookie:
        return cookie == x_guest_session

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current < GUEST_SESSION_GRACE_END


def set_panel_cookie(response: Response, *, scope: str, token: str, request: Request | None = None) -> None:
    name = ADMIN_COOKIE if scope == "admin" else OPERATOR_COOKIE
    response.set_cookie(
        key=name,
        value=token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


def clear_panel_cookie(response: Response, *, scope: str) -> None:
    name = ADMIN_COOKIE if scope == "admin" else OPERATOR_COOKIE
    response.delete_cookie(key=name, path="/")


def read_panel_token(request: Request, scope: str) -> str | None:
    name = ADMIN_COOKIE if scope == "admin" else OPERATOR_COOKIE
    return request.cookies.get(name)


def set_user_cookie(response: Response, token: str, request: Request | None = None) -> None:
    """Постоянная HttpOnly-сессия покупателя (30 дней)."""
    if not token:
        return
    response.set_cookie(
        key=USER_COOKIE,
        value=token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=USER_COOKIE_MAX_AGE,
        path="/",
    )


def read_user_cookie(request: Request) -> str | None:
    return request.cookies.get(USER_COOKIE)


def clear_user_cookie(response: Response) -> None:
    response.delete_cookie(key=USER_COOKIE, path="/")
