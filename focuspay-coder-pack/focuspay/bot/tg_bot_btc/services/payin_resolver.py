"""Планирование payin: single, оператор, отказ."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services import config_rates


@dataclass
class PayinPlan:
    mode: str  # single | operator | reject
    parts: list[int] = field(default_factory=list)
    pay_now: int = 0
    remainder_rub: int = 0
    message: str = ""
    has_bill: bool = False
    partial_probe_ok: bool = False
    resolved_sub_token: str | None = None


def _limits(sub_token: str) -> tuple[int, int]:
    lim = config_rates.MERCHANT_PAYIN_LIMITS.get(
        (sub_token or "CARDRUB").upper(),
        config_rates.MERCHANT_PAYIN_LIMITS.get("CARDRUB", {"max_single": 150000, "min_single": 1000}),
    )
    return int(lim["max_single"]), int(lim["min_single"])


def _bill_has_reciver(bill: dict | None) -> bool:
    if not bill or not isinstance(bill, dict):
        return False
    reciver = str(bill.get("reciver") or bill.get("receiver") or "").strip()
    return bool(reciver)


def _extract_bill(api_response: dict | None) -> bool:
    if not api_response:
        return False
    if api_response.get("status_pending") == "error":
        return False
    data_order = api_response.get("data_order") or {}
    bill = api_response.get("bill") or data_order.get("bill")
    return _bill_has_reciver(bill if isinstance(bill, dict) else None)


def get_bill_from_response(api_response: dict | None) -> dict | None:
    if not api_response or api_response.get("status_pending") == "error":
        return None
    data_order = api_response.get("data_order") or {}
    bill = api_response.get("bill") or data_order.get("bill")
    if _bill_has_reciver(bill if isinstance(bill, dict) else None):
        return bill
    return None


def extract_merchant_uuid(api_response: dict | None) -> str | None:
    if not api_response or api_response.get("status_pending") == "error":
        return None
    data_order = api_response.get("data_order") or {}
    uid = (
        api_response.get("uuid_system")
        or api_response.get("uuid")
        or data_order.get("uuid_system")
        or data_order.get("uuid")
    )
    return str(uid) if uid else None


def build_payin_plan(
    fiat_amount: int,
    sub_token: str,
    *,
    api_response: dict | None = None,
    partial_probe_ok: bool = False,
    resolved_sub_token: str | None = None,
) -> PayinPlan:
    amount = int(fiat_amount)
    has_bill = _extract_bill(api_response)

    if has_bill:
        return PayinPlan(
            mode="single",
            parts=[amount],
            pay_now=amount,
            has_bill=True,
            resolved_sub_token=resolved_sub_token,
        )

    if amount < config_rates.OPERATOR_FALLBACK_MIN_RUB:
        return PayinPlan(
            mode="reject",
            message="Нет реквизитов на эту сумму. Укажите другую сумму или попробуйте позже.",
            has_bill=False,
        )

    return PayinPlan(
        mode="operator",
        pay_now=amount,
        message="Сейчас нет свободных реквизитов на эту сумму. Напишите оператору — он подберёт вариант.",
        has_bill=False,
    )


def plan_to_dict(plan: PayinPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "parts": plan.parts,
        "pay_now": plan.pay_now,
        "remainder_rub": plan.remainder_rub,
        "message": plan.message,
        "has_bill": plan.has_bill,
        "partial_probe_ok": plan.partial_probe_ok,
        "resolved_sub_token": plan.resolved_sub_token,
    }


def allowed_payin_modes(plan_data: dict[str, Any]) -> frozenset[str]:
    """Режимы оплаты, которые сервер разрешил для текущего payin_plan."""
    mode = str(plan_data.get("mode") or "single")
    allowed: set[str] = set()

    if mode == "single":
        allowed.add("single")
    if mode == "operator":
        allowed.add("operator")
    return frozenset(allowed)


def resolve_payin_mode(plan_data: dict[str, Any], requested: str) -> str:
    """Проверяет, что пользователь не подменил callback_data режима оплаты."""
    mode = (requested or "").strip().lower()
    if mode not in allowed_payin_modes(plan_data):
        raise ValueError("Этот способ оплаты недоступен. Начните обмен заново.")
    return mode
