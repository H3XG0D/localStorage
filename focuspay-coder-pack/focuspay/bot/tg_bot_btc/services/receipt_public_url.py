"""Публичный URL чека/видео для payin_set_check."""
import time

from services import config_rates as cfg
from services.webhook_security import RECEIPT_URL_TTL_SEC, sign_receipt_access


def build_receipt_public_url(filename: str) -> str:
    callback_url = (cfg.MERCHANT.get("callback_url") or "").split("?")[0].rstrip("/")
    receipt_base = callback_url.rsplit("/", 1)[0] if "/" in callback_url else callback_url
    exp = int(time.time()) + RECEIPT_URL_TTL_SEC
    sig = sign_receipt_access(filename, exp)
    return f"{receipt_base}/receipt/{filename}?sig={sig}&exp={exp}"
