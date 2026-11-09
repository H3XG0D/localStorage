"""Payin planning (mirrors tg_bot_btc/services/payin_resolver.py)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import settings


@dataclass
class PayinPlan:
    mode: str
    parts: list[int] = field(default_factory=list)
    pay_now: int = 0
    remainder_rub: int = 0
    message: str = ""
    has_bill: bool = False
    partial_probe_ok: bool = False
    resolved_sub_token: str | None = None


def _limits(sub_token: str) -> tuple[int, int]:
    lim = settings.merchant_payin_limits.get(
        (sub_token or "SBPRUB").upper(),
        settings.merchant_payin_limits["SBPRUB"],
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
    op_min = int(settings.operator_fallback_min_rub)

    if has_bill:
        return PayinPlan(
            mode="single",
            parts=[amount],
            pay_now=amount,
            has_bill=True,
            resolved_sub_token=resolved_sub_token,
        )

    if amount < op_min:
        return PayinPlan(
            mode="reject",
            message="Нет реквизитов на эту сумму.",
            has_bill=False,
        )

    return PayinPlan(
        mode="operator",
        pay_now=amount,
        message="Сейчас нет свободных реквизитов. Напишите оператору.",
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
