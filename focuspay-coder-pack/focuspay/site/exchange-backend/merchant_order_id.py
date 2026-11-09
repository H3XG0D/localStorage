"""Единый ID заявки для API мерчанта (= order_id / client_transaction_id)."""
from __future__ import annotations

import json


def _merchant_uuid_from_snapshot(order: dict) -> str | None:
    snap = order.get("payment_snapshot")
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except json.JSONDecodeError:
            return None
    if isinstance(snap, dict):
        uid = snap.get("merchant_uuid")
        if uid:
            return str(uid).strip()
    return None


def resolve_payfast_uuid_system(order: dict) -> str | None:
    """uuid_system для /payin_set_check (Payfast не принимает client_transaction_id)."""
    uid = _merchant_uuid_from_snapshot(order)
    if uid:
        return uid
    mid = str(order.get("merchant_order_id") or "").strip()
    oid = str(order.get("order_id") or "").strip()
    if mid and mid != oid and "-" in mid:
        return mid
    return None


def resolve_merchant_display_id(order: dict) -> str:
    """ID для операторов и кабинета Payfast (uuid_system)."""
    uid = resolve_payfast_uuid_system(order)
    if uid:
        return uid
    mid = str(order.get("merchant_order_id") or "").strip()
    oid = str(order.get("order_id") or "").strip()
    if mid and mid != oid:
        return mid
    return oid


def format_ops_order_id_html(order: dict) -> str:
    """Строка ID для Telegram/HTML в ops-чатах."""
    import html

    disp = resolve_merchant_display_id(order)
    esc = html.escape(disp)
    direction = str(order.get("direction") or "buy").lower()
    if direction == "buy" and resolve_payfast_uuid_system(order):
        return f"🆔 Payfast: <code>{esc}</code>"
    return f"🆔 <code>{esc}</code>"


def resolve_merchant_api_id(order: dict) -> str:
    oid = str(order.get("order_id") or "").strip()
    if oid:
        return oid
    return str(order.get("merchant_order_id") or "").strip()


def resolve_merchant_api_id_with_legacy(order: dict) -> tuple[str, str | None]:
    oid = str(order.get("order_id") or "").strip()
    mid = str(order.get("merchant_order_id") or "").strip()
    snapshot_uuid = _merchant_uuid_from_snapshot(order)
    primary = oid or mid
    legacy = None
    if snapshot_uuid and snapshot_uuid != primary:
        legacy = snapshot_uuid
    elif mid and mid != oid:
        legacy = mid
    return primary, legacy
