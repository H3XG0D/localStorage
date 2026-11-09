#!/usr/bin/env python3
"""Разовый вход аккаунта, который читает участников focus-чата.

Нужны TELEGRAM_API_ID и TELEGRAM_API_HASH с https://my.telegram.org.
Скрипт спросит телефон, код и пароль 2FA. Сессию в git не класть.
Аккаунт после входа должен состоять в focus-чате.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


async def _main() -> int:
    _load_env(ROOT / ".env")
    from services.chat_members_scan import api_credentials, session_path

    creds = api_credentials()
    if creds is None:
        print("FATAL: задай TELEGRAM_API_ID и TELEGRAM_API_HASH", file=sys.stderr)
        return 1
    from telethon import TelegramClient

    from services.chat_members_scan import _client_session_name

    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    api_id, api_hash = creds
    client = TelegramClient(_client_session_name(path), api_id, api_hash)
    await client.start()
    me = await client.get_me()
    username = getattr(me, "username", None) or "—"
    print(f"Сессия записана: {path}")
    print(f"Аккаунт id={int(me.id)} @{username}. Добавь его в focus-чат.")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
