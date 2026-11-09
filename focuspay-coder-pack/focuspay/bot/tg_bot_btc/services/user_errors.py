"""Сообщения об ошибках для пользователей (без внутренних деталей)."""

GENERIC_ERROR = "Произошла ошибка. Попробуйте позже или напишите @focus_operator."
PAYMENT_ERROR = "Ошибка платёжной системы. Попробуйте позже или выберите другой способ оплаты."


def user_facing_message(exc: BaseException, *, payment: bool = False) -> str:
    """Безопасное сообщение для reply_text; не отдаёт traceback и API-ответы."""
    if exc.__class__.__name__ == "ReviewBonusError":
        msg = str(exc).strip()
        if msg and len(msg) < 200:
            return msg
        return GENERIC_ERROR
    if isinstance(exc, ValueError):
        msg = str(exc).strip()
        if msg in ("NO_BILL", "PAYMENT_PROVIDER_ERROR", "PAYFAST_DEADLINE_TOO_SHORT"):
            return PAYMENT_ERROR
        if msg == "ACTIVE_ORDER_EXISTS":
            return (
                "⚠️ У вас уже есть незавершённая заявка на покупку.\n"
                "Нажмите «Совершить обмен» — бот предложит отменить её и создать новую."
            )
        if msg and len(msg) < 120 and not any(
            x in msg.lower() for x in ("traceback", "sql", "http", "exception", "dsn", "token")
        ):
            return msg
    return PAYMENT_ERROR if payment else GENERIC_ERROR
