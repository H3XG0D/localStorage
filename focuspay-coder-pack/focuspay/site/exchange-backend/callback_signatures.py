"""HMAC-подписи callback-кнопок админки."""
import hashlib
import hmac

from config import settings

_SIG_LEN = 32


def _secret() -> bytes:
    return (settings.callback_secret or settings.secret_key).encode()


def _hmac_hex(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def sign_order(order_id: str) -> str:
    return _hmac_hex(order_id)[:_SIG_LEN]


def verify_order_signature(order_id: str, signature: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_order(order_id), signature)


def sign_withdrawal(withdrawal_id: int) -> str:
    return _hmac_hex(f"refwd:{withdrawal_id}")[:_SIG_LEN]


def verify_withdrawal_signature(withdrawal_id: int, signature: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_withdrawal(withdrawal_id), signature)


def sign_operator_payroll(request_id: int) -> str:
    return _hmac_hex(f"opay:{request_id}")[:_SIG_LEN]


def verify_operator_payroll_signature(request_id: int, signature: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_operator_payroll(request_id), signature)


def sign_external_payout(payout_id: int) -> str:
    return _hmac_hex(f"extwd:{int(payout_id)}")[:_SIG_LEN]


def verify_external_payout_signature(payout_id: int, signature: str) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_external_payout(payout_id), signature)
