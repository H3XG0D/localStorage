"""Подпись доступа к файлам чеков (без секрета в URL).

Единый формат с bot-webhook: подпись считается от `filename:exp`,
в URL всегда есть `sig` + `exp`. Legacy-ссылки без `exp` (только HMAC имени)
по-прежнему принимаются на время перехода.
"""
import hashlib
import hmac
import time

from config import settings

RECEIPT_URL_TTL_SEC = 30 * 24 * 3600


def sign_receipt_access(filename: str, exp: int | None = None) -> str:
    secret = settings.receipt_secret or settings.webhook_secret or ""
    if not secret:
        return ""
    payload = f"{filename}:{exp}" if exp is not None else filename
    return hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]


def verify_receipt_access(
    filename: str, signature: str, exp: str | int | None = None
) -> bool:
    if not signature:
        return False
    if exp is not None and str(exp).strip() != "":
        try:
            exp_int = int(exp)
        except (TypeError, ValueError):
            return False
        if time.time() > exp_int:
            return False
        expected = sign_receipt_access(filename, exp_int)
    else:
        expected = sign_receipt_access(filename)
    if not expected:
        return False
    return hmac.compare_digest(expected, signature)
