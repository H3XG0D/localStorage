"""Shared order archive list: filters, SQL, serializer (no operator.py import).

Used by admin GET /orders and operator GET /orders/history.
Finance formulas stay optional behind include_finance.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from bot_user_avatars import bot_user_avatar_public_url
from order_source import normalize_order_source, order_source_label
from order_verification import receipt_kind, receipt_required_type


# Авто = Payfast-поток; ручные = оператор / без авто-реквизитов.
HAS_PAYFAST_SQL = """(
    NULLIF(BTRIM(COALESCE(o.payment_snapshot->>'merchant_uuid', '')), '') IS NOT NULL
    OR (
        NULLIF(BTRIM(COALESCE(o.merchant_order_id, '')), '') IS NOT NULL
        AND o.merchant_order_id <> o.order_id
        AND POSITION('-' IN o.merchant_order_id) > 0
    )
)"""

ORDERS_WITH_BUYER_SQL = """
    SELECT o.*,
           bu.username AS buyer_username,
           bu.first_name AS buyer_first_name,
           oa.display_name AS operator_display_name,
           oa.username AS operator_username,
           ura.referrer_user_id AS referrer_user_id,
           ru.username AS referrer_username,
           ru.first_name AS referrer_first_name
    FROM orders o
    LEFT JOIN bot_users bu ON bu.user_id = o.user_id
    LEFT JOIN operator_accounts oa ON oa.id = o.operator_id
    LEFT JOIN (
        SELECT DISTINCT ON (user_id) user_id, referrer_user_id
        FROM user_referral_attributions
        ORDER BY user_id, created_at ASC
    ) ura ON ura.user_id = o.user_id
    LEFT JOIN bot_users ru ON ru.user_id = ura.referrer_user_id
"""

ORDERS_COUNT_FROM_SQL = """
    FROM orders o
    LEFT JOIN bot_users bu ON bu.user_id = o.user_id
    LEFT JOIN operator_accounts oa ON oa.id = o.operator_id
"""

SUB_TOKEN_LABELS = {
    "CARDRUB": "Карта",
    "SBPRUB": "СБП",
}

STATUS_LABELS = {
    "CREATED": "Создана",
    "AWAITING_CHECK": "Ожидает чек",
    "PENDING": "На проверке",
    "COMPLETED": "Выполнена",
    "PAID": "Оплачена",
    "FAILED": "Ошибка",
    "CANCELED": "Отменена",
    "EXPIRED": "Истекла",
    "DISPUTE": "Спор",
    "OPERATOR_PENDING": "Ожидает оператора",
}

HISTORY_KPI_STATUSES = (
    "AWAITING_CHECK",
    "PENDING",
    "CREATED",
    "DISPUTE",
    "PAID",
    "CANCELED",
    "EXPIRED",
)

LIVE_QUEUE_STATUSES = frozenset(
    {
        "CREATED",
        "AWAITING_CHECK",
        "PENDING",
        "OPERATOR_PENDING",
        "DISPUTE",
        "COMPLETED",
    }
)


def partner_clients_exists_sql(param_idx: int) -> str:
    """Orders whose buyer is attributed to promo campaign $param_idx (all statuses)."""
    if param_idx < 1:
        raise ValueError("param_idx must be >= 1")
    return (
        "EXISTS ("
        "SELECT 1 FROM promo_attributions pa "
        "JOIN promo_campaigns pc ON pc.code = pa.promo_code "
        f"WHERE pa.user_id = o.user_id AND pc.id = ${param_idx})"
    )


def partner_option_from_row(row: Any) -> dict[str, Any]:
    r = dict(row)
    label = (
        str(r.get("label") or "").strip()
        or str(r.get("partner_display_name") or "").strip()
        or str(r.get("name") or "").strip()
        or str(r.get("partner_username") or "").strip()
        or f"#{r.get('id')}"
    )
    return {"id": int(r["id"]), "label": label}


def referrer_fields_from_row(row: Any) -> dict[str, Any]:
    r = dict(row)
    uid = r.get("referrer_user_id")
    if uid is None or uid == "":
        return {
            "referrer_user_id": None,
            "referrer_username": None,
            "referrer_first_name": None,
        }
    uname = r.get("referrer_username")
    if uname and not str(uname).startswith("@"):
        uname = f"@{uname}"
    fname = r.get("referrer_first_name")
    return {
        "referrer_user_id": int(uid),
        "referrer_username": str(uname) if uname else None,
        "referrer_first_name": str(fname) if fname else None,
    }


PARTNER_OPTIONS_SQL = """
    SELECT pc.id,
           COALESCE(
               NULLIF(BTRIM(pa.display_name), ''),
               NULLIF(BTRIM(pc.name), ''),
               NULLIF(BTRIM(pa.username), ''),
               '#' || pc.id::text
           ) AS label
    FROM partner_accounts pa
    JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
    ORDER BY label
"""


def _payment_summary_merchant(row: dict) -> str | None:
    mid = row.get("merchant_id")
    if mid:
        return str(mid)
    snap = row.get("payment_snapshot")
    if isinstance(snap, str):
        import json as _json
        try:
            snap = _json.loads(snap)
        except (TypeError, ValueError):
            return None
    if isinstance(snap, dict) and snap.get("merchant_id"):
        return str(snap.get("merchant_id"))
    return None


def _payment_summary(row: dict) -> dict | None:
    snap = row.get("payment_snapshot")
    if not snap:
        return None
    if isinstance(snap, str):
        import json

        try:
            snap = json.loads(snap)
        except (TypeError, ValueError):
            return None
    if not isinstance(snap, dict):
        return None
    bill = snap.get("bill") if isinstance(snap.get("bill"), dict) else {}
    merchant_uuid = (
        snap.get("merchant_uuid")
        or snap.get("uuid_system")
        or row.get("merchant_order_id")
    )
    parts: list[str] = []
    bank = bill.get("bank")
    reciver = bill.get("reciver") or bill.get("receiver")
    fio = bill.get("fio")
    if bank:
        parts.append(str(bank))
    if fio:
        parts.append(str(fio))
    if reciver:
        parts.append(str(reciver))
    return {
        "merchant_uuid": str(merchant_uuid) if merchant_uuid else None,
        "pay_link": snap.get("pay_link"),
        "summary": " · ".join(parts) if parts else None,
    }


def order_origin(row: dict) -> str:
    """manual | auto — для фильтра и бейджа."""
    import runtime_settings

    direction = str(row.get("direction") or "").lower()
    if direction == "sell":
        return "manual"
    fee = row.get("card_fee_pct")
    if fee is not None:
        return "manual" if runtime_settings.is_manual_card_fee(float(fee)) else "auto"
    snap = _payment_summary(row) or {}
    uuid = str(snap.get("merchant_uuid") or "").strip()
    if uuid:
        return "auto"
    mid = str(row.get("merchant_order_id") or "").strip()
    oid = str(row.get("order_id") or "").strip()
    if mid and mid != oid and "-" in mid:
        return "auto"
    return "manual"


def origin_sql_condition(origin: str, *, idx: int) -> tuple[str, list]:
    """SQL-условие + params для origin=manual|auto."""
    import runtime_settings

    manual_fee = float(runtime_settings.card_fee_pct(manual=True))
    auto_fee = float(runtime_settings.card_fee_pct(manual=False))
    fee_is_manual = (
        f"(o.card_fee_pct IS NOT NULL AND "
        f"ABS(o.card_fee_pct::float8 - ${idx}) < ABS(o.card_fee_pct::float8 - ${idx + 1}) + 1e-9)"
    )
    fee_is_auto = (
        f"(o.card_fee_pct IS NOT NULL AND "
        f"ABS(o.card_fee_pct::float8 - ${idx}) >= ABS(o.card_fee_pct::float8 - ${idx + 1}) + 1e-9)"
    )
    null_fee_auto = f"(o.card_fee_pct IS NULL AND {HAS_PAYFAST_SQL})"
    null_fee_manual = f"(o.card_fee_pct IS NULL AND NOT {HAS_PAYFAST_SQL})"
    params = [manual_fee, auto_fee]
    if origin == "manual":
        cond = f"(LOWER(o.direction) = 'sell' OR {fee_is_manual} OR {null_fee_manual})"
    else:
        cond = f"(LOWER(o.direction) = 'buy' AND ({fee_is_auto} OR {null_fee_auto}))"
    return cond, params


def build_orders_list_query(
    *,
    status: str | None = None,
    direction: str | None = None,
    crypto: str | None = None,
    search: str | None = None,
    origin: str | None = None,
    user_id: int | None = None,
    partner_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    merchant_id: str | None = None,
) -> tuple[str, list]:
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if status:
        conditions.append(f"o.status = ${idx}")
        params.append(status.upper())
        idx += 1
    if direction:
        conditions.append(f"o.direction = ${idx}")
        params.append(direction.lower())
        idx += 1
    if crypto:
        conditions.append(f"LOWER(o.crypto) LIKE ${idx}")
        params.append(f"%{crypto.lower()}%")
        idx += 1
    origin_norm = (origin or "").strip().lower()
    if origin_norm in ("manual", "auto"):
        cond, origin_params = origin_sql_condition(origin_norm, idx=idx)
        conditions.append(cond)
        params.extend(origin_params)
        idx += len(origin_params)
    if search:
        conditions.append(
            f"(o.order_id ILIKE ${idx} OR o.merchant_order_id ILIKE ${idx} "
            f"OR COALESCE(o.payment_snapshot->>'merchant_uuid', '') ILIKE ${idx} "
            f"OR COALESCE(o.payment_snapshot->>'uuid_system', '') ILIKE ${idx} "
            f"OR o.requisites ILIKE ${idx} OR o.user_id::text = ${idx} "
            f"OR bu.username ILIKE ${idx} OR bu.first_name ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1
    if user_id is not None:
        conditions.append(f"o.user_id = ${idx}")
        params.append(user_id)
        idx += 1
    if merchant_id:
        conditions.append(
            f"(o.merchant_id = ${idx} OR o.payment_snapshot->>'merchant_id' = ${idx})"
        )
        params.append(merchant_id)
        idx += 1
    if partner_id is not None:
        conditions.append(partner_clients_exists_sql(idx))
        params.append(int(partner_id))
        idx += 1
    if date_from and date_to:
        try:
            d_from = date.fromisoformat(date_from)
            d_to = date.fromisoformat(date_to)
            conditions.append(f"o.created_at::date BETWEEN ${idx} AND ${idx + 1}")
            params.extend([d_from, d_to])
        except ValueError:
            pass

    return " AND ".join(conditions), params


def counts_sql(where: str) -> str:
    parts = [
        "SELECT COUNT(*)::int AS total",
    ]
    for status in HISTORY_KPI_STATUSES:
        alias = status.lower()
        parts.append(
            f"COUNT(*) FILTER (WHERE o.status = '{status}')::int AS {alias}"
        )
    return ",\n        ".join(parts) + f"\n        {ORDERS_COUNT_FROM_SQL}\n        WHERE {where}"


def counts_from_row(row: Any | None) -> dict[str, int]:
    if not row:
        out = {"all": 0}
        for status in HISTORY_KPI_STATUSES:
            out[status] = 0
        return out
    r = dict(row)
    out = {"all": int(r.get("total") or 0)}
    for status in HISTORY_KPI_STATUSES:
        out[status] = int(r.get(status.lower()) or 0)
    return out


def _iso(val: Any) -> str | None:
    if not val:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def serialize_admin_order(row, *, include_finance: bool = False) -> dict:
    r = dict(row)
    buyer_username = r.get("buyer_username")
    if buyer_username and not str(buyer_username).startswith("@"):
        buyer_username = f"@{buyer_username}"
    cb = float(r.get("cashback_applied_rub") or 0)
    disc = float(r.get("exchange_discount_applied_rub") or 0)
    balance_applied = round(cb + disc, 2)
    sub = str(r.get("sub_token") or "").upper()
    op_crypto = r.get("operator_crypto_received")
    op_fiat = r.get("operator_fiat_paid_out")
    status = str(r.get("status") or "")
    out = {
        "id": r.get("id"),
        "order_id": r.get("order_id"),
        "user_id": r.get("user_id"),
        "buyer_username": buyer_username,
        "buyer_first_name": r.get("buyer_first_name"),
        "status": r.get("status"),
        "status_label": STATUS_LABELS.get(status, status),
        "direction": r.get("direction"),
        "crypto": r.get("crypto"),
        "crypto_amount": r.get("crypto_amount"),
        "fiat_amount": r.get("fiat_amount"),
        "rate": r.get("rate"),
        "requisites": r.get("requisites"),
        "wallet_address": r.get("wallet_address"),
        "network": r.get("network"),
        "sub_token": r.get("sub_token"),
        "sub_token_label": SUB_TOKEN_LABELS.get(sub, sub or None),
        "merchant_order_id": r.get("merchant_order_id"),
        "merchant_id": r.get("merchant_id") or (_payment_summary_merchant(r)),
        "merchant_attempts": r.get("merchant_attempts"),
        "order_source": normalize_order_source(r.get("order_source")),
        "source_label": order_source_label(r.get("order_source")),
        "origin": order_origin(r),
        "promo_code": r.get("promo_code"),
        "promo_bonus_percent": r.get("promo_bonus_percent"),
        "exchange_discount_applied_rub": disc,
        "balance_applied_rub": balance_applied if balance_applied > 0 else 0.0,
        "operator_id": r.get("operator_id"),
        "operator_name": r.get("operator_display_name") or r.get("operator_username"),
        "operator_crypto_received": float(op_crypto) if op_crypto is not None else None,
        "operator_fiat_paid_out": float(op_fiat) if op_fiat is not None else None,
        "payout_tx_hash": r.get("payout_tx_hash"),
        "payout_confirmed_at": _iso(r.get("payout_confirmed_at")),
        "payout_confirmed_by": r.get("payout_confirmed_by"),
        "has_receipt": bool(r.get("receipt_file")),
        "receipt_kind": receipt_kind(r),
        "required_receipt_type": receipt_required_type(r),
        "cancel_reason": r.get("cancel_reason"),
        "canceled_by": r.get("canceled_by"),
        "payment_summary": _payment_summary(r),
        "created_at": _iso(r.get("created_at")),
        "updated_at": _iso(r.get("updated_at")),
        "expires_at": _iso(r.get("expires_at")),
        "cashback_applied_rub": cb,
        "card_fee_pct": float(r["card_fee_pct"]) if r.get("card_fee_pct") is not None else None,
        "in_live_queue": status in LIVE_QUEUE_STATUSES,
        **referrer_fields_from_row(r),
    }
    if r.get("user_id"):
        out["buyer_avatar_url"] = bot_user_avatar_public_url(int(r["user_id"]))
    if include_finance:
        from economics_snapshot import order_economics

        out["service_profit_rub"] = round(
            order_economics(r, clamp=False)["service_profit_rub"],
            2,
        )
    return out


async def fetch_orders_archive(
    conn,
    *,
    status: str | None = None,
    direction: str | None = None,
    crypto: str | None = None,
    search: str | None = None,
    origin: str | None = None,
    user_id: int | None = None,
    partner_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_counts: bool = False,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    common = dict(
        direction=direction,
        crypto=crypto,
        search=search,
        origin=origin,
        user_id=user_id,
        partner_id=partner_id,
        date_from=date_from,
        date_to=date_to,
        merchant_id=merchant_id,
    )
    where, params = build_orders_list_query(status=status, **common)
    idx = len(params) + 1
    rows = await conn.fetch(
        f"""
        {ORDERS_WITH_BUYER_SQL}
        WHERE {where}
        ORDER BY o.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
        limit,
        offset,
    )
    total = await conn.fetchval(
        f"""
        SELECT COUNT(*)::int
        {ORDERS_COUNT_FROM_SQL}
        WHERE {where}
        """,
        *params,
    )
    partner_rows = await conn.fetch(PARTNER_OPTIONS_SQL)
    counts = None
    if include_counts:
        cwhere, cparams = build_orders_list_query(**common)
        count_row = await conn.fetchrow(counts_sql(cwhere), *cparams)
        counts = counts_from_row(count_row)
    return {
        "rows": rows,
        "total": int(total or 0),
        "partner_rows": partner_rows,
        "counts": counts,
    }


async def fetch_order_archive_row(conn, order_id: str):
    return await conn.fetchrow(
        f"{ORDERS_WITH_BUYER_SQL} WHERE o.order_id = $1",
        order_id.strip().upper(),
    )
