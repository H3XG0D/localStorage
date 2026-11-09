"""Самопроверка receipt-URL до отправки мерчанту.

Payfast в `payin_set_check` получает только ссылку и сам скачивает PDF.
Если по URL лежит 403/404 (чужая подпись, нет файла, просрочен exp) —
мерчант видит «ссылку вместо PDF». Проверяем локально то же, что проверит
bot-webhook при отдаче: подпись (с учётом exp) + наличие файла на диске.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("receipt_self_check")


def _receipts_dir() -> Path:
    return Path(os.getenv("RECEIPTS_DIR", "/opt/tg_bot_btc/receipts"))


def check_receipt_url_fetchable(file_url: str) -> tuple[bool, str | None]:
    """То же, что увидит Payfast: подпись валидна, не просрочена, файл на диске."""
    url = (file_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return False, "not_http_url"
    try:
        parts = urlparse(url)
        qs = parse_qs(parts.query)
    except Exception:
        return False, "unparsable_url"
    filename = Path(parts.path.rsplit("/", 1)[-1] if "/" in parts.path else parts.path).name
    if not filename or "." not in filename:
        return False, "no_filename"
    sig = (qs.get("sig") or [""])[0]
    exp = (qs.get("exp") or [""])[0] or None
    try:
        from receipt_security import verify_receipt_access

        if not verify_receipt_access(filename, sig, exp):
            return False, "bad_or_expired_signature"
    except Exception as exc:
        logger.warning("receipt self-check verify failed: %s", exc)
        return False, "verify_error"
    path = (_receipts_dir() / filename).resolve()
    try:
        base = _receipts_dir().resolve()
    except Exception:
        return False, "receipts_dir_missing"
    if path.parent != base or not path.is_file():
        return False, "file_missing_on_disk"
    return True, None
