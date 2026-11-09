"""Проверки доступа и статусов для финансовых операций (без зависимости от Telegram)."""
from services import config_rates


def is_admin_group_chat(chat_id: int | None) -> bool:
    return config_rates.is_reports_group_chat(chat_id)


def is_reports_group_chat(chat_id: int | None) -> bool:
    return config_rates.is_reports_group_chat(chat_id)


def buy_pay_allowed_status(status: str) -> bool:
    """BUY: выплата только после подтверждения оплаты мерчантом (COMPLETED)."""
    return status == "COMPLETED"
