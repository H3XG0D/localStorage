"""Доступ к финансам в админ-панели и уведомления владельцу в Telegram."""
from config import settings

# Synthetic full-panel admin fixture (`20-full-panel-fixtures.sql`).
STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID = 940001


def finance_owner_telegram_id() -> int | None:
    """Кому слать DM о зарплате операторов и т.п."""
    raw = (settings.finance_owner_telegram_id or "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    ids = settings.admin_ids
    return ids[0] if ids else None


def is_finance_owner_telegram_id(telegram_user_id: int | None) -> bool:
    owner = finance_owner_telegram_id()
    if not owner or telegram_user_id is None:
        return False
    return int(telegram_user_id) == int(owner)


def can_view_finance_telegram_id(telegram_user_id: int | None) -> bool:
    """P&L, финансы, тарифы, зарплаты — все Telegram-админы из ADMIN_TELEGRAM_IDS."""
    if telegram_user_id is None:
        return False
    return int(telegram_user_id) in settings.admin_ids


def is_staging_fixture_finance_owner(telegram_user_id: int | None) -> bool:
    """Full-panel staging bootstrap binds admin web_user to telegram_user_id 940001."""
    if (settings.environment or "").strip().lower() != "staging":
        return False
    if telegram_user_id is None:
        return False
    return int(telegram_user_id) == STAGING_FIXTURE_FINANCE_OWNER_TELEGRAM_ID


def is_finance_owner_admin(admin_user: dict) -> bool:
    telegram_user_id = admin_user.get("telegram_user_id")
    if is_finance_owner_telegram_id(telegram_user_id):
        return True
    return is_staging_fixture_finance_owner(telegram_user_id)


def can_view_finance_admin(admin_user: dict) -> bool:
    """P&L / финансы: Telegram admin IDs или явный permission finance.analytics."""
    perms = admin_user.get("permissions")
    if isinstance(perms, (list, tuple, set, frozenset)) and "finance.analytics" in perms:
        return True
    telegram_user_id = admin_user.get("telegram_user_id")
    if can_view_finance_telegram_id(telegram_user_id):
        return True
    return is_staging_fixture_finance_owner(telegram_user_id)


def can_view_finance_operator(operator: dict) -> bool:
    """Финансовая аналитика оператору доступна только по явному RBAC grant."""
    perms = operator.get("permissions")
    return isinstance(perms, (list, tuple, set, frozenset)) and "finance.analytics" in perms


def strip_operator_profit_fields(stats: dict) -> dict:
    """Убирает прибыль из ответа оператору — оставляет оборот и заработок."""
    out = dict(stats)
    out.pop("service_profit_rub", None)
    out.pop("profit_rub", None)
    out.pop("accruals_rub", None)
    return out


def shift_kpi_public_fields(stats: dict | None, can_finance: bool) -> dict:
    """Dashboard card KPIs. Missing earnings stay absent — never coerced to 0."""
    if not stats:
        return {
            "turnover": None,
            "fiat_total": None,
            "orders_count": None,
        }
    turnover = round(float(stats.get("fiat_total") or 0), 2)
    out = {
        "turnover": turnover,
        "fiat_total": turnover,
        "orders_count": int(stats.get("orders_count") or 0),
    }
    if can_finance:
        earnings = round(float(stats.get("earnings_rub") or 0), 2)
        out["earnings"] = earnings
        out["earnings_rub"] = earnings
    return out
