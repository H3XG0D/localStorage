"""Проверка статуса Payfast payin перед автоподтверждением внештатных сделок."""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from merchant_get_order import get_merchant_order
from merchant_order_id import resolve_payfast_uuid_system

logger = logging.getLogger("payfast_payin_guard")

PAYFAST_FAIL_STATUSES = frozenset(
    {"ERROR", "FAILED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}
)
PAYFAST_FINAL_STATUSES = frozenset({"SUCCSES", "SUCCESS", "COMPLETED"})


def payfast_status_from_payload(payload: dict | None) -> str:
    if not payload or not isinstance(payload, dict):
        return ""
    raw = payload.get("status")
    if raw is not None and str(raw).strip():
        return str(raw).strip().upper()
    for nest in ("data_order", "order", "body"):
        nested = payload.get(nest)
        if isinstance(nested, dict):
            st = payfast_status_from_payload(nested)
            if st:
                return st
    return ""


def payfast_status_check_from_payload(payload: dict | None):
    if not payload or not isinstance(payload, dict):
        return None
    if "status_check" in payload:
        return payload.get("status_check")
    for nest in ("data_order", "order", "body"):
        nested = payload.get(nest)
        if isinstance(nested, dict) and "status_check" in nested:
            return nested.get("status_check")
    return None


def payfast_status_file_from_payload(payload: dict | None):
    if not payload or not isinstance(payload, dict):
        return None
    if "status_file" in payload:
        return payload.get("status_file")
    for nest in ("data_order", "order", "body"):
        nested = payload.get(nest)
        if isinstance(nested, dict) and "status_file" in nested:
            return nested.get("status_file")
    return None


def is_payfast_failure_status(status: str | None) -> bool:
    return bool(status) and str(status).upper() in PAYFAST_FAIL_STATUSES


def is_payfast_file_accepted(status_file) -> bool:
    return status_file in (0, "0")


def is_payfast_file_pending(status_file) -> bool:
    return status_file in (1, "1")


def is_payfast_recheck_requested(status_check) -> bool:
    return str(status_check).strip() in {"2", "3", "4"}


def is_payfast_settled(status: str | None, status_file=None) -> bool:
    """Trader confirmed — SUCCSES/SUCCESS/COMPLETED only.

    PAID + status_file=0 is receipt accepted, not trader approve.
    """
    del status_file
    st = str(status or "").strip().upper()
    if not st or is_payfast_failure_status(st):
        return False
    return st in PAYFAST_FINAL_STATUSES


def _provided_fields(payload: dict | None, *names: str) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    values = [payload[name] for name in names if payload.get(name) not in (None, "")]
    for nested_name in ("data_order", "order", "body"):
        nested = payload.get(nested_name)
        if isinstance(nested, dict):
            values.extend(_provided_fields(nested, *names))
    return values


def _same_amount(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False


def payfast_identity_mismatch(order: dict, payload: dict | None) -> str | None:
    """Сверяет только предоставленные callback/provider идентификаторы, fail closed."""
    if not isinstance(payload, dict):
        return None
    expected_uuid = resolve_payfast_uuid_system(order)
    provided_uuids = _provided_fields(payload, "uuid_system", "uuid")
    if expected_uuid and any(str(expected_uuid) != str(value) for value in provided_uuids):
        return "payfast_uuid_mismatch"

    expected_client_id = order.get("client_transaction_id")
    provided_client_ids = _provided_fields(payload, "client_transaction_id")
    if expected_client_id and any(str(expected_client_id) != str(value) for value in provided_client_ids):
        return "payfast_client_transaction_id_mismatch"

    expected_amount = order.get("expected_payfast_amount")
    if expected_amount is None:
        snapshot = order.get("payment_snapshot")
        expected_amount = snapshot.get("fiat_amount") if isinstance(snapshot, dict) else None
    provided_amounts = _provided_fields(payload, "amount")
    if expected_amount is not None and any(not _same_amount(expected_amount, value) for value in provided_amounts):
        return "payfast_amount_mismatch"
    return None


async def verify_payfast_ready_for_payout(
    order: dict, *, require_uuid: bool = False
) -> tuple[bool, str | None, dict | None]:
    if (order.get("direction") or "buy").lower() != "buy":
        return True, None, None

    uuid_system = resolve_payfast_uuid_system(order)
    if not uuid_system:
        if require_uuid:
            logger.error(
                "payfast uuid missing on payin order=%s — fail closed",
                order.get("order_id"),
            )
            return False, "payfast_uuid_missing", None
        return True, None, None

    try:
        resp = await get_merchant_order(uuid_system)
    except Exception as e:
        logger.warning("payfast verify failed order=%s: %s", order.get("order_id"), e)
        return False, "payfast_api_error", None

    if (resp or {}).get("status_pending") == "error":
        return False, "payfast_api_error", resp

    mismatch = payfast_identity_mismatch(order, resp)
    if mismatch:
        logger.warning("payfast authoritative identity mismatch order=%s reason=%s", order.get("order_id"), mismatch)
        return False, mismatch, resp

    st = payfast_status_from_payload(resp)
    sf = payfast_status_file_from_payload(resp)
    sc = payfast_status_check_from_payload(resp)

    if is_payfast_failure_status(st):
        return False, f"payfast_status_{st.lower()}", resp

    # Доп. проверка блокирует только пока трейдер не подтвердил.
    # Финальный SUCCSES важнее status_check: иначе оплаченная заявка висит вечно.
    if is_payfast_recheck_requested(sc) and not is_payfast_settled(st, sf):
        logger.warning(
            "payfast recheck requested order=%s status=%r status_check=%r",
            order.get("order_id"),
            st,
            sc,
        )
        return False, "payfast_recheck_requested", resp

    if is_payfast_settled(st, sf):
        return True, None, resp

    if st in ("ACCEPTED", "PENDING", "CREATED", ""):
        return False, "payfast_not_paid", resp

    if st == "PAID":
        if is_payfast_file_pending(sf):
            return False, "payfast_check_pending", resp
        return False, "payfast_awaiting_trader", resp

    return False, "payfast_not_paid", resp


async def verify_payfast_ready_for_complete(
    order: dict, webhook_body: dict | None = None
) -> tuple[bool, str | None]:
    wh_st = payfast_status_from_payload(webhook_body or {})
    if is_payfast_failure_status(wh_st):
        return False, f"webhook_status_{wh_st.lower()}"

    ok, reason, _ = await verify_payfast_ready_for_payout(order, require_uuid=True)
    return ok, reason
