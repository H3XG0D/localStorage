from fastapi import Request, Response

from app.core.config import settings

AUTH_COOKIE_NAME = "access_token"


def cookie_secure_for_request(request: Request | None) -> bool:
    """Never set Secure on plain HTTP, even if COOKIE_SECURE is misconfigured."""
    if request is None:
        return False
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").lower()
    if proto != "https":
        return False
    return settings.COOKIE_SECURE


def clear_auth_cookie(response: Response, request: Request | None = None) -> None:
    """Clear auth cookie for both secure and non-secure variants (HTTP/HTTPS migration)."""
    for secure in (False, True):
        response.delete_cookie(
            key=AUTH_COOKIE_NAME,
            path="/",
            httponly=True,
            secure=secure,
            samesite="lax",
        )


def set_auth_cookie(response: Response, token: str, request: Request | None = None) -> None:
    clear_auth_cookie(response, request)
    max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=cookie_secure_for_request(request),
        samesite="lax",
        max_age=max_age,
        path="/",
    )
