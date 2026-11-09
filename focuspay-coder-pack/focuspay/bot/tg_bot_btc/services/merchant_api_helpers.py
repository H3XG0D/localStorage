"""Вызовы API мерчанта с fallback на legacy uuid_system."""
from __future__ import annotations

import logging
from typing import Any

from services.merchant_order_id import (
    resolve_merchant_api_id_with_legacy,
    resolve_payfast_uuid_system,
)

logger = logging.getLogger("merchant_api_helpers")

_CANCEL_ALLOWED = frozenset({"CREATED", "AWAITING_CHECK"})
_CANCEL_REFUSED = frozenset({"COMPLETED", "PAID", "EXPIRED", "CANCELED"})

_ALREADY_PAID_MARKERS = (
    "уже успешно оплачен",
    "уже оплачен",
    "already paid",
    "already successfully paid",
    "order already paid",
)


def payfast_set_check_already_paid(result: dict | None) -> bool:
    """Payfast 400 «Заявка уже успешно оплачена» — чек принимать не нужно, заявка уже settled."""
    if not isinstance(result, dict):
        return False
    if result.get("already_settled"):
        return True
    body = result.get("body") if isinstance(result.get("body"), dict) else result
    if not isinstance(body, dict):
        return False
    parts = [str(body.get(k) or "") for k in ("error", "err", "msg", "message")]
    nested = body.get("data_order")
    if isinstance(nested, dict):
        parts.extend(
            str(nested.get(k) or "") for k in ("status", "error", "err", "msg", "message")
        )
    text = " ".join(parts).lower()
    return any(marker in text for marker in _ALREADY_PAID_MARKERS)


async def payin_set_check_for_order(order: dict, file_url: str, payin_set_check_fn) -> dict:
    """Attach a receipt using Payfast's internal uuid_system only.

    Payfast does not accept client_transaction_id for /payin_set_check.  Do not
    fall back to the local order id here: a second request with that id only
    turns a recoverable missing-UUID problem into a misleading HTTP 400.
    """
    uuid_system = resolve_payfast_uuid_system(order)
    if uuid_system:
        return await payin_set_check_fn(uuid_system, file_url)
    logger.error(
        "payin_set_check blocked: uuid_system missing order=%s",
        order.get("order_id"),
    )
    return {
        "status": 422,
        "body": {"error": "no uuid_system for payin_set_check"},
        "ok": False,
        "local_error": "missing_payfast_uuid",
    }


async def cancel_payin_for_order(order: dict, cancel_fn) -> dict:
    """Legacy wrapper: cancel_fn(uuid) -> {status, body}."""
    primary, legacy = resolve_merchant_api_id_with_legacy(order)
    if not primary:
        return {"status": 0, "body": {"error": "no merchant id"}, "ok": False}
    result = await cancel_fn(primary)
    ok = bool(result.get("ok")) if "ok" in result else int(result.get("status") or 0) == 200
    if ok or not legacy:
        out = dict(result)
        out.setdefault("ok", ok)
        return out
    result2 = await cancel_fn(legacy)
    ok2 = bool(result2.get("ok")) if "ok" in result2 else int(result2.get("status") or 0) == 200
    out = dict(result2)
    out.setdefault("ok", ok2)
    return out


async def cancel_payin_safe(
    order: dict,
    *,
    allow_awaiting_check: bool = False,
    update_local: bool = True,
) -> dict[str, Any]:
    """
    Безопасная отмена Payfast payin + опционально local CANCELED.

    Returns:
      ok: local terminal (or already terminal)
      merchant_ok: merchant accepted cancel
      orphan: local canceled but merchant failed
      refused: True if status forbids cancel (COMPLETED/PAID/...)
      status: final/local status seen
    """
    from services.db import get_order, update_order_status
    from services.merchant_client import cancel_order_payin

    order_id = str(order.get("order_id") or "").strip()
    if not order_id:
        return {
            "ok": False,
            "merchant_ok": False,
            "orphan": False,
            "refused": True,
            "status": None,
            "error": "no_order_id",
        }

    fresh = await get_order(order_id) or order
    st = str(fresh.get("status") or "")
    if st in _CANCEL_REFUSED:
        return {
            "ok": st in ("CANCELED", "EXPIRED"),
            "merchant_ok": False,
            "orphan": False,
            "refused": st in ("COMPLETED", "PAID"),
            "status": st,
            "error": "terminal_status",
        }
    allowed = {"CREATED"}
    if allow_awaiting_check:
        allowed.add("AWAITING_CHECK")
    if st not in allowed:
        return {
            "ok": False,
            "merchant_ok": False,
            "orphan": False,
            "refused": True,
            "status": st,
            "error": "status_not_allowed",
        }

    result = await cancel_payin_for_order(dict(fresh), cancel_order_payin)
    merchant_ok = bool(result.get("ok"))
    if not merchant_ok:
        logger.warning(
            "cancel_payin_safe merchant fail order=%s status=%s body=%s",
            order_id,
            result.get("status"),
            result.get("body"),
        )

    local_ok = True
    if update_local and st != "CANCELED":
        local_ok = await update_order_status(order_id, "CANCELED")

    return {
        "ok": bool(local_ok),
        "merchant_ok": merchant_ok,
        "orphan": bool(local_ok) and not merchant_ok,
        "refused": False,
        "status": "CANCELED" if local_ok else st,
        "merchant_result": result,
    }
