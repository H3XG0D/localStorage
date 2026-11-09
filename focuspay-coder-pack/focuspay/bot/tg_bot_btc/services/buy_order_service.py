"""Создание BUY-заявок: payin, split, оператор, кешбэк."""
from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from services import config_rates, runtime_settings
from services.db import create_order_with_promo, get_pool, user_has_active_buy_order
from services.order_groups import (
    cancel_order_group,
    create_order_group,
    load_group_part_fiats,
    on_part_paid,
    part_crypto_amount,
)
from services.buy_payout_validate import clamp_buy_crypto_amount
from services.economics_snapshot import build_economics_snapshot
from services.payin_resolver import PayinPlan, build_payin_plan, plan_to_dict
from services.exchange_discount_db import (
    apply_discount_with_conn,
    hold_discount_for_order,
    release_discount_for_order,
)
from services.user_cashback_db import (
    apply_cashback_with_conn,
    hold_cashback_for_order,
    release_cashback_for_order,
    should_use_cashback,
)

logger = logging.getLogger("buy_order_service")


def _buy_markup_from_quoted_rate(crypto: str, rate: float) -> float | None:
    from services.rates_api import get_cached_buy_market

    market = float(get_cached_buy_market(crypto) or 0)
    if market > 0 and float(rate or 0) > 0:
        return float(rate) / market
    return None


async def payin_preview(
    fiat_amount: int,
    sub_token: str,
    *,
    probe_api_response: dict | None = None,
) -> dict:
    plan = build_payin_plan(fiat_amount, sub_token, api_response=probe_api_response)
    return plan_to_dict(plan)


async def create_operator_order(
    *,
    order_id: str,
    user_id: int,
    crypto: str,
    crypto_amount: float,
    fiat_amount: float,
    rate: float,
    requisites: str,
    sub_token: str,
    exchange_discount_id: int | None = None,
    amount_currency: str | None = None,
) -> dict:
    use_cb = await should_use_cashback(user_id)
    cb_applied = 0.0
    disc_applied = 0.0
    disc_id = exchange_discount_id
    fiat_pay = float(fiat_amount)
    crypto_out = float(crypto_amount)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
            if await user_has_active_buy_order(conn, user_id, exclude_order_id=order_id):
                raise ValueError("ACTIVE_ORDER_EXISTS")
            fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)
            if disc_id:
                fiat_base, crypto_base, disc_applied, disc_id = await apply_discount_with_conn(
                    conn,
                    disc_id,
                    user_id,
                    float(fiat_amount),
                    crypto_amount,
                    rate,
                    crypto,
                )
                if disc_applied > 0 and not await hold_discount_for_order(
                    conn, user_id, order_id, disc_id
                ):
                    disc_applied = 0.0
                    disc_id = None
                    fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)

            fiat_pay, crypto_out, cb_applied = await apply_cashback_with_conn(
                conn,
                user_id,
                fiat_base,
                crypto_base,
                rate,
                crypto,
                use_cashback=use_cb,
            )
            if cb_applied > 0:
                held = await hold_cashback_for_order(conn, user_id, order_id, cb_applied)
                if held <= 0:
                    fiat_pay, crypto_out, cb_applied = float(fiat_base), float(crypto_base), 0.0
                else:
                    cb_applied = held
                    fiat_pay = float(fiat_base) - held
                    crypto_out = float(crypto_base)

            fiat_int = max(1, int(round(fiat_pay)))
            lock_crypto = str(amount_currency or "").strip().lower() == "crypto"
            if lock_crypto:
                from decimal import Decimal, ROUND_CEILING

                fiat_int = max(
                    1,
                    int(Decimal(str(fiat_pay)).to_integral_value(rounding=ROUND_CEILING)),
                )
            crypto_out = clamp_buy_crypto_amount(
                crypto_out,
                fiat_amount=float(fiat_int),
                rate=float(rate),
                crypto=crypto,
                cashback_applied_rub=cb_applied,
                exchange_discount_applied_rub=disc_applied,
                lock_crypto=lock_crypto,
            )
            if float(fiat_int) < config_rates.OPERATOR_FALLBACK_MIN_RUB:
                raise ValueError(
                    f"Минимум для заявки оператору: "
                    f"{config_rates.OPERATOR_FALLBACK_MIN_RUB:,.0f} ₽".replace(",", " ")
                )
            await conn.execute(
                """
                INSERT INTO orders (
                    order_id, user_id, crypto, direction, crypto_amount, fiat_amount,
                    rate, requisites, wallet_address, status, created_at, expires_at, updated_at,
                    order_source, sub_token, card_fee_pct, cashback_applied_rub,
                    exchange_discount_applied_rub, exchange_discount_id, economics_snapshot
                )
                VALUES (
                    $1, $2, $3, 'buy', $4, $5, $6, $7::varchar, $7::text, 'OPERATOR_PENDING',
                    now(), now() + interval '24 hours', now(), 'bot', $8, $9, $10, $11, $12, $13::jsonb
                )
                """,
                order_id,
                user_id,
                crypto,
                crypto_out,
                float(fiat_int),
                rate,
                requisites,
                sub_token,
                runtime_settings.card_fee_pct(manual=True),
                cb_applied,
                disc_applied,
                disc_id,
                json.dumps(
                    build_economics_snapshot(
                        "buy",
                        crypto,
                        float(fiat_int),
                        crypto_out,
                        float(rate),
                        cashback_applied_rub=cb_applied,
                        card_fee=runtime_settings.card_fee_pct(manual=True),
                        manual_buy=True,
                    )
                ),
            )
    return {
        "order_id": order_id,
        "status": "OPERATOR_PENDING",
        "mode": "operator",
        "fiat_amount": fiat_int,
        "cashback_applied": cb_applied,
        "exchange_discount_applied": disc_applied,
    }


async def _ensure_bill_via_poll(api_response: dict | None) -> dict | None:
    """Если в ответе create нет bill — опрашиваем мерчанта (как discovery)."""
    from services.payin_resolver import extract_merchant_uuid, get_bill_from_response

    if not api_response or api_response.get("status_pending") == "error":
        return api_response
    if get_bill_from_response(api_response):
        return api_response
    uuid_val = extract_merchant_uuid(api_response)
    if not uuid_val:
        return api_response
    from services.payin_discovery import _poll_bill

    bill = await _poll_bill(uuid_val)
    if bill:
        merged = dict(api_response)
        merged["bill"] = bill
        return merged
    return api_response


def _payin_uuid(api_response: dict | None) -> str | None:
    pending = api_response or {}
    pending_data = pending.get("data_order") or {}
    uuid_val = (
        pending.get("uuid_system")
        or pending.get("uuid")
        or pending_data.get("uuid_system")
        or pending_data.get("uuid")
    )
    return str(uuid_val) if uuid_val else None


async def _compensate_unpersisted_buy_order(
    order_id: str,
    *,
    disc_applied: float,
    cb_applied: float,
    merchant_uuid: str | None,
    cancel_payin_fn,
) -> None:
    """Снять холд/скидку и отменить payin, если заявка не записалась."""
    if merchant_uuid and cancel_payin_fn:
        try:
            await cancel_payin_fn(str(merchant_uuid))
        except Exception as e:
            logger.warning("cancel payin after unpersisted buy %s: %s", order_id, e)
    if disc_applied > 0:
        try:
            await release_discount_for_order(order_id)
        except Exception as e:
            logger.warning("release discount after unpersisted buy %s: %s", order_id, e)
    if cb_applied > 0:
        try:
            await release_cashback_for_order(order_id)
        except Exception as e:
            logger.warning("release cashback after unpersisted buy %s: %s", order_id, e)


async def create_buy_part_order(
    *,
    create_payin_order_fn,
    cancel_payin_fn,
    order_id: str,
    user_id: int,
    crypto: str,
    crypto_amount: float,
    fiat_amount: int,
    rate: float,
    requisites: str,
    sub_token: str,
    callback_url: str,
    group_id: int | None = None,
    part_index: int | None = None,
    parts_count: int = 1,
    apply_remainder_credit: int = 0,
    api_response: dict | None = None,
    exchange_discount_id: int | None = None,
    amount_currency: str | None = None,
) -> dict[str, Any]:
    use_cb = await should_use_cashback(user_id)
    cb_applied = 0.0
    disc_applied = 0.0
    disc_id = exchange_discount_id
    fiat_pay = float(fiat_amount)
    crypto_out = float(crypto_amount)

    pool_pre = await get_pool()
    async with pool_pre.acquire() as conn_pre:
        async with conn_pre.transaction():
            await conn_pre.execute("SELECT pg_advisory_xact_lock($1)", user_id)
            if await user_has_active_buy_order(conn_pre, user_id, exclude_order_id=order_id):
                raise ValueError("ACTIVE_ORDER_EXISTS")
            fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)
            if disc_id:
                fiat_base, crypto_base, disc_applied, disc_id = await apply_discount_with_conn(
                    conn_pre,
                    disc_id,
                    user_id,
                    float(fiat_amount),
                    crypto_amount,
                    rate,
                    crypto,
                )
                if disc_applied > 0 and not await hold_discount_for_order(
                    conn_pre, user_id, order_id, disc_id
                ):
                    disc_applied = 0.0
                    disc_id = None
                    fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)

            fiat_pay, crypto_out, cb_applied = await apply_cashback_with_conn(
                conn_pre,
                user_id,
                fiat_base,
                crypto_base,
                rate,
                crypto,
                use_cashback=use_cb,
            )
            if cb_applied > 0:
                held = await hold_cashback_for_order(
                    conn_pre, user_id, order_id, cb_applied
                )
                if held <= 0:
                    fiat_pay, crypto_out, cb_applied = float(fiat_base), float(crypto_base), 0.0
                else:
                    cb_applied = held
                    fiat_pay = float(fiat_base) - held
                    crypto_out = float(crypto_base)

    fiat_int = max(1, int(round(fiat_pay)))
    lock_crypto = str(amount_currency or "").strip().lower() == "crypto"
    if lock_crypto:
        from decimal import Decimal, ROUND_CEILING

        fiat_int = max(
            1,
            int(Decimal(str(fiat_pay)).to_integral_value(rounding=ROUND_CEILING)),
        )
    crypto_out = clamp_buy_crypto_amount(
        crypto_out,
        fiat_amount=float(fiat_int),
        rate=float(rate),
        crypto=crypto,
        cashback_applied_rub=cb_applied,
        exchange_discount_applied_rub=disc_applied,
        lock_crypto=lock_crypto,
    )

    # Холд уже закоммичен. CancelledError (таймаут поиска реквизитов) не
    # ловится except Exception — снимаем hold/скидку в finally, если INSERT
    # заявки так и не прошёл.
    order_created = False
    order_result: dict[str, Any] = {}
    bill: dict = {}
    link = ""
    try:
        # Скидка на обмен или кешбэк снизили сумму к оплате — счёт мерчанта
        # (probe был на исходную сумму) надо перевыставить на fiat_int.
        if api_response is not None and int(fiat_int) != int(fiat_amount):
            stale_uuid = _payin_uuid(api_response)
            if stale_uuid and cancel_payin_fn:
                try:
                    await cancel_payin_fn(stale_uuid)
                except Exception as e:
                    logger.warning("cancel stale probe %s for discount: %s", order_id, e)
            api_response = None

        data_order: dict = {}
        if api_response is None:
            api_response = await create_payin_order_fn(
                order_id=order_id,
                user_id=user_id,
                fiat_amount=fiat_int,
                callback_url=callback_url,
                sub_token=sub_token,
            )
            # Счёт мерчанта после create может прийти не сразу (особенно при
            # повторном создании из-за скидки) — поллим так же, как discovery,
            # иначе валидные реквизиты теряются и заявка уходит на оператора.
            api_response = await _ensure_bill_via_poll(api_response)
        if (api_response or {}).get("status_pending") == "error":
            raise ValueError("PAYMENT_PROVIDER_ERROR")

        data_order = (api_response or {}).get("data_order") or {}
        bill = (api_response or {}).get("bill") or data_order.get("bill") or {}
        from services.payin_resolver import _bill_has_reciver

        if not _bill_has_reciver(bill if isinstance(bill, dict) else None):
            raise ValueError("NO_BILL")

        uuid_system = _payin_uuid(api_response)
        date_end_str = (api_response or {}).get("dateEnd") or data_order.get("dateEnd")
        merchant_end = None
        if date_end_str:
            try:
                merchant_end = datetime.fromisoformat(str(date_end_str).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                merchant_end = None
        from services.buyer_access_guards import calculate_payfast_deadlines

        deadlines = calculate_payfast_deadlines(merchant_end)
        if deadlines.merchant_deadline_from_provider and deadlines.merchant_window_too_short:
            raise ValueError("PAYFAST_DEADLINE_TOO_SHORT")

        expires_at_override = deadlines.requisites_expires_at
        link = (api_response or {}).get("link") or data_order.get("link") or ""
        payment_snapshot = {
            "bill": bill,
            "pay_link": link,
            "fiat_amount": fiat_int,
            "merchant_expires_at": deadlines.merchant_expires_at.isoformat(),
            "requisites_issued_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        if amount_currency:
            payment_snapshot["amount_currency"] = str(amount_currency).strip().lower()
        if uuid_system:
            payment_snapshot["merchant_uuid"] = str(uuid_system)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                order_result = await _create_buy_order_in_tx(
                    conn,
                    order_id=order_id,
                    user_id=user_id,
                    crypto=crypto,
                    crypto_amount=crypto_out,
                    fiat_amount=float(fiat_int),
                    rate=rate,
                    requisites=requisites,
                    merchant_order_id=str(uuid_system) if uuid_system else str(order_id),
                    sub_token=sub_token,
                    expires_at_override=expires_at_override,
                    group_id=group_id,
                    part_index=part_index,
                    cashback_applied_rub=cb_applied,
                    exchange_discount_applied_rub=disc_applied,
                    exchange_discount_id=disc_id,
                    payment_snapshot=payment_snapshot,
                    pending_remainder_rub=float(apply_remainder_credit or 0),
                    amount_currency=amount_currency,
                )
        order_created = True
    finally:
        if not order_created:
            await asyncio.shield(
                _compensate_unpersisted_buy_order(
                    order_id,
                    disc_applied=disc_applied,
                    cb_applied=cb_applied,
                    merchant_uuid=_payin_uuid(api_response),
                    cancel_payin_fn=cancel_payin_fn,
                )
            )

    return {
        "order_id": order_id,
        "api_response": api_response,
        "order_result": order_result,
        "bill": bill,
        "link": link,
        "fiat_amount": fiat_int,
        "crypto_amount": crypto_out,
        "cashback_applied": cb_applied,
        "exchange_discount_applied": disc_applied,
        "group_id": group_id,
        "part_index": part_index,
        "parts_count": parts_count,
    }


async def _create_buy_order_in_tx(conn, **kwargs):
    import json
    from services.promo_bonus import apply_fixed_rub_bonus
    from decimal import Decimal as D

    order_id = kwargs["order_id"]
    user_id = kwargs["user_id"]
    crypto = kwargs["crypto"]
    crypto_amount = kwargs["crypto_amount"]
    fiat_amount = kwargs["fiat_amount"]
    rate = kwargs["rate"]
    requisites = kwargs["requisites"]
    merchant_order_id = kwargs.get("merchant_order_id")
    sub_token = kwargs.get("sub_token")
    expires_at_override = kwargs.get("expires_at_override")
    group_id = kwargs.get("group_id")
    part_index = kwargs.get("part_index")
    cashback_applied_rub = kwargs.get("cashback_applied_rub") or 0
    exchange_discount_applied_rub = kwargs.get("exchange_discount_applied_rub") or 0
    exchange_discount_id = kwargs.get("exchange_discount_id")
    pending_remainder_rub = kwargs.get("pending_remainder_rub") or 0
    payment_snapshot = kwargs.get("payment_snapshot")
    amount_currency = kwargs.get("amount_currency")
    snap_json = json.dumps(payment_snapshot) if payment_snapshot else None
    card_fee = kwargs.get("card_fee")
    if card_fee is None:
        card_fee = runtime_settings.card_fee_pct(manual=False)
    payin_requisite_id = kwargs.get("payin_requisite_id")
    overpay_credit_rub = float(kwargs.get("overpay_credit_rub") or 0)
    overpay_rub = float(kwargs.get("overpay_rub") or 0)

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

    from services import config_rates as cfg

    final_crypto = clamp_buy_crypto_amount(
        float(final_crypto),
        fiat_amount=float(final_fiat),
        rate=float(rate),
        crypto=crypto,
        cashback_applied_rub=float(cashback_applied_rub or 0),
        exchange_discount_applied_rub=float(exchange_discount_applied_rub or 0),
        lock_crypto=str(amount_currency or "").strip().lower() == "crypto",
    )
    economics_json = json.dumps(
        build_economics_snapshot(
            "buy",
            crypto,
            float(final_fiat),
            final_crypto,
            float(rate),
            cashback_applied_rub=float(cashback_applied_rub),
            card_fee=card_fee,
            buy_markup_override=_buy_markup_from_quoted_rate(crypto, rate),
            triangle_subsidy_rub=float(kwargs.get("triangle_subsidy_rub") or 0),
        )
    )

    await conn.execute(
        """
        INSERT INTO orders (
            order_id, user_id, crypto, direction, crypto_amount, fiat_amount,
            rate, requisites, wallet_address, status, created_at, expires_at, updated_at,
            merchant_order_id, sub_token, promo_code, group_id, part_index,
            cashback_applied_rub, exchange_discount_applied_rub, exchange_discount_id,
            payment_snapshot, economics_snapshot, pending_remainder_rub, card_fee_pct, order_source,
            payin_requisite_id, overpay_rub, overpay_credit_rub
        )
        VALUES (
            $1, $2, $3, 'buy', $4, $5, $6, $7::varchar, $7::text, 'CREATED', now(),
            COALESCE($8::timestamptz, now() + interval '20 minutes'), now(),
            $9, $10, $11, $12, $13, $14, $15, $16, $17::jsonb, $18::jsonb, $19, $20, 'bot', $21, $22, $23
        )
        """,
        order_id,
        user_id,
        crypto,
        final_crypto,
        float(final_fiat),
        rate,
        requisites,
        expires_at_override,
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
        card_fee,
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
    pass


async def create_payin_rail_buy_order(
    *,
    generate_order_id_fn,
    user_id: int,
    crypto: str,
    crypto_amount: float,
    fiat_amount: int,
    rate: float,
    wallet: str,
    sub_token: str,
    exchange_discount_id: int | None = None,
    amount_currency: str | None = None,
    accept_round_up: bool = False,
) -> dict[str, Any] | None:
    """Карта реквизитчика вместо PayFast. None — нет смены, слота или клиент не подходит."""
    from services.runtime_settings import triangle_enabled

    if not triangle_enabled():
        return None
    from services.payin_requisite_rail import payin_reviewer_on_shift

    if not await payin_reviewer_on_shift():
        return None
    from services.payin_requisite_rail import (
        METHOD_SUB_TOKENS,
        bill_from_requisite,
        payin_card_fee_pct,
        payment_expires_at,
        reserve_payin_slot,
        user_can_use_payin_rail,
    )

    order_id = generate_order_id_fn()
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
                if not await user_can_use_payin_rail(conn, user_id):
                    raise _PayinRailMiss()
                if await user_has_active_buy_order(conn, user_id, exclude_order_id=order_id):
                    raise ValueError("ACTIVE_ORDER_EXISTS")
                use_cb = await should_use_cashback(user_id)
                disc_applied = 0.0
                disc_id = exchange_discount_id
                fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)
                if disc_id:
                    fiat_base, crypto_base, disc_applied, disc_id = await apply_discount_with_conn(
                        conn,
                        disc_id,
                        user_id,
                        float(fiat_amount),
                        crypto_amount,
                        rate,
                        crypto,
                    )
                    if disc_applied > 0 and not await hold_discount_for_order(
                        conn, user_id, order_id, disc_id
                    ):
                        disc_applied = 0.0
                        disc_id = None
                        fiat_base, crypto_base = float(fiat_amount), float(crypto_amount)
                fiat_pay, crypto_out, cb_applied = await apply_cashback_with_conn(
                    conn,
                    user_id,
                    fiat_base,
                    crypto_base,
                    rate,
                    crypto,
                    use_cashback=use_cb,
                )
                if cb_applied > 0:
                    held = await hold_cashback_for_order(conn, user_id, order_id, cb_applied)
                    if held <= 0:
                        fiat_pay, crypto_out, cb_applied = float(fiat_base), float(crypto_base), 0.0
                    else:
                        cb_applied = held
                        fiat_pay = float(fiat_base) - held
                        crypto_out = float(crypto_base)
                fiat_int = max(1, int(round(fiat_pay)))
                lock_crypto = str(amount_currency or "").strip().lower() == "crypto"
                quoted_crypto = float(crypto_out)
                profit_snap = build_economics_snapshot(
                    "buy",
                    crypto,
                    float(fiat_int),
                    float(quoted_crypto),
                    float(rate),
                    cashback_applied_rub=float(cb_applied or 0),
                    card_fee=0.0,
                    buy_markup_override=_buy_markup_from_quoted_rate(crypto, rate),
                )
                reserved = await reserve_payin_slot(
                    conn,
                    order_id=order_id,
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
                    lock_crypto = True
                else:
                    crypto_out = clamp_buy_crypto_amount(
                        crypto_out,
                        fiat_amount=float(fiat_int),
                        rate=float(rate),
                        crypto=crypto,
                        cashback_applied_rub=float(cb_applied or 0),
                        exchange_discount_applied_rub=float(disc_applied or 0),
                        lock_crypto=lock_crypto,
                    )
                bill = bill_from_requisite(
                    {
                        "bank": slot.bank,
                        "requisites": slot.requisites,
                        "holder_name": slot.holder_name,
                    }
                )
                effective_sub = METHOD_SUB_TOKENS.get(slot.method, (sub_token or "CARDRUB").upper())
                payment_snapshot = {
                    "bill": bill,
                    "fiat_amount": fiat_int,
                    "payin_requisite_id": slot.id,
                    "rail": "requisite",
                    "payin_fit": fit.kind,
                    "overpay_credit_rub": overpay_credit,
                }
                created = await _create_buy_order_in_tx(
                    conn,
                    order_id=order_id,
                    user_id=user_id,
                    crypto=crypto,
                    crypto_amount=crypto_out,
                    fiat_amount=float(fiat_int),
                    rate=rate,
                    requisites=wallet,
                    sub_token=effective_sub,
                    expires_at_override=payment_expires_at(slot.deadline_at),
                    payment_snapshot=payment_snapshot,
                    cashback_applied_rub=cb_applied,
                    exchange_discount_applied_rub=disc_applied,
                    exchange_discount_id=disc_id,
                    amount_currency="crypto" if fit.kind == "round_up" else amount_currency,
                    card_fee=payin_card_fee_pct(slot.cost_pct),
                    payin_requisite_id=slot.id,
                    overpay_rub=overpay_credit,
                    overpay_credit_rub=overpay_credit,
                    triangle_subsidy_rub=float(fit.subsidy_rub or 0),
                )
    except _PayinRailMiss:
        return None
    return {
        "order_id": order_id,
        "fiat_amount": created["fiat_amount"],
        "bill": bill,
        "link": "",
        "api_response": {"bill": bill},
        "order_result": {
            "crypto_amount": created["crypto_amount"],
            "fiat_amount": created["fiat_amount"],
        },
        "cashback_applied": cb_applied,
        "exchange_discount_applied": disc_applied,
        "rail": "requisite",
        "resolved_sub_token": effective_sub,
    }


async def execute_buy_with_plan(
    *,
    create_payin_order_fn,
    cancel_payin_fn,
    generate_order_id_fn,
    user_id: int,
    crypto: str,
    crypto_amount: float,
    fiat_amount: int,
    rate: float,
    requisites: str,
    sub_token: str,
    callback_url: str,
    plan: PayinPlan,
    exchange_discount_id: int | None = None,
    amount_currency: str | None = None,
) -> dict[str, Any]:
    if plan.mode == "operator":
        from services.rates_api import get_cached_buy_market

        oid = generate_order_id_fn()
        base = crypto.split("_")[0].lower()
        market = float(get_cached_buy_market(base) or 0)
        op_rate = float(rate)
        op_crypto = float(crypto_amount)
        op_fiat = float(fiat_amount)
        amount_cur = str(amount_currency or "").strip().lower()
        lock_crypto = amount_cur == "crypto"
        if market > 0 and amount_cur == "rub":
            from decimal import ROUND_CEILING as _CEIL

            op_rate = market * runtime_settings.buy_markup(manual=True)
            op_fiat = max(
                1,
                int(
                    Decimal(str(op_crypto * op_rate)).to_integral_value(
                        rounding=_CEIL
                    )
                ),
            )
        elif market > 0 and not lock_crypto:
            op_rate = market * runtime_settings.buy_markup(manual=True)
            op_crypto = float(fiat_amount) / op_rate
        await create_operator_order(
            order_id=oid,
            user_id=user_id,
            crypto=crypto,
            crypto_amount=op_crypto,
            fiat_amount=op_fiat,
            rate=op_rate,
            requisites=requisites,
            sub_token=sub_token,
            exchange_discount_id=exchange_discount_id,
            amount_currency=amount_currency,
        )
        return {"mode": "operator", "order_id": oid, "fiat_amount": op_fiat}

    if plan.mode == "single":
        parts = [int(fiat_amount)]
    elif plan.mode == "remainder_balance" and plan.remainder_rub > 0:
        parts = [int(plan.parts[0]) if plan.parts else int(plan.pay_now)]
    else:
        parts = plan.parts or [int(plan.pay_now or fiat_amount)]

    group_id = None
    if len(parts) > 1:
        group_id = await create_order_group(
            user_id=user_id,
            crypto=crypto,
            total_fiat=float(fiat_amount),
            total_crypto=crypto_amount,
            rate=rate,
            requisites=requisites,
            sub_token=sub_token,
            parts_count=len(parts),
            parts_fiat=parts,
        )

    part_fiat = int(parts[0])
    total_fiat = float(fiat_amount)
    # Крипта только за фактически оплаченную часть (split / остаток на баланс).
    if len(parts) > 1 or plan.mode == "remainder_balance" or part_fiat < int(round(total_fiat)):
        part_crypto = await part_crypto_amount(
            {"total_fiat": total_fiat, "total_crypto": crypto_amount},
            part_fiat,
        )
    else:
        part_crypto = crypto_amount
    remainder_credit = plan.remainder_rub if plan.mode == "remainder_balance" else 0

    last_err = None
    for _ in range(3):
        oid = generate_order_id_fn()
        try:
            result = await create_buy_part_order(
                create_payin_order_fn=create_payin_order_fn,
                cancel_payin_fn=cancel_payin_fn,
                order_id=oid,
                user_id=user_id,
                crypto=crypto,
                crypto_amount=part_crypto,
                fiat_amount=part_fiat,
                rate=rate,
                requisites=requisites,
                sub_token=sub_token,
                callback_url=callback_url,
                group_id=group_id,
                part_index=1 if group_id else None,
                parts_count=len(parts),
                apply_remainder_credit=remainder_credit,
                exchange_discount_id=exchange_discount_id,
                amount_currency=amount_currency,
            )
            result["mode"] = plan.mode
            result["parts"] = parts
            result["parts_count"] = len(parts)
            return result
        except ValueError as e:
            if str(e) == "NO_BILL":
                last_err = e
                break
            raise
        except asyncpg.UniqueViolationError:
            continue
    raise ValueError(last_err or "Не удалось создать заявку")


async def handle_order_paid_side_effects(
    order_id: str,
    bot=None,
    *,
    create_payin_order_fn=None,
    cancel_payin_fn=None,
    generate_order_id_fn=None,
) -> None:
    """Следующая часть split + уведомление пользователю."""
    next_part = await on_part_paid(order_id)
    if not next_part:
        return
    if not create_payin_order_fn:
        from handlers.exchange_flow import (
            create_payin_order,
            cancel_order_merchant,
            generate_local_order_id,
        )
        create_payin_order_fn = create_payin_order
        cancel_payin_fn = cancel_order_merchant
        generate_order_id_fn = generate_local_order_id

    group = next_part["group"]
    gid = next_part["group_id"]
    next_idx = next_part["part_index"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE group_id = $1 AND part_index = $2
              AND status NOT IN ('CANCELED', 'EXPIRED')
            LIMIT 1
            """,
            gid,
            next_idx,
        )
    if exists:
        return

    try:
        result = await create_buy_part_order(
            create_payin_order_fn=create_payin_order_fn,
            cancel_payin_fn=cancel_payin_fn,
            order_id=generate_order_id_fn(),
            user_id=int(group["user_id"]),
            crypto=group["crypto"],
            crypto_amount=await part_crypto_amount(group, next_part["part_fiat"]),
            fiat_amount=next_part["part_fiat"],
            rate=float(group["rate"]),
            requisites=group["requisites"],
            sub_token=group["sub_token"] or "CARDRUB",
            callback_url=(config_rates.MERCHANT.get("callback_url") or "").strip(),
            group_id=next_part["group_id"],
            part_index=next_part["part_index"],
            parts_count=int(group["parts_count"]),
        )
        uid = int(group["user_id"])
        from services.buy_payment_prompt import send_buy_payment_prompt
        from services.db import get_order

        order = await get_order(result["order_id"]) or {
            "order_id": result["order_id"],
            "fiat_amount": result["fiat_amount"],
            "crypto": group["crypto"],
            "payment_snapshot": {"bill": result.get("bill") or {}},
        }
        if bot:
            await send_buy_payment_prompt(
                bot,
                dict(order),
                chat_id=uid,
                title=(
                    f"✅ Платёж {next_part['part_index'] - 1} из {group['parts_count']} получен.\n"
                    f"Перейдите к платежу {next_part['part_index']}:"
                ),
            )
        else:
            import requests
            from services import config_rates as cfg
            from services.buy_payment_prompt import (
                format_buy_payment_html,
                payment_markups_for_order,
            )

            text = format_buy_payment_html(
                dict(order),
                title=(
                    f"✅ Платёж {next_part['part_index'] - 1} из {group['parts_count']} получен.\n"
                    f"Перейдите к платежу {next_part['part_index']}:"
                ),
            )
            reply_kb, inline_kb = payment_markups_for_order(dict(order))
            url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(
                url,
                json={"chat_id": uid, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            if inline_kb:
                # inline via Bot API needs reply_markup as JSON — skip if no bot instance
                pass
    except Exception as e:
        logger.warning("next part creation failed: %s", e)
        await _alert_split_part_failure(order_id, next_part, e)


async def _alert_split_part_failure(
    order_id: str, next_part: dict, err: Exception
) -> None:
    import html

    from services import config_rates as cfg

    chat_id = cfg.reports_group_id() or None
    if not chat_id:
        return
    gid = next_part.get("group_id")
    idx = next_part.get("part_index")
    text = (
        f"⚠️ <b>Не создана часть {idx} split-оплаты</b>\n\n"
        f"После заявки: <code>{html.escape(order_id)}</code>\n"
        f"Группа: <code>{gid}</code>\n"
        f"Ошибка: <code>{html.escape(str(err)[:500])}</code>"
    )
    try:
        import requests

        url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as notify_err:
        logger.warning("split failure admin alert: %s", notify_err)


async def notify_operator_request(bot, order_id: str, user_id: int, username: str | None, fiat_amount: float, crypto: str, sub_token: str) -> None:
    from services.config_rates import reports_group_id

    reports_gid = reports_group_id()
    if not reports_gid or not bot:
        return
    uname = f"@{username}" if username else f"id {user_id}"
    text = (
        f"🛎 <b>Заявка через оператора</b> <code>{order_id}</code>\n\n"
        f"👤 {uname}\n"
        f"💰 {fiat_amount:,.0f} ₽ · {crypto} · {sub_token}\n"
        f"Нет реквизитов мерчанта — клиент направлен к @focus_operator"
    ).replace(",", " ")
    await bot.send_message(chat_id=reports_gid, text=text, parse_mode="HTML")
