"""Допустимые переходы статусов заявки (единая машина состояний)."""
from __future__ import annotations

TERMINAL_STATUSES = frozenset({"PAID", "CANCELED", "EXPIRED", "FAILED"})

_ALLOWED: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"AWAITING_CHECK", "PENDING", "CANCELED", "EXPIRED"}),
    # AWAITING_CHECK НЕ завершается напрямую: чек должен долететь до мерчанта
    # (AWAITING_CHECK -> PENDING) перед COMPLETED. Иначе крипта уходит без чека.
    "AWAITING_CHECK": frozenset({"PENDING", "CANCELED", "EXPIRED"}),
    "PENDING": frozenset({"AWAITING_CHECK", "CANCELED", "EXPIRED", "COMPLETED"}),
    # COMPLETED -> AWAITING_CHECK: Appeals может запросить видео уже после
    # подтверждения мерчантом — тогда выплату ставим на удержание (см.
    # services/video_receipt_request.py, req_type=3).
    "COMPLETED": frozenset({"PAID", "CANCELED", "AWAITING_CHECK"}),
    # PENDING: веб-SELL создаётся сразу OPERATOR_PENDING, и клиент подтверждает
    # отправку крипты кнопкой «Я оплатил» — заявка встаёт в очередь на выплату.
    "OPERATOR_PENDING": frozenset({"PENDING", "CANCELED", "EXPIRED", "PAID"}),
    "DISPUTE": frozenset({"PENDING", "COMPLETED", "CANCELED", "PAID", "EXPIRED"}),
    "PAID": frozenset(),
    "CANCELED": frozenset(),
    # Appeals / Payfast: после истечения таймера всё ещё могут запросить видео.
    "EXPIRED": frozenset({"AWAITING_CHECK"}),
    "FAILED": frozenset(),
}


def allowed_status_transition(
    prev_status: str | None,
    new_status: str,
    *,
    direction: str | None = None,
    payin_rail: bool = False,
) -> bool:
    if not prev_status or not new_status:
        return False
    prev = prev_status.upper()
    new = new_status.upper()
    if prev == new:
        return True
    if prev == "CREATED" and new == "PAID":
        return (direction or "").lower() == "sell"
    if prev in ("PENDING", "AWAITING_CHECK") and new == "PAID":
        return (direction or "").lower() == "sell"
    if payin_rail and prev == "AWAITING_CHECK" and new == "COMPLETED":
        return (direction or "").lower() == "buy"
    return new in _ALLOWED.get(prev, frozenset())


def sell_pay_allowed_status(status: str) -> bool:
    """SELL: выплата только после подтверждения пользователем («Я оплатил» / чек)."""
    return status in ("PENDING", "AWAITING_CHECK", "COMPLETED")
