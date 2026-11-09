"""BUY orders for web: payin plan, split, operator, cashback, promo, remainder."""
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal as D

import asyncpg
from fastapi import HTTPException

from config import settings
from db import get_pool
from economics_snapshot import build_economics_snapshot
from merchant_client import cancel_payin, create_payin_order
from payin_discovery import discover_payin_plan
from payin_resolver import plan_to_dict
from exchange_discount_db import (
    apply_discount_with_conn,
    get_active_discounts,
    hold_discount_for_order,
)
from promo_bonus import apply_fixed_rub_bonus
from user_cashback_db import (
    apply_cashback_with_conn,
    hold_cashback_for_order,
    should_use_cashback,
)

logger = logging.getLogger("buy_order_web")

PAYFAST_RECOVERY_BUFFER_MINUTES = 7
PAYFAST_FALLBACK_WINDOW_MINUTES = 20


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payfast_date_end(response: dict) -> datetime | None:
    data_order = response.get("data_order") or {}
    raw = response.get("dateEnd") or data_order.get("dateEnd")
    if not raw:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class PayfastDeadlines:
    merchant_expires_at: datetime
    requisites_expires_at: datetime
    merchant_deadline_from_provider: bool
    merchant_window_too_short: bool


def _payfast_deadlines(response: dict, *, now: datetime | None = None) -> PayfastDeadlines:
    now_utc = _as_utc(now) or datetime.now(tz=timezone.utc)
    provider_end = _payfast_date_end(response)
    merchant_window_too_short = bool(
        provider_end is not None
        and provider_end <= now_utc + timedelta(minutes=PAYFAST_RECOVERY_BUFFER_MINUTES)
    )
    merchant_expires_at = provider_end or now_utc + timedelta(
        minutes=PAYFAST_FALLBACK_WINDOW_MINUTES
    )
    requisites_expires_at = merchant_expires_at - timedelta(
        minutes=PAYFAST_RECOVERY_BUFFER_MINUTES
    )
    return PayfastDeadlines(
        merchant_expires_at=merchant_expires_at,
        requisites_expires_at=requisites_expires_at,
        merchant_deadline_from_provider=provider_end is not None,
        merchant_window_too_short=merchant_window_too_short,
    )


async def _cancel_payfast_if_present(uuid_system: str | None, order_id: str) -> None:
    if not uuid_system:
        return
    try:
        await cancel_payin(str(uuid_system))
    except Exception as e:
        logger.warning("cancel PayFast payin %s: %s", order_id, e)


async def _raise_short_payfast_deadline(uuid_system: str | None, order_id: str) -> None:
    await _cancel_payfast_if_present(uuid_system, order_id)
    raise HTTPException(
        status_code=503,
        detail="Не удалось выдать реквизиты, попробуйте позже.",
    )


async def _user_has_active_order(conn, user_id: int) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1 FROM orders
        WHERE user_id = $1
          AND status IN (
              'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
          )
        LIMIT 1
        """,
        user_id,
    )
    return row is not None


async def payin_fit_preview(fiat_amount: int, sub_token: str, user_id: int) -> dict:
    from payin_requisite_rail import preview_payin_fit

    pool = await get_pool()
    async with pool.acquire() as conn:
        fit = await preview_payin_fit(
            conn,
            amount_rub=int(fiat_amount),
            sub_token=sub_token,
            user_id=user_id,
        )
    payload = fit.as_dict()
    mode = str(payload.get("offer_mode") or "none")
    if fit.offer and mode == "happy":
        payload["message"] = (
            f"Счастливая сделка: к оплате {payload['pay_rub']:.0f} ₽ "
            f"(−{payload['credit_rub']:.0f} ₽). Разница на баланс после оплаты."
        )
    elif fit.offer and mode == "silent":
        payload["message"] = (
            f"К оплате {payload['pay_rub']:.0f} ₽. "
            f"Разница {payload['credit_rub']:.0f} ₽ вернётся на баланс после оплаты."
        )
    else:
        payload["message"] = ""
    return payload


async def payin_preview(fiat_amount: int, sub_token: str, user_id: int) -> dict:
    """Локальный preview без запросов к мерчанту (реквизиты проверяются при create)."""
    _ = user_id
    amount = int(fiat_amount)
    sub = (sub_token or "SBPRUB").upper()
    op_min = int(settings.operator_fallback_min_rub)
    if amount < op_min:
        return {
            "mode": "reject",
            "parts": [],
            "pay_now": 0,
            "remainder_rub": 0,
            "message": "Нет реквизитов на эту сумму.",
            "has_bill": False,
            "partial_probe_ok": False,
            "resolved_sub_token": None,
        }
    return {
        "mode": "single_candidate",
        "parts": [amount],
        "pay_now": amount,
        "remainder_rub": 0,
        "message": "",
        "has_bill": False,
        "partial_probe_ok": False,
        "resolved_sub_token": "SBPRUB" if sub == "CARDRUB" else None,
    }


async def _create_buy_order_in_tx(conn, **kwargs) -> dict:
    order_id = kwargs["order_id"]
    user_id = kwargs["user_id"]
    crypto = kwargs["crypto_sym"]
    crypto_amount = kwargs["crypto_amount"]
    fiat_amount = kwargs["fiat_amount"]
    rate = kwargs["rate"]
    requisites = kwargs["requisites"]
    merchant_order_id = kwargs.get("merchant_order_id")
    sub_token = kwargs.get("sub_token")
    expires_at = kwargs.get("expires_at")
    group_id = kwargs.get("group_id")
    part_index = kwargs.get("part_index")
    cashback_applied_rub = kwargs.get("cashback_applied_rub") or 0
    exchange_discount_applied_rub = kwargs.get("exchange_discount_applied_rub") or 0
    exchange_discount_id = kwargs.get("exchange_discount_id")
    pending_remainder_rub = kwargs.get("pending_remainder_rub") or 0
    payment_snapshot = kwargs.get("payment_snapshot")
    client_ip = kwargs.get("client_ip")
    stored_card_fee_pct = kwargs.get("card_fee_pct")
    if stored_card_fee_pct is None:
        from runtime_settings import card_fee_pct

        stored_card_fee_pct = card_fee_pct(manual=False)
    from order_source import coerce_public_order_source

    payin_requisite_id = kwargs.get("payin_requisite_id")
    order_source = coerce_public_order_source(kwargs.get("order_source"))
    overpay_credit_rub = float(kwargs.get("overpay_credit_rub") or 0)
    overpay_rub = float(kwargs.get("overpay_rub") or 0)
    manual_buy = kwargs.get("manual_buy")
    if manual_buy is None:
        manual_buy = kwargs.get("card_fee_pct") is not None
    snap_json = json.dumps(payment_snapshot) if payment_snapshot else None

    promo_row = await conn.fetchrow(
        """
        INSERT INTO promo_bonus_usages (user_id, order_id, promo_code, bonus_percent, bonus_fixed_rub)
        SELECT pa.user_id, $2, pa.promo_code, 0, pc.client_fixed_bonus_rub
        FROM promo_attributions pa
        JOIN promo_campaigns pc ON pc.code = pa.promo_code AND pc.is_active = TRUE
        WHERE pa.user_id = $1
          AND pc.client_fixed_bonus_rub IS NOT NULL
          AND pc.client_fixed_bonus_rub > 0
          AND pc.author_telegram_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM promo_bonus_usages pbu WHERE pbu.user_id = pa.user_id)
        ON CONFLICT (user_id) DO NOTHING
        RETURNING promo_code, bonus_fixed_rub
        """,
        user_id,
        order_id,
    )

    final_crypto = D(str(crypto_amount))
    final_fiat = D(str(fiat_amount))
    promo_code = None
    if promo_row and promo_row["bonus_fixed_rub"]:
        promo_code = promo_row["promo_code"]
        crypto_base = crypto.split("_")[0].lower()
        final_crypto, final_fiat = apply_fixed_rub_bonus(
            "buy",
            final_crypto,
            final_fiat,
            D(str(promo_row["bonus_fixed_rub"])),
            crypto_base,
            D(str(rate)),
        )

    economics_json = json.dumps(
        build_economics_snapshot(
            "buy",
            crypto,
            float(final_fiat),
            float(final_crypto),
            float(rate),
            cashback_applied_rub=float(cashback_applied_rub),
            card_fee=float(stored_card_fee_pct),
            manual_buy=bool(manual_buy),
            buy_markup_override=kwargs.get("buy_markup_override"),
            triangle_subsidy_rub=float(kwargs.get("triangle_subsidy_rub") or 0),
        )
    )

    await conn.execute(
        """
        INSERT INTO orders (
            order_id, user_id, crypto, direction, crypto_amount, fiat_amount,
            rate, requisites, status, created_at, expires_at, updated_at,
            merchant_order_id, sub_token, promo_code, group_id, part_index,
            cashback_applied_rub, exchange_discount_applied_rub, exchange_discount_id,
            payment_snapshot, economics_snapshot, pending_remainder_rub, client_ip,
            card_fee_pct, order_source, payin_requisite_id, overpay_rub, overpay_credit_rub
        )
        VALUES (
            $1, $2, $3, 'buy', $4, $5, $6, $7, 'CREATED', now(),
            COALESCE($8::timestamptz, now() + interval '30 minutes'), now(),
            $9, $10, $11, $12, $13, $14, $15, $16, $17::jsonb, $18::jsonb, $19, $20::inet, $21, $22, $23, $24, $25
        )
        """,
        order_id,
        user_id,
        crypto,
        float(final_crypto),
        float(final_fiat),
        rate,
        requisites,
        expires_at,
        merchant_order_id,
        sub_token,
        promo_code,
        group_id,
        part_index,
        cashback_applied_rub,
        exchange_discount_applied_rub,
        exchange_discount_id,
        snap_json,
        economics_json,
        pending_remainder_rub,
        client_ip,
        stored_card_fee_pct,
        order_source,
        payin_requisite_id,
        overpay_rub,
        overpay_credit_rub,
    )
    return {
        "promo_applied": promo_row is not None,
        "crypto_amount": float(final_crypto),
        "fiat_amount": float(final_fiat),
    }


class _PayinRailMiss(Exception):
    """Нет подходящего payin-реквизита — откатываем tx и идём на PayFast."""


async def try_create_payin_rail_buy(
    *,
    user_id: int,
    crypto_sym: str,
    crypto_amount: float,
    fiat_amount: int,
    rate: float,
    requisites: str,
    sub_token: str,
    client_ip: str | None,
    accept_round_up: bool = False,
    buy_markup_override: float | None = None,
) -> dict | None:
    """Карта реквизитчика вместо PayFast. None — нет смены, клиент не подходит или пул пуст."""
    from runtime_settings import triangle_enabled

    if not triangle_enabled():
        return None
    from payin_requisite_rail import payin_reviewer_on_shift

    if not await payin_reviewer_on_shift():
        return None
    from buy_crypto_amount import clamp_buy_crypto_amount
    from order_service import _active_order_conflict
    from payin_requisite_rail import (
        METHOD_SUB_TOKENS,
        bill_from_requisite,
        payin_card_fee_pct,
        payment_expires_at,
        reserve_payin_slot,
        user_can_use_payin_rail,
    )

    pool = await get_pool()
    probe_oid = str(uuid.uuid4().int)[:8]
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
                if not await user_can_use_payin_rail(conn, user_id):
                    raise _PayinRailMiss()
                if await _user_has_active_order(conn, user_id):
                    existing = await conn.fetchval(
                        """
                        SELECT order_id FROM orders
                        WHERE user_id = $1
                          AND status IN (
                              'CREATED', 'AWAITING_CHECK', 'PENDING',
                              'OPERATOR_PENDING', 'COMPLETED'
                          )
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        user_id,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=_active_order_conflict(str(existing or "")),
                    )
                use_cb = await should_use_cashback(user_id)
                disc_applied = 0.0
                disc_id = None
                active_disc = await get_active_discounts(
                    user_id, fiat_amount=float(fiat_amount)
                )
                if active_disc:
                    disc_id = active_disc[0]["id"]
                    fiat_base, crypto_base, disc_applied, disc_id = await apply_discount_with_conn(
                        conn,
                        disc_id,
                        user_id,
                        float(fiat_amount),
                        float(crypto_amount),
                        rate,
                        crypto_sym,
                    )
                    if disc_applied > 0 and not await hold_discount_for_order(
                        conn, user_id, probe_oid, disc_id
                    ):
                        disc_applied = 0.0
                        disc_id = None
                        fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)
                else:
                    fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)

                fiat_pay, crypto_out, cb_applied = await apply_cashback_with_conn(
                    conn,
                    user_id,
                    fiat_base,
                    crypto_base,
                    rate,
                    crypto_sym,
                    use_cashback=use_cb,
                )
                if cb_applied > 0:
                    held = await hold_cashback_for_order(
                        conn, user_id, probe_oid, cb_applied
                    )
                    if held <= 0:
                        fiat_pay = float(fiat_base)
                        crypto_out = float(crypto_base)
                        cb_applied = 0.0
                    elif held < cb_applied - 0.01:
                        cb_applied = held
                        fiat_pay = float(fiat_base) - held
                        crypto_out = float(crypto_base)
                fiat_int = max(1, int(round(fiat_pay)))
                quoted_crypto = float(crypto_out)
                profit_snap = build_economics_snapshot(
                    "buy",
                    crypto_sym,
                    float(fiat_int),
                    float(quoted_crypto),
                    float(rate),
                    cashback_applied_rub=float(cb_applied or 0),
                    card_fee=0.0,
                    manual_buy=False,
                    buy_markup_override=buy_markup_override,
                )
                reserved = await reserve_payin_slot(
                    conn,
                    order_id=probe_oid,
                    amount_rub=fiat_int,
                    sub_token=sub_token,
                    accept_round_up=accept_round_up,
                    buy_profit_rub=profit_snap["service_profit_rub"],
                )
                if reserved is None:
                    raise _PayinRailMiss()
                slot, fit = reserved
                overpay_credit = float(fit.credit_rub or 0)
                if fit.kind == "round_up":
                    fiat_int = max(1, int(round(float(fit.pay_rub))))
                    crypto_out = quoted_crypto
                else:
                    crypto_out = clamp_buy_crypto_amount(
                        crypto_out,
                        fiat_amount=float(fiat_int),
                        rate=float(rate),
                        crypto=crypto_sym,
                        cashback_applied_rub=float(cb_applied or 0),
                        exchange_discount_applied_rub=float(disc_applied or 0),
                    )
                bill = bill_from_requisite(
                    {
                        "bank": slot.bank,
                        "requisites": slot.requisites,
                        "holder_name": slot.holder_name,
                    }
                )
                expires_at = payment_expires_at(slot.deadline_at)
                effective_sub = METHOD_SUB_TOKENS.get(slot.method, sub_token.upper())
                payment_snapshot = {
                    "bill": bill,
                    "fiat_amount": fiat_int,
                    "payin_requisite_id": slot.id,
                    "rail": "requisite",
                    "payin_fit": fit.kind,
                    "overpay_credit_rub": overpay_credit,
                }
                await _create_buy_order_in_tx(
                    conn,
                    order_id=probe_oid,
                    user_id=user_id,
                    crypto_sym=crypto_sym,
                    crypto_amount=crypto_out,
                    fiat_amount=float(fiat_int),
                    rate=rate,
                    requisites=requisites,
                    sub_token=effective_sub,
                    expires_at=expires_at,
                    payment_snapshot=payment_snapshot,
                    cashback_applied_rub=cb_applied,
                    exchange_discount_applied_rub=disc_applied,
                    exchange_discount_id=disc_id,
                    client_ip=client_ip,
                    card_fee_pct=payin_card_fee_pct(slot.cost_pct),
                    manual_buy=False,
                    order_source=order_source,
                    payin_requisite_id=slot.id,
                    overpay_rub=overpay_credit,
                    overpay_credit_rub=overpay_credit,
                    buy_markup_override=buy_markup_override,
                    triangle_subsidy_rub=float(fit.subsidy_rub or 0),
                )
                row = await conn.fetchrow(
                    "SELECT * FROM orders WHERE order_id = $1", probe_oid
                )
    except _PayinRailMiss:
        return None
    except HTTPException:
        raise
    return {
        "row": row,
        "bill": bill,
        "link": "",
        "parts_count": 1,
        "part_index": 1,
        "remainder_rub": 0,
        "cashback_applied": cb_applied,
        "exchange_discount_applied": disc_applied,
        "resolved_sub_token": effective_sub if effective_sub != sub_token.upper() else None,
        "payment_note": "Оплата на карту сервиса. После перевода нажмите «Я оплатил» и приложите чек.",
        "rail": "requisite",
    }


def _no_shift_block_detail(gate) -> str:
    coin = str(getattr(gate, "coin", "") or "").upper()
    label = coin if coin.isalnum() else "этой валюты"
    if getattr(gate, "reason", "") == "coin_short":
        return (
            f"Сейчас на кошельке недостаточно {label} для этой суммы. "
            "Укажите меньшую сумму или попробуйте позже."
        )
    if getattr(gate, "reason", "") == "coin_unknown":
        return "Сейчас не можем выдать эту сумму. Попробуйте позже."
    return "Сейчас нет операторов на смене. Попробуйте позже."


async def create_buy_web(
    *,
    user_id: int,
    crypto_sym: str,
    crypto_amount: float,
    fiat_amount: int,
    rate: float,
    requisites: str,
    sub_token: str,
    plan_mode: str | None,
    client_ip: str | None,
    accept_round_up: bool = False,
    buy_markup_override: float | None = None,
    order_source: str = "site",
    requisite_retry: bool = False,
) -> dict:
    from fastapi import HTTPException

    from bot_status_bridge import is_user_banned as _is_banned
    _banned, _, _ban_type = await _is_banned(user_id)
    if _banned:
        if _ban_type == "soft":
            raise HTTPException(
                status_code=503,
                detail="Сейчас нет операторов на смене. Попробуйте позже.",
            )
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован.")

    from auto_service_gate import resolve_no_shift_access
    from no_shift_blocks import record_no_shift_block

    gate = await resolve_no_shift_access(
        user_id,
        "buy",
        int(fiat_amount),
        crypto=crypto_sym,
        crypto_amount=float(crypto_amount),
    )
    auto_served = gate.kind == "allow_auto"
    if gate.kind == "block" and requisite_retry:
        if gate.reason in ("coin_short", "coin_unknown"):
            return {
                "requisite_retry_empty": True,
                "message": _no_shift_block_detail(gate),
            }
        return {"requisite_retry_empty": True}
    if gate.kind == "block":
        block_reason = gate.reason if gate.reason in ("coin_short", "coin_unknown") else "no_shift"
        await record_no_shift_block(
            user_id,
            "buy",
            reason=block_reason,
            fiat_amount=int(fiat_amount),
        )
        raise HTTPException(
            status_code=503,
            detail=_no_shift_block_detail(gate),
        )

    sub = sub_token.upper()

    async def _maybe_mark_auto(order_id: str) -> None:
        if not auto_served or not order_id:
            return
        from auto_order_flags import mark_order_auto_served
        from auto_no_shift_notify import notify_auto_buy_order

        pool = await get_pool()
        async with pool.acquire() as conn:
            await mark_order_auto_served(conn, order_id, None)
        await notify_auto_buy_order(
            order_id=order_id,
            user_id=user_id,
            fiat_amount=float(fiat_amount),
            crypto=crypto_sym,
        )

    rail = await try_create_payin_rail_buy(
        user_id=user_id,
        crypto_sym=crypto_sym,
        crypto_amount=crypto_amount,
        fiat_amount=fiat_amount,
        rate=rate,
        requisites=requisites,
        sub_token=sub,
        client_ip=client_ip,
        accept_round_up=accept_round_up,
        buy_markup_override=buy_markup_override,
    )
    if rail is not None:
        row = rail.get("row") or {}
        oid = str(row.get("order_id") or "")
        await _maybe_mark_auto(oid)
        return rail

    discovery = await discover_payin_plan(
        fiat_amount=fiat_amount,
        sub_token=sub,
        user_id=user_id,
        create_payin_fn=create_payin_order,
        cancel_payin_fn=cancel_payin,
    )
    plan = discovery.plan
    effective_sub = plan.resolved_sub_token or sub
    op_min = int(settings.operator_fallback_min_rub)

    if plan.mode == "reject":
        if requisite_retry:
            return {"requisite_retry_empty": True}
        raise HTTPException(
            status_code=400,
            detail=plan.message or "Нет реквизитов на эту сумму.",
        )

    if plan.mode == "single" and plan.has_bill and discovery.probe_response:
        probe_oid = discovery.probe_order_id or str(uuid.uuid4().int)[:8]
        from buy_crypto_amount import clamp_buy_crypto_amount

        api_response = discovery.probe_response
        data_order = api_response.get("data_order") or {}
        bill = api_response.get("bill") or data_order.get("bill") or {}
        uuid_system = (
            api_response.get("uuid_system")
            or api_response.get("uuid")
            or data_order.get("uuid_system")
            or data_order.get("uuid")
        )
        deadlines = _payfast_deadlines(api_response)
        if (
            deadlines.merchant_deadline_from_provider
            and deadlines.merchant_window_too_short
        ):
            await _raise_short_payfast_deadline(
                str(uuid_system) if uuid_system else None,
                probe_oid,
            )
        merchant_expires_at = deadlines.merchant_expires_at
        expires_at = deadlines.requisites_expires_at
        link = api_response.get("link") or data_order.get("link") or ""

        pool = await get_pool()
        # Один лок на пользователя на ВСю операцию: применение скидки/кешбэка,
        # их hold, INSERT заказа и hold кешбэка — в одной транзакции, иначе
        # параллельные заявки переиспользуют один и тот же баланс (over-hold).
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
                    if await _user_has_active_order(conn, user_id):
                        from order_service import _active_order_conflict

                        existing = await conn.fetchval(
                            """
                            SELECT order_id FROM orders
                            WHERE user_id = $1
                              AND status IN (
                                  'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
                              )
                            ORDER BY created_at DESC LIMIT 1
                            """,
                            user_id,
                        )
                        raise HTTPException(
                            status_code=409,
                            detail=_active_order_conflict(str(existing or "")),
                        )
                    use_cb = await should_use_cashback(user_id)
                    disc_applied = 0.0
                    disc_id = None
                    # Только ваучеры, подходящие по минимальной сумме заказа.
                    active_disc = await get_active_discounts(
                        user_id, fiat_amount=float(fiat_amount)
                    )
                    if active_disc:
                        disc_id = active_disc[0]["id"]
                        fiat_base, crypto_base, disc_applied, disc_id = await apply_discount_with_conn(
                            conn,
                            disc_id,
                            user_id,
                            float(fiat_amount),
                            float(crypto_amount),
                            rate,
                            crypto_sym,
                        )
                        if disc_applied > 0 and not await hold_discount_for_order(
                            conn, user_id, probe_oid, disc_id
                        ):
                            disc_applied = 0.0
                            disc_id = None
                            fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)
                    else:
                        fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)

                    fiat_pay, crypto_out, cb_applied = await apply_cashback_with_conn(
                        conn,
                        user_id,
                        fiat_base,
                        crypto_base,
                        rate,
                        crypto_sym,
                        use_cashback=use_cb,
                    )
                    if cb_applied > 0:
                        held = await hold_cashback_for_order(
                            conn, user_id, probe_oid, cb_applied
                        )
                        if held <= 0:
                            fiat_pay = float(fiat_base)
                            crypto_out = float(crypto_base)
                            cb_applied = 0.0
                        elif held < cb_applied - 0.01:
                            cb_applied = held
                            fiat_pay = float(fiat_base) - held
                            crypto_out = float(crypto_base)
                    fiat_int = max(1, int(round(fiat_pay)))
                    crypto_out = clamp_buy_crypto_amount(
                        crypto_out,
                        fiat_amount=float(fiat_int),
                        rate=float(rate),
                        crypto=crypto_sym,
                        cashback_applied_rub=float(cb_applied or 0),
                        exchange_discount_applied_rub=float(disc_applied or 0),
                    )
                    # Скидка или кешбэк снизили сумму к оплате — перевыставляем
                    # счёт мерчанта (probe был на исходную), иначе клиент видит
                    # меньшую сумму, а PayFast ждёт старую.
                    if int(fiat_int) != int(fiat_amount):
                        if uuid_system:
                            try:
                                await cancel_payin(str(uuid_system))
                            except Exception as e:
                                logger.warning(
                                    "cancel stale probe %s for reduced pay: %s", probe_oid, e
                                )
                        new_resp = await create_payin_order(
                            order_id=probe_oid,
                            user_id=user_id,
                            fiat_amount=fiat_int,
                            sub_token=effective_sub,
                        )
                        new_data = new_resp.get("data_order") or {}
                        bill = new_resp.get("bill") or new_data.get("bill") or {}
                        from payin_resolver import _bill_has_reciver

                        if (new_resp or {}).get("status_pending") == "error" or not _bill_has_reciver(
                            bill if isinstance(bill, dict) else None
                        ):
                            raise HTTPException(
                                status_code=503,
                                detail="Нет реквизитов на сумму к оплате, попробуйте позже",
                            )
                        uuid_system = (
                            new_resp.get("uuid_system")
                            or new_resp.get("uuid")
                            or new_data.get("uuid_system")
                            or new_data.get("uuid")
                        )
                        link = new_resp.get("link") or new_data.get("link") or ""
                        api_response = new_resp
                        deadlines = _payfast_deadlines(new_resp)
                        if (
                            deadlines.merchant_deadline_from_provider
                            and deadlines.merchant_window_too_short
                        ):
                            await _raise_short_payfast_deadline(
                                str(uuid_system) if uuid_system else None,
                                probe_oid,
                            )
                        merchant_expires_at = deadlines.merchant_expires_at
                        expires_at = deadlines.requisites_expires_at
                    payment_snapshot = {
                        "bill": bill,
                        "pay_link": link,
                        "fiat_amount": fiat_int,
                        "merchant_expires_at": merchant_expires_at.isoformat(),
                        "merchant_id": (api_response or {}).get("_merchant_id"),
                        "merchant_attempts": (api_response or {}).get("_merchant_attempts") or [],
                    }
                    if uuid_system:
                        payment_snapshot["merchant_uuid"] = str(uuid_system)
                    await _create_buy_order_in_tx(
                        conn,
                        order_id=probe_oid,
                        user_id=user_id,
                        crypto_sym=crypto_sym,
                        crypto_amount=crypto_out,
                        fiat_amount=float(fiat_int),
                        rate=rate,
                        requisites=requisites,
                        merchant_order_id=str(probe_oid),
                        sub_token=effective_sub,
                        expires_at=expires_at,
                        payment_snapshot=payment_snapshot,
                        cashback_applied_rub=cb_applied,
                        exchange_discount_applied_rub=disc_applied,
                        exchange_discount_id=disc_id,
                        client_ip=client_ip,
                        buy_markup_override=buy_markup_override,
                        order_source=order_source,
                    )
                    row = await conn.fetchrow(
                        "SELECT * FROM orders WHERE order_id = $1", probe_oid
                    )
        except HTTPException:
            # Конфликт активной заявки и т.п. — транзакция откатилась, холды не
            # зафиксированы; отменяем осиротевший merchant-probe.
            if uuid_system:
                try:
                    await cancel_payin(str(uuid_system))
                except Exception as e:
                    logger.warning("probe cancel after conflict %s: %s", probe_oid, e)
            raise
        except Exception:
            # Всё в одной транзакции — БД-холды откатились автоматически.
            # Осталось отменить merchant-probe.
            if uuid_system:
                try:
                    await cancel_payin(str(uuid_system))
                except Exception as e:
                    logger.warning("compensating merchant cancel %s: %s", probe_oid, e)
            raise
        out = {
            "row": row,
            "bill": bill,
            "link": link,
            "parts_count": 1,
            "part_index": 1,
            "remainder_rub": 0,
            "cashback_applied": cb_applied,
            "exchange_discount_applied": disc_applied,
            "resolved_sub_token": plan.resolved_sub_token,
            "payment_note": plan.message if plan.resolved_sub_token == "SBPRUB" else "",  # nosec B105
        }
        if row:
            await _maybe_mark_auto(str(row["order_id"]))
        return out

    if plan_mode and plan_mode != "operator":
        raise HTTPException(
            status_code=400,
            detail="Недопустимый режим оплаты для этой суммы",
        )

    if plan.mode == "operator" or (plan.mode == "reject" and fiat_amount >= op_min):
        if requisite_retry:
            return {"requisite_retry_empty": True}
        from requisite_retry import open_requisite_retry

        network = crypto_sym.split("_", 1)[1] if "_" in crypto_sym else None
        opened = await open_requisite_retry(
            {
                "user_id": user_id,
                "fiat_amount": int(fiat_amount),
                "crypto": crypto_sym,
                "network": network,
                "wallet": requisites,
                "sub_token": sub,
                "rate": float(rate),
                "crypto_amount": float(crypto_amount),
                "order_source": order_source,
            }
        )
        if opened.get("saved"):
            return opened
        if auto_served:
            await record_no_shift_block(
                user_id,
                "buy",
                reason="merchant_no_bill",
                fiat_amount=int(fiat_amount),
            )
            raise HTTPException(
                status_code=503,
                detail="Автоматические реквизиты сейчас недоступны. Попробуйте позже.",
            )
        import runtime_settings
        from order_service import _validate_amounts
        from routers.public import get_rates_cached

        oid = str(uuid.uuid4().int)[:8]
        crypto_base = crypto_sym.split("_")[0].lower()
        market = await get_rates_cached()
        op_crypto = float(crypto_amount)
        rapira = float((market or {}).get(crypto_base) or 0)
        if rapira > 0:
            op_rate = rapira * runtime_settings.buy_markup(manual=True)
            op_fiat = max(
                1,
                int(
                    D(str(op_crypto * op_rate)).to_integral_value(
                        rounding=ROUND_CEILING
                    )
                ),
            )
        else:
            crypto_dec, fiat_dec, rate_dec = _validate_amounts(
                crypto_base, "buy", fiat_amount, None, market, manual_buy=True
            )
            op_crypto = float(crypto_dec)
            op_fiat = float(fiat_dec)
            op_rate = float(rate_dec)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
                if await _user_has_active_order(conn, user_id):
                    from order_service import _active_order_conflict

                    existing = await conn.fetchval(
                        """
                        SELECT order_id FROM orders
                        WHERE user_id = $1
                          AND status IN (
                              'CREATED', 'AWAITING_CHECK', 'PENDING',
                              'OPERATOR_PENDING', 'COMPLETED'
                          )
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        user_id,
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=_active_order_conflict(str(existing or "")),
                    )
                await _create_buy_order_in_tx(
                    conn,
                    order_id=oid,
                    user_id=user_id,
                    crypto_sym=crypto_sym,
                    crypto_amount=op_crypto,
                    fiat_amount=op_fiat,
                    rate=op_rate,
                    requisites=requisites,
                    sub_token=sub,
                    client_ip=client_ip,
                    card_fee_pct=runtime_settings.card_fee_pct(manual=True),
                    order_source=order_source,
                )
                await conn.execute(
                    "UPDATE orders SET status = 'OPERATOR_PENDING', expires_at = now() + interval '24 hours' WHERE order_id = $1",
                    oid,
                )
            row = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", oid)
        from order_service import buy_without_requisites_message

        return {
            "order_id": oid,
            "status": "OPERATOR_PENDING",
            "operator_message": buy_without_requisites_message(oid),
            "row": row,
        }

    raise HTTPException(
        status_code=400,
        detail=plan.message or "Не удалось получить реквизиты для оплаты.",
    )
