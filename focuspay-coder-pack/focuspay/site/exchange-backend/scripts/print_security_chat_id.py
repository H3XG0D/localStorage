#!/usr/bin/env python3
"""Узнать chat_id группы для SECURITY_TELEGRAM_CHAT_ID.

1. Добавьте @focuspay1_bot в вашу группу логов.
2. Напишите в группе любое сообщение (например: /start).
3. Запустите: python scripts/print_security_chat_id.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import settings  # noqa: E402


def main() -> None:
    token = (settings.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        print("Задайте TELEGRAM_BOT_TOKEN в .env")
        sys.exit(1)
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=50"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("ok"):
        print(data)
        sys.exit(1)
    seen: set[tuple] = set()
    print("Чаты из последних обновлений бота:\n")
    for u in data.get("result", []):
        for key in ("message", "channel_post", "my_chat_member", "chat_member"):
            obj = u.get(key)
            if not obj:
                continue
            chat = obj.get("chat") or obj
            if not chat or "id" not in chat:
                continue
            row = (
                chat.get("type"),
                chat.get("id"),
                chat.get("title") or chat.get("username") or chat.get("first_name"),
            )
            if row in seen:
                continue
            seen.add(row)
            print(f"  type={row[0]}  id={row[1]}  name={row[2]}")
    if not seen:
        print("  (пусто — напишите сообщение в группе с ботом и запустите снова)")
    print("\nВ .env: SECURITY_TELEGRAM_CHAT_ID=<id группы (отрицательное число)>")


if __name__ == "__main__":
    main()
