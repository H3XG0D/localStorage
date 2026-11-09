"""Единый ID заявки для API мерчанта (= наш order_id / client_transaction_id)."""
from __future__ import annotations

from services.payment_snapshot import order_payment_snapshot


def _merchant_uuid_from_snapshot(order: dict) -> str | None:
    snap = order_payment_snapshot(order)

    for key in ("merchant_uuid", "uuid_system"):
        uid = snap.get(key)
        if isinstance(uid, bool) or not isinstance(uid, (str, int, float)):
            continue
        normalized = str(uid).strip()
        if normalized:
            return normalized
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
    """ID для cancel_order_payin и payin_set_check."""
    oid = str(order.get("order_id") or "").strip()
    if oid:
        return oid
    return str(order.get("merchant_order_id") or "").strip()


def resolve_merchant_api_id_with_legacy(order: dict) -> tuple[str, str | None]:
    """(primary, legacy_uuid) — primary=order_id; legacy=uuid_system из snapshot или старый merchant_order_id."""
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
