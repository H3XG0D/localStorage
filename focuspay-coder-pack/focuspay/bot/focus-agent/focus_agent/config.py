from __future__ import annotations

import os
from pathlib import Path


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


TOKEN = _get("TELEGRAM_BOT_TOKEN")
DATABASE_DSN = _get("DATABASE_DSN") or _get("database_dsn")
LLM_API_KEY = _get("FOCUS_AGENT_API_KEY")
LLM_BASE_URL = _get("FOCUS_AGENT_BASE_URL", "https://ai.starimg.ru/v1").rstrip("/")
LLM_MODEL = _get("FOCUS_AGENT_MODEL", "grok-4.6")
JOURNAL_PATH = Path(_get("JOURNAL_PATH", "/opt/focus-brain/agent-journal.md"))
EXCHANGE_BACKEND = Path(_get("EXCHANGE_BACKEND", "/opt/exchange-backend"))
VOICE_PATH = Path(_get("VOICE_PATH", "/opt/focus-brain/voice.md"))


def _int(name: str) -> int:
    raw = _get(name)
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


# Same group as /dash on the exchange bot. Reports go here, not into the user chat.
REPORTS_GROUP_ID = _int("TELEGRAM_REPORTS_GROUP_ID")
