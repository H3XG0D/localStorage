"""Mask cards and secrets before the model and before the database."""

from __future__ import annotations

import sys

from focus_agent.config import EXCHANGE_BACKEND


def redact(text: str | None) -> str:
    backend = str(EXCHANGE_BACKEND)
    if backend not in sys.path:
        sys.path.append(backend)
    from privacy_redaction import redact_text

    return redact_text(text or "")
