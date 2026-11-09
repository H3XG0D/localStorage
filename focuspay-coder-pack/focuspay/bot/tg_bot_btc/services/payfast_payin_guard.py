"""Проверка статуса Payfast payin перед COMPLETED/выплатой крипты."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from services.merchant_order_id import resolve_payfast_uuid_system

logger = logging.getLogger("payfast_payin_guard")

PAYFAST_FAIL_STATUSES = frozenset(
    {"ERROR", "FAILED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}
)
# Финальное подтверждение трейдера (Payfast §3.3).
PAYFAST_FINAL_STATUSES = frozenset({"SUCCSES", "SUCCESS", "COMPLETED"})


def payfast_status_from_payload(payload: dict | None) -> str:
    if not payload or not isinstance(payload, dict):
        return ""
    for key in ("status",):
        raw = payload.get(key)
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


def payfast_amount_from_payload(payload: dict | None):
    """Извлечь сумму из ответа Payfast /get_order или callback."""
    if not payload or not isinstance(payload, dict):
        return None
    if "amount" in payload:
        return payload.get("amount")
    for nest in ("data_order", "order", "body"):
        nested = payload.get(nest)
        if isinstance(nested, dict) and "amount" in nested:
            return nested.get("amount")
    return None


def is_payfast_failure_status(status: str | None) -> bool:
    return bool(status) and str(status).upper() in PAYFAST_FAIL_STATUSES


def is_webhook_payment_failure(status: str | None) -> bool:
    return is_payfast_failure_status(status)


def is_payfast_file_accepted(status_file) -> bool:
    return status_file in (0, "0")


def is_payfast_file_pending(status_file) -> bool:
    return status_file in (1, "1")


def is_payfast_recheck_requested(status_check) -> bool:
    """Payfast запросил доп. проверку: 2=PDF повторно, 3=видео, 4=неизвестно (считаем блокирующим).

    Даже если status/status_file выглядят settled — выплата запрещена до снятия recheck.
    """
    return str(status_check).strip() in {"2", "3", "4"}


def payfast_recheck_req_type(status_check) -> int:
    """Тип чека для клиента при recheck Payfast.

    Payfast: 2=повторный PDF, 3=видео, 4=неизвестно.
    Мы всегда просим видео — повторный PDF почти никогда не помогает.
    """
    del status_check
    return 3


def payfast_date_end_appeal_from_payload(payload: dict | None) -> datetime | None:
    if not payload or not isinstance(payload, dict):
        return None
    raw = payload.get("dateEndAppeal")
    if raw is None:
        for nest in ("data_order", "order", "body"):
            nested = payload.get(nest)
            if isinstance(nested, dict) and nested.get("dateEndAppeal") is not None:
                raw = nested.get("dateEndAppeal")
                break
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_payfast_appeal_active(payload: dict | None) -> bool:
    """Апелляция Payfast (recheck) ещё не закончилась — не экспайрим заявку."""
    sc = payfast_status_check_from_payload(payload)
    if not is_payfast_recheck_requested(sc):
        return False
    appeal_end = payfast_date_end_appeal_from_payload(payload)
    if appeal_end is None:
        return True
    return appeal_end > datetime.now(timezone.utc)


PAYFAST_CHECK_REVIEW_EXTENSION = timedelta(minutes=30)
# PAID — чек у трейдера, SUCCSES ещё нет. Не закрываем и не экспайрим.
PAYFAST_REVIEW_HOLD_REASONS = frozenset(
    {"payfast_check_pending", "payfast_awaiting_trader"}
)


async def keep_order_alive_for_payfast_review(
    order: dict,
    api_resp: dict | None,
    *,
    pf_err: str,
    source: str = "reconciler",
) -> bool:
    """Продлить таймер, пока Payfast проверяет чек или ждёт апрув трейдера."""
    if pf_err not in PAYFAST_REVIEW_HOLD_REASONS:
        return False

    order_id = str(order["order_id"])
    now = datetime.now(timezone.utc)
    appeal_end = payfast_date_end_appeal_from_payload(api_resp)
    until = (
        appeal_end
        if appeal_end is not None and appeal_end > now
        else now + PAYFAST_CHECK_REVIEW_EXTENSION
    )

    from services.db import extend_order_expires_at

    await extend_order_expires_at(order_id, until)
    logger.info(
        "payfast review keep-alive order=%s source=%s reason=%s until=%s",
        order_id,
        source,
        pf_err,
        until.isoformat(),
    )
    return True


async def handle_payfast_recheck(
    order: dict,
    api_resp: dict | None,
    *,
    source: str = "reconciler",
    bot=None,
) -> tuple[bool, str | None]:
    """Продлить expires_at и запросить у клиента PDF/видео, если Payfast ждёт recheck."""
    sc = payfast_status_check_from_payload(api_resp)
    if not is_payfast_recheck_requested(sc):
        return False, "not_recheck"

    appeal_end = payfast_date_end_appeal_from_payload(api_resp)
    now = datetime.now(timezone.utc)
    if appeal_end is not None and appeal_end <= now:
        return False, "appeal_ended"

    order_id = str(order["order_id"])
    req_type = payfast_recheck_req_type(sc)
    until = appeal_end if appeal_end is not None else now + timedelta(minutes=45)

    from services.db import extend_order_expires_at

    await extend_order_expires_at(order_id, until)

    from services.video_receipt_request import request_client_receipt_check

    ok, reason = await request_client_receipt_check(
        order_id,
        req_type,
        bot=bot,
        source=source,
    )
    if ok:
        logger.info(
            "payfast recheck handled order=%s req_type=%s source=%s until=%s",
            order_id,
            req_type,
            source,
            until.isoformat(),
        )
        return True, reason or "ok"
    logger.warning(
        "payfast recheck request failed order=%s req_type=%s source=%s reason=%s",
        order_id,
        req_type,
        source,
        reason,
    )
    return False, reason


def is_payfast_settled(status: str | None, status_file=None) -> bool:
    """Оплата подтверждена трейдером — только SUCCSES/SUCCESS/COMPLETED.

    PAID + status_file=0 — чек принят, апрува ещё нет. Инцидент 2026-09-10:
    reconciler закрывал BUY и писал ops «отправьте крипту», пока кабинет
    Payfast ещё не апрувнул.
    status_check=1 НЕ означает подтверждение (§3.4: доп. чек не запрошен).
    """
    del status_file
    st = str(status or "").strip().upper()
    if not st or is_payfast_failure_status(st):
        return False
    return st in PAYFAST_FINAL_STATUSES


def payfast_block_message(reason: str | None) -> str:
    r = (reason or "").lower()
    if r.startswith("payfast_status_"):
        st = r.replace("payfast_status_", "").upper()
        return f"Payfast: статус {st} — выплата запрещена, сверьте кабинет мерчанта."
    if r == "payfast_not_paid":
        return "Payfast: оплата ещё не подтверждена (ACCEPTED/PENDING)."
    if r == "payfast_check_pending":
        return "Payfast: чек на проверке трейдера (PAID, status_file=1)."
    if r == "payfast_awaiting_trader":
        return "Payfast: чек принят, ждём SUCCSES трейдера — крипту не отправлять."
    if r == "payfast_api_error":
        return "Не удалось проверить статус в Payfast. Повторите позже."
    if r == "payfast_status_check_missing":
        return "Payfast: нет подтверждения оплаты — сверьте статус в кабинете."
    if r == "payfast_recheck_requested":
        return "Payfast запросил доп. проверку (видео/PDF) — выплата запрещена до снятия проверки."
    if r == "payfast_uuid_missing":
        return "Payfast: не найден ID заявки в мерчанте — выплата запрещена, проверьте вручную."
    return "Payfast: выплата запрещена — сверьте статус заявки."


async def verify_payfast_ready_for_payout(
    order: dict, *, require_uuid: bool = False
) -> tuple[bool, str | None, dict | None]:
    """
    Живая проверка Payfast перед отправкой крипты.
    Returns (ok, error_code, api_response).

    require_uuid=True: если у заявки нет uuid_system в мерчанте — fail-closed
    (для Payfast-payin заявок на этапе COMPLETED/выплаты uuid обязан быть).
    """
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
        from services.merchant_client import get_merchant_order

        resp = await get_merchant_order(uuid_system)
    except Exception as e:
        logger.warning("payfast verify failed order=%s: %s", order.get("order_id"), e)
        return False, "payfast_api_error", None

    if (resp or {}).get("status_pending") == "error":
        return False, "payfast_api_error", resp

    st = payfast_status_from_payload(resp)
    sf = payfast_status_file_from_payload(resp)
    sc = payfast_status_check_from_payload(resp)

    if is_payfast_failure_status(st):
        return False, f"payfast_status_{st.lower()}", resp

    # Дополнительная проверка блокирует только незавершённый ордер.
    # Финальный SUCCSES имеет приоритет над status_check.
    if is_payfast_recheck_requested(sc) and not is_payfast_settled(st, sf):
        logger.warning(
            "payfast recheck requested order=%s status=%r status_check=%r — payout blocked",
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
) -> tuple[bool, str | None, dict | None]:
    """Перед переводом в COMPLETED по webhook.

    На этом этапе заявка — Payfast-payin, поэтому uuid обязателен (fail-closed).
    """
    wh_st = payfast_status_from_payload(webhook_body or {})
    if is_payfast_failure_status(wh_st):
        return False, f"webhook_status_{wh_st.lower()}", None

    return await verify_payfast_ready_for_payout(order, require_uuid=True)
