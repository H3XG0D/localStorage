"""HMAC-подписи callback-кнопок (без зависимостей от Telegram/БД)."""
import hashlib
import hmac

from services import config_rates

_SIG_LEN = 32  # 128 bit


def _hmac_hex(payload: str) -> str:
    return hmac.new(
        config_rates.CALLBACK_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def sign_order(order_id: str) -> str:
    return _hmac_hex(order_id)[:_SIG_LEN]


def verify_order_signature(order_id: str, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_order(order_id)
    return hmac.compare_digest(expected, signature)


def sign_withdrawal(withdrawal_id: int) -> str:
    return _hmac_hex(f"refwd:{withdrawal_id}")[:_SIG_LEN]


def verify_withdrawal_signature(withdrawal_id: int, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_withdrawal(withdrawal_id)
    return hmac.compare_digest(expected, signature)


def sign_review_submission(submission_id: int) -> str:
    return _hmac_hex(f"rev:{submission_id}")[:_SIG_LEN]


def verify_review_submission_signature(submission_id: int, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_review_submission(submission_id)
    return hmac.compare_digest(expected, signature)


def sign_operator_payroll(request_id: int) -> str:
    return _hmac_hex(f"opay:{request_id}")[:_SIG_LEN]


def verify_operator_payroll_signature(request_id: int, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_operator_payroll(request_id)
    return hmac.compare_digest(expected, signature)


def sign_receipt_review(order_id: str) -> str:
    return _hmac_hex(f"rcpt:{order_id}")[:_SIG_LEN]


def verify_receipt_review_signature(order_id: str, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_receipt_review(order_id)
    return hmac.compare_digest(expected, signature)


def sign_account_review(user_id: int) -> str:
    return _hmac_hex(f"areview:{int(user_id)}")[:_SIG_LEN]


def verify_account_review_signature(user_id: int, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_account_review(int(user_id))
    return hmac.compare_digest(expected, signature)


def sign_device_review(user_id: int) -> str:
    return _hmac_hex(f"dreview:{int(user_id)}")[:_SIG_LEN]


def verify_device_review_signature(user_id: int, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_device_review(int(user_id))
    return hmac.compare_digest(expected, signature)


def sign_external_payout(payout_id: int) -> str:
    return _hmac_hex(f"extwd:{int(payout_id)}")[:_SIG_LEN]


def verify_external_payout_signature(payout_id: int, signature: str) -> bool:
    if not signature:
        return False
    expected = sign_external_payout(int(payout_id))
    return hmac.compare_digest(expected, signature)
