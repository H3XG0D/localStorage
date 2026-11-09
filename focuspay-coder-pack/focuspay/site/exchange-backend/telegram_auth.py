"""Verify Telegram Login Widget payload (https://core.telegram.org/widgets/login)."""
import hashlib
import hmac
import time
from typing import Any

from fastapi import HTTPException

from config import settings

MAX_AUTH_AGE_SECONDS = 86400  # 24 hours


def _field_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def verify_telegram_login(data: dict[str, Any]) -> dict[str, Any]:
    """
    Validates hash and auth_date. Returns cleaned user fields.
    Expected keys: id, first_name, last_name?, username?, photo_url?, auth_date, hash
    """
    received_hash = data.get("hash")
    if not received_hash:
        raise HTTPException(status_code=400, detail="Missing hash")

    auth_date = data.get("auth_date")
    if auth_date is None:
        raise HTTPException(status_code=400, detail="Missing auth_date")

    try:
        auth_ts = int(auth_date)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid auth_date")

    if time.time() - auth_ts > MAX_AUTH_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Telegram auth data expired")

    check_items = {
        k: v
        for k, v in data.items()
        if k != "hash" and v is not None and v != ""
    }
    data_check_string = "\n".join(
        f"{k}={_field_str(check_items[k])}" for k in sorted(check_items.keys())
    )

    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=503,
            detail="Telegram bot token not configured on server",
        )

    secret_key = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    calculated = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated, str(received_hash)):
        raise HTTPException(status_code=401, detail="Invalid Telegram signature")

    try:
        tg_id = int(_field_str(check_items["id"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Missing or invalid Telegram id")

    return {
        "id": tg_id,
        "first_name": check_items.get("first_name"),
        "last_name": check_items.get("last_name"),
        "username": check_items.get("username"),
        "photo_url": check_items.get("photo_url"),
        "auth_date": auth_ts,
    }
