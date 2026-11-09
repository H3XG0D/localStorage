"""Telegram WebApp initData HMAC verification."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass
class WebAppUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    is_premium: bool | None = None


@dataclass
class VerifiedInitData:
    user: WebAppUser
    auth_date: int
    raw: dict[str, str]


def _data_check_string(pairs: list[tuple[str, str]]) -> str:
    filtered = [(k, v) for k, v in pairs if k != "hash"]
    filtered.sort(key=lambda x: x[0])
    return "\n".join(f"{k}={v}" for k, v in filtered)


def verify_webapp_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 3600,
) -> VerifiedInitData:
    raw = (init_data or "").strip()
    if not raw:
        raise InitDataError("empty init_data")
    token = (bot_token or "").strip()
    if not token:
        raise InitDataError("bot_token missing")

    pairs = parse_qsl(raw, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.get("hash")
    if not received_hash:
        raise InitDataError("missing hash")

    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(
        secret_key,
        _data_check_string(pairs).encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise InitDataError("bad signature")

    try:
        auth_date = int(data.get("auth_date") or 0)
    except ValueError as e:
        raise InitDataError("bad auth_date") from e
    if max_age_seconds and (time.time() - auth_date) > max_age_seconds:
        raise InitDataError("init_data expired")

    user_raw = data.get("user")
    if not user_raw:
        raise InitDataError("missing user")
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError as e:
        raise InitDataError("bad user json") from e
    try:
        uid = int(user_obj["id"])
    except (KeyError, TypeError, ValueError) as e:
        raise InitDataError("bad user id") from e

    return VerifiedInitData(
        user=WebAppUser(
            id=uid,
            username=user_obj.get("username"),
            first_name=user_obj.get("first_name"),
            last_name=user_obj.get("last_name"),
            language_code=user_obj.get("language_code"),
            is_premium=user_obj.get("is_premium"),
        ),
        auth_date=auth_date,
        raw={k: v for k, v in data.items()},
    )
