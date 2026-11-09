"""Публичный URL загруженного чека/видео для payin_set_check.

Единый формат с bot-webhook (`sig` + `exp`, подпись от `filename:exp`),
иначе Payfast получает ссылку, по которой вместо PDF лежит 403.
"""
import time

from config import settings
from receipt_security import RECEIPT_URL_TTL_SEC, sign_receipt_access


def build_receipt_public_url(filename: str) -> str:
    base = (settings.receipt_public_base_url or "").rstrip("/")
    if not base:
        callback = (settings.merchant_callback_url or "").split("?")[0].rstrip("/")
        base = callback.rsplit("/", 1)[0] if "/" in callback else callback
    exp = int(time.time()) + RECEIPT_URL_TTL_SEC
    sig = sign_receipt_access(filename, exp)
    return f"{base}/receipt/{filename}?sig={sig}&exp={exp}"
