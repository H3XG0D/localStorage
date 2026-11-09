"""Redaction before any model / audit / notify path."""
from __future__ import annotations

from privacy_redaction import content_hash, redact_text


def sanitize_prompt(text: str, *, max_len: int = 2000) -> tuple[str, str]:
    """Returns (redacted_text, sha256_hex). Never returns secrets."""
    redacted = redact_text(text or "", keep_short_ids=True)[:max_len]
    return redacted, content_hash(redacted)


def audit_preview(text: str, *, max_len: int = 240) -> str:
    return redact_text(text or "", keep_short_ids=True)[:max_len]
