"""Вызовы API мерчанта с fallback на legacy uuid_system."""
from merchant_client import cancel_payin, payin_set_check
from merchant_order_id import (
    resolve_merchant_api_id_with_legacy,
    resolve_payfast_uuid_system,
)

_ALREADY_PAID_MARKERS = (
    "уже успешно оплачен",
    "уже оплачен",
    "already paid",
    "already successfully paid",
    "order already paid",
)


def payfast_set_check_already_paid(result: dict | None) -> bool:
    """Payfast 400 «Заявка уже успешно оплачена» — повторная отправка чека не отказ."""
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


async def payin_set_check_for_order(order: dict, file_url: str) -> dict:
    from receipt_self_check import check_receipt_url_fetchable

    ok, reason = check_receipt_url_fetchable(file_url)
    if not ok:
        import logging

        oid = (order or {}).get("order_id") or (order or {}).get("merchant_order_id")
        logging.getLogger("receipt_self_check").warning(
            "payin_set_check blocked order=%s reason=%s url=%s",
            oid,
            reason,
            (file_url or "")[:120],
        )
        return {"status": 400, "body": {"error": f"receipt_url_not_fetchable: {reason}"}}
    merchant_id = (order or {}).get("merchant_id") or ((order or {}).get("payment_snapshot") or {}).get("merchant_id") if isinstance((order or {}).get("payment_snapshot"), dict) else (order or {}).get("merchant_id")
    uuid_system = resolve_payfast_uuid_system(order)
    if uuid_system:
        return await payin_set_check(uuid_system, file_url, merchant_id=merchant_id)
    primary, legacy = resolve_merchant_api_id_with_legacy(order)
    if not primary:
        return {"status": 400, "body": {"error": "no uuid_system for payin_set_check"}}
    result = await payin_set_check(primary, file_url, merchant_id=merchant_id)
    if result.get("status") == 200 or not legacy:
        return result
    return await payin_set_check(legacy, file_url, merchant_id=merchant_id)


async def cancel_payin_for_order(order: dict) -> dict:
    merchant_id = (order or {}).get("merchant_id") if isinstance(order, dict) else None
    primary, legacy = resolve_merchant_api_id_with_legacy(order)
    if not primary:
        return {"status": 0, "body": {"error": "no merchant id"}}
    result = await cancel_payin(primary, merchant_id=merchant_id)
    if result.get("status") == 200 or not legacy:
        return result
    return await cancel_payin(legacy, merchant_id=merchant_id)
