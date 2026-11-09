"""NDJSON debug logs for agent sessions (remove after fix verified)."""
from __future__ import annotations

import json
import os
import time

_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_PATH = os.environ.get(
    "DEBUG_AGENT_LOG",
    os.path.join(_BOT_ROOT, ".cursor", "debug-30ccf1.log"),
)
_SESSION = "30ccf1"


def _enabled() -> bool:
    return os.environ.get("DEBUG_AGENT", "").strip().lower() in ("1", "true", "yes")


def agent_log(
    location: str,
    message: str,
    data: dict | None = None,
    *,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    if not _enabled():
        return
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION,
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
            "runId": run_id,
        }
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        import logging

        logging.getLogger("debug_agent").info(
            "%s %s %s", location, message, data
        )
    # #endregion
