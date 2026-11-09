"""Доступность оплаты по QR: баланс платформы и причина отказа.

Мерчантский USDT-пул общий для всех клиентов: если он пуст, оплата не пройдёт ни у кого.
Поэтому баланс кешируется и проверяется до запроса `check`, а не после отказа платформы.
"""
from __future__ import annotations

import logging
import time

from services import finance666_client as api
from services.finance666_client import Finance666Error
from services.runtime_settings import (
    qr_pay_enabled,
    qr_pay_low_balance_allowlist,
    qr_pay_min_merchant_usdt,
)

logger = logging.getLogger("qr_pay_status")

BALANCE_TTL_SEC = 60

UNAVAILABLE_TEXT = "⏳ Временно оплата по QR недоступна. Попробуйте позже."

_balance: float | None = None
_balance_ts: float = 0.0
_currency: str = "USDT"


def cached_balance() -> float | None:
    """Последний известный баланс без сетевого запроса. None — ещё не спрашивали."""
    return _balance


def balance_age_sec() -> float | None:
    return None if _balance_ts <= 0 else time.time() - _balance_ts


def currency() -> str:
    return _currency


def invalidate() -> None:
    """Забыть баланс целиком: устаревшее значение не должно решать за платформу."""
    global _balance, _balance_ts
    _balance = None
    _balance_ts = 0.0


async def merchant_balance(*, force: bool = False) -> float | None:
    """Баланс платформы с кешем на минуту. None — узнать не удалось."""
    global _balance, _balance_ts, _currency

    if not api.configured():
        return None
    if not force and _balance is not None and time.time() - _balance_ts < BALANCE_TTL_SEC:
        return _balance
    try:
        data = await api.merchant_balance()
    except Finance666Error as exc:
        logger.warning("merchant balance unavailable: %s", exc)
        return _balance
    available = data.get("available_balance")
    if available is None:
        return _balance
    _balance = float(available)
    _currency = str(data.get("currency") or "USDT")
    _balance_ts = time.time()
    return _balance


def low_balance_allowed(user_id: int | None, username: str | None = None) -> bool:
    """Исключение из порога: этим аккаунтам оплата открыта и на пустом пуле."""
    allowlist = qr_pay_low_balance_allowlist()
    if not allowlist:
        return False
    if user_id and str(int(user_id)) in allowlist:
        return True
    name = (username or "").strip().lstrip("@").lower()
    return bool(name) and name in allowlist


async def availability(
    *,
    force: bool = False,
    user_id: int | None = None,
    username: str | None = None,
) -> dict:
    """Можно ли сейчас платить по QR и почему нет."""
    if not qr_pay_enabled():
        return {"available": False, "reason": "disabled", "balance": cached_balance()}
    if not api.configured():
        return {"available": False, "reason": "no_key", "balance": None}

    threshold = qr_pay_min_merchant_usdt()
    balance = await merchant_balance(force=force)
    if balance is None:
        # Баланс неизвестен: не блокируем, платформа сама откажет на check.
        return {"available": True, "reason": None, "balance": None, "threshold": threshold}
    if balance < threshold:
        if low_balance_allowed(user_id, username):
            return {
                "available": True,
                "reason": "low_balance_allowlisted",
                "balance": balance,
                "threshold": threshold,
            }
        return {
            "available": False,
            "reason": "low_balance",
            "balance": balance,
            "threshold": threshold,
        }
    return {"available": True, "reason": None, "balance": balance, "threshold": threshold}


def looks_available(user_id: int | None = None, username: str | None = None) -> bool:
    """Синхронная оценка для клавиатур: по флагу и последнему известному балансу."""
    if not qr_pay_enabled() or not api.configured():
        return False
    balance = cached_balance()
    if balance is None:
        return True
    if balance >= qr_pay_min_merchant_usdt():
        return True
    return low_balance_allowed(user_id, username)
