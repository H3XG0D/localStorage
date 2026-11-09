"""Telegram Login без iframe (oauth.telegram.org) — работает при блокировке third-party cookies."""
from urllib.parse import quote

from fastapi import HTTPException

from config import settings


def bot_id_from_token(token: str) -> str:
    part = (token or "").split(":")[0]
    if not part.isdigit():
        raise HTTPException(status_code=503, detail="Invalid TELEGRAM_BOT_TOKEN")
    return part


def build_telegram_oauth_url(origin: str, return_path: str = "/login") -> str:
    """
    Редирект на oauth.telegram.org (first-party для Telegram).
    После входа Telegram вернёт на return_to с #tgAuthResult=... или ?id=&hash=...
    """
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=503,
            detail="Telegram bot token not configured on server",
        )

    origin = origin.rstrip("/")
    if not origin.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid origin")

    return_path = return_path if return_path.startswith("/") else f"/{return_path}"
    return_to = f"{origin}{return_path}"
    bot_id = bot_id_from_token(settings.telegram_bot_token)

    return (
        "https://oauth.telegram.org/auth"
        f"?bot_id={bot_id}"
        f"&origin={quote(origin, safe='')}"
        f"&request_access=write"
        f"&return_to={quote(return_to, safe='')}"
    )
