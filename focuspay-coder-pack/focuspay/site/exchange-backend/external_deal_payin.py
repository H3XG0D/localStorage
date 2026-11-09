"""Payfast payin + чек для внештатных сделок из кабинета."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from config import settings
from payin_bill_display import format_client_payment_text, public_payin_bill
from external_exchange_calc import preview_deal
from external_exchange_calc import build_markup_formula, normalize_markup_mode
from external_exchange_service import (
    _row,
    cancel_external_deal,
    create_external_deal,
    get_exchanger_active,
    resolve_exchanger_markup,
    resolve_exchanger_markup_pct,
)
from external_exchange_trust import deal_fields_from_row, trust_fields_from_row
from merchant_api_helpers import (
    cancel_payin_for_order,
    payfast_set_check_already_paid,
    payin_set_check_for_order,
)
from merchant_order_id import resolve_merchant_display_id
from payin_discovery import discover_payin_plan
from payin_resolver import get_bill_from_response
from merchant_client import cancel_payin, create_payin_order
from external_deal_timing import resolve_deal_expires_at
from external_exchange_payout import withdraw_fee_usd, withdraw_fees_map
from exchanger_api_keys import ensure_exchanger_hmac_schema
from external_client_stat import apply_stat_on_create, payload_from_row

logger = logging.getLogger("external_deal_payin")


async def record_payfast_review(
    conn,
    *,
    incident_type: str,
    deal_id: int | None = None,
    merchant_ref: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Хранит только коды/имена полей, не callback payload, PII или секреты."""
    raw = detail if isinstance(detail, dict) else {}
    safe: dict[str, Any] = {}
    for key in ("reason", "source", "status"):
        if raw.get(key) is not None:
            safe[key] = str(raw[key])[:128]
    for key in ("provided_fields", "authoritative_fields"):
        if isinstance(raw.get(key), (list, tuple)):
            safe[key] = sorted(str(value) for value in raw[key])
    if isinstance(raw.get("http_status"), int):
        safe["http_status"] = raw["http_status"]
    ref = str(merchant_ref or "").strip()[:128] or None
    dedupe_input = json.dumps(
        {"incident_type": incident_type, "deal_id": deal_id, "merchant_ref": ref, "detail": safe},
        sort_keys=True,
        separators=(",", ":"),
    )
    dedupe_key = hashlib.sha256(dedupe_input.encode("utf-8")).hexdigest()
    await conn.execute(
        """
        INSERT INTO external_deal_payfast_reviews
            (incident_type, deal_id, merchant_ref, detail, dedupe_key)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        ON CONFLICT (dedupe_key) DO NOTHING
        """,
        incident_type,
        deal_id,
        ref,
        json.dumps(safe, sort_keys=True),
        dedupe_key,
    )


ACTIVE_STATUSES = ("awaiting_receipt", "pending")


class DealAmountError(ValueError):
    """Некорректная сумма сделки до HTTP-обёртки."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _coin_key(crypto: str | None) -> str:
    return (crypto or "usdt").split("_")[0].lower().strip() or "usdt"


def input_rub_from_crypto(amount_crypto: float, crypto: str, rates: dict) -> float:
    """Рапира: ₽ за 1 монету → сумма ввода для наценки."""
    amt = float(amount_crypto)
    if amt <= 0:
        raise DealAmountError("invalid", "amount_crypto must be > 0")
    coin = _coin_key(crypto)
    rate = float(rates.get(coin) or 0)
    if rate <= 0:
        raise DealAmountError("rate", f"Курс {coin.upper()}/RUB недоступен")
    rub = round(amt * rate, 2)
    if rub < 1:
        raise DealAmountError("too_small", "Сумма слишком маленькая для реквизита")
    return rub


def resolve_cabinet_input_rub(
    *,
    amount_rub: float | None = None,
    amount_crypto: float | None = None,
    crypto: str = "usdt",
    rates: dict,
) -> tuple[float, dict]:
    """amount_crypto (если > 0) важнее amount_rub. Возвращает ₽ ввода и поля для preview."""
    coin = _coin_key(crypto)
    extra: dict[str, Any] = {
        "crypto": coin,
        "crypto_rate_rub": float(rates.get(coin) or 0),
    }
    crypto_amt = float(amount_crypto) if amount_crypto is not None else 0.0
    if crypto_amt > 0:
        try:
            rub = input_rub_from_crypto(crypto_amt, coin, rates)
        except DealAmountError as exc:
            status = 503 if exc.code == "rate" else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        extra["amount_crypto"] = crypto_amt
        extra["amount_unit"] = "crypto"
        extra["input_rub"] = rub
        return rub, extra
    rub = float(amount_rub) if amount_rub is not None else 0.0
    if rub <= 0:
        raise HTTPException(status_code=400, detail="Укажите сумму в рублях или в крипте")
    extra["amount_unit"] = "rub"
    extra["input_rub"] = rub
    return rub, extra


def _support_username() -> str:
    return (settings.chat_support_username or "focus_operator").strip().lstrip("@")


def _merchant_response_text(body: Any) -> str:
    if isinstance(body, dict):
        parts = [str(v) for v in body.values() if v is not None]
        return " ".join(parts).lower()
    return str(body or "").lower()


def merchant_wants_video(body: Any) -> bool:
    text = _merchant_response_text(body)
    return (
        "видео" in text
        or "video" in text
        or ("pdf" in text and "не пройден" in text)
    )


def merchant_reject_detail(body: Any, *, video: bool) -> str:
    support = _support_username()
    if video:
        return (
            f"PDF не принят — требуется видео. "
            f"Напишите @{support} с номером сделки — оператор примет видео от клиента."
        )
    return (
        f"Мерчант отклонил чек. Проверьте PDF или напишите @{support} с номером сделки."
    )


def deal_merchant_ctx(deal: dict) -> dict:
    """Контекст для payin_set_check / cancel_payin (как orders row)."""
    snap = deal.get("payment_snapshot")
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except json.JSONDecodeError:
            snap = None
    if not isinstance(snap, dict):
        pay = deal.get("payment")
        if isinstance(pay, dict):
            snap = {k: v for k, v in pay.items() if k != "type"}
        else:
            snap = None
    oid = f"EXT-{deal['id']}"
    expected_amount = snap.get("fiat_amount") if isinstance(snap, dict) else None
    return {
        "order_id": oid,
        "merchant_order_id": deal.get("merchant_order_id") or oid,
        "client_transaction_id": deal.get("merchant_order_id") or deal.get("client_transaction_id") or None,
        "expected_payfast_amount": expected_amount if expected_amount is not None else deal.get("client_pays_rub"),
        "payment_snapshot": snap,
    }


def payment_from_deal(deal: dict) -> dict | None:
    snap = deal.get("payment_snapshot")
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except json.JSONDecodeError:
            return None
    if not isinstance(snap, dict):
        return None
    return {"type": "buy", **snap}


def payin_user_id(exchanger_id: int, fingerprint: str | None = None) -> int:
    """Id покупателя для Doliv payin.

    Без fingerprint все клиенты магазина выглядят как один «покупатель» (-exchanger_id)
    и ломают трафик карт. Строка магазина хешируется в стабильный 48-битный int.
    """
    raw = str(fingerprint or "").strip()
    if not raw:
        return -abs(int(exchanger_id))
    digest = hashlib.sha256(f"{int(exchanger_id)}:{raw}".encode("utf-8")).hexdigest()
    n = int(digest[:12], 16)
    return n if n > 0 else 1


def _iso_ts(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def deal_public_out(deal) -> dict:
    d = _row(deal)
    payment = payment_from_deal(d)
    sub_token = d.get("sub_token")
    client_pays = float(d.get("client_pays_rub") or 0)
    if payment:
        raw_bill = payment.get("bill")
        clean_bill = public_payin_bill(raw_bill)
        amount = payment.get("fiat_amount")
        payment = {**payment, "bill": clean_bill}
        payment_text = format_client_payment_text(
            amount_rub=amount if amount is not None else client_pays,
            sub_token=sub_token,
            bill=clean_bill,
            deal_id=d["id"],
        )
    else:
        payment_text = format_client_payment_text(
            amount_rub=client_pays,
            sub_token=sub_token,
            bill=None,
            deal_id=d["id"],
        )
    paid_at = d.get("paid_confirmed_at")
    receipt_at = d.get("receipt_submitted_at")
    created_at = d.get("created_at")
    expires_at = d.get("expires_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    if isinstance(paid_at, datetime):
        paid_at = paid_at.isoformat()
    if isinstance(receipt_at, datetime):
        receipt_at = receipt_at.isoformat()
    expires_at = _iso_ts(expires_at)
    status = str(d.get("status") or "")
    req_type = int(d.get("required_receipt_type") or 2)
    markup_mode = normalize_markup_mode(str(d.get("markup_mode") or "on_deal"))
    markup_pct = float(d.get("markup_pct") or 0)
    base_rub = float(d.get("amount_rub") or 0)
    formula = build_markup_formula(
        base_rub=base_rub,
        client_pays_rub=client_pays,
        markup_pct=markup_pct,
        markup_mode=markup_mode,
        input_rub=client_pays if markup_mode == "on_turnover" else base_rub,
    )
    payfast_ref = str(d.get("merchant_order_id") or f"EXT-{d['id']}")
    payfast_order_id = resolve_merchant_display_id(deal_merchant_ctx(d))
    payout_on_credit = bool(d.get("payout_on_credit"))
    payout_wallet = str(d.get("payout_wallet") or "").strip() or None
    payout_id = d.get("payout_id")
    crypto = str(d.get("crypto") or "usdt")
    return {
        "id": d["id"],
        "status": status,
        "amount_rub": base_rub,
        "client_pays_rub": client_pays,
        "principal_usdt": float(d.get("principal_usdt") or 0),
        "total_credit_usdt": float(d.get("principal_usdt") or 0),
        "crypto": d.get("crypto"),
        "markup_pct": markup_pct,
        "markup_mode": markup_mode,
        "markup_rub": formula["markup_rub"],
        "input_rub": formula["input_rub"],
        "formula_text": formula["formula_text"],
        "input_label": formula["input_label"],
        "sub_token": d.get("sub_token"),
        "note": d.get("note"),
        "created_at": created_at,
        "expires_at": expires_at,
        "client_transaction_id": d.get("client_transaction_id") or None,
        "paid_confirmed_at": paid_at,
        "receipt_submitted_at": receipt_at,
        "required_receipt_type": req_type,
        "requires_receipt": bool(paid_at) and status == "awaiting_receipt",
        "can_confirm_paid": status == "awaiting_receipt" and not paid_at,
        "can_upload_receipt": (
            status == "awaiting_receipt" and bool(paid_at) and req_type != 3
        ),
        "needs_operator_video": (
            status == "awaiting_receipt" and bool(paid_at) and req_type == 3
        ),
        "can_cancel": status == "awaiting_receipt" and not receipt_at,
        "payment": payment,
        "payment_text": payment_text,
        "payfast_order_id": payfast_order_id or None,
        "payfast_ref": payfast_ref,
        "merchant_id": d.get("merchant_id") or (payment or {}).get("merchant_id"),
        "payout_on_credit": payout_on_credit,
        "payout_wallet": payout_wallet,
        "payout_id": int(payout_id) if payout_id else None,
        "payout_fee_usd": withdraw_fee_usd(crypto) if payout_on_credit else 0.0,
        "fingerprint": str(d.get("customer_fingerprint") or "").strip() or None,
        "client_stat": payload_from_row(d.get("client_stat")) if d.get("client_stat") else None,
        "client_stat_at": _iso_ts(d.get("client_stat_at")),
        **deal_fields_from_row(d),
        **trust_fields_from_row(d),
    }


async def list_active_deals(conn, exchanger_id: int):
    return await conn.fetch(
        """
        SELECT * FROM external_deals
        WHERE exchanger_id = $1
          AND status IN ('awaiting_receipt', 'pending')
        ORDER BY created_at DESC
        """,
        exchanger_id,
    )


async def get_active_deal(conn, exchanger_id: int):
    rows = await list_active_deals(conn, exchanger_id)
    return rows[0] if rows else None


async def get_deal_for_exchanger(conn, deal_id: int, exchanger_id: int):
    return await conn.fetchrow(
        """
        SELECT d.*, e.is_trusted_client, e.auto_credit_on_payfast
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        WHERE d.id = $1 AND d.exchanger_id = $2
        """,
        deal_id,
        exchanger_id,
    )


def _deal_list_item(row) -> dict:
    d = _row(row)
    created = d.get("created_at")
    if isinstance(created, datetime):
        created = created.isoformat()
    out = {
        "id": int(d["id"]),
        "status": str(d.get("status") or ""),
        "amount_rub": float(d.get("amount_rub") or 0),
        "client_pays_rub": float(d.get("client_pays_rub") or 0),
        "principal_usdt": float(d.get("principal_usdt") or 0),
        "crypto": d.get("crypto"),
        "sub_token": d.get("sub_token"),
        "note": d.get("note"),
        "created_at": created,
        "expires_at": _iso_ts(d.get("expires_at")),
        "payout_on_credit": bool(d.get("payout_on_credit")),
        "payout_id": int(d["payout_id"]) if d.get("payout_id") else None,
    }
    payfast_order_id = resolve_merchant_display_id(deal_merchant_ctx(d))
    if payfast_order_id:
        out["payfast_order_id"] = payfast_order_id
    return out


def _resolve_status_filter(status: str | None) -> list[str] | None:
    if not status:
        return None
    s = status.strip().lower()
    if s == "active":
        return list(ACTIVE_STATUSES)
    if s in ("awaiting_receipt", "pending", "confirmed", "cancelled"):
        return [s]
    return None


async def count_deals_for_exchanger(
    conn,
    exchanger_id: int,
    *,
    status: str | None = None,
) -> int:
    statuses = _resolve_status_filter(status)
    if statuses:
        return int(
            await conn.fetchval(
                """
                SELECT COUNT(*) FROM external_deals
                WHERE exchanger_id = $1 AND status = ANY($2::text[])
                """,
                exchanger_id,
                statuses,
            )
            or 0
        )
    return int(
        await conn.fetchval(
            "SELECT COUNT(*) FROM external_deals WHERE exchanger_id = $1",
            exchanger_id,
        )
        or 0
    )


async def count_active_deals_for_exchanger(conn, exchanger_id: int) -> int:
    return int(
        await conn.fetchval(
            """
            SELECT COUNT(*) FROM external_deals
            WHERE exchanger_id = $1 AND status = ANY($2::text[])
            """,
            exchanger_id,
            list(ACTIVE_STATUSES),
        )
        or 0
    )


async def list_deals_for_exchanger(
    conn,
    exchanger_id: int,
    *,
    limit: int = 30,
    offset: int = 0,
    status: str | None = None,
) -> list[dict]:
    await ensure_exchanger_hmac_schema(conn)
    statuses = _resolve_status_filter(status)
    if statuses:
        rows = await conn.fetch(
            """
            SELECT id, status, amount_rub, client_pays_rub, principal_usdt,
                   crypto, sub_token, note, created_at, expires_at,
                   merchant_order_id, payment_snapshot,
                   payout_on_credit, payout_wallet, payout_id
            FROM external_deals
            WHERE exchanger_id = $1 AND status = ANY($4::text[])
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            exchanger_id,
            limit,
            offset,
            statuses,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, status, amount_rub, client_pays_rub, principal_usdt,
                   crypto, sub_token, note, created_at, expires_at,
                   merchant_order_id, payment_snapshot,
                   payout_on_credit, payout_wallet, payout_id
            FROM external_deals
            WHERE exchanger_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            exchanger_id,
            limit,
            offset,
        )
    return [_deal_list_item(r) for r in rows]


async def preview_cabinet_deal(
    conn,
    exchanger_id: int,
    amount_rub: float | None = None,
    *,
    amount_crypto: float | None = None,
    crypto: str = "usdt",
) -> dict:
    ex = await get_exchanger_active(conn, exchanger_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Внештатник не найден")
    from routers.public import get_exchanger_rates_cached

    rates = await get_exchanger_rates_cached()
    amount_rub, extra = resolve_cabinet_input_rub(
        amount_rub=amount_rub,
        amount_crypto=amount_crypto,
        crypto=crypto,
        rates=rates,
    )
    usdt_rate_rub = float(rates.get("usdt") or 0)
    if usdt_rate_rub <= 0:
        raise HTTPException(status_code=503, detail="Курс USDT/RUB недоступен")
    markup = resolve_exchanger_markup(ex)
    result = preview_deal(
        amount_rub,
        usdt_rate_rub,
        markup_pct=float(markup["markup_pct"]),
        markup_mode=str(markup["markup_mode"]),
        card_fee_pct=settings.ext_card_fee_pct,
        receive_fee_usd=settings.ext_receive_fee_usd,
        operator_percent=0.0,
    )
    if not result:
        raise HTTPException(status_code=400, detail="Ошибка расчёта")
    result.pop("house_profit_usd", None)
    result.pop("net_profit_rub", None)
    result["markup_pct"] = float(markup["markup_pct"])
    result["markup_mode"] = str(markup["markup_mode"])
    result["withdraw_fees"] = withdraw_fees_map()
    result["withdraw_fee_usd"] = withdraw_fee_usd("usdt")
    result.update(extra)
    return result


async def _attach_payin_to_deal(
    conn,
    deal_id: int,
    exchanger_id: int,
    client_pays_rub: float,
    sub_token: str,
    *,
    fingerprint: str | None = None,
    client_transaction_id: str | None = None,
    callback_url: str | None = None,
) -> dict:
    sub = (sub_token or "SBPRUB").upper()
    user_id = payin_user_id(exchanger_id, fingerprint)
    fiat_int = max(1, int(round(client_pays_rub)))

    canonical_id = (client_transaction_id or "").strip() or f"EXT-{deal_id}"
    discovery = await discover_payin_plan(
        fiat_amount=fiat_int,
        sub_token=sub,
        user_id=user_id,
        create_payin_fn=create_payin_order,
        cancel_payin_fn=cancel_payin,
        client_transaction_id=canonical_id,
    )
    plan = discovery.plan
    if plan.mode == "reject":
        raise HTTPException(
            status_code=400,
            detail=plan.message or "Нет реквизитов на эту сумму.",
        )

    if not (plan.mode == "single" and plan.has_bill and discovery.probe_response):
        # 503, not 502: Cloudflare replaces 502 with an HTML error page and the UI
        # shows a generic «сервер недоступен» instead of our JSON detail.
        detail = (
            (plan.message or "").strip()
            or "Не удалось получить реквизиты для оплаты. Попробуйте через минуту."
        )
        raise HTTPException(status_code=503, detail=detail)

    api_response = discovery.probe_response
    payin_id = discovery.probe_order_id or canonical_id
    data_order = api_response.get("data_order") or {}
    bill = api_response.get("bill") or data_order.get("bill") or {}
    uuid_system = (
        api_response.get("uuid_system")
        or api_response.get("uuid")
        or data_order.get("uuid_system")
        or data_order.get("uuid")
    )
    link = api_response.get("link") or data_order.get("link") or ""
    from merchants.client import attempts_from_response, merchant_id_from_response
    payment_snapshot = {
        "bill": bill,
        "pay_link": link,
        "fiat_amount": fiat_int,
        "merchant_id": merchant_id_from_response(api_response),
        "merchant_attempts": attempts_from_response(api_response),
    }
    if uuid_system:
        payment_snapshot["merchant_uuid"] = str(uuid_system)

    expires_at = resolve_deal_expires_at(api_response)
    ctx_id = canonical_id
    cb_url = (callback_url or "").strip() or None
    resolved_sub = (plan.resolved_sub_token or sub).upper()
    fp = (fingerprint or "").strip() or None
    try:
        await conn.execute(
            """
            UPDATE external_deals
            SET merchant_order_id = $1,
                payment_snapshot = $2::jsonb,
                sub_token = $3,
                expires_at = $4,
                client_transaction_id = COALESCE($5, client_transaction_id),
                callback_url = COALESCE($6, callback_url),
                customer_fingerprint = COALESCE($7, customer_fingerprint),
                merchant_id = $9,
                merchant_attempts = $10::jsonb
            WHERE id = $8
            """,
        payin_id,
        json.dumps(payment_snapshot),
        resolved_sub,
        expires_at,
        ctx_id,
        cb_url,
        fp,
        deal_id,
        payment_snapshot.get("merchant_id"),
        json.dumps(payment_snapshot.get("merchant_attempts") or []),
    )
    except Exception:
        # до применения миграции add_merchant_attribution.sql
        await conn.execute(
            """
            UPDATE external_deals
            SET merchant_order_id = $1,
                payment_snapshot = $2::jsonb,
                sub_token = $3,
                expires_at = $4,
                client_transaction_id = COALESCE($5, client_transaction_id),
                callback_url = COALESCE($6, callback_url),
                customer_fingerprint = COALESCE($7, customer_fingerprint)
            WHERE id = $8
            """,
            payin_id,
            json.dumps(payment_snapshot),
            resolved_sub,
            expires_at,
            ctx_id,
            cb_url,
            fp,
            deal_id,
        )
    return payment_snapshot


async def get_deal_by_client_transaction_id(conn, exchanger_id: int, client_transaction_id: str):
    ctx = (client_transaction_id or "").strip()
    if not ctx:
        return None
    return await conn.fetchrow(
        """
        SELECT d.*, e.is_trusted_client, e.auto_credit_on_payfast
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        WHERE d.exchanger_id = $1 AND d.client_transaction_id = $2
        ORDER BY d.id DESC
        LIMIT 1
        """,
        exchanger_id,
        ctx,
    )


async def create_cabinet_deal_with_payin(
    conn,
    *,
    exchanger_id: int,
    amount_rub: float,
    crypto: str,
    sub_token: str,
    note: str | None,
    created_by: str,
    client_is_new: bool = True,
    payout_on_credit: bool = False,
    payout_wallet: str | None = None,
    client_transaction_id: str | None = None,
    callback_url: str | None = None,
    fingerprint: str | None = None,
    client_stat: Any = None,
) -> dict[str, Any]:
    from operator_availability import has_operator_on_shift

    await ensure_exchanger_hmac_schema(conn)

    if not await has_operator_on_shift():
        raise HTTPException(
            status_code=503,
            detail="Сейчас нет операторов на смене. Попробуйте позже.",
        )

    ex = await get_exchanger_active(conn, exchanger_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Внештатник не найден")

    ctx_id = (client_transaction_id or "").strip() or None
    if ctx_id:
        existing = await get_deal_by_client_transaction_id(conn, exchanger_id, ctx_id)
        if existing:
            out = deal_public_out(dict(existing))
            out["idempotent"] = True
            return out

    markup = resolve_exchanger_markup(ex)

    async with conn.transaction():
        deal = await create_external_deal(
            conn,
            exchanger_id=exchanger_id,
            amount_rub=amount_rub,
            crypto=crypto,
            note=note,
            created_by=created_by,
            pending=True,
            operator_id=None,
            operator_percent=0.0,
            markup_pct=float(markup["markup_pct"]),
            markup_mode=str(markup["markup_mode"]),
            client_is_new=client_is_new,
            payout_on_credit=payout_on_credit,
            payout_wallet=payout_wallet,
        )
        deal_id = int(deal["id"])
        try:
            await _attach_payin_to_deal(
                conn,
                deal_id,
                exchanger_id,
                float(deal["client_pays_rub"]),
                sub_token,
                fingerprint=fingerprint,
                client_transaction_id=ctx_id,
                callback_url=callback_url,
            )
        except HTTPException:
            await conn.execute(
                "UPDATE external_deals SET status = 'cancelled' WHERE id = $1",
                deal_id,
            )
            raise

    try:
        await apply_stat_on_create(
            conn,
            exchanger_id=exchanger_id,
            deal_id=deal_id,
            fingerprint=fingerprint,
            client_stat=client_stat,
        )
    except Exception:
        logger.warning("client_stat on create failed deal=%s", deal_id, exc_info=True)

    row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    return deal_public_out(dict(row))


async def confirm_deal_paid(conn, deal_id: int, exchanger_id: int) -> dict:
    row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    if row["status"] != "awaiting_receipt":
        raise HTTPException(status_code=400, detail="Нельзя подтвердить оплату в этом статусе")
    if row.get("paid_confirmed_at"):
        raise HTTPException(status_code=400, detail="Оплата уже подтверждена")

    await conn.execute(
        """
        UPDATE external_deals
        SET paid_confirmed_at = now()
        WHERE id = $1
        """,
        deal_id,
    )
    refreshed = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    return {
        "status": "awaiting_receipt",
        "message": "Загрузите PDF-чек",
        "requires_receipt": True,
        "deal": deal_public_out(dict(refreshed)),
    }


async def attach_receipt_for_deal(
    conn,
    deal_id: int,
    exchanger_id: int,
    receipt_url: str,
    receipt_file: str,
) -> dict:
    row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    if row["status"] != "awaiting_receipt":
        raise HTTPException(status_code=400, detail="Чек не ожидается")
    if not row.get("paid_confirmed_at"):
        raise HTTPException(status_code=400, detail="Сначала подтвердите оплату")
    if row.get("receipt_submitted_at"):
        raise HTTPException(status_code=400, detail="Чек уже отправлен")
    if int(row.get("required_receipt_type") or 2) == 3:
        raise HTTPException(
            status_code=400,
            detail="Нужно видео экрана, PDF больше не принимается",
        )

    deal_dict = dict(row)
    if receipt_file:
        await conn.execute(
            "UPDATE external_deals SET receipt_file = $1 WHERE id = $2",
            receipt_file,
            deal_id,
        )

    ctx = deal_merchant_ctx(deal_dict)
    result = await payin_set_check_for_order(ctx, receipt_url)
    response_status = int(result.get("status") or 500)
    if response_status >= 400 and not payfast_set_check_already_paid(result):
        body = result.get("body")
        # 5xx / throttling are transport/provider failures: keep the deal retryable.
        if response_status >= 500 or response_status in (408, 429):
            raise HTTPException(status_code=503, detail="Мерчант временно недоступен. Повторите отправку чека позже.")
        wants_video = merchant_wants_video(body)
        await record_payfast_review(
            conn,
            incident_type="receipt_rejected_permanent",
            deal_id=deal_id,
            merchant_ref=str(deal_dict.get("merchant_order_id") or f"EXT-{deal_id}"),
            detail={"source": "receipt", "http_status": response_status, "reason": "merchant_rejected"},
        )
        if wants_video:
            await conn.execute(
                """
                UPDATE external_deals
                SET required_receipt_type = 3
                WHERE id = $1
                """,
                deal_id,
            )
        raise HTTPException(
            status_code=400,
            detail=merchant_reject_detail(body, video=wants_video),
        )

    await conn.execute(
        """
        UPDATE external_deals
        SET status = 'pending',
            receipt_submitted_at = now()
        WHERE id = $1
        """,
        deal_id,
    )
    refreshed = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    return {"status": "pending", "message": "Чек отправлен", "deal": deal_public_out(dict(refreshed))}


async def get_deal_by_merchant_ref(conn, ref: str):
    """Payfast uuid, EXT-{id} или merchant_order_id → строка сделки + внештатник."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    deal_id: int | None = None
    upper = ref.upper()
    if upper.startswith("EXT-"):
        try:
            deal_id = int(ref.split("-", 1)[1])
        except ValueError:
            deal_id = None
    return await conn.fetchrow(
        """
        SELECT d.*, e.name AS exchanger_name, e.is_trusted_client, e.auto_credit_on_payfast,
               ea.username AS account_username
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
        WHERE ($1::int IS NOT NULL AND d.id = $1)
           OR d.merchant_order_id = $2
           OR d.client_transaction_id = $2
           OR d.payment_snapshot->>'merchant_uuid' = $2
           OR ('EXT-' || d.id::text) = $2
        ORDER BY d.created_at DESC
        LIMIT 1
        """,
        deal_id,
        ref,
    )


async def get_external_deals_for_payfast_reconcile(conn, *, min_age_sec: int = 90):
    return await conn.fetch(
        """
        SELECT d.id
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        WHERE d.status = 'pending'
          AND d.receipt_submitted_at IS NOT NULL
          AND d.receipt_submitted_at < now() - make_interval(secs => $1)
          AND e.is_trusted_client = TRUE
          AND e.auto_credit_on_payfast = TRUE
          AND COALESCE(d.required_receipt_type, 2) != 3
        ORDER BY d.receipt_submitted_at ASC
        LIMIT 50
        """,
        min_age_sec,
    )


async def try_auto_confirm_external_deal_on_payfast(
    conn,
    deal_id: int,
    *,
    webhook_body: dict | None = None,
) -> dict:
    row = await conn.fetchrow(
        """
        SELECT d.*, e.name AS exchanger_name, e.is_trusted_client, e.auto_credit_on_payfast,
               ea.username AS account_username
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
        WHERE d.id = $1
        """,
        deal_id,
    )
    if not row:
        return {"skipped": True, "reason": "deal_not_found"}

    from external_exchange_trust import effective_auto_credit

    if not effective_auto_credit(
        bool(row["is_trusted_client"]), bool(row["auto_credit_on_payfast"])
    ):
        return {"skipped": True, "reason": "auto_credit_disabled"}

    status = str(row["status"] or "")
    if status == "confirmed":
        from payfast_payin_guard import is_payfast_failure_status, payfast_status_from_payload

        callback_status = payfast_status_from_payload(webhook_body)
        if is_payfast_failure_status(callback_status):
            await record_payfast_review(
                conn,
                incident_type="post_completion_provider_error",
                deal_id=deal_id,
                merchant_ref=str(row.get("merchant_order_id") or f"EXT-{deal_id}"),
                detail={"source": "callback", "status": callback_status, "reason": "provider_failure_after_confirmed"},
            )
        return {"skipped": True, "reason": "already_confirmed", "deal_id": deal_id}
    if status != "pending":
        return {"skipped": True, "reason": f"status_{status}", "deal_id": deal_id}
    if not row.get("receipt_submitted_at"):
        return {"skipped": True, "reason": "no_receipt", "deal_id": deal_id}
    if int(row.get("required_receipt_type") or 2) == 3:
        return {"skipped": True, "reason": "video_required", "deal_id": deal_id}

    deal_dict = dict(row)
    ctx = deal_merchant_ctx(deal_dict)
    ctx["direction"] = "buy"

    from payfast_payin_guard import payfast_identity_mismatch, verify_payfast_ready_for_complete

    callback_mismatch = payfast_identity_mismatch(ctx, webhook_body)
    if callback_mismatch:
        await record_payfast_review(
            conn,
            incident_type="callback_mismatch",
            deal_id=deal_id,
            merchant_ref=str(deal_dict.get("merchant_order_id") or f"EXT-{deal_id}"),
            detail={
                "source": "callback",
                "reason": callback_mismatch,
                "provided_fields": [key for key in ("uuid", "uuid_system", "client_transaction_id", "amount", "data_order") if isinstance(webhook_body, dict) and key in webhook_body],
            },
        )
        return {"skipped": True, "reason": callback_mismatch, "deal_id": deal_id}

    ok, err = await verify_payfast_ready_for_complete(ctx, webhook_body)
    if not ok:
        if err and err.endswith("_mismatch"):
            await record_payfast_review(
                conn,
                incident_type="callback_mismatch",
                deal_id=deal_id,
                merchant_ref=str(deal_dict.get("merchant_order_id") or f"EXT-{deal_id}"),
                detail={"source": "get_order", "reason": err},
            )
        return {"skipped": True, "reason": err or "payfast_not_ready", "deal_id": deal_id}

    from external_exchange_service import confirm_external_deal

    result = await confirm_external_deal(conn, deal_id, confirmed_by="payfast:webhook")
    return {"confirmed": True, "deal_id": deal_id, "deal": result, "exchanger": deal_dict}


async def request_external_deal_receipt_type(
    conn,
    deal_id: int,
    req_type: int,
    *,
    source: str = "appeals",
) -> dict | None:
    """Appeals/webhook: запрос PDF (2) или видео через оператора (3) для сделки кабинета."""
    row = await conn.fetchrow(
        """
        SELECT d.*, e.name AS exchanger_name, ea.username AS account_username
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
        WHERE d.id = $1
        """,
        deal_id,
    )
    if not row:
        return None

    status = str(row["status"] or "")
    allowed = ("awaiting_receipt", "pending")
    if status not in allowed:
        logger.info(
            "external deal receipt request blocked deal=%s status=%s source=%s",
            deal_id,
            status,
            source,
        )
        return None

    if req_type == 3:
        if status == "pending":
            await conn.execute(
                """
                UPDATE external_deals
                SET status = 'awaiting_receipt',
                    required_receipt_type = 3,
                    receipt_submitted_at = NULL
                WHERE id = $1
                """,
                deal_id,
            )
        else:
            await conn.execute(
                "UPDATE external_deals SET required_receipt_type = 3 WHERE id = $1",
                deal_id,
            )
    elif req_type == 2 and status == "pending":
        await conn.execute(
            """
            UPDATE external_deals
            SET status = 'awaiting_receipt',
                required_receipt_type = 2,
                receipt_submitted_at = NULL
            WHERE id = $1
            """,
            deal_id,
        )
    else:
        await conn.execute(
            "UPDATE external_deals SET required_receipt_type = $1 WHERE id = $2",
            req_type,
            deal_id,
        )

    refreshed = await conn.fetchrow(
        """
        SELECT d.*, e.name AS exchanger_name, ea.username AS account_username
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
        WHERE d.id = $1
        """,
        deal_id,
    )
    return dict(refreshed) if refreshed else None


async def request_external_deal_video(
    conn,
    deal_id: int,
    *,
    source: str = "appeals",
) -> dict | None:
    return await request_external_deal_receipt_type(
        conn, deal_id, req_type=3, source=source
    )


async def cancel_cabinet_deal(conn, deal_id: int, exchanger_id: int) -> dict:
    row = await get_deal_for_exchanger(conn, deal_id, exchanger_id)
    if not row:
        raise HTTPException(status_code=404, detail="Сделка не найдена")
    try:
        if row.get("merchant_order_id") or row.get("payment_snapshot"):
            await cancel_payin_for_order(deal_merchant_ctx(dict(row)))
    except Exception as exc:
        logger.warning("cancel payin for deal %s: %s", deal_id, exc)
    try:
        result = await cancel_external_deal(conn, deal_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "cancelled", "deal": deal_public_out(result)}
