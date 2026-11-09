"""HTTP-клиент Telegram Bot API с токеном в параметре (не settings.telegram_bot_token)."""
from __future__ import annotations

from typing import Any

import aiohttp

_TIMEOUT = aiohttp.ClientTimeout(total=20)


class TelegramApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


async def telegram_call(
    token: str,
    method: str,
    *,
    json_payload: dict[str, Any] | None = None,
    form: aiohttp.FormData | None = None,
) -> dict[str, Any]:
    token = (token or "").strip()
    if not token:
        raise TelegramApiError("Bot token not configured")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        if form is not None:
            async with session.post(url, data=form) as response:
                body = await _json(response)
        else:
            async with session.post(url, json=json_payload or {}) as response:
                body = await _json(response)
    if not body.get("ok"):
        raise TelegramApiError(
            str(body.get("description") or "Telegram API error"),
            payload=body,
        )
    return body


async def _json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        data = await response.json()
        return data if isinstance(data, dict) else {"ok": False, "description": str(data)}
    except Exception:
        text = await response.text()
        return {"ok": False, "description": text[:400], "status": response.status}


async def get_me(token: str) -> dict[str, Any]:
    result = await telegram_call(token, "getMe")
    return result.get("result") or {}


async def set_webhook(
    token: str,
    *,
    url: str,
    secret: str,
    allowed_updates: list[str] | None = None,
) -> dict[str, Any]:
    return await telegram_call(
        token,
        "setWebhook",
        json_payload={
            "url": url,
            "secret_token": secret,
            "allowed_updates": allowed_updates or ["message", "callback_query"],
            "drop_pending_updates": False,
        },
    )


async def get_webhook_info(token: str) -> dict[str, Any]:
    result = await telegram_call(token, "getWebhookInfo")
    return result.get("result") or {}


async def delete_webhook(token: str) -> dict[str, Any]:
    return await telegram_call(token, "deleteWebhook", json_payload={"drop_pending_updates": False})


async def set_my_commands(token: str, commands: list[dict[str, str]]) -> dict[str, Any]:
    return await telegram_call(token, "setMyCommands", json_payload={"commands": commands})


async def send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await telegram_call(token, "sendMessage", json_payload=payload)


async def edit_message(
    token: str,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return await telegram_call(token, "editMessageText", json_payload=payload)


async def get_file(token: str, file_id: str) -> dict[str, Any]:
    result = await telegram_call(token, "getFile", json_payload={"file_id": file_id})
    return result.get("result") or {}


async def download_file(token: str, file_path: str) -> bytes:
    token = (token or "").strip()
    url = f"https://api.telegram.org/file/bot{token}/{file_path.lstrip('/')}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as session:
        async with session.get(url) as response:
            if response.status >= 400:
                raise TelegramApiError(f"download failed HTTP {response.status}", status=response.status)
            return await response.read()
