"""Внештатные сделки: дедлайн оператора и предупреждения."""
from datetime import datetime, timedelta, timezone

EXTERNAL_DEAL_DEADLINE_SEC = int(22.5 * 60)  # 1350

EXTERNAL_DEAL_CLIENT_PAY_MIN = 20

EXTERNAL_DEAL_WARNING_ELAPSED_SEC = 15 * 60  # 900
EXTERNAL_DEAL_WARNING_REMAINING_SEC = int(7.5 * 60)  # 450

EXTERNAL_DEAL_CLIENT_PAY_TEXT = "Оплатите одним платежом, за 20 минут."

EXTERNAL_DEAL_WARNING_TEXT = "Осталось 7.5 минуты на оплату"


def default_deal_expires_at(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment + timedelta(minutes=EXTERNAL_DEAL_CLIENT_PAY_MIN)


def parse_merchant_date_end(raw) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def resolve_deal_expires_at(api_response: dict | None, *, now: datetime | None = None) -> datetime:
    """dateEnd мерчанта, иначе now + 20 минут. Автоотмены нет — только индикатор."""
    payload = api_response or {}
    nested = payload.get("data_order") if isinstance(payload.get("data_order"), dict) else {}
    parsed = parse_merchant_date_end(payload.get("dateEnd") or nested.get("dateEnd"))
    if parsed is not None:
        return parsed
    return default_deal_expires_at(now)
